from typing import Any, Optional

from fastapi import APIRouter, Query

from doova_one_view.api.kpi.service import KPIService

router = APIRouter(prefix="/kpi", tags=["KPI"])


@router.get("/overview")
async def get_overview(
    date_from: Optional[str] = Query(None),
    date_to: Optional[str] = Query(None),
) -> dict[str, Any]:
    return await KPIService.get_overview(date_from, date_to)


@router.get("/summary")
async def get_summary(
    date_from: Optional[str] = Query(None),
    date_to: Optional[str] = Query(None),
) -> dict[str, Any]:
    return await KPIService.get_overview(date_from, date_to)


@router.get("/trends")
async def get_trends(
    date_from: Optional[str] = Query(None),
    date_to: Optional[str] = Query(None),
) -> dict[str, Any]:
    return await KPIService.get_trends(date_from, date_to)


@router.get("/top-products")
async def get_top_products(
    limit: int = Query(10, ge=1),
) -> dict[str, Any]:
    return await KPIService.get_top_products(limit, descending=True)


@router.get("/bottom-products")
async def get_bottom_products(
    limit: int = Query(10, ge=1),
) -> dict[str, Any]:
    return await KPIService.get_top_products(limit, descending=False)


@router.get("/top-customers")
async def get_top_customers(
    limit: int = Query(10, ge=1),
) -> dict[str, Any]:
    return await KPIService.get_top_customers(limit)


@router.get("/receivables-aging")
async def get_receivables_aging() -> dict[str, Any]:
    return await KPIService.get_receivables_aging()


@router.get("/fast-moving-products")
async def get_fast_moving_products(
    limit: int = Query(10, ge=1),
) -> dict[str, Any]:
    return await KPIService.get_fast_moving_products(limit)


@router.get("/category-performance")
async def get_category_performance() -> dict[str, Any]:
    return await KPIService.get_category_performance()


@router.get("/currency-impact")
async def get_currency_impact() -> dict[str, Any]:
    return await KPIService.get_currency_impact()
