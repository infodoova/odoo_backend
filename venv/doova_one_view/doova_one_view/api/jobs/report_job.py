"""
Background job that fires scheduled reports.

Every 15 minutes it queries for ReportSchedule rows whose next_send_at is in
the past, generates a PDF via the AI agent, emails all recipients, then
advances next_send_at to the next occurrence.
"""

import asyncio
import base64
import logging
import time
from datetime import datetime, timezone as tz
from pathlib import Path
from django.db import close_old_connections
from doova_one_view.api.common.utils import db_sync_to_async

logger = logging.getLogger(__name__)

_CHECK_INTERVAL_SECONDS = 60  # 1 minute


def cleanup_old_reports(retention_days: int = 90, reports_dir: str | None = None) -> int:
    """
    Automated PDF retention cleanup.
    Deletes report PDF files modified older than retention_days.
    Returns the count of deleted files.
    """
    if reports_dir is None or reports_dir == "reports":
        from django.conf import settings
        dir_path = Path(getattr(settings, "REPORTS_DIR", Path("reports")))
    else:
        dir_path = Path(reports_dir)

    if not dir_path.exists() or not dir_path.is_dir():
        return 0


    now_ts = time.time()
    cutoff_ts = now_ts - (retention_days * 86400)
    deleted_cnt = 0

    for file_path in dir_path.glob("*.pdf"):
        try:
            if file_path.stat().st_mtime < cutoff_ts:
                file_path.unlink()
                deleted_cnt += 1
                logger.info(f"PDF Retention Cleanup: deleted old report {file_path.name}")
        except Exception as e:
            logger.warning(f"Failed to delete old report file {file_path}: {e}")

    return deleted_cnt


class ReportJobManager:
    _task: asyncio.Task = None
    _running: bool = False
    _last_cleanup_ts: float = 0.0

    @classmethod
    async def start(cls):
        if cls._running:
            return
        cls._running = True
        cls._task = asyncio.create_task(cls._run_loop())
        logger.info("ReportJobManager started (interval: 15 min)")

    @classmethod
    async def stop(cls):
        cls._running = False
        if cls._task:
            cls._task.cancel()
            try:
                await cls._task
            except asyncio.CancelledError:
                pass
        logger.info("ReportJobManager stopped")

    @classmethod
    async def _run_loop(cls):
        logger.info("ReportJobManager loop started — running initial check immediately")
        while cls._running:
            try:
                close_old_connections()
                await cls._process_due_schedules()

                # Run PDF retention cleanup every 24 hours (86400 seconds)
                now_ts = time.time()
                if now_ts - cls._last_cleanup_ts >= 86400:
                    cls._last_cleanup_ts = now_ts
                    await asyncio.to_thread(cleanup_old_reports, retention_days=90)
            except Exception:
                logger.exception("ReportJobManager loop error")

            for _ in range(_CHECK_INTERVAL_SECONDS):
                if not cls._running:
                    break
                await asyncio.sleep(1)

    @staticmethod
    async def _process_due_schedules():
        close_old_connections()
        now = datetime.now(tz.utc)
        logger.info(f"ReportJobManager: checking due schedules at {now.isoformat()}")

        @db_sync_to_async
        def _get_due():
            from odoo_app.models.report_schedule import ReportSchedule
            return list(
                ReportSchedule.objects.filter(
                    next_send_at__lte=now,
                    is_enabled=True,
                ).select_related('tenant')
            )

        schedules = await _get_due()

        if not schedules:
            logger.info("ReportJobManager: no due schedules found")
            return

        logger.info(f"ReportJobManager: {len(schedules)} schedule(s) due — firing concurrently")
        sem = asyncio.Semaphore(5)

        async def _run_bounded(sched):
            async with sem:
                try:
                    await ReportJobManager._fire_schedule(sched, now)
                except Exception as err:
                    logger.exception(f"ReportJobManager: error firing schedule {sched.id}: {err}")

        await asyncio.gather(*[_run_bounded(s) for s in schedules], return_exceptions=True)

    @staticmethod
    async def _fire_schedule(schedule, now: datetime):
        from odoo_app.models.report_schedule import ReportLog
        from doova_one_view.api.email.service import EmailService
        from doova_one_view.api.reports.utils import calculate_next_send
        from doova_one_view.api.agent.tools_refactored.reporting_v2 import generate_report_tool

        tenant_id = str(schedule.tenant_id) if schedule.tenant_id else None
        company_ids = schedule.companies if schedule.companies else None
        tenant_ids = schedule.tenants if schedule.tenants else None
        next_dt = calculate_next_send(schedule.frequency, now)

        # ── Claim immediately ────────────────────────────────────────────────
        # Advance next_send_at BEFORE any work so that a server restart or a
        # concurrent process cannot re-pick this schedule and send duplicates.
        # The WHERE clause on next_send_at acts as an optimistic lock:
        # if another process already claimed it, 0 rows match and we bail out.
        @db_sync_to_async
        def _claim():
            from odoo_app.models.report_schedule import ReportSchedule
            return ReportSchedule.objects.filter(
                id=schedule.id,
                next_send_at=schedule.next_send_at,
            ).update(next_send_at=next_dt)

        claimed = await _claim()
        if not claimed:
            logger.warning(f"ReportJobManager: schedule {schedule.id} already claimed — skipping")
            return

        start_time = time.time()
        error_category = "unknown"

        try:
            # 0. Fast-fail check: If there are recipients, ensure email is configured
            if schedule.recipients:
                from django.conf import settings
                if not getattr(settings, 'EMAIL_HOST_USER', None):
                    logger.error(f"ReportJobManager: EMAIL_HOST_USER is missing. Aborting schedule {schedule.id} to save AI credits.")
                    error_msg = "SMTP credentials not configured"
                    duration_sec = round(time.time() - start_time, 2)
                    
                    @db_sync_to_async
                    def _save_early_failure():
                        schedule.consecutive_failures += 1
                        schedule.last_error = error_msg
                        if schedule.consecutive_failures >= 3:
                            schedule.is_enabled = False
                            schedule.paused_reason = f"Auto-disabled after {schedule.consecutive_failures} consecutive failures: {error_msg}"
                            logger.critical(f"ReportJobManager: Circuit breaker tripped for schedule {schedule.id} — auto-disabled")
                        schedule.save(update_fields=['consecutive_failures', 'last_error', 'is_enabled', 'paused_reason', 'updated_at'])

                        ReportLog.objects.create(
                            schedule=schedule,
                            status='failed',
                            error_message=error_msg,
                            error_category='smtp_missing',
                            duration_seconds=duration_sec,
                        )
                    await _save_early_failure()
                    return

            # 1. Fetch tenant-specific configurable thresholds
            from doova_one_view.api.agent.thresholds import get_tenant_thresholds
            from doova_one_view.api.agent.citation_validator import CitationValidator
            from doova_one_view.api.agent.completeness import CompletenessEvaluator
            thresholds = await db_sync_to_async(get_tenant_thresholds)(tenant_id)
            min_completeness = thresholds.get("min_completeness_threshold_pct", 90.0)

            # 2. Build AI-generated report content using the user's prompt
            try:
                custom_content = await ReportJobManager._build_analysis(
                    tenant_id, schedule.report_type, company_ids, schedule.prompt, tenant_ids=tenant_ids
                )
            except Exception as ai_err:
                error_category = "ai_failure"
                raise ai_err

            # 3. Programmatic Citation-Grounding Verification Gate
            citations = CitationValidator.extract_citations_from_text(custom_content)
            if citations:
                from doova_one_view.api.agent.tools_refactored.sales import get_sales_summary_tool
                from doova_one_view.api.agent.tools_refactored.finance import calculate_pnl_tool
                ground_truth = {}
                try:
                    pnl_data = await db_sync_to_async(calculate_pnl_tool)(tenant_id=tenant_id, company_ids=company_ids)
                    if isinstance(pnl_data, dict):
                        ground_truth.update(pnl_data)
                except Exception:
                    pass

                val_res = CitationValidator.validate_citations(
                    citations, ground_truth=ground_truth, tolerance_pct=thresholds.get("po_matching_tolerance_pct", 1.0)
                )

                if not val_res["is_valid"]:
                    logger.warning(f"ReportJobManager: Citations ungrounded for schedule {schedule.id} — attempting repair retry")
                    # 1-Step Repair Retry
                    try:
                        repair_prompt = (schedule.prompt or "") + "\n\n" + (val_res["repair_prompt"] or "")
                        custom_content = await ReportJobManager._build_analysis(
                            tenant_id, schedule.report_type, company_ids, repair_prompt, tenant_ids=tenant_ids
                        )
                        citations_retry = CitationValidator.extract_citations_from_text(custom_content)
                        val_res_retry = CitationValidator.validate_citations(
                            citations_retry, ground_truth=ground_truth, tolerance_pct=thresholds.get("po_matching_tolerance_pct", 1.0)
                        )
                        if not val_res_retry["is_valid"]:
                            error_category = "validation_failed"
                            raise Exception(f"Citation validation failed after repair retry: {val_res_retry['violations']}")
                    except Exception as rep_err:
                        error_category = "validation_failed"
                        raise rep_err

            # 4. Generate PDF
            try:
                from doova_one_view.api.agent.report_classifier import ReportTypeClassifier
                resolved_report_type = ReportTypeClassifier.classify(
                    prompt=schedule.prompt or "",
                    custom_content=custom_content or "",
                    raw_type=schedule.report_type,
                )
                result = await db_sync_to_async(generate_report_tool)(
                    tenant_id=tenant_id,
                    company_ids=company_ids,
                    custom_content=custom_content,
                    tenant_ids=tenant_ids,
                    report_type=resolved_report_type,
                    prompt=schedule.prompt,
                )
                filename = result['filename']
            except Exception as pdf_err:
                error_category = "pdf_failure"
                raise pdf_err

            # 3. Encode PDF & measure size
            from django.conf import settings
            reports_dir = Path(getattr(settings, "REPORTS_DIR", Path("reports")))
            pdf_path = reports_dir / filename
            pdf_bytes = pdf_path.read_bytes()
            pdf_size_bytes = len(pdf_bytes)
            pdf_b64 = base64.b64encode(pdf_bytes).decode()

            attachment = {
                "filename": filename,
                "content": pdf_b64,
                "contentType": "application/pdf",
            }

            # 4. Email each recipient with backoff retry
            tname = await _get_schedule_tenant_name(schedule)
            subject = _build_subject(schedule, tname)
            html_body = _build_email_body(schedule, tname)
            sent_count = 0
            email_errors = []

            for email in schedule.recipients:
                try:
                    await EmailService.send_report_email(
                        to=email,
                        subject=subject,
                        html_body=html_body,
                        attachments=[attachment],
                        max_retries=3,
                    )
                    sent_count += 1
                except Exception as email_err:
                    logger.error(f"Failed to send report email to {email}: {email_err}")
                    email_errors.append(f"{email}: {email_err}")

            if sent_count == 0 and schedule.recipients:
                error_category = "email_failure"
                raise Exception(f"Failed to deliver report email to any recipient after retries: {'; '.join(email_errors)}")

            duration_sec = round(time.time() - start_time, 2)

            # 5. Success reset & log record
            @db_sync_to_async
            def _save_success():
                schedule.last_sent_at = now
                schedule.consecutive_failures = 0
                schedule.last_error = None
                schedule.paused_reason = None
                schedule.save(update_fields=['last_sent_at', 'consecutive_failures', 'last_error', 'paused_reason', 'updated_at'])

                ReportLog.objects.create(
                    schedule=schedule,
                    status='sent',
                    filename=filename,
                    duration_seconds=duration_sec,
                    pdf_size_bytes=pdf_size_bytes,
                )

            await _save_success()
            logger.info(f"Report sent for schedule {schedule.id} in {duration_sec}s ({pdf_size_bytes} bytes). Next: {next_dt}")

        except Exception as e:
            error_msg = str(e)
            duration_sec = round(time.time() - start_time, 2)
            logger.exception(f"Failed to fire schedule {schedule.id} ({error_category}) after {duration_sec}s")

            # Increment consecutive failures & check circuit breaker
            @db_sync_to_async
            def _save_failure():
                schedule.consecutive_failures += 1
                schedule.last_error = error_msg[:1000]
                if schedule.consecutive_failures >= 3:
                    schedule.is_enabled = False
                    schedule.paused_reason = f"Auto-disabled after {schedule.consecutive_failures} consecutive failures: {error_msg[:150]}"
                    logger.critical(f"ReportJobManager: Circuit breaker tripped for schedule {schedule.id} — auto-disabled after 3 consecutive failures")

                schedule.save(update_fields=['consecutive_failures', 'last_error', 'is_enabled', 'paused_reason', 'updated_at'])

                ReportLog.objects.create(
                    schedule=schedule,
                    status='failed',
                    error_message=error_msg,
                    error_category=error_category,
                    duration_seconds=duration_sec,
                )

            await _save_failure()


    @staticmethod
    async def _build_analysis(
        tenant_id: str,
        report_type: str,
        company_ids: list | None,
        user_prompt: str,
        tenant_ids: list | None = None,
    ) -> str:
        """
        Call the LangChain AI agent with the user's prompt to generate detailed
        report content in Markdown, which is then rendered into the PDF.
        """
        from doova_one_view.api.agent.langchain_agent import DoovaLangChainAgent
        from doova_one_view.api.agent.tools_refactored.template_registry import TEMPLATE_REGISTRY, get_template_metadata
        from doova_one_view.api.agent.report_classifier import ReportTypeClassifier

        if company_ids and len(company_ids) > 0:
            company_ctx = f"for selected companies {company_ids}"
        else:
            company_ctx = "across all companies"

        canonical_type = ReportTypeClassifier.normalize_report_type(report_type)
        meta = get_template_metadata(canonical_type)
        domain_label = meta.get("title", f"{canonical_type.capitalize()} Report")
        domain_guidance = meta.get("subtitle", "Comprehensive business performance analysis.")

        default_prompt = (
            f"<report_criteria>\n"
            f"Generate a comprehensive {domain_label} ({domain_guidance}) covering:\n"
            f"1. Core domain KPIs, vital signs, and operational benchmarks.\n"
            f"2. Major performance drivers, volume trends, and variances.\n"
            f"3. Identified operational or financial risks and anomalies.\n"
            f"4. Concrete, prioritized strategic management recommendations.\n"
            f"Focus on actionable insights grounded in posted Odoo data.\n"
            f"</report_criteria>"
        )

        full_prompt = (
            f"<role>\n"
            f"You are an automated reporting AI and business analyst, generating a highly structured {domain_label} {company_ctx}.\n"
            f"Your expertise is in synthesizing complex business data into clear, actionable executive summaries.\n"
            f"</role>\n\n"
            f"<instructions>\n"
            f"1. Use all relevant tools (sales, finance, inventory, receivables, etc.) to gather real data and context.\n"
            f"2. Carefully analyze the data according to the criteria defined in the <user_request>.\n"
            f"3. Do NOT call the create_report or get_latest_report tools.\n"
            f"4. Before writing your final report, use <thinking> tags to internally plan your structure, determine the necessary tool calls, and compute key insights.\n"
            f"5. After thinking, output ONLY the final report matching the strict format defined in <output_format>.\n"
            f"</instructions>\n\n"
            f"<output_format>\n"
            f"Your response will be converted directly into a PDF report. Follow these formatting rules strictly:\n"
            f"- Do NOT include any preamble like 'Here is your report' — start directly with the first header.\n"
            f"- Use ## for main section headers (e.g., ## Revenue Performance).\n"
            f"- Use ### for subsection headers.\n"
            f"- Use Markdown tables with | for tabular data (e.g., top products, top customers).\n"
            f"- Use - bullet points for lists.\n"
            f"- Use **bold** to highlight key numbers and metrics.\n"
            f"- To include a chart, output a fenced code block with language `chart` (i.e. ```chart). Inside, provide a JSON object with exactly these keys: `chart_type` ('bar', 'line', or 'pie'), `title` (string), `labels` (list of strings), and `values` (list of numbers).\n"
            f"</output_format>\n\n"
            f"<user_request>\n"
            f"{user_prompt.strip() if user_prompt and user_prompt.strip() else default_prompt}\n"
            f"</user_request>"
        )

        try:
            agent = DoovaLangChainAgent()
            result = await asyncio.to_thread(agent.run, full_prompt, tenant_id, company_ids=company_ids, tenant_ids=tenant_ids)
            return result
        except Exception as e:
            logger.exception(f"AI agent failed for schedule — using fallback content")
            return (
                f"## Automated {report_type.capitalize()} Report\n\n"
                f"The AI agent encountered an error generating this report: {e}\n\n"
                f"Please check server logs for details."
            )


@db_sync_to_async
def _get_schedule_tenant_name(schedule) -> str:
    if schedule.tenants and len(schedule.tenants) > 0:
        try:
            from odoo_app.models.tenant import Tenant
            tenants = list(Tenant.objects.filter(id__in=schedule.tenants))
            if tenants:
                return ", ".join(t.name for t in tenants)
        except Exception:
            pass
    try:
        return schedule.tenant.name if schedule.tenant else "Your Business"
    except Exception:
        return "Your Business"


def _build_subject(schedule, tname: str = "Your Business") -> str:
    freq_labels = {
        'daily':       'Daily',
        'weekly':      'Weekly',
        'biweekly':    'Bi-Weekly',
        'monthly':     'Monthly',
        'quarterly':   'Quarterly',
        'semi_annual': 'Semi-Annual',
        'annual':      'Annual',
    }
    label = freq_labels.get(schedule.frequency, schedule.frequency.capitalize())
    return f"Your {label} Business Report — {tname}"


def _build_email_body(schedule, tname: str = "Your Business") -> str:
    freq_labels = {
        'daily':       'daily',
        'weekly':      'weekly',
        'biweekly':    'bi-weekly',
        'monthly':     'monthly',
        'quarterly':   'quarterly',
        'semi_annual': 'semi-annual',
        'annual':      'annual',
    }
    label = freq_labels.get(schedule.frequency, schedule.frequency)
    company_note = (
        "all companies" if not schedule.companies
        else f"{len(schedule.companies)} selected company/ies"
    )
    return f"""
    <div style="font-family: Arial, sans-serif; max-width: 600px; margin: auto;">
        <h2 style="color: #1a3d5c;">Your Scheduled Business Report</h2>
        <p>Hi,</p>
        <p>
            Please find attached your <strong>{label}</strong> business report
            for <strong>{tname}</strong> ({company_note}).
        </p>
        <p>This report was automatically generated and sent by <strong>Nexus</strong>.</p>
        <hr style="border-color: #eee;" />
        <p style="color: #999; font-size: 12px;">
            To manage your report schedule, visit the Reports section in Nexus.
        </p>
    </div>
    """

