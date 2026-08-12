"""
Background job that fires daily alert checks.

Every hour it queries AlertSchedule rows whose next_check_at is past,
runs the AI agent to detect unusual activity, sends alert emails only
when anomalies are found, then advances next_check_at by 24 hours.

System-default schedules (is_system_default=True) run for every tenant.
"""

import asyncio
import json
import logging
import re
from datetime import datetime, timezone as tz, timedelta


from doova_one_view.api.email.email_utils import md_to_html as _md_to_html


logger = logging.getLogger(__name__)

_CHECK_INTERVAL_SECONDS = 60  # 1 minute

DEFAULT_ALERT_PROMPT = (
    "<monitoring_criteria>\n"
    "1. Check ALL available business data (sales, purchases, inventory, finance, receivables, payables) from the last 24 hours.\n"
    "2. Look for unusual spikes or drops in revenue (>20%).\n"
    "3. Identify large unexpected expenses or duplicate/suspicious transactions.\n"
    "4. Highlight overdue invoices past 30 days.\n"
    "5. Flag abnormal inventory movements or sudden changes in order volumes.\n"
    "6. Report any other anomaly a CFO should know about immediately.\n"
    "</monitoring_criteria>"
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

        logger.info(f"AlertJobManager: {len(schedules)} schedule(s) due — processing concurrently")
        sem = asyncio.Semaphore(5)

        async def _process_single(schedule):
            async with sem:
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
                            logger.error(
                                f"AlertJobManager: cron check failed schedule={schedule.id} tenant={tid}"
                            )
                else:
                    if schedule.tenant_id or schedule.tenants:
                        try:
                            tenant_ids = schedule.tenants if schedule.tenants else None
                            await AlertJobManager.run_check(
                                schedule=schedule,
                                tenant_id=str(schedule.tenant_id) if schedule.tenant_id else None,
                                send_email=True,
                                is_instant=False,
                                tenant_ids=tenant_ids,
                            )
                        except Exception:
                            logger.error(
                                f"AlertJobManager: cron check failed schedule={schedule.id} tenant={schedule.tenant_id}"
                            )

        await asyncio.gather(*[_process_single(s) for s in schedules], return_exceptions=True)

    @staticmethod
    async def _get_all_tenant_ids() -> list:
        from asgiref.sync import sync_to_async

        @sync_to_async
        def _fetch():
            from odoo_app.models.tenant import Tenant
            return [str(t.id) for t in Tenant.objects.all()]

        return await _fetch()

    @staticmethod
    async def _check_daily_rate_limit(tenant_id: str) -> bool:
        from asgiref.sync import sync_to_async

        @sync_to_async
        def _check():
            from odoo_app.models.alert_schedule import AlertLog
            from doova_one_view.api.agent.config import AgentConfig
            from datetime import timedelta
            from django.utils import timezone

            limit = getattr(AgentConfig, "MAX_DAILY_ALERT_CHECKS_PER_TENANT", 20)
            cutoff = timezone.now() - timedelta(days=1)
            count = AlertLog.objects.filter(
                tenant_id=tenant_id,
                checked_at__gte=cutoff,
            ).count()
            return count >= limit

        return await _check()

    # ------------------------------------------------------------------
    # Core check — used by both the scheduled loop and the run-now route
    # ------------------------------------------------------------------

    @staticmethod
    async def run_check(
        schedule,
        tenant_id: str,
        send_email: bool,
        is_instant: bool,
        tenant_ids: list | None = None,
    ) -> dict:
        """
        Run the AI anomaly check for one (schedule, tenant) pair.
        """
        from asgiref.sync import sync_to_async

        now = datetime.now(tz.utc)
        company_ids = schedule.companies if schedule.companies else None

        # Rate limiting: Check if tenant exceeded 24-hour max AI alert checks
        is_exceeded = await AlertJobManager._check_daily_rate_limit(tenant_id)
        if is_exceeded:
            if is_instant:
                from fastapi import HTTPException
                from doova_one_view.api.agent.config import AgentConfig
                max_limit = getattr(AgentConfig, "MAX_DAILY_ALERT_CHECKS_PER_TENANT", 20)
                raise HTTPException(
                    status_code=429,
                    detail=f"Rate limit exceeded: Maximum daily AI alert checks ({max_limit}) reached for this tenant."
                )


            else:
                logger.warning(f"AlertJobManager: daily rate limit reached for tenant={tenant_id} — skipping check.")
                return {
                    "condition_triggered": False,
                    "summary": "RATE LIMIT: Daily alert check limit reached for this tenant.",
                    "alert_sent": False,
                    "log_id": None,
                }

        if not is_instant:
            @sync_to_async
            def _claim():
                from odoo_app.models.alert_schedule import AlertSchedule
                return AlertSchedule.objects.filter(
                    id=schedule.id,
                    next_check_at=schedule.next_check_at,
                ).update(
                    next_check_at=now + timedelta(days=1),
                    last_checked_at=now,
                )

            claimed = await _claim()
            if not claimed:
                logger.warning(f"AlertJobManager: schedule {schedule.id} already claimed — skipping")
                return {"has_anomalies": False, "summary": "", "alert_sent": False, "log_id": None}

        try:
            summary, condition_triggered, severity = await AlertJobManager._detect_anomalies(
                tenant_id=tenant_id,
                company_ids=company_ids,
                user_prompt=schedule.prompt,
                tenant_ids=tenant_ids,
                thresholds=getattr(schedule, "thresholds", None),
            )

            alert_sent = False
            is_ai_error = "AI Advisor Service" in summary
            should_send = (condition_triggered or (is_instant and not is_ai_error)) and send_email and schedule.recipients
            if should_send:
                await AlertJobManager._send_alert_email(
                    schedule=schedule,
                    tenant_id=tenant_id,
                    summary=summary,
                    is_anomaly=condition_triggered,
                    severity=severity,
                )
                alert_sent = True


            @sync_to_async
            def _log_success():
                from odoo_app.models.alert_schedule import AlertLog
                from odoo_app.models.tenant import Tenant
                tenant_obj = Tenant.objects.filter(id=tenant_id).first()
                return AlertLog.objects.create(
                    schedule=schedule,
                    tenant=tenant_obj,
                    status='completed',
                    condition_triggered=condition_triggered,
                    summary=summary,
                    alert_sent=alert_sent,
                ).id

            log_id = await _log_success()
            logger.info(
                f"AlertJobManager: check done schedule={schedule.id} "
                f"tenant={tenant_id} condition_triggered={condition_triggered}"
            )
            from doova_one_view.api.agent.metrics import metrics_registry
            metrics_registry.record_alert_check(condition_triggered=condition_triggered, alert_sent=alert_sent, skipped_llm=False, status="completed")
            return {
                "condition_triggered": condition_triggered,
                "summary": summary,
                "alert_sent": alert_sent,
                "log_id": log_id,
            }

        except Exception as exc:
            error_msg = str(exc)
            logger.exception(
                f"AlertJobManager: check failed schedule={schedule.id} tenant={tenant_id}"
            )

            # next_check_at already advanced in _claim — just log the failure
            @sync_to_async
            def _log_failure():
                from odoo_app.models.alert_schedule import AlertLog
                from odoo_app.models.tenant import Tenant
                tenant_obj = Tenant.objects.filter(id=tenant_id).first()
                return AlertLog.objects.create(
                    schedule=schedule,
                    tenant=tenant_obj,
                    status='failed',
                    condition_triggered=False,
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
        tenant_ids: list | None = None,
        thresholds: dict | None = None,
    ) -> tuple:
        """
        Returns (summary: str, has_anomalies: bool).
        """
        from doova_one_view.api.jobs.alert_prechecks import run_all_prechecks
        from doova_one_view.api.agent.langchain_agent import DoovaLangChainAgent

        # Tier 1: Deterministic SQL Pre-Checks (zero LLM cost)
        precheck_res = await asyncio.to_thread(
            run_all_prechecks, tenant_id, company_ids, tenant_ids=tenant_ids, thresholds=thresholds
        )
        has_custom_prompt = bool(
            user_prompt and user_prompt.strip() and user_prompt.strip() != DEFAULT_ALERT_PROMPT
        )

        if not precheck_res["any_triggered"] and not has_custom_prompt:
            logger.info(f"AlertJobManager: Tier 1 pre-checks CLEAR for tenant={tenant_id} and no custom prompt — skipping LLM inference.")
            from doova_one_view.api.agent.metrics import metrics_registry
            metrics_registry.record_alert_check(has_anomalies=False, alert_sent=False, skipped_llm=True, status="completed")
            return "OK: All monitored financial, inventory, and operational metrics are within normal baseline ranges.", False, "success"

        if has_custom_prompt:
            logger.info(f"AlertJobManager: Custom user prompt provided ('{user_prompt[:40]}...') — proceeding to Tier 2 AI analysis.")
        else:
            logger.info(f"AlertJobManager: Tier 1 pre-checks TRIGGERED ({precheck_res['triggered_checks']}) — proceeding to Tier 2 AI analysis.")

        if company_ids and len(company_ids) > 0:
            company_ctx = f"for selected companies {company_ids}"
        else:
            company_ctx = "across all companies"
        effective_prompt = (
            user_prompt.strip()
            if user_prompt and user_prompt.strip()
            else DEFAULT_ALERT_PROMPT
        )

        from doova_one_view.api.agent.tools_refactored.communication import serialize_alert_context

        context_json = serialize_alert_context(
            tenant_id=tenant_id,
            user_prompt=user_prompt,
            thresholds=thresholds,
            company_ids=company_ids,
            precheck_summary=precheck_res.get("precheck_summary", ""),
        )

        full_prompt = (
            f"<role>\n"
            f"You are an executive business advisor reporting to a business owner {company_ctx}.\n"
            f"Your expertise is translating complex data into simple, actionable executive findings.\n"
            f"</role>\n\n"
            f"<alert_context_json>\n"
            f"{context_json}\n"
            f"</alert_context_json>\n\n"
            f"<deterministic_precheck_findings>\n"
            f"Automated pre-checks flagged the following potential anomalies:\n"
            f"{precheck_res['precheck_summary']}\n"
            f"</deterministic_precheck_findings>\n\n"
            f"<instructions>\n"
            f"1. Use relevant tools to gather context on the flagged issues before making your assessment.\n"
            f"2. Write for a business owner/client. Omit raw internal database sequence numbers (e.g. #317916/#317917) and internal GL account IDs.\n"
            f"3. Do NOT use technical statistical jargon like '>3σ from mean' — say 'Unusually Large Transaction'.\n"
            f"4. Structure your response into 3 simple sections: What Happened, Business Impact, and Recommended Action.\n"
            f"5. Before writing your final report, enclose your internal reasoning within <thinking> tags.\n"
            f"6. After thinking, output your final assessment matching the strict format defined in <output_format>.\n"
            f"</instructions>\n\n"
            f"<output_format>\n"
            f"Your response must begin with a STRATEGIC RECOMMENDATION section. The very first line of this section MUST state the exact severity, matching one of:\n"
            f"  CRITICAL: <one-line headline>\n"
            f"  WARNING: <one-line headline>\n"
            f"  INFO: <one-line headline>\n"
            f"  OK: <one-line headline>\n\n"
            f"Do not add any text, markdown, or greetings before the severity line. "
            f"Following the headline, provide your simple, executive findings.\n"
            f"You may also optionally include a JSON summary block at the end of your response:\n"
            f"```json\n"
            f'{{"condition_triggered": true|false, "severity": "critical|warning|info|success", "summary": "..."}}\n'
            f"```\n"
            f"</output_format>\n\n"
            f"<user_request>\n"
            f"{effective_prompt}\n"
            f"</user_request>"
        )

        agent = DoovaLangChainAgent()
        try:
            result = await asyncio.to_thread(agent.run, full_prompt, tenant_id, company_ids=company_ids, tenant_ids=tenant_ids)
            result = result.strip() if result else ""
        except Exception as exc:
            err_str = str(exc)
            if any(k in err_str.lower() for k in ["credit balance", "insufficient_quota", "quota", "invalid_request_error", "payment_required"]):
                logger.error(f"AlertJobManager: Upstream LLM provider quota/credit error for tenant={tenant_id}: {exc}")
                return (
                    "INFO: AI Advisor Service Temporarily Unavailable\n\n"
                    "## Service Notice\n"
                    "The AI analysis engine is temporarily paused due to upstream LLM provider credit limits. "
                    "Please verify API key billing and credit balance in administrator settings.",
                    False,
                    "info",
                )
            logger.error(f"AlertJobManager: AI execution error for tenant={tenant_id}: {exc}")
            return (
                f"INFO: AI Advisor Execution Exception\n\n## Service Notice\n{err_str}",
                False,
                "info",
            )

        return AlertJobManager._parse_llm_response(result)


    @staticmethod
    def _parse_llm_response(result: str) -> tuple[str, bool, str]:
        """
        Parses LLM response string into (summary: str, condition_triggered: bool, severity: str).
        Guarantees bulletproof parsing with multi-layered fallbacks:
          Layer 1: Extract JSON snippet (```json { ... } ``` or raw JSON)
          Layer 2: Extract explicit severity line prefix (CRITICAL:, WARNING:, INFO:, OK:)
          Layer 3: Strategic Recommendation section search
          Layer 4: Safe default fallback
        """
        if not result or not isinstance(result, str):
            return "No response generated by AI advisor.", False, "info"

        clean_res = result.strip()

        # Layer 1: JSON block parsing via Pydantic LlmAlertResult schema
        json_match = re.search(r'```(?:json)?\s*(\{[\s\S]*?\})\s*```', clean_res, re.IGNORECASE)
        if not json_match:
            json_match = re.search(r'(\{[\s\S]*?"condition_triggered"[\s\S]*?\})', clean_res)

        if json_match:
            try:
                from doova_one_view.api.alerts.schemas import LlmAlertResult
                parsed = LlmAlertResult.model_validate_json(json_match.group(1))
                summary = parsed.summary.strip() or clean_res
                return summary, parsed.condition_triggered, parsed.severity
            except Exception as e:
                logger.warning(f"AlertJobManager: Pydantic deserialization of LLM response failed ({e}), using regex fallback.")


        # Layer 2: Explicit severity prefix regex
        crit_match = re.search(r'^\*{0,2}(CRITICAL|ALERT):\*{0,2}\s*', clean_res, re.IGNORECASE | re.MULTILINE)
        warn_match = re.search(r'^\*{0,2}WARNING:\*{0,2}\s*', clean_res, re.IGNORECASE | re.MULTILINE)
        info_match = re.search(r'^\*{0,2}INFO:\*{0,2}\s*', clean_res, re.IGNORECASE | re.MULTILINE)
        ok_match   = re.search(r'^\*{0,2}OK:\*{0,2}\s*', clean_res, re.IGNORECASE | re.MULTILINE)

        if crit_match:
            return clean_res[crit_match.end():].strip(), True, "critical"
        if warn_match:
            return clean_res[warn_match.end():].strip(), True, "warning"
        if info_match:
            return clean_res[info_match.end():].strip(), False, "info"
        if ok_match:
            return clean_res[ok_match.end():].strip(), False, "success"

        # Layer 3: Strategic Recommendation section fallback search
        rec_match = re.search(r'##\s*STRATEGIC\s+RECOMMENDATION\b', clean_res, re.IGNORECASE)
        section = clean_res[rec_match.end():].strip() if rec_match else clean_res

        if re.search(r'\b(CRITICAL|ALERT)\b', section, re.IGNORECASE):
            return section, True, "critical"
        if re.search(r'\bWARNING\b', section, re.IGNORECASE):
            return section, True, "warning"
        if re.search(r'\bINFO\b', section, re.IGNORECASE):
            return section, False, "info"
        if re.search(r'\bOK\b', section, re.IGNORECASE):
            return section, False, "success"

        # Layer 4: Safe default fallback
        return section, False, "info"

    # ------------------------------------------------------------------
    # Alert email
    # ------------------------------------------------------------------

    @staticmethod
    async def _send_alert_email(schedule, tenant_id: str, summary: str, is_anomaly: bool = True, severity: str = "critical"):
        from doova_one_view.api.email.service import EmailService
        from doova_one_view.api.agent.tools_refactored.communication import _format_alert_email_html
        from asgiref.sync import sync_to_async

        @sync_to_async
        def _resolve_tenant_name():
            t_name = "Your Business"
            try:
                if schedule.tenant:
                    t_name = schedule.tenant.name
            except Exception:
                pass
            if schedule.tenants and len(schedule.tenants) > 0:
                try:
                    from odoo_app.models.tenant import Tenant
                    t_objs = list(Tenant.objects.filter(id__in=schedule.tenants))
                    if t_objs:
                        t_name = ", ".join(t.name for t in t_objs)
                except Exception:
                    pass
            return t_name

        tenant_name = await _resolve_tenant_name()

        prefix_map = {
            "critical": "CRITICAL ALERT",
            "warning": "WARNING ALERT",
            "info": "INFORMATION UPDATE",
            "success": "STATUS UPDATE: Business Check Clear",
        }
        prefix = prefix_map.get(severity, "ALERT: Unusual Activity Detected" if is_anomaly else "STATUS UPDATE: Business Check Clear")
        subject = f"{prefix} — {tenant_name}"

        html_body = _format_alert_email_html(
            title=f"{prefix} — {tenant_name}",
            message=summary,
            severity=severity,
            tenant_id=tenant_id,
        )

async def _send_webhook_notification(webhook_url: str, title: str, summary: str, is_anomaly: bool):
    """Dispatches real-time alert notifications to Slack, MS Teams, or custom HTTP Webhook URLs."""
    import httpx
    payload = {
        "text": f"🚨 *{title}*",
        "attachments": [
            {
                "color": "#e74c3c" if is_anomaly else "#2ecc71",
                "title": "Nexus Financial Alert",
                "text": summary[:2000],
                "footer": "Nexus Automated AI Business Monitoring",
            }
        ],
    }
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(webhook_url, json=payload)
            resp.raise_for_status()
            logger.info(f"Successfully dispatched alert webhook notification to {webhook_url}")
    except Exception as exc:
        logger.error(f"Failed to dispatch alert webhook notification to {webhook_url}: {exc}")


        sent_count = 0
        errors = []
        for email in schedule.recipients:
            try:
                await EmailService.send(
                    to=email,
                    subject=subject,
                    html_body=html_body,
                    priority="HIGH",
                    max_retries=3,
                )
                sent_count += 1
            except Exception as exc:
                logger.error(f"Failed to send alert email to {email}: {exc}")
                errors.append(f"{email}: {exc}")

        # Dispatch to Webhook URL if configured (Slack / Teams / Custom)
        if getattr(schedule, "webhook_url", None):
            await _send_webhook_notification(
                webhook_url=schedule.webhook_url,
                title=subject,
                summary=summary,
                is_anomaly=True,
            )

        if sent_count == 0 and schedule.recipients:
            raise Exception(f"Failed to send alert email to any recipient after retries: {'; '.join(errors)}")
