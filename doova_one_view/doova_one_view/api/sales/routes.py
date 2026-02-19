"""
Sales API routes
"""

from fastapi import APIRouter, Depends, Query, HTTPException
from fastapi.responses import StreamingResponse
from typing import List, Optional
from datetime import date
from odoo_app.models import AppUser
from doova_one_view.api.dependencies import get_current_user
from doova_one_view.api.sales.schemas import (
    SalesOrderRead, SalesOrderWithLinesRead, SalesSummary, 
    AdvancedSearchRequest, PaginatedResponse, SalesDashboard
)
from doova_one_view.api.sales.service import SalesService
from doova_one_view.api.tenants.service import TenantService

router = APIRouter(prefix="/sales", tags=["Sales"])

@router.get("/{tenant_id}/dashboard", response_model=SalesDashboard)
async def get_sales_dashboard(
    tenant_id: str,
    start_date: Optional[date] = Query(None, description="Start date (YYYY-MM-DD)"),
    end_date: Optional[date] = Query(None, description="End date (YYYY-MM-DD)"),
    user: AppUser = Depends(get_current_user)
):
    """Get comprehensive sales dashboard metrics for a tenant"""
    await TenantService.get_tenant(tenant_id, str(user.id))
    return await SalesService.get_dashboard(tenant_id, start_date, end_date)

@router.get("/{tenant_id}/summary", response_model=SalesSummary)
async def get_sales_summary(
    tenant_id: str,
    user: AppUser = Depends(get_current_user)
):
    """Get summarized sales metrics for a tenant"""
    # Security: Verify user has access to this tenant
    await TenantService.get_tenant(tenant_id, str(user.id))
    return await SalesService.get_sales_summary(tenant_id)

@router.get("/{tenant_id}/orders", response_model=PaginatedResponse[SalesOrderRead])
async def list_sales_orders(
    tenant_id: str,
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    partner_id: Optional[int] = None,
    user: AppUser = Depends(get_current_user)
):
    """List sales orders for a tenant"""
    await TenantService.get_tenant(tenant_id, str(user.id))
    return await SalesService.list_orders(tenant_id, limit, offset, partner_id)

@router.get("/{tenant_id}/filters")
async def get_sales_filters(
    tenant_id: str,
    user: AppUser = Depends(get_current_user)
):
    """Get distinct values for filtering sales orders"""
    await TenantService.get_tenant(tenant_id, str(user.id))
    return await SalesService.get_distinct_enums(tenant_id)

@router.get("/{tenant_id}/orders/{order_id}", response_model=SalesOrderWithLinesRead)
async def get_sales_order(
    tenant_id: str,
    order_id: int,
    user: AppUser = Depends(get_current_user)
):
    """Get a specific sales order with its lines"""
    await TenantService.get_tenant(tenant_id, str(user.id))
    return await SalesService.get_order(tenant_id, order_id)

@router.get("/{tenant_id}/export", response_class=StreamingResponse)
async def export_sales_orders(
    tenant_id: str,
    partner_id: Optional[int] = None,
    user: AppUser = Depends(get_current_user)
):
    """Export sales orders to CSV"""
    await TenantService.get_tenant(tenant_id, str(user.id))
    
    csv_generator = await SalesService.export_orders_csv(tenant_id, partner_id)
    
    from datetime import datetime
    now = datetime.now().strftime("%Y%m%d_%H%M%S")
    
    return StreamingResponse(
        csv_generator,
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename=sales_orders_{tenant_id}_{now}.csv"}
    )

@router.post("/{tenant_id}/search", response_model=PaginatedResponse[SalesOrderRead])
async def search_sales_orders(
    tenant_id: str,
    request: AdvancedSearchRequest,
    user: AppUser = Depends(get_current_user)
):
    """Advanced search for sales orders with complex filters"""
    # Security: Verify user has access to this tenant
    await TenantService.get_tenant(tenant_id, str(user.id))
    return await SalesService.advanced_search(tenant_id, request)
