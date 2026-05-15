"""
Inventory API routes.
"""

from typing import Any, Optional

from fastapi import APIRouter, Depends, Query
from fastapi.responses import Response

from odoo_app.models import AppUser
from doova_one_view.api.common.utils import parse_company_ids
from doova_one_view.api.dependencies import get_current_user
from doova_one_view.api.inventory.schemas import SearchRequest
from doova_one_view.api.inventory.service import InventoryService
from doova_one_view.api.tenants.service import TenantService

router = APIRouter(prefix="/inventory", tags=["Inventory"])


def _company_ids(company_id: Optional[int], companies: Optional[str]) -> Optional[list[int]]:
    return parse_company_ids(company_id if company_id is not None else companies)


@router.get("/{tenant_id}/summary")
async def get_inventory_summary(
    tenant_id: str,
    company_id: Optional[int] = Query(None),
    companies: Optional[str] = Query(None),
    user: AppUser = Depends(get_current_user),
) -> dict[str, Any]:
    await TenantService.get_tenant(tenant_id, str(user.id))
    return await InventoryService.get_inventory_summary(
        tenant_id, _company_ids(company_id, companies)
    )


@router.get("/{tenant_id}/dashboard")
async def get_inventory_dashboard(
    tenant_id: str,
    start_date: Optional[str] = Query(None),
    end_date: Optional[str] = Query(None),
    date_from: Optional[str] = Query(None),
    date_to: Optional[str] = Query(None),
    company_id: Optional[int] = Query(None),
    companies: Optional[str] = Query(None),
    includeCompanies: Optional[str] = Query(None),
    include_companies: Optional[str] = Query(None),
    user: AppUser = Depends(get_current_user),
) -> dict[str, Any]:
    await TenantService.get_tenant(tenant_id, str(user.id))
    return await InventoryService.get_dashboard(
        tenant_id,
        start_date or date_from,
        end_date or date_to,
        _company_ids(company_id, companies),
    )


# Pickings: static subpaths before /pickings/{picking_id}
@router.get("/{tenant_id}/pickings/export")
async def export_pickings(
    tenant_id: str,
    company_id: Optional[int] = Query(None),
    companies: Optional[str] = Query(None),
    user: AppUser = Depends(get_current_user),
) -> Response:
    await TenantService.get_tenant(tenant_id, str(user.id))
    csv_content = await InventoryService.export_pickings_csv(
        tenant_id, _company_ids(company_id, companies)
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
    user: AppUser = Depends(get_current_user),
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
    company_id: Optional[int] = Query(None),
    companies: Optional[str] = Query(None),
    user: AppUser = Depends(get_current_user),
) -> dict[str, Any]:
    await TenantService.get_tenant(tenant_id, str(user.id))
    return await InventoryService.get_pickings(
        tenant_id, limit, offset, _company_ids(company_id, companies)
    )


@router.get("/{tenant_id}/pickings/{picking_id}")
async def get_picking(
    tenant_id: str,
    picking_id: int,
    company_id: Optional[int] = Query(None),
    companies: Optional[str] = Query(None),
    user: AppUser = Depends(get_current_user),
) -> dict[str, Any]:
    await TenantService.get_tenant(tenant_id, str(user.id))
    return await InventoryService.get_picking(
        tenant_id, picking_id, _company_ids(company_id, companies)
    )


# Moves: static subpaths before /moves/{move_id}
@router.get("/{tenant_id}/moves/export")
async def export_moves(
    tenant_id: str,
    company_id: Optional[int] = Query(None),
    companies: Optional[str] = Query(None),
    user: AppUser = Depends(get_current_user),
) -> Response:
    await TenantService.get_tenant(tenant_id, str(user.id))
    csv_content = await InventoryService.export_moves_csv(
        tenant_id, _company_ids(company_id, companies)
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
    user: AppUser = Depends(get_current_user),
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
    company_id: Optional[int] = Query(None),
    companies: Optional[str] = Query(None),
    user: AppUser = Depends(get_current_user),
) -> dict[str, Any]:
    await TenantService.get_tenant(tenant_id, str(user.id))
    return await InventoryService.get_moves(
        tenant_id, limit, offset, picking_id, _company_ids(company_id, companies)
    )


@router.get("/{tenant_id}/moves/{move_id}")
async def get_stock_move(
    tenant_id: str,
    move_id: int,
    company_id: Optional[int] = Query(None),
    companies: Optional[str] = Query(None),
    user: AppUser = Depends(get_current_user),
) -> dict[str, Any]:
    await TenantService.get_tenant(tenant_id, str(user.id))
    return await InventoryService.get_move(
        tenant_id, move_id, _company_ids(company_id, companies)
    )


@router.get("/{tenant_id}/export")
async def export_inventory_default(
    tenant_id: str,
    company_id: Optional[int] = Query(None),
    companies: Optional[str] = Query(None),
    user: AppUser = Depends(get_current_user),
) -> Response:
    await TenantService.get_tenant(tenant_id, str(user.id))
    csv_content = await InventoryService.export_moves_csv(
        tenant_id, _company_ids(company_id, companies)
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
    company_id: Optional[int] = Query(None),
    companies: Optional[str] = Query(None),
    user: AppUser = Depends(get_current_user),
) -> Response:
    await TenantService.get_tenant(tenant_id, str(user.id))
    csv_content = await InventoryService.export_quants_csv(
        tenant_id, _company_ids(company_id, companies)
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
    user: AppUser = Depends(get_current_user),
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
    company_id: Optional[int] = Query(None),
    companies: Optional[str] = Query(None),
    user: AppUser = Depends(get_current_user),
) -> dict[str, Any]:
    await TenantService.get_tenant(tenant_id, str(user.id))
    return await InventoryService.get_quants(
        tenant_id, limit, offset, product_id, _company_ids(company_id, companies)
    )


@router.get("/{tenant_id}/filters")
async def get_filters(
    tenant_id: str,
    company_id: Optional[int] = Query(None),
    companies: Optional[str] = Query(None),
    user: AppUser = Depends(get_current_user),
) -> dict[str, Any]:
    await TenantService.get_tenant(tenant_id, str(user.id))
    return await InventoryService.get_filters(
        tenant_id, _company_ids(company_id, companies)
    )
