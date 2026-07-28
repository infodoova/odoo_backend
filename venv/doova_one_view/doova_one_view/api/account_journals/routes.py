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

def _company_ids(company_id: Optional[int], companies: Optional[str]) -> Optional[list[int]]:
    return parse_company_ids(company_id if company_id is not None else companies)

@router.get("/{tenant_id}/filters")
async def get_journals_filters(
    tenant_id: str,
    company_id: Optional[int] = Query(None),
    companies: Optional[str] = Query(None),
    user: AppUser = _view_journals,
) -> dict[str, Any]:
    await TenantService.get_tenant(tenant_id, str(user.id))
    return await AccountJournalService.get_journals_filters(tenant_id, _company_ids(company_id, companies))

@router.get("/{tenant_id}/export")
async def export_journals(
    tenant_id: str,
    company_id: Optional[int] = Query(None),
    companies: Optional[str] = Query(None),
    user: AppUser = _export_journals,
) -> Response:
    await TenantService.get_tenant(tenant_id, str(user.id))
    csv_content = await AccountJournalService.export_journals_csv(tenant_id, _company_ids(company_id, companies))
    return Response(
        content=csv_content,
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename=account_journals_{tenant_id}.csv"},
    )

@router.post("/{tenant_id}/search")
async def search_journals(
    tenant_id: str,
    request: SearchRequest,
    company_id: Optional[int] = Query(None),
    companies: Optional[str] = Query(None),
    user: AppUser = _view_journals,
) -> PaginatedResponse[AccountJournalRead]:
    await TenantService.get_tenant(tenant_id, str(user.id))
    company_ids = _company_ids(company_id, companies)
    if company_ids is None:
        company_ids = parse_company_ids(request.company_id if request.company_id is not None else request.companies)
    return await AccountJournalService.search_journals(tenant_id, request.filters, request.limit, request.offset, company_ids)

@router.get("/{tenant_id}")
async def list_journals(
    tenant_id: str,
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    search: Optional[str] = Query(None),
    company_id: Optional[int] = Query(None),
    companies: Optional[str] = Query(None),
    user: AppUser = _view_journals,
) -> PaginatedResponse[AccountJournalRead]:
    await TenantService.get_tenant(tenant_id, str(user.id))
    return await AccountJournalService.get_journals(tenant_id, limit, offset, search, _company_ids(company_id, companies))

@router.get("/{tenant_id}/{journal_id}")
async def get_journal(
    tenant_id: str,
    journal_id: int,
    company_id: Optional[int] = Query(None),
    companies: Optional[str] = Query(None),
    user: AppUser = _view_journals,
) -> AccountJournalRead:
    await TenantService.get_tenant(tenant_id, str(user.id))
    return await AccountJournalService.get_journal(tenant_id, journal_id, _company_ids(company_id, companies))
