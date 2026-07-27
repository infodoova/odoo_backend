"""
Background job that fires scheduled reports.

Every 15 minutes it queries for ReportSchedule rows whose next_send_at is in
the past, generates a PDF via the AI agent, emails all recipients, then
advances next_send_at to the next occurrence.
"""

import asyncio
import base64
import logging
from datetime import datetime, timezone as tz
from pathlib import Path

logger = logging.getLogger(__name__)

_CHECK_INTERVAL_SECONDS = 60  # 1 minute


class ReportJobManager:
    _task: asyncio.Task = None
    _running: bool = False

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
                await cls._process_due_schedules()
            except Exception:
                logger.exception("ReportJobManager loop error")

            for _ in range(_CHECK_INTERVAL_SECONDS):
                if not cls._running:
                    break
                await asyncio.sleep(1)

    @staticmethod
    async def _process_due_schedules():
        from asgiref.sync import sync_to_async

        now = datetime.now(tz.utc)
        logger.info(f"ReportJobManager: checking due schedules at {now.isoformat()}")

        @sync_to_async
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

        logger.info(f"ReportJobManager: {len(schedules)} schedule(s) due — firing now")
        for schedule in schedules:
            await ReportJobManager._fire_schedule(schedule, now)

    @staticmethod
    async def _fire_schedule(schedule, now: datetime):
        from asgiref.sync import sync_to_async
        from odoo_app.models.report_schedule import ReportLog
        from doova_one_view.api.email.service import EmailService
        from doova_one_view.api.reports.utils import calculate_next_send
        from doova_one_view.api.agent.tools_refactored.reporting_v2 import generate_report_tool

        tenant_id = str(schedule.tenant.id) if schedule.tenant else None
        company_ids = schedule.companies if schedule.companies else None
        tenant_ids = schedule.tenants if schedule.tenants else None
        next_dt = calculate_next_send(schedule.frequency, now)

        # ── Claim immediately ────────────────────────────────────────────────
        # Advance next_send_at BEFORE any work so that a server restart or a
        # concurrent process cannot re-pick this schedule and send duplicates.
        # The WHERE clause on next_send_at acts as an optimistic lock:
        # if another process already claimed it, 0 rows match and we bail out.
        @sync_to_async
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

        try:
            # 0. Fast-fail check: If there are recipients, ensure email is configured
            if schedule.recipients:
                from django.conf import settings
                if not getattr(settings, 'EMAIL_HOST_USER', None):
                    logger.error(f"ReportJobManager: EMAIL_HOST_USER is missing. Aborting schedule {schedule.id} to save AI credits.")
                    # Log failure early
                    from asgiref.sync import sync_to_async
                    from odoo_app.models.report_schedule import ReportLog
                    @sync_to_async
                    def _save_early_failure():
                        ReportLog.objects.create(schedule=schedule, status='failed', error_message='SMTP credentials not configured')
                    await _save_early_failure()
                    return

            # 1. Build AI-generated report content using the user's prompt
            custom_content = await ReportJobManager._build_analysis(
                tenant_id, schedule.report_type, company_ids, schedule.prompt, tenant_ids=tenant_ids
            )

            # 2. Generate PDF
            result = await sync_to_async(generate_report_tool)(
                tenant_id=tenant_id,
                company_ids=company_ids,
                custom_content=custom_content,
                tenant_ids=tenant_ids,
            )
            filename = result['filename']

            # 3. Encode PDF
            pdf_path = Path('reports') / filename
            pdf_b64 = base64.b64encode(pdf_path.read_bytes()).decode()
            attachment = {
                "filename": filename,
                "content": pdf_b64,
                "contentType": "application/pdf",
            }

            # 4. Email each recipient
            subject = _build_subject(schedule)
            html_body = _build_email_body(schedule)
            for email in schedule.recipients:
                try:
                    await EmailService.send_report_email(
                        to=email,
                        subject=subject,
                        html_body=html_body,
                        attachments=[attachment],
                    )
                except Exception as email_err:
                    logger.warning(f"Could not send email to {email}: {email_err}")

            # 5. Record last_sent_at — next_send_at was already advanced in _claim
            @sync_to_async
            def _save_success():
                schedule.last_sent_at = now
                schedule.save(update_fields=['last_sent_at'])
                ReportLog.objects.create(schedule=schedule, status='sent', filename=filename)

            await _save_success()
            logger.info(f"Report sent for schedule {schedule.id}. Next: {next_dt}")

        except Exception as e:
            error_msg = str(e)
            logger.exception(f"Failed to fire schedule {schedule.id}")

            # next_send_at already advanced — just log the failure
            @sync_to_async
            def _save_failure():
                ReportLog.objects.create(
                    schedule=schedule,
                    status='failed',
                    error_message=error_msg,
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

        if company_ids and len(company_ids) > 0:
            company_ctx = f"for selected companies {company_ids}"
        else:
            company_ctx = "across all companies"

        default_prompt = (
            f"<report_criteria>\n"
            f"Generate a comprehensive {report_type} business report covering:\n"
            f"1. Sales performance and revenue breakdown.\n"
            f"2. Top products and top customers.\n"
            f"3. Financial health score, receivables, and payables.\n"
            f"4. Profit & loss overview.\n"
            f"5. Any notable operational anomalies or risks.\n"
            f"Focus on actionable insights and clear trend analysis.\n"
            f"</report_criteria>"
        )

        full_prompt = (
            f"<role>\n"
            f"You are an elite automated reporting AI and financial analyst, generating a highly structured {report_type} report {company_ctx}.\n"
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


def _get_schedule_tenant_name(schedule) -> str:
    if schedule.tenants and len(schedule.tenants) > 0:
        try:
            from odoo_app.models.tenant import Tenant
            tenants = list(Tenant.objects.filter(id__in=schedule.tenants))
            if tenants:
                return ", ".join(t.name for t in tenants)
        except Exception:
            pass
    return schedule.tenant.name if schedule.tenant else "Your Business"


def _build_subject(schedule) -> str:
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
    tname = _get_schedule_tenant_name(schedule)
    return f"Your {label} Business Report — {tname}"


def _build_email_body(schedule) -> str:
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
    tname = _get_schedule_tenant_name(schedule)
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
