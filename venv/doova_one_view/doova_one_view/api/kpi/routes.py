from typing import Any, Optional

from fastapi import APIRouter, Depends, Query

from doova_one_view.api.auth.permissions import require_permissions
from doova_one_view.api.kpi.service import KPIService
from doova_one_view.api.kpi.schemas import KPIPeriodDetailResponse

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


# ── Revenues ──────────────────────────────────────────────────────────────────

@router.get(
    "/revenues/today",
    dependencies=[_view_kpi],
    response_model=KPIPeriodDetailResponse,
    summary="Today's revenues — all tenants",
    description=(
        "Itemised list of confirmed/done sales orders placed today, "
        "summed across all tenants. Uses SalesOrder — same source as KPI overview."
    ),
)
async def get_revenues_today(
    date: Optional[str] = Query(None, description="ISO date (YYYY-MM-DD). Defaults to server today."),
    limit: int = Query(50, ge=1, description="Number of items to return"),
    offset: int = Query(0, ge=0, description="Number of items to skip"),
) -> dict[str, Any]:
    return await KPIService.get_period_detail("revenues", "today", date, limit, offset)


@router.get(
    "/revenues/monthly",
    dependencies=[_view_kpi],
    response_model=KPIPeriodDetailResponse,
    summary="Monthly revenues — all tenants",
    description="Itemised sales order revenues for the current calendar month across all tenants.",
)
async def get_revenues_monthly(
    date: Optional[str] = Query(None, description="ISO date (YYYY-MM-DD). Defaults to server today."),
    limit: int = Query(50, ge=1, description="Number of items to return"),
    offset: int = Query(0, ge=0, description="Number of items to skip"),
) -> dict[str, Any]:
    return await KPIService.get_period_detail("revenues", "monthly", date, limit, offset)


@router.get(
    "/revenues/yearly",
    dependencies=[_view_kpi],
    response_model=KPIPeriodDetailResponse,
    summary="Yearly revenues — all tenants",
    description="Itemised sales order revenues for the current calendar year across all tenants.",
)
async def get_revenues_yearly(
    date: Optional[str] = Query(None, description="ISO date (YYYY-MM-DD). Defaults to server today."),
    limit: int = Query(50, ge=1, description="Number of items to return"),
    offset: int = Query(0, ge=0, description="Number of items to skip"),
) -> dict[str, Any]:
    return await KPIService.get_period_detail("revenues", "yearly", date, limit, offset)


# ── Expenses ──────────────────────────────────────────────────────────────────

@router.get(
    "/expenses/today",
    dependencies=[_view_kpi],
    response_model=KPIPeriodDetailResponse,
    summary="Today's expenses — all tenants",
    description=(
        "Itemised list of confirmed/done purchase orders placed today, "
        "summed across all tenants. Uses PurchaseOrder — same source as KPI overview."
    ),
)
async def get_expenses_today(
    date: Optional[str] = Query(None, description="ISO date (YYYY-MM-DD). Defaults to server today."),
    limit: int = Query(50, ge=1, description="Number of items to return"),
    offset: int = Query(0, ge=0, description="Number of items to skip"),
) -> dict[str, Any]:
    return await KPIService.get_period_detail("expenses", "today", date, limit, offset)


@router.get(
    "/expenses/monthly",
    dependencies=[_view_kpi],
    response_model=KPIPeriodDetailResponse,
    summary="Monthly expenses — all tenants",
    description="Itemised purchase order expenses for the current calendar month across all tenants.",
)
async def get_expenses_monthly(
    date: Optional[str] = Query(None, description="ISO date (YYYY-MM-DD). Defaults to server today."),
    limit: int = Query(50, ge=1, description="Number of items to return"),
    offset: int = Query(0, ge=0, description="Number of items to skip"),
) -> dict[str, Any]:
    return await KPIService.get_period_detail("expenses", "monthly", date, limit, offset)


@router.get(
    "/expenses/yearly",
    dependencies=[_view_kpi],
    response_model=KPIPeriodDetailResponse,
    summary="Yearly expenses — all tenants",
    description="Itemised purchase order expenses for the current calendar year across all tenants.",
)
async def get_expenses_yearly(
    date: Optional[str] = Query(None, description="ISO date (YYYY-MM-DD). Defaults to server today."),
    limit: int = Query(50, ge=1, description="Number of items to return"),
    offset: int = Query(0, ge=0, description="Number of items to skip"),
) -> dict[str, Any]:
    return await KPIService.get_period_detail("expenses", "yearly", date, limit, offset)


# ── Profits ───────────────────────────────────────────────────────────────────

@router.get(
    "/profits/today",
    dependencies=[_view_kpi],
    response_model=KPIPeriodDetailResponse,
    summary="Today's profits — all tenants",
    description="Revenue items, expense items and net profit for today across all tenants.",
)
async def get_profits_today(
    date: Optional[str] = Query(None, description="ISO date (YYYY-MM-DD). Defaults to server today."),
    limit: int = Query(50, ge=1, description="Number of items to return"),
    offset: int = Query(0, ge=0, description="Number of items to skip"),
) -> dict[str, Any]:
    return await KPIService.get_period_detail("profits", "today", date, limit, offset)


@router.get(
    "/profits/monthly",
    dependencies=[_view_kpi],
    response_model=KPIPeriodDetailResponse,
    summary="Monthly profits — all tenants",
    description="Revenue items, expense items and net profit for the current month across all tenants.",
)
async def get_profits_monthly(
    date: Optional[str] = Query(None, description="ISO date (YYYY-MM-DD). Defaults to server today."),
    limit: int = Query(50, ge=1, description="Number of items to return"),
    offset: int = Query(0, ge=0, description="Number of items to skip"),
) -> dict[str, Any]:
    return await KPIService.get_period_detail("profits", "monthly", date, limit, offset)


@router.get(
    "/profits/yearly",
    dependencies=[_view_kpi],
    response_model=KPIPeriodDetailResponse,
    summary="Yearly profits — all tenants",
    description="Revenue items, expense items and net profit for the current year across all tenants.",
)
async def get_profits_yearly(
    date: Optional[str] = Query(None, description="ISO date (YYYY-MM-DD). Defaults to server today."),
    limit: int = Query(50, ge=1, description="Number of items to return"),
    offset: int = Query(0, ge=0, description="Number of items to skip"),
) -> dict[str, Any]:
    return await KPIService.get_period_detail("profits", "yearly", date, limit, offset)
