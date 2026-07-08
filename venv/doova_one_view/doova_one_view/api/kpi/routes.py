from typing import Any, Optional

from fastapi import APIRouter, Depends, Query

from doova_one_view.api.auth.permissions import require_permissions
from doova_one_view.api.kpi.service import KPIService
from doova_one_view.api.kpi.schemas import AgingBucketDetailResponse, KPIPeriodDetailResponse, CustomerDetail, ProductDetail, CurrencyExposureResponse

router = APIRouter(prefix="/kpi", tags=["KPI"])

_view_kpi = Depends(require_permissions("view_kpi"))


@router.get("/overview", dependencies=[_view_kpi])
async def get_overview(
    date_from: Optional[str] = Query(None),
    date_to: Optional[str] = Query(None),
    base_currency: Optional[str] = Query(None),
) -> dict[str, Any]:
    return await KPIService.get_overview(date_from, date_to, base_currency)


@router.get("/summary", dependencies=[_view_kpi])
async def get_summary(
    date_from: Optional[str] = Query(None),
    date_to: Optional[str] = Query(None),
    base_currency: Optional[str] = Query(None),
) -> dict[str, Any]:
    return await KPIService.get_overview(date_from, date_to, base_currency)


@router.get("/trends", dependencies=[_view_kpi])
async def get_trends(
    date_from: Optional[str] = Query(None),
    date_to: Optional[str] = Query(None),
    base_currency: Optional[str] = Query(None),
) -> dict[str, Any]:
    return await KPIService.get_trends(date_from, date_to, base_currency)


@router.get("/top-products", dependencies=[_view_kpi])
async def get_top_products(
    limit: int = Query(10, ge=1),
    base_currency: Optional[str] = Query(None),
) -> dict[str, Any]:
    return await KPIService.get_top_products(limit, descending=True, base_currency=base_currency)


@router.get("/bottom-products", dependencies=[_view_kpi])
async def get_bottom_products(
    limit: int = Query(10, ge=1),
    base_currency: Optional[str] = Query(None),
) -> dict[str, Any]:
    return await KPIService.get_top_products(limit, descending=False, base_currency=base_currency)


@router.get(
    "/products/{product_id}/detail",
    dependencies=[_view_kpi],
    response_model=ProductDetail,
    summary="Product detail with sales history",
    description=(
        "Returns a specific product's profile including total quantity sold, revenue, and margin, "
        "along with a paginated list of all sales order lines involving this product."
    ),
)
async def get_product_detail(
    product_id: int,
    order_limit: int = Query(50, ge=1, description="Orders to return for this product"),
    order_offset: int = Query(0, ge=0, description="Orders to skip for this product"),
) -> ProductDetail:
    return await KPIService.get_product_detail(product_id, order_limit, order_offset)


@router.get("/top-customers", dependencies=[_view_kpi])
async def get_top_customers(
    limit: int = Query(10, ge=1),
    base_currency: Optional[str] = Query(None),
) -> dict[str, Any]:
    return await KPIService.get_top_customers(limit, base_currency=base_currency)


@router.get(
    "/customers/{customer_id}/detail",
    dependencies=[_view_kpi],
    response_model=CustomerDetail,
    summary="Customer detail with orders",
    description=(
        "Returns a specific customer's profile including full contact details "
        "(email, phone, city, country) and a paginated list of their sales orders, "
        "each with a receipt-level breakdown of order lines."
    ),
)
async def get_customer_detail(
    customer_id: int,
    order_limit: int = Query(50, ge=1, description="Orders to return for this customer"),
    order_offset: int = Query(0, ge=0, description="Orders to skip for this customer"),
) -> CustomerDetail:
    return await KPIService.get_customer_detail(customer_id, order_limit, order_offset)


@router.get("/receivables-aging", dependencies=[_view_kpi])
async def get_receivables_aging() -> dict[str, Any]:
    return await KPIService.get_receivables_aging()


@router.get(
    "/receivables-aging/detail",
    dependencies=[_view_kpi],
    response_model=AgingBucketDetailResponse,
    summary="Receivables aging bucket detail",
    description=(
        "Returns paginated invoices for a specific aging bucket. "
        "Includes invoice amount, dates, and full client details. "
        "**bucket** values: `current`, `1-30`, `31-60`, `61-90`, `90+`"
    ),
)
async def get_receivables_aging_detail(
    bucket: str = Query(..., description="Aging bucket: current | 1-30 | 31-60 | 61-90 | 90+"),
    limit: int = Query(50, ge=1, description="Number of invoices to return"),
    offset: int = Query(0, ge=0, description="Number of invoices to skip"),
) -> AgingBucketDetailResponse:
    return await KPIService.get_receivables_aging_detail(bucket, limit, offset)


@router.get("/fast-moving-products", dependencies=[_view_kpi])
async def get_fast_moving_products(
    limit: int = Query(10, ge=1),
) -> dict[str, Any]:
    return await KPIService.get_fast_moving_products(limit)


@router.get("/category-performance", dependencies=[_view_kpi])
async def get_category_performance() -> dict[str, Any]:
    return await KPIService.get_category_performance()


@router.get("/currency-impact", dependencies=[_view_kpi], response_model=CurrencyExposureResponse)
async def get_currency_impact(
    base_currency: Optional[str] = Query(None, description="Base currency code (e.g. USD, EUR). Defaults to company's primary currency.")
) -> CurrencyExposureResponse:
    return await KPIService.get_currency_impact(base_currency=base_currency)


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
    base_currency: Optional[str] = Query(None),
) -> dict[str, Any]:
    return await KPIService.get_period_detail("revenues", "today", date, limit, offset, base_currency)


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
    base_currency: Optional[str] = Query(None),
) -> dict[str, Any]:
    return await KPIService.get_period_detail("revenues", "monthly", date, limit, offset, base_currency)


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
    base_currency: Optional[str] = Query(None),
) -> dict[str, Any]:
    return await KPIService.get_period_detail("revenues", "yearly", date, limit, offset, base_currency)


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
    base_currency: Optional[str] = Query(None),
) -> dict[str, Any]:
    return await KPIService.get_period_detail("expenses", "today", date, limit, offset, base_currency)


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
    base_currency: Optional[str] = Query(None),
) -> dict[str, Any]:
    return await KPIService.get_period_detail("expenses", "monthly", date, limit, offset, base_currency)


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
    base_currency: Optional[str] = Query(None),
) -> dict[str, Any]:
    return await KPIService.get_period_detail("expenses", "yearly", date, limit, offset, base_currency)


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
    base_currency: Optional[str] = Query(None),
) -> dict[str, Any]:
    return await KPIService.get_period_detail("profits", "today", date, limit, offset, base_currency)


@router.get(
    "/profits/monthly",
    dependencies=[_view_kpi],
    response_model=KPIPeriodDetailResponse,
    summary="Monthly profits — all tenants",
    description="Revenue items, expense items and net profit for the current calendar month across all tenants.",
)
async def get_profits_monthly(
    date: Optional[str] = Query(None, description="ISO date (YYYY-MM-DD). Defaults to server today."),
    limit: int = Query(50, ge=1, description="Number of items to return"),
    offset: int = Query(0, ge=0, description="Number of items to skip"),
    base_currency: Optional[str] = Query(None),
) -> dict[str, Any]:
    return await KPIService.get_period_detail("profits", "monthly", date, limit, offset, base_currency)


@router.get(
    "/profits/yearly",
    dependencies=[_view_kpi],
    response_model=KPIPeriodDetailResponse,
    summary="Yearly profits — all tenants",
    description="Revenue items, expense items and net profit for the current calendar year across all tenants.",
)
async def get_profits_yearly(
    date: Optional[str] = Query(None, description="ISO date (YYYY-MM-DD). Defaults to server today."),
    limit: int = Query(50, ge=1, description="Number of items to return"),
    offset: int = Query(0, ge=0, description="Number of items to skip"),
    base_currency: Optional[str] = Query(None),
) -> dict[str, Any]:
    return await KPIService.get_period_detail("profits", "yearly", date, limit, offset, base_currency)
