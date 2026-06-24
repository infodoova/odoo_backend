"""
Background job that fires daily alert checks.

Every hour it queries AlertSchedule rows whose next_check_at is past,
runs the AI agent to detect unusual activity, sends alert emails only
when anomalies are found, then advances next_check_at by 24 hours.

System-default schedules (is_system_default=True) run for every tenant.
"""

import asyncio
import logging
import re
from datetime import datetime, timezone as tz, timedelta

logger = logging.getLogger(__name__)

_CHECK_INTERVAL_SECONDS = 60 * 60  # 1 hour

DEFAULT_ALERT_PROMPT = (
    "Check ALL available business data (sales, purchases, inventory, finance, "
    "receivables, payables) from the last 24 hours. Look for: unusual spikes or "
    "drops in revenue (>20%), large unexpected expenses, overdue invoices past "
    "30 days, abnormal inventory movements, sudden changes in order volumes, "
    "duplicate or suspicious transactions, and any other anomaly a CFO should "
    "know about immediately."
)


class AlertJobManager:
    _task: asyncio.Task = None
    _running: bool = False

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    @classmethod
    async def start(cls):
        if cls._running:
            return
        cls._running = True
        cls._task = asyncio.create_task(cls._run_loop())
        logger.info("AlertJobManager started (check interval: 1 hour)")

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
        logger.info("AlertJobManager loop started")
        while cls._running:
            try:
                await cls._process_due_schedules()
            except Exception:
                logger.exception("AlertJobManager: unhandled error in loop")
            for _ in range(_CHECK_INTERVAL_SECONDS):
                if not cls._running:
                    break
                await asyncio.sleep(1)

    # ------------------------------------------------------------------
    # Scheduled processing
    # ------------------------------------------------------------------

    @staticmethod
    async def _process_due_schedules():
        from asgiref.sync import sync_to_async

        now = datetime.now(tz.utc)
        logger.info(f"AlertJobManager: checking due schedules at {now.isoformat()}")

        @sync_to_async
        def _get_due():
            from odoo_app.models.alert_schedule import AlertSchedule
            return list(
                AlertSchedule.objects
                .filter(next_check_at__lte=now, is_enabled=True)
                .select_related('tenant')
            )

        schedules = await _get_due()
        if not schedules:
            logger.info("AlertJobManager: no due schedules")
            return

        logger.info(f"AlertJobManager: {len(schedules)} schedule(s) due")
        for schedule in schedules:
            if schedule.is_system_default:
                tenant_ids = await AlertJobManager._get_all_tenant_ids()
                for tid in tenant_ids:
                    try:
                        await AlertJobManager.run_check(
                            schedule=schedule,
                            tenant_id=tid,
                            send_email=True,
                            is_instant=False,
                        )
                    except Exception:
                        # already logged + AlertLog written inside run_check
                        logger.error(
                            f"AlertJobManager: cron check failed schedule={schedule.id} tenant={tid}"
                        )
            else:
                if schedule.tenant_id:
                    try:
                        await AlertJobManager.run_check(
                            schedule=schedule,
                            tenant_id=str(schedule.tenant_id),
                            send_email=True,
                            is_instant=False,
                        )
                    except Exception:
                        logger.error(
                            f"AlertJobManager: cron check failed schedule={schedule.id} tenant={schedule.tenant_id}"
                        )

    @staticmethod
    async def _get_all_tenant_ids() -> list:
        from asgiref.sync import sync_to_async

        @sync_to_async
        def _fetch():
            from odoo_app.models.tenant import Tenant
            return [str(t.id) for t in Tenant.objects.all()]

        return await _fetch()

    # ------------------------------------------------------------------
    # Core check — used by both the scheduled loop and the run-now route
    # ------------------------------------------------------------------

    @staticmethod
    async def run_check(
        schedule,
        tenant_id: str,
        send_email: bool,
        is_instant: bool,
    ) -> dict:
        """
        Run the AI anomaly check for one (schedule, tenant) pair.

        Returns:
            { has_anomalies, summary, alert_sent, log_id }

        On failure, logs the error, writes a failed AlertLog, and
        re-raises so callers can decide how to surface the error.
        """
        from asgiref.sync import sync_to_async

        now = datetime.now(tz.utc)
        company_ids = schedule.companies if schedule.companies else None

        try:
            summary, has_anomalies = await AlertJobManager._detect_anomalies(
                tenant_id=tenant_id,
                company_ids=company_ids,
                user_prompt=schedule.prompt,
            )

            alert_sent = False
            if has_anomalies and send_email and schedule.recipients:
                await AlertJobManager._send_alert_email(
                    schedule=schedule,
                    tenant_id=tenant_id,
                    summary=summary,
                )
                alert_sent = True

            if not is_instant:
                @sync_to_async
                def _advance():
                    schedule.next_check_at = now + timedelta(days=1)
                    schedule.last_checked_at = now
                    schedule.save(update_fields=['next_check_at', 'last_checked_at'])
                await _advance()

            @sync_to_async
            def _log_success():
                from odoo_app.models.alert_schedule import AlertLog
                from odoo_app.models.tenant import Tenant
                tenant_obj = Tenant.objects.filter(id=tenant_id).first()
                return AlertLog.objects.create(
                    schedule=schedule,
                    tenant=tenant_obj,
                    status='completed',
                    has_anomalies=has_anomalies,
                    summary=summary,
                    alert_sent=alert_sent,
                ).id

            log_id = await _log_success()
            logger.info(
                f"AlertJobManager: check done schedule={schedule.id} "
                f"tenant={tenant_id} anomalies={has_anomalies}"
            )
            return {
                "has_anomalies": has_anomalies,
                "summary": summary,
                "alert_sent": alert_sent,
                "log_id": log_id,
            }

        except Exception as exc:
            error_msg = str(exc)
            logger.exception(
                f"AlertJobManager: check failed schedule={schedule.id} tenant={tenant_id}"
            )

            if not is_instant:
                @sync_to_async
                def _advance_on_err():
                    schedule.next_check_at = now + timedelta(days=1)
                    schedule.save(update_fields=['next_check_at'])
                try:
                    await _advance_on_err()
                except Exception:
                    pass

            @sync_to_async
            def _log_failure():
                from odoo_app.models.alert_schedule import AlertLog
                from odoo_app.models.tenant import Tenant
                tenant_obj = Tenant.objects.filter(id=tenant_id).first()
                return AlertLog.objects.create(
                    schedule=schedule,
                    tenant=tenant_obj,
                    status='failed',
                    has_anomalies=False,
                    error_message=error_msg,
                ).id

            try:
                await _log_failure()
            except Exception:
                pass

            raise

    # ------------------------------------------------------------------
    # AI detection
    # ------------------------------------------------------------------

    @staticmethod
    async def _detect_anomalies(
        tenant_id: str,
        company_ids: list | None,
        user_prompt: str,
    ) -> tuple:
        """
        Returns (summary: str, has_anomalies: bool).

        The LangChain agent must start its response with:
          'ALERT: <headline>'  — anomaly detected
          'OK: <headline>'     — all clear
        """
        from doova_one_view.api.agent.langchain_agent import DoovaLangChainAgent

        company_id = (
            company_ids[0]
            if company_ids and len(company_ids) == 1
            else None
        )
        company_ctx = (
            f"for Company ID {company_id}" if company_id else "across all companies"
        )
        effective_prompt = (
            user_prompt.strip()
            if user_prompt and user_prompt.strip()
            else DEFAULT_ALERT_PROMPT
        )

        full_prompt = (
            f"You are a vigilance AI monitoring a business {company_ctx} "
            f"for unusual or suspicious activity.\n\n"
            f"Use all relevant tools (sales, finance, inventory, receivables, trial balance, "
            f"detect_anomalies) before making your assessment.\n\n"
            f"CRITICAL FORMAT RULE: The very first line of your STRATEGIC RECOMMENDATION "
            f"section MUST be exactly one of:\n"
            f"  ALERT: <one-line headline>   — if you found unusual or concerning activity\n"
            f"  OK: <one-line headline>       — if everything looks normal\n"
            f"Do not add any words before ALERT: or OK: on that line. "
            f"Follow it with your full detailed findings.\n\n"
            f"Only flag genuine data anomalies — not missing data or date range issues.\n\n"
            f"What to check:\n{effective_prompt}"
        )

        agent = DoovaLangChainAgent()
        result = await asyncio.to_thread(agent.run, full_prompt, tenant_id, company_id)
        result = result.strip()

        # The agent system prompt forces every response to start with
        # "## CFO INTERNAL THOUGHT PROCESS" before "## STRATEGIC RECOMMENDATION",
        # so ALERT:/OK: can appear well past the first N characters.
        # Search the ENTIRE response for ALERT:/OK: at the start of any line.
        alert_match = re.search(r'^ALERT:\s*', result, re.IGNORECASE | re.MULTILINE)
        ok_match    = re.search(r'^OK:\s*',    result, re.IGNORECASE | re.MULTILINE)

        if alert_match:
            return result[alert_match.end():].strip(), True
        if ok_match:
            return result[ok_match.end():].strip(), False

        # No explicit prefix — strip the CFO thought process section if present
        # and return just the strategic recommendation as all-clear.
        rec_match = re.search(
            r'##\s*STRATEGIC\s+RECOMMENDATION\s*\n', result, re.IGNORECASE
        )
        if rec_match:
            return result[rec_match.end():].strip(), False
        return result, False

    # ------------------------------------------------------------------
    # Alert email
    # ------------------------------------------------------------------

    @staticmethod
    async def _send_alert_email(schedule, tenant_id: str, summary: str):
        from doova_one_view.api.email.service import EmailService

        tenant_name = schedule.tenant.name if schedule.tenant else "Your Business"
        subject = f"ALERT: Unusual Activity Detected — {tenant_name}"
        company_note = (
            "all companies"
            if not schedule.companies
            else f"{len(schedule.companies)} selected company/ies"
        )

        # Render markdown → HTML so tables, bold, headings display properly in email.
        # Fall back to plain <br>-separated text if the markdown package is missing.
        try:
            import markdown as _md
            summary_html = _md.markdown(summary, extensions=["tables", "nl2br"])
        except ImportError:
            summary_html = summary.replace('\n', '<br>')

        html_body = f"""
        <div style="font-family:Arial,sans-serif;max-width:640px;margin:auto;color:#374151;">
          <!-- Header banner -->
          <div style="background:#dc2626;padding:18px 24px;border-radius:8px 8px 0 0;">
            <h1 style="color:#fff;margin:0;font-size:18px;font-weight:700;">
              &#9888;&#65039; Unusual Activity Detected
            </h1>
            <p style="color:#fecaca;margin:4px 0 0;font-size:13px;">
              {tenant_name} &nbsp;·&nbsp; {company_note}
            </p>
          </div>

          <!-- Body -->
          <div style="border:1px solid #fca5a5;border-top:none;padding:24px;border-radius:0 0 8px 8px;background:#fff;">

            <p style="margin:0 0 16px;font-size:14px;line-height:1.5;">
              The daily alert check has detected unusual activity that requires your attention.
            </p>

            <!-- AI findings box -->
            <div style="
              background:#fef2f2;
              border:1px solid #fca5a5;
              border-left:4px solid #dc2626;
              border-radius:6px;
              padding:16px 20px;
              margin-bottom:20px;
              font-size:13px;
              line-height:1.6;
            ">
              <style scoped>
                table {{border-collapse:collapse;width:100%;font-size:12px;margin:8px 0}}
                th {{text-align:left;padding:6px 8px;border-bottom:2px solid #fca5a5;font-weight:600;color:#7f1d1d}}
                td {{padding:5px 8px;border-bottom:1px solid #fee2e2;color:#374151}}
                tr:nth-child(even) td {{background:#fff5f5}}
                h2,h3,h4 {{color:#991b1b;margin:12px 0 4px}}
                hr {{border:none;border-top:1px solid #fca5a5;margin:10px 0}}
                blockquote {{border-left:3px solid #f87171;padding:4px 10px;margin:4px 0;color:#7f1d1d;background:#fff1f2}}
                strong {{color:#991b1b}}
              </style>
              {summary_html}
            </div>

            <p style="font-size:13px;margin:0 0 20px;">
              Please log in to <strong>Doova OneView</strong> to review the details and take action.
            </p>

            <hr style="border:none;border-top:1px solid #fee2e2;margin:0 0 16px;" />
            <p style="color:#9ca3af;font-size:11px;margin:0;line-height:1.5;">
              This alert was automatically generated by Doova OneView.
              To manage alert schedules, visit the <strong>Alerts</strong> section.
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
