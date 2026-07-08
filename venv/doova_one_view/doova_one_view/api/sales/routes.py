"""
Sales API routes
"""

from fastapi import APIRouter, Depends, Query, HTTPException
from fastapi.responses import Response, StreamingResponse
from typing import Any, List, Optional
from datetime import date
from odoo_app.models import AppUser
from doova_one_view.api.dependencies import get_current_user
from doova_one_view.api.common.utils import parse_company_ids
from doova_one_view.api.common.schemas import PaginatedResponse
from doova_one_view.api.sales.schemas import (
    SearchRequest,
    SalesDashboard,
    SalesOrderRead,
    SalesOrderWithLinesRead
)
from doova_one_view.api.sales.service import SalesService
from doova_one_view.api.tenants.service import TenantService

router = APIRouter(prefix="/sales", tags=["Sales"])

@router.get("/{tenant_id}/dashboard")
async def get_sales_dashboard(
    tenant_id: str,
    start_date: Optional[str] = Query(None, description="Start date (YYYY-MM-DD)"),
    end_date: Optional[str] = Query(None, description="End date (YYYY-MM-DD)"),
    companies: Optional[str] = Query(None, description="Single ID or comma-separated IDs"),
    base_currency: Optional[str] = Query(None, description="Target currency for financial values"),
    user: AppUser = Depends(get_current_user)
) -> SalesDashboard:
    """Get comprehensive sales dashboard metrics for a tenant"""
    await TenantService.get_tenant(tenant_id, str(user.id))
    company_ids = parse_company_ids(companies)
    return await SalesService.get_dashboard(tenant_id, start_date, end_date, company_ids, base_currency)

@router.get("/{tenant_id}/kpis")
async def get_sales_kpis(
    tenant_id: str,
    start_date: Optional[str] = Query(None, description="Start date (YYYY-MM-DD)"),
    end_date: Optional[str] = Query(None, description="End date (YYYY-MM-DD)"),
    companies: Optional[str] = Query(None, description="Single ID or comma-separated IDs"),
    base_currency: Optional[str] = Query(None, description="Target currency for financial values"),
    user: AppUser = Depends(get_current_user)
) -> SalesDashboard:
    """Alias for dashboard"""
    await TenantService.get_tenant(tenant_id, str(user.id))
    company_ids = parse_company_ids(companies)
    return await SalesService.get_dashboard(tenant_id, start_date, end_date, company_ids, base_currency)

@router.get("/{tenant_id}/orders")
async def list_sales_orders(
    tenant_id: str,
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    partner_id: Optional[int] = None,
    companies: Optional[str] = Query(None, description="Single ID or comma-separated IDs"),
    user: AppUser = Depends(get_current_user)
) -> PaginatedResponse[SalesOrderRead]:
    """List sales orders for a tenant"""
    await TenantService.get_tenant(tenant_id, str(user.id))
    company_ids = parse_company_ids(companies)
    return await SalesService.get_orders(tenant_id, limit, offset, partner_id, company_ids)

@router.get("/{tenant_id}/filters")
async def get_sales_filters(
    tenant_id: str,
    user: AppUser = Depends(get_current_user)
) -> dict[str, Any]:
    """Get distinct values for filtering sales orders"""
    await TenantService.get_tenant(tenant_id, str(user.id))
    return await SalesService.get_filters(tenant_id)

@router.get("/{tenant_id}/orders/{order_id}")
async def get_sales_order(
    tenant_id: str,
    order_id: int,
    companies: Optional[str] = Query(None, description="Single ID or comma-separated IDs"),
    user: AppUser = Depends(get_current_user)
) -> SalesOrderWithLinesRead:
    """Get a specific sales order with its lines"""
    await TenantService.get_tenant(tenant_id, str(user.id))
    company_ids = parse_company_ids(companies)
    return await SalesService.get_order(tenant_id, order_id, company_ids)

@router.get("/{tenant_id}/export")
async def export_sales_orders(
    tenant_id: str,
    companies: Optional[str] = Query(None, description="Single ID or comma-separated IDs"),
    user: AppUser = Depends(get_current_user)
) -> Response:
    """Export sales orders to CSV"""
    await TenantService.get_tenant(tenant_id, str(user.id))
    company_ids = parse_company_ids(companies)
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
    user: AppUser = Depends(get_current_user)
) -> PaginatedResponse[SalesOrderRead]:
    """Advanced search for sales orders with complex filters"""
    await TenantService.get_tenant(tenant_id, str(user.id))
    company_ids = parse_company_ids(request.companies)
    return await SalesService.search_orders(
        tenant_id, request.filters, request.limit, request.offset, company_ids
    )
