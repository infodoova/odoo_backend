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


def _md_to_html(text: str) -> str:
    """Convert the AI-generated markdown summary to email-safe HTML."""

    def inline(s: str) -> str:
        s = s.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
        s = re.sub(r'\*\*(.*?)\*\*', r'<strong>\1</strong>', s)
        s = re.sub(r'__(.*?)__',     r'<strong>\1</strong>', s)
        s = re.sub(r'\*(.*?)\*',     r'<em>\1</em>', s)
        s = re.sub(r'`(.*?)`',       r'<code style="background:#f1f5f9;padding:1px 4px;border-radius:3px;font-size:12px;">\1</code>', s)
        return s

    def is_sep(cells):
        return all(re.match(r'^:?-+:?$', c.strip()) for c in cells if c.strip())

    TH  = 'style="text-align:left;padding:8px 12px;background:#1e3a5f;color:#fff;font-size:12px;font-weight:700;"'
    TD  = 'style="padding:7px 12px;border-bottom:1px solid #e5e7eb;font-size:12px;color:#374151;vertical-align:top;"'
    TDa = 'style="padding:7px 12px;border-bottom:1px solid #e5e7eb;font-size:12px;color:#374151;vertical-align:top;background:#f8fafc;"'

    lines  = text.splitlines()
    out    = []
    i      = 0
    in_ul  = False
    in_ol  = False

    def close_lists():
        nonlocal in_ul, in_ol
        if in_ul:
            out.append('</ul>')
            in_ul = False
        if in_ol:
            out.append('</ol>')
            in_ol = False

    while i < len(lines):
        raw  = lines[i]
        line = raw.strip()

        # blank line
        if not line:
            close_lists()
            i += 1
            continue

        # H1
        if re.match(r'^# [^#]', line):
            close_lists()
            out.append(f'<h2 style="font-size:17px;font-weight:700;color:#1e3a5f;margin:18px 0 6px;padding-bottom:6px;border-bottom:2px solid #e5e7eb;">{inline(line[2:])}</h2>')
            i += 1; continue

        # H2
        if re.match(r'^## [^#]', line):
            close_lists()
            out.append(f'<h3 style="font-size:15px;font-weight:700;color:#1e3a5f;margin:16px 0 5px;padding-bottom:4px;border-bottom:1.5px solid #dbeafe;">{inline(line[3:])}</h3>')
            i += 1; continue

        # H3
        if re.match(r'^### [^#]', line):
            close_lists()
            out.append(f'<h4 style="font-size:13px;font-weight:700;color:#1d4ed8;margin:12px 0 4px;">{inline(line[4:])}</h4>')
            i += 1; continue

        # H4
        if re.match(r'^#### ', line):
            close_lists()
            out.append(f'<h5 style="font-size:12px;font-weight:700;color:#374151;margin:10px 0 3px;">{inline(line[5:])}</h5>')
            i += 1; continue

        # HR
        if re.match(r'^[-*]{3,}$', line):
            close_lists()
            out.append('<hr style="border:none;border-top:1px solid #e5e7eb;margin:12px 0;"/>')
            i += 1; continue

        # Blockquote — collect consecutive lines
        if line.startswith('> '):
            close_lists()
            bq = []
            while i < len(lines) and lines[i].strip().startswith('> '):
                bq.append(inline(lines[i].strip()[2:]))
                i += 1
            content = ' '.join(bq)
            out.append(
                f'<div style="border-left:4px solid #f59e0b;background:#fffbeb;'
                f'padding:10px 14px;margin:10px 0;border-radius:0 6px 6px 0;">'
                f'<p style="margin:0;font-size:13px;color:#92400e;font-style:italic;">{content}</p></div>'
            )
            continue

        # Table
        if line.startswith('|') and line.endswith('|'):
            close_lists()
            table_lines = []
            while i < len(lines) and lines[i].strip().startswith('|') and lines[i].strip().endswith('|'):
                table_lines.append(lines[i].strip())
                i += 1
            # separate header / separator / body
            rows = [row for row in table_lines if not is_sep([c for c in row[1:-1].split('|')])]
            if rows:
                out.append('<table style="border-collapse:collapse;width:100%;margin:10px 0 14px;font-size:12px;">')
                for ridx, row in enumerate(rows):
                    cells = [c.strip() for c in row[1:-1].split('|')]
                    tag = 'th' if ridx == 0 else 'td'
                    attr = TH if ridx == 0 else (TD if ridx % 2 == 1 else TDa)
                    out.append('<tr>' + ''.join(f'<{tag} {attr}>{inline(c)}</{tag}>' for c in cells) + '</tr>')
                out.append('</table>')
            continue

        # Unordered list
        if re.match(r'^[-*+] ', line):
            if not in_ul:
                close_lists()
                out.append('<ul style="margin:6px 0 10px 18px;padding:0;">')
                in_ul = True
            out.append(f'<li style="font-size:13px;color:#374151;line-height:1.6;margin-bottom:3px;">{inline(line[2:])}</li>')
            i += 1; continue

        # Ordered list
        m = re.match(r'^(\d+)\.\s+(.*)', line)
        if m:
            if not in_ol:
                close_lists()
                out.append('<ol style="margin:6px 0 10px 18px;padding:0;">')
                in_ol = True
            out.append(f'<li style="font-size:13px;color:#374151;line-height:1.6;margin-bottom:3px;">{inline(m.group(2))}</li>')
            i += 1; continue

        # Regular paragraph
        close_lists()
        out.append(f'<p style="font-size:13.5px;color:#374151;line-height:1.65;margin:0 0 8px;">{inline(line)}</p>')
        i += 1

    close_lists()
    return '\n'.join(out)

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

        # ── Claim immediately (scheduled runs only) ──────────────────────────
        # Advance next_check_at BEFORE the AI runs so a restart or concurrent
        # process cannot re-pick this schedule and send duplicate alerts.
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
        from doova_one_view.api.jobs.alert_prechecks import run_all_prechecks
        from doova_one_view.api.agent.langchain_agent import DoovaLangChainAgent

        # Tier 1: Deterministic SQL Pre-Checks (zero LLM cost)
        precheck_res = await asyncio.to_thread(run_all_prechecks, tenant_id, company_ids)
        if not precheck_res["any_triggered"]:
            logger.info(f"AlertJobManager: Tier 1 pre-checks CLEAR for tenant={tenant_id} — skipping LLM inference.")
            return "OK: All monitored financial, inventory, and operational metrics are within normal baseline ranges.", False

        logger.info(f"AlertJobManager: Tier 1 pre-checks TRIGGERED ({precheck_res['triggered_checks']}) — proceeding to Tier 2 LLM analysis.")

        if company_ids and len(company_ids) > 0:
            company_ctx = f"for selected companies {company_ids}"
        else:
            company_ctx = "across all companies"
        effective_prompt = (
            user_prompt.strip()
            if user_prompt and user_prompt.strip()
            else DEFAULT_ALERT_PROMPT
        )

        full_prompt = (
            f"<role>\n"
            f"You are an elite vigilance AI and forensic auditor monitoring a business {company_ctx} for unusual, risky, or suspicious activity. "
            f"Your expertise lies in identifying financial anomalies, inventory shrinkage, and operational risks.\n"
            f"</role>\n\n"
            f"<deterministic_precheck_findings>\n"
            f"Automated pre-checks flagged the following potential anomalies:\n"
            f"{precheck_res['precheck_summary']}\n"
            f"</deterministic_precheck_findings>\n\n"
            f"<instructions>\n"
            f"1. Use all relevant tools (sales, finance, inventory, receivables, trial balance, detect_anomalies) to gather complete context on the flagged issues before making an assessment.\n"
            f"2. Carefully analyze the data according to the criteria defined in the <user_request>.\n"
            f"3. Only flag genuine data anomalies (e.g., sudden spikes, drastic drops, negative cash flows) — ignore missing data or date range issues.\n"
            f"4. Before writing your final report, enclose your internal reasoning within <thinking> tags to plan your tool usage and analyze the data step-by-step.\n"
            f"5. After thinking, output your final assessment matching the strict format defined in <output_format>.\n"
            f"</instructions>\n\n"
            f"<output_format>\n"
            f"Your response must begin with a STRATEGIC RECOMMENDATION section. The very first line of this section MUST be exactly one of the following:\n"
            f"  ALERT: <one-line headline>\n"
            f"  OK: <one-line headline>\n\n"
            f"Do not add any text, markdown, or greetings before the 'ALERT:' or 'OK:' line. "
            f"Following the headline, provide your full detailed findings and analysis.\n"
            f"</output_format>\n\n"
            f"<user_request>\n"
            f"{effective_prompt}\n"
            f"</user_request>"
        )

        agent = DoovaLangChainAgent()
        result = await asyncio.to_thread(agent.run, full_prompt, tenant_id, company_ids=company_ids)
        result = result.strip()

        # The agent sometimes wraps ALERT:/OK: in bold (**ALERT:**) or places it
        # after section headers. Use progressively looser patterns.

        # Pass 1 — strict line-start, with optional bold markers
        alert_match = re.search(r'^\*{0,2}ALERT:\*{0,2}\s*', result, re.IGNORECASE | re.MULTILINE)
        ok_match    = re.search(r'^\*{0,2}OK:\*{0,2}\s*',    result, re.IGNORECASE | re.MULTILINE)

        if alert_match:
            return result[alert_match.end():].strip(), True
        if ok_match:
            return result[ok_match.end():].strip(), False

        # Pass 2 — find STRATEGIC RECOMMENDATION section, then search inside it
        rec_match = re.search(r'##\s*STRATEGIC\s+RECOMMENDATION\b', result, re.IGNORECASE)
        section = result[rec_match.end():].strip() if rec_match else result

        alert_in_sec = re.search(r'\*{0,2}ALERT:\*{0,2}\s*', section, re.IGNORECASE)
        ok_in_sec    = re.search(r'\*{0,2}OK:\*{0,2}\s*',    section, re.IGNORECASE)

        if alert_in_sec:
            return section[alert_in_sec.end():].strip(), True
        if ok_in_sec:
            return section[ok_in_sec.end():].strip(), False

        # Pass 3 — bare keyword anywhere (e.g. "**ALERT** — headline")
        if re.search(r'\bALERT\b', section, re.IGNORECASE):
            return section, True

        return section, False

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

        summary_html = _md_to_html(summary)

        html_body = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8"/>
<meta name="viewport" content="width=device-width,initial-scale=1.0"/>
<style>
  /* Reset */
  body,table,td,p,a,li,blockquote{{margin:0;padding:0;border:0;font-size:100%;vertical-align:baseline}}
  body{{background:#f3f4f6;font-family:Arial,Helvetica,sans-serif;-webkit-text-size-adjust:100%}}

  /* AI content typography */
  .ai-content p{{margin:0 0 10px;font-size:13.5px;line-height:1.65;color:#374151}}
  .ai-content h2{{font-size:15px;font-weight:700;color:#111827;margin:22px 0 8px;padding-bottom:5px;border-bottom:2px solid #e5e7eb}}
  .ai-content h3{{font-size:13.5px;font-weight:700;color:#374151;margin:16px 0 6px}}
  .ai-content h4{{font-size:13px;font-weight:700;color:#374151;margin:12px 0 4px}}

  /* Tables */
  .ai-content table{{border-collapse:collapse;width:100%;font-size:12.5px;margin:12px 0 16px;border-radius:6px;overflow:hidden}}
  .ai-content thead tr{{background:#1e3a5f}}
  .ai-content th{{text-align:left;padding:9px 12px;font-weight:600;color:#ffffff;font-size:12px;letter-spacing:0.3px}}
  .ai-content td{{padding:8px 12px;border-bottom:1px solid #e5e7eb;color:#374151;vertical-align:top}}
  .ai-content tbody tr:nth-child(even) td{{background:#f8fafc}}
  .ai-content tbody tr:hover td{{background:#eff6ff}}
  .ai-content tbody tr:last-child td{{border-bottom:none}}

  /* Blockquotes */
  .ai-content blockquote{{border-left:4px solid #f59e0b;background:#fffbeb;padding:10px 14px;margin:12px 0;border-radius:0 6px 6px 0}}
  .ai-content blockquote p{{color:#92400e;font-size:13px;margin:0}}

  /* Lists */
  .ai-content ul,.ai-content ol{{margin:8px 0 12px 20px;padding:0}}
  .ai-content li{{font-size:13.5px;line-height:1.6;color:#374151;margin-bottom:4px}}

  /* Inline */
  .ai-content strong{{color:#111827;font-weight:700}}
  .ai-content em{{font-style:italic;color:#6b7280}}
  .ai-content code{{background:#f1f5f9;border:1px solid #e2e8f0;border-radius:3px;padding:1px 5px;font-size:12px;font-family:monospace}}
  .ai-content hr{{border:none;border-top:1px solid #e5e7eb;margin:16px 0}}
</style>
</head>
<body style="background:#f3f4f6;padding:24px 0;">

<table width="100%" cellpadding="0" cellspacing="0" border="0">
<tr><td align="center">
<table width="620" cellpadding="0" cellspacing="0" border="0" style="max-width:620px;">

  <!-- Header -->
  <tr>
    <td style="background:linear-gradient(135deg,#1e3a5f 0%,#1e40af 100%);padding:28px 32px;border-radius:12px 12px 0 0;">
      <table width="100%" cellpadding="0" cellspacing="0" border="0">
        <tr>
          <td>
            <span style="display:inline-block;background:#dc2626;color:#fff;font-size:11px;font-weight:700;letter-spacing:1px;padding:4px 10px;border-radius:20px;text-transform:uppercase;margin-bottom:10px;">&#9888; Alert</span>
            <h1 style="color:#ffffff;font-size:22px;font-weight:700;margin:0 0 6px;line-height:1.2;">Unusual Activity Detected</h1>
            <p style="color:#93c5fd;font-size:13px;margin:0;">{tenant_name}&nbsp;&nbsp;·&nbsp;&nbsp;{company_note}</p>
          </td>
          <td align="right" style="vertical-align:top;">
            <span style="font-size:42px;line-height:1;">&#128680;</span>
          </td>
        </tr>
      </table>
    </td>
  </tr>

  <!-- Alert summary strip -->
  <tr>
    <td style="background:#dc2626;padding:12px 32px;">
      <p style="color:#fff;font-size:13px;margin:0;line-height:1.5;">
        The AI monitoring check has detected <strong style="color:#fef9c3;">anomalies that require your immediate attention.</strong>
        Review the findings below and take action.
      </p>
    </td>
  </tr>

  <!-- Main content -->
  <tr>
    <td style="background:#ffffff;padding:28px 32px;border-left:1px solid #e5e7eb;border-right:1px solid #e5e7eb;">
      <div class="ai-content">
        {summary_html}
      </div>
    </td>
  </tr>

  <!-- CTA footer -->
  <tr>
    <td style="background:#f8fafc;padding:20px 32px;border:1px solid #e5e7eb;border-top:2px solid #1e3a5f;border-radius:0 0 12px 12px;">
      <table width="100%" cellpadding="0" cellspacing="0" border="0">
        <tr>
          <td style="vertical-align:middle;">
            <p style="color:#374151;font-size:13px;margin:0 0 2px;font-weight:600;">Nexus</p>
            <p style="color:#6b7280;font-size:12px;margin:0;">Automated AI Business Monitoring</p>
          </td>
          <td align="right" style="vertical-align:middle;">
            <p style="color:#9ca3af;font-size:11px;margin:0;text-align:right;line-height:1.5;">
              To manage alert schedules,<br>visit the <strong style="color:#1e3a5f;">Alerts</strong> section in Nexus.
            </p>
          </td>
        </tr>
      </table>
    </td>
  </tr>

</table>
</td></tr>
</table>

</body>
</html>"""

        for email in schedule.recipients:
            await EmailService.send(
                to=email,
                subject=subject,
                html_body=html_body,
                priority="HIGH",
            )
