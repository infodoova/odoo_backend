"""
Bank Statements API routes.
"""

from typing import Any, Optional
from fastapi import APIRouter, Depends, Query
from fastapi.responses import Response

from odoo_app.models import AppUser
from doova_one_view.api.common.utils import parse_company_ids
from doova_one_view.api.dependencies import get_current_user
from doova_one_view.api.bank_statements.schemas import SearchRequest
from doova_one_view.api.bank_statements.service import BankStatementService
from doova_one_view.api.tenants.service import TenantService

router = APIRouter(prefix="/bank-statements", tags=["Bank Statements"])

def _company_ids(company_id: Optional[int], companies: Optional[str]) -> Optional[list[int]]:
    return parse_company_ids(company_id if company_id is not None else companies)

@router.get("/{tenant_id}/filters")
async def get_statements_filters(
    tenant_id: str,
    company_id: Optional[int] = Query(None),
    companies: Optional[str] = Query(None),
    user: AppUser = Depends(get_current_user),
) -> dict[str, Any]:
    await TenantService.get_tenant(tenant_id, str(user.id))
    return await BankStatementService.get_statements_filters(tenant_id, _company_ids(company_id, companies))

@router.get("/{tenant_id}/export")
async def export_statements(
    tenant_id: str,
    company_id: Optional[int] = Query(None),
    companies: Optional[str] = Query(None),
    user: AppUser = Depends(get_current_user),
) -> Response:
    await TenantService.get_tenant(tenant_id, str(user.id))
    csv_content = await BankStatementService.export_statements_csv(tenant_id, _company_ids(company_id, companies))
    return Response(
        content=csv_content,
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename=bank_statements_{tenant_id}.csv"},
    )

@router.post("/{tenant_id}/search")
async def search_statements(
    tenant_id: str,
    request: SearchRequest,
    company_id: Optional[int] = Query(None),
    companies: Optional[str] = Query(None),
    user: AppUser = Depends(get_current_user),
) -> dict[str, Any]:
    await TenantService.get_tenant(tenant_id, str(user.id))
    company_ids = _company_ids(company_id, companies)
    if company_ids is None:
        company_ids = parse_company_ids(request.company_id if request.company_id is not None else request.companies)
    return await BankStatementService.search_statements(tenant_id, request.filters, request.limit, request.offset, company_ids)

@router.get("/{tenant_id}")
async def list_statements(
    tenant_id: str,
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    search: Optional[str] = Query(None),
    company_id: Optional[int] = Query(None),
    companies: Optional[str] = Query(None),
    user: AppUser = Depends(get_current_user),
) -> dict[str, Any]:
    await TenantService.get_tenant(tenant_id, str(user.id))
    return await BankStatementService.get_statements(tenant_id, limit, offset, search, _company_ids(company_id, companies))

# Lines endpoints
@router.get("/{tenant_id}/lines/filters")
async def get_statement_lines_filters(
    tenant_id: str,
    company_id: Optional[int] = Query(None),
    companies: Optional[str] = Query(None),
    user: AppUser = Depends(get_current_user),
) -> dict[str, Any]:
    await TenantService.get_tenant(tenant_id, str(user.id))
    return await BankStatementService.get_statement_lines_filters(tenant_id, _company_ids(company_id, companies))

@router.get("/{tenant_id}/lines/export")
async def export_statement_lines(
    tenant_id: str,
    company_id: Optional[int] = Query(None),
    companies: Optional[str] = Query(None),
    user: AppUser = Depends(get_current_user),
) -> Response:
    await TenantService.get_tenant(tenant_id, str(user.id))
    csv_content = await BankStatementService.export_statement_lines_csv(tenant_id, _company_ids(company_id, companies))
    return Response(
        content=csv_content,
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename=bank_statement_lines_{tenant_id}.csv"},
    )

@router.post("/{tenant_id}/lines/search")
async def search_statement_lines(
    tenant_id: str,
    request: SearchRequest,
    company_id: Optional[int] = Query(None),
    companies: Optional[str] = Query(None),
    user: AppUser = Depends(get_current_user),
) -> dict[str, Any]:
    await TenantService.get_tenant(tenant_id, str(user.id))
    company_ids = _company_ids(company_id, companies)
    if company_ids is None:
        company_ids = parse_company_ids(request.company_id if request.company_id is not None else request.companies)
    return await BankStatementService.search_statement_lines(tenant_id, request.filters, request.limit, request.offset, company_ids)

@router.get("/{tenant_id}/lines/{line_id}")
async def get_statement_line(
    tenant_id: str,
    line_id: int,
    user: AppUser = Depends(get_current_user),
) -> dict[str, Any]:
    await TenantService.get_tenant(tenant_id, str(user.id))
    return await BankStatementService.get_statement_line(tenant_id, line_id)

@router.get("/{tenant_id}/lines")
async def list_statement_lines(
    tenant_id: str,
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    company_id: Optional[int] = Query(None),
    companies: Optional[str] = Query(None),
    user: AppUser = Depends(get_current_user),
) -> dict[str, Any]:
    await TenantService.get_tenant(tenant_id, str(user.id))
    return await BankStatementService.get_statement_lines(tenant_id, limit, offset, None, _company_ids(company_id, companies))

# Statement lines for a specific statement
@router.get("/{tenant_id}/{statement_id}/lines")
async def list_statement_lines_for_statement(
    tenant_id: str,
    statement_id: int,
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    company_id: Optional[int] = Query(None),
    companies: Optional[str] = Query(None),
    user: AppUser = Depends(get_current_user),
) -> dict[str, Any]:
    await TenantService.get_tenant(tenant_id, str(user.id))
    return await BankStatementService.get_statement_lines(tenant_id, limit, offset, statement_id, _company_ids(company_id, companies))

# Detail endpoint last so it doesn't mask /lines, etc.
@router.get("/{tenant_id}/{statement_id}")
async def get_statement(
    tenant_id: str,
    statement_id: int,
    user: AppUser = Depends(get_current_user),
) -> dict[str, Any]:
    await TenantService.get_tenant(tenant_id, str(user.id))
    return await BankStatementService.get_statement(tenant_id, statement_id)
