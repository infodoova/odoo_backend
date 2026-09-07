"""
Account Partial Reconciles API routes.
"""

from typing import Any, Optional
from fastapi import APIRouter, Depends, Query
from fastapi.responses import Response

from odoo_app.models import AppUser
from doova_one_view.api.common.schemas import PaginatedResponse
from doova_one_view.api.auth.permissions import require_permissions, require_any_permission
from doova_one_view.api.account_partial_reconciles.schemas import (
    SearchRequest,
    AccountPartialReconcileRead,
)
from doova_one_view.api.account_partial_reconciles.service import AccountPartialReconcileService
from doova_one_view.api.tenants.service import TenantService

_view_reconciles   = Depends(require_any_permission("view_account_reconciles"))
_export_reconciles = Depends(require_any_permission("export_account_reconciles"))

router = APIRouter(prefix="/account-partial-reconciles", tags=["Account Partial Reconciles"])

from doova_one_view.api.common.utils import parse_company_ids

def _company_ids(
    company_id: Optional[int] = None,
    companies: Optional[str] = None,
    company_ids: Optional[str] = None,
) -> Optional[list[int]]:
    val = company_ids if company_ids is not None else (company_id if company_id is not None else companies)
    return parse_company_ids(val)

@router.get("/{tenant_id}/filters")
async def get_reconciles_filters(
    tenant_id: str,
    user: AppUser = _view_reconciles,
) -> dict[str, Any]:
    await TenantService.get_tenant(tenant_id, str(user.id))
    return await AccountPartialReconcileService.get_reconciles_filters(tenant_id)

@router.get("/{tenant_id}/export")
async def export_reconciles(
    tenant_id: str,
    company_id: Optional[int] = Query(None),
    companies: Optional[str] = Query(None),
    company_ids: Optional[str] = Query(None, description="Comma-separated or JSON list of company IDs"),
    user: AppUser = _export_reconciles,
) -> Response:
    await TenantService.get_tenant(tenant_id, str(user.id))
    csv_content = await AccountPartialReconcileService.export_reconciles_csv(tenant_id, _company_ids(company_id, companies, company_ids))
    return Response(
        content=csv_content,
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename=account_partial_reconciles_{tenant_id}.csv"},
    )

@router.post("/{tenant_id}/search")
async def search_reconciles(
    tenant_id: str,
    request: SearchRequest,
    company_id: Optional[int] = Query(None),
    companies: Optional[str] = Query(None),
    company_ids: Optional[str] = Query(None, description="Comma-separated or JSON list of company IDs"),
    user: AppUser = _view_reconciles,
) -> PaginatedResponse[AccountPartialReconcileRead]:
    await TenantService.get_tenant(tenant_id, str(user.id))
    c_ids = _company_ids(company_id, companies, company_ids)
    if c_ids is None:
        c_ids = parse_company_ids(getattr(request, "company_ids", None) or getattr(request, "company_id", None) or getattr(request, "companies", None))
    return await AccountPartialReconcileService.search_reconciles(tenant_id, request.filters, request.limit, request.offset, c_ids)

@router.get("/{tenant_id}")
async def list_reconciles(
    tenant_id: str,
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    company_id: Optional[int] = Query(None),
    companies: Optional[str] = Query(None),
    company_ids: Optional[str] = Query(None, description="Comma-separated or JSON list of company IDs"),
    user: AppUser = _view_reconciles,
) -> PaginatedResponse[AccountPartialReconcileRead]:
    await TenantService.get_tenant(tenant_id, str(user.id))
    return await AccountPartialReconcileService.get_reconciles(tenant_id, limit, offset, _company_ids(company_id, companies, company_ids))

@router.get("/{tenant_id}/{reconcile_id}")
async def get_reconcile(
    tenant_id: str,
    reconcile_id: int,
    user: AppUser = _view_reconciles,
) -> AccountPartialReconcileRead:
    await TenantService.get_tenant(tenant_id, str(user.id))
    return await AccountPartialReconcileService.get_reconcile(tenant_id, reconcile_id)
