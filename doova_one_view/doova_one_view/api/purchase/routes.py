"""
Purchase API routes
"""

from fastapi import APIRouter, Depends, Query
from typing import List, Optional
from odoo_app.models import AppUser
from doova_one_view.api.dependencies import get_current_user
from doova_one_view.api.purchase.schemas import (
    PurchaseOrderRead, PurchaseOrderWithLinesRead, PurchaseSummary, PaginatedResponse
)
from doova_one_view.api.purchase.service import PurchaseService
from doova_one_view.api.tenants.service import TenantService

router = APIRouter(prefix="/purchase", tags=["Purchase"])

@router.get("/{tenant_id}/summary", response_model=PurchaseSummary)
async def get_purchase_summary(
    tenant_id: str,
    user: AppUser = Depends(get_current_user)
):
    """Get summarized purchase metrics for a tenant"""
    await TenantService.get_tenant(tenant_id, str(user.id))
    return await PurchaseService.get_purchase_summary(tenant_id)

@router.get("/{tenant_id}/orders", response_model=PaginatedResponse[PurchaseOrderRead])
async def list_purchase_orders(
    tenant_id: str,
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    partner_id: Optional[int] = None,
    user: AppUser = Depends(get_current_user)
):
    """List purchase orders for a tenant"""
    await TenantService.get_tenant(tenant_id, str(user.id))
    return await PurchaseService.list_orders(tenant_id, limit, offset, partner_id)

@router.get("/{tenant_id}/orders/{order_id}", response_model=PurchaseOrderWithLinesRead)
async def get_purchase_order(
    tenant_id: str,
    order_id: int,
    user: AppUser = Depends(get_current_user)
):
    """Get a specific purchase order with its lines"""
    await TenantService.get_tenant(tenant_id, str(user.id))
    return await PurchaseService.get_order(tenant_id, order_id)
