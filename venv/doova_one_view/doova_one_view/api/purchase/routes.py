"""
Purchase API routes.
"""

from typing import Any, Optional

from fastapi import APIRouter, Depends, Query
from fastapi.responses import Response

from odoo_app.models import AppUser
from doova_one_view.api.common.schemas import PaginatedResponse
from doova_one_view.api.common.utils import parse_company_ids
from doova_one_view.api.dependencies import get_current_user
from doova_one_view.api.purchase.schemas import (
    PurchaseOrderRead,
    PurchaseOrderWithLinesRead,
    PurchaseSummary,
    SearchRequest,
)
from doova_one_view.api.purchase.service import PurchaseService
from doova_one_view.api.tenants.service import TenantService

router = APIRouter(prefix="/purchase", tags=["Purchase"])


def _company_ids(companies: Optional[str]) -> Optional[list[int]]:
    return parse_company_ids(companies)


@router.get("/{tenant_id}/summary")
async def get_purchase_summary(
    tenant_id: str,
    start_date: Optional[str] = Query(None),
    end_date: Optional[str] = Query(None),
    companies: Optional[str] = Query(None, description="Single ID or comma-separated IDs"),
    base_currency: Optional[str] = Query(None, description="Target currency for financial values"),
    user: AppUser = Depends(get_current_user),
) -> PurchaseSummary:
    """doova-compatible summary plus optional backend filters."""
    await TenantService.get_tenant(tenant_id, str(user.id))
    return await PurchaseService.get_summary(
        tenant_id, start_date, end_date, _company_ids(companies), base_currency
    )


@router.get("/{tenant_id}/dashboard")
async def get_purchase_dashboard(
    tenant_id: str,
    start_date: Optional[str] = Query(None),
    end_date: Optional[str] = Query(None),
    companies: Optional[str] = Query(None, description="Single ID or comma-separated IDs"),
    base_currency: Optional[str] = Query(None, description="Target currency for financial values"),
    user: AppUser = Depends(get_current_user),
) -> dict[str, Any]:
    await TenantService.get_tenant(tenant_id, str(user.id))
    return await PurchaseService.get_dashboard(
        tenant_id, start_date, end_date, _company_ids(companies), base_currency
    )


@router.get("/{tenant_id}/kpis")
async def get_purchase_kpis(
    tenant_id: str,
    start_date: Optional[str] = Query(None),
    end_date: Optional[str] = Query(None),
    companies: Optional[str] = Query(None, description="Single ID or comma-separated IDs"),
    base_currency: Optional[str] = Query(None, description="Target currency for financial values"),
    user: AppUser = Depends(get_current_user),
) -> dict[str, Any]:
    await TenantService.get_tenant(tenant_id, str(user.id))
    return await PurchaseService.get_dashboard(
        tenant_id, start_date, end_date, _company_ids(companies), base_currency
    )


@router.get("/{tenant_id}/orders")
async def list_purchase_orders(
    tenant_id: str,
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    partner_id: Optional[int] = Query(None),
    companies: Optional[str] = Query(None, description="Single ID or comma-separated IDs"),
    user: AppUser = Depends(get_current_user),
) -> PaginatedResponse[PurchaseOrderRead]:
    await TenantService.get_tenant(tenant_id, str(user.id))
    return await PurchaseService.get_orders(
        tenant_id, limit, offset, partner_id, _company_ids(companies)
    )


@router.get("/{tenant_id}/orders/{order_id}")
async def get_purchase_order(
    tenant_id: str,
    order_id: int,
    companies: Optional[str] = Query(None, description="Single ID or comma-separated IDs"),
    user: AppUser = Depends(get_current_user),
) -> PurchaseOrderWithLinesRead:
    await TenantService.get_tenant(tenant_id, str(user.id))
    return await PurchaseService.get_order(
        tenant_id, order_id, _company_ids(companies)
    )


@router.get("/{tenant_id}/filters")
async def get_purchase_filters(
    tenant_id: str,
    user: AppUser = Depends(get_current_user),
) -> dict[str, Any]:
    await TenantService.get_tenant(tenant_id, str(user.id))
    return await PurchaseService.get_filters(tenant_id)


@router.post("/{tenant_id}/search")
async def search_purchase_orders(
    tenant_id: str,
    request: SearchRequest,
    user: AppUser = Depends(get_current_user),
) -> PaginatedResponse[PurchaseOrderRead]:
    await TenantService.get_tenant(tenant_id, str(user.id))
    company_ids = parse_company_ids(request.companies)
    return await PurchaseService.search_orders(
        tenant_id, request.filters, request.limit, request.offset, company_ids
    )


@router.get("/{tenant_id}/export")
async def export_purchase_orders(
    tenant_id: str,
    companies: Optional[str] = Query(None, description="Single ID or comma-separated IDs"),
    user: AppUser = Depends(get_current_user),
) -> Response:
    await TenantService.get_tenant(tenant_id, str(user.id))
    csv_content = await PurchaseService.export_orders_csv(
        tenant_id, _company_ids(companies)
    )
    return Response(
        content=csv_content,
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename=purchase_orders_{tenant_id}.csv"},
    )

# ── Drill-Down Endpoints ────────────────────────────────────────────────────────

from doova_one_view.api.purchase.schemas import (
    MetricDetailResponse, DailyOrdersResponse, MarketBreakdownResponse,
    ProductPurchaseDetailResponse, EntityProfileResponse
)

@router.get("/{tenant_id}/dashboard/metric-details")
async def get_dashboard_metric_details(
    tenant_id: str,
    metric: str = Query(..., description="E.g., total_spend, order_count, avg_order_value, or a state like draft/purchase"),
    start_date: Optional[str] = Query(None, description="Start date (YYYY-MM-DD)"),
    end_date: Optional[str] = Query(None, description="End date (YYYY-MM-DD)"),
    companies: Optional[str] = Query(None, description="Single ID or comma-separated IDs"),
    base_currency: Optional[str] = Query(None, description="Target currency for financial values"),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    user: AppUser = Depends(get_current_user)
) -> MetricDetailResponse:
    await TenantService.get_tenant(tenant_id, str(user.id))
    company_ids = _company_ids(companies)
    return await PurchaseService.get_dashboard_metric_details(
        tenant_id=tenant_id,
        metric=metric,
        start_date=start_date,
        end_date=end_date,
        company_ids=company_ids,
        base_currency=base_currency,
        limit=limit,
        offset=offset
    )

@router.get("/{tenant_id}/dashboard/daily-orders")
async def get_daily_orders(
    tenant_id: str,
    day: str = Query(..., description="The calendar day to drill into (YYYY-MM-DD)"),
    companies: Optional[str] = Query(None, description="Single ID or comma-separated IDs"),
    base_currency: Optional[str] = Query(None, description="Target currency for financial values"),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    user: AppUser = Depends(get_current_user)
) -> DailyOrdersResponse:
    await TenantService.get_tenant(tenant_id, str(user.id))
    company_ids = _company_ids(companies)
    return await PurchaseService.get_daily_orders(
        tenant_id=tenant_id,
        day=day,
        company_ids=company_ids,
        base_currency=base_currency,
        limit=limit,
        offset=offset
    )

@router.get("/{tenant_id}/dashboard/market-breakdown")
async def get_market_breakdown_details(
    tenant_id: str,
    section: str = Query(..., description="top_vendors, top_suppliers, top_products, top_buyers"),
    entity_id: int = Query(..., description="The entity ID (partner_id / product_id / user_id)"),
    start_date: Optional[str] = Query(None, description="Start date (YYYY-MM-DD)"),
    end_date: Optional[str] = Query(None, description="End date (YYYY-MM-DD)"),
    companies: Optional[str] = Query(None, description="Single ID or comma-separated IDs"),
    base_currency: Optional[str] = Query(None, description="Target currency for financial values"),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    user: AppUser = Depends(get_current_user)
) -> MarketBreakdownResponse:
    await TenantService.get_tenant(tenant_id, str(user.id))
    company_ids = _company_ids(companies)
    return await PurchaseService.get_market_breakdown_details(
        tenant_id=tenant_id,
        section=section,
        entity_id=entity_id,
        start_date=start_date,
        end_date=end_date,
        company_ids=company_ids,
        base_currency=base_currency,
        limit=limit,
        offset=offset
    )

@router.get("/{tenant_id}/dashboard/product-purchase-details")
async def get_product_purchase_details(
    tenant_id: str,
    product_id: int = Query(..., description="The product's Django pk"),
    start_date: Optional[str] = Query(None, description="Start date (YYYY-MM-DD)"),
    end_date: Optional[str] = Query(None, description="End date (YYYY-MM-DD)"),
    companies: Optional[str] = Query(None, description="Single ID or comma-separated IDs"),
    base_currency: Optional[str] = Query(None, description="Target currency for financial values"),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    user: AppUser = Depends(get_current_user)
) -> ProductPurchaseDetailResponse:
    await TenantService.get_tenant(tenant_id, str(user.id))
    company_ids = _company_ids(companies)
    return await PurchaseService.get_product_purchase_details(
        tenant_id=tenant_id,
        product_id=product_id,
        start_date=start_date,
        end_date=end_date,
        company_ids=company_ids,
        base_currency=base_currency,
        limit=limit,
        offset=offset
    )

@router.get("/{tenant_id}/dashboard/entity-profile")
async def get_entity_profile(
    tenant_id: str,
    entity_type: str = Query(..., description="'vendor', 'supplier', or 'buyer'"),
    entity_id: int = Query(..., description="The entity's Django pk"),
    user: AppUser = Depends(get_current_user)
) -> EntityProfileResponse:
    await TenantService.get_tenant(tenant_id, str(user.id))
    return await PurchaseService.get_entity_profile(
        tenant_id=tenant_id,
        entity_type=entity_type,
        entity_id=entity_id
    )

