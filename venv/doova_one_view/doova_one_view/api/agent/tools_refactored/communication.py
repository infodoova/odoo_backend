from doova_one_view.api.agent.query_context import build_tenant_filter_sql
from typing import Optional
# api/agent/tools_refactored/communication.py

from uuid import uuid4
from datetime import datetime
import re

def send_alert_tool(tenant_id: str, title: str, message: str, severity: str = "info", company_id: int | None = None, source_tool: str | None = None, company_ids: Optional[list[int]] = None, tenant_ids: Optional[list[str]] = None) -> dict:
    allowed = ["info", "warning", "critical", "success"]
    if severity not in allowed: severity = "info"
    alert = {
        "alert_id": str(uuid4()), "tenant_id": tenant_id, "company_id": company_id,
        "title": title, "message": message, "severity": severity,
        "source_tool": source_tool, "created_at": datetime.now().isoformat(), "status": "prepared",
    }
    return {"tool_name": "send_alert_tool", "alert": alert, "sent": False}

def send_email_tool(tenant_id: str, to_email: str, subject: str, body: str, company_id: int | None = None, source_tool: str | None = None, company_ids: Optional[list[int]] = None, tenant_ids: Optional[list[str]] = None) -> dict:
    if not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", to_email):
        return {"tool_name": "send_email_tool", "sent": False, "status": "invalid_email"}
    email = {
        "email_id": str(uuid4()), "tenant_id": tenant_id, "company_id": company_id,
        "to_email": to_email, "subject": subject, "body": body,
        "source_tool": source_tool, "created_at": datetime.now().isoformat(), "status": "prepared",
    }
    return {"tool_name": "send_email_tool", "email": email, "sent": False}


