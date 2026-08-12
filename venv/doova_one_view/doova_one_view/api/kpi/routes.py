from typing import Any, Optional

from fastapi import APIRouter, Depends, Query

from doova_one_view.api.auth.permissions import require_permissions
from doova_one_view.api.kpi.service import KPIService
from doova_one_view.api.kpi.schemas import AgingBucketDetailResponse, KPIPeriodDetailResponse, CustomerDetail, ProductDetail, CurrencyExposureResponse
from typing import Any, Optional

from fastapi import APIRouter, Depends, Query

from doova_one_view.api.auth.permissions import require_permissions
from doova_one_view.api.kpi.service import KPIService
from doova_one_view.api.kpi.schemas import AgingBucketDetailResponse, KPIPeriodDetailResponse, CustomerDetail, ProductDetail, CurrencyExposureResponse

router = APIRouter(prefix="/kpi", tags=["KPI"])

_view_kpi = Depends(require_permissions("view_kpi"))


def _parse_csv_str(val: Optional[str]) -> Optional[list[str]]:
    if not val:
        return None
    items = [x.strip() for x in val.split(',') if x.strip()]
    return items if items else None


def _parse_csv_int(val: Optional[str]) -> Optional[list[int]]:
    if not val:
        return None
    res = []
    for x in val.split(','):
        x = x.strip()
        if x:
            try:
                res.append(int(x))
            except ValueError:
                pass
    return res if res else None


@router.get("/overview", dependencies=[_view_kpi])
async def get_overview(
    date_from: Optional[str] = Query(None),
    date_to: Optional[str] = Query(None),
    base_currency: Optional[str] = Query(None),
    tenant_ids: Optional[str] = Query(None, description="Comma-separated list of tenant UUIDs"),
    company_ids: Optional[str] = Query(None, description="Comma-separated list of company integer IDs"),
) -> dict[str, Any]:
    return await KPIService.get_overview(
        date_from, date_to, base_currency,
        tenant_ids=_parse_csv_str(tenant_ids),
        company_ids=_parse_csv_int(company_ids)
    )


@router.get("/summary", dependencies=[_view_kpi])
async def get_summary(
    date_from: Optional[str] = Query(None),
    date_to: Optional[str] = Query(None),
    base_currency: Optional[str] = Query(None),
    tenant_ids: Optional[str] = Query(None, description="Comma-separated list of tenant UUIDs"),
    company_ids: Optional[str] = Query(None, description="Comma-separated list of company integer IDs"),
) -> dict[str, Any]:
    return await KPIService.get_overview(
        date_from, date_to, base_currency,
        tenant_ids=_parse_csv_str(tenant_ids),
        company_ids=_parse_csv_int(company_ids)
    )


@router.get("/trends", dependencies=[_view_kpi])
async def get_trends(
    date_from: Optional[str] = Query(None),
    date_to: Optional[str] = Query(None),
    base_currency: Optional[str] = Query(None),
    tenant_ids: Optional[str] = Query(None, description="Comma-separated list of tenant UUIDs"),
    company_ids: Optional[str] = Query(None, description="Comma-separated list of company integer IDs"),
) -> dict[str, Any]:
    return await KPIService.get_trends(
        date_from, date_to, base_currency,
        tenant_ids=_parse_csv_str(tenant_ids),
        company_ids=_parse_csv_int(company_ids)
    )


@router.get("/top-products", dependencies=[_view_kpi])
async def get_top_products(
    limit: int = Query(10, ge=0, description="Max items to return. Pass 0 for unlimited."),
    offset: int = Query(0, ge=0, description="Number of items to skip."),
    base_currency: Optional[str] = Query(None),
    tenant_ids: Optional[str] = Query(None, description="Comma-separated list of tenant UUIDs"),
    company_ids: Optional[str] = Query(None, description="Comma-separated list of company integer IDs"),
) -> dict[str, Any]:
    return await KPIService.get_top_products(
        limit=limit, offset=offset, descending=True, base_currency=base_currency,
        tenant_ids=_parse_csv_str(tenant_ids),
        company_ids=_parse_csv_int(company_ids)
    )


@router.get("/bottom-products", dependencies=[_view_kpi])
async def get_bottom_products(
    limit: int = Query(10, ge=0, description="Max items to return. Pass 0 for unlimited."),
    offset: int = Query(0, ge=0, description="Number of items to skip."),
    base_currency: Optional[str] = Query(None),
    tenant_ids: Optional[str] = Query(None, description="Comma-separated list of tenant UUIDs"),
    company_ids: Optional[str] = Query(None, description="Comma-separated list of company integer IDs"),
) -> dict[str, Any]:
    return await KPIService.get_top_products(
        limit=limit, offset=offset, descending=False, base_currency=base_currency,
        tenant_ids=_parse_csv_str(tenant_ids),
        company_ids=_parse_csv_int(company_ids)
    )


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
    tenant_ids: Optional[str] = Query(None, description="Comma-separated list of tenant UUIDs"),
    company_ids: Optional[str] = Query(None, description="Comma-separated list of company integer IDs"),
) -> ProductDetail:
    return await KPIService.get_product_detail(
        product_id, order_limit, order_offset,
        tenant_ids=_parse_csv_str(tenant_ids),
        company_ids=_parse_csv_int(company_ids)
    )


@router.get("/top-customers", dependencies=[_view_kpi])
async def get_top_customers(
    limit: int = Query(10, ge=0, description="Max items to return. Pass 0 for unlimited."),
    offset: int = Query(0, ge=0, description="Number of items to skip."),
    base_currency: Optional[str] = Query(None),
    tenant_ids: Optional[str] = Query(None, description="Comma-separated list of tenant UUIDs"),
    company_ids: Optional[str] = Query(None, description="Comma-separated list of company integer IDs"),
) -> dict[str, Any]:
    return await KPIService.get_top_customers(
        limit=limit, offset=offset, base_currency=base_currency,
        tenant_ids=_parse_csv_str(tenant_ids),
        company_ids=_parse_csv_int(company_ids)
    )


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
    tenant_ids: Optional[str] = Query(None, description="Comma-separated list of tenant UUIDs"),
    company_ids: Optional[str] = Query(None, description="Comma-separated list of company integer IDs"),
) -> CustomerDetail:
    return await KPIService.get_customer_detail(
        customer_id, order_limit, order_offset,
        tenant_ids=_parse_csv_str(tenant_ids),
        company_ids=_parse_csv_int(company_ids)
    )


@router.get("/receivables-aging", dependencies=[_view_kpi])
async def get_receivables_aging(
    tenant_ids: Optional[str] = Query(None, description="Comma-separated list of tenant UUIDs"),
    company_ids: Optional[str] = Query(None, description="Comma-separated list of company integer IDs"),
) -> dict[str, Any]:
    return await KPIService.get_receivables_aging(
        tenant_ids=_parse_csv_str(tenant_ids),
        company_ids=_parse_csv_int(company_ids)
    )


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
    tenant_ids: Optional[str] = Query(None, description="Comma-separated list of tenant UUIDs"),
    company_ids: Optional[str] = Query(None, description="Comma-separated list of company integer IDs"),
) -> AgingBucketDetailResponse:
    return await KPIService.get_receivables_aging_detail(
        bucket, limit, offset,
        tenant_ids=_parse_csv_str(tenant_ids),
        company_ids=_parse_csv_int(company_ids)
    )


@router.get("/fast-moving-products", dependencies=[_view_kpi])
async def get_fast_moving_products(
    limit: int = Query(10, ge=0, description="Max items to return. Pass 0 for unlimited."),
    offset: int = Query(0, ge=0, description="Number of items to skip."),
    tenant_ids: Optional[str] = Query(None, description="Comma-separated list of tenant UUIDs"),
    company_ids: Optional[str] = Query(None, description="Comma-separated list of company integer IDs"),
) -> dict[str, Any]:
    return await KPIService.get_fast_moving_products(
        limit=limit, offset=offset,
        tenant_ids=_parse_csv_str(tenant_ids),
        company_ids=_parse_csv_int(company_ids)
    )


@router.get("/category-performance", dependencies=[_view_kpi])
async def get_category_performance(
    limit: int = Query(10, ge=0, description="Max items to return. Pass 0 for unlimited."),
    offset: int = Query(0, ge=0, description="Number of items to skip."),
    tenant_ids: Optional[str] = Query(None, description="Comma-separated list of tenant UUIDs"),
    company_ids: Optional[str] = Query(None, description="Comma-separated list of company integer IDs"),
) -> dict[str, Any]:
    return await KPIService.get_category_performance(
        limit=limit, offset=offset,
        tenant_ids=_parse_csv_str(tenant_ids),
        company_ids=_parse_csv_int(company_ids)
    )



@router.get("/currency-impact", dependencies=[_view_kpi], response_model=CurrencyExposureResponse)
async def get_currency_impact(
    base_currency: Optional[str] = Query(None, description="Base currency code (e.g. USD, EUR). Defaults to company's primary currency."),
    tenant_ids: Optional[str] = Query(None, description="Comma-separated list of tenant UUIDs"),
    company_ids: Optional[str] = Query(None, description="Comma-separated list of company integer IDs"),
) -> CurrencyExposureResponse:
    return await KPIService.get_currency_impact(
        base_currency=base_currency,
        tenant_ids=_parse_csv_str(tenant_ids),
        company_ids=_parse_csv_int(company_ids)
    )


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
    tenant_ids: Optional[str] = Query(None, description="Comma-separated list of tenant UUIDs"),
    company_ids: Optional[str] = Query(None, description="Comma-separated list of company integer IDs"),
) -> dict[str, Any]:
    return await KPIService.get_period_detail(
        "revenues", "today", date, limit, offset, base_currency,
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
    limit: int = Query(50, ge=1, description="Number of items to return"),
    offset: int = Query(0, ge=0, description="Number of items to skip"),
    base_currency: Optional[str] = Query(None),
    tenant_ids: Optional[str] = Query(None, description="Comma-separated list of tenant UUIDs"),
    company_ids: Optional[str] = Query(None, description="Comma-separated list of company integer IDs"),
) -> dict[str, Any]:
    return await KPIService.get_period_detail(
        "revenues", "monthly", date, limit, offset, base_currency,
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
    limit: int = Query(50, ge=1, description="Number of items to return"),
    offset: int = Query(0, ge=0, description="Number of items to skip"),
    base_currency: Optional[str] = Query(None),
    tenant_ids: Optional[str] = Query(None, description="Comma-separated list of tenant UUIDs"),
    company_ids: Optional[str] = Query(None, description="Comma-separated list of company integer IDs"),
) -> dict[str, Any]:
    return await KPIService.get_period_detail(
        "revenues", "yearly", date, limit, offset, base_currency,
        tenant_ids=_parse_csv_str(tenant_ids), company_ids=_parse_csv_int(company_ids)
    )


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
    tenant_ids: Optional[str] = Query(None, description="Comma-separated list of tenant UUIDs"),
    company_ids: Optional[str] = Query(None, description="Comma-separated list of company integer IDs"),
) -> dict[str, Any]:
    return await KPIService.get_period_detail(
        "expenses", "today", date, limit, offset, base_currency,
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
    limit: int = Query(50, ge=1, description="Number of items to return"),
    offset: int = Query(0, ge=0, description="Number of items to skip"),
    base_currency: Optional[str] = Query(None),
    tenant_ids: Optional[str] = Query(None, description="Comma-separated list of tenant UUIDs"),
    company_ids: Optional[str] = Query(None, description="Comma-separated list of company integer IDs"),
) -> dict[str, Any]:
    return await KPIService.get_period_detail(
        "expenses", "monthly", date, limit, offset, base_currency,
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
    limit: int = Query(50, ge=1, description="Number of items to return"),
    offset: int = Query(0, ge=0, description="Number of items to skip"),
    base_currency: Optional[str] = Query(None),
    tenant_ids: Optional[str] = Query(None, description="Comma-separated list of tenant UUIDs"),
    company_ids: Optional[str] = Query(None, description="Comma-separated list of company integer IDs"),
) -> dict[str, Any]:
    return await KPIService.get_period_detail(
        "expenses", "yearly", date, limit, offset, base_currency,
        tenant_ids=_parse_csv_str(tenant_ids), company_ids=_parse_csv_int(company_ids)
    )


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
    tenant_ids: Optional[str] = Query(None, description="Comma-separated list of tenant UUIDs"),
    company_ids: Optional[str] = Query(None, description="Comma-separated list of company integer IDs"),
) -> dict[str, Any]:
    return await KPIService.get_period_detail(
        "profits", "today", date, limit, offset, base_currency,
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
    limit: int = Query(50, ge=1, description="Number of items to return"),
    offset: int = Query(0, ge=0, description="Number of items to skip"),
    base_currency: Optional[str] = Query(None),
    tenant_ids: Optional[str] = Query(None, description="Comma-separated list of tenant UUIDs"),
    company_ids: Optional[str] = Query(None, description="Comma-separated list of company integer IDs"),
) -> dict[str, Any]:
    return await KPIService.get_period_detail(
        "profits", "monthly", date, limit, offset, base_currency,
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
    limit: int = Query(50, ge=1, description="Number of items to return"),
    offset: int = Query(0, ge=0, description="Number of items to skip"),
    base_currency: Optional[str] = Query(None),
    tenant_ids: Optional[str] = Query(None, description="Comma-separated list of tenant UUIDs"),
    company_ids: Optional[str] = Query(None, description="Comma-separated list of company integer IDs"),
) -> dict[str, Any]:
    return await KPIService.get_period_detail(
        "profits", "yearly", date, limit, offset, base_currency,
        tenant_ids=_parse_csv_str(tenant_ids), company_ids=_parse_csv_int(company_ids)
    )
