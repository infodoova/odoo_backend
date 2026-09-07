"""
Sales API routes
"""

from fastapi import APIRouter, Depends, Query, HTTPException
from fastapi.responses import Response, StreamingResponse
from typing import Any, List, Optional
from datetime import date
from odoo_app.models import AppUser
from doova_one_view.api.dependencies import get_current_user
from doova_one_view.api.auth.permissions import require_permissions, require_any_permission

_view_sales_overview = Depends(require_permissions("view_sales_overview"))
_view_sales_orders   = Depends(require_permissions("view_sales_orders"))
_export_sales_orders = Depends(require_permissions("export_sales_orders"))
from doova_one_view.api.common.utils import parse_company_ids
from doova_one_view.api.common.schemas import PaginatedResponse
from doova_one_view.api.sales.schemas import (
    SearchRequest,
    SalesDashboard,
    SalesOrderRead,
    SalesOrderWithLinesRead,
    MetricDetailResponse,
    DailyOrdersResponse,
    MarketBreakdownResponse,
    EntityProfileResponse,
    ProductSalesDetailResponse,
    CustomerMetricsResponse
)
from doova_one_view.api.sales.service import SalesService
from doova_one_view.api.tenants.service import TenantService

router = APIRouter(prefix="/sales", tags=["Sales"])

@router.get("/{tenant_id}/dashboard")
async def get_sales_dashboard(
    tenant_id: str,
    start_date: Optional[str] = Query(None, description="Start date (YYYY-MM-DD)"),
    end_date: Optional[str] = Query(None, description="End date (YYYY-MM-DD)"),
    company_ids: Optional[str] = Query(None, description="Comma-separated or JSON list of company IDs"),
    base_currency: Optional[str] = Query(None, description="Target currency for financial values"),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    user: AppUser = _view_sales_overview
) -> SalesDashboard:
    """Get comprehensive sales dashboard metrics for a tenant"""
    await TenantService.get_tenant(tenant_id, str(user.id))
    company_ids = parse_company_ids(company_ids)
    return await SalesService.get_dashboard(tenant_id, start_date, end_date, company_ids, base_currency)

@router.get("/{tenant_id}/dashboard/metric-details")
async def get_dashboard_metric_details(
    tenant_id: str,
    metric: str = Query(..., description="The metric name (e.g., total_revenue, total_profit, pipeline_value, order_count, avg_order_value)"),
    start_date: Optional[str] = Query(None, description="Start date (YYYY-MM-DD)"),
    end_date: Optional[str] = Query(None, description="End date (YYYY-MM-DD)"),
    company_ids: Optional[str] = Query(None, description="Comma-separated or JSON list of company IDs"),
    base_currency: Optional[str] = Query(None, description="Target currency for financial values"),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    user: AppUser = _view_sales_overview
) -> MetricDetailResponse:
    """Get detailed order breakdown for a specific dashboard metric"""
    await TenantService.get_tenant(tenant_id, str(user.id))
    company_ids = parse_company_ids(company_ids)
    return await SalesService.get_dashboard_metric_details(
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
    company_ids: Optional[str] = Query(None, description="Comma-separated or JSON list of company IDs"),
    base_currency: Optional[str] = Query(None, description="Target currency for financial values"),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    user: AppUser = _view_sales_overview
) -> DailyOrdersResponse:
    """Get all confirmed orders placed on a specific calendar day (Daily Performance drill-down)"""
    await TenantService.get_tenant(tenant_id, str(user.id))
    company_ids = parse_company_ids(company_ids)
    return await SalesService.get_daily_orders(
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
    section: str = Query(..., description="Section name: top_customers, top_products, or top_salespeople"),
    entity_id: int = Query(..., description="The entity ID (partner_id / product_id / user_id)"),
    start_date: Optional[str] = Query(None, description="Start date (YYYY-MM-DD)"),
    end_date: Optional[str] = Query(None, description="End date (YYYY-MM-DD)"),
    company_ids: Optional[str] = Query(None, description="Comma-separated or JSON list of company IDs"),
    base_currency: Optional[str] = Query(None, description="Target currency for financial values"),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    user: AppUser = _view_sales_overview
) -> MarketBreakdownResponse:
    """Drill into a market-breakdown entity to see confirmed orders for a specific customer, product, or salesperson"""
    await TenantService.get_tenant(tenant_id, str(user.id))
    company_ids = parse_company_ids(company_ids)
    return await SalesService.get_market_breakdown_details(
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

@router.get("/{tenant_id}/dashboard/entity-profile")
async def get_entity_profile(
    tenant_id: str,
    entity_type: str = Query(..., description="'salesperson' or 'customer'"),
    entity_id: int = Query(..., description="The entity's Django pk (same ID from dashboard rankings)"),
    user: AppUser = _view_sales_overview
) -> EntityProfileResponse:
    """Get profile details for a salesperson or customer (name, phone, email, etc.)"""
    await TenantService.get_tenant(tenant_id, str(user.id))
    return await SalesService.get_entity_profile(
        tenant_id=tenant_id,
        entity_type=entity_type,
        entity_id=entity_id
    )

@router.get("/{tenant_id}/dashboard/product-sales-details")
async def get_product_sales_details(
    tenant_id: str,
    product_id: int = Query(..., description="The product's Django pk (same ID from top_products)"),
    start_date: Optional[str] = Query(None, description="Start date (YYYY-MM-DD)"),
    end_date: Optional[str] = Query(None, description="End date (YYYY-MM-DD)"),
    company_ids: Optional[str] = Query(None, description="Comma-separated or JSON list of company IDs"),
    base_currency: Optional[str] = Query(None, description="Target currency for financial values"),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    user: AppUser = _view_sales_overview
) -> ProductSalesDetailResponse:
    """Get every sale-line for a specific product — when sold, how many pieces, price, customer, etc."""
    await TenantService.get_tenant(tenant_id, str(user.id))
    company_ids = parse_company_ids(company_ids)
    return await SalesService.get_product_sales_details(
        tenant_id=tenant_id,
        product_id=product_id,
        start_date=start_date,
        end_date=end_date,
        company_ids=company_ids,
        base_currency=base_currency,
        limit=limit,
        offset=offset
    )

@router.get("/{tenant_id}/customer-metrics")
async def get_customer_metrics(
    tenant_id: str,
    start_date: Optional[str] = Query(None, description="Start date (YYYY-MM-DD)"),
    end_date: Optional[str] = Query(None, description="End date (YYYY-MM-DD)"),
    company_ids: Optional[str] = Query(None, description="Comma-separated or JSON list of company IDs"),
    partner_id: Optional[int] = Query(None, description="Filter by a specific customer"),
    user: AppUser = _view_sales_overview
) -> CustomerMetricsResponse:
    """Calculate and return Purchase Frequency and Customer Lifespan."""
    await TenantService.get_tenant(tenant_id, str(user.id))
    company_ids = parse_company_ids(company_ids)
    return await SalesService.get_customer_metrics(
        tenant_id=tenant_id,
        start_date=start_date,
        end_date=end_date,
        company_ids=company_ids,
        partner_id=partner_id
    )

@router.get("/{tenant_id}/kpis")
async def get_sales_kpis(
    tenant_id: str,
    start_date: Optional[str] = Query(None, description="Start date (YYYY-MM-DD)"),
    end_date: Optional[str] = Query(None, description="End date (YYYY-MM-DD)"),
    company_ids: Optional[str] = Query(None, description="Comma-separated or JSON list of company IDs"),
    base_currency: Optional[str] = Query(None, description="Target currency for financial values"),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    user: AppUser = _view_sales_overview
) -> SalesDashboard:
    """Alias for dashboard"""
    await TenantService.get_tenant(tenant_id, str(user.id))
    company_ids = parse_company_ids(company_ids)
    return await SalesService.get_dashboard(tenant_id, start_date, end_date, company_ids, base_currency)

@router.get("/{tenant_id}/orders")
async def list_sales_orders(
    tenant_id: str,
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    partner_id: Optional[int] = None,
    company_ids: Optional[str] = Query(None, description="Comma-separated or JSON list of company IDs"),
    user: AppUser = _view_sales_orders
) -> PaginatedResponse[SalesOrderRead]:
    """List sales orders for a tenant"""
    await TenantService.get_tenant(tenant_id, str(user.id))
    company_ids = parse_company_ids(company_ids)
    return await SalesService.get_orders(tenant_id, limit, offset, partner_id, company_ids)

@router.get("/{tenant_id}/filters")
async def get_sales_filters(
    tenant_id: str,
    user: AppUser = _view_sales_orders
) -> dict[str, Any]:
    """Get distinct values for filtering sales orders"""
    await TenantService.get_tenant(tenant_id, str(user.id))
    return await SalesService.get_filters(tenant_id)

@router.get("/{tenant_id}/orders/{order_id}")
async def get_sales_order(
    tenant_id: str,
    order_id: int,
    company_ids: Optional[str] = Query(None, description="Comma-separated or JSON list of company IDs"),
    user: AppUser = _view_sales_orders
) -> SalesOrderWithLinesRead:
    """Get a specific sales order with its lines"""
    await TenantService.get_tenant(tenant_id, str(user.id))
    company_ids = parse_company_ids(company_ids)
    return await SalesService.get_order(tenant_id, order_id, company_ids)

@router.get("/{tenant_id}/export")
async def export_sales_orders(
    tenant_id: str,
    company_ids: Optional[str] = Query(None, description="Comma-separated or JSON list of company IDs"),
    user: AppUser = _export_sales_orders
) -> Response:
    """Export sales orders to CSV"""
    await TenantService.get_tenant(tenant_id, str(user.id))
    company_ids = parse_company_ids(company_ids)
    csv_content = await SalesService.export_orders_csv(tenant_id, company_ids)
    
    return Response(
        content=csv_content,
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename=sales_orders_{tenant_id}.csv"}
    )

@router.post("/{tenant_id}/search")
async def search_sales_orders(
    tenant_id: str,
    request: SearchRequest,
    user: AppUser = _view_sales_orders
) -> PaginatedResponse[SalesOrderRead]:
    """Advanced search for sales orders with complex filters"""
    await TenantService.get_tenant(tenant_id, str(user.id))
    company_ids = parse_company_ids(request.companies)
    return await SalesService.search_orders(
        tenant_id, request.filters, request.limit, request.offset, company_ids
    )
