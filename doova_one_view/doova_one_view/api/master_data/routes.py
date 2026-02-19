"""
Master Data API routes
"""

from fastapi import APIRouter, Depends, Query
from typing import List, Optional
from odoo_app.models import AppUser
from doova_one_view.api.dependencies import get_current_user
from doova_one_view.api.master_data.schemas import (
    ProductRead, PartnerRead, CurrencyRead, PaginatedResponse
)
from doova_one_view.api.master_data.service import MasterDataService
from doova_one_view.api.tenants.service import TenantService

router = APIRouter(prefix="/master-data", tags=["Master Data"])

@router.get("/{tenant_id}/products", response_model=PaginatedResponse[ProductRead])
async def list_products(
    tenant_id: str,
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    search: Optional[str] = None,
    user: AppUser = Depends(get_current_user)
):
    """List products for a tenant"""
    await TenantService.get_tenant(tenant_id, str(user.id))
    return await MasterDataService.list_products(tenant_id, limit, offset, search)

@router.get("/{tenant_id}/partners", response_model=PaginatedResponse[PartnerRead])
async def list_partners(
    tenant_id: str,
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    is_customer: Optional[bool] = None,
    is_supplier: Optional[bool] = None,
    search: Optional[str] = None,
    user: AppUser = Depends(get_current_user)
):
    """List partners for a tenant"""
    await TenantService.get_tenant(tenant_id, str(user.id))
    return await MasterDataService.list_partners(tenant_id, limit, offset, is_customer, is_supplier, search)

@router.get("/{tenant_id}/currencies", response_model=PaginatedResponse[CurrencyRead])
async def list_currencies(
    tenant_id: str,
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    active_only: bool = Query(True),
    user: AppUser = Depends(get_current_user)
):
    """List currencies for a tenant"""
    await TenantService.get_tenant(tenant_id, str(user.id))
    return await MasterDataService.list_currencies(tenant_id, limit, offset, active_only)
