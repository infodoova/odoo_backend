"""
Accounting API routes.

NOTE: Revenue / Expense / Profit summary endpoints have moved to /api/v1/kpi/
      (revenues/today, revenues/monthly, revenues/yearly, expenses/*, profits/*)
      so that numbers are consistent with the KPI overview dashboard.
"""

from typing import Any, Optional

import asyncio
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response

from odoo_app.models import AppUser
from doova_one_view.api.accounting.schemas import SearchRequest
from doova_one_view.api.accounting.service import AccountingService
from doova_one_view.api.common.utils import parse_company_ids
from doova_one_view.api.dependencies import get_current_user
from doova_one_view.api.tenants.service import TenantService

router = APIRouter(prefix="/accounting", tags=["Accounting"])


async def _get_tenant_id_for_user(user: AppUser) -> str:
    """Return the first tenant the user has access to."""
    def _fetch():
        from odoo_app.models.user_tenant_access import UserTenantAccess
        access = UserTenantAccess.objects.filter(user=user).select_related('tenant').first()
        return str(access.tenant_id) if access else None

    tenant_id = await asyncio.to_thread(_fetch)
    if not tenant_id:
        raise HTTPException(status_code=400, detail="No tenant associated with this user")
    return tenant_id


def _company_ids(company_id: Optional[int], companies: Optional[str]) -> Optional[list[int]]:
    return parse_company_ids(company_id if company_id is not None else companies)


@router.get("/{tenant_id}/summary")
async def get_accounting_summary(
    tenant_id: str,
    start_date: Optional[str] = Query(None),
    end_date: Optional[str] = Query(None),
    date_from: Optional[str] = Query(None),
    date_to: Optional[str] = Query(None),
    company_id: Optional[int] = Query(None),
    companies: Optional[str] = Query(None),
    user: AppUser = Depends(get_current_user),
) -> dict[str, Any]:
    await TenantService.get_tenant(tenant_id, str(user.id))
    return await AccountingService.get_summary(
        tenant_id,
        start_date or date_from,
        end_date or date_to,
        _company_ids(company_id, companies),
    )


@router.get("/{tenant_id}/dashboard")
async def get_accounting_dashboard(
    tenant_id: str,
    start_date: Optional[str] = Query(None),
    end_date: Optional[str] = Query(None),
    date_from: Optional[str] = Query(None),
    date_to: Optional[str] = Query(None),
    company_id: Optional[int] = Query(None),
    companies: Optional[str] = Query(None),
    includeCompanies: Optional[str] = Query(None),
    include_companies: Optional[str] = Query(None),
    user: AppUser = Depends(get_current_user),
) -> dict[str, Any]:
    await TenantService.get_tenant(tenant_id, str(user.id))
    return await AccountingService.get_dashboard(
        tenant_id,
        start_date or date_from,
        end_date or date_to,
        _company_ids(company_id, companies),
    )



@router.get("/{tenant_id}/kpis")
async def get_accounting_kpis(
    tenant_id: str,
    start_date: Optional[str] = Query(None),
    end_date: Optional[str] = Query(None),
    date_from: Optional[str] = Query(None),
    date_to: Optional[str] = Query(None),
    company_id: Optional[int] = Query(None),
    companies: Optional[str] = Query(None),
    includeCompanies: Optional[str] = Query(None),
    include_companies: Optional[str] = Query(None),
    user: AppUser = Depends(get_current_user),
) -> dict[str, Any]:
    await TenantService.get_tenant(tenant_id, str(user.id))
    return await AccountingService.get_dashboard(
        tenant_id,
        start_date or date_from,
        end_date or date_to,
        _company_ids(company_id, companies),
    )


@router.get("/{tenant_id}/moves")
async def list_accounting_moves(
    tenant_id: str,
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    partner_id: Optional[int] = Query(None),
    move_type: Optional[str] = Query(None, description="out_invoice, in_invoice, entry, etc."),
    company_id: Optional[int] = Query(None),
    companies: Optional[str] = Query(None),
    user: AppUser = Depends(get_current_user),
) -> dict[str, Any]:
    await TenantService.get_tenant(tenant_id, str(user.id))
    return await AccountingService.get_moves(
        tenant_id, limit, offset, partner_id, _company_ids(company_id, companies), move_type
    )


@router.get("/{tenant_id}/moves/{move_id}")
async def get_accounting_move(
    tenant_id: str,
    move_id: int,
    company_id: Optional[int] = Query(None),
    companies: Optional[str] = Query(None),
    user: AppUser = Depends(get_current_user),
) -> dict[str, Any]:
    await TenantService.get_tenant(tenant_id, str(user.id))
    return await AccountingService.get_move(
        tenant_id, move_id, _company_ids(company_id, companies)
    )


@router.get("/{tenant_id}/filters")
async def get_accounting_filters(
    tenant_id: str,
    user: AppUser = Depends(get_current_user),
) -> dict[str, Any]:
    await TenantService.get_tenant(tenant_id, str(user.id))
    return await AccountingService.get_filters(tenant_id)


@router.post("/{tenant_id}/search")
async def search_accounting_moves(
    tenant_id: str,
    request: SearchRequest,
    user: AppUser = Depends(get_current_user),
) -> dict[str, Any]:
    await TenantService.get_tenant(tenant_id, str(user.id))
    company_ids = parse_company_ids(
        request.company_id if request.company_id is not None else request.companies
    )
    return await AccountingService.search_moves(
        tenant_id, request.filters, request.limit, request.offset, company_ids
    )


@router.get("/{tenant_id}/export")
async def export_accounting_moves(
    tenant_id: str,
    company_id: Optional[int] = Query(None),
    companies: Optional[str] = Query(None),
    user: AppUser = Depends(get_current_user),
) -> Response:
    await TenantService.get_tenant(tenant_id, str(user.id))
    csv_content = await AccountingService.export_moves_csv(
        tenant_id, _company_ids(company_id, companies)
    )
    return Response(
        content=csv_content,
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename=account_moves_{tenant_id}.csv"},
    )
