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
    timezone: Optional[str] = None
    is_enabled: Optional[bool] = None
    is_system_default: Optional[bool] = None
    next_check_at: Optional[datetime] = None


class AlertScheduleResponse(BaseModel):
    id: str
    tenant_id: Optional[str]
    tenantIds: List[str] = []
    name: str
    prompt: str
    recipients: List[str]
    companyIds: List[int] = []
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
    has_anomalies: bool
    summary: Optional[str]
    alert_sent: bool
    error_message: Optional[str]
    checked_at: datetime

    model_config = {"from_attributes": True}


class RunAlertRequest(BaseModel):
    send_email: bool = False


class RunAlertResponse(BaseModel):
    has_anomalies: bool
    summary: str
    alert_sent: bool
    log_id: int
