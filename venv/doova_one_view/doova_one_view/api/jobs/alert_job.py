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
from django.db import close_old_connections
from doova_one_view.api.common.utils import db_sync_to_async

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
    "6. Report any other anomaly a business owner should know about immediately.\n"
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
                close_old_connections()
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
        close_old_connections()
        now = datetime.now(tz.utc)
        logger.info(f"AlertJobManager: checking due schedules at {now.isoformat()}")

        @db_sync_to_async
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
        @db_sync_to_async
        def _fetch():
            from odoo_app.models.tenant import Tenant
            return [str(t.id) for t in Tenant.objects.all()]

        return await _fetch()

    @staticmethod
    async def _check_daily_rate_limit(tenant_id: str) -> bool:
        @db_sync_to_async
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
            @db_sync_to_async
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
            should_send = condition_triggered and send_email and bool(schedule.recipients)
            if should_send:
                await AlertJobManager._send_alert_email(
                    schedule=schedule,
                    tenant_id=tenant_id,
                    summary=summary,
                    is_anomaly=condition_triggered,
                    severity=severity,
                )
                alert_sent = True


            @db_sync_to_async
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
                "severity": severity,
            }

        except Exception as exc:
            error_msg = str(exc)
            logger.exception(
                f"AlertJobManager: check failed schedule={schedule.id} tenant={tenant_id}"
            )

            # next_check_at already advanced in _claim — just log the failure
            @db_sync_to_async
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
            metrics_registry.record_alert_check(condition_triggered=False, alert_sent=False, skipped_llm=True, status="completed")
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
            f"You are a senior executive business advisor to the owner of a company {company_ctx}.\n"
            f"Your core skill is converting raw financial and operational data into concise, "
            f"decision-ready findings. You communicate like a trusted business advisor: precise, plain-spoken, "
            f"and focused on business impact — never on technical mechanics.\n"
            f"</role>\n\n"

            f"<alert_context_json>\n"
            f"{context_json}\n"
            f"</alert_context_json>\n\n"

            f"<deterministic_precheck_findings>\n"
            f"Automated pre-checks flagged the following potential anomalies:\n"
            f"{precheck_res['precheck_summary']}\n"
            f"</deterministic_precheck_findings>\n\n"

            f"<grounding_rules>\n"
            f"- Base every claim strictly on <alert_context_json> and "
            f"<deterministic_precheck_findings>. Never invent figures, dates, or trends.\n"
            f"- If the data is insufficient to answer <user_request> definitively, say so "
            f"explicitly and state what data would resolve it. Do not guess.\n"
            f"- Round figures for readability (e.g., '$1.2M' not '$1,203,447.18') unless "
            f"exact precision is material to the finding.\n"
            f"</grounding_rules>\n\n"

            f"<severity_rubric>\n"
            f"Severity is determined by the CONTENT of the answer to <user_request>, never "
            f"by how the question is phrased. A factually-phrased question (e.g., 'are "
            f"yearly expenses above 1M?') does not by itself mean INFO — evaluate what the "
            f"answer actually says.\n\n"
            f"Once you have the answer, judge it the way an informed business owner would, "
            f"using whatever thresholds, targets, budgets, or prior-period comparisons are "
            f"available in the data:\n"
            f"- CRITICAL: the answer reveals an immediate, material adverse risk or a hard "
            f"threshold breach requiring action within days.\n"
            f"- WARNING: the answer reveals a deteriorating trend or an approaching "
            f"threshold that needs attention soon, but is not yet an emergency.\n"
            f"- OK: the answer is healthy, on-target, or within expected bounds.\n"
            f"- INFO: the answer is purely descriptive with no clear positive or negative "
            f"reading even in context (e.g., a headcount, a balance, a status with nothing "
            f"to compare it against). Never default to INFO just because the question "
            f"sounds factual — use it only when the finding itself carries no good/bad "
            f"signal.\n\n"
            f"Example: 'Are yearly expenses above $1M?' — '$1.2M, 20% over budget' is "
            f"adverse → WARNING or CRITICAL depending on severity, NOT INFO. '$850K, under "
            f"budget' is healthy → OK, NOT INFO. Only a version with nothing to measure "
            f"against (e.g., 'what were total yearly expenses?' with no budget on record) "
            f"would be INFO.\n\n"
            f"Escalation guard: pre-check anomalies UNRELATED to <user_request> (e.g., "
            f"overdue AR, stockouts) must NOT hijack the primary headline severity. Report "
            f"them separately under 'Additional Risk Observations'.\n"
            f"</severity_rubric>\n\n"

            f"<instructions>\n"
            f"1. Answer the primary metric or question in <user_request> first and directly.\n"
            f"2. Apply <severity_rubric> to determine the headline severity.\n"
            f"3. Quantify impact wherever possible: amounts, percentages, deltas vs. prior "
            f"periods, and time horizons.\n"
            f"4. Write for a business owner: no internal sequence IDs, no schema/field names, "
            f"no statistical jargon (say 'unusually high vs. the last 6 months', not "
            f"'3-sigma deviation').\n"
            f"5. Recommended actions must be specific and executable this week — name the "
            f"action, the owner (role), and the urgency. Avoid vague advice like "
            f"'monitor closely'.\n"
            f"6. Before writing your final report, reason step-by-step inside <thinking> tags: "
            f"restate the user's question, identify the relevant data points, test them "
            f"against the rubric, and decide severity. Keep this reasoning out of the "
            f"final report sections.\n"
            f"7. Then output your final assessment exactly per <output_format>.\n"
            f"</instructions>\n\n"

            f"<output_format>\n"
            f"After the closing </thinking> tag, your report must begin with the severity "
            f"line. The very first line MUST match exactly one of:\n"
            f"  CRITICAL: <one-line headline>\n"
            f"  WARNING: <one-line headline>\n"
            f"  INFO: <one-line headline>\n"
            f"  OK: <one-line headline>\n\n"
            f"No text, markdown, or greeting may precede the severity line.\n\n"
            f"Then provide these sections in order:\n"
            f"1. PRIMARY FINDING — 2-3 sentences answering the user's question with key figures.\n"
            f"2. BUSINESS IMPACT — what this means for cash, revenue, cost, or operations, "
            f"quantified where possible.\n"
            f"3. RECOMMENDED ACTION — 1-3 concrete, prioritized next steps.\n"
            f"4. ADDITIONAL RISK OBSERVATIONS — only if pre-checks flagged unrelated issues; "
            f"omit this section entirely if none exist.\n\n"
            f"End with a mandatory machine-readable summary block:\n"
            f"```json\n"
            f'{{"condition_triggered": true|false, "severity": "critical|warning|info|success", '
            f'"summary": "<one sentence>", "confidence": "high|medium|low"}}\n'
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
        crit_match = re.search(r'^\*{0,2}CRITICAL:\*{0,2}\s*', clean_res, re.IGNORECASE | re.MULTILINE)
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

        if re.search(r'\bCRITICAL\b', section, re.IGNORECASE):
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
        @db_sync_to_async
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

        from doova_one_view.api.agent.utils import replace_tenant_ids_with_names
        summary = replace_tenant_ids_with_names(summary)

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
            await AlertJobManager._send_webhook_notification(
                webhook_url=schedule.webhook_url,
                title=subject,
                summary=summary,
                is_anomaly=is_anomaly,
            )

        if sent_count == 0 and schedule.recipients:
            raise Exception(f"Failed to send alert email to any recipient after retries: {'; '.join(errors)}")

    @staticmethod
    async def _send_webhook_notification(webhook_url: str, title: str, summary: str, is_anomaly: bool):
        """Dispatches real-time alert notifications to Slack, MS Teams, or custom HTTP Webhook URLs."""
        import httpx
        from doova_one_view.api.agent.utils import replace_tenant_ids_with_names
        title = replace_tenant_ids_with_names(title)
        summary = replace_tenant_ids_with_names(summary)
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


_send_webhook_notification = AlertJobManager._send_webhook_notification
