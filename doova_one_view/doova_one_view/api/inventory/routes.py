"""
Inventory API routes
"""

from fastapi import APIRouter, Depends, Query
from typing import List, Optional
from odoo_app.models import AppUser
from doova_one_view.api.dependencies import get_current_user
from doova_one_view.api.inventory.schemas import (
    StockQuantRead, StockMoveRead, InventorySummary, PaginatedResponse
)
from doova_one_view.api.inventory.service import InventoryService
from doova_one_view.api.tenants.service import TenantService

router = APIRouter(prefix="/inventory", tags=["Inventory"])

@router.get("/{tenant_id}/summary", response_model=InventorySummary)
async def get_inventory_summary(
    tenant_id: str,
    user: AppUser = Depends(get_current_user)
):
    """Get summarized inventory metrics for a tenant"""
    await TenantService.get_tenant(tenant_id, str(user.id))
    return await InventoryService.get_inventory_summary(tenant_id)

@router.get("/{tenant_id}/quants", response_model=PaginatedResponse[StockQuantRead])
async def list_stock_quants(
    tenant_id: str,
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    product_id: Optional[int] = None,
    user: AppUser = Depends(get_current_user)
):
    """List current stock levels (quants) for a tenant"""
    await TenantService.get_tenant(tenant_id, str(user.id))
    return await InventoryService.list_quants(tenant_id, limit, offset, product_id)

@router.get("/{tenant_id}/moves", response_model=PaginatedResponse[StockMoveRead])
async def list_stock_moves(
    tenant_id: str,
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    user: AppUser = Depends(get_current_user)
):
    """List stock moves for a tenant"""
    await TenantService.get_tenant(tenant_id, str(user.id))
    return await InventoryService.list_moves(tenant_id, limit, offset)
