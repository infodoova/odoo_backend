from typing import Any, Optional

from fastapi import APIRouter, Depends, Query, Request

from odoo_app.models import AppUser
from doova_one_view.api.common.utils import parse_company_ids
from doova_one_view.api.dependencies import get_current_user
from doova_one_view.api.kpi.service import KPIService
from doova_one_view.api.tenants.service import TenantService

router = APIRouter(prefix="/kpi", tags=["KPI"])


def _company_ids(request: Request, company_id: Optional[int], companies: Optional[str]) -> Optional[list[int]]:
    raw = []
    if companies:
        raw.append(companies)
    raw.extend(request.query_params.getlist("companies"))
    if company_id is not None:
        raw.append(str(company_id))

    cleaned = [
        str(value).strip()
        for value in raw
        if value is not None and str(value).strip().lower() not in {"", "all", "all companies", "undefined", "null", "none"}
    ]
    return parse_company_ids(",".join(cleaned)) if cleaned else None


async def _tenant_ids(user: AppUser) -> list[str]:
    tenants = await TenantService.list_tenants(str(user.id), limit=10000, offset=0)
    return [tenant.id for tenant in tenants]


@router.get("/overview")
async def get_overview(
    request: Request,
    date_from: Optional[str] = Query(None),
    date_to: Optional[str] = Query(None),
    company_id: Optional[int] = Query(None),
    companies: Optional[str] = Query(None),
    user: AppUser = Depends(get_current_user),
) -> dict[str, Any]:
    return await KPIService.get_overview(await _tenant_ids(user), date_from, date_to, _company_ids(request, company_id, companies))


@router.get("/summary")
async def get_summary(
    request: Request,
    date_from: Optional[str] = Query(None),
    date_to: Optional[str] = Query(None),
    company_id: Optional[int] = Query(None),
    companies: Optional[str] = Query(None),
    user: AppUser = Depends(get_current_user),
) -> dict[str, Any]:
    return await KPIService.get_overview(await _tenant_ids(user), date_from, date_to, _company_ids(request, company_id, companies))


@router.get("/trends")
async def get_trends(
    request: Request,
    date_from: Optional[str] = Query(None),
    date_to: Optional[str] = Query(None),
    company_id: Optional[int] = Query(None),
    companies: Optional[str] = Query(None),
    user: AppUser = Depends(get_current_user),
) -> dict[str, Any]:
    return await KPIService.get_trends(await _tenant_ids(user), date_from, date_to, _company_ids(request, company_id, companies))


@router.get("/top-products")
async def get_top_products(
    request: Request,
    limit: int = Query(10, ge=1),
    company_id: Optional[int] = Query(None),
    companies: Optional[str] = Query(None),
    user: AppUser = Depends(get_current_user),
) -> dict[str, Any]:
    return await KPIService.get_top_products(await _tenant_ids(user), limit, _company_ids(request, company_id, companies), descending=True)


@router.get("/bottom-products")
async def get_bottom_products(
    request: Request,
    limit: int = Query(10, ge=1),
    company_id: Optional[int] = Query(None),
    companies: Optional[str] = Query(None),
    user: AppUser = Depends(get_current_user),
) -> dict[str, Any]:
    return await KPIService.get_top_products(await _tenant_ids(user), limit, _company_ids(request, company_id, companies), descending=False)


@router.get("/top-customers")
async def get_top_customers(
    request: Request,
    limit: int = Query(10, ge=1),
    company_id: Optional[int] = Query(None),
    companies: Optional[str] = Query(None),
    user: AppUser = Depends(get_current_user),
) -> dict[str, Any]:
    return await KPIService.get_top_customers(await _tenant_ids(user), limit, _company_ids(request, company_id, companies))


@router.get("/receivables-aging")
async def get_receivables_aging(
    request: Request,
    company_id: Optional[int] = Query(None),
    companies: Optional[str] = Query(None),
    user: AppUser = Depends(get_current_user),
) -> dict[str, Any]:
    return await KPIService.get_receivables_aging(await _tenant_ids(user), _company_ids(request, company_id, companies))


@router.get("/fast-moving-products")
async def get_fast_moving_products(
    request: Request,
    limit: int = Query(10, ge=1),
    company_id: Optional[int] = Query(None),
    companies: Optional[str] = Query(None),
    user: AppUser = Depends(get_current_user),
) -> dict[str, Any]:
    return await KPIService.get_fast_moving_products(await _tenant_ids(user), limit, _company_ids(request, company_id, companies))


@router.get("/category-performance")
async def get_category_performance(
    request: Request,
    company_id: Optional[int] = Query(None),
    companies: Optional[str] = Query(None),
    user: AppUser = Depends(get_current_user),
) -> dict[str, Any]:
    return await KPIService.get_category_performance(await _tenant_ids(user), _company_ids(request, company_id, companies))


@router.get("/currency-impact")
async def get_currency_impact(
    request: Request,
    company_id: Optional[int] = Query(None),
    companies: Optional[str] = Query(None),
    user: AppUser = Depends(get_current_user),
) -> dict[str, Any]:
    return await KPIService.get_currency_impact(await _tenant_ids(user), _company_ids(request, company_id, companies))
