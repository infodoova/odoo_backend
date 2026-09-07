"""
Inventory API routes.
"""

from typing import Any, Optional

from fastapi import APIRouter, Depends, Query
from fastapi.responses import Response

from odoo_app.models import AppUser
from doova_one_view.api.common.utils import parse_company_ids
from doova_one_view.api.dependencies import get_current_user
from doova_one_view.api.auth.permissions import require_permissions, require_any_permission

_view_inventory_overview   = Depends(require_permissions("view_inventory_overview"))
_view_inventory_moves      = Depends(require_permissions("view_inventory_moves"))
_view_inventory_pickings   = Depends(require_permissions("view_inventory_pickings"))
_view_inventory_quants     = Depends(require_permissions("view_inventory_quants"))
_export_inventory_moves    = Depends(require_permissions("export_inventory_moves"))
_export_inventory_pickings = Depends(require_permissions("export_inventory_pickings"))
_export_inventory_quants   = Depends(require_permissions("export_inventory_quants"))
from doova_one_view.api.inventory.schemas import (
    SearchRequest,
    MetricDetailResponse,
    DailyMovesResponse,
    MarketBreakdownResponse,
    EntityProfileResponse,
    ProductInventoryDetailResponse,
    StockTopCardsResponse,
    InventoryAlertsResponse,
    UpcomingShipmentsResponse,
    ShipmentTrackingDetailResponse,
)
from doova_one_view.api.inventory.service import InventoryService
from doova_one_view.api.tenants.service import TenantService

router = APIRouter(prefix="/inventory", tags=["Inventory"])


def _company_ids(company_ids: Optional[str] = None) -> Optional[list[int]]:
    return parse_company_ids(company_ids)


@router.get("/{tenant_id}/summary")
async def get_inventory_summary(
    tenant_id: str,
    company_ids: Optional[str] = Query(None, description="Comma-separated or JSON list of company IDs"),
    base_currency: Optional[str] = Query(None, description="Target currency for financial values"),
    user: AppUser = _view_inventory_overview,
) -> dict[str, Any]:
    await TenantService.get_tenant(tenant_id, str(user.id))
    return await InventoryService.get_inventory_summary(
        tenant_ids=[tenant_id],
        company_ids=_company_ids(company_ids),
        base_currency=base_currency,
    )


@router.get("/{tenant_id}/dashboard")
async def get_inventory_dashboard(
    tenant_id: str,
    start_date: Optional[str] = Query(None),
    end_date: Optional[str] = Query(None),
    date_from: Optional[str] = Query(None),
    date_to: Optional[str] = Query(None),
    company_ids: Optional[str] = Query(None, description="Comma-separated or JSON list of company IDs"),
    base_currency: Optional[str] = Query(None, description="Target currency for financial values"),
    user: AppUser = _view_inventory_overview,
) -> dict[str, Any]:
    await TenantService.get_tenant(tenant_id, str(user.id))
    return await InventoryService.get_dashboard(
        tenant_id,
        start_date or date_from,
        end_date or date_to,
        _company_ids(company_ids),
        base_currency,
    )


@router.get("/{tenant_id}/dashboard/top-cards")
async def get_inventory_top_cards(
    tenant_id: str,
    company_ids: Optional[str] = Query(None, description="Comma-separated or JSON list of company IDs"),
    low_stock_threshold: int = Query(10, ge=1, description="Quantity at or below which a product is considered low stock"),
    limit: int = Query(25, ge=1, le=100, description="Max drill-down items per card"),
    user: AppUser = _view_inventory_overview,
) -> StockTopCardsResponse:
    await TenantService.get_tenant(tenant_id, str(user.id))
    return await InventoryService.get_top_cards(
        tenant_id,
        company_ids=_company_ids(company_ids),
        low_stock_threshold=low_stock_threshold,
        limit=limit,
    )


@router.get("/{tenant_id}/dashboard/alerts")
async def get_inventory_alerts(
    tenant_id: str,
    company_ids: Optional[str] = Query(None, description="Comma-separated or JSON list of company IDs"),
    low_stock_threshold: int = Query(10, ge=1),
    limit: int = Query(10, ge=1, le=50, description="Max drill-down items per alert group"),
    user: AppUser = _view_inventory_overview,
) -> InventoryAlertsResponse:
    """Return an aggregated list of inventory alerts."""
    await TenantService.get_tenant(tenant_id, str(user.id))
    return await InventoryService.get_alerts(
        tenant_ids=[tenant_id],
        company_ids=_company_ids(company_ids),
        low_stock_threshold=low_stock_threshold,
        limit=limit,
    )


@router.get("/{tenant_id}/dashboard/stock-tables/{table_type}")
async def get_stock_table(
    tenant_id: str,
    table_type: str,
    company_ids: Optional[str] = Query(None, description="Comma-separated or JSON list of company IDs"),
    start_date: Optional[str] = Query(None, description="Start date filter (YYYY-MM-DD)"),
    end_date: Optional[str] = Query(None, description="End date filter (YYYY-MM-DD)"),
    low_stock_threshold: int = Query(10, ge=1, description="Quantity at or below which a product is considered low stock"),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    user: AppUser = _view_inventory_overview,
) -> dict[str, Any]:
    """
    Get paginated tables for specific inventory categories:
    table_type can be: low_stock, out_of_stock, negative_stock, expiring_soon, slow_moving
    """
    await TenantService.get_tenant(tenant_id, str(user.id))
    return await InventoryService.get_stock_table(
        tenant_ids=[tenant_id],
        table_type=table_type,
        company_ids=_company_ids(company_ids),
        start_date=start_date,
        end_date=end_date,
        low_stock_threshold=low_stock_threshold,
        limit=limit,
        offset=offset,
    )


@router.get("/{tenant_id}/dashboard/upcoming-shipments")
@router.get("/{tenant_id}/upcoming-shipments")
async def get_upcoming_shipments(
    tenant_id: str,
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    partner_id: Optional[int] = Query(None),
    vendor_id: Optional[int] = Query(None),
    product_id: Optional[int] = Query(None),
    start_date: Optional[str] = Query(None, description="Start date (YYYY-MM-DD)"),
    end_date: Optional[str] = Query(None, description="End date (YYYY-MM-DD)"),
    eta_status: Optional[str] = Query(None, description="Filter by ETA status: overdue, arriving_today, on_time"),
    search: Optional[str] = Query(None, description="Search picking name, PO origin, partner, or product"),
    company_ids: Optional[str] = Query(None, description="Comma-separated or JSON list of company IDs"),
    user: AppUser = _view_inventory_overview,
) -> UpcomingShipmentsResponse:
    await TenantService.get_tenant(tenant_id, str(user.id))
    return await InventoryService.get_upcoming_shipments(
        tenant_id=tenant_id,
        limit=limit,
        offset=offset,
        partner_id=vendor_id if vendor_id is not None else partner_id,
        product_id=product_id,
        start_date=start_date,
        end_date=end_date,
        eta_status=eta_status,
        search=search,
        company_ids=_company_ids(company_ids),
    )


@router.get("/{tenant_id}/shipments/{picking_id}/track")
@router.get("/{tenant_id}/pickings/{picking_id}/track")
async def get_shipment_tracking(
    tenant_id: str,
    picking_id: int,
    company_ids: Optional[str] = Query(None, description="Comma-separated or JSON list of company IDs"),
    user: AppUser = _view_inventory_pickings,
) -> ShipmentTrackingDetailResponse:
    await TenantService.get_tenant(tenant_id, str(user.id))
    return await InventoryService.get_shipment_tracking(
        tenant_id, picking_id, _company_ids(company_ids)
    )



# Pickings: static subpaths before /pickings/{picking_id}



# Pickings: static subpaths before /pickings/{picking_id}
@router.get("/{tenant_id}/pickings/export")
async def export_pickings(
    tenant_id: str,
    company_ids: Optional[str] = Query(None, description="Comma-separated or JSON list of company IDs"),
    user: AppUser = _export_inventory_pickings,
) -> Response:
    await TenantService.get_tenant(tenant_id, str(user.id))
    csv_content = await InventoryService.export_pickings_csv(
        tenant_id, _company_ids(company_ids)
    )
    return Response(
        content=csv_content,
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename=inventory_pickings_{tenant_id}.csv"},
    )


@router.post("/{tenant_id}/pickings/search")
async def search_pickings(
    tenant_id: str,
    request: SearchRequest,
    user: AppUser = _view_inventory_pickings,
) -> dict[str, Any]:
    await TenantService.get_tenant(tenant_id, str(user.id))
    company_ids = parse_company_ids(
        request.company_id if request.company_id is not None else request.companies
    )
    return await InventoryService.search_pickings(
        tenant_id, request.filters, request.limit, request.offset, company_ids
    )


@router.get("/{tenant_id}/pickings")
async def list_pickings(
    tenant_id: str,
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    company_ids: Optional[str] = Query(None, description="Comma-separated or JSON list of company IDs"),
    user: AppUser = _view_inventory_pickings,
) -> dict[str, Any]:
    await TenantService.get_tenant(tenant_id, str(user.id))
    return await InventoryService.get_pickings(
        tenant_id, limit, offset, _company_ids(company_ids)
    )


@router.get("/{tenant_id}/pickings/{picking_id}")
async def get_picking(
    tenant_id: str,
    picking_id: int,
    company_ids: Optional[str] = Query(None, description="Comma-separated or JSON list of company IDs"),
    user: AppUser = _view_inventory_pickings,
) -> dict[str, Any]:
    await TenantService.get_tenant(tenant_id, str(user.id))
    return await InventoryService.get_picking(
        tenant_id, picking_id, _company_ids(company_ids)
    )


# Moves: static subpaths before /moves/{move_id}
@router.get("/{tenant_id}/moves/export")
async def export_moves(
    tenant_id: str,
    company_ids: Optional[str] = Query(None, description="Comma-separated or JSON list of company IDs"),
    user: AppUser = _export_inventory_moves,
) -> Response:
    await TenantService.get_tenant(tenant_id, str(user.id))
    csv_content = await InventoryService.export_moves_csv(
        tenant_id, _company_ids(company_ids)
    )
    return Response(
        content=csv_content,
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename=inventory_moves_{tenant_id}.csv"},
    )


@router.post("/{tenant_id}/moves/search")
async def search_moves(
    tenant_id: str,
    request: SearchRequest,
    user: AppUser = _view_inventory_moves,
) -> dict[str, Any]:
    await TenantService.get_tenant(tenant_id, str(user.id))
    company_ids = parse_company_ids(
        request.company_id if request.company_id is not None else request.companies
    )
    return await InventoryService.search_moves(
        tenant_id, request.filters, request.limit, request.offset, company_ids
    )


@router.get("/{tenant_id}/moves")
async def list_stock_moves(
    tenant_id: str,
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    picking_id: Optional[int] = Query(None),
    company_ids: Optional[str] = Query(None, description="Comma-separated or JSON list of company IDs"),
    user: AppUser = _view_inventory_moves,
) -> dict[str, Any]:
    await TenantService.get_tenant(tenant_id, str(user.id))
    return await InventoryService.get_moves(
        tenant_id, limit, offset, picking_id, _company_ids(company_ids)
    )


@router.get("/{tenant_id}/moves/{move_id}")
async def get_stock_move(
    tenant_id: str,
    move_id: int,
    company_ids: Optional[str] = Query(None, description="Comma-separated or JSON list of company IDs"),
    user: AppUser = _view_inventory_moves,
) -> dict[str, Any]:
    await TenantService.get_tenant(tenant_id, str(user.id))
    return await InventoryService.get_move(
        tenant_id, move_id, _company_ids(company_ids)
    )


@router.get("/{tenant_id}/export")
async def export_inventory_default(
    tenant_id: str,
    company_ids: Optional[str] = Query(None, description="Comma-separated or JSON list of company IDs"),
    user: AppUser = _export_inventory_moves,
) -> Response:
    await TenantService.get_tenant(tenant_id, str(user.id))
    csv_content = await InventoryService.export_moves_csv(
        tenant_id, _company_ids(company_ids)
    )
    return Response(
        content=csv_content,
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename=inventory_moves_{tenant_id}.csv"},
    )


# Quants: static subpaths before /quants
@router.get("/{tenant_id}/quants/export")
async def export_quants(
    tenant_id: str,
    company_ids: Optional[str] = Query(None, description="Comma-separated or JSON list of company IDs"),
    user: AppUser = _export_inventory_quants,
) -> Response:
    await TenantService.get_tenant(tenant_id, str(user.id))
    csv_content = await InventoryService.export_quants_csv(
        tenant_id, _company_ids(company_ids)
    )
    return Response(
        content=csv_content,
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename=inventory_quants_{tenant_id}.csv"},
    )


@router.post("/{tenant_id}/quants/search")
async def search_quants(
    tenant_id: str,
    request: SearchRequest,
    user: AppUser = _view_inventory_quants,
) -> dict[str, Any]:
    await TenantService.get_tenant(tenant_id, str(user.id))
    company_ids = parse_company_ids(
        request.company_id if request.company_id is not None else request.companies
    )
    return await InventoryService.search_quants(
        tenant_id, request.filters, request.limit, request.offset, company_ids
    )


@router.get("/{tenant_id}/quants")
async def list_stock_quants(
    tenant_id: str,
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    product_id: Optional[int] = Query(None),
    company_ids: Optional[str] = Query(None, description="Comma-separated or JSON list of company IDs"),
    user: AppUser = _view_inventory_quants,
) -> dict[str, Any]:
    await TenantService.get_tenant(tenant_id, str(user.id))
    return await InventoryService.get_quants(
        tenant_id, limit, offset, product_id, _company_ids(company_ids)
    )


@router.get("/{tenant_id}/filters")
async def get_filters(
    tenant_id: str,
    company_ids: Optional[str] = Query(None, description="Comma-separated or JSON list of company IDs"),
    user: AppUser = _view_inventory_moves,
) -> dict[str, Any]:
    await TenantService.get_tenant(tenant_id, str(user.id))
    return await InventoryService.get_filters(
        tenant_id, _company_ids(company_ids)
    )


@router.get("/{tenant_id}/dashboard/metric-details")
async def get_dashboard_metric_details(
    tenant_id: str,
    metric: str = Query(..., description="Metric name: total_items_in_stock, incoming_shipments_count, outgoing_shipments_count, expiring_soon_count"),
    start_date: Optional[str] = Query(None, description="Start date filter (YYYY-MM-DD)"),
    end_date: Optional[str] = Query(None, description="End date filter (YYYY-MM-DD)"),
    company_ids: Optional[str] = Query(None, description="Comma-separated or JSON list of company IDs"),
    base_currency: Optional[str] = Query(None, description="Target currency for financial values"),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    user: AppUser = _view_inventory_overview,
) -> MetricDetailResponse:
    await TenantService.get_tenant(tenant_id, str(user.id))
    return await InventoryService.get_dashboard_metric_details(
        tenant_id,
        metric,
        start_date,
        end_date,
        _company_ids(company_ids),
        base_currency,
        limit,
        offset,
    )


@router.get("/{tenant_id}/dashboard/daily-moves")
async def get_daily_moves(
    tenant_id: str,
    day: str = Query(..., description="The calendar day to drill into (YYYY-MM-DD)"),
    company_ids: Optional[str] = Query(None, description="Comma-separated or JSON list of company IDs"),
    base_currency: Optional[str] = Query(None, description="Target currency for financial values"),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    user: AppUser = _view_inventory_overview,
) -> DailyMovesResponse:
    await TenantService.get_tenant(tenant_id, str(user.id))
    return await InventoryService.get_daily_moves(
        tenant_id,
        day,
        _company_ids(company_ids),
        base_currency,
        limit,
        offset,
    )


@router.get("/{tenant_id}/dashboard/market-breakdown")
async def get_market_breakdown_details(
    tenant_id: str,
    section: str = Query(..., description="Section name: top_locations, top_companies, top_statuses"),
    entity_id: str = Query(..., description="The entity ID or name"),
    start_date: Optional[str] = Query(None, description="Start date filter (YYYY-MM-DD)"),
    end_date: Optional[str] = Query(None, description="End date filter (YYYY-MM-DD)"),
    company_ids: Optional[str] = Query(None, description="Comma-separated or JSON list of company IDs"),
    base_currency: Optional[str] = Query(None, description="Target currency for financial values"),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    user: AppUser = _view_inventory_overview,
) -> MarketBreakdownResponse:
    await TenantService.get_tenant(tenant_id, str(user.id))
    parsed_entity_id: Any = entity_id
    try:
        parsed_entity_id = int(entity_id)
    except ValueError:
        pass

    return await InventoryService.get_market_breakdown_details(
        tenant_id,
        section,
        parsed_entity_id,
        start_date,
        end_date,
        _company_ids(company_ids),
        base_currency,
        limit,
        offset,
    )


@router.get("/{tenant_id}/dashboard/entity-profile")
async def get_entity_profile(
    tenant_id: str,
    entity_type: str = Query(..., description="Entity type: customer, vendor, supplier"),
    entity_id: int = Query(..., description="Partner ID"),
    user: AppUser = _view_inventory_overview,
) -> EntityProfileResponse:
    await TenantService.get_tenant(tenant_id, str(user.id))
    return await InventoryService.get_entity_profile(tenant_id, entity_type, entity_id)


@router.get("/{tenant_id}/dashboard/product-inventory-details")
async def get_product_inventory_details(
    tenant_id: str,
    product_id: int = Query(..., description="Product ID"),
    start_date: Optional[str] = Query(None, description="Start date filter (YYYY-MM-DD)"),
    end_date: Optional[str] = Query(None, description="End date filter (YYYY-MM-DD)"),
    company_ids: Optional[str] = Query(None, description="Comma-separated or JSON list of company IDs"),
    base_currency: Optional[str] = Query(None, description="Target currency for financial values"),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    user: AppUser = _view_inventory_overview,
) -> ProductInventoryDetailResponse:
    await TenantService.get_tenant(tenant_id, str(user.id))
    return await InventoryService.get_product_inventory_details(
        tenant_id,
        product_id,
        start_date,
        end_date,
        _company_ids(company_ids),
        base_currency,
        limit,
        offset,
    )
