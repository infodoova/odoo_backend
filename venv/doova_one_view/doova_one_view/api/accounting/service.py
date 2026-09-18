"""
Accounting API service.
"""

import asyncio
from datetime import date, datetime, timedelta
from typing import Any, Optional, Union

from django.db.models import Avg, Case, Count, DecimalField, F, Prefetch, Q, Sum, When

from odoo_app.models.account_move import AccountMove
from odoo_app.models.account_move_line import AccountMoveLine
from doova_one_view.api.common.exceptions import NotFoundError, ValidationError
from doova_one_view.api.kpi.service import (
    _get_rate_map, _get_conversion_rate, _sum_converted
)

def _to_float(value: Any) -> float:
    if value is None:
        return 0.0
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _iso(value: Any) -> Optional[str]:
    if value is None:
        return None
    try:
        return value.isoformat()
    except Exception:
        return str(value)


def _metric(value: float, previous_value: float = 0.0) -> dict[str, float]:
    value = _to_float(value)
    previous_value = _to_float(previous_value)
    change = ((value - previous_value) / abs(previous_value) * 100) if previous_value else 0.0
    return {
        "value": value,
        "previous_value": previous_value,
        "change_percentage": change,
        "change_pct": change,
    }


def _csv_escape(value: Any) -> str:
    s = str(value)
    if any(ch in s for ch in (",", '"', "\n", "\r")):
        return f'"{s.replace(chr(34), chr(34) + chr(34))}"'
    return s


def _partner_obj(obj: Any) -> Optional[dict[str, Any]]:
    partner = getattr(obj, "partner", None)
    if partner is None:
        return None
    return {
        "id": partner.id,
        "odoo_id": partner.odoo_id,
        "name": partner.name,
        "email": getattr(partner, "email", None),
        "phone": getattr(partner, "phone", None),
        "country_code": getattr(partner, "country_code", None),
        "city": getattr(partner, "city", None),
        "is_customer": getattr(partner, "is_customer", False),
        "is_supplier": getattr(partner, "is_supplier", False),
    }


def _company_obj(obj: Any) -> Optional[dict[str, Any]]:
    company = getattr(obj, "company", None)
    if company is None:
        return None
    return {
        "id": company.id,
        "odoo_id": company.odoo_id,
        "name": company.name,
        "currency_code": getattr(company, "currency_code", None),
        "country_code": getattr(company, "country_code", None),
    }


def _product_obj(line: AccountMoveLine) -> Optional[dict[str, Any]]:
    product = getattr(line, "product", None)
    if product is None:
        return None
    return {
        "id": product.id,
        "odoo_id": product.odoo_id,
        "name": product.name,
        "display_name": product.name,
        "default_code": getattr(product, "default_code", None),
        "barcode": getattr(product, "barcode", None),
        "product_type": getattr(product, "product_type", None),
        "list_price": _to_float(getattr(product, "list_price", 0)),
        "standard_price": _to_float(getattr(product, "standard_price", 0)),
        "uom_name": getattr(product, "uom_name", None),
    }


def _move_to_item(move: AccountMove) -> dict[str, Any]:
    partner = _partner_obj(move)
    company = _company_obj(move)
    partner_name = partner["name"] if partner else ""
    company_name = company["name"] if company else ""

    return {
        "id": move.id,
        "odoo_id": move.odoo_id,
        "name": move.odoo_name or "",
        "odoo_name": move.odoo_name,
        "ref": move.ref or "",
        "date": _iso(move.date),
        "invoice_date": _iso(move.invoice_date),
        "invoice_date_due": _iso(move.invoice_date_due),
        "synced_at": _iso(move.synced_at),
        "move_type": move.move_type,
        "state": move.state,
        "payment_state": move.payment_state or "",
        "amount_untaxed": _to_float(move.amount_untaxed),
        "amount_tax": _to_float(move.amount_tax),
        "amount_total": _to_float(move.amount_total),
        "amount_residual": _to_float(move.amount_residual),
        "currency": move.currency_code,
        "currency_code": move.currency_code,
        "partner": partner,
        "partner_id": getattr(move, "partner_id", None),
        "partner_name": partner_name,
        "company": company,
        "company_id": getattr(move, "company_id", None),
        "company_name": company_name,
        "invoice_origin": move.invoice_origin,
        "journal": None,
        "journal_id": None,
        "journal_name": "",
        "user": None,
        "user_id": None,
        "user_name": "",
    }


def _line_to_item(line: AccountMoveLine) -> dict[str, Any]:
    product = _product_obj(line)
    partner = _partner_obj(line)
    company = _company_obj(line)
    price_subtotal = _to_float(line.price_subtotal)

    return {
        "id": line.id,
        "odoo_id": line.odoo_id,
        "account_id": None,
        "account_name": line.account_name or "",
        "account_code": line.account_code or "",
        "account_type": line.account_type,
        "name": line.name or "",
        "quantity": _to_float(line.quantity),
        "price_unit": _to_float(line.price_unit),
        "price_subtotal": price_subtotal,
        "price_total": price_subtotal,
        "debit": _to_float(line.debit),
        "credit": _to_float(line.credit),
        "balance": _to_float(line.balance),
        "amount_currency": _to_float(line.amount_currency),
        "currency": line.currency_code,
        "currency_code": line.currency_code,
        "product": product,
        "product_id": getattr(line, "product_id", None),
        "product_name": product["name"] if product else "",
        "partner": partner,
        "partner_id": getattr(line, "partner_id", None),
        "partner_name": partner["name"] if partner else "",
        "company": company,
        "company_id": getattr(line, "company_id", None),
        "company_name": company["name"] if company else "",
        "synced_at": _iso(line.synced_at),
    }


def _empty_aging() -> list[dict[str, Any]]:
    return [
        {"bucket": "0-30", "amount": 0.0, "count": 0},
        {"bucket": "31-60", "amount": 0.0, "count": 0},
        {"bucket": "61-90", "amount": 0.0, "count": 0},
        {"bucket": "90+", "amount": 0.0, "count": 0},
    ]


class AccountingService:
    """Service for accounting operations."""

    @staticmethod
    def _base_qs(
        tenant_ids: Optional[list[str]] = None,
        company_ids: Optional[list[int]] = None,
    ):
        from doova_one_view.api.agent.query_context import (
            normalize_tenant_ids,
            normalize_company_ids,
            apply_scope_filter_orm,
        )
        t_ids = normalize_tenant_ids(tenant_ids)
        c_ids = normalize_company_ids(company_ids)

        qs = AccountMove.objects.all()
        qs = apply_scope_filter_orm(qs, "tenant_id", t_ids)
        qs = apply_scope_filter_orm(qs, "company_id", c_ids)
        return qs

    @staticmethod
    def _date_qs(qs, start_date: Optional[str], end_date: Optional[str]):
        if start_date:
            qs = qs.filter(date__gte=start_date)
        if end_date:
            qs = qs.filter(date__lte=end_date)
        return qs

    @staticmethod
    def _get_tag4_account_ids(tenant_ids: Optional[list[str]] = None) -> set[int]:
        """Returns the set of Odoo account IDs carrying Tag 4 (Purchase Expenses accounts)."""
        from odoo_app.models.chart_of_accounts import ChartOfAccounts
        from doova_one_view.api.agent.query_context import apply_scope_filter_orm, normalize_tenant_ids
        try:
            t_ids = normalize_tenant_ids(tenant_ids)
            qs = ChartOfAccounts.objects.all()
            qs = apply_scope_filter_orm(qs, "tenant_id", t_ids)
            coas = qs.only("odoo_id", "tag_ids")
            tag4_ids = set()
            for c in coas:
                if c.tag_ids and 4 in c.tag_ids and c.odoo_id:
                    tag4_ids.add(c.odoo_id)
            return tag4_ids
        except Exception:
            return set()

    @staticmethod
    def _is_tag4_purchase_expense(
        tenant_ids: Optional[list[str]] = None,
        account_odoo_id: Optional[int] = None,
        company_ids: Optional[list[int]] = None,
        acode: Optional[str] = None,
        aname: Optional[str] = None,
        tag4_ids: Optional[set[int]] = None,
    ) -> bool:
        """
        In standard Odoo Accounting (P&L Line 50 / Executive Summary Line 32),
        accounts carrying Tag 4 (Purchase Expenses accounts / interim purchase clearing)
        are excluded from Operating Expenses.
        """
        if tag4_ids is None:
            tag4_ids = AccountingService._get_tag4_account_ids(tenant_ids)
        
        if account_odoo_id and account_odoo_id in tag4_ids:
            return True
            
        # Fallback if account_odoo_id is not yet populated
        code_str = (acode or "").strip()
        name_str = (aname or "").strip().lower()
        full_name = f"{code_str} {name_str}".strip().lower()
        
        if code_str.startswith("6011") or code_str.startswith("6012") or code_str.startswith("6018") or code_str.startswith("6052") or code_str.startswith("60510002") or code_str.startswith("60510003") or code_str.startswith("60510004"):
            return True
        if code_str in ("61121003", "61125002", "61181002", "62610004", "62610005", "62620004", "62620005", "62690002", "63110003", "67400002"):
            return True
        if any(kw in full_name for kw in [
            "purchase of goods", "purchase of assets", "purchases of assets", "cost of goods purchased",
            "freight - goods", "customs charges - goods", "purchase of spare part", "purchase of colorant",
            "purchases of raw materials", "purchases tools"
        ]):
            return True
        return False

    @staticmethod
    def _is_inventory_scrap_adjustment(atype: str, acode: str, aname: str, net_debit: float, tenant_ids: Optional[list[str]] = None, account_odoo_id: Optional[int] = None) -> bool:
        """
        In standard Odoo Chart of Accounts under Anglo-Saxon automated inventory valuation,
        interim stock valuation variance accounts (e.g. Products Loss, Damaged Products, 60520003)
        used for inventory scrap / valuation clearing represent inventory asset movements,
        not operational overhead expenditure.
        """
        if atype != "expense":
            return False
        if tenant_ids:
            return AccountingService._is_tag4_purchase_expense(tenant_ids=tenant_ids, account_odoo_id=account_odoo_id, acode=acode, aname=aname)
        name_clean = (aname or "").lower().strip()
        code_clean = (acode or "").lower().strip()
        full_name = f"{code_clean} {name_clean}".strip()
        
        if code_clean in ("60520003", "60510002") or code_clean.startswith("6011") or code_clean.startswith("6012") or code_clean.startswith("6018") or code_clean.startswith("6052"):
            return True
        if any(kw in full_name for kw in ["purchase of goods", "purchase of assets", "purchases of assets", "cost of goods purchased", "freight - goods", "customs charges - goods"]):
            return True
        if name_clean in ("products loss", "adjustment products loss") and net_debit < -5000000:
            return True
        return False

    @staticmethod
    async def get_moves(
        tenant_id: str,
        limit: int = 50,
        offset: int = 0,
        partner_id: Optional[int] = None,
        company_ids: Optional[list[int]] = None,
        move_type: Optional[str] = None,
    ) -> dict[str, Any]:
        def _list():
            qs = AccountingService._base_qs(tenant_id, company_ids)
            if partner_id is not None:
                qs = qs.filter(partner_id=partner_id)
            if move_type:
                qs = qs.filter(move_type=move_type)
            total = qs.count()
            moves = list(
                qs.select_related("partner", "company")
                .order_by("-date", "-id")[offset : offset + limit]
            )
            return moves, total

        moves, total = await asyncio.to_thread(_list)
        return {
            "items": [_move_to_item(m) for m in moves],
            "total": total,
            "limit": limit,
            "offset": offset,
            "applied_filters": {
                "tenant_id": tenant_id,
                "partner_id": partner_id,
                "company_ids": company_ids,
                "move_type": move_type,
            },
        }

    @staticmethod
    async def get_move(
        tenant_id: str,
        move_id: int,
        company_ids: Optional[list[int]] = None,
    ) -> dict[str, Any]:
        def _get():
            qs = AccountingService._base_qs(tenant_id, company_ids)
            try:
                return (
                    qs.select_related("partner", "company")
                    .prefetch_related(
                        Prefetch(
                            "lines",
                            queryset=AccountMoveLine.objects.select_related(
                                "product", "partner", "company"
                            ),
                        )
                    )
                    .get(id=move_id)
                )
            except AccountMove.DoesNotExist:
                raise NotFoundError("AccountMove", str(move_id))

        move = await asyncio.to_thread(_get)
        item = _move_to_item(move)
        item["lines"] = [_line_to_item(line) for line in move.lines.all()]
        return item

    @staticmethod
    async def get_summary(
        tenant_id: str,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        company_ids: Optional[list[int]] = None,
        base_currency: Optional[str] = None,
    ) -> dict[str, Any]:
        def _summary():
            qs = AccountingService._date_qs(
                AccountingService._base_qs(tenant_id, company_ids), start_date, end_date
            )
            rate_map = _get_rate_map()
            effective_base = base_currency or "XAF"
            
            invoices = qs.filter(move_type="out_invoice", state="posted")
            bills = qs.filter(move_type="in_invoice", state="posted")
            
            total_invoiced = _sum_converted(invoices, "amount_total", effective_base, rate_map)
            total_receivable = _sum_converted(invoices, "amount_residual", effective_base, rate_map)
            
            total_bills = _sum_converted(bills, "amount_total", effective_base, rate_map)
            total_payable = _sum_converted(bills, "amount_residual", effective_base, rate_map)
            return {
                "total_invoiced": total_invoiced,
                "total_bills": total_bills,
                "total_receivable": total_receivable,
                "total_payable": total_payable,
                "net_profit_estimate": total_invoiced - total_bills,
                "applied_filters": {
                    "tenant_id": tenant_id,
                    "start_date": start_date,
                    "end_date": end_date,
                    "company_ids": company_ids,
                },
            }

        return await asyncio.to_thread(_summary)

    @staticmethod
    async def get_dashboard(
        tenant_id: str,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        company_ids: Optional[list[int]] = None,
        base_currency: Optional[str] = None,
    ) -> dict[str, Any]:
        def _dashboard():
            qs = AccountingService._date_qs(
                AccountingService._base_qs(tenant_id, company_ids), start_date, end_date
            )
            
            rate_map = _get_rate_map()
            effective_base = base_currency or "XAF"
            
            revenue_qs = qs.filter(move_type="out_invoice", state="posted")
            expense_qs = qs.filter(move_type="in_invoice", state="posted")

            from odoo_app.models.account_move_line import AccountMoveLine
            from django.db.models import Sum
            
            # Scoped direct index query on AccountMoveLine
            line_base = AccountMoveLine.objects.filter(
                tenant_id=tenant_id,
                account_move__state='posted'
            )
            if company_ids:
                line_base = line_base.filter(company_id__in=company_ids)
            if start_date:
                line_base = line_base.filter(account_move__date__gte=start_date)
            if end_date:
                line_base = line_base.filter(account_move__date__lte=end_date)

            tag4_ids = AccountingService._get_tag4_account_ids(tenant_id)
            line_aggs = line_base.values("company_id", "account_odoo_id", "account_type", "account_code", "account_name", "company__currency_code").annotate(
                total_debit=Sum("debit"),
                total_credit=Sum("credit")
            )
            
            true_revenue = 0.0
            true_other_income = 0.0
            true_cogs = 0.0
            true_expenses = 0.0
            true_depreciation = 0.0
            true_taxes_interest = 0.0
            
            for agg in line_aggs:
                cid = agg.get("company_id")
                a_odoo_id = agg.get("account_odoo_id")
                atype = agg["account_type"] or ""
                acode = agg["account_code"] or ""
                aname = agg["account_name"] or ""
                # Use company currency to convert to dashboard base currency
                company_currency = agg["company__currency_code"] or "COMPANY_BASE"
                rate = _get_conversion_rate(company_currency, effective_base, rate_map)
                
                net_credit = (_to_float(agg["total_credit"]) - _to_float(agg["total_debit"])) * rate
                net_debit = (_to_float(agg["total_debit"]) - _to_float(agg["total_credit"])) * rate

                if atype == "income":
                    true_revenue += net_credit
                elif atype == "income_other":
                    true_other_income += net_credit
                elif atype == "expense_direct_cost":
                    true_cogs += net_debit
                elif atype == "expense_depreciation":
                    true_depreciation += net_debit
                elif atype == "expense":
                    if not AccountingService._is_tag4_purchase_expense(tenant_ids=[tenant_id] if tenant_id else None, account_odoo_id=a_odoo_id, company_ids=[cid] if cid else None, acode=acode, aname=aname, tag4_ids=tag4_ids):
                        true_expenses += net_debit
                        if acode.startswith("67") or acode.startswith("69"):
                            true_taxes_interest += net_debit

            gross_profit = true_revenue - true_cogs
            total_all_expenses = true_expenses + true_depreciation
            ebit = gross_profit - true_expenses
            net_profit = gross_profit + true_other_income - total_all_expenses
            
            cumulative_qs = AccountingService._base_qs(tenant_id, company_ids)
            if end_date:
                cumulative_qs = cumulative_qs.filter(date__lte=end_date)
            cumulative_qs = cumulative_qs.filter(state='posted')
            
            cum_lines = AccountMoveLine.objects.filter(
                tenant_id=tenant_id,
                account_move__state='posted',
                account_type__in=[
                    "asset_receivable", "liability_payable", "liability_current", "asset_cash",
                    "asset_current", "asset_fixed", "asset_non_current", "asset_prepayments"
                ]
            )
            if company_ids:
                cum_lines = cum_lines.filter(company_id__in=company_ids)
            if end_date:
                cum_lines = cum_lines.filter(account_move__date__lte=end_date)

            cumulative_aggs = cum_lines.values("account_type", "company__currency_code").annotate(
                total_debit=Sum("debit"),
                total_credit=Sum("credit")
            )
            
            receivable_balance = 0.0
            payable_balance = 0.0
            bank_balance = 0.0
            total_assets = 0.0
            asset_breakdown = {
                "cash_and_equivalents": 0.0,
                "accounts_receivable": 0.0,
                "current_assets": 0.0,
                "fixed_assets": 0.0,
                "non_current_assets": 0.0,
                "prepayments": 0.0,
            }
            
            for agg in cumulative_aggs:
                company_currency = agg["company__currency_code"] or "COMPANY_BASE"
                rate = _get_conversion_rate(company_currency, effective_base, rate_map)
                atype = agg["account_type"]
                net = (_to_float(agg["total_debit"]) - _to_float(agg["total_credit"])) * rate
                
                if atype.startswith("asset"):
                    total_assets += net

                if atype == "asset_receivable":
                    receivable_balance += net
                    asset_breakdown["accounts_receivable"] += net
                elif atype == "asset_cash":
                    bank_balance += net
                    asset_breakdown["cash_and_equivalents"] += net
                elif atype == "asset_current":
                    asset_breakdown["current_assets"] += net
                elif atype == "asset_fixed":
                    asset_breakdown["fixed_assets"] += net
                elif atype == "asset_non_current":
                    asset_breakdown["non_current_assets"] += net
                elif atype == "asset_prepayments":
                    asset_breakdown["prepayments"] += net
                elif atype in ("liability_payable", "liability_current"):
                    payable_balance -= net # payables are credit normal

            # --- Bank & Cash Balances Details ---
            opening_cash_balance = 0.0
            cash_in = 0.0
            cash_out = 0.0
            
            # Opening balance (moves strictly before start_date)
            if start_date:
                open_lines = AccountMoveLine.objects.filter(
                    tenant_id=tenant_id,
                    account_move__state='posted',
                    account_move__date__lt=start_date,
                    account_type="asset_cash"
                )
                if company_ids:
                    open_lines = open_lines.filter(company_id__in=company_ids)

                opening_aggs = open_lines.values("company__currency_code").annotate(
                    net_cash=Sum("debit") - Sum("credit")
                )
                for agg in opening_aggs:
                    comp_curr = agg["company__currency_code"] or "COMPANY_BASE"
                    rate = _get_conversion_rate(comp_curr, effective_base, rate_map)
                    opening_cash_balance += _to_float(agg["net_cash"]) * rate
            else:
                opening_cash_balance = 0.0 # If all-time, opening is 0

            # Cash In & Out (moves within the date range)
            period_lines = line_base.filter(account_type="asset_cash")
            period_aggs = period_lines.values("company__currency_code").annotate(
                total_debit=Sum("debit"),
                total_credit=Sum("credit")
            )
            for agg in period_aggs:
                comp_curr = agg["company__currency_code"] or "COMPANY_BASE"
                rate = _get_conversion_rate(comp_curr, effective_base, rate_map)
                
                # In Odoo, for asset accounts, Debit is Increase (In), Credit is Decrease (Out)
                cash_in += _to_float(agg["total_debit"]) * rate
                cash_out += _to_float(agg["total_credit"]) * rate

            today = date.today()
            overdue_filter = Q(invoice_date_due__lt=today) & ~Q(payment_state__in=["paid", "reversed"])
            
            # Note: overdue amounts still rely on invoice residuals but look at ALL invoices up to end_date
            # because 'amount_residual' is an invoice-level field, not easily derived from generic move lines.
            overdue_receivable = _sum_converted(
                cumulative_qs.filter(overdue_filter, move_type="out_invoice", amount_residual__gt=0),
                "amount_residual", effective_base, rate_map
            )
            overdue_payable = _sum_converted(
                cumulative_qs.filter(overdue_filter, move_type="in_invoice", amount_residual__gt=0),
                "amount_residual", effective_base, rate_map
            )

            rev_cust_map = {}
            for r in revenue_qs.filter(partner_id__isnull=False).values("partner_id", "partner__name", "currency_code").annotate(value=Sum("amount_total")):
                pid = r['partner_id']
                if pid not in rev_cust_map:
                    rev_cust_map[pid] = {'name': r['partner__name'], 'value': 0.0}
                code = r['currency_code'] or "COMPANY_BASE"
                rev_cust_map[pid]['value'] += _to_float(r['value']) * _get_conversion_rate(code, effective_base, rate_map)
            top_revenue_customers = [
                {"id": k, "name": v['name'] or "", "value": v['value']}
                for k, v in sorted(rev_cust_map.items(), key=lambda x: x[1]['value'], reverse=True)[:5]
            ]
            
            exp_vend_map = {}
            for r in expense_qs.filter(partner_id__isnull=False).values("partner_id", "partner__name", "currency_code").annotate(value=Sum("amount_total")):
                pid = r['partner_id']
                if pid not in exp_vend_map:
                    exp_vend_map[pid] = {'name': r['partner__name'], 'value': 0.0}
                code = r['currency_code'] or "COMPANY_BASE"
                exp_vend_map[pid]['value'] += _to_float(r['value']) * _get_conversion_rate(code, effective_base, rate_map)
            top_expense_vendors = [
                {"id": k, "name": v['name'] or "", "value": v['value']}
                for k, v in sorted(exp_vend_map.items(), key=lambda x: x[1]['value'], reverse=True)[:5]
            ]

            trend_aggs = line_base.values("account_move__date", "account_type", "company__currency_code").annotate(
                total_debit=Sum("debit"),
                total_credit=Sum("credit")
            )
            
            revenue_trend_map = {}
            expense_trend_map = {}
            cash_flow_map = {}
            
            for row in trend_aggs:
                if not row["account_move__date"]: continue
                d_str = _iso(row["account_move__date"])
                company_currency = row["company__currency_code"] or "COMPANY_BASE"
                rate = _get_conversion_rate(company_currency, effective_base, rate_map)
                
                net_credit = (_to_float(row["total_credit"]) - _to_float(row["total_debit"])) * rate
                net_debit = (_to_float(row["total_debit"]) - _to_float(row["total_credit"])) * rate
                
                atype = row["account_type"] or ""
                
                if atype.startswith("income"):
                    revenue_trend_map[d_str] = revenue_trend_map.get(d_str, 0.0) + net_credit
                elif atype.startswith("expense"):
                    expense_trend_map[d_str] = expense_trend_map.get(d_str, 0.0) + net_debit
                    
                if atype in ["asset_cash", "liability_credit_card"]:
                    cash_flow_map[d_str] = cash_flow_map.get(d_str, 0.0) + net_debit # debit increases cash

            revenue_trend = [{"date": d, "value": v} for d, v in sorted(revenue_trend_map.items())]
            expense_trend = [{"date": d, "value": v} for d, v in sorted(expense_trend_map.items())]
            cash_flow_trend = [{"date": d, "value": v} for d, v in sorted(cash_flow_map.items())]

            # Consolidated single query for distributions
            dist_rows = list(qs.values("state", "payment_state", "move_type").annotate(count=Count("id")))
            state_distribution = {}
            payment_state_distribution = {}
            move_type_distribution = {}
            for r in dist_rows:
                st = r["state"] or "unknown"
                pst = r["payment_state"] or "unknown"
                mt = r["move_type"] or "unknown"
                cnt = r["count"]
                state_distribution[st] = state_distribution.get(st, 0) + cnt
                payment_state_distribution[pst] = payment_state_distribution.get(pst, 0) + cnt
                move_type_distribution[mt] = move_type_distribution.get(mt, 0) + cnt

            receivables_aging = AccountingService._aging(qs, "out_invoice", effective_base, rate_map)
            payables_aging = AccountingService._aging(qs, "in_invoice", effective_base, rate_map)

            net_profit_margin_pct = (net_profit / true_revenue * 100) if true_revenue else 0.0
            
            # Calculate total cash flow from the trend array
            total_cash_flow = sum(item["value"] for item in cash_flow_trend)
            
            # --- Deep Cash Flow Tracing (Breakdown) with Tenant Scoped Joins ---
            cash_flow_breakdown_map = AccountingService._calc_cash_flow_breakdown(
                tenant_id, start_date, end_date, company_ids, effective_base, rate_map
            )
            
            # Format breakdown for output
            cash_flow_breakdown = [
                {"category": cat, "value": val} 
                for cat, val in sorted(cash_flow_breakdown_map.items(), key=lambda x: abs(x[1]), reverse=True)
            ]
            
            applied = {
                "tenant_id": tenant_id,
                "start_date": start_date,
                "end_date": end_date,
                "company_ids": company_ids,
            }
            
            # --- Intelligent Alerts Engine ---
            alerts = []
            
            # 1. Receivables Aging Alert (>25% over 90 days)
            total_recv = sum(b.get("amount", 0.0) for b in receivables_aging)
            over_90_recv = 0.0
            for bucket in receivables_aging:
                if bucket.get("bucket") == "90+":
                    over_90_recv = bucket.get("amount", 0.0)
            if total_recv > 0 and (over_90_recv / total_recv) > 0.25:
                alerts.append({
                    "severity": "high",
                    "type": "receivables_aging",
                    "message": f"High risk: {over_90_recv / total_recv:.0%} of your unpaid receivables are older than 90 days."
                })
                
            # 2. Expense Spike Alert (>3x average daily)
            if expense_trend:
                avg_expense = sum(d["value"] for d in expense_trend) / len(expense_trend)
                if avg_expense > 0:
                    for d in expense_trend:
                        if d["value"] > avg_expense * 3 and d["value"] > 1000:
                            alerts.append({
                                "severity": "medium",
                                "type": "expense_spike",
                                "message": f"Expenses spiked sharply on {d['date']} to {d['value']:,.0f}."
                            })
                            break
                            
            # 3. Vendor Concentration Alert (>40% total expenses)
            if top_expense_vendors and true_expenses > 0:
                top_vendor = top_expense_vendors[0]
                if (top_vendor["value"] / true_expenses) > 0.40:
                    alerts.append({
                        "severity": "medium",
                        "type": "vendor_concentration",
                        "message": f"Vendor concentration: '{top_vendor['name']}' represents {top_vendor['value'] / true_expenses:.0%} of your total expenses."
                    })
                    
            # 4. Cash Flow Drop Alert (>3x negative average)
            negative_flows = [d["value"] for d in cash_flow_trend if d["value"] < 0]
            if negative_flows:
                avg_negative = sum(negative_flows) / len(negative_flows)
                for d in cash_flow_trend:
                    if d["value"] < avg_negative * 3:
                        alerts.append({
                            "severity": "medium",
                            "type": "cash_flow_drop",
                            "message": f"Significant cash flow drop observed on {d['date']} ({d['value']:,.0f})."
                        })
                        break

            return {
                "total_revenue": _metric(true_revenue),
                "total_expenses": _metric(true_expenses),
                "net_profit": _metric(net_profit),
                "net_cash_flow": _metric(total_cash_flow),
                "gross_profit": _metric(gross_profit),
                "ebit": _metric(ebit),
                "net_profit_margin_pct": net_profit_margin_pct,
                "total_assets": _metric(total_assets),
                "total_assets_value": total_assets,
                "asset_breakdown": asset_breakdown,
                "bank_balance": bank_balance,
                "opening_cash_balance": opening_cash_balance,
                "cash_in": cash_in,
                "cash_out": cash_out,
                "closing_cash_balance": opening_cash_balance + cash_in - cash_out,
                "receivable_balance": receivable_balance,
                "overdue_receivable": overdue_receivable,
                "payable_balance": payable_balance,
                "overdue_payable": overdue_payable,
                "top_revenue_customers": top_revenue_customers,
                "top_expense_vendors": top_expense_vendors,
                "revenue_trend": revenue_trend,
                "expense_trend": expense_trend,
                "cash_flow_trend": cash_flow_trend,
                "cash_flow_breakdown": cash_flow_breakdown,
                "state_distribution": state_distribution,
                "payment_state_distribution": payment_state_distribution,
                "payment_status_distribution": payment_state_distribution,
                "move_type_distribution": move_type_distribution,
                "receivables_aging": receivables_aging,
                "payables_aging": payables_aging,
                "ar_aging": receivables_aging,
                "ap_aging": payables_aging,
                "alerts": alerts,
                "applied_filters": applied,
            }

        return await asyncio.to_thread(_dashboard)

    @staticmethod
    def _calc_cash_flow_breakdown(
        tenant_id: str,
        start_date: Optional[str],
        end_date: Optional[str],
        company_ids: Optional[list[int]],
        effective_base: str,
        rate_map: dict
    ) -> dict[str, float]:
        from django.db import connection
        cash_flow_breakdown_map = {}
        with connection.cursor() as cursor:
            sql = """
                SELECT 
                    pay_line.id as cash_line_id,
                    pay_line.debit - pay_line.credit as cash_amount,
                    comp.currency_code,
                    
                    -- === Zero-Step ===
                    m1_inc_line.id as m1_inc_id,
                    m1_inc_line.account_name as m1_account_name,
                    ABS(m1_inc_line.balance) as m1_inc_balance,
                    
                    -- === One-Step ===
                    COALESCE(recon1_d.id, recon1_c.id) as recon1_id,
                    COALESCE(recon1_d.amount, recon1_c.amount) as recon1_amount,
                    COALESCE(m2_d.id, m2_c.id) as m2_line_id,
                    ABS(COALESCE(m2_d.balance, m2_c.balance)) as m2_line_balance,
                    m2_inc_line.id as m2_inc_id,
                    m2_inc_line.account_name as m2_account_name,
                    ABS(m2_inc_line.balance) as m2_inc_balance,
                    
                    -- === Two-Step ===
                    COALESCE(recon2_d.id, recon2_c.id) as recon2_id,
                    COALESCE(recon2_d.amount, recon2_c.amount) as recon2_amount,
                    COALESCE(m3_d.id, m3_c.id) as m3_line_id,
                    ABS(COALESCE(m3_d.balance, m3_c.balance)) as m3_ar_balance,
                    m3_inc_line.id as m3_inc_id,
                    m3_inc_line.account_name as m3_account_name,
                    ABS(m3_inc_line.balance) as m3_inc_balance
                    
                FROM fact_account_move_lines pay_line
                JOIN fact_account_moves pay_move ON pay_line.account_move_id = pay_move.id
                LEFT JOIN dim_companies comp ON pay_line.company_id = comp.id
                
                -- FIND COUNTERPART (Outstanding or AR/AP)
                LEFT JOIN fact_account_move_lines pay_cp_line 
                    ON pay_cp_line.account_move_id = pay_move.id 
                    AND pay_cp_line.tenant_id = pay_line.tenant_id
                    AND pay_cp_line.id != pay_line.id
                    AND pay_cp_line.account_type IN ('asset_receivable', 'liability_payable', 'asset_current', 'asset_cash')
                    
                -- ZERO-STEP (Direct Cash Expense/Income)
                LEFT JOIN fact_account_move_lines m1_inc_line
                    ON m1_inc_line.account_move_id = pay_move.id
                    AND m1_inc_line.tenant_id = pay_line.tenant_id
                    AND m1_inc_line.id != pay_line.id
                    AND m1_inc_line.account_type NOT IN ('asset_receivable', 'liability_payable', 'asset_cash')
                    
                -- JUMP 1 (Pure Index Equalities)
                LEFT JOIN fact_account_partial_reconciles recon1_d
                    ON recon1_d.tenant_id = pay_line.tenant_id
                    AND recon1_d.debit_move_line_id = pay_cp_line.id
                LEFT JOIN fact_account_move_lines m2_d
                    ON m2_d.tenant_id = pay_line.tenant_id
                    AND m2_d.id = recon1_d.credit_move_line_id
                    
                LEFT JOIN fact_account_partial_reconciles recon1_c
                    ON recon1_c.tenant_id = pay_line.tenant_id
                    AND recon1_c.credit_move_line_id = pay_cp_line.id
                LEFT JOIN fact_account_move_lines m2_c
                    ON m2_c.tenant_id = pay_line.tenant_id
                    AND m2_c.id = recon1_c.debit_move_line_id
                    
                -- One-Step target: Is Move 2 the Invoice?
                LEFT JOIN fact_account_move_lines m2_inc_line
                    ON m2_inc_line.tenant_id = pay_line.tenant_id
                    AND m2_inc_line.account_move_id = COALESCE(m2_d.account_move_id, m2_c.account_move_id)
                    AND m2_inc_line.id != COALESCE(m2_d.id, m2_c.id)
                    AND m2_inc_line.account_type NOT IN ('asset_receivable', 'liability_payable', 'asset_cash')

                -- JUMP 2 (Pure Index Equalities)
                LEFT JOIN fact_account_move_lines m2_ar_line
                    ON m2_ar_line.tenant_id = pay_line.tenant_id
                    AND m2_ar_line.account_move_id = COALESCE(m2_d.account_move_id, m2_c.account_move_id)
                    AND m2_ar_line.id != COALESCE(m2_d.id, m2_c.id)
                    AND m2_ar_line.account_type IN ('asset_receivable', 'liability_payable')
                    
                LEFT JOIN fact_account_partial_reconciles recon2_d
                    ON recon2_d.tenant_id = pay_line.tenant_id
                    AND recon2_d.debit_move_line_id = m2_ar_line.id
                LEFT JOIN fact_account_move_lines m3_d
                    ON m3_d.tenant_id = pay_line.tenant_id
                    AND m3_d.id = recon2_d.credit_move_line_id
                    
                LEFT JOIN fact_account_partial_reconciles recon2_c
                    ON recon2_c.tenant_id = pay_line.tenant_id
                    AND recon2_c.credit_move_line_id = m2_ar_line.id
                LEFT JOIN fact_account_move_lines m3_c
                    ON m3_c.tenant_id = pay_line.tenant_id
                    AND m3_c.id = recon2_c.debit_move_line_id
                    
                -- Two-Step target: Income on Move 3
                LEFT JOIN fact_account_move_lines m3_inc_line
                    ON m3_inc_line.tenant_id = pay_line.tenant_id
                    AND m3_inc_line.account_move_id = COALESCE(m3_d.account_move_id, m3_c.account_move_id)
                    AND m3_inc_line.id != COALESCE(m3_d.id, m3_c.id)
                    AND m3_inc_line.account_type NOT IN ('asset_receivable', 'liability_payable', 'asset_cash')
                    
                WHERE pay_line.tenant_id = %s
                  AND pay_line.account_type = 'asset_cash'
                  AND pay_move.state = 'posted'
            """
            params = [tenant_id]
            
            if start_date:
                sql += " AND pay_move.date >= %s"
                params.append(start_date)
            if end_date:
                sql += " AND pay_move.date <= %s"
                params.append(end_date)
            if company_ids:
                placeholders = ','.join(['%s'] * len(company_ids))
                sql += f" AND pay_line.company_id IN ({placeholders})"
                params.extend(company_ids)
                
            cursor.execute(sql, params)
            columns = [col[0] for col in cursor.description]
            
            # Track by cash line to handle un-reconciled remainders
            cash_lines = {}
            
            for row in cursor.fetchall():
                d = dict(zip(columns, row))
                c_id = d['cash_line_id']
                if c_id not in cash_lines:
                    cash_lines[c_id] = {
                        'amount': _to_float(d['cash_amount']),
                        'currency': d['currency_code'] or 'COMPANY_BASE',
                        'm1_inc_lines': {},
                        'recon1s': {}
                    }
                    
                c_info = cash_lines[c_id]
                
                if d['m1_inc_id']:
                    c_info['m1_inc_lines'][d['m1_inc_id']] = {
                        'cat': d['m1_account_name'],
                        'balance': _to_float(d['m1_inc_balance'] or 0)
                    }
                    
                if d['recon1_id']:
                    r1_id = d['recon1_id']
                    if r1_id not in c_info['recon1s']:
                        c_info['recon1s'][r1_id] = {
                            'amount': _to_float(d['recon1_amount'] or 0),
                            'm2_line_balance': _to_float(d['m2_line_balance'] or 0),
                            'm2_inc_lines': {},
                            'recon2s': {}
                        }
                    r1_info = c_info['recon1s'][r1_id]
                    
                    if d['m2_inc_id']:
                        r1_info['m2_inc_lines'][d['m2_inc_id']] = {
                            'cat': d['m2_account_name'],
                            'balance': _to_float(d['m2_inc_balance'] or 0)
                        }
                        
                    if d['recon2_id']:
                        r2_id = d['recon2_id']
                        if r2_id not in r1_info['recon2s']:
                            r1_info['recon2s'][r2_id] = {
                                'amount': _to_float(d['recon2_amount'] or 0),
                                'm3_ar_balance': _to_float(d['m3_ar_balance'] or 0),
                                'm3_inc_lines': {}
                            }
                        r2_info = r1_info['recon2s'][r2_id]
                        
                        if d['m3_inc_id']:
                            r2_info['m3_inc_lines'][d['m3_inc_id']] = {
                                'cat': d['m3_account_name'],
                                'balance': _to_float(d['m3_inc_balance'] or 0)
                            }

            # Process allocations
            for c_id, info in cash_lines.items():
                total_abs = abs(info['amount'])
                sign = 1 if info['amount'] > 0 else -1
                explained_abs = 0.0
                rate = _get_conversion_rate(info['currency'], effective_base, rate_map)
                
                for r1_id, r1_info in info['recon1s'].items():
                    r1_amt = r1_info['amount']
                    if r1_amt == 0: continue
                    
                    explained_abs += r1_amt
                    
                    if r1_info['m2_inc_lines']:
                        m2_ar_bal = r1_info['m2_line_balance']
                        if m2_ar_bal > 0:
                            for m2_inc_id, m2_inc in r1_info['m2_inc_lines'].items():
                                ratio = m2_inc['balance'] / m2_ar_bal
                                allocated = r1_amt * ratio * sign
                                cat = m2_inc['cat'] or 'Unknown'
                                cash_flow_breakdown_map[cat] = cash_flow_breakdown_map.get(cat, 0.0) + (allocated * rate)
                                
                    elif r1_info['recon2s']:
                        m2_line_bal = r1_info['m2_line_balance']
                        if m2_line_bal > 0:
                            funding_ratio = r1_amt / m2_line_bal
                            
                            for r2_id, r2_info in r1_info['recon2s'].items():
                                invoice_funded = r2_info['amount'] * funding_ratio
                                m3_ar_bal = r2_info['m3_ar_balance']
                                if m3_ar_bal > 0:
                                    for m3_inc_id, m3_inc in r2_info['m3_inc_lines'].items():
                                        inc_ratio = m3_inc['balance'] / m3_ar_bal
                                        allocated = invoice_funded * inc_ratio * sign
                                        cat = m3_inc['cat'] or 'Unknown'
                                        cash_flow_breakdown_map[cat] = cash_flow_breakdown_map.get(cat, 0.0) + (allocated * rate)
                    else:
                        cat = 'Unreconciled Cash Entry'
                        cash_flow_breakdown_map[cat] = cash_flow_breakdown_map.get(cat, 0.0) + (r1_amt * sign * rate)

                unreconciled_abs = total_abs - explained_abs
                if unreconciled_abs > 0.01:
                    if info['m1_inc_lines']:
                        total_m1_bal = sum(m1['balance'] for m1 in info['m1_inc_lines'].values())
                        if total_m1_bal > 0:
                            for m1_inc_id, m1_inc in info['m1_inc_lines'].items():
                                ratio = m1_inc['balance'] / total_m1_bal
                                allocated = unreconciled_abs * ratio * sign
                                cat = m1_inc['cat'] or 'Unknown'
                                cash_flow_breakdown_map[cat] = cash_flow_breakdown_map.get(cat, 0.0) + (allocated * rate)
                        else:
                            cat = 'Unreconciled Cash Entry'
                            cash_flow_breakdown_map[cat] = cash_flow_breakdown_map.get(cat, 0.0) + (unreconciled_abs * sign * rate)
                    else:
                        cat = 'Unreconciled Cash Entry'
                        cash_flow_breakdown_map[cat] = cash_flow_breakdown_map.get(cat, 0.0) + (unreconciled_abs * sign * rate)

        return cash_flow_breakdown_map

    @staticmethod
    async def get_bank_cash_summary(
        tenant_id: str,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        company_ids: Optional[list[int]] = None,
        base_currency: Optional[str] = None,
    ) -> dict[str, Any]:
        """Dedicated high-performance calculation for bank & cash summary endpoint."""
        def _summary():
            rate_map = _get_rate_map()
            effective_base = base_currency or "XAF"
            
            line_base = AccountMoveLine.objects.filter(
                tenant_id=tenant_id,
                account_move__state='posted'
            )
            if company_ids:
                line_base = line_base.filter(company_id__in=company_ids)
            if start_date:
                line_base = line_base.filter(account_move__date__gte=start_date)
            if end_date:
                line_base = line_base.filter(account_move__date__lte=end_date)

            cum_lines = AccountMoveLine.objects.filter(
                tenant_id=tenant_id,
                account_move__state='posted',
                account_type="asset_cash"
            )
            if company_ids:
                cum_lines = cum_lines.filter(company_id__in=company_ids)
            if end_date:
                cum_lines = cum_lines.filter(account_move__date__lte=end_date)

            cumulative_aggs = cum_lines.values("company__currency_code").annotate(
                total_debit=Sum("debit"),
                total_credit=Sum("credit")
            )
            bank_balance = 0.0
            for agg in cumulative_aggs:
                comp_curr = agg["company__currency_code"] or "COMPANY_BASE"
                rate = _get_conversion_rate(comp_curr, effective_base, rate_map)
                bank_balance += (_to_float(agg["total_debit"]) - _to_float(agg["total_credit"])) * rate

            opening_cash_balance = 0.0
            cash_in = 0.0
            cash_out = 0.0
            
            if start_date:
                open_lines = AccountMoveLine.objects.filter(
                    tenant_id=tenant_id,
                    account_move__state='posted',
                    account_move__date__lt=start_date,
                    account_type="asset_cash"
                )
                if company_ids:
                    open_lines = open_lines.filter(company_id__in=company_ids)

                for agg in open_lines.values("company__currency_code").annotate(net_cash=Sum("debit") - Sum("credit")):
                    comp_curr = agg["company__currency_code"] or "COMPANY_BASE"
                    rate = _get_conversion_rate(comp_curr, effective_base, rate_map)
                    opening_cash_balance += _to_float(agg["net_cash"]) * rate

            period_lines = line_base.filter(account_type="asset_cash")
            for agg in period_lines.values("company__currency_code").annotate(total_debit=Sum("debit"), total_credit=Sum("credit")):
                comp_curr = agg["company__currency_code"] or "COMPANY_BASE"
                rate = _get_conversion_rate(comp_curr, effective_base, rate_map)
                cash_in += _to_float(agg["total_debit"]) * rate
                cash_out += _to_float(agg["total_credit"]) * rate

            cash_flow_breakdown_map = AccountingService._calc_cash_flow_breakdown(
                tenant_id, start_date, end_date, company_ids, effective_base, rate_map
            )
            cash_flow_breakdown = [
                {"category": cat, "value": val} 
                for cat, val in sorted(cash_flow_breakdown_map.items(), key=lambda x: abs(x[1]), reverse=True)
            ]

            return {
                "opening_cash_balance": opening_cash_balance,
                "cash_in": cash_in,
                "cash_out": cash_out,
                "closing_cash_balance": opening_cash_balance + cash_in - cash_out,
                "bank_balance": bank_balance,
                "cash_flow_breakdown": cash_flow_breakdown,
            }

        return await asyncio.to_thread(_summary)

    @staticmethod
    def _calc_pnl_sync(
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        company_ids: Optional[list[int]] = None,
        base_currency: Optional[str] = None,
        tenant_ids: Optional[list[str]] = None,
    ) -> dict[str, Any]:
        qs = AccountingService._date_qs(
            AccountingService._base_qs(tenant_ids=tenant_ids, company_ids=company_ids),
            start_date,
            end_date
        ).filter(state='posted')

        tag4_ids = AccountingService._get_tag4_account_ids(tenant_ids)
        lines_aggs = AccountMoveLine.objects.filter(
            account_move__in=qs
        ).values("company_id", "account_odoo_id", "account_type", "account_code", "account_name", "company__currency_code").annotate(
            net_debit=Sum("debit"),
            net_credit=Sum("credit")
        )

        effective_base = base_currency or "XAF"
        rate_map = _get_rate_map()

        revenue = 0.0
        other_income = 0.0
        cogs = 0.0
        depreciation = 0.0
        general_expenses = 0.0
        taxes_interest = 0.0

        for agg in lines_aggs:
            cid = agg.get("company_id")
            a_odoo_id = agg.get("account_odoo_id")
            atype = agg.get("account_type") or ""
            acode = agg.get("account_code") or ""
            aname = agg.get("account_name") or ""
            company_curr = agg.get("company__currency_code") or "XAF"
            
            rate = _get_conversion_rate(company_curr, effective_base, rate_map)
            
            net_debit = (_to_float(agg.get("net_debit")) - _to_float(agg.get("net_credit"))) * rate
            net_credit = (_to_float(agg.get("net_credit")) - _to_float(agg.get("net_debit"))) * rate

            if atype == "income":
                revenue += net_credit
            elif atype == "income_other":
                other_income += net_credit
            elif atype == "expense_direct_cost":
                cogs += net_debit
            elif atype == "expense_depreciation":
                depreciation += net_debit
            elif atype == "expense":
                if not AccountingService._is_tag4_purchase_expense(tenant_ids=tenant_ids, account_odoo_id=a_odoo_id, company_ids=[cid] if cid else None, acode=acode, aname=aname, tag4_ids=tag4_ids):
                    general_expenses += net_debit
                    if acode.startswith("67") or acode.startswith("69"):
                        taxes_interest += net_debit

        gross_profit = revenue - cogs
        total_expenses = general_expenses + depreciation
        ebit = gross_profit - general_expenses
        ebitda = ebit + depreciation
        net_profit = gross_profit + other_income - total_expenses

        return {
            "revenue": revenue,
            "other_income": other_income,
            "cogs": cogs,
            "gross_profit": gross_profit,
            "expenses": general_expenses,
            "depreciation": depreciation,
            "other_expenses": depreciation,
            "total_expenses": total_expenses,
            "operating_expenses": general_expenses,
            "ebitda": ebitda,
            "ebit": ebit,
            "taxes_and_interest": taxes_interest,
            "net_profit": net_profit,
        }

    @staticmethod
    def _calc_executive_summary_sync(
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        company_ids: Optional[list[int]] = None,
        base_currency: Optional[str] = None,
        tenant_ids: Optional[list[str]] = None,
    ) -> dict[str, Any]:
        """
        Calculates the complete 5-pillar Executive Summary exactly matching Odoo Report ID 6:
        - Cash: Cash received, Cash spent, Cash surplus, Closing bank balance
        - Profitability: Revenue, Cost of Revenue, Gross profit, Expenses (OpEx), Net Profit
        - Balance Sheet: Receivables, Payables, Net assets
        - Performance: Gross profit margin %, Net profit margin %, Return on investments %
        - Position: Average debtors days, Average creditors days, Short term cash forecast, Current assets to liabilities
        """
        import datetime
        effective_base = base_currency or "XAF"
        rate_map = _get_rate_map()
        tag4_ids = AccountingService._get_tag4_account_ids(tenant_ids)
        
        # 1. Period-scoped move lines (P&L & Cash flow)
        p_qs = AccountingService._date_qs(
            AccountingService._base_qs(tenant_ids=tenant_ids, company_ids=company_ids),
            start_date,
            end_date
        ).filter(state='posted')
        
        period_aggs = AccountMoveLine.objects.filter(
            account_move__in=p_qs
        ).values("company_id", "account_odoo_id", "account_type", "account_code", "account_name", "company__currency_code").annotate(
            net_debit=Sum("debit"),
            net_credit=Sum("credit")
        )
        
        revenue = 0.0
        other_income = 0.0
        cogs = 0.0
        depreciation = 0.0
        opex = 0.0
        cash_received = 0.0
        cash_spent = 0.0
        
        for agg in period_aggs:
            cid = agg.get("company_id")
            a_odoo_id = agg.get("account_odoo_id")
            atype = agg.get("account_type") or ""
            acode = agg.get("account_code") or ""
            aname = agg.get("account_name") or ""
            company_curr = agg.get("company__currency_code") or "XAF"
            rate = _get_conversion_rate(company_curr, effective_base, rate_map)
            
            deb = _to_float(agg.get("net_debit")) * rate
            crd = _to_float(agg.get("net_credit")) * rate
            net_d = deb - crd
            net_c = crd - deb
            
            if atype == "income":
                revenue += net_c
            elif atype == "income_other":
                other_income += net_c
            elif atype == "expense_direct_cost":
                cogs += net_d
            elif atype == "expense_depreciation":
                depreciation += net_d
            elif atype == "expense":
                if not AccountingService._is_tag4_purchase_expense(tenant_ids=tenant_ids, account_odoo_id=a_odoo_id, company_ids=[cid] if cid else None, acode=acode, aname=aname, tag4_ids=tag4_ids):
                    opex += net_d
            elif atype in ("asset_cash", "liability_credit_card"):
                cash_received += deb
                cash_spent -= crd
                
        gross_profit = revenue - cogs
        total_expenses = opex + depreciation
        net_profit = gross_profit + other_income - total_expenses
        cash_surplus = cash_received + cash_spent
        
        # 2. Cumulative Balance Sheet up to end_date
        cum_qs = AccountingService._base_qs(tenant_ids=tenant_ids, company_ids=company_ids)
        if end_date:
            cum_qs = cum_qs.filter(date__lte=end_date)
        cum_qs = cum_qs.filter(state='posted')
        
        cum_aggs = AccountMoveLine.objects.filter(
            account_move__in=cum_qs
        ).values("company_id", "account_type", "company__currency_code").annotate(
            bal=Sum("debit") - Sum("credit")
        )
        
        receivables = 0.0
        payables = 0.0
        closing_bank_balance = 0.0
        current_assets = 0.0
        current_liabilities = 0.0
        total_assets = 0.0
        total_liabilities = 0.0
        
        for agg in cum_aggs:
            atype = agg.get("account_type") or ""
            company_curr = agg.get("company__currency_code") or "XAF"
            rate = _get_conversion_rate(company_curr, effective_base, rate_map)
            bal = _to_float(agg.get("bal")) * rate
            
            if atype == "asset_receivable":
                receivables += bal
                current_assets += bal
                total_assets += bal
            elif atype == "liability_payable":
                payables += bal
                current_liabilities += (-bal)
                total_liabilities += (-bal)
            elif atype in ("asset_cash", "liability_credit_card"):
                closing_bank_balance += bal
                if atype == "asset_cash":
                    current_assets += bal
                    total_assets += bal
                else:
                    current_liabilities += (-bal)
                    total_liabilities += (-bal)
            elif atype in ("asset_current", "asset_prepayments"):
                current_assets += bal
                total_assets += bal
            elif atype in ("asset_fixed", "asset_non_current"):
                total_assets += bal
            elif atype in ("liability_current",):
                current_liabilities += (-bal)
                total_liabilities += (-bal)
            elif atype in ("liability_non_current",):
                total_liabilities += (-bal)
                
        net_assets = total_assets - total_liabilities
        
        # 3. Performance & Position Ratios
        gp_margin = (gross_profit / revenue * 100) if revenue else 0.0
        np_margin = (net_profit / revenue * 100) if revenue else 0.0
        roi = (net_profit / total_assets * 100) if total_assets else 0.0
        
        # Date duration in days (NDays)
        ndays = 30.0
        if start_date and end_date:
            try:
                d_start = datetime.date.fromisoformat(str(start_date)[:10])
                d_end = datetime.date.fromisoformat(str(end_date)[:10])
                ndays = max((d_end - d_start).days + 1, 1)
            except Exception:
                pass
                
        dso = (receivables / revenue * ndays) if revenue else 0.0
        dpo = (-payables / (cogs + opex) * ndays) if (cogs + opex) else 0.0
        short_term_cash_forecast = receivables + payables
        current_ratio = (current_assets / current_liabilities) if current_liabilities else 0.0
        
        return {
            "cash": {
                "cash_received": cash_received,
                "cash_spent": cash_spent,
                "cash_surplus": cash_surplus,
                "closing_bank_balance": closing_bank_balance,
            },
            "profitability": {
                "revenue": revenue,
                "cost_of_revenue": cogs,
                "gross_profit": gross_profit,
                "expenses": opex,
                "other_income": other_income,
                "other_expenses": depreciation,
                "net_profit": net_profit,
            },
            "balance_sheet": {
                "receivables": receivables,
                "payables": payables,
                "net_assets": net_assets,
            },
            "performance": {
                "gross_profit_margin_pct": round(gp_margin, 2),
                "net_profit_margin_pct": round(np_margin, 2),
                "return_on_investments_pct": round(roi, 2),
            },
            "position": {
                "average_debtors_days": round(dso, 1),
                "average_creditors_days": round(dpo, 1),
                "short_term_cash_forecast": short_term_cash_forecast,
                "current_assets_to_liabilities": round(current_ratio, 2),
            }
        }

    @staticmethod
    async def get_executive_summary(
        tenant_ids: Optional[list[str]] = None,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        company_ids: Optional[list[int]] = None,
        base_currency: Optional[str] = None,
    ) -> dict[str, Any]:
        """Calculates the complete 5-pillar Executive Summary matching Odoo Report 6."""
        return await asyncio.to_thread(
            AccountingService._calc_executive_summary_sync,
            start_date=start_date,
            end_date=end_date,
            company_ids=company_ids,
            base_currency=base_currency,
            tenant_ids=tenant_ids,
        )

    @staticmethod
    async def get_pnl_summary(
        tenant_ids: Optional[list[str]] = None,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        company_ids: Optional[list[int]] = None,
        base_currency: Optional[str] = None,
    ) -> dict[str, Any]:
        """Calculates a proper P&L breakdown by analyzing AccountMoveLines."""
        return await asyncio.to_thread(
            AccountingService._calc_pnl_sync,
            start_date=start_date,
            end_date=end_date,
            company_ids=company_ids,
            base_currency=base_currency,
            tenant_ids=tenant_ids,
        )

    @staticmethod
    async def get_balance_sheet(
        tenant_id: str,
        as_of_date: Optional[str] = None,
        company_ids: Optional[list[int]] = None,
        base_currency: Optional[str] = None,
    ) -> dict[str, Any]:
        """Retrieve a structured Balance Sheet matching Odoo."""
        from doova_one_view.api.agent.tools_refactored.finance import get_balance_sheet_tool
        return await asyncio.to_thread(
            get_balance_sheet_tool,
            tenant_id=tenant_id,
            company_ids=company_ids,
            as_of_date=as_of_date,
            base_currency=base_currency
        )

    @staticmethod
    def _calc_cash_flow_sync(
        tenant_ids: Optional[list[str]] = None,
        company_ids: Optional[list[int]] = None,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        base_currency: Optional[str] = None,
        source: str = "auto",
    ) -> dict[str, Any]:
        """Calculates a proper Cash Flow Statement matching Odoo via CashFlowEngine."""
        from .cash_flow_engine import CashFlowEngine
        from doova_one_view.api.agent.query_context import normalize_tenant_ids, normalize_company_ids
        t_ids = normalize_tenant_ids(tenant_ids)
        c_ids = normalize_company_ids(company_ids)
        primary_t = t_ids[0] if t_ids else None
        return CashFlowEngine.compute(
            tenant_id=primary_t,
            start_date=start_date,
            end_date=end_date,
            company_ids=c_ids,
            base_currency=base_currency,
            tenant_ids=t_ids,
            source=source,
        )

    @staticmethod
    async def get_cash_flow_statement(
        tenant_ids: Optional[list[str]] = None,
        company_ids: Optional[list[int]] = None,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        base_currency: Optional[str] = None,
        source: str = "auto",
    ) -> dict[str, Any]:
        """Calculates a structured Cash Flow Statement matching Odoo."""
        return await asyncio.to_thread(
            AccountingService._calc_cash_flow_sync,
            tenant_ids=tenant_ids,
            company_ids=company_ids,
            start_date=start_date,
            end_date=end_date,
            base_currency=base_currency,
            source=source,
        )

    @staticmethod
    def _get_cash_flow_drilldown_sync(
        tenant_id: str,
        section: str,
        line_key: Optional[str] = None,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        company_ids: Optional[list[int]] = None,
        limit: int = 200,
    ) -> list[dict[str, Any]]:
        """Retrieves itemized journal moves for a specific Cash Flow section."""
        from .cash_flow_engine import CashFlowEngine
        return CashFlowEngine.get_drilldown_lines(
            tenant_id=tenant_id,
            section=section,
            line_key=line_key,
            start_date=start_date,
            end_date=end_date,
            company_ids=company_ids,
            limit=limit,
        )

    @staticmethod
    async def get_cash_flow_drilldown(
        tenant_id: str,
        section: str,
        line_key: Optional[str] = None,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        company_ids: Optional[list[int]] = None,
        limit: int = 200,
    ) -> list[dict[str, Any]]:
        """Retrieves itemized journal moves for a specific Cash Flow section asynchronously."""
        return await asyncio.to_thread(
            AccountingService._get_cash_flow_drilldown_sync,
            tenant_id,
            section,
            line_key,
            start_date,
            end_date,
            company_ids,
            limit,
        )

    # ── Expense category keyword mapping ──────────────────────────────────
    _EXPENSE_CATEGORIES = [
        ("Rent",       ["rent"]),
        ("Salaries",   ["salar", "wage", "staff charge", "worker", "personnel",
                        "income tax on salar"]),
        ("Purchases",  ["purchase", "cost of goods purchased", "customs",
                        "freight", "containers", "packing"]),
        ("Marketing",  ["marketing", "commission"]),
        ("Logistics",  ["transport", "travel", "car expense", "fuel", "logistics"]),
        ("Utilities",  ["electric", "internet", "telephone", "mobile",
                        "water", "satellite"]),
    ]

    @staticmethod
    def _classify_expense(account_name: str, account_code: str) -> str:
        """Return the expense category for a given account name/code."""
        name_lower = (account_name or "").lower()
        for category, keywords in AccountingService._EXPENSE_CATEGORIES:
            if any(kw in name_lower for kw in keywords):
                return category
        return "Other Expenses"

    @staticmethod
    async def get_expense_breakdown(
        tenant_id: str,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        company_ids: Optional[list[int]] = None,
        base_currency: Optional[str] = None,
    ) -> dict[str, Any]:
        """Expense breakdown by category (Rent, Salaries, Purchases, etc.)."""
        def _breakdown():
            qs = AccountingService._date_qs(
                AccountingService._base_qs(tenant_id, company_ids), start_date, end_date
            ).filter(state='posted')

            tag4_ids = AccountingService._get_tag4_account_ids(tenant_id)
            lines_aggs = AccountMoveLine.objects.filter(
                account_move__in=qs,
                account_type='expense',
            ).values(
                "company_id", "account_odoo_id", "account_code", "account_name", "company__currency_code"
            ).annotate(
                total_debit=Sum("debit"),
                total_credit=Sum("credit"),
            )

            effective_base = base_currency or "XAF"
            rate_map = _get_rate_map()

            category_totals: dict[str, float] = {}

            for agg in lines_aggs:
                cid = agg.get("company_id")
                a_odoo_id = agg.get("account_odoo_id")
                acode = agg.get("account_code") or ""
                aname = agg.get("account_name") or ""
                company_curr = agg.get("company__currency_code") or "XAF"

                if AccountingService._is_tag4_purchase_expense(tenant_ids=[tenant_id] if tenant_id else None, account_odoo_id=a_odoo_id, company_ids=[cid] if cid else None, acode=acode, aname=aname, tag4_ids=tag4_ids):
                    continue

                rate = _get_conversion_rate(company_curr, effective_base, rate_map)
                balance = (_to_float(agg["total_debit"]) - _to_float(agg["total_credit"])) * rate

                cat = AccountingService._classify_expense(aname, acode)
                category_totals[cat] = category_totals.get(cat, 0.0) + balance

            total = sum(category_totals.values())

            categories = []
            for cat in ["Rent", "Salaries", "Purchases", "Marketing",
                         "Logistics", "Utilities", "Other Expenses"]:
                amount = category_totals.get(cat, 0.0)
                pct = (amount / total * 100) if total else 0.0
                categories.append({
                    "category": cat,
                    "amount": amount,
                    "percentage": round(pct, 2),
                })

            return {
                "total_expenses": total,
                "categories": categories,
            }

        return await asyncio.to_thread(_breakdown)


    @staticmethod
    async def get_period_transactions(
        tenant_id: str,
        move_types: list[str],
        period: str,
        date_str: Optional[str] = None,
    ) -> dict[str, Any]:
        def _fetch():
            target_date = date.today()
            if date_str:
                try:
                    target_date = date.fromisoformat(date_str)
                except ValueError:
                    pass

            qs = AccountingService._base_qs(tenant_id).filter(
                move_type__in=move_types,
                state="posted"
            )

            if period == "today":
                qs = qs.filter(date=target_date)
            elif period == "monthly":
                qs = qs.filter(date__year=target_date.year, date__month=target_date.month)
            elif period == "yearly":
                qs = qs.filter(date__year=target_date.year)

            # Prefetch partner/company/lines for performance
            moves = list(
                qs.select_related("partner", "company")
                .prefetch_related(
                    Prefetch(
                        "lines",
                        queryset=AccountMoveLine.objects.select_related("product", "partner")
                    )
                )
                .order_by("-date", "-id")
            )

            items = []
            for m in moves:
                categories = list(dict.fromkeys(
                    line.account_name for line in m.lines.all() if line.account_name
                ))

                if not categories:
                    categories = list(dict.fromkeys(
                        line.product.name for line in m.lines.all() if line.product and line.product.name
                    ))

                items.append({
                    "id": m.id,
                    "odoo_id": m.odoo_id,
                    "name": m.odoo_name or "",
                    "amount": _to_float(m.amount_total),
                    "source": m.partner.name if m.partner else ("Unknown Customer" if m.move_type == "out_invoice" else "Unknown Vendor"),
                    "categories": categories,
                    "category_summary": ", ".join(categories) if categories else "Uncategorized",
                    "date": _iso(m.date),
                    "time": _iso(m.synced_at),  # sync timestamp
                    "move_type": m.move_type,
                    "lines": [_line_to_item(line) for line in m.lines.all()]
                })

            return items, target_date

        items, target_date = await asyncio.to_thread(_fetch)

        # Calculate subtotals
        revenues = [item for item in items if item["move_type"] == "out_invoice"]
        expenses = [item for item in items if item["move_type"] == "in_invoice"]

        total_revenue = sum(r["amount"] for r in revenues)
        total_expenses = sum(e["amount"] for e in expenses)

        return {
            "date": target_date.isoformat(),
            "items": items,
            "revenues": revenues,
            "expenses": expenses,
            "total_count": len(items),
            "revenue_count": len(revenues),
            "expense_count": len(expenses),
            "revenue_amount": total_revenue,
            "expense_amount": total_expenses,
            "net_profit": total_revenue - total_expenses,
        }

    @staticmethod
    async def get_today_expenses(
        tenant_id: str,
        date_str: Optional[str] = None,
    ) -> dict[str, Any]:
        res = await AccountingService.get_period_transactions(
            tenant_id, ["in_invoice"], "today", date_str
        )
        return {
            "date": res["date"],
            "items": res["items"],
            "total_count": res["total_count"],
            "total_amount": res["expense_amount"],
        }

    @staticmethod
    def _aging(qs, move_type: str, effective_base: str = "XAF", rate_map: dict = None) -> list[dict[str, Any]]:
        if rate_map is None:
            rate_map = {}
        today = date.today()
        
        # Check if partial reconciles exist for this tenant
        from odoo_app.models import AccountPartialReconcile
        tenant_ids = list(qs.values_list("tenant_id", flat=True).distinct())
        company_ids = list(qs.values_list("company_id", flat=True).distinct())
        
        account_type = "asset_receivable" if move_type == "out_invoice" else "liability_payable"
        
        if tenant_ids and AccountPartialReconcile.objects.filter(tenant_id__in=tenant_ids).exists():
            from django.db import connection
            is_recv = (account_type == "asset_receivable")
            tenant_filter = "AND l.tenant_id IN %s"
            tenant_params = [tuple(str(t) for t in tenant_ids)]
            company_filter = "AND l.company_id IN %s" if company_ids and None not in company_ids else ""
            company_params = [tuple(int(c) for c in company_ids if c is not None)] if company_filter else []
            
            sql = f"""
                WITH line_recon AS (
                    SELECT
                        l.id AS line_id,
                        l.company_id,
                        l.account_move_id,
                        m.date AS move_date,
                        l.debit,
                        l.credit,
                        COALESCE(SUM(pr_deb.amount), 0) AS reconciled_debit,
                        COALESCE(SUM(pr_cred.amount), 0) AS reconciled_credit
                    FROM fact_account_move_lines l
                    JOIN fact_account_moves m ON l.account_move_id = m.id
                    LEFT JOIN fact_account_partial_reconciles pr_deb 
                        ON pr_deb.debit_move_line_id = l.id AND pr_deb.max_date <= %s
                    LEFT JOIN fact_account_partial_reconciles pr_cred 
                        ON pr_cred.credit_move_line_id = l.id AND pr_cred.max_date <= %s
                    WHERE m.state = 'posted'
                      AND l.account_type = %s
                      AND m.date <= %s
                      {tenant_filter}
                      {company_filter}
                    GROUP BY l.id, l.company_id, l.account_move_id, m.date, l.debit, l.credit
                ),
                line_residual AS (
                    SELECT
                        line_id,
                        move_date,
                        (DATE %s - move_date) AS days,
                        CASE 
                            WHEN {'debit > 0 THEN debit - reconciled_debit ELSE -(credit - reconciled_credit)' if is_recv else 'credit > 0 THEN credit - reconciled_credit ELSE -(debit - reconciled_debit)'}
                        END AS residual
                    FROM line_recon
                )
                SELECT
                    COALESCE(SUM(CASE WHEN days <= 0 THEN residual ELSE 0 END), 0) AS at_date,
                    COALESCE(COUNT(CASE WHEN days <= 0 AND ABS(residual) > 0.01 THEN 1 END), 0) AS at_date_cnt,
                    COALESCE(SUM(CASE WHEN days BETWEEN 1 AND 30 THEN residual ELSE 0 END), 0) AS b_1_30,
                    COALESCE(COUNT(CASE WHEN days BETWEEN 1 AND 30 AND ABS(residual) > 0.01 THEN 1 END), 0) AS b_1_30_cnt,
                    COALESCE(SUM(CASE WHEN days BETWEEN 31 AND 60 THEN residual ELSE 0 END), 0) AS b_31_60,
                    COALESCE(COUNT(CASE WHEN days BETWEEN 31 AND 60 AND ABS(residual) > 0.01 THEN 1 END), 0) AS b_31_60_cnt,
                    COALESCE(SUM(CASE WHEN days BETWEEN 61 AND 90 THEN residual ELSE 0 END), 0) AS b_61_90,
                    COALESCE(COUNT(CASE WHEN days BETWEEN 61 AND 90 AND ABS(residual) > 0.01 THEN 1 END), 0) AS b_61_90_cnt,
                    COALESCE(SUM(CASE WHEN days BETWEEN 91 AND 120 THEN residual ELSE 0 END), 0) AS b_91_120,
                    COALESCE(COUNT(CASE WHEN days BETWEEN 91 AND 120 AND ABS(residual) > 0.01 THEN 1 END), 0) AS b_91_120_cnt,
                    COALESCE(SUM(CASE WHEN days >= 121 THEN residual ELSE 0 END), 0) AS b_older,
                    COALESCE(COUNT(CASE WHEN days >= 121 AND ABS(residual) > 0.01 THEN 1 END), 0) AS b_older_cnt,
                    COALESCE(SUM(residual), 0) AS total
                FROM line_residual
            """
            params = [today, today, account_type, today] + tenant_params + company_params + [today]
            with connection.cursor() as cursor:
                cursor.execute(sql, params)
                r = cursor.fetchone()
                at_d = float(r[0] or 0)
                at_d_cnt = int(r[1] or 0)
                b1 = float(r[2] or 0)
                b1_cnt = int(r[3] or 0)
                b2 = float(r[4] or 0)
                b2_cnt = int(r[5] or 0)
                b3 = float(r[6] or 0)
                b3_cnt = int(r[7] or 0)
                b4 = float(r[8] or 0)
                b4_cnt = int(r[9] or 0)
                b5 = float(r[10] or 0)
                b5_cnt = int(r[11] or 0)
                
                return [
                    {"bucket": "0-30", "amount": at_d + b1, "count": at_d_cnt + b1_cnt},
                    {"bucket": "31-60", "amount": b2, "count": b2_cnt},
                    {"bucket": "61-90", "amount": b3, "count": b3_cnt},
                    {"bucket": "91-120", "amount": b4, "count": b4_cnt},
                    {"bucket": "Older", "amount": b5, "count": b5_cnt},
                ]

        d30 = today - timedelta(days=30)
        d60 = today - timedelta(days=60)
        d90 = today - timedelta(days=90)
        
        base = qs.filter(
            move_type=move_type,
            invoice_date_due__isnull=False,
            amount_residual__gt=0,
        ).exclude(payment_state__in=["paid", "reversed"])

        rows = list(
            base.values("currency_code")
            .annotate(
                cnt_0_30=Count(Case(When(invoice_date_due__gte=d30, invoice_date_due__lte=today, then=1))),
                amt_0_30=Sum(Case(When(invoice_date_due__gte=d30, invoice_date_due__lte=today, then="amount_residual"), default=0, output_field=DecimalField())),
                cnt_31_60=Count(Case(When(invoice_date_due__gte=d60, invoice_date_due__lt=d30, then=1))),
                amt_31_60=Sum(Case(When(invoice_date_due__gte=d60, invoice_date_due__lt=d30, then="amount_residual"), default=0, output_field=DecimalField())),
                cnt_61_90=Count(Case(When(invoice_date_due__gte=d90, invoice_date_due__lt=d60, then=1))),
                amt_61_90=Sum(Case(When(invoice_date_due__gte=d90, invoice_date_due__lt=d60, then="amount_residual"), default=0, output_field=DecimalField())),
                cnt_90_plus=Count(Case(When(invoice_date_due__lt=d90, then=1))),
                amt_90_plus=Sum(Case(When(invoice_date_due__lt=d90, then="amount_residual"), default=0, output_field=DecimalField())),
            )
        )

        buckets = {
            "0-30": {"amount": 0.0, "count": 0},
            "31-60": {"amount": 0.0, "count": 0},
            "61-90": {"amount": 0.0, "count": 0},
            "90+": {"amount": 0.0, "count": 0},
        }

        for r in rows:
            code = r["currency_code"] or "COMPANY_BASE"
            rate = _get_conversion_rate(code, effective_base, rate_map)
            buckets["0-30"]["count"] += r["cnt_0_30"] or 0
            buckets["0-30"]["amount"] += _to_float(r["amt_0_30"]) * rate
            buckets["31-60"]["count"] += r["cnt_31_60"] or 0
            buckets["31-60"]["amount"] += _to_float(r["amt_31_60"]) * rate
            buckets["61-90"]["count"] += r["cnt_61_90"] or 0
            buckets["61-90"]["amount"] += _to_float(r["amt_61_90"]) * rate
            buckets["90+"]["count"] += r["cnt_90_plus"] or 0
            buckets["90+"]["amount"] += _to_float(r["amt_90_plus"]) * rate

        return [
            {"bucket": k, "amount": buckets[k]["amount"], "count": buckets[k]["count"]}
            for k in ["0-30", "31-60", "61-90", "90+"]
        ]

    @staticmethod
    async def get_filters(tenant_id: str) -> dict[str, Any]:
        def _filters():
            qs = AccountMove.objects.filter(tenant_id=tenant_id)
            move_types = [v for v in qs.values_list("move_type", flat=True).distinct() if v]
            states = [v for v in qs.values_list("state", flat=True).distinct() if v]
            payment_states = [v for v in qs.values_list("payment_state", flat=True).distinct() if v]
            currencies = [v for v in qs.values_list("currency_code", flat=True).distinct() if v]
            partners = [
                {"id": row["partner_id"], "name": row["partner__name"] or ""}
                for row in qs.filter(partner_id__isnull=False)
                .values("partner_id", "partner__name")
                .distinct()
                .order_by("partner__name")
            ]
            return {
                "move_types": move_types,
                "move_type": move_types,
                "state": states,
                "states": states,
                "payment_states": payment_states,
                "payment_state": payment_states,
                "currencies": currencies,
                "partners": partners,
                "partner_names": [p["name"] for p in partners if p["name"]],
            }

        return await asyncio.to_thread(_filters)

    @staticmethod
    async def search_moves(
        tenant_id: str,
        filters: list[Any],
        limit: int,
        offset: int,
        company_ids: Optional[list[int]] = None,
    ) -> dict[str, Any]:
        def _search():
            qs = AccountingService._base_qs(tenant_id, company_ids)
            field_map = {
                "odoo_id": "odoo_id",
                "odoo_name": "odoo_name",
                "name": "odoo_name",
                "ref": "ref",
                "partner_name": "partner__name",
                "company_name": "company__name",
                "date": "date",
                "invoice_date": "invoice_date",
                "invoice_date_due": "invoice_date_due",
                "move_type": "move_type",
                "state": "state",
                "payment_state": "payment_state",
                "amount_untaxed": "amount_untaxed",
                "amount_tax": "amount_tax",
                "amount_total": "amount_total",
                "amount_residual": "amount_residual",
                "currency_code": "currency_code",
                "synced_at": "odoo_write_date",
            }
            for f in filters or []:
                field = getattr(f, "field", None) or (f.get("field") if isinstance(f, dict) else None)
                op = (getattr(f, "operator", None) or (f.get("operator") if isinstance(f, dict) else "")).lower()
                value = getattr(f, "value", None) if hasattr(f, "value") else (f.get("value") if isinstance(f, dict) else None)
                max_value = (
                    getattr(f, "maxValue", None)
                    or getattr(f, "max_value", None)
                    or (f.get("maxValue") if isinstance(f, dict) else None)
                    or (f.get("max_value") if isinstance(f, dict) else None)
                )
                orm_field = field_map.get(field)
                if not orm_field:
                    continue
                if op in ("contains", "contain"):
                    qs = qs.filter(**{f"{orm_field}__icontains": value})
                elif op in ("startswith", "starts_with"):
                    qs = qs.filter(**{f"{orm_field}__istartswith": value})
                elif op in ("endswith", "ends_with"):
                    qs = qs.filter(**{f"{orm_field}__iendswith": value})
                elif op in ("equals", "eq", "="):
                    qs = qs.filter(**{orm_field: value})
                elif op in ("gt", "after"):
                    qs = qs.filter(**{f"{orm_field}__gt": value})
                elif op in ("lt", "before"):
                    qs = qs.filter(**{f"{orm_field}__lt": value})
                elif op == "between":
                    if max_value is not None:
                        qs = qs.filter(**{f"{orm_field}__range": (value, max_value)})
                    elif isinstance(value, list) and len(value) == 2:
                        qs = qs.filter(**{f"{orm_field}__range": (value[0], value[1])})

            total = qs.count()
            moves = list(
                qs.select_related("partner", "company")
                .order_by("-date", "-id")[offset : offset + limit]
            )
            return moves, total

        moves, total = await asyncio.to_thread(_search)
        return {
            "items": [_move_to_item(m) for m in moves],
            "total": total,
            "limit": limit,
            "offset": offset,
            "applied_filters": {
                "tenant_id": tenant_id,
                "filters": [
                    getattr(f, "model_dump", lambda: dict(f))() for f in (filters or [])
                ],
                "company_ids": company_ids,
            },
        }

    @staticmethod
    async def export_moves_csv(
        tenant_id: str,
        company_ids: Optional[list[int]] = None,
    ) -> str:
        header_cols = [
            "id", "odoo_id", "odoo_name", "ref", "date", "invoice_date",
            "invoice_date_due", "move_type", "state", "payment_state",
            "partner_name", "company_name", "amount_untaxed", "amount_tax",
            "amount_total", "amount_residual", "currency_code", "synced_at",
        ]

        def _export():
            qs = AccountingService._base_qs(tenant_id, company_ids)
            return list(qs.select_related("partner", "company").order_by("-date", "-id"))

        moves = await asyncio.to_thread(_export)
        lines = [",".join(header_cols)]
        for move in moves:
            item = _move_to_item(move)
            lines.append(",".join(_csv_escape(item.get(col, "")) for col in header_cols))
        return "\n".join(lines)

    # ── Drill-Down Implementations ──────────────────────────────────────────

    @staticmethod
    def _parse_date(date_str: Optional[str]) -> Optional[date]:
        if not date_str:
            return None
        try:
            return date.fromisoformat(date_str)
        except ValueError:
            return None

    @staticmethod
    async def get_dashboard_metric_details(
        tenant_id: str,
        metric: str,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        company_ids: Optional[list[int]] = None,
        base_currency: Optional[str] = None,
        limit: int = 50,
        offset: int = 0
    ) -> dict[str, Any]:
        def _get():
            from doova_one_view.api.accounting.schemas import (
                AccountingDetailMove, MetricDetailCompanyGroup, MetricDetailResponse
            )
            
            base_qs = AccountingService._base_qs(tenant_id, company_ids)
            
            if metric in ['receivable_balance', 'payable_balance', 'overdue_receivable', 'overdue_payable']:
                # Balances are cumulative up to end_date, so we ignore start_date
                qs = base_qs.filter(state="posted")
                if end_date:
                    qs = qs.filter(date__lte=end_date)
                    
                if metric == 'receivable_balance':
                    qs = qs.filter(~Q(payment_state__in=["paid", "reversed"]), move_type="out_invoice", amount_residual__gt=0)
                elif metric == 'payable_balance':
                    qs = qs.filter(~Q(payment_state__in=["paid", "reversed"]), move_type="in_invoice", amount_residual__gt=0)
                elif metric == 'overdue_receivable':
                    overdue_filter = Q(invoice_date_due__lt=date.today()) & ~Q(payment_state__in=["paid", "reversed"])
                    qs = qs.filter(overdue_filter, move_type="out_invoice", amount_residual__gt=0)
                elif metric == 'overdue_payable':
                    overdue_filter = Q(invoice_date_due__lt=date.today()) & ~Q(payment_state__in=["paid", "reversed"])
                    qs = qs.filter(overdue_filter, move_type="in_invoice", amount_residual__gt=0)
            else:
                # Other metrics use the strict date range
                qs = AccountingService._date_qs(base_qs, start_date, end_date)
                if metric in ['total_revenue', 'total_expenses', 'net_profit', 'gross_profit', 'ebit', 'net_cash_flow']:
                    qs = qs.filter(state="posted")
                else:
                    raise ValueError(f"Metric drill-down not supported for: {metric}")

            moves = qs.select_related('partner', 'company').prefetch_related(
                'lines', 'lines__product', 'lines__partner', 'lines__company'
            ).order_by('-date', '-id')

            rate_map = _get_rate_map()
            effective_base = (base_currency or "XAF").upper()
            
            groups = {}
            total_revenue = 0.0
            total_expenses = 0.0
            total_cash_flow = 0.0
            total_metric_sum = 0.0
            flat_moves = []

            for move in moves:
                company_obj = move.company
                cid   = company_obj.odoo_id if company_obj else None
                cname = company_obj.name     if company_obj else "Unknown Company"
                if cid not in groups:
                    groups[cid] = {
                        "company_id": cid,
                        "company_name": cname,
                        "metric_value": 0.0
                    }

                code = move.currency_code or "COMPANY_BASE"
                rate = _get_conversion_rate(code, effective_base, rate_map)
                
                converted_amount = _to_float(move.amount_total) * rate
                converted_residual = _to_float(move.amount_residual) * rate

                move_value = 0.0
                if metric in ['total_revenue', 'total_expenses', 'net_profit', 'gross_profit', 'ebit', 'net_cash_flow']:
                    rev = 0.0
                    exp = 0.0
                    cogs = 0.0
                    opex = 0.0
                    cf = 0.0
                    for l in move.lines.all():
                        company_currency = l.company.currency_code if l.company and hasattr(l.company, 'currency_code') else "COMPANY_BASE"
                        l_rate = _get_conversion_rate(company_currency, effective_base, rate_map)
                        net_credit = (_to_float(l.credit) - _to_float(l.debit)) * l_rate
                        net_debit = (_to_float(l.debit) - _to_float(l.credit)) * l_rate
                        atype = l.account_type or ""
                        acode = l.account_code or ""
                        aname = l.account_name or ""

                        if AccountingService._is_inventory_scrap_adjustment(atype, acode, aname, net_debit):
                            continue

                        if atype.startswith("income"):
                            rev += net_credit
                        elif atype.startswith("expense"):
                            exp += net_debit
                            if atype == "expense_direct_cost":
                                cogs += net_debit
                            elif atype in ("expense", "expense_depreciation"):
                                if acode.startswith("67") or acode.startswith("69"):
                                    pass  # financial charges + income tax excluded from opex
                                else:
                                    opex += net_debit
                        elif atype in ["asset_cash", "liability_credit_card"]:
                            cf += net_debit
                                
                    total_revenue += rev
                    total_expenses += exp
                    total_cash_flow += cf
                    
                    if metric == 'total_revenue':
                        move_value = rev
                    elif metric == 'total_expenses':
                        move_value = exp
                    elif metric == 'gross_profit':
                        move_value = rev - cogs
                    elif metric == 'ebit':
                        move_value = rev - cogs - opex
                    elif metric == 'net_profit':
                        move_value = rev - exp
                    elif metric == 'net_cash_flow':
                        move_value = cf
                        
                    if move_value == 0.0:
                        continue

                elif metric in ['receivable_balance', 'payable_balance', 'overdue_receivable', 'overdue_payable']:
                    move_value = converted_residual

                groups[cid]["metric_value"] += move_value
                total_metric_sum += move_value

                flat_moves.append(AccountingDetailMove(
                    id=move.id,
                    odoo_id=move.odoo_id,
                    odoo_name=move.odoo_name,
                    company_id=cid,
                    company_name=cname,
                    partner=_partner_obj(move),
                    date=move.date,
                    state=move.state,
                    payment_state=move.payment_state,
                    move_type=move.move_type,
                    amount_total=_to_float(move.amount_total),
                    amount_residual=_to_float(move.amount_residual),
                    currency_code=code,
                    lines=[_line_to_item(l) for l in move.lines.all()],
                    converted_amount=converted_amount,
                    converted_residual=converted_residual,
                    ref=move.ref,
                    synced_at=move.synced_at
                ))

            company_groups = [
                MetricDetailCompanyGroup(**g) for g in groups.values()
            ]

            total_items = len(flat_moves)
            paginated_moves = flat_moves[offset:offset + limit]

            return MetricDetailResponse(
                metric_name=metric,
                base_currency=effective_base,
                total_metric_value=total_metric_sum,
                company_groups=company_groups,
                items=paginated_moves,
                total=total_items,
                limit=limit,
                offset=offset
            ).model_dump()

        return await asyncio.to_thread(_get)

    @staticmethod
    async def get_daily_moves(
        tenant_id: str,
        day: str,
        company_ids: Optional[list[int]] = None,
        base_currency: Optional[str] = None,
        limit: int = 50,
        offset: int = 0
    ) -> dict[str, Any]:
        def _get():
            from doova_one_view.api.accounting.schemas import (
                AccountingDetailMove, MetricDetailCompanyGroup, DailyMovesResponse
            )
            target_date = AccountingService._parse_date(day)
            if not target_date:
                raise ValueError("Invalid day format. Expected YYYY-MM-DD")

            qs = AccountingService._base_qs(tenant_id, company_ids).filter(date=target_date)
            moves = qs.select_related('partner', 'company').prefetch_related(
                'lines', 'lines__product', 'lines__partner', 'lines__company'
            ).order_by('-id')

            effective_base = (base_currency or 'XAF').upper()
            rate_map = _get_rate_map()

            groups = {}
            total_revenue = 0.0
            total_expenses = 0.0
            total_cash_flow = 0.0
            flat_moves = []

            for move in moves:
                company_obj = move.company
                cid   = company_obj.odoo_id if company_obj else None
                cname = company_obj.name     if company_obj else "Unknown Company"

                if cid not in groups:
                    groups[cid] = {
                        "company_id": cid,
                        "company_name": cname,
                        "metric_value": 0.0
                    }

                code = move.currency_code or 'COMPANY_BASE'
                rate = _get_conversion_rate(code, effective_base, rate_map)
                converted_amount = _to_float(move.amount_total) * rate
                converted_residual = _to_float(move.amount_residual) * rate

                if move.state == 'posted':
                    rev = 0.0
                    exp = 0.0
                    cf = 0.0
                    for l in move.lines.all():
                        company_currency = l.company.currency_code if l.company and hasattr(l.company, 'currency_code') else "COMPANY_BASE"
                        l_rate = _get_conversion_rate(company_currency, effective_base, rate_map)
                        net_credit = (_to_float(l.credit) - _to_float(l.debit)) * l_rate
                        net_debit = (_to_float(l.debit) - _to_float(l.credit)) * l_rate
                        atype = l.account_type or ""
                        acode = l.account_code or ""
                        aname = l.account_name or ""

                        if AccountingService._is_inventory_scrap_adjustment(atype, acode, aname, net_debit):
                            continue

                        if atype.startswith("income"):
                            rev += net_credit
                        elif atype.startswith("expense"):
                            exp += net_debit
                        elif atype in ["asset_cash", "liability_credit_card"]:
                            cf += net_debit
                            
                    total_revenue += rev
                    total_expenses += exp
                    total_cash_flow += cf
                    groups[cid]['metric_value'] += (rev - exp)

                flat_moves.append(AccountingDetailMove(
                    id=move.id,
                    odoo_id=move.odoo_id,
                    odoo_name=move.odoo_name,
                    company_id=cid,
                    company_name=cname,
                    partner=_partner_obj(move),
                    date=move.date,
                    state=move.state,
                    payment_state=move.payment_state,
                    move_type=move.move_type,
                    amount_total=_to_float(move.amount_total),
                    amount_residual=_to_float(move.amount_residual),
                    currency_code=code,
                    lines=[_line_to_item(l) for l in move.lines.all()],
                    converted_amount=converted_amount,
                    converted_residual=converted_residual,
                    ref=move.ref,
                    synced_at=move.synced_at
                ))

            company_groups = [
                MetricDetailCompanyGroup(**g) for g in groups.values()
            ]

            total_items = len(flat_moves)
            paginated_moves = flat_moves[offset:offset + limit]

            return DailyMovesResponse(
                date=day,
                base_currency=effective_base,
                total_revenue=total_revenue,
                total_expenses=total_expenses,
                net_profit=total_revenue - total_expenses,
                net_cash_flow=total_cash_flow,
                move_count=total_items,
                company_groups=company_groups,
                items=paginated_moves,
                total=total_items,
                limit=limit,
                offset=offset
            ).model_dump()

        return await asyncio.to_thread(_get)

    @staticmethod
    async def get_market_breakdown_details(
        tenant_id: str,
        section: str,
        entity_id: int,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        company_ids: Optional[list[int]] = None,
        base_currency: Optional[str] = None,
        limit: int = 50,
        offset: int = 0
    ) -> dict[str, Any]:
        def _get():
            from doova_one_view.api.accounting.schemas import (
                AccountingDetailMove, MetricDetailCompanyGroup, MarketBreakdownResponse
            )
            SECTION_FILTER = {
                'top_revenue_customers': ('partner_id', 'partner__name'),
                'top_expense_vendors':   ('partner_id', 'partner__name'),
            }

            if section not in SECTION_FILTER:
                raise ValueError(f"Invalid section: {section}")

            fk_field, name_field = SECTION_FILTER[section]

            base_qs = AccountingService._base_qs(tenant_id, company_ids)
            base_qs = AccountingService._date_qs(base_qs, start_date, end_date)
            
            if section == 'top_revenue_customers':
                base_qs = base_qs.filter(move_type="out_invoice", state="posted")
            else:
                base_qs = base_qs.filter(move_type="in_invoice", state="posted")

            base_qs = base_qs.filter(**{fk_field: entity_id})

            first = base_qs.first()
            entity_name = first.partner.name if (first and first.partner) else 'Unknown'

            moves = base_qs.select_related('partner', 'company').prefetch_related(
                'lines', 'lines__product', 'lines__partner', 'lines__company'
            ).distinct().order_by('-date', '-id')

            effective_base = (base_currency or 'XAF').upper()
            rate_map = _get_rate_map()

            groups = {}
            flat_moves = []
            total_amount = 0.0

            for move in moves:
                company_obj = move.company
                cid   = company_obj.odoo_id if company_obj else None
                cname = company_obj.name     if company_obj else "Unknown Company"

                if cid not in groups:
                    groups[cid] = {
                        "company_id": cid,
                        "company_name": cname,
                        "metric_value": 0.0
                    }

                code = move.currency_code or 'COMPANY_BASE'
                rate = _get_conversion_rate(code, effective_base, rate_map)
                converted_amount = _to_float(move.amount_total) * rate
                converted_residual = _to_float(move.amount_residual) * rate

                groups[cid]['metric_value'] += converted_amount
                total_amount += converted_amount

                flat_moves.append(AccountingDetailMove(
                    id=move.id,
                    odoo_id=move.odoo_id,
                    odoo_name=move.odoo_name,
                    company_id=cid,
                    company_name=cname,
                    partner=_partner_obj(move),
                    date=move.date,
                    state=move.state,
                    payment_state=move.payment_state,
                    move_type=move.move_type,
                    amount_total=_to_float(move.amount_total),
                    amount_residual=_to_float(move.amount_residual),
                    currency_code=code,
                    lines=[_line_to_item(l) for l in move.lines.all()],
                    converted_amount=converted_amount,
                    converted_residual=converted_residual,
                    ref=move.ref,
                    synced_at=move.synced_at
                ))

            company_groups = [
                MetricDetailCompanyGroup(**g) for g in groups.values()
            ]

            total_items = len(flat_moves)
            paginated_moves = flat_moves[offset:offset + limit]

            return MarketBreakdownResponse(
                section=section,
                entity_id=entity_id,
                entity_name=entity_name,
                base_currency=effective_base,
                total_amount=total_amount,
                move_count=total_items,
                company_groups=company_groups,
                items=paginated_moves,
                total=total_items,
                limit=limit,
                offset=offset
            ).model_dump()

        return await asyncio.to_thread(_get)

    @staticmethod
    async def get_entity_profile(
        tenant_id: str,
        entity_type: str,
        entity_id: int
    ) -> dict[str, Any]:
        def _get():
            from odoo_app.models import Partner
            from doova_one_view.api.accounting.schemas import EntityProfileResponse
            
            if entity_type not in ['customer', 'vendor', 'supplier']:
                raise ValueError(f"Invalid entity type: {entity_type}")
                
            try:
                p = Partner.objects.get(id=entity_id, tenant_id=tenant_id)
                return EntityProfileResponse(
                    entity_id=p.id,
                    entity_type=entity_type,
                    name=p.name,
                    email=p.email,
                    phone=p.phone,
                    city=p.city
                ).model_dump()
            except Partner.DoesNotExist:
                raise NotFoundError("Partner", str(entity_id))

        return await asyncio.to_thread(_get)

    @staticmethod
    async def get_product_moves_details(
        tenant_id: str,
        product_id: int,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        company_ids: Optional[list[int]] = None,
        base_currency: Optional[str] = None,
        limit: int = 50,
        offset: int = 0
    ) -> dict[str, Any]:
        def _get():
            from odoo_app.models import Product
            from doova_one_view.api.accounting.schemas import (
                ProductMovesDetailResponse, MetricDetailCompanyGroup
            )
            try:
                product = Product.objects.get(id=product_id, tenant_id=tenant_id)
            except Product.DoesNotExist:
                raise NotFoundError("Product", str(product_id))

            lines_qs = AccountMoveLine.objects.filter(
                tenant_id=tenant_id,
                product_id=product_id
            )
            
            if start_date:
                lines_qs = lines_qs.filter(account_move__date__gte=start_date)
            if end_date:
                lines_qs = lines_qs.filter(account_move__date__lte=end_date)

            lines_qs = lines_qs.select_related(
                'account_move', 'account_move__company', 'account_move__partner', 'product'
            ).order_by('-account_move__date')

            if company_ids:
                lines_qs = lines_qs.filter(account_move__company_id__in=company_ids)

            effective_base = (base_currency or 'XAF').upper()
            rate_map = _get_rate_map()

            groups = {}
            flat_lines = []
            total_amount = 0.0
            total_qty = 0.0

            for line in lines_qs:
                move = line.account_move
                if not move:
                    continue

                company_obj = move.company
                cid   = company_obj.odoo_id if company_obj else None
                cname = company_obj.name     if company_obj else "Unknown Company"

                if cid not in groups:
                    groups[cid] = {
                        "company_id": cid,
                        "company_name": cname,
                        "metric_value": 0.0
                    }

                code = move.currency_code or 'COMPANY_BASE'
                rate = _get_conversion_rate(code, effective_base, rate_map)
                
                line_total = _to_float(line.price_subtotal)
                converted_amount = line_total * rate
                
                groups[cid]['metric_value'] += converted_amount
                total_amount += converted_amount
                
                qty = _to_float(line.quantity)
                total_qty += qty

                flat_lines.append(_line_to_item(line))

            company_groups = [
                MetricDetailCompanyGroup(**g) for g in groups.values()
            ]

            total_items = len(flat_lines)
            paginated = flat_lines[offset:offset + limit]

            return ProductMovesDetailResponse(
                product_id=product.id,
                product_name=product.name,
                product_sku=product.default_code,
                product_type=product.product_type,
                list_price=_to_float(product.list_price) if product.list_price else None,
                base_currency=effective_base,
                total_amount=total_amount,
                total_qty=total_qty,
                line_count=total_items,
                company_groups=company_groups,
                items=paginated,
                total=total_items,
                limit=limit,
                offset=offset
            ).model_dump()

        return await asyncio.to_thread(_get)

    @staticmethod
    async def get_aging_details(
        tenant_id: str,
        bucket: str,
        move_type: str,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        company_ids: Optional[list[int]] = None,
        base_currency: Optional[str] = None,
        limit: int = 50,
        offset: int = 0
    ) -> dict[str, Any]:
        def _get():
            from doova_one_view.api.accounting.schemas import (
                AccountingDetailMove, MetricDetailCompanyGroup, AgingDetailsResponse
            )
            from odoo_app.models import AccountPartialReconcile, Company
            rate_map = _get_rate_map()
            effective_base = base_currency or "XAF"
            
            if end_date:
                try:
                    ref_date = datetime.strptime(end_date, "%Y-%m-%d").date()
                except Exception:
                    ref_date = date.today()
            else:
                ref_date = date.today()

            b_key = bucket.lower().strip()
            account_type = "asset_receivable" if move_type == "out_invoice" else "liability_payable"

            # 1. Partial Reconcile Engine matching Accounting Overview
            if AccountPartialReconcile.objects.filter(tenant_id=tenant_id).exists():
                from django.db import connection
                if b_key in ("current", "not_due", "not-due", "not due", "0"):
                    day_cond = "days <= 0"
                elif b_key in ("0-30", "0-30 days", "0-30days"):
                    day_cond = "days <= 30"
                elif b_key in ("1-30", "1-30 days", "1-30days"):
                    day_cond = "days BETWEEN 1 AND 30"
                elif b_key in ("31-60", "31-60 days", "31-60days"):
                    day_cond = "days BETWEEN 31 AND 60"
                elif b_key in ("61-90", "61-90 days", "61-90days"):
                    day_cond = "days BETWEEN 61 AND 90"
                elif b_key in ("91-120", "91-120 days", "91-120days"):
                    day_cond = "days BETWEEN 91 AND 120"
                elif b_key in ("older", "121+", "121+ days", "120+", ">120"):
                    day_cond = "days >= 121"
                elif b_key in ("90+", "90+ days", ">90", "91+"):
                    day_cond = "days >= 91"
                else:
                    raise ValidationError(f"Invalid bucket: {bucket}. Valid values: current, 0-30, 1-30, 31-60, 61-90, 91-120, Older, 90+")

                c_filter = "AND l.company_id IN %s" if company_ids and None not in company_ids else ""
                c_params = [tuple(int(c) for c in company_ids if c is not None)] if c_filter else []

                sql = f"""
                    WITH line_recon AS (
                        SELECT
                            l.id AS line_id,
                            l.company_id,
                            l.account_move_id,
                            m.date AS move_date,
                            l.debit,
                            l.credit,
                            COALESCE(SUM(pr_deb.amount), 0) AS reconciled_debit,
                            COALESCE(SUM(pr_cred.amount), 0) AS reconciled_credit
                        FROM fact_account_move_lines l
                        JOIN fact_account_moves m ON l.account_move_id = m.id
                        LEFT JOIN fact_account_partial_reconciles pr_deb 
                            ON pr_deb.debit_move_line_id = l.id AND pr_deb.max_date <= %s
                        LEFT JOIN fact_account_partial_reconciles pr_cred 
                            ON pr_cred.credit_move_line_id = l.id AND pr_cred.max_date <= %s
                        WHERE m.state = 'posted'
                          AND l.account_type = %s
                          AND m.date <= %s
                          AND l.tenant_id = %s
                          {c_filter}
                        GROUP BY l.id, l.company_id, l.account_move_id, m.date, l.debit, l.credit
                    ),
                    line_residual AS (
                        SELECT
                            line_id,
                            company_id,
                            account_move_id,
                            move_date,
                            (DATE %s - move_date) AS days,
                            CASE 
                                WHEN '{account_type}' = 'asset_receivable' THEN
                                    CASE WHEN debit > 0 THEN debit - reconciled_debit ELSE -(credit - reconciled_credit) END
                                ELSE
                                    CASE WHEN credit > 0 THEN credit - reconciled_credit ELSE -(debit - reconciled_debit) END
                            END AS residual
                        FROM line_recon
                    )
                    SELECT
                        line_id,
                        company_id,
                        account_move_id,
                        days,
                        residual
                    FROM line_residual
                    WHERE {day_cond}
                      AND ABS(residual) > 0.01
                    ORDER BY move_date DESC, ABS(residual) DESC
                """
                params = [ref_date, ref_date, account_type, ref_date, tenant_id] + c_params + [ref_date]
                with connection.cursor() as cursor:
                    cursor.execute(sql, params)
                    rows = cursor.fetchall()

                total_count = len(rows)
                page_rows = rows[offset : offset + limit]
                move_ids = list({r[2] for r in page_rows})
                moves_map = {
                    m.id: m 
                    for m in AccountMove.objects.filter(id__in=move_ids).select_related("partner", "company").prefetch_related("lines", "lines__product")
                }

                groups = {}
                total_amount = 0.0
                comp_objs = {c.id: c for c in Company.objects.filter(tenant_id=tenant_id)}

                for r in rows:
                    cid = r[1]
                    res_val = float(r[4])
                    comp = comp_objs.get(cid)
                    code = comp.currency_code if comp else "COMPANY_BASE"
                    rate = _get_conversion_rate(code, effective_base, rate_map)
                    conv_res = res_val * rate

                    if cid not in groups:
                        groups[cid] = {
                            "company_id": comp.odoo_id if comp else cid,
                            "company_name": comp.name if comp else "Unknown Company",
                            "metric_value": 0.0,
                        }
                    groups[cid]["metric_value"] += conv_res
                    total_amount += conv_res

                company_groups = [MetricDetailCompanyGroup(**g) for g in groups.values()]
                company_groups.sort(key=lambda x: x.metric_value, reverse=True)

                flat_moves = []
                for r in page_rows:
                    move = moves_map.get(r[2])
                    if not move:
                        continue
                    code = move.currency_code or "COMPANY_BASE"
                    rate = _get_conversion_rate(code, effective_base, rate_map)
                    conv_amount = _to_float(move.amount_total) * rate
                    residual_line_val = float(r[4])
                    conv_res = residual_line_val * rate

                    company_obj = move.company
                    cid = company_obj.odoo_id if company_obj else None
                    cname = company_obj.name if company_obj else "Unknown Company"

                    flat_moves.append(AccountingDetailMove(
                        id=move.id,
                        odoo_id=move.odoo_id,
                        odoo_name=move.odoo_name,
                        company_id=cid,
                        company_name=cname,
                        partner=_partner_obj(move),
                        date=move.date,
                        state=move.state,
                        payment_state=move.payment_state,
                        move_type=move.move_type,
                        amount_total=_to_float(move.amount_total),
                        amount_residual=residual_line_val,
                        currency_code=code,
                        lines=[_line_to_item(l) for l in move.lines.all()],
                        converted_amount=conv_amount,
                        converted_residual=conv_res,
                        ref=move.ref,
                        synced_at=move.synced_at
                    ))

                return AgingDetailsResponse(
                    bucket=bucket,
                    move_type=move_type,
                    base_currency=effective_base,
                    total_amount=total_amount,
                    move_count=total_count,
                    company_groups=company_groups,
                    items=flat_moves,
                    total=total_count,
                    limit=limit,
                    offset=offset,
                ).model_dump()

            # 2. Fallback for non-reconciled tenants
            qs = AccountingService._date_qs(
                AccountingService._base_qs(tenant_id, company_ids), start_date, end_date
            )
            base = qs.filter(
                move_type=move_type,
                amount_residual__gt=0,
            ).exclude(payment_state__in=["paid", "reversed"])
            
            if b_key in ("current", "not_due", "not-due", "not due", "0"):
                bucket_qs = base.filter(Q(invoice_date_due__isnull=True) | Q(invoice_date_due__gte=ref_date))
            elif b_key in ("0-30", "0-30 days", "0-30days"):
                bucket_qs = base.filter(
                    invoice_date_due__isnull=False,
                    invoice_date_due__gte=ref_date - timedelta(days=30),
                    invoice_date_due__lte=ref_date
                )
            elif b_key in ("1-30", "1-30 days", "1-30days"):
                bucket_qs = base.filter(
                    invoice_date_due__isnull=False,
                    invoice_date_due__gte=ref_date - timedelta(days=30),
                    invoice_date_due__lte=ref_date - timedelta(days=1)
                )
            elif b_key in ("31-60", "31-60 days", "31-60days"):
                bucket_qs = base.filter(
                    invoice_date_due__isnull=False,
                    invoice_date_due__gte=ref_date - timedelta(days=60),
                    invoice_date_due__lte=ref_date - timedelta(days=31)
                )
            elif b_key in ("61-90", "61-90 days", "61-90days"):
                bucket_qs = base.filter(
                    invoice_date_due__isnull=False,
                    invoice_date_due__gte=ref_date - timedelta(days=90),
                    invoice_date_due__lte=ref_date - timedelta(days=61)
                )
            elif b_key in ("91-120", "91-120 days", "91-120days"):
                bucket_qs = base.filter(
                    invoice_date_due__isnull=False,
                    invoice_date_due__gte=ref_date - timedelta(days=120),
                    invoice_date_due__lte=ref_date - timedelta(days=91)
                )
            elif b_key in ("older", "121+", "121+ days", "120+", ">120"):
                bucket_qs = base.filter(
                    invoice_date_due__isnull=False,
                    invoice_date_due__lte=ref_date - timedelta(days=121)
                )
            elif b_key in ("90+", "90+ days", ">90", "91+"):
                bucket_qs = base.filter(
                    invoice_date_due__isnull=False,
                    invoice_date_due__lte=ref_date - timedelta(days=91)
                )
            else:
                raise ValidationError(f"Invalid bucket: {bucket}. Valid values: current, 0-30, 1-30, 31-60, 61-90, 91-120, Older, 90+")
                
            moves = bucket_qs.select_related("partner", "company").prefetch_related("lines", "lines__product").order_by("-date", "-id")
            
            total_count = moves.count()
            
            groups = {}
            total_amount = 0.0
            
            # Use values to quickly calculate the totals and groups
            aggs = bucket_qs.values("company_id", "company__odoo_id", "company__name", "currency_code").annotate(
                val=Sum("amount_residual")
            )
            for row in aggs:
                cid = row["company_id"]
                c_odoo_id = row["company__odoo_id"]
                cname = row["company__name"] or "Unknown Company"
                code = row["currency_code"] or "COMPANY_BASE"
                val = _to_float(row["val"]) * _get_conversion_rate(code, effective_base, rate_map)
                
                if cid not in groups:
                    groups[cid] = {
                        "company_id": c_odoo_id,
                        "company_name": cname,
                        "metric_value": 0.0
                    }
                groups[cid]["metric_value"] += val
                total_amount += val
                
            company_groups = [MetricDetailCompanyGroup(**g) for g in groups.values()]
            company_groups.sort(key=lambda x: x.metric_value, reverse=True)
            
            flat_moves = []
            for move in moves[offset:offset + limit]:
                code = move.currency_code or "COMPANY_BASE"
                rate = _get_conversion_rate(code, effective_base, rate_map)
                conv_amount = _to_float(move.amount_total) * rate
                conv_res = _to_float(move.amount_residual) * rate
                
                company_obj = move.company
                cid = company_obj.odoo_id if company_obj else None
                cname = company_obj.name if company_obj else "Unknown Company"

                flat_moves.append(AccountingDetailMove(
                    id=move.id,
                    odoo_id=move.odoo_id,
                    odoo_name=move.odoo_name,
                    company_id=cid,
                    company_name=cname,
                    partner=_partner_obj(move),
                    date=move.date,
                    state=move.state,
                    payment_state=move.payment_state,
                    move_type=move.move_type,
                    amount_total=_to_float(move.amount_total),
                    amount_residual=_to_float(move.amount_residual),
                    currency_code=code,
                    lines=[_line_to_item(l) for l in move.lines.all()],
                    converted_amount=conv_amount,
                    converted_residual=conv_res,
                    ref=move.ref,
                    synced_at=move.synced_at
                ))
                
            return AgingDetailsResponse(
                bucket=bucket,
                move_type=move_type,
                base_currency=effective_base,
                total_amount=total_amount,
                move_count=total_count,
                company_groups=company_groups,
                items=flat_moves,
                total=total_count,
                limit=limit,
                offset=offset,
            ).model_dump()
            
        return await asyncio.to_thread(_get)
    @staticmethod
    async def get_journal_cards(
        tenant_id: str,
        start_date: str = None,
        end_date: str = None,
        company_ids: list[int] = None,
        base_currency: str = None,
        limit: int = 50,
        offset: int = 0
    ) -> dict[str, Any]:
        def _get():
            from odoo_app.models import AccountJournal, AccountMove, BankStatement, AccountMoveLine
            from django.db.models import Sum, Q, Count, Case, When, F, DecimalField
            from datetime import date
            from doova_one_view.api.kpi.service import _get_rate_map, _get_conversion_rate, _sum_converted
            
            rate_map = _get_rate_map()
            effective_base = (base_currency or "XAF").upper()
            
            qs = AccountJournal.objects.filter(tenant_id=tenant_id)
            if company_ids:
                qs = qs.filter(company_id__in=company_ids)
                
            total = qs.count()
            journals = list(qs.select_related('company').order_by('name')[offset:offset+limit])
            if not journals:
                return {
                    "items": [],
                    "total": total,
                    "limit": limit,
                    "offset": offset,
                    "base_currency": effective_base
                }

            j_ids = [j.id for j in journals]
            today_val = date.today()

            # 1. Batch Misc Operations across all journals in page
            misc_qs = AccountMove.objects.filter(
                tenant_id=tenant_id,
                journal_id__in=j_ids,
                state='posted',
                move_type='entry'
            )
            if start_date:
                misc_qs = misc_qs.filter(date__gte=start_date)
            if end_date:
                misc_qs = misc_qs.filter(date__lte=end_date)

            misc_aggs = {
                r['journal_id']: r
                for r in misc_qs.values('journal_id').annotate(
                    count=Count('id'),
                    amount=Sum('amount_total')
                )
            }

            # 2. Batch Bank Statements across bank/cash journals
            bank_cash_jids = [j.id for j in journals if (j.type or "general") in ["bank", "cash"]]
            latest_stmts_map = {}
            if bank_cash_jids:
                stmt_qs = BankStatement.objects.filter(tenant_id=tenant_id, journal_id__in=bank_cash_jids)
                if end_date:
                    stmt_qs = stmt_qs.filter(date__lte=end_date)
                
                for stmt in stmt_qs.order_by('journal_id', '-date', '-id'):
                    if stmt.journal_id not in latest_stmts_map:
                        latest_stmts_map[stmt.journal_id] = _to_float(stmt.balance_end_real)

            # 3. Batch General Ledger lines for bank/cash & general journals
            gl_base = AccountMoveLine.objects.filter(
                tenant_id=tenant_id,
                account_move__state='posted'
            )
            if end_date:
                gl_base = gl_base.filter(account_move__date__lte=end_date)

            gl_journal_aggs = {
                r['account_move__journal_id']: r
                for r in gl_base.filter(account_move__journal_id__in=j_ids).values('account_move__journal_id').annotate(
                    total_debit=Sum('debit'),
                    total_credit=Sum('credit')
                )
            }

            code_company_pairs = set()
            for j in journals:
                if hasattr(j, 'default_account_code') and j.default_account_code:
                    code_company_pairs.add((j.default_account_code, j.company_id))

            gl_code_map = {}
            if code_company_pairs:
                q_codes = Q()
                for code, comp_id in code_company_pairs:
                    if comp_id:
                        q_codes |= Q(account_code=code, company_id=comp_id)
                    else:
                        q_codes |= Q(account_code=code)
                
                for r in gl_base.filter(q_codes).values('account_code', 'company_id').annotate(
                    total_debit=Sum('debit'),
                    total_credit=Sum('credit')
                ):
                    gl_code_map[(r['account_code'], r['company_id'])] = _to_float(r['total_debit']) - _to_float(r['total_credit'])

            # 4. Batch Sale & Purchase Moves
            sale_purchase_jids = [j.id for j in journals if (j.type or "general") in ["sale", "purchase"]]
            sale_purchase_aggs = {}
            if sale_purchase_jids:
                sp_moves = AccountMove.objects.filter(
                    tenant_id=tenant_id,
                    journal_id__in=sale_purchase_jids,
                )
                if start_date:
                    sp_moves = sp_moves.filter(date__gte=start_date)
                if end_date:
                    sp_moves = sp_moves.filter(date__lte=end_date)

                sp_data = sp_moves.values('journal_id', 'state', 'payment_state').annotate(
                    cnt=Count('id'),
                    total_signed=Sum('amount_total_signed'),
                    residual_signed=Sum('amount_residual_signed'),
                    late_cnt=Count(Case(When(invoice_date_due__lt=today_val, then=1))),
                    late_residual=Sum(Case(When(invoice_date_due__lt=today_val, then='amount_residual_signed'), default=0, output_field=DecimalField()))
                )
                for r in sp_data:
                    jid = r['journal_id']
                    if jid not in sale_purchase_aggs:
                        sale_purchase_aggs[jid] = {
                            'draft_count': 0,
                            'draft_amount': 0.0,
                            'unpaid_count': 0,
                            'unpaid_amount': 0.0,
                            'late_count': 0,
                            'late_amount': 0.0,
                        }
                    rec = sale_purchase_aggs[jid]
                    st = r['state']
                    pay_st = r['payment_state']
                    
                    if st == 'draft':
                        rec['draft_count'] += r['cnt'] or 0
                        rec['draft_amount'] += abs(_to_float(r['total_signed']))
                    elif st == 'posted' and pay_st not in ['paid', 'reversed']:
                        rec['unpaid_count'] += r['cnt'] or 0
                        rec['unpaid_amount'] += abs(_to_float(r['residual_signed']))
                        rec['late_count'] += r['late_cnt'] or 0
                        rec['late_amount'] += abs(_to_float(r['late_residual']))

            # 5. Batch General Journal Moves (state=draft & state=posted)
            general_jids = [j.id for j in journals if (j.type or "general") not in ["bank", "cash", "sale", "purchase"]]
            general_moves_aggs = {}
            if general_jids:
                gen_moves = AccountMove.objects.filter(
                    tenant_id=tenant_id,
                    journal_id__in=general_jids
                )
                if start_date:
                    gen_moves = gen_moves.filter(date__gte=start_date)
                if end_date:
                    gen_moves = gen_moves.filter(date__lte=end_date)
                
                for r in gen_moves.values('journal_id', 'state').annotate(
                    count=Count('id'),
                    amount=Sum('amount_total')
                ):
                    jid = r['journal_id']
                    if jid not in general_moves_aggs:
                        general_moves_aggs[jid] = {}
                    general_moves_aggs[jid][r['state']] = {
                        'count': r['count'] or 0,
                        'amount': _to_float(r['amount'])
                    }

            cards = []
            for j in journals:
                company_currency = j.company.currency_code if (j.company and j.company.currency_code) else "COMPANY_BASE"
                if not company_currency or company_currency == "COMPANY_BASE":
                    company_currency = "XAF"
                
                rate = _get_conversion_rate(company_currency, effective_base, rate_map)
                
                metrics = {
                    "balance": 0.0,
                    "latest_statement_balance": 0.0,
                    "gl_balance": 0.0,
                    "outstanding_payments": 0.0,
                    "outstanding_receipts": 0.0,
                    "unpaid_count": 0,
                    "unpaid_amount": 0.0,
                    "draft_count": 0,
                    "draft_amount": 0.0,
                    "late_count": 0,
                    "late_amount": 0.0,
                    "misc_operations_count": 0,
                    "misc_operations_amount": 0.0
                }
                
                misc_data = misc_aggs.get(j.id)
                if misc_data:
                    metrics["misc_operations_count"] = misc_data['count'] or 0
                    metrics["misc_operations_amount"] = _to_float(misc_data['amount']) * rate
                
                j_type = j.type or "general"
                
                if j_type in ["bank", "cash"]:
                    if j.id in latest_stmts_map:
                        metrics["latest_statement_balance"] = latest_stmts_map[j.id] * rate
                        metrics["balance"] = metrics["latest_statement_balance"]

                    if hasattr(j, 'default_account_code') and j.default_account_code:
                        gl_net = gl_code_map.get((j.default_account_code, j.company_id), 0.0)
                    else:
                        j_gl = gl_journal_aggs.get(j.id)
                        gl_net = (_to_float(j_gl['total_debit']) - _to_float(j_gl['total_credit'])) if j_gl else 0.0

                    metrics["gl_balance"] = gl_net * rate
                    if j.id not in latest_stmts_map:
                        metrics["balance"] = metrics["gl_balance"]

                    if hasattr(j, 'default_account_code') and j.default_account_code:
                        j_gl = gl_journal_aggs.get(j.id)
                        j_own_net = (_to_float(j_gl['total_debit']) - _to_float(j_gl['total_credit'])) if j_gl else 0.0
                        journal_own_bal = j_own_net * rate
                    else:
                        journal_own_bal = metrics["gl_balance"]

                    metrics["misc_operations_amount"] = metrics["gl_balance"] - journal_own_bal

                elif j_type in ["sale", "purchase"]:
                    sp_res = sale_purchase_aggs.get(j.id, {})
                    metrics["draft_count"] = sp_res.get("draft_count", 0)
                    metrics["draft_amount"] = sp_res.get("draft_amount", 0.0) * rate
                    metrics["unpaid_count"] = sp_res.get("unpaid_count", 0)
                    metrics["unpaid_amount"] = sp_res.get("unpaid_amount", 0.0) * rate
                    metrics["late_count"] = sp_res.get("late_count", 0)
                    metrics["late_amount"] = sp_res.get("late_amount", 0.0) * rate

                else:
                    g_res = general_moves_aggs.get(j.id, {})
                    draft_info = g_res.get("draft", {})
                    metrics["draft_count"] = draft_info.get("count", 0)
                    metrics["draft_amount"] = draft_info.get("amount", 0.0) * rate

                    j_gl = gl_journal_aggs.get(j.id)
                    gl_net = (_to_float(j_gl['total_debit']) - _to_float(j_gl['total_credit'])) if j_gl else 0.0
                    metrics["gl_balance"] = gl_net * rate

                    posted_info = g_res.get("posted", {})
                    metrics["balance"] = posted_info.get("amount", 0.0) * rate
                    metrics["unpaid_count"] = posted_info.get("count", 0)
                    metrics["unpaid_amount"] = posted_info.get("amount", 0.0) * rate

                cards.append({
                    "id": j.odoo_id,
                    "name": j.name,
                    "code": j.code,
                    "type": j.type,
                    "currency_code": j.currency_code or company_currency,
                    "company_id": j.company.odoo_id if j.company else None,
                    "company_name": j.company.name if j.company else None,
                    "metrics": metrics
                })
                
            return {
                "items": cards,
                "total": total,
                "limit": limit,
                "offset": offset,
                "base_currency": effective_base
            }
            
        return await asyncio.to_thread(_get)
