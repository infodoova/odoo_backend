import logging
from uuid import uuid4
from datetime import datetime
import re
from typing import Optional
from asgiref.sync import async_to_sync
from doova_one_view.api.agent.query_context import build_tenant_filter_sql
from doova_one_view.api.email.email_utils import md_to_html

logger = logging.getLogger(__name__)


def _format_alert_email_html(title: str, message: str, severity: str, tenant_id: str) -> str:
    combined = f"{title} {message}".lower()

    # Enhanced severity classification logic
    is_critical_match = (
        severity == "critical" or
        any(k in combined for k in [
            "critical", "severe", "severely", "shortfall", "breach", "uncollectible", 
            "debit != credit", "emergency"
        ]) or
        ("100%" in combined and ("overdue" in combined or "past due" in combined)) or
        ("overdue" in combined and ("past due" in combined or "ratio: 100%" in combined or "30%" in combined))
    )
    
    is_warning_match = (
        severity == "warning" or
        any(k in combined for k in ["warning", "anomaly", "overdue", "past due", "risk", "exposure", "drop"])
    )

    if is_critical_match:
        severity = "critical"
    elif is_warning_match and severity not in ("critical", "success"):
        severity = "warning"
    elif severity not in ("critical", "warning", "info", "success"):
        severity = "info"

    severity_colors = {
        "critical": ("#dc2626", "#fef2f2", "CRITICAL ALERT"),
        "warning": ("#d97706", "#fffbeb", "WARNING ALERT"),
        "info": ("#2563eb", "#eff6ff", "INFORMATION UPDATE"),
        "success": ("#16a34a", "#f0fdf4", "MILESTONE ACHIEVED 🎉"),
    }
    color, bg_color, label = severity_colors.get(severity, ("#2563eb", "#eff6ff", "ALERT"))

    from doova_one_view.api.agent.utils import replace_tenant_ids_with_names
    from odoo_app.models.tenant import Tenant
    tenant_name = "Organization"
    is_uuid = bool(re.match(r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$', str(tenant_id or ""), re.IGNORECASE))
    try:
        t_obj = Tenant.objects.filter(id=tenant_id).first()
        if t_obj and t_obj.name:
            tenant_name = t_obj.name
        elif tenant_id and not is_uuid:
            tenant_name = str(tenant_id)
    except Exception:
        if tenant_id and not is_uuid:
            tenant_name = str(tenant_id)

    title = replace_tenant_ids_with_names(title)
    message = replace_tenant_ids_with_names(message)
    message_html = md_to_html(message)

    return f"""<!DOCTYPE html>
<html>
<head>
<meta charset="UTF-8"/>
<style>
  .ai-content p {{ margin: 0 0 10px; font-size: 13.5px; line-height: 1.65; color: #374151; }}
  .ai-content h2 {{ font-size: 15px; font-weight: 700; color: #111827; margin: 22px 0 8px; padding-bottom: 5px; border-bottom: 2px solid #e5e7eb; }}
  .ai-content h3 {{ font-size: 13.5px; font-weight: 700; color: #374151; margin: 16px 0 6px; }}
  .ai-content h4 {{ font-size: 13px; font-weight: 700; color: #374151; margin: 12px 0 4px; }}
  .ai-content table {{ border-collapse: collapse; width: 100%; font-size: 12.5px; margin: 12px 0 16px; border-radius: 6px; overflow: hidden; }}
  .ai-content thead tr {{ background: #1e3a5f; }}
  .ai-content th {{ text-align: left; padding: 9px 12px; font-weight: 600; color: #ffffff; font-size: 12px; letter-spacing: 0.3px; }}
  .ai-content td {{ padding: 8px 12px; border-bottom: 1px solid #e5e7eb; color: #374151; vertical-align: top; }}
  .ai-content tbody tr:nth-child(even) td {{ background: #f8fafc; }}
  .ai-content blockquote {{ border-left: 4px solid #f59e0b; background: #fffbeb; padding: 10px 14px; margin: 12px 0; border-radius: 0 6px 6px 0; }}
  .ai-content blockquote p {{ color: #92400e; font-size: 13px; margin: 0; }}
  .ai-content ul, .ai-content ol {{ margin: 8px 0 12px 20px; padding: 0; }}
  .ai-content li {{ font-size: 13.5px; line-height: 1.6; color: #374151; margin-bottom: 4px; }}
  .ai-content strong {{ color: #111827; font-weight: 700; }}
  .ai-content em {{ font-style: italic; color: #6b7280; }}
  .ai-content code {{ background: #f1f5f9; border: 1px solid #e2e8f0; border-radius: 3px; padding: 1px 5px; font-size: 12px; font-family: monospace; }}
  .ai-content hr {{ border: none; border-top: 1px solid #e5e7eb; margin: 16px 0; }}
</style>
</head>
<body style="font-family: Arial, sans-serif; background-color: #f3f4f6; padding: 20px;">
  <div style="max-width: 620px; margin: 0 auto; background: #ffffff; border-radius: 8px; overflow: hidden; border: 1px solid #e5e7eb;">
    <div style="background-color: {color}; padding: 16px 24px; color: #ffffff;">
      <span style="font-size: 12px; font-weight: bold; letter-spacing: 1px; text-transform: uppercase;">{label}</span>
      <h2 style="margin: 8px 0 0 0; font-size: 20px;">{title}</h2>
    </div>
    <div style="padding: 24px; color: #374151; line-height: 1.6;">
      <div class="ai-content">
        {message_html}
      </div>
      <div style="margin-top: 20px; background-color: {bg_color}; border-left: 4px solid {color}; padding: 12px; border-radius: 4px; font-size: 13px; color: #4b5563;">
        Organization: <strong>{tenant_name}</strong><br/>
        Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S UTC')}
      </div>
    </div>
    <div style="background-color: #f9fafb; padding: 12px 24px; text-align: center; font-size: 12px; color: #9ca3af; border-top: 1px solid #e5e7eb;">
      Sent automatically by Nexus AI Agent
    </div>
  </div>
</body>
</html>"""



def get_tenant_alert_recipients(tenant_id: str) -> list[str]:
    recipients = []
    try:
        from odoo_app.models.alert_schedule import AlertSchedule
        schedules = AlertSchedule.objects.filter(tenant_id=tenant_id, is_enabled=True)
        for s in schedules:
            if s.recipients and isinstance(s.recipients, list):
                for r in s.recipients:
                    if r and r not in recipients:
                        recipients.append(r)
    except Exception as e:
        logger.warning(f"Could not fetch alert schedule recipients for tenant {tenant_id}: {e}")

    if not recipients:
        try:
            from django.conf import settings
            default_email = getattr(settings, "DEFAULT_FROM_EMAIL", None) or getattr(settings, "EMAIL_HOST_USER", None)
            if default_email:
                recipients.append(default_email)
        except Exception:
            pass

    return recipients


def send_alert_tool(
    tenant_id: str,
    title: str,
    message: str,
    severity: str = "info",
    company_id: int | None = None,
    source_tool: str | None = None,
    company_ids: Optional[list[int]] = None,
    tenant_ids: Optional[list[str]] = None,
    to_email: Optional[str] = None,
) -> dict:
    allowed = ["info", "warning", "critical", "success"]
    if severity not in allowed:
        severity = "info"

    from doova_one_view.api.agent.utils import replace_tenant_ids_with_names
    title = replace_tenant_ids_with_names(title)
    message = replace_tenant_ids_with_names(message)

    alert = {
        "alert_id": str(uuid4()),
        "tenant_id": tenant_id,
        "company_id": company_id,
        "title": title,
        "message": message,
        "severity": severity,
        "source_tool": source_tool,
        "created_at": datetime.now().isoformat(),
        "status": "prepared",
    }

    recipients = [to_email] if to_email else get_tenant_alert_recipients(tenant_id)

    if not recipients:
        alert["status"] = "no_recipients"
        return {
            "tool_name": "send_alert_tool",
            "alert": alert,
            "sent": False,
            "detail": "No valid email recipients configured for tenant.",
        }

    from doova_one_view.api.email.service import EmailService
    html_body = _format_alert_email_html(title, message, severity, tenant_id)
    subject = f"[{severity.upper()}] Alert: {title}"

    sent_count = 0
    errors = []

    for email_addr in recipients:
        try:
            async_to_sync(EmailService.send)(
                to=email_addr,
                subject=subject,
                html_body=html_body,
                text_body=f"[{severity.upper()}] {title}\n\n{message}",
                priority="HIGH" if severity in ("critical", "warning") else "NORMAL",
            )
            sent_count += 1
        except Exception as e:
            logger.error(f"Failed to send alert email to {email_addr}: {e}")
            errors.append(str(e))

    if sent_count > 0:
        alert["status"] = "sent"
        return {
            "tool_name": "send_alert_tool",
            "alert": alert,
            "alert_id": alert["alert_id"],
            "sent": True,
            "recipients_notified": sent_count,
            "message": (
                f"Alert email dispatched directly to {sent_count} recipient(s). "
                "CRITICAL: Do NOT print, summarize, or output the alert text in your final response to the user. "
                "The user explicitly requested zero frontend UI text generation. "
                "Simply state: 'Alert email dispatched directly to recipient(s).'"
            ),
        }
    else:
        alert["status"] = "failed"
        return {"tool_name": "send_alert_tool", "alert": alert, "alert_id": alert["alert_id"], "sent": False, "errors": errors}


def send_email_tool(
    tenant_id: str,
    to_email: str,
    subject: str,
    body: str,
    company_id: int | None = None,
    source_tool: str | None = None,
    company_ids: Optional[list[int]] = None,
    tenant_ids: Optional[list[str]] = None,
) -> dict:
    if not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", to_email):
        return {"tool_name": "send_email_tool", "sent": False, "status": "invalid_email"}

    from doova_one_view.api.agent.utils import replace_tenant_ids_with_names
    subject = replace_tenant_ids_with_names(subject)
    body = replace_tenant_ids_with_names(body)

    email = {
        "email_id": str(uuid4()),
        "tenant_id": tenant_id,
        "company_id": company_id,
        "to_email": to_email,
        "subject": subject,
        "body": body,
        "source_tool": source_tool,
        "created_at": datetime.now().isoformat(),
        "status": "prepared",
    }

    from doova_one_view.api.email.service import EmailService

    html_body = f"""<!DOCTYPE html>
<html>
<head><meta charset="UTF-8"/></head>
<body style="font-family: Arial, sans-serif; padding: 20px; color: #374151;">
  <div style="max-width: 600px; margin: 0 auto; background: #ffffff; border-radius: 8px; padding: 24px; border: 1px solid #e5e7eb;">
    <h2 style="color: #1e3a5f; margin-top: 0;">{subject}</h2>
    <div style="white-space: pre-wrap; line-height: 1.6;">{body}</div>
  </div>
</body>
</html>"""

    try:
        async_to_sync(EmailService.send)(
            to=to_email,
            subject=subject,
            html_body=html_body,
            text_body=body,
            priority="NORMAL",
        )
        email["status"] = "sent"
        return {"tool_name": "send_email_tool", "email": email, "sent": True}
    except Exception as e:
        logger.error(f"send_email_tool failed to send email to {to_email}: {e}")
        email["status"] = "failed"
        return {"tool_name": "send_email_tool", "email": email, "sent": False, "error": str(e)}


from doova_one_view.api.alerts.schemas import AlertContextPayload

MAX_ALERT_PAYLOAD_BYTES = 8192


def serialize_alert_context(
    tenant_id: str | None,
    user_prompt: str | None,
    thresholds: dict | None = None,
    company_ids: list | None = None,
    precheck_summary: str | None = None,
) -> str:
    """
    Serializes alert context into a safe, bounded JSON string using AlertContextPayload schema.
    Guarantees size <= MAX_ALERT_PAYLOAD_BYTES and valid JSON formatting.
    """
    payload = AlertContextPayload(
        tenant_id=tenant_id,
        prompt=user_prompt or "",
        thresholds=thresholds or {},
        company_ids=company_ids or [],
        precheck_summary=precheck_summary or "",
    )
    return payload.to_json_prompt(max_bytes=MAX_ALERT_PAYLOAD_BYTES)





