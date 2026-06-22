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

_CHECK_INTERVAL_SECONDS = 15 * 60  # 15 minutes


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
        from doova_one_view.api.agent.tools_refactored.reporting import generate_report_tool

        tenant_id = str(schedule.tenant.id)
        company_ids = schedule.companies if schedule.companies else None

        try:
            # 1. Build AI-generated report content using the user's prompt
            custom_content = await ReportJobManager._build_analysis(
                tenant_id, schedule.report_type, company_ids, schedule.prompt
            )

            # 2. Generate PDF
            result = await sync_to_async(generate_report_tool)(
                tenant_id=tenant_id,
                company_ids=company_ids,
                custom_content=custom_content,
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
                await EmailService.send_report_email(
                    to=email,
                    subject=subject,
                    html_body=html_body,
                    attachments=[attachment],
                )

            # 5. Advance next_send_at and log success
            next_dt = calculate_next_send(schedule.frequency, now)

            @sync_to_async
            def _save_success():
                schedule.next_send_at = next_dt
                schedule.last_sent_at = now
                schedule.save(update_fields=['next_send_at', 'last_sent_at'])
                ReportLog.objects.create(schedule=schedule, status='sent', filename=filename)

            await _save_success()
            logger.info(f"Report sent for schedule {schedule.id}. Next: {next_dt}")

        except Exception as e:
            error_msg = str(e)
            logger.exception(f"Failed to fire schedule {schedule.id}")

            @sync_to_async
            def _save_failure():
                from doova_one_view.api.reports.utils import calculate_next_send
                next_dt = calculate_next_send(schedule.frequency, now)
                schedule.next_send_at = next_dt
                schedule.save(update_fields=['next_send_at'])
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
    ) -> str:
        """
        Call the LangChain AI agent with the user's prompt to generate detailed
        report content in Markdown, which is then rendered into the PDF.
        """
        from doova_one_view.api.agent.langchain_agent import DoovaLangChainAgent

        company_id = company_ids[0] if company_ids and len(company_ids) == 1 else None
        company_ctx = f"for Company ID {company_id}" if company_id else "across all companies"

        default_prompt = (
            f"Generate a comprehensive {report_type} business report with all key metrics, "
            f"trends, and actionable insights. Cover: sales performance, revenue breakdown, "
            f"top products, top customers, financial health score, receivables, payables, "
            f"profit & loss, and any notable anomalies."
        )

        full_prompt = (
            f"You are generating an automated scheduled {report_type} PDF report {company_ctx}.\n\n"
            f"IMPORTANT FORMATTING RULES — your response will be converted directly to PDF:\n"
            f"- Use ## for main section headers (e.g. ## Revenue Performance)\n"
            f"- Use ### for subsection headers\n"
            f"- Use Markdown tables with | for tabular data (e.g. top products, top customers)\n"
            f"- Use - bullet points for lists\n"
            f"- Use **bold** to highlight key numbers and metrics\n"
            f"- Do NOT include any preamble like 'Here is your report' — start directly with content\n\n"
            f"Call ALL relevant tools first (sales, finance, inventory, receivables, etc.) "
            f"to gather real data, then write a thorough, structured report with actual numbers.\n\n"
            f"User's report request:\n{user_prompt.strip() if user_prompt and user_prompt.strip() else default_prompt}"
        )

        try:
            agent = DoovaLangChainAgent()
            result = await asyncio.to_thread(agent.run, full_prompt, tenant_id, company_id)
            return result
        except Exception as e:
            logger.exception(f"AI agent failed for schedule — using fallback content")
            return (
                f"## Automated {report_type.capitalize()} Report\n\n"
                f"The AI agent encountered an error generating this report: {e}\n\n"
                f"Please check server logs for details."
            )


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
    return f"Your {label} Business Report — {schedule.tenant.name}"


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
    return f"""
    <div style="font-family: Arial, sans-serif; max-width: 600px; margin: auto;">
        <h2 style="color: #1a3d5c;">Your Scheduled Business Report</h2>
        <p>Hi,</p>
        <p>
            Please find attached your <strong>{label}</strong> business report
            for <strong>{schedule.tenant.name}</strong> ({company_note}).
        </p>
        <p>This report was automatically generated and sent by <strong>Doova OneView</strong>.</p>
        <hr style="border-color: #eee;" />
        <p style="color: #999; font-size: 12px;">
            To manage your report schedule, visit the Reports section in Doova OneView.
        </p>
    </div>
    """
