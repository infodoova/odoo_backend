"""
Tenant schemas (Pydantic models)
"""

from pydantic import BaseModel, AnyUrl, ConfigDict, Field
from typing import Optional
from datetime import datetime


class TenantCreate(BaseModel):
    """Tenant creation request schema"""
    name: str = Field(..., min_length=1, max_length=255)
    odoo_url: AnyUrl
    odoo_database: str = Field(..., min_length=1, max_length=100)
    odoo_api_key: str = Field(..., min_length=1)
    is_active: bool = Field(default=True)


class TenantUpdate(BaseModel):
    """Tenant update request schema"""
    name: Optional[str] = Field(None, min_length=1, max_length=255)
    odoo_url: Optional[AnyUrl] = None
    odoo_database: Optional[str] = Field(None, min_length=1, max_length=100)
    odoo_api_key: Optional[str] = Field(None, min_length=1)
    is_active: Optional[bool] = None


class TenantRead(BaseModel):
    """Tenant response schema"""
    id: str
    name: str
    odoo_url: str
    odoo_database: str
    is_active: bool
    sync_status: str
    last_sync_at: Optional[datetime]
    created_at: datetime
    updated_at: datetime
    user_count: Optional[int] = None

    model_config = ConfigDict(from_attributes=True)


class SyncResponse(BaseModel):
    """Sync operation response schema"""
    message: str
    tenant_id: str
    sync_type: str
    results: dict
    status: str
    message_type: Optional[str] = "info"  # success, error, info, warning


class SyncStatusResponse(BaseModel):
    """Sync status response schema"""
    tenant_id: str
    sync_status: str
    last_sync_at: Optional[datetime]
    last_sync_results: Optional[dict] = None
