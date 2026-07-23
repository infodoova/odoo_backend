"""
Account Partial Reconciles API routes.
"""

from typing import Any, Optional
from fastapi import APIRouter, Depends, Query
from fastapi.responses import Response

from odoo_app.models import AppUser
from doova_one_view.api.common.schemas import PaginatedResponse
from doova_one_view.api.dependencies import get_current_user
from doova_one_view.api.account_partial_reconciles.schemas import (
    SearchRequest,
    AccountPartialReconcileRead,
)
from doova_one_view.api.account_partial_reconciles.service import AccountPartialReconcileService
from doova_one_view.api.tenants.service import TenantService

router = APIRouter(prefix="/account-partial-reconciles", tags=["Account Partial Reconciles"])

@router.get("/{tenant_id}/filters")
async def get_reconciles_filters(
    tenant_id: str,
    user: AppUser = Depends(get_current_user),
) -> dict[str, Any]:
    await TenantService.get_tenant(tenant_id, str(user.id))
    return await AccountPartialReconcileService.get_reconciles_filters(tenant_id)

@router.get("/{tenant_id}/export")
async def export_reconciles(
    tenant_id: str,
    user: AppUser = Depends(get_current_user),
) -> Response:
    await TenantService.get_tenant(tenant_id, str(user.id))
    csv_content = await AccountPartialReconcileService.export_reconciles_csv(tenant_id)
    return Response(
        content=csv_content,
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename=account_partial_reconciles_{tenant_id}.csv"},
    )

@router.post("/{tenant_id}/search")
async def search_reconciles(
    tenant_id: str,
    request: SearchRequest,
    user: AppUser = Depends(get_current_user),
) -> PaginatedResponse[AccountPartialReconcileRead]:
    await TenantService.get_tenant(tenant_id, str(user.id))
    return await AccountPartialReconcileService.search_reconciles(tenant_id, request.filters, request.limit, request.offset)

@router.get("/{tenant_id}")
async def list_reconciles(
    tenant_id: str,
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    user: AppUser = Depends(get_current_user),
) -> PaginatedResponse[AccountPartialReconcileRead]:
    await TenantService.get_tenant(tenant_id, str(user.id))
    return await AccountPartialReconcileService.get_reconciles(tenant_id, limit, offset)

@router.get("/{tenant_id}/{reconcile_id}")
async def get_reconcile(
    tenant_id: str,
    reconcile_id: int,
    user: AppUser = Depends(get_current_user),
) -> AccountPartialReconcileRead:
    await TenantService.get_tenant(tenant_id, str(user.id))
    return await AccountPartialReconcileService.get_reconcile(tenant_id, reconcile_id)
