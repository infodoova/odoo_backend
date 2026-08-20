"""
Accounting API routes.

NOTE: Revenue / Expense / Profit summary endpoints have moved to /api/v1/kpi/
      (revenues/today, revenues/monthly, revenues/yearly, expenses/*, profits/*)
      so that numbers are consistent with the KPI overview dashboard.
"""

from typing import Any, Optional

import asyncio
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response

from odoo_app.models import AppUser
from doova_one_view.api.accounting.schemas import SearchRequest, ProfitAndLossSummary, ExpenseBreakdownResponse
from doova_one_view.api.accounting.service import AccountingService
from doova_one_view.api.common.utils import parse_company_ids
from doova_one_view.api.dependencies import get_current_user
from doova_one_view.api.auth.permissions import require_permissions, require_any_permission

_view_accounting_overview = Depends(require_permissions("view_accounting_overview"))
_view_accounting_moves    = Depends(require_permissions("view_accounting_moves"))
_export_accounting_moves  = Depends(require_permissions("export_accounting_moves"))
from doova_one_view.api.tenants.service import TenantService

router = APIRouter(prefix="/accounting", tags=["Accounting"])


async def _get_tenant_id_for_user(user: AppUser) -> str:
    """Return the first tenant the user has access to."""
    def _fetch():
        from odoo_app.models.user_tenant_access import UserTenantAccess
        access = UserTenantAccess.objects.filter(user=user).select_related('tenant').first()
        return str(access.tenant_id) if access else None

    tenant_id = await asyncio.to_thread(_fetch)
    if not tenant_id:
        raise HTTPException(status_code=400, detail="No tenant associated with this user")
    return tenant_id


async def _get_all_tenants_for_user(user: AppUser) -> list[dict[str, Any]]:
    """Return all tenants the user has access to."""
    def _fetch():
        from odoo_app.models.user_tenant_access import UserTenantAccess
        return list(UserTenantAccess.objects.filter(user=user).select_related('tenant'))

    accesses = await asyncio.to_thread(_fetch)
    if not accesses:
        raise HTTPException(status_code=400, detail="No tenants associated with this user")
    return [{"id": str(access.tenant_id), "name": access.tenant.name} for access in accesses]


def _company_ids(company_id: Optional[int], companies: Optional[str]) -> Optional[list[int]]:
    return parse_company_ids(company_id if company_id is not None else companies)


@router.get("/{tenant_id}/summary")
async def get_accounting_summary(
    tenant_id: str,
    start_date: Optional[str] = Query(None),
    end_date: Optional[str] = Query(None),
    date_from: Optional[str] = Query(None),
    date_to: Optional[str] = Query(None),
    company_id: Optional[int] = Query(None),
    companies: Optional[str] = Query(None),
    base_currency: Optional[str] = Query(None, description="Target currency for financial values"),
    user: AppUser = _view_accounting_overview,
) -> dict[str, Any]:
    await TenantService.get_tenant(tenant_id, str(user.id))
    return await AccountingService.get_summary(
        tenant_id,
        start_date or date_from,
        end_date or date_to,
        _company_ids(company_id, companies),
        base_currency,
    )


@router.get("/{tenant_id}/dashboard")
async def get_accounting_dashboard(
    tenant_id: str,
    start_date: Optional[str] = Query(None),
    end_date: Optional[str] = Query(None),
    date_from: Optional[str] = Query(None),
    date_to: Optional[str] = Query(None),
    company_id: Optional[int] = Query(None),
    companies: Optional[str] = Query(None),
    includeCompanies: Optional[str] = Query(None),
    include_companies: Optional[str] = Query(None),
    base_currency: Optional[str] = Query(None, description="Target currency for financial values"),
    user: AppUser = _view_accounting_overview,
) -> dict[str, Any]:
    await TenantService.get_tenant(tenant_id, str(user.id))
    return await AccountingService.get_dashboard(
        tenant_id,
        start_date or date_from,
        end_date or date_to,
        _company_ids(company_id, companies),
        base_currency,
    )

from doova_one_view.api.accounting.schemas import BankCashSummaryResponse

@router.get("/{tenant_id}/dashboard/bank-cash-summary", response_model=BankCashSummaryResponse)
async def get_bank_cash_summary(
    tenant_id: str,
    start_date: Optional[str] = Query(None),
    end_date: Optional[str] = Query(None),
    date_from: Optional[str] = Query(None),
    date_to: Optional[str] = Query(None),
    company_id: Optional[int] = Query(None),
    companies: Optional[str] = Query(None),
    base_currency: Optional[str] = Query(None, description="Target currency for financial values"),
    user: AppUser = _view_accounting_overview,
) -> BankCashSummaryResponse:
    """Dedicated endpoint for the Bank & Cash Balance vs Cash Flow dashboard card."""
    await TenantService.get_tenant(tenant_id, str(user.id))
    data = await AccountingService.get_bank_cash_summary(
        tenant_id,
        start_date or date_from,
        end_date or date_to,
        _company_ids(company_id, companies),
        base_currency,
    )
    return BankCashSummaryResponse(
        opening_cash_balance=data.get("opening_cash_balance", 0.0),
        cash_in=data.get("cash_in", 0.0),
        cash_out=data.get("cash_out", 0.0),
        closing_cash_balance=data.get("closing_cash_balance", 0.0),
        bank_balance=data.get("bank_balance", 0.0),
        cash_flow_breakdown=data.get("cash_flow_breakdown", [])
    )

@router.get("/{tenant_id}/pnl", response_model=ProfitAndLossSummary)
async def get_profit_and_loss(
    tenant_id: str,
    start_date: Optional[str] = Query(None),
    end_date: Optional[str] = Query(None),
    date_from: Optional[str] = Query(None),
    date_to: Optional[str] = Query(None),
    company_id: Optional[int] = Query(None),
    companies: Optional[str] = Query(None),
    base_currency: Optional[str] = Query(None, description="Target currency for financial values"),
    user: AppUser = _view_accounting_overview,
) -> ProfitAndLossSummary:
    """Retrieve a structured Profit & Loss breakdown."""
    await TenantService.get_tenant(tenant_id, str(user.id))
    data = await AccountingService.get_pnl_summary(
        tenant_id,
        start_date or date_from,
        end_date or date_to,
        _company_ids(company_id, companies),
        base_currency,
    )
    return ProfitAndLossSummary(**data)


@router.get("/{tenant_id}/expense-breakdown", response_model=ExpenseBreakdownResponse)
async def get_expense_breakdown(
    tenant_id: str,
    start_date: Optional[str] = Query(None),
    end_date: Optional[str] = Query(None),
    date_from: Optional[str] = Query(None),
    date_to: Optional[str] = Query(None),
    company_id: Optional[int] = Query(None),
    companies: Optional[str] = Query(None),
    base_currency: Optional[str] = Query(None, description="Target currency for financial values"),
    user: AppUser = _view_accounting_overview,
) -> ExpenseBreakdownResponse:
    """Expense breakdown by category (Rent, Salaries, Purchases, etc.)."""
    await TenantService.get_tenant(tenant_id, str(user.id))
    data = await AccountingService.get_expense_breakdown(
        tenant_id,
        start_date or date_from,
        end_date or date_to,
        _company_ids(company_id, companies),
        base_currency,
    )
    return ExpenseBreakdownResponse(**data)


@router.get("/{tenant_id}/kpis")
async def get_accounting_kpis(
    tenant_id: str,
    start_date: Optional[str] = Query(None),
    end_date: Optional[str] = Query(None),
    date_from: Optional[str] = Query(None),
    date_to: Optional[str] = Query(None),
    company_id: Optional[int] = Query(None),
    companies: Optional[str] = Query(None),
    includeCompanies: Optional[str] = Query(None),
    include_companies: Optional[str] = Query(None),
    base_currency: Optional[str] = Query(None, description="Target currency for financial values"),
    user: AppUser = _view_accounting_overview,
) -> dict[str, Any]:
    await TenantService.get_tenant(tenant_id, str(user.id))
    return await AccountingService.get_dashboard(
        tenant_id,
        start_date or date_from,
        end_date or date_to,
        _company_ids(company_id, companies),
        base_currency,
    )

@router.get("/{tenant_id}/pnl", response_model=ProfitAndLossSummary)
async def get_profit_and_loss(
    tenant_id: str,
    start_date: Optional[str] = Query(None),
    end_date: Optional[str] = Query(None),
    date_from: Optional[str] = Query(None),
    date_to: Optional[str] = Query(None),
    company_id: Optional[int] = Query(None),
    companies: Optional[str] = Query(None),
    base_currency: Optional[str] = Query(None, description="Target currency for financial values"),
    user: AppUser = Depends(get_current_user),
) -> ProfitAndLossSummary:
    """Retrieve a structured Profit & Loss breakdown."""
    await TenantService.get_tenant(tenant_id, str(user.id))
    data = await AccountingService.get_pnl_summary(
        tenant_id,
        start_date or date_from,
        end_date or date_to,
        _company_ids(company_id, companies),
        base_currency,
    )
    return ProfitAndLossSummary(**data)



@router.get("/{tenant_id}/moves")
async def list_accounting_moves(
    tenant_id: str,
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    partner_id: Optional[int] = Query(None),
    move_type: Optional[str] = Query(None, description="out_invoice, in_invoice, entry, etc."),
    company_id: Optional[int] = Query(None),
    companies: Optional[str] = Query(None),
    user: AppUser = _view_accounting_moves,
) -> dict[str, Any]:
    await TenantService.get_tenant(tenant_id, str(user.id))
    return await AccountingService.get_moves(
        tenant_id, limit, offset, partner_id, _company_ids(company_id, companies), move_type
    )


@router.get("/{tenant_id}/moves/{move_id}")
async def get_accounting_move(
    tenant_id: str,
    move_id: int,
    company_id: Optional[int] = Query(None),
    companies: Optional[str] = Query(None),
    user: AppUser = _view_accounting_moves,
) -> dict[str, Any]:
    await TenantService.get_tenant(tenant_id, str(user.id))
    return await AccountingService.get_move(
        tenant_id, move_id, _company_ids(company_id, companies)
    )


@router.get("/{tenant_id}/filters")
async def get_accounting_filters(
    tenant_id: str,
    user: AppUser = _view_accounting_moves,
) -> dict[str, Any]:
    await TenantService.get_tenant(tenant_id, str(user.id))
    return await AccountingService.get_filters(tenant_id)


@router.post("/{tenant_id}/search")
async def search_accounting_moves(
    tenant_id: str,
    request: SearchRequest,
    user: AppUser = _view_accounting_moves,
) -> dict[str, Any]:
    await TenantService.get_tenant(tenant_id, str(user.id))
    company_ids = parse_company_ids(
        request.company_id if request.company_id is not None else request.companies
    )
    return await AccountingService.search_moves(
        tenant_id, request.filters, request.limit, request.offset, company_ids
    )


@router.get("/{tenant_id}/export")
async def export_accounting_moves(
    tenant_id: str,
    company_id: Optional[int] = Query(None),
    companies: Optional[str] = Query(None),
    user: AppUser = _export_accounting_moves,
) -> Response:
    await TenantService.get_tenant(tenant_id, str(user.id))
    csv_content = await AccountingService.export_moves_csv(
        tenant_id, _company_ids(company_id, companies)
    )
    return Response(
        content=csv_content,
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename=account_moves_{tenant_id}.csv"},
    )


# ── Drill-Down Endpoints ────────────────────────────────────────────────────────

from doova_one_view.api.accounting.schemas import (
    MetricDetailResponse, DailyMovesResponse, MarketBreakdownResponse,
    ProductMovesDetailResponse, EntityProfileResponse, AgingDetailsResponse
)

@router.get("/{tenant_id}/dashboard/metric-details")
async def get_dashboard_metric_details(
    tenant_id: str,
    metric: str = Query(..., description="The metric name (e.g., total_revenue, total_expenses, net_profit, receivable_balance, payable_balance, overdue_receivable, overdue_payable)"),
    start_date: Optional[str] = Query(None, description="Start date (YYYY-MM-DD)"),
    end_date: Optional[str] = Query(None, description="End date (YYYY-MM-DD)"),
    companies: Optional[str] = Query(None, description="Single ID or comma-separated IDs"),
    base_currency: Optional[str] = Query(None, description="Target currency for financial values"),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    user: AppUser = _view_accounting_overview,
) -> MetricDetailResponse:
    await TenantService.get_tenant(tenant_id, str(user.id))
    company_ids = parse_company_ids(companies)
    return await AccountingService.get_dashboard_metric_details(
        tenant_id=tenant_id,
        metric=metric,
        start_date=start_date,
        end_date=end_date,
        company_ids=company_ids,
        base_currency=base_currency,
        limit=limit,
        offset=offset
    )

@router.get("/{tenant_id}/dashboard/daily-moves")
async def get_daily_moves(
    tenant_id: str,
    day: str = Query(..., description="The calendar day to drill into (YYYY-MM-DD)"),
    companies: Optional[str] = Query(None, description="Single ID or comma-separated IDs"),
    base_currency: Optional[str] = Query(None, description="Target currency for financial values"),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    user: AppUser = _view_accounting_overview,
) -> DailyMovesResponse:
    await TenantService.get_tenant(tenant_id, str(user.id))
    company_ids = parse_company_ids(companies)
    return await AccountingService.get_daily_moves(
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
    section: str = Query(..., description="Section name: top_revenue_customers or top_expense_vendors"),
    entity_id: int = Query(..., description="The entity ID (partner_id)"),
    start_date: Optional[str] = Query(None, description="Start date (YYYY-MM-DD)"),
    end_date: Optional[str] = Query(None, description="End date (YYYY-MM-DD)"),
    companies: Optional[str] = Query(None, description="Single ID or comma-separated IDs"),
    base_currency: Optional[str] = Query(None, description="Target currency for financial values"),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    user: AppUser = _view_accounting_overview,
) -> MarketBreakdownResponse:
    await TenantService.get_tenant(tenant_id, str(user.id))
    company_ids = parse_company_ids(companies)
    return await AccountingService.get_market_breakdown_details(
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
    entity_type: str = Query(..., description="'customer' or 'vendor'/'supplier'"),
    entity_id: int = Query(..., description="The entity's Django pk"),
    user: AppUser = _view_accounting_overview,
) -> EntityProfileResponse:
    await TenantService.get_tenant(tenant_id, str(user.id))
    return await AccountingService.get_entity_profile(
        tenant_id=tenant_id,
        entity_type=entity_type,
        entity_id=entity_id
    )

@router.get("/{tenant_id}/dashboard/product-moves-details")
async def get_product_moves_details(
    tenant_id: str,
    product_id: int = Query(..., description="The product's Django pk"),
    start_date: Optional[str] = Query(None, description="Start date (YYYY-MM-DD)"),
    end_date: Optional[str] = Query(None, description="End date (YYYY-MM-DD)"),
    companies: Optional[str] = Query(None, description="Single ID or comma-separated IDs"),
    base_currency: Optional[str] = Query(None, description="Target currency for financial values"),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    user: AppUser = _view_accounting_overview,
) -> ProductMovesDetailResponse:
    await TenantService.get_tenant(tenant_id, str(user.id))
    company_ids = parse_company_ids(companies)
    return await AccountingService.get_product_moves_details(
        tenant_id=tenant_id,
        product_id=product_id,
        start_date=start_date,
        end_date=end_date,
        company_ids=company_ids,
        base_currency=base_currency,
        limit=limit,
        offset=offset
    )


@router.get("/{tenant_id}/dashboard/aging-details")
async def get_aging_details(
    tenant_id: str,
    bucket: str = Query(..., description="Aging bucket: '0-30', '31-60', '61-90', '90+'"),
    move_type: str = Query(..., description="'out_invoice' for receivables, 'in_invoice' for payables"),
    start_date: Optional[str] = Query(None, description="Start date (YYYY-MM-DD)"),
    end_date: Optional[str] = Query(None, description="End date (YYYY-MM-DD)"),
    companies: Optional[str] = Query(None, description="Single ID or comma-separated IDs"),
    base_currency: Optional[str] = Query(None, description="Target currency for financial values"),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    user: AppUser = _view_accounting_overview,
) -> AgingDetailsResponse:
    await TenantService.get_tenant(tenant_id, str(user.id))
    company_ids = parse_company_ids(companies)
    return await AccountingService.get_aging_details(
        tenant_id=tenant_id,
        bucket=bucket,
        move_type=move_type,
        start_date=start_date,
        end_date=end_date,
        company_ids=company_ids,
        base_currency=base_currency,
        limit=limit,
        offset=offset
    )

from doova_one_view.api.accounting.schemas import JournalCardsResponse

@router.get("/{tenant_id}/dashboard/journals")
async def get_dashboard_journals(
    tenant_id: str,
    start_date: Optional[str] = Query(None, description="Start date (YYYY-MM-DD)"),
    end_date: Optional[str] = Query(None, description="End date (YYYY-MM-DD)"),
    companies: Optional[str] = Query(None, description="Single ID or comma-separated IDs"),
    base_currency: Optional[str] = Query(None, description="Target currency for financial values"),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    user: AppUser = _view_accounting_overview,
) -> JournalCardsResponse:
    await TenantService.get_tenant(tenant_id, str(user.id))
    company_ids = parse_company_ids(companies)
    return await AccountingService.get_journal_cards(
        tenant_id=tenant_id,
        start_date=start_date,
        end_date=end_date,
        company_ids=company_ids,
        base_currency=base_currency,
        limit=limit,
        offset=offset
    )
