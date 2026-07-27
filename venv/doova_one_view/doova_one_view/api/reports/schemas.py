from __future__ import annotations
from datetime import datetime
from typing import List, Optional
from pydantic import BaseModel, EmailStr, field_validator


VALID_FREQUENCIES = {'daily', 'weekly', 'biweekly', 'monthly', 'quarterly', 'semi_annual', 'annual'}


class ReportScheduleCreate(BaseModel):
    recipients:  List[EmailStr]
    frequency:   str
    timezone:    str = 'UTC'
    companyIds:  List[int] = []
    tenantIds:   List[str] = []
    report_type: str = 'analysis'
    prompt:      str = ''
    is_enabled:  bool = True
    start_at:    datetime  # first send time (UTC)

    @field_validator('frequency')
    @classmethod
    def validate_frequency(cls, v: str) -> str:
        if v not in VALID_FREQUENCIES:
            raise ValueError(f"frequency must be one of: {', '.join(sorted(VALID_FREQUENCIES))}")
        return v

    @field_validator('recipients')
    @classmethod
    def validate_recipients(cls, v: List[EmailStr]) -> List[EmailStr]:
        if not v:
            raise ValueError("At least one recipient is required")
        return v


class ReportScheduleUpdate(BaseModel):
    recipients:  Optional[List[EmailStr]] = None
    frequency:   Optional[str] = None
    timezone:    Optional[str] = None
    companyIds:  Optional[List[int]] = None
    tenantIds:   Optional[List[str]] = None
    report_type: Optional[str] = None
    prompt:      Optional[str] = None
    is_enabled:  Optional[bool] = None
    next_send_at: Optional[datetime] = None

    @field_validator('frequency')
    @classmethod
    def validate_frequency(cls, v: str | None) -> str | None:
        if v is not None and v not in VALID_FREQUENCIES:
            raise ValueError(f"frequency must be one of: {', '.join(sorted(VALID_FREQUENCIES))}")
        return v


class ReportScheduleResponse(BaseModel):
    id:           str
    tenant_id:    Optional[str] = None
    tenantIds:    List[str] = []
    recipients:   List[str]
    frequency:    str
    timezone:     str
    companyIds:   List[int] = []
    report_type:  str
    prompt:       str
    is_enabled:   bool
    next_send_at: datetime
    last_sent_at: Optional[datetime]
    created_at:   datetime

    model_config = {"from_attributes": True}


class ReportLogResponse(BaseModel):
    id:            int
    schedule_id:   str
    status:        str
    filename:      Optional[str]
    error_message: Optional[str]
    sent_at:       datetime

    model_config = {"from_attributes": True}
