"""
Master Data API routes.
"""

from typing import Any, Optional

from fastapi import APIRouter, Depends, Query
from fastapi.responses import Response

from odoo_app.models import AppUser
from doova_one_view.api.common.utils import parse_company_ids
from doova_one_view.api.dependencies import get_current_user
from doova_one_view.api.auth.permissions import require_permissions, require_any_permission

_view_partners   = Depends(require_permissions("view_partners"))
_view_products   = Depends(require_permissions("view_products"))
_view_lots       = Depends(require_permissions("view_lots"))
_view_categories = Depends(require_permissions("view_categories"))
_view_chart      = Depends(require_permissions("view_chart_of_accounts"))
_export_partners   = Depends(require_permissions("export_partners"))
_export_products   = Depends(require_permissions("export_products"))
_export_lots       = Depends(require_permissions("export_lots"))
_export_chart      = Depends(require_permissions("export_chart_of_accounts"))
from doova_one_view.api.master_data.schemas import SearchRequest, ChartOfAccountsRead
from doova_one_view.api.master_data.service import MasterDataService
from doova_one_view.api.tenants.service import TenantService

router = APIRouter(prefix="/master-data", tags=["Master Data"])


def _to_bool_or_none(value: Optional[str | bool]) -> Optional[bool]:
    if value is None or isinstance(value, bool):
        return value
    s = str(value).strip().lower()
    if not s:
        return None
    if s in ("true", "t", "1", "yes", "y"):
        return True
    if s in ("false", "f", "0", "no", "n"):
        return False
    return None


def _company_ids(company_id: Optional[int], companies: Optional[str]) -> Optional[list[int]]:
    return parse_company_ids(company_id if company_id is not None else companies)


@router.get("/{tenant_id}/companies")
async def list_companies(
    tenant_id: str,
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    active_only: bool = Query(False),
    user: AppUser = Depends(get_current_user),
) -> dict[str, Any]:
    await TenantService.get_tenant(tenant_id, str(user.id))
    return await MasterDataService.get_companies(tenant_id, limit, offset, active_only)


@router.get("/{tenant_id}/enums")
async def get_enums(
    tenant_id: str,
    user: AppUser = Depends(get_current_user),
) -> dict[str, Any]:
    await TenantService.get_tenant(tenant_id, str(user.id))
    return await MasterDataService.get_enums(tenant_id)


@router.get("/{tenant_id}/filters")
async def get_filters(
    tenant_id: str,
    company_id: Optional[int] = Query(None),
    companies: Optional[str] = Query(None),
    includeCompanies: Optional[str] = Query(None),
    include_companies: Optional[str] = Query(None),
    user: AppUser = Depends(get_current_user),
) -> dict[str, Any]:
    await TenantService.get_tenant(tenant_id, str(user.id))
    return await MasterDataService.get_filters(tenant_id, _company_ids(company_id, companies))


# Partners: static subpaths before /partners
@router.get("/{tenant_id}/partners/filters")
async def get_partners_filters(
    tenant_id: str,
    user: AppUser = _view_partners,
) -> dict[str, Any]:
    await TenantService.get_tenant(tenant_id, str(user.id))
    return await MasterDataService.get_partners_filters(tenant_id)


@router.post("/{tenant_id}/partners/search")
async def search_partners(
    tenant_id: str,
    request: SearchRequest,
    user: AppUser = _view_partners,
) -> dict[str, Any]:
    await TenantService.get_tenant(tenant_id, str(user.id))
    return await MasterDataService.search_partners(
        tenant_id, request.filters, request.limit, request.offset
    )


@router.get("/{tenant_id}/partners/export")
async def export_partners(
    tenant_id: str,
    user: AppUser = _export_partners,
) -> Response:
    await TenantService.get_tenant(tenant_id, str(user.id))
    csv_content = await MasterDataService.export_partners_csv(tenant_id)
    return Response(
        content=csv_content,
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename=partners_{tenant_id}.csv"},
    )


@router.get("/{tenant_id}/partners")
async def list_partners(
    tenant_id: str,
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    is_customer: Optional[str] = Query(None),
    is_supplier: Optional[str] = Query(None),
    search: Optional[str] = Query(None),
    user: AppUser = _view_partners,
) -> dict[str, Any]:
    await TenantService.get_tenant(tenant_id, str(user.id))
    return await MasterDataService.get_partners(
        tenant_id,
        limit,
        offset,
        search,
        _to_bool_or_none(is_customer),
        _to_bool_or_none(is_supplier),
    )


# Products: static subpaths before /products
@router.get("/{tenant_id}/products/filters")
async def get_products_filters(
    tenant_id: str,
    company_id: Optional[int] = Query(None),
    companies: Optional[str] = Query(None),
    user: AppUser = _view_products,
) -> dict[str, Any]:
    await TenantService.get_tenant(tenant_id, str(user.id))
    return await MasterDataService.get_products_filters(tenant_id, _company_ids(company_id, companies))


@router.post("/{tenant_id}/products/search")
async def search_products(
    tenant_id: str,
    request: SearchRequest,
    company_id: Optional[int] = Query(None),
    companies: Optional[str] = Query(None),
    user: AppUser = _view_products,
) -> dict[str, Any]:
    await TenantService.get_tenant(tenant_id, str(user.id))
    return await MasterDataService.search_products(
        tenant_id,
        request.filters,
        request.limit,
        request.offset,
        _company_ids(company_id, companies),
    )


@router.get("/{tenant_id}/products/export")
async def export_products(
    tenant_id: str,
    company_id: Optional[int] = Query(None),
    companies: Optional[str] = Query(None),
    user: AppUser = _export_products,
) -> Response:
    await TenantService.get_tenant(tenant_id, str(user.id))
    csv_content = await MasterDataService.export_products_csv(
        tenant_id, _company_ids(company_id, companies)
    )
    return Response(
        content=csv_content,
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename=products_{tenant_id}.csv"},
    )


@router.get("/{tenant_id}/products")
async def list_products(
    tenant_id: str,
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    search: Optional[str] = Query(None),
    company_id: Optional[int] = Query(None),
    companies: Optional[str] = Query(None),
    user: AppUser = _view_products,
) -> dict[str, Any]:
    await TenantService.get_tenant(tenant_id, str(user.id))
    return await MasterDataService.get_products(
        tenant_id, limit, offset, search, _company_ids(company_id, companies)
    )


# Categories: /tree before /{category_id}
@router.get("/{tenant_id}/categories/tree")
async def get_categories_tree(
    tenant_id: str,
    user: AppUser = _view_categories,
) -> list[dict[str, Any]]:
    await TenantService.get_tenant(tenant_id, str(user.id))
    return await MasterDataService.get_categories_tree(tenant_id)


@router.get("/{tenant_id}/categories/{category_id}")
async def get_category(
    tenant_id: str,
    category_id: int,
    include_products: bool = Query(False),
    user: AppUser = _view_categories,
) -> dict[str, Any]:
    await TenantService.get_tenant(tenant_id, str(user.id))
    return await MasterDataService.get_category(tenant_id, category_id, include_products)


# Lots: static subpaths before /lots
@router.post("/{tenant_id}/lots/search")
async def search_lots(
    tenant_id: str,
    request: SearchRequest,
    company_id: Optional[int] = Query(None),
    companies: Optional[str] = Query(None),
    user: AppUser = _view_lots,
) -> dict[str, Any]:
    await TenantService.get_tenant(tenant_id, str(user.id))
    company_ids = _company_ids(company_id, companies)
    if company_ids is None:
        company_ids = parse_company_ids(
            request.company_id if request.company_id is not None else request.companies
        )
    return await MasterDataService.search_lots(
        tenant_id, request.filters, request.limit, request.offset, company_ids
    )


@router.get("/{tenant_id}/lots/export")
async def export_lots(
    tenant_id: str,
    company_id: Optional[int] = Query(None),
    companies: Optional[str] = Query(None),
    user: AppUser = _export_lots,
) -> Response:
    await TenantService.get_tenant(tenant_id, str(user.id))
    csv_content = await MasterDataService.export_lots_csv(
        tenant_id, _company_ids(company_id, companies)
    )
    return Response(
        content=csv_content,
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename=lots_{tenant_id}.csv"},
    )


@router.get("/{tenant_id}/lots/filters")
async def get_lots_filters(
    tenant_id: str,
    company_id: Optional[int] = Query(None),
    companies: Optional[str] = Query(None),
    user: AppUser = _view_lots,
) -> dict[str, Any]:
    await TenantService.get_tenant(tenant_id, str(user.id))
    return await MasterDataService.get_lots_filters(
        tenant_id, _company_ids(company_id, companies)
    )


@router.get("/{tenant_id}/lots")
async def list_lots(
    tenant_id: str,
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    company_id: Optional[int] = Query(None),
    companies: Optional[str] = Query(None),
    user: AppUser = _view_lots,
) -> dict[str, Any]:
    await TenantService.get_tenant(tenant_id, str(user.id))
    return await MasterDataService.get_lots(
        tenant_id, limit, offset, _company_ids(company_id, companies)
    )


@router.get("/{tenant_id}/currencies")
async def list_currencies(
    tenant_id: str,
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    active_only: bool = Query(True),
    user: AppUser = Depends(get_current_user),
) -> dict[str, Any]:
    await TenantService.get_tenant(tenant_id, str(user.id))
    return await MasterDataService.get_currencies(tenant_id, limit, offset, active_only)


# Chart of Accounts: static subpaths before /chart-of-accounts
@router.post("/{tenant_id}/chart-of-accounts/search")
async def search_chart_of_accounts(
    tenant_id: str,
    request: SearchRequest,
    user: AppUser = _view_chart,
) -> dict[str, Any]:
    await TenantService.get_tenant(tenant_id, str(user.id))
    return await MasterDataService.search_chart_of_accounts(
        tenant_id, request.filters, request.limit, request.offset
    )


@router.get("/{tenant_id}/chart-of-accounts/export")
async def export_chart_of_accounts(
    tenant_id: str,
    user: AppUser = _export_chart,
) -> Response:
    await TenantService.get_tenant(tenant_id, str(user.id))
    csv_content = await MasterDataService.export_chart_of_accounts_csv(tenant_id)
    return Response(
        content=csv_content,
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename=chart_of_accounts_{tenant_id}.csv"},
    )


@router.get("/{tenant_id}/chart-of-accounts/filters")
async def get_chart_of_accounts_filters(
    tenant_id: str,
    user: AppUser = _view_chart,
) -> dict[str, Any]:
    await TenantService.get_tenant(tenant_id, str(user.id))
    return await MasterDataService.get_chart_of_accounts_filters(tenant_id)


@router.get("/{tenant_id}/chart-of-accounts")
async def list_chart_of_accounts(
    tenant_id: str,
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    search: Optional[str] = Query(None),
    user: AppUser = _view_chart,
) -> dict[str, Any]:
    await TenantService.get_tenant(tenant_id, str(user.id))
    return await MasterDataService.get_chart_of_accounts(
        tenant_id, limit, offset, search
    )
