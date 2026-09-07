"""
Account Journals API routes.
"""

from typing import Any, Optional
from fastapi import APIRouter, Depends, Query
from fastapi.responses import Response

from odoo_app.models import AppUser
from doova_one_view.api.common.utils import parse_company_ids
from doova_one_view.api.common.schemas import PaginatedResponse
from doova_one_view.api.auth.permissions import require_permissions, require_any_permission
from doova_one_view.api.account_journals.schemas import (
    SearchRequest,
    AccountJournalRead,
)
from doova_one_view.api.account_journals.service import AccountJournalService
from doova_one_view.api.tenants.service import TenantService

_view_journals   = Depends(require_any_permission("view_account_journals"))
_export_journals = Depends(require_permissions("export_account_journals"))

router = APIRouter(prefix="/account-journals", tags=["Account Journals"])

def _company_ids(company_ids: Optional[str] = None) -> Optional[list[int]]:
    return parse_company_ids(company_ids)

@router.get("/{tenant_id}/filters")
async def get_journals_filters(
    tenant_id: str,
    company_ids: Optional[str] = Query(None, description="Comma-separated or JSON list of company IDs"),
    user: AppUser = _view_journals,
) -> dict[str, Any]:
    await TenantService.get_tenant(tenant_id, str(user.id))
    return await AccountJournalService.get_journals_filters(tenant_id, _company_ids(company_ids))

@router.get("/{tenant_id}/export")
async def export_journals(
    tenant_id: str,
    company_ids: Optional[str] = Query(None, description="Comma-separated or JSON list of company IDs"),
    user: AppUser = _export_journals,
) -> Response:
    await TenantService.get_tenant(tenant_id, str(user.id))
    csv_content = await AccountJournalService.export_journals_csv(tenant_id, _company_ids(company_ids))
    return Response(
        content=csv_content,
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename=account_journals_{tenant_id}.csv"},
    )

@router.post("/{tenant_id}/search")
async def search_journals(
    tenant_id: str,
    request: SearchRequest,
    company_ids: Optional[str] = Query(None, description="Comma-separated or JSON list of company IDs"),
    user: AppUser = _view_journals,
) -> PaginatedResponse[AccountJournalRead]:
    await TenantService.get_tenant(tenant_id, str(user.id))
    c_ids = _company_ids(company_ids)
    if c_ids is None:
        c_ids = parse_company_ids(getattr(request, "company_ids", None) or getattr(request, "company_id", None) or getattr(request, "companies", None))
    return await AccountJournalService.search_journals(tenant_id, request.filters, request.limit, request.offset, c_ids)

@router.get("/{tenant_id}")
async def list_journals(
    tenant_id: str,
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    search: Optional[str] = Query(None),
    company_ids: Optional[str] = Query(None, description="Comma-separated or JSON list of company IDs"),
    base_currency: Optional[str] = Query(None, description="Target currency"),
    user: AppUser = _view_journals,
) -> PaginatedResponse[AccountJournalRead]:
    await TenantService.get_tenant(tenant_id, str(user.id))
    return await AccountJournalService.get_journals(tenant_id, limit, offset, search, _company_ids(company_ids))

@router.get("/{tenant_id}/audit")
async def get_journal_audit(
    tenant_id: str,
    start_date: Optional[str] = Query(None),
    end_date: Optional[str] = Query(None),
    date_from: Optional[str] = Query(None),
    date_to: Optional[str] = Query(None),
    company_ids: Optional[str] = Query(None, description="Comma-separated or JSON list of company IDs"),
    base_currency: Optional[str] = Query(None, description="Target currency"),
    user: AppUser = _view_journals,
) -> dict[str, Any]:
    """Official Journal Audit report matching Odoo Report 20."""
    await TenantService.get_tenant(tenant_id, str(user.id))
    from doova_one_view.api.agent.tools_refactored.banking import get_journal_audit_tool
    return get_journal_audit_tool(
        tenant_ids=[tenant_id] if tenant_id else None,
        start_date=start_date or date_from,
        end_date=end_date or date_to,
        company_ids=_company_ids(company_ids),
        base_currency=base_currency,
    )

@router.get("/{tenant_id}/{journal_id}")
async def get_journal(
    tenant_id: str,
    journal_id: int,
    company_ids: Optional[str] = Query(None, description="Comma-separated or JSON list of company IDs"),
    user: AppUser = _view_journals,
) -> AccountJournalRead:
    await TenantService.get_tenant(tenant_id, str(user.id))
    return await AccountJournalService.get_journal(tenant_id, journal_id, _company_ids(company_ids))
