from typing import Any, Optional

from fastapi import APIRouter, Depends, Query

from doova_one_view.api.auth.permissions import require_permissions
from doova_one_view.api.kpi.service import KPIService

router = APIRouter(prefix="/kpi", tags=["KPI"])

_view_kpi = Depends(require_permissions("view_kpi"))


@router.get("/overview", dependencies=[_view_kpi])
async def get_overview(
    date_from: Optional[str] = Query(None),
    date_to: Optional[str] = Query(None),
) -> dict[str, Any]:
    return await KPIService.get_overview(date_from, date_to)


@router.get("/summary", dependencies=[_view_kpi])
async def get_summary(
    date_from: Optional[str] = Query(None),
    date_to: Optional[str] = Query(None),
) -> dict[str, Any]:
    return await KPIService.get_overview(date_from, date_to)


@router.get("/trends", dependencies=[_view_kpi])
async def get_trends(
    date_from: Optional[str] = Query(None),
    date_to: Optional[str] = Query(None),
) -> dict[str, Any]:
    return await KPIService.get_trends(date_from, date_to)


@router.get("/top-products", dependencies=[_view_kpi])
async def get_top_products(
    limit: int = Query(10, ge=1),
) -> dict[str, Any]:
    return await KPIService.get_top_products(limit, descending=True)


@router.get("/bottom-products", dependencies=[_view_kpi])
async def get_bottom_products(
    limit: int = Query(10, ge=1),
) -> dict[str, Any]:
    return await KPIService.get_top_products(limit, descending=False)


@router.get("/top-customers", dependencies=[_view_kpi])
async def get_top_customers(
    limit: int = Query(10, ge=1),
) -> dict[str, Any]:
    return await KPIService.get_top_customers(limit)


@router.get("/receivables-aging", dependencies=[_view_kpi])
async def get_receivables_aging() -> dict[str, Any]:
    return await KPIService.get_receivables_aging()


@router.get("/fast-moving-products", dependencies=[_view_kpi])
async def get_fast_moving_products(
    limit: int = Query(10, ge=1),
) -> dict[str, Any]:
    return await KPIService.get_fast_moving_products(limit)


@router.get("/category-performance", dependencies=[_view_kpi])
async def get_category_performance() -> dict[str, Any]:
    return await KPIService.get_category_performance()


@router.get("/currency-impact", dependencies=[_view_kpi])
async def get_currency_impact() -> dict[str, Any]:
    return await KPIService.get_currency_impact()
