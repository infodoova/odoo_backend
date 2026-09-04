from __future__ import annotations
from datetime import datetime
from typing import List, Optional
from pydantic import BaseModel, EmailStr, field_validator


class AlertScheduleCreate(BaseModel):
    name: str = 'Daily Activity Alert'
    prompt: str = ''
    recipients: List[EmailStr]
    companyIds: List[int] = []
    tenantIds: List[str] = []
    thresholds: Optional[dict] = None  # custom precheck overrides {"cash_drop_pct": 15.0, ...}
    webhook_url: Optional[str] = None  # Slack/Teams/Custom HTTP webhook
    timezone: str = 'UTC'
    is_enabled: bool = True
    is_system_default: bool = False
    start_at: datetime  # first check time (UTC)
    frequency: Optional[str] = None
    report_type: Optional[str] = None

    @field_validator('recipients')
    @classmethod
    def validate_recipients(cls, v: List[EmailStr]) -> List[EmailStr]:
        if not v:
            raise ValueError("At least one recipient is required")
        return v


class AlertScheduleUpdate(BaseModel):
    name: Optional[str] = None
    prompt: Optional[str] = None
    recipients: Optional[List[EmailStr]] = None
    companyIds: Optional[List[int]] = None
    tenantIds: Optional[List[str]] = None
    thresholds: Optional[dict] = None
    webhook_url: Optional[str] = None
    timezone: Optional[str] = None
    is_enabled: Optional[bool] = None
    is_system_default: Optional[bool] = None
    next_check_at: Optional[datetime] = None


class AlertScheduleResponse(BaseModel):
    id: str
    tenant_id: Optional[str] = None
    tenant_name: Optional[str] = None
    tenantName: Optional[str] = None
    tenantIds: List[str] = []
    tenant_names: List[str] = []
    tenantNames: List[str] = []
    name: str
    prompt: str
    recipients: List[str]
    companyIds: List[int] = []
    company_name: Optional[str] = None
    companyName: Optional[str] = None
    company_names: List[str] = []
    companyNames: List[str] = []
    thresholds: dict = {}
    webhook_url: Optional[str] = None
    timezone: str
    is_enabled: bool
    is_system_default: bool
    next_check_at: datetime
    last_checked_at: Optional[datetime]
    created_at: datetime

    model_config = {"from_attributes": True}


class AlertLogResponse(BaseModel):
    id: int
    schedule_id: Optional[str]
    tenant_id: Optional[str]
    status: str
    condition_triggered: bool = False
    summary: Optional[str]
    alert_sent: bool
    error_message: Optional[str]
    checked_at: datetime

    model_config = {"from_attributes": True}


class RunAlertRequest(BaseModel):
    send_email: bool = True


class RunAlertResponse(BaseModel):
    condition_triggered: bool = False
    alert_sent: bool = False
    log_id: int
    message: str









class AlertContextPayload(BaseModel):
    tenant_id: Optional[str] = None
    prompt: str = ""
    thresholds: dict = {}
    company_ids: List[int] = []
    precheck_summary: str = ""

    def to_json_prompt(self, max_bytes: int = 8192) -> str:
        clean_prompt = self.prompt.strip()
        if len(clean_prompt) > 4000:
            clean_prompt = clean_prompt[:4000] + "... [truncated]"

        payload = self.model_copy(update={"prompt": clean_prompt})
        serialized = payload.model_dump_json(indent=2)
        if len(serialized.encode("utf-8")) > max_bytes:
            payload = payload.model_copy(update={"prompt": clean_prompt[:1000] + "... [truncated]"})
            serialized = payload.model_dump_json(indent=2)
        return serialized


class LlmAlertResult(BaseModel):
    condition_triggered: bool = False
    severity: str = "info"
    summary: str = ""

    @field_validator("severity")
    @classmethod
    def validate_severity(cls, v: str) -> str:
        v_lower = (v or "info").lower()
        if v_lower in ("critical", "warning", "info", "success"):
            return v_lower
        return "info"

