from __future__ import annotations
from datetime import datetime, date
from typing import List, Optional
from pydantic import BaseModel, EmailStr, field_validator, model_validator


VALID_FREQUENCIES = {'daily', 'weekly', 'biweekly', 'monthly', 'quarterly', 'semi_annual', 'annual'}


class ReportScheduleCreate(BaseModel):
    report_name:      str = ''
    recipients:       List[EmailStr]
    frequency:        str
    timezone:         str = 'UTC'
    companyIds:       List[int] = []
    tenantIds:        List[str] = []
    report_type:      str = 'analysis'
    date_range_start: Optional[date] = None
    date_range_end:   Optional[date] = None
    prompt:           str = ''
    is_enabled:       bool = True
    start_at:         datetime  # first send time (UTC)

    @field_validator('timezone')
    @classmethod
    def validate_timezone(cls, v: str) -> str:
        import zoneinfo
        try:
            zoneinfo.ZoneInfo(v)
            return v
        except Exception:
            raise ValueError(f"Invalid timezone: '{v}'. Must be a valid IANA timezone string (e.g. UTC, Asia/Riyadh, America/New_York).")

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

    @model_validator(mode='after')
    def validate_date_range(self) -> ReportScheduleCreate:
        start = self.date_range_start
        end = self.date_range_end
        if (start is not None and end is None) or (start is None and end is not None):
            raise ValueError("Both date_range_start and date_range_end must be provided together.")
        if start and end and end < start:
            raise ValueError("date_range_end must be greater than or equal to date_range_start.")
        return self


class ReportScheduleUpdate(BaseModel):
    report_name:      Optional[str] = None
    recipients:       Optional[List[EmailStr]] = None
    frequency:        Optional[str] = None
    timezone:         Optional[str] = None
    companyIds:       Optional[List[int]] = None
    tenantIds:        Optional[List[str]] = None
    report_type:      Optional[str] = None
    date_range_start: Optional[date] = None
    date_range_end:   Optional[date] = None
    prompt:           Optional[str] = None
    is_enabled:       Optional[bool] = None
    next_send_at:     Optional[datetime] = None

    @field_validator('timezone')
    @classmethod
    def validate_timezone(cls, v: str | None) -> str | None:
        if v is not None:
            import zoneinfo
            try:
                zoneinfo.ZoneInfo(v)
                return v
            except Exception:
                raise ValueError(f"Invalid timezone: '{v}'. Must be a valid IANA timezone string (e.g. UTC, Asia/Riyadh, America/New_York).")
        return v

    @field_validator('frequency')
    @classmethod
    def validate_frequency(cls, v: str | None) -> str | None:
        if v is not None and v not in VALID_FREQUENCIES:
            raise ValueError(f"frequency must be one of: {', '.join(sorted(VALID_FREQUENCIES))}")
        return v

    @model_validator(mode='after')
    def validate_date_range(self) -> ReportScheduleUpdate:
        start = self.date_range_start
        end = self.date_range_end
        if start is not None and end is not None and end < start:
            raise ValueError("date_range_end must be greater than or equal to date_range_start.")
        return self



class ReportScheduleResponse(BaseModel):
    id:               str
    report_name:      str = ''
    tenant_id:        Optional[str] = None
    tenantIds:        List[str] = []
    recipients:       List[str]
    frequency:        str
    timezone:         str
    companyIds:       List[int] = []
    report_type:      str
    date_range_start: Optional[date] = None
    date_range_end:   Optional[date] = None
    prompt:           str
    is_enabled:       bool
    next_send_at:     datetime
    last_sent_at:     Optional[datetime]
    created_at:       datetime

    model_config = {"from_attributes": True}


class ReportLogResponse(BaseModel):
    id:               int
    schedule_id:      str
    status:           str
    filename:         Optional[str]
    error_message:    Optional[str]
    error_category:   Optional[str] = None
    duration_seconds: Optional[float] = None
    pdf_size_bytes:   Optional[int] = None
    sent_at:          datetime

    model_config = {"from_attributes": True}

