from typing import Any, Optional

from fastapi import APIRouter, Depends, Query

from doova_one_view.api.auth.permissions import require_permissions
from doova_one_view.api.kpi.service import KPIService
from doova_one_view.api.kpi.schemas import (
    AgingBucketDetailResponse,
    KPIPeriodDetailResponse,
    CustomerDetail,
    ProductDetail,
    CurrencyExposureResponse,
)

router = APIRouter(prefix="/kpi", tags=["KPI"])

_view_kpi = Depends(require_permissions("view_kpi"))


def _val_str(val: Any) -> Optional[str]:
    return val if isinstance(val, str) else None


def _val_int(val: Any, default: int = 0) -> int:
    if isinstance(val, int) and not isinstance(val, bool):
        return val
    if isinstance(val, str):
        try:
            return int(val.strip())
        except (ValueError, TypeError):
            return default
    return default


def _parse_csv_str(val: Any) -> Optional[list[str]]:
    if not isinstance(val, str) or not val.strip():
        return None
    items = [x.strip() for x in val.split(",") if x.strip()]
    return items if items else None


def _parse_csv_int(val: Any) -> Optional[list[int]]:
    if not isinstance(val, str) or not val.strip():
        return None
    res = []
    for x in val.split(","):
        x = x.strip()
        if x:
            try:
                res.append(int(x))
            except ValueError:
                pass
    return res if res else None


@router.get("/overview", dependencies=[_view_kpi])
async def get_overview(
    date_from: Optional[str] = Query(None, description="Start date (YYYY-MM-DD)"),
    date_to: Optional[str] = Query(None, description="End date (YYYY-MM-DD)"),
    base_currency: Optional[str] = Query(None),
    tenant_ids: Optional[str] = Query(None, description="Comma-separated list of tenant UUIDs"),
    company_ids: Optional[str] = Query(None, description="Comma-separated list of company integer IDs"),
) -> dict[str, Any]:
    return await KPIService.get_overview(
        _val_str(date_from), _val_str(date_to), _val_str(base_currency),
        tenant_ids=_parse_csv_str(tenant_ids),
        company_ids=_parse_csv_int(company_ids)
    )


@router.get("/summary", dependencies=[_view_kpi])
async def get_summary(
    date_from: Optional[str] = Query(None, description="Start date (YYYY-MM-DD)"),
    date_to: Optional[str] = Query(None, description="End date (YYYY-MM-DD)"),
    base_currency: Optional[str] = Query(None),
    tenant_ids: Optional[str] = Query(None, description="Comma-separated list of tenant UUIDs"),
    company_ids: Optional[str] = Query(None, description="Comma-separated list of company integer IDs"),
) -> dict[str, Any]:
    return await KPIService.get_overview(
        _val_str(date_from), _val_str(date_to), _val_str(base_currency),
        tenant_ids=_parse_csv_str(tenant_ids),
        company_ids=_parse_csv_int(company_ids)
    )


@router.get("/trends", dependencies=[_view_kpi])
async def get_trends(
    date_from: Optional[str] = Query(None, description="Start date (YYYY-MM-DD)"),
    date_to: Optional[str] = Query(None, description="End date (YYYY-MM-DD)"),
    base_currency: Optional[str] = Query(None),
    tenant_ids: Optional[str] = Query(None, description="Comma-separated list of tenant UUIDs"),
    company_ids: Optional[str] = Query(None, description="Comma-separated list of company integer IDs"),
) -> dict[str, Any]:
    return await KPIService.get_trends(
        _val_str(date_from), _val_str(date_to), _val_str(base_currency),
        tenant_ids=_parse_csv_str(tenant_ids),
        company_ids=_parse_csv_int(company_ids)
    )


@router.get("/top-products", dependencies=[_view_kpi])
async def get_top_products(
    limit: Optional[Any] = Query(10, description="Max items to return. Pass 0 for unlimited."),
    offset: Optional[Any] = Query(0, description="Number of items to skip."),
    date_from: Optional[str] = Query(None, description="Start date (YYYY-MM-DD)"),
    date_to: Optional[str] = Query(None, description="End date (YYYY-MM-DD)"),
    base_currency: Optional[str] = Query(None),
    tenant_ids: Optional[str] = Query(None, description="Comma-separated list of tenant UUIDs"),
    company_ids: Optional[str] = Query(None, description="Comma-separated list of company integer IDs"),
) -> dict[str, Any]:
    return await KPIService.get_top_products(
        limit=_val_int(limit, 10), offset=_val_int(offset, 0), descending=True, base_currency=_val_str(base_currency),
        tenant_ids=_parse_csv_str(tenant_ids),
        company_ids=_parse_csv_int(company_ids),
        date_from=_val_str(date_from),
        date_to=_val_str(date_to),
    )


@router.get("/bottom-products", dependencies=[_view_kpi])
async def get_bottom_products(
    limit: Optional[Any] = Query(10, description="Max items to return. Pass 0 for unlimited."),
    offset: Optional[Any] = Query(0, description="Number of items to skip."),
    date_from: Optional[str] = Query(None, description="Start date (YYYY-MM-DD)"),
    date_to: Optional[str] = Query(None, description="End date (YYYY-MM-DD)"),
    base_currency: Optional[str] = Query(None),
    tenant_ids: Optional[str] = Query(None, description="Comma-separated list of tenant UUIDs"),
    company_ids: Optional[str] = Query(None, description="Comma-separated list of company integer IDs"),
) -> dict[str, Any]:
    return await KPIService.get_top_products(
        limit=_val_int(limit, 10), offset=_val_int(offset, 0), descending=False, base_currency=_val_str(base_currency),
        tenant_ids=_parse_csv_str(tenant_ids),
        company_ids=_parse_csv_int(company_ids),
        date_from=_val_str(date_from),
        date_to=_val_str(date_to),
    )


@router.get(
    "/products/{product_id}/detail",
    dependencies=[_view_kpi],
    response_model=ProductDetail,
    summary="Product detail with sales history",
    description=(
        "Returns a specific product's profile including total quantity sold, revenue, and margin, "
        "along with a paginated list of all sales order lines involving this product within the date range."
    ),
)
async def get_product_detail(
    product_id: int,
    order_limit: Optional[Any] = Query(50, description="Orders to return for this product"),
    order_offset: Optional[Any] = Query(0, description="Orders to skip for this product"),
    date_from: Optional[str] = Query(None, description="Start date (YYYY-MM-DD)"),
    date_to: Optional[str] = Query(None, description="End date (YYYY-MM-DD)"),
    tenant_ids: Optional[str] = Query(None, description="Comma-separated list of tenant UUIDs"),
    company_ids: Optional[str] = Query(None, description="Comma-separated list of company integer IDs"),
) -> ProductDetail:
    return await KPIService.get_product_detail(
        product_id, _val_int(order_limit, 50), _val_int(order_offset, 0),
        tenant_ids=_parse_csv_str(tenant_ids),
        company_ids=_parse_csv_int(company_ids),
        date_from=_val_str(date_from),
        date_to=_val_str(date_to),
    )


@router.get("/top-customers", dependencies=[_view_kpi])
async def get_top_customers(
    limit: Optional[Any] = Query(10, description="Max items to return. Pass 0 for unlimited."),
    offset: Optional[Any] = Query(0, description="Number of items to skip."),
    date_from: Optional[str] = Query(None, description="Start date (YYYY-MM-DD)"),
    date_to: Optional[str] = Query(None, description="End date (YYYY-MM-DD)"),
    base_currency: Optional[str] = Query(None),
    tenant_ids: Optional[str] = Query(None, description="Comma-separated list of tenant UUIDs"),
    company_ids: Optional[str] = Query(None, description="Comma-separated list of company integer IDs"),
) -> dict[str, Any]:
    return await KPIService.get_top_customers(
        limit=_val_int(limit, 10), offset=_val_int(offset, 0), base_currency=_val_str(base_currency),
        tenant_ids=_parse_csv_str(tenant_ids),
        company_ids=_parse_csv_int(company_ids),
        date_from=_val_str(date_from),
        date_to=_val_str(date_to),
    )


@router.get(
    "/customers/{customer_id}/detail",
    dependencies=[_view_kpi],
    response_model=CustomerDetail,
    summary="Customer detail with orders",
    description=(
        "Returns a specific customer's profile including full contact details "
        "(email, phone, city, country) and a paginated list of their sales orders within the date range, "
        "each with a receipt-level breakdown of order lines."
    ),
)
async def get_customer_detail(
    customer_id: int,
    order_limit: Optional[Any] = Query(50, description="Orders to return for this customer"),
    order_offset: Optional[Any] = Query(0, description="Orders to skip for this customer"),
    date_from: Optional[str] = Query(None, description="Start date (YYYY-MM-DD)"),
    date_to: Optional[str] = Query(None, description="End date (YYYY-MM-DD)"),
    tenant_ids: Optional[str] = Query(None, description="Comma-separated list of tenant UUIDs"),
    company_ids: Optional[str] = Query(None, description="Comma-separated list of company integer IDs"),
) -> CustomerDetail:
    return await KPIService.get_customer_detail(
        customer_id, _val_int(order_limit, 50), _val_int(order_offset, 0),
        tenant_ids=_parse_csv_str(tenant_ids),
        company_ids=_parse_csv_int(company_ids),
        date_from=_val_str(date_from),
        date_to=_val_str(date_to),
    )


@router.get("/receivables-aging", dependencies=[_view_kpi])
async def get_receivables_aging(
    date_from: Optional[str] = Query(None, description="Start date (YYYY-MM-DD)"),
    date_to: Optional[str] = Query(None, description="End date / As of date (YYYY-MM-DD). Defaults to today."),
    as_of_date: Optional[str] = Query(None, description="Aging reference date (YYYY-MM-DD)"),
    tenant_ids: Optional[str] = Query(None, description="Comma-separated list of tenant UUIDs"),
    company_ids: Optional[str] = Query(None, description="Comma-separated list of company integer IDs"),
) -> dict[str, Any]:
    return await KPIService.get_receivables_aging(
        tenant_ids=_parse_csv_str(tenant_ids),
        company_ids=_parse_csv_int(company_ids),
        as_of_date=_val_str(as_of_date) or _val_str(date_to) or _val_str(date_from),
    )


@router.get(
    "/receivables-aging/detail",
    dependencies=[_view_kpi],
    response_model=AgingBucketDetailResponse,
    summary="Receivables aging bucket detail",
    description=(
        "Returns paginated invoices for a specific aging bucket as of the specified date. "
        "Includes invoice amount, dates, and full client details. "
        "**bucket** values: `current`, `1-30`, `31-60`, `61-90`, `90+`"
    ),
)
async def get_receivables_aging_detail(
    bucket: str = Query(..., description="Aging bucket: current | 1-30 | 31-60 | 61-90 | 90+"),
    limit: Optional[Any] = Query(50, description="Number of invoices to return"),
    offset: Optional[Any] = Query(0, description="Number of invoices to skip"),
    date_from: Optional[str] = Query(None, description="Start date (YYYY-MM-DD)"),
    date_to: Optional[str] = Query(None, description="End date / As of date (YYYY-MM-DD). Defaults to today."),
    as_of_date: Optional[str] = Query(None, description="Aging reference date (YYYY-MM-DD)"),
    tenant_ids: Optional[str] = Query(None, description="Comma-separated list of tenant UUIDs"),
    company_ids: Optional[str] = Query(None, description="Comma-separated list of company integer IDs"),
) -> AgingBucketDetailResponse:
    return await KPIService.get_receivables_aging_detail(
        str(bucket), _val_int(limit, 50), _val_int(offset, 0),
        tenant_ids=_parse_csv_str(tenant_ids),
        company_ids=_parse_csv_int(company_ids),
        as_of_date=_val_str(as_of_date) or _val_str(date_to) or _val_str(date_from),
    )


@router.get("/fast-moving-products", dependencies=[_view_kpi])
async def get_fast_moving_products(
    limit: Optional[Any] = Query(10, description="Max items to return. Pass 0 for unlimited."),
    offset: Optional[Any] = Query(0, description="Number of items to skip."),
    date_from: Optional[str] = Query(None, description="Start date (YYYY-MM-DD)"),
    date_to: Optional[str] = Query(None, description="End date (YYYY-MM-DD)"),
    tenant_ids: Optional[str] = Query(None, description="Comma-separated list of tenant UUIDs"),
    company_ids: Optional[str] = Query(None, description="Comma-separated list of company integer IDs"),
) -> dict[str, Any]:
    return await KPIService.get_fast_moving_products(
        limit=_val_int(limit, 10), offset=_val_int(offset, 0),
        tenant_ids=_parse_csv_str(tenant_ids),
        company_ids=_parse_csv_int(company_ids),
        date_from=_val_str(date_from),
        date_to=_val_str(date_to),
    )


@router.get("/category-performance", dependencies=[_view_kpi])
async def get_category_performance(
    limit: Optional[Any] = Query(10, description="Max items to return. Pass 0 for unlimited."),
    offset: Optional[Any] = Query(0, description="Number of items to skip."),
    date_from: Optional[str] = Query(None, description="Start date (YYYY-MM-DD)"),
    date_to: Optional[str] = Query(None, description="End date (YYYY-MM-DD)"),
    tenant_ids: Optional[str] = Query(None, description="Comma-separated list of tenant UUIDs"),
    company_ids: Optional[str] = Query(None, description="Comma-separated list of company integer IDs"),
) -> dict[str, Any]:
    return await KPIService.get_category_performance(
        limit=_val_int(limit, 10), offset=_val_int(offset, 0),
        tenant_ids=_parse_csv_str(tenant_ids),
        company_ids=_parse_csv_int(company_ids),
        date_from=_val_str(date_from),
        date_to=_val_str(date_to),
    )


@router.get("/currency-impact", dependencies=[_view_kpi], response_model=CurrencyExposureResponse)
async def get_currency_impact(
    base_currency: Optional[str] = Query(None, description="Base currency code (e.g. USD, EUR). Defaults to company's primary currency."),
    date_from: Optional[str] = Query(None, description="Start date (YYYY-MM-DD)"),
    date_to: Optional[str] = Query(None, description="End date (YYYY-MM-DD)"),
    tenant_ids: Optional[str] = Query(None, description="Comma-separated list of tenant UUIDs"),
    company_ids: Optional[str] = Query(None, description="Comma-separated list of company integer IDs"),
) -> CurrencyExposureResponse:
    return await KPIService.get_currency_impact(
        base_currency=_val_str(base_currency),
        tenant_ids=_parse_csv_str(tenant_ids),
        company_ids=_parse_csv_int(company_ids),
        date_from=_val_str(date_from),
        date_to=_val_str(date_to),
    )


# ── Revenues ──────────────────────────────────────────────────────────────────

@router.get(
    "/revenues",
    dependencies=[_view_kpi],
    response_model=KPIPeriodDetailResponse,
    summary="Itemised revenues over date range",
    description="Itemised list of confirmed/done sales orders within the specified date range across all tenants.",
)
async def get_revenues(
    date_from: Optional[str] = Query(None, description="Start date (YYYY-MM-DD)"),
    date_to: Optional[str] = Query(None, description="End date (YYYY-MM-DD)"),
    limit: Optional[Any] = Query(50, description="Number of items to return"),
    offset: Optional[Any] = Query(0, description="Number of items to skip"),
    base_currency: Optional[str] = Query(None),
    tenant_ids: Optional[str] = Query(None, description="Comma-separated list of tenant UUIDs"),
    company_ids: Optional[str] = Query(None, description="Comma-separated list of company integer IDs"),
) -> dict[str, Any]:
    return await KPIService.get_period_detail(
        "revenues",
        date_from=_val_str(date_from),
        date_to=_val_str(date_to),
        limit=_val_int(limit, 50),
        offset=_val_int(offset, 0),
        base_currency=_val_str(base_currency),
        tenant_ids=_parse_csv_str(tenant_ids),
        company_ids=_parse_csv_int(company_ids),
    )


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
    limit: Optional[Any] = Query(50, description="Number of items to return"),
    offset: Optional[Any] = Query(0, description="Number of items to skip"),
    base_currency: Optional[str] = Query(None),
    tenant_ids: Optional[str] = Query(None, description="Comma-separated list of tenant UUIDs"),
    company_ids: Optional[str] = Query(None, description="Comma-separated list of company integer IDs"),
) -> dict[str, Any]:
    return await KPIService.get_period_detail(
        "revenues", period="today", date_str=_val_str(date), limit=_val_int(limit, 50), offset=_val_int(offset, 0), base_currency=_val_str(base_currency),
        tenant_ids=_parse_csv_str(tenant_ids), company_ids=_parse_csv_int(company_ids)
    )


@router.get(
    "/revenues/monthly",
    dependencies=[_view_kpi],
    response_model=KPIPeriodDetailResponse,
    summary="Monthly revenues — all tenants",
    description="Itemised sales order revenues for the current calendar month across all tenants.",
)
async def get_revenues_monthly(
    date: Optional[str] = Query(None, description="ISO date (YYYY-MM-DD). Defaults to server today."),
    limit: Optional[Any] = Query(50, description="Number of items to return"),
    offset: Optional[Any] = Query(0, description="Number of items to skip"),
    base_currency: Optional[str] = Query(None),
    tenant_ids: Optional[str] = Query(None, description="Comma-separated list of tenant UUIDs"),
    company_ids: Optional[str] = Query(None, description="Comma-separated list of company integer IDs"),
) -> dict[str, Any]:
    return await KPIService.get_period_detail(
        "revenues", period="monthly", date_str=_val_str(date), limit=_val_int(limit, 50), offset=_val_int(offset, 0), base_currency=_val_str(base_currency),
        tenant_ids=_parse_csv_str(tenant_ids), company_ids=_parse_csv_int(company_ids)
    )


@router.get(
    "/revenues/yearly",
    dependencies=[_view_kpi],
    response_model=KPIPeriodDetailResponse,
    summary="Yearly revenues — all tenants",
    description="Itemised sales order revenues for the current calendar year across all tenants.",
)
async def get_revenues_yearly(
    date: Optional[str] = Query(None, description="ISO date (YYYY-MM-DD). Defaults to server today."),
    limit: Optional[Any] = Query(50, description="Number of items to return"),
    offset: Optional[Any] = Query(0, description="Number of items to skip"),
    base_currency: Optional[str] = Query(None),
    tenant_ids: Optional[str] = Query(None, description="Comma-separated list of tenant UUIDs"),
    company_ids: Optional[str] = Query(None, description="Comma-separated list of company integer IDs"),
) -> dict[str, Any]:
    return await KPIService.get_period_detail(
        "revenues", period="yearly", date_str=_val_str(date), limit=_val_int(limit, 50), offset=_val_int(offset, 0), base_currency=_val_str(base_currency),
        tenant_ids=_parse_csv_str(tenant_ids), company_ids=_parse_csv_int(company_ids)
    )


# ── Expenses ──────────────────────────────────────────────────────────────────

@router.get(
    "/expenses",
    dependencies=[_view_kpi],
    response_model=KPIPeriodDetailResponse,
    summary="Itemised expenses over date range",
    description="Itemised list of confirmed/done purchase orders within the specified date range across all tenants.",
)
async def get_expenses(
    date_from: Optional[str] = Query(None, description="Start date (YYYY-MM-DD)"),
    date_to: Optional[str] = Query(None, description="End date (YYYY-MM-DD)"),
    limit: Optional[Any] = Query(50, description="Number of items to return"),
    offset: Optional[Any] = Query(0, description="Number of items to skip"),
    base_currency: Optional[str] = Query(None),
    tenant_ids: Optional[str] = Query(None, description="Comma-separated list of tenant UUIDs"),
    company_ids: Optional[str] = Query(None, description="Comma-separated list of company integer IDs"),
) -> dict[str, Any]:
    return await KPIService.get_period_detail(
        "expenses",
        date_from=_val_str(date_from),
        date_to=_val_str(date_to),
        limit=_val_int(limit, 50),
        offset=_val_int(offset, 0),
        base_currency=_val_str(base_currency),
        tenant_ids=_parse_csv_str(tenant_ids),
        company_ids=_parse_csv_int(company_ids),
    )


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
    limit: Optional[Any] = Query(50, description="Number of items to return"),
    offset: Optional[Any] = Query(0, description="Number of items to skip"),
    base_currency: Optional[str] = Query(None),
    tenant_ids: Optional[str] = Query(None, description="Comma-separated list of tenant UUIDs"),
    company_ids: Optional[str] = Query(None, description="Comma-separated list of company integer IDs"),
) -> dict[str, Any]:
    return await KPIService.get_period_detail(
        "expenses", period="today", date_str=_val_str(date), limit=_val_int(limit, 50), offset=_val_int(offset, 0), base_currency=_val_str(base_currency),
        tenant_ids=_parse_csv_str(tenant_ids), company_ids=_parse_csv_int(company_ids)
    )


@router.get(
    "/expenses/monthly",
    dependencies=[_view_kpi],
    response_model=KPIPeriodDetailResponse,
    summary="Monthly expenses — all tenants",
    description="Itemised purchase order expenses for the current calendar month across all tenants.",
)
async def get_expenses_monthly(
    date: Optional[str] = Query(None, description="ISO date (YYYY-MM-DD). Defaults to server today."),
    limit: Optional[Any] = Query(50, description="Number of items to return"),
    offset: Optional[Any] = Query(0, description="Number of items to skip"),
    base_currency: Optional[str] = Query(None),
    tenant_ids: Optional[str] = Query(None, description="Comma-separated list of tenant UUIDs"),
    company_ids: Optional[str] = Query(None, description="Comma-separated list of company integer IDs"),
) -> dict[str, Any]:
    return await KPIService.get_period_detail(
        "expenses", period="monthly", date_str=_val_str(date), limit=_val_int(limit, 50), offset=_val_int(offset, 0), base_currency=_val_str(base_currency),
        tenant_ids=_parse_csv_str(tenant_ids), company_ids=_parse_csv_int(company_ids)
    )


@router.get(
    "/expenses/yearly",
    dependencies=[_view_kpi],
    response_model=KPIPeriodDetailResponse,
    summary="Yearly expenses — all tenants",
    description="Itemised purchase order expenses for the current calendar year across all tenants.",
)
async def get_expenses_yearly(
    date: Optional[str] = Query(None, description="ISO date (YYYY-MM-DD). Defaults to server today."),
    limit: Optional[Any] = Query(50, description="Number of items to return"),
    offset: Optional[Any] = Query(0, description="Number of items to skip"),
    base_currency: Optional[str] = Query(None),
    tenant_ids: Optional[str] = Query(None, description="Comma-separated list of tenant UUIDs"),
    company_ids: Optional[str] = Query(None, description="Comma-separated list of company integer IDs"),
) -> dict[str, Any]:
    return await KPIService.get_period_detail(
        "expenses", period="yearly", date_str=_val_str(date), limit=_val_int(limit, 50), offset=_val_int(offset, 0), base_currency=_val_str(base_currency),
        tenant_ids=_parse_csv_str(tenant_ids), company_ids=_parse_csv_int(company_ids)
    )


# ── Profits ───────────────────────────────────────────────────────────────────

@router.get(
    "/profits",
    dependencies=[_view_kpi],
    response_model=KPIPeriodDetailResponse,
    summary="Itemised profits over date range",
    description="Revenue items, expense items and net profit for the specified date range across all tenants.",
)
async def get_profits(
    date_from: Optional[str] = Query(None, description="Start date (YYYY-MM-DD)"),
    date_to: Optional[str] = Query(None, description="End date (YYYY-MM-DD)"),
    limit: Optional[Any] = Query(50, description="Number of items to return"),
    offset: Optional[Any] = Query(0, description="Number of items to skip"),
    base_currency: Optional[str] = Query(None),
    tenant_ids: Optional[str] = Query(None, description="Comma-separated list of tenant UUIDs"),
    company_ids: Optional[str] = Query(None, description="Comma-separated list of company integer IDs"),
) -> dict[str, Any]:
    return await KPIService.get_period_detail(
        "profits",
        date_from=_val_str(date_from),
        date_to=_val_str(date_to),
        limit=_val_int(limit, 50),
        offset=_val_int(offset, 0),
        base_currency=_val_str(base_currency),
        tenant_ids=_parse_csv_str(tenant_ids),
        company_ids=_parse_csv_int(company_ids),
    )


@router.get(
    "/profits/today",
    dependencies=[_view_kpi],
    response_model=KPIPeriodDetailResponse,
    summary="Today's profits — all tenants",
    description="Revenue items, expense items and net profit for today across all tenants.",
)
async def get_profits_today(
    date: Optional[str] = Query(None, description="ISO date (YYYY-MM-DD). Defaults to server today."),
    limit: Optional[Any] = Query(50, description="Number of items to return"),
    offset: Optional[Any] = Query(0, description="Number of items to skip"),
    base_currency: Optional[str] = Query(None),
    tenant_ids: Optional[str] = Query(None, description="Comma-separated list of tenant UUIDs"),
    company_ids: Optional[str] = Query(None, description="Comma-separated list of company integer IDs"),
) -> dict[str, Any]:
    return await KPIService.get_period_detail(
        "profits", period="today", date_str=_val_str(date), limit=_val_int(limit, 50), offset=_val_int(offset, 0), base_currency=_val_str(base_currency),
        tenant_ids=_parse_csv_str(tenant_ids), company_ids=_parse_csv_int(company_ids)
    )


@router.get(
    "/profits/monthly",
    dependencies=[_view_kpi],
    response_model=KPIPeriodDetailResponse,
    summary="Monthly profits — all tenants",
    description="Revenue items, expense items and net profit for the current calendar month across all tenants.",
)
async def get_profits_monthly(
    date: Optional[str] = Query(None, description="ISO date (YYYY-MM-DD). Defaults to server today."),
    limit: Optional[Any] = Query(50, description="Number of items to return"),
    offset: Optional[Any] = Query(0, description="Number of items to skip"),
    base_currency: Optional[str] = Query(None),
    tenant_ids: Optional[str] = Query(None, description="Comma-separated list of tenant UUIDs"),
    company_ids: Optional[str] = Query(None, description="Comma-separated list of company integer IDs"),
) -> dict[str, Any]:
    return await KPIService.get_period_detail(
        "profits", period="monthly", date_str=_val_str(date), limit=_val_int(limit, 50), offset=_val_int(offset, 0), base_currency=_val_str(base_currency),
        tenant_ids=_parse_csv_str(tenant_ids), company_ids=_parse_csv_int(company_ids)
    )


@router.get(
    "/profits/yearly",
    dependencies=[_view_kpi],
    response_model=KPIPeriodDetailResponse,
    summary="Yearly profits — all tenants",
    description="Revenue items, expense items and net profit for the current calendar year across all tenants.",
)
async def get_profits_yearly(
    date: Optional[str] = Query(None, description="ISO date (YYYY-MM-DD). Defaults to server today."),
    limit: Optional[Any] = Query(50, description="Number of items to return"),
    offset: Optional[Any] = Query(0, description="Number of items to skip"),
    base_currency: Optional[str] = Query(None),
    tenant_ids: Optional[str] = Query(None, description="Comma-separated list of tenant UUIDs"),
    company_ids: Optional[str] = Query(None, description="Comma-separated list of company integer IDs"),
) -> dict[str, Any]:
    return await KPIService.get_period_detail(
        "profits", period="yearly", date_str=_val_str(date), limit=_val_int(limit, 50), offset=_val_int(offset, 0), base_currency=_val_str(base_currency),
        tenant_ids=_parse_csv_str(tenant_ids), company_ids=_parse_csv_int(company_ids)
    )
