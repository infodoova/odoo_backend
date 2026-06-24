"""
Background job that fires scheduled alert checks daily.

Every hour it queries for AlertSchedule rows whose next_check_at is in the past,
runs the AI agent to detect unusual activity, sends alert emails only when
anomalies are found, then advances next_check_at by 24 hours.

System-default schedules run for every tenant automatically.
"""

import asyncio
import logging
from datetime import datetime, timezone as tz, timedelta

logger = logging.getLogger(__name__)

_CHECK_INTERVAL_SECONDS = 60 * 60  # 1 hour

DEFAULT_ALERT_PROMPT = (
    "Check ALL available business data (sales, purchases, inventory, finance, receivables, payables) "
    "from the last 24 hours. Look specifically for: unusual spikes or drops in revenue (>20%), "
    "large unexpected expenses, overdue invoices past 30 days, abnormal inventory movements, "
    "sudden changes in order volumes, duplicate or suspicious transactions, and any other "
    "anomalies that a CFO or operations manager should know about immediately."
)


class AlertJobManager:
    _task: asyncio.Task = None
    _running: bool = False

    @classmethod
    async def start(cls):
        if cls._running:
            return
        cls._running = True
        cls._task = asyncio.create_task(cls._run_loop())
        logger.info("AlertJobManager started (interval: 1 hour)")

    @classmethod
    async def stop(cls):
        cls._running = False
        if cls._task:
            cls._task.cancel()
            try:
                await cls._task
            except asyncio.CancelledError:
                pass
        logger.info("AlertJobManager stopped")

    @classmethod
    async def _run_loop(cls):
        logger.info("AlertJobManager loop started — running initial check immediately")
        while cls._running:
            try:
                await cls._process_due_schedules()
            except Exception:
                logger.exception("AlertJobManager loop error")

            for _ in range(_CHECK_INTERVAL_SECONDS):
                if not cls._running:
                    break
                await asyncio.sleep(1)

    @staticmethod
    async def _process_due_schedules():
        from asgiref.sync import sync_to_async

        now = datetime.now(tz.utc)
        logger.info(f"AlertJobManager: checking due alert schedules at {now.isoformat()}")

        @sync_to_async
        def _get_due():
            from odoo_app.models.alert_schedule import AlertSchedule
            return list(
                AlertSchedule.objects.filter(
                    next_check_at__lte=now,
                    is_enabled=True,
                ).select_related('tenant')
            )

        schedules = await _get_due()

        if not schedules:
            logger.info("AlertJobManager: no due alert schedules")
            return

        logger.info(f"AlertJobManager: {len(schedules)} schedule(s) due")

        for schedule in schedules:
            if schedule.is_system_default:
                # Run for every active tenant
                tenants = await _get_all_tenants()
                for tenant_id in tenants:
                    await AlertJobManager.run_check(
                        schedule=schedule,
                        tenant_id=tenant_id,
                        send_email=True,
                        is_instant=False,
                    )
            else:
                tenant_id = str(schedule.tenant_id) if schedule.tenant_id else None
                if tenant_id:
                    await AlertJobManager.run_check(
                        schedule=schedule,
                        tenant_id=tenant_id,
                        send_email=True,
                        is_instant=False,
                    )


async def _get_all_tenants() -> list[str]:
    from asgiref.sync import sync_to_async

    @sync_to_async
    def _fetch():
        from odoo_app.models.tenant import Tenant
        return [str(t.id) for t in Tenant.objects.filter(is_active=True)]

    try:
        return await _fetch()
    except Exception:
        # Fall back if tenant has no is_active field
        @sync_to_async
        def _fetch_all():
            from odoo_app.models.tenant import Tenant
            return [str(t.id) for t in Tenant.objects.all()]
        return await _fetch_all()


# ---------------------------------------------------------------------------
# Core check logic — shared by background job AND instant run-now endpoint
# ---------------------------------------------------------------------------

async def _run_check_impl(
    schedule,
    tenant_id: str,
    send_email: bool,
    is_instant: bool,
) -> dict:
    from asgiref.sync import sync_to_async

    now = datetime.now(tz.utc)
    company_ids = schedule.companies if schedule.companies else None

    try:
        # 1. Run AI anomaly detection
        summary, has_anomalies = await _detect_anomalies(
            tenant_id=tenant_id,
            company_ids=company_ids,
            user_prompt=schedule.prompt,
        )

        # 2. Send email only if anomalies found AND email is requested
        alert_sent = False
        if has_anomalies and send_email and schedule.recipients:
            await _send_alert_email(schedule=schedule, tenant_id=tenant_id, summary=summary)
            alert_sent = True

        # 3. Advance next_check_at (only for scheduled runs, not instant)
        if not is_instant:
            @sync_to_async
            def _save_success():
                schedule.next_check_at = now + timedelta(days=1)
                schedule.last_checked_at = now
                schedule.save(update_fields=['next_check_at', 'last_checked_at'])
            await _save_success()

        # 4. Create log entry
        @sync_to_async
        def _log_success():
            from odoo_app.models.alert_schedule import AlertLog
            from odoo_app.models.tenant import Tenant
            tenant_obj = Tenant.objects.filter(id=tenant_id).first()
            log = AlertLog.objects.create(
                schedule=schedule,
                tenant=tenant_obj,
                status='completed',
                has_anomalies=has_anomalies,
                summary=summary,
                alert_sent=alert_sent,
            )
            return log.id

        log_id = await _log_success()
        logger.info(f"Alert check completed for schedule {schedule.id}, tenant {tenant_id}: anomalies={has_anomalies}")
        return {"has_anomalies": has_anomalies, "summary": summary, "alert_sent": alert_sent, "log_id": log_id}

    except Exception as e:
        error_msg = str(e)
        logger.exception(f"Alert check failed for schedule {schedule.id}, tenant {tenant_id}")

        if not is_instant:
            @sync_to_async
            def _advance_on_error():
                schedule.next_check_at = now + timedelta(days=1)
                schedule.save(update_fields=['next_check_at'])
            await _advance_on_error()

        @sync_to_async
        def _log_failure():
            from odoo_app.models.alert_schedule import AlertLog
            from odoo_app.models.tenant import Tenant
            tenant_obj = Tenant.objects.filter(id=tenant_id).first()
            log = AlertLog.objects.create(
                schedule=schedule,
                tenant=tenant_obj,
                status='failed',
                has_anomalies=False,
                error_message=error_msg,
            )
            return log.id

        log_id = await _log_failure()
        raise RuntimeError(error_msg)


# Attach to class for use from routes
AlertJobManager.run_check = staticmethod(_run_check_impl)


async def _detect_anomalies(
    tenant_id: str,
    company_ids: list | None,
    user_prompt: str,
) -> tuple[str, bool]:
    """
    Run the LangChain AI agent to detect unusual activity.

    Returns (summary: str, has_anomalies: bool).
    The agent must prefix its response with 'ALERT:' or 'OK:'.
    """
    from doova_one_view.api.agent.langchain_agent import DoovaLangChainAgent

    company_id = company_ids[0] if company_ids and len(company_ids) == 1 else None
    company_ctx = f"for Company ID {company_id}" if company_id else "across all companies"

    effective_prompt = user_prompt.strip() if user_prompt and user_prompt.strip() else DEFAULT_ALERT_PROMPT

    full_prompt = (
        f"You are a vigilance AI monitoring a business {company_ctx} for unusual or suspicious activity.\n\n"
        f"IMPORTANT: After gathering data with your tools, you MUST begin your response with exactly one of:\n"
        f"  'ALERT: <brief one-line summary>' — if you detect any unusual or concerning activity\n"
        f"  'OK: <brief one-line summary>' — if everything appears normal\n\n"
        f"Then provide detailed findings below that prefix line.\n\n"
        f"Use ALL relevant tools (sales, finance, inventory, receivables, etc.) to gather data "
        f"before making your assessment. Do NOT speculate — only flag actual data anomalies.\n\n"
        f"What to check:\n{effective_prompt}"
    )

    try:
        agent = DoovaLangChainAgent()
        result = await asyncio.to_thread(agent.run, full_prompt, tenant_id, company_id)
        result_stripped = result.strip()

        if result_stripped.upper().startswith("ALERT:"):
            # Extract everything after "ALERT:"
            summary = result_stripped[len("ALERT:"):].strip()
            return summary, True
        else:
            # "OK:" or anything else — no anomalies
            if result_stripped.upper().startswith("OK:"):
                summary = result_stripped[len("OK:"):].strip()
            else:
                summary = result_stripped
            return summary, False

    except Exception as e:
        logger.exception("AI anomaly detection failed")
        raise


async def _send_alert_email(schedule, tenant_id: str, summary: str):
    from doova_one_view.api.email.service import EmailService

    tenant_name = schedule.tenant.name if schedule.tenant else "Your Business"
    subject = f"ALERT: Unusual Activity Detected — {tenant_name}"
    company_note = (
        "all companies" if not schedule.companies
        else f"{len(schedule.companies)} selected company/ies"
    )

    # Split summary into headline + details
    lines = summary.split('\n', 1)
    headline = lines[0].strip()
    details_html = lines[1].replace('\n', '<br>') if len(lines) > 1 else ''

    html_body = f"""
    <div style="font-family: Arial, sans-serif; max-width: 600px; margin: auto;">
        <div style="background:#dc2626; padding:12px 20px; border-radius:6px 6px 0 0;">
            <h2 style="color:#fff; margin:0; font-size:18px;">⚠ Unusual Activity Detected</h2>
        </div>
        <div style="border:1px solid #fca5a5; border-top:none; padding:20px; border-radius:0 0 6px 6px;">
            <p style="color:#374151;">Hi,</p>
            <p style="color:#374151;">
                The daily alert check for <strong>{tenant_name}</strong> ({company_note})
                has detected unusual activity that requires your attention:
            </p>
            <div style="background:#fef2f2; border-left:4px solid #dc2626; padding:12px 16px; margin:16px 0;">
                <strong style="color:#991b1b;">{headline}</strong>
                {"<br><br>" + details_html if details_html else ""}
            </div>
            <p style="color:#374151;">
                Please log in to <strong>Doova OneView</strong> to review the details and take action.
            </p>
            <hr style="border-color:#fee2e2; margin:20px 0;" />
            <p style="color:#9ca3af; font-size:12px;">
                This alert was automatically generated by Doova OneView.
                To manage your alert schedules, visit the Alerts section.
            </p>
        </div>
    </div>
    """

    for email in schedule.recipients:
        await EmailService.send(
            to=email,
            subject=subject,
            html_body=html_body,
            priority="HIGH",
        )
