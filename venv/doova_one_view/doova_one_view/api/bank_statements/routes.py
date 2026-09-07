"""
Bank Statements API routes.
"""

from typing import Any, Optional
from fastapi import APIRouter, Depends, Query
from fastapi.responses import Response

from odoo_app.models import AppUser
from doova_one_view.api.common.utils import parse_company_ids
from doova_one_view.api.common.schemas import PaginatedResponse
from doova_one_view.api.auth.permissions import require_permissions, require_any_permission
from doova_one_view.api.dependencies import get_current_user
from doova_one_view.api.bank_statements.schemas import (
    SearchRequest,
    BankStatementRead,
    BankStatementLineRead
)
from doova_one_view.api.bank_statements.service import BankStatementService
from doova_one_view.api.tenants.service import TenantService

_view_bank_statements   = Depends(require_any_permission("view_bank_statements"))
_export_bank_statements = Depends(require_permissions("export_bank_statements"))

router = APIRouter(prefix="/bank-statements", tags=["Bank Statements"])

def _company_ids(
    company_id: Optional[int] = None,
    companies: Optional[str] = None,
    company_ids: Optional[str] = None,
) -> Optional[list[int]]:
    val = company_ids if company_ids is not None else (company_id if company_id is not None else companies)
    return parse_company_ids(val)

@router.get("/{tenant_id}/filters")
async def get_statements_filters(
    tenant_id: str,
    company_id: Optional[int] = Query(None),
    companies: Optional[str] = Query(None),
    company_ids: Optional[str] = Query(None, description="Comma-separated or JSON list of company IDs"),
    user: AppUser = _view_bank_statements,
) -> dict[str, Any]:
    await TenantService.get_tenant(tenant_id, str(user.id))
    return await BankStatementService.get_statements_filters(tenant_id, _company_ids(company_id, companies, company_ids))

@router.get("/{tenant_id}/export")
async def export_statements(
    tenant_id: str,
    company_id: Optional[int] = Query(None),
    companies: Optional[str] = Query(None),
    company_ids: Optional[str] = Query(None, description="Comma-separated or JSON list of company IDs"),
    user: AppUser = _export_bank_statements,
) -> Response:
    await TenantService.get_tenant(tenant_id, str(user.id))
    csv_content = await BankStatementService.export_statements_csv(tenant_id, _company_ids(company_id, companies, company_ids))
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
    company_ids: Optional[str] = Query(None, description="Comma-separated or JSON list of company IDs"),
    user: AppUser = _view_bank_statements,
) -> PaginatedResponse[BankStatementRead]:
    await TenantService.get_tenant(tenant_id, str(user.id))
    c_ids = _company_ids(company_id, companies, company_ids)
    if c_ids is None:
        c_ids = parse_company_ids(getattr(request, "company_ids", None) or getattr(request, "company_id", None) or getattr(request, "companies", None))
    return await BankStatementService.search_statements(tenant_id, request.filters, request.limit, request.offset, c_ids)

@router.get("/{tenant_id}")
async def list_statements(
    tenant_id: str,
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    search: Optional[str] = Query(None),
    company_id: Optional[int] = Query(None),
    companies: Optional[str] = Query(None),
    company_ids: Optional[str] = Query(None, description="Comma-separated or JSON list of company IDs"),
    base_currency: Optional[str] = Query(None, description="Target currency"),
    user: AppUser = _view_bank_statements,
) -> PaginatedResponse[BankStatementRead]:
    await TenantService.get_tenant(tenant_id, str(user.id))
    return await BankStatementService.get_statements(tenant_id, limit, offset, search, _company_ids(company_id, companies, company_ids))

# Lines endpoints
@router.get("/{tenant_id}/lines/filters")
async def get_statement_lines_filters(
    tenant_id: str,
    company_id: Optional[int] = Query(None),
    companies: Optional[str] = Query(None),
    company_ids: Optional[str] = Query(None, description="Comma-separated or JSON list of company IDs"),
    user: AppUser = _view_bank_statements,
) -> dict[str, Any]:
    await TenantService.get_tenant(tenant_id, str(user.id))
    return await BankStatementService.get_statement_lines_filters(tenant_id, _company_ids(company_id, companies, company_ids))

@router.get("/{tenant_id}/lines/export")
async def export_statement_lines(
    tenant_id: str,
    company_id: Optional[int] = Query(None),
    companies: Optional[str] = Query(None),
    company_ids: Optional[str] = Query(None, description="Comma-separated or JSON list of company IDs"),
    user: AppUser = _export_bank_statements,
) -> Response:
    await TenantService.get_tenant(tenant_id, str(user.id))
    csv_content = await BankStatementService.export_statement_lines_csv(tenant_id, _company_ids(company_id, companies, company_ids))
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
    company_ids: Optional[str] = Query(None, description="Comma-separated or JSON list of company IDs"),
    user: AppUser = _view_bank_statements,
) -> PaginatedResponse[BankStatementLineRead]:
    await TenantService.get_tenant(tenant_id, str(user.id))
    c_ids = _company_ids(company_id, companies, company_ids)
    if c_ids is None:
        c_ids = parse_company_ids(getattr(request, "company_ids", None) or getattr(request, "company_id", None) or getattr(request, "companies", None))
    return await BankStatementService.search_statement_lines(tenant_id, request.filters, request.limit, request.offset, c_ids)

@router.get("/{tenant_id}/lines/{line_id}")
async def get_statement_line(
    tenant_id: str,
    line_id: int,
    company_id: Optional[int] = Query(None),
    companies: Optional[str] = Query(None),
    company_ids: Optional[str] = Query(None, description="Comma-separated or JSON list of company IDs"),
    user: AppUser = _view_bank_statements,
) -> BankStatementLineRead:
    await TenantService.get_tenant(tenant_id, str(user.id))
    return await BankStatementService.get_statement_line(tenant_id, line_id, _company_ids(company_id, companies, company_ids))

@router.get("/{tenant_id}/lines")
async def list_statement_lines(
    tenant_id: str,
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    company_id: Optional[int] = Query(None),
    companies: Optional[str] = Query(None),
    company_ids: Optional[str] = Query(None, description="Comma-separated or JSON list of company IDs"),
    user: AppUser = _view_bank_statements,
) -> PaginatedResponse[BankStatementLineRead]:
    await TenantService.get_tenant(tenant_id, str(user.id))
    return await BankStatementService.get_statement_lines(tenant_id, limit, offset, None, _company_ids(company_id, companies, company_ids))

# Statement lines for a specific statement
@router.get("/{tenant_id}/{statement_id}/lines")
async def list_statement_lines_for_statement(
    tenant_id: str,
    statement_id: int,
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    company_id: Optional[int] = Query(None),
    companies: Optional[str] = Query(None),
    company_ids: Optional[str] = Query(None, description="Comma-separated or JSON list of company IDs"),
    user: AppUser = _view_bank_statements,
) -> PaginatedResponse[BankStatementLineRead]:
    await TenantService.get_tenant(tenant_id, str(user.id))
    return await BankStatementService.get_lines_for_statement(tenant_id, statement_id, limit, offset, _company_ids(company_id, companies, company_ids))

# Detail endpoint last so it doesn't mask /lines, etc.
@router.get("/{tenant_id}/{statement_id}")
async def get_statement(
    tenant_id: str,
    statement_id: int,
    company_id: Optional[int] = Query(None),
    companies: Optional[str] = Query(None),
    company_ids: Optional[str] = Query(None, description="Comma-separated or JSON list of company IDs"),
    user: AppUser = _view_bank_statements,
) -> BankStatementRead:
    await TenantService.get_tenant(tenant_id, str(user.id))
    return await BankStatementService.get_statement(tenant_id, statement_id, _company_ids(company_id, companies, company_ids))
