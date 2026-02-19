"""
Accounting API routes
"""

from fastapi import APIRouter, Depends, Query
from typing import List, Optional
from odoo_app.models import AppUser
from doova_one_view.api.dependencies import get_current_user
from doova_one_view.api.accounting.schemas import (
    AccountMoveRead, AccountMoveWithLinesRead, AccountingSummary, PaginatedResponse
)
from doova_one_view.api.accounting.service import AccountingService
from doova_one_view.api.tenants.service import TenantService

router = APIRouter(prefix="/accounting", tags=["Accounting"])

@router.get("/{tenant_id}/summary", response_model=AccountingSummary)
async def get_accounting_summary(
    tenant_id: str,
    user: AppUser = Depends(get_current_user)
):
    """Get summarized accounting metrics for a tenant"""
    await TenantService.get_tenant(tenant_id, str(user.id))
    return await AccountingService.get_accounting_summary(tenant_id)

@router.get("/{tenant_id}/moves", response_model=PaginatedResponse[AccountMoveRead])
async def list_accounting_moves(
    tenant_id: str,
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    move_type: Optional[str] = Query(None, description="out_invoice, in_invoice, entry, etc."),
    user: AppUser = Depends(get_current_user)
):
    """List accounting moves for a tenant"""
    await TenantService.get_tenant(tenant_id, str(user.id))
    return await AccountingService.list_moves(tenant_id, limit, offset, move_type)

@router.get("/{tenant_id}/moves/{move_id}", response_model=AccountMoveWithLinesRead)
async def get_accounting_move(
    tenant_id: str,
    move_id: int,
    user: AppUser = Depends(get_current_user)
):
    """Get a specific accounting move with its lines"""
    await TenantService.get_tenant(tenant_id, str(user.id))
    return await AccountingService.get_move(tenant_id, move_id)
