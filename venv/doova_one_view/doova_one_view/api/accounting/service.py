"""
Accounting API service.
"""

import asyncio
from datetime import date, timedelta
from typing import Any, Optional

from django.db.models import Avg, Count, Prefetch, Q, Sum

from odoo_app.models.account_move import AccountMove
from odoo_app.models.account_move_line import AccountMoveLine
from doova_one_view.api.common.exceptions import NotFoundError
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
    def _base_qs(tenant_id: str, company_ids: Optional[list[int]] = None):
        qs = AccountMove.objects.filter(tenant_id=tenant_id)
        if company_ids:
            qs = qs.filter(company_id__in=company_ids)
        return qs

    @staticmethod
    def _date_qs(qs, start_date: Optional[str], end_date: Optional[str]):
        if start_date:
            qs = qs.filter(date__gte=start_date)
        if end_date:
            qs = qs.filter(date__lte=end_date)
        return qs

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

            posted_qs = qs.filter(state="posted")
            from odoo_app.models.account_move_line import AccountMoveLine
            from django.db.models import Sum
            
            line_aggs = AccountMoveLine.objects.filter(
                account_move__in=posted_qs
            ).values("account_type", "account_code", "company__currency_code").annotate(
                total_debit=Sum("debit"),
                total_credit=Sum("credit")
            )
            
            true_revenue = 0.0
            true_expenses = 0.0
            true_cogs = 0.0
            true_opex = 0.0
            
            for agg in line_aggs:
                atype = agg["account_type"] or ""
                acode = agg["account_code"] or ""
                # Use company currency to convert to dashboard base currency
                company_currency = agg["company__currency_code"] or "COMPANY_BASE"
                rate = _get_conversion_rate(company_currency, effective_base, rate_map)
                
                net_credit = (_to_float(agg["total_credit"]) - _to_float(agg["total_debit"])) * rate
                net_debit = (_to_float(agg["total_debit"]) - _to_float(agg["total_credit"])) * rate
                
                if atype.startswith("income"):
                    true_revenue += net_credit
                elif atype.startswith("expense"):
                    true_expenses += net_debit
                    if atype == "expense_direct_cost":
                        true_cogs += net_debit
                    elif atype in ("expense", "expense_depreciation"):
                        if not (acode.startswith("64") or acode.startswith("67") or acode.startswith("69")):
                            true_opex += net_debit

            gross_profit = true_revenue - true_cogs
            ebit = gross_profit - true_opex
            net_profit = true_revenue - true_expenses
            
            cumulative_qs = AccountingService._base_qs(tenant_id, company_ids)
            if end_date:
                cumulative_qs = cumulative_qs.filter(date__lte=end_date)
            cumulative_qs = cumulative_qs.filter(state='posted')
            
            cumulative_aggs = AccountMoveLine.objects.filter(
                account_move__in=cumulative_qs,
                account_type__in=["asset_receivable", "liability_payable", "liability_current"]
            ).values("account_type", "company__currency_code").annotate(
                total_debit=Sum("debit"),
                total_credit=Sum("credit")
            )
            
            receivable_balance = 0.0
            payable_balance = 0.0
            
            for agg in cumulative_aggs:
                company_currency = agg["company__currency_code"] or "COMPANY_BASE"
                rate = _get_conversion_rate(company_currency, effective_base, rate_map)
                net = (_to_float(agg["total_debit"]) - _to_float(agg["total_credit"])) * rate
                if agg["account_type"] == "asset_receivable":
                    receivable_balance += net
                elif agg["account_type"] in ("liability_payable", "liability_current"):
                    payable_balance += net

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

            trend_aggs = AccountMoveLine.objects.filter(
                account_move__in=posted_qs
            ).values("account_move__date", "account_type", "company__currency_code").annotate(
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



            state_distribution = {
                row["state"] or "unknown": row["count"]
                for row in qs.values("state").annotate(count=Count("id"))
            }
            payment_state_distribution = {
                row["payment_state"] or "unknown": row["count"]
                for row in qs.values("payment_state").annotate(count=Count("id"))
            }
            move_type_distribution = {
                row["move_type"] or "unknown": row["count"]
                for row in qs.values("move_type").annotate(count=Count("id"))
            }

            receivables_aging = AccountingService._aging(qs, "out_invoice", effective_base, rate_map)
            payables_aging = AccountingService._aging(qs, "in_invoice", effective_base, rate_map)

            net_profit_margin_pct = (net_profit / true_revenue * 100) if true_revenue else 0.0
            
            # Calculate total cash flow from the trend array
            total_cash_flow = sum(item["value"] for item in cash_flow_trend)
            
            applied = {
                "tenant_id": tenant_id,
                "start_date": start_date,
                "end_date": end_date,
                "company_ids": company_ids,
            }
            return {
                "total_revenue": _metric(true_revenue),
                "total_expenses": _metric(true_expenses),
                "net_profit": _metric(net_profit),
                "net_cash_flow": _metric(total_cash_flow),
                "gross_profit": _metric(gross_profit),
                "ebit": _metric(ebit),
                "net_profit_margin_pct": net_profit_margin_pct,
                "receivable_balance": receivable_balance,
                "overdue_receivable": overdue_receivable,
                "payable_balance": payable_balance,
                "overdue_payable": overdue_payable,
                "top_revenue_customers": top_revenue_customers,
                "top_expense_vendors": top_expense_vendors,
                "revenue_trend": revenue_trend,
                "expense_trend": expense_trend,
                "cash_flow_trend": cash_flow_trend,
                "state_distribution": state_distribution,
                "payment_state_distribution": payment_state_distribution,
                "payment_status_distribution": payment_state_distribution,
                "move_type_distribution": move_type_distribution,
                "receivables_aging": receivables_aging,
                "payables_aging": payables_aging,
                "ar_aging": receivables_aging,
                "ap_aging": payables_aging,
                "applied_filters": applied,
            }

        return await asyncio.to_thread(_dashboard)

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
        base = qs.filter(
            move_type=move_type,
            invoice_date_due__isnull=False,
            amount_residual__gt=0,
        ).exclude(payment_state__in=["paid", "reversed"])
        buckets = [
            ("0-30", today - timedelta(days=30), today),
            ("31-60", today - timedelta(days=60), today - timedelta(days=31)),
            ("61-90", today - timedelta(days=90), today - timedelta(days=61)),
            ("90+", None, today - timedelta(days=91)),
        ]
        out = []
        for label, start, end in buckets:
            bucket_qs = base.filter(invoice_date_due__lte=end)
            if start is not None:
                bucket_qs = bucket_qs.filter(invoice_date_due__gte=start)
            
            amount = _sum_converted(bucket_qs, "amount_residual", effective_base, rate_map)
            count = bucket_qs.count()
            
            out.append({
                "bucket": label,
                "amount": amount,
                "count": count or 0,
            })
        return out or _empty_aging()

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
                        
                        if atype.startswith("income"):
                            rev += net_credit
                        elif atype.startswith("expense"):
                            exp += net_debit
                            if atype == "expense_direct_cost":
                                cogs += net_debit
                            elif atype in ("expense", "expense_depreciation"):
                                if not (acode.startswith("64") or acode.startswith("67") or acode.startswith("69")):
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
            qs = AccountingService._date_qs(
                AccountingService._base_qs(tenant_id, company_ids), start_date, end_date
            )
            rate_map = _get_rate_map()
            effective_base = base_currency or "XAF"
            
            today = date.today()
            base = qs.filter(
                move_type=move_type,
                invoice_date_due__isnull=False,
                amount_residual__gt=0,
            ).exclude(payment_state__in=["paid", "reversed"])
            
            if bucket == "0-30":
                start_b, end_b = today - timedelta(days=30), today
            elif bucket == "31-60":
                start_b, end_b = today - timedelta(days=60), today - timedelta(days=31)
            elif bucket == "61-90":
                start_b, end_b = today - timedelta(days=90), today - timedelta(days=61)
            elif bucket == "90+":
                start_b, end_b = None, today - timedelta(days=91)
            else:
                raise ValueError(f"Invalid bucket: {bucket}")
                
            bucket_qs = base.filter(invoice_date_due__lte=end_b)
            if start_b is not None:
                bucket_qs = bucket_qs.filter(invoice_date_due__gte=start_b)
                
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
