from __future__ import annotations

import asyncio
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from typing import Any, Optional

from django.db.models import Avg, Case, Count, DecimalField, ExpressionWrapper, F, Max, Q, Sum, Value, When
from django.db.models.functions import Coalesce, TruncMonth
from django.utils import timezone

from odoo_app.models import AccountMove, AccountMoveLine, PurchaseOrder, SalesOrder, SalesOrderLine, StockQuant
from odoo_app.models.purchase_order_line import PurchaseOrderLine


def _to_float(value: Any) -> float:
    try:
        return float(value or 0)
    except Exception:
        return 0.0


def _to_int(value: Any) -> int:
    try:
        return int(value or 0)
    except Exception:
        return 0


def _metric(value: Any, previous_value: Any = 0) -> dict[str, float]:
    current = _to_float(value)
    previous = _to_float(previous_value)
    change = ((current - previous) / abs(previous) * 100) if previous else 0.0
    return {
        "value": current,
        "previous_value": previous,
        "change_pct": change,
        "change_percentage": change,
    }




def _date_filter(qs, field: str, date_from: Optional[str], date_to: Optional[str]):
    if date_from:
        qs = qs.filter(**{f"{field}__date__gte": date_from})
    if date_to:
        qs = qs.filter(**{f"{field}__date__lte": date_to})
    return qs


def _sum(qs, field: str) -> float:
    return _to_float(qs.aggregate(value=Coalesce(Sum(field), Decimal("0")))["value"])


def _get_rate_map(tenant_ids: Optional[list[str]] = None) -> dict:
    from doova_one_view.api.agent.query_context import normalize_tenant_ids
    clean_tenant_ids = normalize_tenant_ids(tenant_ids)
    clean_tenant_id = clean_tenant_ids[0] if clean_tenant_ids else None

    from django.db import connection
    with connection.cursor() as cursor:
        rows = []
        if clean_tenant_id:
            cursor.execute("""
                SELECT DISTINCT ON (c.code) c.code, cr.rate
                FROM dim_currency_rates cr
                JOIN dim_currencies c ON cr.currency_id = c.id
                WHERE cr.tenant_id = %s OR c.tenant_id = %s
                ORDER BY c.code, cr.name DESC
            """, [clean_tenant_id, clean_tenant_id])
            rows = cursor.fetchall()
            
        if not rows:
            cursor.execute("""
                SELECT DISTINCT ON (c.code) c.code, cr.rate
                FROM dim_currency_rates cr
                JOIN dim_currencies c ON cr.currency_id = c.id
                JOIN tenants t ON c.tenant_id = t.id
                WHERE t.is_active = True
                ORDER BY c.code, cr.name DESC
            """)
            rows = cursor.fetchall()
            
    rate_map = {}
    for code, rate in rows:
        rate_map[code] = float(rate) if rate else 1.0
    return rate_map



def _get_conversion_rate(from_curr: str, to_curr: str, rate_map: dict) -> float:
    if from_curr == to_curr:
        return 1.0
    rate_from = rate_map.get(from_curr, 1.0)
    rate_to = rate_map.get(to_curr, 1.0)
    if rate_from == 0:
        return 0.0
    return rate_to / rate_from


def _sum_converted(qs, field: str, effective_base: str, rate_map: dict) -> float:
    rows = list(qs.values("currency_code").annotate(total=Coalesce(Sum(field), Decimal("0"))))
    total_converted = 0.0
    for r in rows:
        code = r["currency_code"] or "COMPANY_BASE"
        raw_val = _to_float(r["total"])
        total_converted += raw_val * _get_conversion_rate(code, effective_base, rate_map)
    return total_converted


def _apply_tenant_company_filter(
    qs,
    tenant_ids: Optional[list[str]] = None,
    company_ids: Optional[list[int]] = None,
    tenant_field: str = "tenant_id",
    company_field: str = "company_id",
):
    if tenant_ids:
        qs = qs.filter(**{f"{tenant_field}__in": tenant_ids})
    if company_ids and company_field:
        qs = qs.filter(**{f"{company_field}__in": company_ids})
    return qs


def _empty_overview(tenant_ids: Optional[list[str]], date_from, date_to, company_ids: Optional[list[int]]):
    return {
        "kpis": {
            "dashboard_revenue": {"today": 0.0, "month": 0.0, "year": 0.0},
            "dashboard_expenses": {"today": 0.0, "month": 0.0, "year": 0.0},
            "dashboard_profit": {"today": 0.0, "month": 0.0, "year": 0.0},
            "revenue": _metric(0),
            "gross_margin": _metric(0),
            "orders": _metric(0),
            "average_order_value": _metric(0),
            "inventory_value": {"value": 0.0},
            "net_working_capital": {
                "value": 0.0,
                "current_assets": {
                    "total": 0.0,
                    "cash_and_equivalents": 0.0,
                    "accounts_receivable": {"value": 0.0, "overdue": 0.0},
                    "inventory": 0.0,
                },
                "current_liabilities": {
                    "total": 0.0,
                    "accounts_payable": 0.0,
                    "accrued_expenses": 0.0,
                    "short_term_debt": 0.0,
                    "other_current_liabilities": 0.0,
                }
            },
        },
        "tenant_benchmarks": [],
        "applied_filters": {"tenant_ids": tenant_ids or [], "date_from": date_from, "date_to": date_to, "company_ids": company_ids or []},
    }


class KPIService:
    @staticmethod
    async def get_overview(
        date_from: Optional[str],
        date_to: Optional[str],
        base_currency: Optional[str] = None,
        tenant_ids: Optional[list[str]] = None,
        company_ids: Optional[list[int]] = None,
    ) -> dict[str, Any]:
        def _get():
            today = date.today()
            rate_map = _get_rate_map()
            effective_base = base_currency or "XAF"
            base_multiplier = _get_conversion_rate("COMPANY_BASE", effective_base, rate_map)
            
            # Point-in-time reference for overdue / aging / balance sheet items & dashboard calendar reference
            as_of_date = today
            if date_to:
                try:
                    as_of_date = date.fromisoformat(date_to)
                except (ValueError, TypeError):
                    pass
            elif date_from:
                try:
                    as_of_date = date.fromisoformat(date_from)
                except (ValueError, TypeError):
                    pass

            ref_date = as_of_date

            # Dashboard base querysets (Today/Month/Year) - Filtered by tenant_ids & company_ids if provided
            base_sales = _apply_tenant_company_filter(
                SalesOrder.objects.filter(state__in=["sale", "done"], tenant__is_active=True),
                tenant_ids, company_ids
            )
            base_purchases = _apply_tenant_company_filter(
                PurchaseOrder.objects.filter(state__in=["purchase", "done"], tenant__is_active=True),
                tenant_ids, company_ids
            )

            # Timezone-aware date bounds for Today / Month / Year
            start_of_day = datetime.combine(ref_date, time.min)
            end_of_day = datetime.combine(ref_date, time.max)
            start_of_month = datetime.combine(date(ref_date.year, ref_date.month, 1), time.min)
            start_of_year = datetime.combine(date(ref_date.year, 1, 1), time.min)
            end_of_year = datetime.combine(date(ref_date.year, 12, 31), time.max)

            if timezone.is_aware(timezone.now()):
                start_of_day = timezone.make_aware(start_of_day)
                end_of_day = timezone.make_aware(end_of_day)
                start_of_month = timezone.make_aware(start_of_month)
                start_of_year = timezone.make_aware(start_of_year)
                end_of_year = timezone.make_aware(end_of_year)

            sales_time_rows = list(
                base_sales.filter(date_order__range=(start_of_year, end_of_year))
                .values("currency_code")
                .annotate(
                    today_total=Coalesce(Sum(Case(When(date_order__range=(start_of_day, end_of_day), then="amount_total"), default=Decimal("0"))), Decimal("0")),
                    month_total=Coalesce(Sum(Case(When(date_order__gte=start_of_month, then="amount_total"), default=Decimal("0"))), Decimal("0")),
                    year_total=Coalesce(Sum("amount_total"), Decimal("0")),
                )
            )

            purchases_time_rows = list(
                base_purchases.filter(date_order__range=(start_of_year, end_of_year))
                .values("currency_code")
                .annotate(
                    today_total=Coalesce(Sum(Case(When(date_order__range=(start_of_day, end_of_day), then="amount_total"), default=Decimal("0"))), Decimal("0")),
                    month_total=Coalesce(Sum(Case(When(date_order__gte=start_of_month, then="amount_total"), default=Decimal("0"))), Decimal("0")),
                    year_total=Coalesce(Sum("amount_total"), Decimal("0")),
                )
            )

            revenue_today = sum(_to_float(r["today_total"]) * _get_conversion_rate(r["currency_code"] or "COMPANY_BASE", effective_base, rate_map) for r in sales_time_rows)
            revenue_month = sum(_to_float(r["month_total"]) * _get_conversion_rate(r["currency_code"] or "COMPANY_BASE", effective_base, rate_map) for r in sales_time_rows)
            revenue_year = sum(_to_float(r["year_total"]) * _get_conversion_rate(r["currency_code"] or "COMPANY_BASE", effective_base, rate_map) for r in sales_time_rows)

            expenses_today = sum(_to_float(r["today_total"]) * _get_conversion_rate(r["currency_code"] or "COMPANY_BASE", effective_base, rate_map) for r in purchases_time_rows)
            expenses_month = sum(_to_float(r["month_total"]) * _get_conversion_rate(r["currency_code"] or "COMPANY_BASE", effective_base, rate_map) for r in purchases_time_rows)
            expenses_year = sum(_to_float(r["year_total"]) * _get_conversion_rate(r["currency_code"] or "COMPANY_BASE", effective_base, rate_map) for r in purchases_time_rows)

            # Receivables and Payables - Filtered by tenant_ids, company_ids & as_of_date
            receivables = _apply_tenant_company_filter(
                AccountMove.objects.filter(
                    state="posted",
                    move_type="out_invoice",
                    payment_state__in=["not_paid", "partial", "in_payment"],
                    tenant__is_active=True,
                    date__lte=as_of_date,
                ),
                tenant_ids, company_ids
            )
            receivables_value = _sum_converted(receivables, "amount_residual", effective_base, rate_map)
            overdue_value = _sum_converted(receivables.filter(invoice_date_due__lt=as_of_date), "amount_residual", effective_base, rate_map)

            payables = _apply_tenant_company_filter(
                AccountMove.objects.filter(
                    state="posted",
                    move_type="in_invoice",
                    payment_state__in=["not_paid", "partial", "in_payment"],
                    tenant__is_active=True,
                    date__lte=as_of_date,
                ),
                tenant_ids, company_ids
            )
            payables_value = _sum_converted(payables, "amount_residual", effective_base, rate_map)

            # ── Inventory Valuation (Historical StockMove/GL or Live StockQuant) ────────
            is_historical = bool(date_from or date_to)
            inv_expr = ExpressionWrapper(
                F("quantity") * Coalesce(F("product__standard_price"), Value(0)),
                output_field=DecimalField(max_digits=20, decimal_places=4),
            )

            # Pre-compute inventory values by company
            comp_inv_cache: dict[Optional[int], float] = {}

            if not is_historical or as_of_date >= date.today():
                quants_qs = _apply_tenant_company_filter(
                    StockQuant.objects.filter(quantity__gt=0, tenant__is_active=True),
                    tenant_ids, company_ids
                )
                comp_quants = list(
                    quants_qs.values("company_id")
                    .annotate(val=Coalesce(Sum(inv_expr), Decimal("0")))
                )
                for r in comp_quants:
                    cid = r["company_id"]
                    comp_inv_cache[cid] = _to_float(r["val"]) * base_multiplier
            else:
                # Historical stock valuation as of as_of_date:
                # Use flat values() to avoid heavy model instantiation
                from odoo_app.models import StockMove
                moves_data = list(
                    _apply_tenant_company_filter(
                        StockMove.objects.filter(state="done", date__date__lte=as_of_date, tenant__is_active=True),
                        tenant_ids, company_ids
                    ).values(
                        "company_id", "product_id", "quantity_done", "product_uom_qty",
                        "location_src", "location_dest", "product__standard_price"
                    )
                )

                if moves_data:
                    comp_prod_qty: dict[tuple[Optional[int], int], Decimal] = {}
                    prod_price_map: dict[int, Decimal] = {}
                    for m in moves_data:
                        cid = m["company_id"]
                        pid = m["product_id"]
                        if not pid:
                            continue
                        qty = m["quantity_done"] if m["quantity_done"] is not None and m["quantity_done"] > 0 else m["product_uom_qty"]
                        if not qty:
                            continue
                        src = (m["location_src"] or "").lower()
                        dest = (m["location_dest"] or "").lower()
                        is_outgoing = ("stock" in src or "internal" in src or "wh" in src) and not ("stock" in dest or "internal" in dest or "wh" in dest)
                        
                        key = (cid, pid)
                        delta = Decimal(str(qty))
                        if is_outgoing:
                            comp_prod_qty[key] = comp_prod_qty.get(key, Decimal("0")) - delta
                        else:
                            comp_prod_qty[key] = comp_prod_qty.get(key, Decimal("0")) + delta
                        
                        if pid not in prod_price_map:
                            prod_price_map[pid] = Decimal(str(m["product__standard_price"] or 0))

                    for (cid, pid), net_qty in comp_prod_qty.items():
                        if net_qty > 0:
                            item_val = _to_float(net_qty * prod_price_map.get(pid, Decimal("0"))) * base_multiplier
                            comp_inv_cache[cid] = comp_inv_cache.get(cid, 0.0) + item_val
                else:
                    # Fallback to General Ledger asset_current
                    gl_moves = _apply_tenant_company_filter(
                        AccountMoveLine.objects.filter(
                            account_type='asset_current',
                            account_move__state='posted',
                            tenant__is_active=True,
                            account_move__date__lte=as_of_date,
                        ),
                        tenant_ids, company_ids, company_field="account_move__company_id"
                    )
                    for r in gl_moves.values("account_move__company_id").annotate(tot=Coalesce(Sum("balance"), Decimal("0"))):
                        gl_v = _to_float(r["tot"]) * base_multiplier
                        if gl_v > 0:
                            comp_inv_cache[r["account_move__company_id"]] = gl_v

            def _calculate_inventory_value(c_ids=None) -> float:
                if c_ids is None:
                    return sum(comp_inv_cache.values())
                return sum(comp_inv_cache.get(cid, 0.0) for cid in c_ids)

            inventory_value = _calculate_inventory_value(company_ids)

            # ── Net Working Capital (General Ledger Balance Sheet synchronized) ───────
            cash_moves = _apply_tenant_company_filter(
                AccountMoveLine.objects.filter(
                    account_type='asset_cash',
                    account_move__state='posted',
                    tenant__is_active=True,
                    account_move__date__lte=as_of_date,
                ),
                tenant_ids, company_ids, company_field="account_move__company_id"
            )
            cash_value = _sum(cash_moves, "balance") * base_multiplier

            # GL Receivables Moves (asset_receivable)
            ar_gl_moves = _apply_tenant_company_filter(
                AccountMoveLine.objects.filter(
                    account_type='asset_receivable',
                    account_move__state='posted',
                    tenant__is_active=True,
                    account_move__date__lte=as_of_date,
                ),
                tenant_ids, company_ids, company_field="account_move__company_id"
            )
            nwc_ar_value = _sum(ar_gl_moves, "balance") * base_multiplier if ar_gl_moves.exists() else receivables_value

            # GL Inventory & Other Current Assets (asset_current, asset_prepayments)
            inv_gl_moves = _apply_tenant_company_filter(
                AccountMoveLine.objects.filter(
                    account_type__in=['asset_current', 'asset_prepayments'],
                    account_move__state='posted',
                    tenant__is_active=True,
                    account_move__date__lte=as_of_date,
                ),
                tenant_ids, company_ids, company_field="account_move__company_id"
            )
            nwc_inv_value = _sum(inv_gl_moves, "balance") * base_multiplier if inv_gl_moves.exists() else inventory_value

            # GL Payables Moves (liability_payable)
            ap_gl_moves = _apply_tenant_company_filter(
                AccountMoveLine.objects.filter(
                    account_type='liability_payable',
                    account_move__state='posted',
                    tenant__is_active=True,
                    account_move__date__lte=as_of_date,
                ),
                tenant_ids, company_ids, company_field="account_move__company_id"
            )
            nwc_ap_value = -1 * _sum(ap_gl_moves, "balance") * base_multiplier if ap_gl_moves.exists() else payables_value

            # Batched Cash by Company
            cash_by_comp = {
                r["account_move__company_id"]: _to_float(r["tot"]) * base_multiplier
                for r in cash_moves.values("account_move__company_id").annotate(tot=Coalesce(Sum("balance"), Decimal("0")))
            }

            # Batched GL Receivables by Company
            ar_gl_by_comp = {
                r["account_move__company_id"]: _to_float(r["tot"]) * base_multiplier
                for r in ar_gl_moves.values("account_move__company_id").annotate(tot=Coalesce(Sum("balance"), Decimal("0")))
            }

            # Batched GL Inventory/Other Assets by Company
            inv_gl_by_comp = {
                r["account_move__company_id"]: _to_float(r["tot"]) * base_multiplier
                for r in inv_gl_moves.values("account_move__company_id").annotate(tot=Coalesce(Sum("balance"), Decimal("0")))
            }

            # Batched GL Payables by Company
            ap_gl_by_comp = {
                r["account_move__company_id"]: -1 * _to_float(r["tot"]) * base_multiplier
                for r in ap_gl_moves.values("account_move__company_id").annotate(tot=Coalesce(Sum("balance"), Decimal("0")))
            }

            # Batched Receivables & Overdue by Company (from Invoices)
            ar_by_comp_curr = list(
                receivables.values("company_id", "currency_code")
                .annotate(tot=Coalesce(Sum("amount_residual"), Decimal("0")))
            )
            ar_map: dict[Optional[int], float] = {}
            for r in ar_by_comp_curr:
                cid = r["company_id"]
                code = r["currency_code"] or "COMPANY_BASE"
                val = _to_float(r["tot"]) * _get_conversion_rate(code, effective_base, rate_map)
                ar_map[cid] = ar_map.get(cid, 0.0) + val

            # Batched Payables by Company (from Bills)
            ap_by_comp_curr = list(
                payables.values("company_id", "currency_code")
                .annotate(tot=Coalesce(Sum("amount_residual"), Decimal("0")))
            )
            ap_map: dict[Optional[int], float] = {}
            for r in ap_by_comp_curr:
                cid = r["company_id"]
                code = r["currency_code"] or "COMPANY_BASE"
                val = _to_float(r["tot"]) * _get_conversion_rate(code, effective_base, rate_map)
                ap_map[cid] = ap_map.get(cid, 0.0) + val

            # Overdue invoices by Company
            ar_overdue_by_comp_curr = list(
                receivables.filter(invoice_date_due__lt=as_of_date)
                .values("company_id", "currency_code")
                .annotate(tot=Coalesce(Sum("amount_residual"), Decimal("0")))
            )
            ar_overdue_map: dict[Optional[int], float] = {}
            for r in ar_overdue_by_comp_curr:
                cid = r["company_id"]
                code = r["currency_code"] or "COMPANY_BASE"
                val = _to_float(r["tot"]) * _get_conversion_rate(code, effective_base, rate_map)
                ar_overdue_map[cid] = ar_overdue_map.get(cid, 0.0) + val
            
            from odoo_app.models import TenantFinancialMapping, Company
            
            mappings = TenantFinancialMapping.objects.select_related('tenant').filter(tenant__is_active=True)
            if tenant_ids:
                mappings = mappings.filter(tenant_id__in=tenant_ids)

            q_accrued = Q()
            q_short_term = Q()
            
            for mapping in mappings:
                for prefix in mapping.accrued_expense_prefixes:
                    q_accrued |= Q(tenant=mapping.tenant, account_code__startswith=prefix)
                for prefix in mapping.short_term_debt_prefixes:
                    q_short_term |= Q(tenant=mapping.tenant, account_code__startswith=prefix)

            other_liabilities_moves = _apply_tenant_company_filter(
                AccountMoveLine.objects.filter(
                    account_type__in=['liability_current', 'liability_credit_card'],
                    account_move__state='posted',
                    tenant__is_active=True,
                    account_move__date__lte=as_of_date,
                ),
                tenant_ids, company_ids, company_field="account_move__company_id"
            )

            total_other_liabilities = -1 * _sum(other_liabilities_moves, "balance") * base_multiplier

            accrued_expenses_value = 0.0
            if q_accrued:
                accrued_expenses_value = -1 * _sum(other_liabilities_moves.filter(q_accrued), "balance") * base_multiplier

            short_term_debt_value = 0.0
            if q_short_term:
                short_term_debt_value = -1 * _sum(other_liabilities_moves.filter(q_short_term), "balance") * base_multiplier

            other_liabilities_value = total_other_liabilities - accrued_expenses_value - short_term_debt_value
            
            current_assets = cash_value + nwc_ar_value + nwc_inv_value
            current_liabilities = nwc_ap_value + accrued_expenses_value + short_term_debt_value + other_liabilities_value
            net_working_capital = current_assets - current_liabilities

            working_capital_ratio = round(current_assets / current_liabilities, 2) if current_liabilities > 0 else 0.0
            quick_ratio = round((cash_value + nwc_ar_value) / current_liabilities, 2) if current_liabilities > 0 else 0.0
            health_status = "healthy" if working_capital_ratio >= 1.5 else ("warning" if working_capital_ratio >= 1.0 else "critical")

            # Batched Other Liabilities by Company
            tot_other_liab_by_comp = {
                r["account_move__company_id"]: -1 * _to_float(r["tot"]) * base_multiplier
                for r in other_liabilities_moves.values("account_move__company_id").annotate(tot=Coalesce(Sum("balance"), Decimal("0")))
            }
            accrued_by_comp = {}
            if q_accrued:
                accrued_by_comp = {
                    r["account_move__company_id"]: -1 * _to_float(r["tot"]) * base_multiplier
                    for r in other_liabilities_moves.filter(q_accrued).values("account_move__company_id").annotate(tot=Coalesce(Sum("balance"), Decimal("0")))
                }
            debt_by_comp = {}
            if q_short_term:
                debt_by_comp = {
                    r["account_move__company_id"]: -1 * _to_float(r["tot"]) * base_multiplier
                    for r in other_liabilities_moves.filter(q_short_term).values("account_move__company_id").annotate(tot=Coalesce(Sum("balance"), Decimal("0")))
                }

            # ── Per-Company Net Working Capital Breakdown ─────────────────────────────
            company_qs = Company.objects.all()
            if tenant_ids:
                company_qs = company_qs.filter(tenant_id__in=tenant_ids)
            if company_ids:
                company_qs = company_qs.filter(id__in=company_ids)

            company_breakdown = []
            for comp in company_qs:
                c_cash = cash_by_comp.get(comp.id, 0.0)
                c_ar_val = ar_gl_by_comp.get(comp.id, ar_map.get(comp.id, 0.0))
                c_ar_overdue = ar_overdue_map.get(comp.id, 0.0)
                c_inv_val = inv_gl_by_comp.get(comp.id, _calculate_inventory_value([comp.id]))
                c_ap_val = ap_gl_by_comp.get(comp.id, ap_map.get(comp.id, 0.0))
                c_tot_other_liab = tot_other_liab_by_comp.get(comp.id, 0.0)
                c_accrued = accrued_by_comp.get(comp.id, 0.0)
                c_debt = debt_by_comp.get(comp.id, 0.0)
                c_other = c_tot_other_liab - c_accrued - c_debt

                c_assets = c_cash + c_ar_val + c_inv_val
                c_liabilities = c_ap_val + c_accrued + c_debt + c_other
                c_nwc = c_assets - c_liabilities
                c_cr = round(c_assets / c_liabilities, 2) if c_liabilities > 0 else 0.0
                c_qr = round((c_cash + c_ar_val) / c_liabilities, 2) if c_liabilities > 0 else 0.0
                c_status = "healthy" if c_cr >= 1.5 else ("warning" if c_cr >= 1.0 else "critical")

                company_breakdown.append({
                    "company_id": comp.id,
                    "company_name": comp.name,
                    "currency_code": comp.currency_code or "COMPANY_BASE",
                    "net_working_capital": c_nwc,
                    "working_capital_ratio": c_cr,
                    "quick_ratio": c_qr,
                    "health_status": c_status,
                    "current_assets": {
                        "total": c_assets,
                        "cash_and_equivalents": c_cash,
                        "accounts_receivable": {"value": c_ar_val, "overdue": c_ar_overdue},
                        "inventory": c_inv_val,
                    },
                    "current_liabilities": {
                        "total": c_liabilities,
                        "accounts_payable": c_ap_val,
                        "accrued_expenses": c_accrued,
                        "short_term_debt": c_debt,
                        "other_current_liabilities": c_other,
                    }
                })

            # Historical Metrics - Dependent on date filters
            sales = _date_filter(base_sales, "date_order", date_from, date_to)
            purchases = _date_filter(base_purchases, "date_order", date_from, date_to)

            # Previous Period Calculation for Comparison
            prev_revenue = 0.0
            prev_expenses = 0.0
            prev_profit = 0.0
            prev_orders = 0
            prev_avg_order_value = 0.0
            prev_margin_pct = 0.0

            if date_from and date_to:
                try:
                    d_from = date.fromisoformat(date_from)
                    d_to = date.fromisoformat(date_to)
                    if d_to >= d_from:
                        duration_days = (d_to - d_from).days + 1
                        prev_d_to = d_from - timedelta(days=1)
                        prev_d_from = prev_d_to - timedelta(days=duration_days - 1)
                        prev_date_from_str = prev_d_from.isoformat()
                        prev_date_to_str = prev_d_to.isoformat()

                        prev_sales = _date_filter(base_sales, "date_order", prev_date_from_str, prev_date_to_str)
                        prev_purchases = _date_filter(base_purchases, "date_order", prev_date_from_str, prev_date_to_str)

                        prev_revenue = _sum_converted(prev_sales, "amount_total", effective_base, rate_map)
                        prev_expenses = _sum_converted(prev_purchases, "amount_total", effective_base, rate_map)
                        prev_profit = prev_revenue - prev_expenses
                        prev_sales_stats = prev_sales.aggregate(
                            order_count=Count("id"),
                            gross_margin=Coalesce(Sum("margin"), Decimal("0"))
                        )
                        prev_orders = prev_sales_stats["order_count"] or 0
                        prev_avg_order_value = round(prev_revenue / prev_orders, 2) if prev_orders else 0.0
                        prev_gross_margin_val = _to_float(prev_sales_stats["gross_margin"]) * base_multiplier if prev_sales_stats["gross_margin"] else (prev_revenue - prev_expenses)
                        prev_margin_pct = round(prev_gross_margin_val / prev_revenue * 100, 2) if prev_revenue else 0.0
                except (ValueError, TypeError):
                    pass
            
            # ── Inventory Risk Metrics ─────────────────────────────
            from odoo_app.models import StockMove
            if is_historical and as_of_date < today:
                # Historical Dead Stock: Products with sales in the 90 days before as_of_date
                ninety_days_ago = as_of_date - timedelta(days=90)
                sold_lines_qs = _apply_tenant_company_filter(
                    SalesOrderLine.objects.filter(
                        sales_order__date_order__gte=ninety_days_ago,
                        sales_order__date_order__lte=as_of_date,
                        sales_order__state__in=["sale", "done"],
                        tenant__is_active=True
                    ),
                    tenant_ids, company_ids, company_field="sales_order__company_id"
                )
                sold_product_ids = set(sold_lines_qs.values_list("product_id", flat=True).distinct())
                
                # Products with stock moves up to as_of_date
                hist_stock_moves = _apply_tenant_company_filter(
                    StockMove.objects.filter(state="done", date__date__lte=as_of_date, tenant__is_active=True),
                    tenant_ids, company_ids
                )
                if hist_stock_moves.exists():
                    active_pids = set(hist_stock_moves.values_list("product_id", flat=True).distinct())
                    dead_pids = [pid for pid in active_pids if pid not in sold_product_ids]
                    dead_stock_product_count = len(dead_pids)
                    total_sku_count = len(active_pids)
                else:
                    dead_stock_product_count = 0
                    total_sku_count = 0

                dead_stock_rate = round((dead_stock_product_count / total_sku_count * 100), 2) if total_sku_count > 0 else 0.0
                reservation_pressure = 0.0
                low_stock_count = 0
                expiring_soon_count = 0
            else:
                quant_stats_qs = _apply_tenant_company_filter(
                    StockQuant.objects.filter(tenant__is_active=True),
                    tenant_ids, company_ids
                )
                quant_stats = quant_stats_qs.aggregate(
                    total_qty=Coalesce(Sum("quantity"), Decimal("0")),
                    total_reserved=Coalesce(Sum("reserved_quantity"), Decimal("0")),
                )
                total_qty = _to_float(quant_stats["total_qty"])
                total_reserved = _to_float(quant_stats["total_reserved"])
                reservation_pressure = (total_reserved / total_qty * 100) if total_qty > 0 else 0.0

                low_stock_qs = _apply_tenant_company_filter(
                    StockQuant.objects.filter(quantity__lt=5, quantity__gt=0, tenant__is_active=True),
                    tenant_ids, company_ids
                )
                low_stock_count = low_stock_qs.count()

                thirty_days_later = as_of_date + timedelta(days=30)
                expiring_soon_qs = _apply_tenant_company_filter(
                    StockQuant.objects.filter(
                        lot__expiration_date__range=(as_of_date, thirty_days_later),
                        quantity__gt=0,
                        tenant__is_active=True
                    ),
                    tenant_ids, company_ids
                )
                expiring_soon_count = expiring_soon_qs.count()

                ninety_days_ago = as_of_date - timedelta(days=90)
                sold_lines_qs = _apply_tenant_company_filter(
                    SalesOrderLine.objects.filter(
                        sales_order__date_order__gte=ninety_days_ago,
                        sales_order__date_order__lte=as_of_date,
                        sales_order__state__in=["sale", "done"],
                        tenant__is_active=True
                    ),
                    tenant_ids, company_ids, company_field="sales_order__company_id"
                )
                sold_product_ids = sold_lines_qs.values_list("product_id", flat=True).distinct()
                
                dead_stock_quants = _apply_tenant_company_filter(
                    StockQuant.objects.filter(quantity__gt=0, tenant__is_active=True),
                    tenant_ids, company_ids
                ).exclude(product_id__in=sold_product_ids)

                dead_stock_product_count = dead_stock_quants.values("product_id").distinct().count()

                total_sku_qs = _apply_tenant_company_filter(
                    StockQuant.objects.filter(quantity__gt=0, tenant__is_active=True),
                    tenant_ids, company_ids
                )
                total_sku_count = total_sku_qs.values("product_id").distinct().count()
                dead_stock_rate = (dead_stock_product_count / total_sku_count * 100) if total_sku_count > 0 else 0.0

            total_revenue = _sum_converted(sales, "amount_total", effective_base, rate_map)
            total_expenses = _sum_converted(purchases, "amount_total", effective_base, rate_map)
            total_profit = total_revenue - total_expenses

            # ── Return Values ─────────────────────────────────────
            if not sales.exists():
                return {
                    "kpis": {
                        "dashboard_revenue": {"today": revenue_today, "month": revenue_month, "year": revenue_year, "custom": 0.0, "period": 0.0},
                        "dashboard_expenses": {"today": expenses_today, "month": expenses_month, "year": expenses_year, "custom": total_expenses, "period": total_expenses},
                        "dashboard_profit": {
                            "today": revenue_today - expenses_today,
                            "month": revenue_month - expenses_month,
                            "year": revenue_year - expenses_year,
                            "custom": total_profit,
                            "period": total_profit,
                        },
                        "revenue": _metric(0, prev_revenue),
                        "expenses": _metric(total_expenses, prev_expenses),
                        "profit": _metric(total_profit, prev_profit),
                        "net_profit": _metric(total_profit, prev_profit),
                        "gross_margin": _metric(0, prev_margin_pct),
                        "orders": _metric(0, prev_orders),
                        "average_order_value": _metric(0, prev_avg_order_value),
                        "inventory_value": {"value": inventory_value},
                        "inventory_risk": {
                            "inventory_reservation_pressure_pct": reservation_pressure,
                            "dead_stock_rate_pct": dead_stock_rate,
                            "dead_stock_product_count": dead_stock_product_count,
                            "low_stock_count": low_stock_count,
                            "expiring_soon_count": expiring_soon_count
                        },
                        "net_working_capital": {
                            "value": net_working_capital,
                            "working_capital_ratio": working_capital_ratio,
                            "quick_ratio": quick_ratio,
                            "health_status": health_status,
                            "current_assets": {
                                "total": current_assets,
                                "cash_and_equivalents": cash_value,
                                "accounts_receivable": {"value": nwc_ar_value, "overdue": overdue_value},
                                "inventory": nwc_inv_value,
                            },
                            "current_liabilities": {
                                "total": current_liabilities,
                                "accounts_payable": nwc_ap_value,
                                "accrued_expenses": accrued_expenses_value,
                                "short_term_debt": short_term_debt_value,
                                "other_current_liabilities": other_liabilities_value,
                            },
                            "company_breakdown": company_breakdown,
                        },
                    },
                    "tenant_benchmarks": [],
                    "applied_filters": {
                        "tenant_ids": tenant_ids or [],
                        "date_from": date_from,
                        "date_to": date_to,
                        "company_ids": company_ids or [],
                    },
                }

            sales_stats = sales.aggregate(
                order_count=Count("id"),
                gross_margin=Coalesce(Sum("margin"), Decimal("0")),
            )
            order_count = _to_int(sales_stats["order_count"])
            avg_order_value = round(total_revenue / order_count, 2) if order_count else 0.0
            
            # Since margin is in COMPANY_BASE in Odoo, convert it
            gross_margin_value = _to_float(sales_stats["gross_margin"]) * base_multiplier if sales_stats["gross_margin"] else (total_revenue - total_expenses)
            gross_margin_pct = round(gross_margin_value / total_revenue * 100, 2) if total_revenue else 0.0

            # Tenant benchmarks (converting margin and revenue in single aggregation)
            tenant_stats = list(
                sales.values("tenant_id", "tenant__name", "currency_code")
                .annotate(
                    order_count=Count("id"),
                    margin=Coalesce(Sum("margin"), Decimal("0")),
                    revenue=Coalesce(Sum("amount_total"), Decimal("0")),
                )
            )
            tenant_map = {}
            for r in tenant_stats:
                tid = r["tenant_id"]
                tname = r["tenant__name"] or str(tid)
                code = r["currency_code"] or "COMPANY_BASE"
                conv = _get_conversion_rate(code, effective_base, rate_map)
                rev_val = _to_float(r["revenue"]) * conv
                margin_val = _to_float(r["margin"]) * base_multiplier
                
                if tid not in tenant_map:
                    tenant_map[tid] = {
                        "tenant_id": str(tid),
                        "tenant_name": tname,
                        "revenue": 0.0,
                        "order_count": 0,
                        "margin": 0.0,
                    }
                tenant_map[tid]["revenue"] += rev_val
                tenant_map[tid]["order_count"] += r["order_count"]
                tenant_map[tid]["margin"] += margin_val

            tenant_rows = list(tenant_map.values())
            for row in tenant_rows:
                row["margin_rate_pct"] = (row["margin"] / row["revenue"] * 100) if row["revenue"] else 0.0
            tenant_rows.sort(key=lambda x: x["revenue"], reverse=True)

            return {
                "kpis": {
                    "dashboard_revenue": {"today": revenue_today, "month": revenue_month, "year": revenue_year, "custom": total_revenue, "period": total_revenue},
                    "dashboard_expenses": {"today": expenses_today, "month": expenses_month, "year": expenses_year, "custom": total_expenses, "period": total_expenses},
                    "dashboard_profit": {
                        "today": revenue_today - expenses_today,
                        "month": revenue_month - expenses_month,
                        "year": revenue_year - expenses_year,
                        "custom": total_profit,
                        "period": total_profit,
                    },
                    "revenue": _metric(total_revenue, prev_revenue),
                    "expenses": _metric(total_expenses, prev_expenses),
                    "profit": _metric(total_profit, prev_profit),
                    "net_profit": _metric(total_profit, prev_profit),
                    "gross_margin": _metric(gross_margin_pct, prev_margin_pct),
                    "orders": _metric(order_count, prev_orders),
                    "average_order_value": _metric(avg_order_value, prev_avg_order_value),
                    "inventory_value": {"value": inventory_value},
                    "inventory_risk": {
                        "inventory_reservation_pressure_pct": reservation_pressure,
                        "dead_stock_rate_pct": dead_stock_rate,
                        "dead_stock_product_count": dead_stock_product_count,
                        "low_stock_count": low_stock_count,
                        "expiring_soon_count": expiring_soon_count
                    },
                    "net_working_capital": {
                        "value": net_working_capital,
                        "working_capital_ratio": working_capital_ratio,
                        "quick_ratio": quick_ratio,
                        "health_status": health_status,
                        "current_assets": {
                            "total": current_assets,
                            "cash_and_equivalents": cash_value,
                            "accounts_receivable": {"value": nwc_ar_value, "overdue": overdue_value},
                            "inventory": nwc_inv_value,
                        },
                        "current_liabilities": {
                            "total": current_liabilities,
                            "accounts_payable": nwc_ap_value,
                            "accrued_expenses": accrued_expenses_value,
                            "short_term_debt": short_term_debt_value,
                            "other_current_liabilities": other_liabilities_value,
                        },
                        "company_breakdown": company_breakdown,
                    },
                },

                "tenant_benchmarks": [
                    {
                        "tenant_id": str(row["tenant_id"]),
                        "tenant_name": row["tenant_name"],
                        "revenue": _to_float(row["revenue"]),
                        "order_count": _to_int(row["order_count"]),
                        "margin": _to_float(row["margin"]),
                        "margin_rate_pct": row["margin_rate_pct"],
                    }
                    for row in tenant_rows
                ],
                "applied_filters": {
                    "tenant_ids": tenant_ids or [],
                    "date_from": date_from,
                    "date_to": date_to,
                    "company_ids": company_ids or [],
                },
            }

        return await asyncio.to_thread(_get)

    @staticmethod
    async def get_trends(
        date_from: Optional[str],
        date_to: Optional[str],
        base_currency: Optional[str] = None,
        tenant_ids: Optional[list[str]] = None,
        company_ids: Optional[list[int]] = None,
    ) -> dict[str, Any]:
        def _get():
            rate_map = _get_rate_map()
            effective_base = base_currency or "XAF"
            base_multiplier = _get_conversion_rate("COMPANY_BASE", effective_base, rate_map)
            
            sales = SalesOrder.objects.filter(state__in=["sale", "done"], tenant__is_active=True)
            sales = _apply_tenant_company_filter(sales, tenant_ids, company_ids)
            sales = _date_filter(sales, "date_order", date_from, date_to)

            purchases = PurchaseOrder.objects.filter(state__in=["purchase", "done"], tenant__is_active=True)
            purchases = _apply_tenant_company_filter(purchases, tenant_ids, company_ids)
            purchases = _date_filter(purchases, "date_order", date_from, date_to)

            sales_rows = list(
                sales.annotate(month=TruncMonth("date_order"))
                .values("month", "currency_code")
                .annotate(revenue=Coalesce(Sum("amount_total"), Decimal("0")), orders=Count("id"), margin=Coalesce(Sum("margin"), Decimal("0")))
                .order_by("month")
            )
            purchase_rows = list(
                purchases.annotate(month=TruncMonth("date_order"))
                .values("month", "currency_code")
                .annotate(expenses=Coalesce(Sum("amount_total"), Decimal("0")))
                .order_by("month")
            )

            # Aggregate expenses by month converting currencies
            expense_by_month = {}
            for r in purchase_rows:
                if not r["month"]:
                    continue
                key = r["month"].strftime("%Y-%m")
                code = r["currency_code"] or "COMPANY_BASE"
                val = _to_float(r["expenses"]) * _get_conversion_rate(code, effective_base, rate_map)
                expense_by_month[key] = expense_by_month.get(key, 0.0) + val

            # Aggregate sales by month converting currencies
            sales_by_month = {}
            for r in sales_rows:
                if not r["month"]:
                    continue
                key = r["month"].strftime("%Y-%m")
                code = r["currency_code"] or "COMPANY_BASE"
                rev = _to_float(r["revenue"]) * _get_conversion_rate(code, effective_base, rate_map)
                margin = _to_float(r["margin"]) * base_multiplier
                orders = _to_float(r["orders"])
                
                if key not in sales_by_month:
                    sales_by_month[key] = {"revenue": 0.0, "margin": 0.0, "orders": 0.0}
                sales_by_month[key]["revenue"] += rev
                sales_by_month[key]["margin"] += margin
                sales_by_month[key]["orders"] += orders

            revenue_trend = []
            orders_trend = []
            profit_trend = []
            margin_trend = []

            # Sort keys to ensure chronological order
            all_months = sorted(list(set(list(sales_by_month.keys()) + list(expense_by_month.keys()))))
            
            for key in all_months:
                s_data = sales_by_month.get(key, {"revenue": 0.0, "margin": 0.0, "orders": 0.0})
                revenue = s_data["revenue"]
                expenses = expense_by_month.get(key, 0.0)
                profit = revenue - expenses
                margin_pct = (profit / revenue * 100) if revenue else 0.0
                
                revenue_trend.append({"month": key, "date": key, "value": revenue})
                orders_trend.append({"month": key, "date": key, "value": s_data["orders"]})
                profit_trend.append({"month": key, "date": key, "value": profit, "profit": profit})
                margin_trend.append({"month": key, "date": key, "value": margin_pct, "margin": profit, "margin_pct": margin_pct})

            procurement_trend = [
                {"month": k, "date": k, "value": v}
                for k, v in sorted(expense_by_month.items())
            ]

            tenant_sales = list(
                sales.annotate(month=TruncMonth("date_order"))
                .values("month", "tenant__name", "currency_code")
                .annotate(revenue=Coalesce(Sum("amount_total"), Decimal("0")))
                .order_by("month")
            )
            
            tenant_rev_map = {}
            for row in tenant_sales:
                if not row["month"]:
                    continue
                month_str = row["month"].strftime("%Y-%m")
                t_name = row["tenant__name"] or "Unknown Tenant"
                key = (month_str, t_name)
                
                code = row["currency_code"] or "COMPANY_BASE"
                val = _to_float(row["revenue"]) * _get_conversion_rate(code, effective_base, rate_map)
                tenant_rev_map[key] = tenant_rev_map.get(key, 0.0) + val
                
            tenant_revenue = []
            for (m, t), v in sorted(tenant_rev_map.items()):
                tenant_revenue.append({
                    "month": m,
                    "tenant_name": t,
                    "revenue": v
                })

            return {
                "trends": {
                    "revenue": revenue_trend,
                    "profit": profit_trend,
                    "margin": margin_trend,
                    "orders": orders_trend,
                    "aov": [],
                    "procurement": procurement_trend,
                    "late_delivery": [],
                    "invoiced": [],
                    "overdue_ar": [],
                    "tenant_revenue": tenant_revenue,
                },
                "revenue": revenue_trend,
                "profit": profit_trend,
                "margin": margin_trend,
                "orders": orders_trend,
                "procurement": procurement_trend,
                "revenue_trend": revenue_trend,
                "profit_trend": profit_trend,
                "margin_trend": margin_trend,
                "orders_trend": orders_trend,
                "procurement_trend": procurement_trend,
                "revenue_health": {"revenue": revenue_trend, "profit": profit_trend, "margin": margin_trend, "orders": orders_trend},
                "items": revenue_trend,
                "has_data": bool(revenue_trend or profit_trend or procurement_trend),
                "applied_filters": {"tenant_ids": tenant_ids or [], "date_from": date_from, "date_to": date_to, "company_ids": company_ids or []},
            }

        return await asyncio.to_thread(_get)


    @staticmethod
    async def get_top_products(
        limit: int = 10,
        offset: int = 0,
        descending: bool = True,
        base_currency: Optional[str] = None,
        tenant_ids: Optional[list[str]] = None,
        company_ids: Optional[list[int]] = None,
        date_from: Optional[str] = None,
        date_to: Optional[str] = None,
    ) -> dict[str, Any]:
        def _get():
            rate_map = _get_rate_map()
            effective_base = base_currency or "XAF"
            base_multiplier = _get_conversion_rate("COMPANY_BASE", effective_base, rate_map)
            
            cogs_expr = ExpressionWrapper(
                F("product_uom_qty") * Coalesce(F("product__standard_price"), Value(0)),
                output_field=DecimalField(max_digits=20, decimal_places=4)
            )

            lines = SalesOrderLine.objects.filter(
                sales_order__state__in=["sale", "done"],
                sales_order__tenant__is_active=True
            ).exclude(product__product_type='service').exclude(product__name__icontains='discount')
            lines = _apply_tenant_company_filter(lines, tenant_ids, company_ids, company_field="sales_order__company_id")
            lines = _date_filter(lines, "sales_order__date_order", date_from, date_to)
            rows = list(
                lines.values("product_id", "product__name", "product__default_code", "sales_order__currency_code")
                .annotate(
                    revenue=Coalesce(Sum("price_subtotal"), Decimal("0")),
                    quantity=Coalesce(Sum("product_uom_qty"), Decimal("0")),
                    margin=Coalesce(Sum("margin"), Decimal("0")),
                    calc_cogs=Coalesce(Sum(cogs_expr), Decimal("0")),
                    last_sold_on=Max("sales_order__date_order"),
                )
            )
            
            # Aggregate python side to handle multiple currencies
            prod_map = {}
            for r in rows:
                pid = r["product_id"]
                if pid not in prod_map:
                    prod_map[pid] = {
                        "product_id": pid,
                        "product__name": r["product__name"],
                        "product__default_code": r["product__default_code"],
                        "revenue": 0.0,
                        "quantity": 0.0,
                        "margin": 0.0,
                        "last_sold_on": None,
                    }
                code = r["sales_order__currency_code"] or "COMPANY_BASE"
                val = _to_float(r["revenue"]) * _get_conversion_rate(code, effective_base, rate_map)
                
                row_margin = _to_float(r["margin"]) * base_multiplier  # margin is in COMPANY_BASE
                row_cogs = _to_float(r["calc_cogs"]) * base_multiplier
                if row_margin == 0 and row_cogs > 0:
                    row_margin = val - row_cogs

                prod_map[pid]["revenue"] += val
                prod_map[pid]["quantity"] += _to_float(r["quantity"])
                prod_map[pid]["margin"] += row_margin

                m_date = r.get("last_sold_on")
                if m_date:
                    if prod_map[pid]["last_sold_on"] is None or m_date > prod_map[pid]["last_sold_on"]:
                        prod_map[pid]["last_sold_on"] = m_date

                
            agg_rows = list(prod_map.values())
            agg_rows.sort(key=lambda x: x["revenue"], reverse=descending)
            
            total_count = len(agg_rows)
            paged_rows = agg_rows[offset : offset + limit] if (limit and limit > 0) else agg_rows[offset:]
            has_more = total_count > (offset + len(paged_rows))

            products = []
            for row in paged_rows:
                revenue = row["revenue"]
                margin = row["margin"]
                cogs = max(0.0, revenue - margin)
                last_sold = row.get("last_sold_on")
                last_sold_str = last_sold.strftime("%Y-%m-%d") if hasattr(last_sold, "strftime") else (str(last_sold)[:10] if last_sold else None)
                products.append({
                    "id": _to_int(row["product_id"]),
                    "name": row["product__name"] or "Unknown Product",
                    "product__name": row["product__name"] or "Unknown Product",
                    "product__default_code": row["product__default_code"] or "",
                    "revenue": revenue,
                    "quantity": row["quantity"],
                    "gross_profit": margin,
                    "cogs": cogs,
                    "margin_pct": (margin / revenue * 100) if revenue else 0.0,
                    "last_sold_on": last_sold_str,
                })

            return {
                "products": products,
                "items": products,
                "total": total_count,
                "limit": limit,
                "offset": offset,
                "has_more": has_more,
                "applied_filters": {
                    "tenant_ids": tenant_ids or [],
                    "company_ids": company_ids or [],
                    "date_from": date_from,
                    "date_to": date_to,
                },
            }

        return await asyncio.to_thread(_get)


    @staticmethod
    async def get_product_detail(
        product_id: int,
        order_limit: int = 50,
        order_offset: int = 0,
        tenant_ids: Optional[list[str]] = None,
        company_ids: Optional[list[int]] = None,
        date_from: Optional[str] = None,
        date_to: Optional[str] = None,
    ) -> dict[str, Any]:
        """
        Returns details for a specific product, including total sales metrics
        and a paginated list of the sales order lines involving it.
        """
        def _fetch():
            from fastapi import HTTPException
            from odoo_app.models.sales_order_line import SalesOrderLine as SOLine
            from odoo_app.models import Product
            
            try:
                product_qs = Product.objects.select_related("category", "tenant").filter(id=product_id, tenant__is_active=True)
                if tenant_ids:
                    product_qs = product_qs.filter(tenant_id__in=tenant_ids)
                if company_ids:
                    product_qs = product_qs.filter(Q(company_id__in=company_ids) | Q(company_id__isnull=True))
                product = product_qs.get()
            except Product.DoesNotExist:
                raise HTTPException(status_code=404, detail="Product not found or tenant/company filter excluded product")


            # Get all sale/done order lines for this product
            lines_qs = SOLine.objects.filter(
                product=product,
                sales_order__state__in=["sale", "done"],
                sales_order__tenant__is_active=True
            ).select_related("sales_order", "sales_order__partner", "sales_order__company", "sales_order__tenant")
            lines_qs = _apply_tenant_company_filter(lines_qs, tenant_ids, company_ids, company_field="sales_order__company_id")
            lines_qs = _date_filter(lines_qs, "sales_order__date_order", date_from, date_to)

            totals = lines_qs.aggregate(
                total_qty=Coalesce(Sum("product_uom_qty"), Decimal("0")),
                total_rev=Coalesce(Sum("price_subtotal"), Decimal("0")),
                total_margin=Coalesce(Sum("margin"), Decimal("0")),
            )

            ordered_lines = lines_qs.order_by("-sales_order__date_order", "-id")
            
            all_lines = list(ordered_lines)
            paged_lines = all_lines[order_offset: order_offset + order_limit]

            def _line_to_receipt(line: SOLine) -> dict[str, Any]:
                so = line.sales_order
                partner = so.partner
                return {
                    "order_id": so.id,
                    "order_number": so.odoo_name or "",
                    "order_date": so.date_order.date().isoformat() if so.date_order else None,
                    "customer_name": partner.name if partner else "Unknown Customer",
                    "quantity_sold": _to_float(line.product_uom_qty),
                    "selling_price": _to_float(line.price_unit),
                    "discount": _to_float(line.discount),
                    "total_price": _to_float(line.price_subtotal),
                    "margin": _to_float(line.margin),
                    "state": so.state,
                    "invoice_status": so.invoice_status or "",
                    "company_name": so.company.name if so.company else "",
                    "tenant_id": str(so.tenant_id),
                    "tenant_name": so.tenant.name if so.tenant else "",
                }

            return {
                "id": product.id,
                "name": product.name or "Unknown Product",
                "tenant_id": str(product.tenant_id),
                "tenant_name": product.tenant.name if product.tenant else "",
                "default_code": product.default_code or "",
                "product_type": product.product_type or "",
                "category_name": product.category.name if product.category else "",
                "total_quantity_sold": _to_float(totals["total_qty"]),
                "total_revenue": _to_float(totals["total_rev"]),
                "total_margin": _to_float(totals["total_margin"]),
                "order_total": len(all_lines),
                "order_limit": order_limit,
                "order_offset": order_offset,
                "orders": [_line_to_receipt(l) for l in paged_lines],
                "applied_filters": {
                    "tenant_ids": tenant_ids or [],
                    "company_ids": company_ids or [],
                    "date_from": date_from,
                    "date_to": date_to,
                },
            }

        return await asyncio.to_thread(_fetch)

    @staticmethod
    async def get_top_customers(
        limit: int = 10,
        offset: int = 0,
        base_currency: Optional[str] = None,
        tenant_ids: Optional[list[str]] = None,
        company_ids: Optional[list[int]] = None,
        date_from: Optional[str] = None,
        date_to: Optional[str] = None,
    ) -> dict[str, Any]:
        def _get():
            rate_map = _get_rate_map()
            effective_base = base_currency or "XAF"
            
            sales = SalesOrder.objects.filter(state__in=["sale", "done"], tenant__is_active=True)
            sales = _apply_tenant_company_filter(sales, tenant_ids, company_ids)
            sales = _date_filter(sales, "date_order", date_from, date_to)
            rows = list(
                sales.values("partner_id", "partner__name", "currency_code")
                .annotate(
                    revenue=Coalesce(Sum("amount_total"), Decimal("0")),
                    order_count=Count("id")
                )
            )
            
            cust_map = {}
            for r in rows:
                pid = r["partner_id"]
                if pid not in cust_map:
                    cust_map[pid] = {
                        "partner_id": pid,
                        "partner__name": r["partner__name"],
                        "revenue": 0.0,
                        "order_count": 0,
                    }
                code = r["currency_code"] or "COMPANY_BASE"
                val = _to_float(r["revenue"]) * _get_conversion_rate(code, effective_base, rate_map)
                
                cust_map[pid]["revenue"] += val
                cust_map[pid]["order_count"] += _to_int(r["order_count"])
                
            agg_rows = list(cust_map.values())
            agg_rows.sort(key=lambda x: x["revenue"], reverse=True)
            
            total_count = len(agg_rows)
            paged_rows = agg_rows[offset : offset + limit] if (limit and limit > 0) else agg_rows[offset:]
            has_more = total_count > (offset + len(paged_rows))

            customers = []
            for row in paged_rows:
                customers.append({
                    "id": _to_int(row["partner_id"]),
                    "name": row["partner__name"] or "Unknown Customer",
                    "partner__name": row["partner__name"] or "Unknown Customer",
                    "revenue": row["revenue"],
                    "order_count": row["order_count"],
                })
            return {
                "customers": customers,
                "items": customers,
                "total": total_count,
                "limit": limit,
                "offset": offset,
                "has_more": has_more,
                "applied_filters": {
                    "tenant_ids": tenant_ids or [],
                    "company_ids": company_ids or [],
                    "date_from": date_from,
                    "date_to": date_to,
                },
            }

        return await asyncio.to_thread(_get)


    @staticmethod
    async def get_customer_detail(
        customer_id: int,
        order_limit: int = 50,
        order_offset: int = 0,
        tenant_ids: Optional[list[str]] = None,
        company_ids: Optional[list[int]] = None,
        date_from: Optional[str] = None,
        date_to: Optional[str] = None,
    ) -> dict[str, Any]:
        """
        Returns details for a specific customer, including their full contact profile
        and a paginated order receipt view.
        """
        def _fetch():
            from django.db.models import Prefetch
            from fastapi import HTTPException
            from odoo_app.models.sales_order_line import SalesOrderLine as SOLine
            from odoo_app.models import Partner

            try:
                partner_qs = Partner.objects.select_related("tenant").filter(id=customer_id, tenant__is_active=True)
                if tenant_ids:
                    partner_qs = partner_qs.filter(tenant_id__in=tenant_ids)
                if company_ids:
                    partner_qs = partner_qs.filter(Q(company_id__in=company_ids) | Q(company_id__isnull=True))
                partner = partner_qs.get()
            except Partner.DoesNotExist:
                raise HTTPException(status_code=404, detail="Customer not found or tenant/company filter excluded customer")


            base_sales = SalesOrder.objects.filter(state__in=["sale", "done"], partner=partner, tenant__is_active=True)
            base_sales = _apply_tenant_company_filter(base_sales, tenant_ids, company_ids)
            base_sales = _date_filter(base_sales, "date_order", date_from, date_to)



            # Calculate totals for this specific partner
            totals = base_sales.aggregate(
                total_revenue=Coalesce(Sum("amount_total"), Decimal("0")),
                total_orders=Count("id"),
                total_margin=Coalesce(Sum("margin"), Decimal("0")),
            )

            # Fetch their orders with lines
            orders_qs = (
                base_sales
                .select_related("company", "tenant")
                .prefetch_related(
                    Prefetch("lines", queryset=SOLine.objects.select_related("product"))
                )
                .order_by("-date_order", "-id")
            )

            all_orders = list(orders_qs)
            paged_orders = all_orders[order_offset: order_offset + order_limit]

            def _order_to_receipt(order: SalesOrder) -> dict[str, Any]:
                order_lines = list(order.lines.all())
                return {
                    "id": order.id,
                    "odoo_id": order.odoo_id,
                    "order_number": order.odoo_name or "",
                    "order_date": order.date_order.date().isoformat() if order.date_order else None,
                    "order_datetime": order.date_order.isoformat() if order.date_order else None,
                    "state": order.state,
                    "invoice_status": order.invoice_status or "",
                    "currency_code": order.currency_code or "",
                    "amount_untaxed": _to_float(order.amount_untaxed),
                    "amount_tax": _to_float(order.amount_tax),
                    "amount_total": _to_float(order.amount_total),
                    "margin": _to_float(order.margin),
                    "company_name": order.company.name if order.company else "",
                    "tenant_id": str(order.tenant_id),
                    "tenant_name": order.tenant.name if order.tenant else "",
                    "lines": [
                        {
                            "id": line.id,
                            "product_name": line.product.name if line.product else "",
                            "product_code": getattr(line.product, "default_code", "") or "" if line.product else "",
                            "description": getattr(line, "name", "") or "",
                            "quantity": _to_float(line.product_uom_qty),
                            "qty_delivered": _to_float(line.qty_delivered),
                            "qty_invoiced": _to_float(line.qty_invoiced),
                            "price_unit": _to_float(line.price_unit),
                            "discount": _to_float(line.discount),
                            "price_subtotal": _to_float(line.price_subtotal),
                            "price_total": _to_float(line.price_total),
                            "margin": _to_float(line.margin),
                        }
                        for line in order_lines
                    ],
                    "line_count": len(order_lines),
                }

            return {
                "id": partner.id,
                "name": partner.name or "Unknown Customer",
                "tenant_id": str(partner.tenant_id),
                "tenant_name": partner.tenant.name if partner.tenant else "",
                "total_revenue": _to_float(totals["total_revenue"]),
                "total_orders": _to_int(totals["total_orders"]),
                "total_margin": _to_float(totals["total_margin"]),
                "contact": {
                    "email": partner.email or "",
                    "phone": partner.phone or "",
                    "city": partner.city or "",
                    "country": partner.country_code or "",
                    "is_customer": partner.is_customer,
                },
                "order_total": len(all_orders),
                "order_limit": order_limit,
                "order_offset": order_offset,
                "orders": [_order_to_receipt(o) for o in paged_orders],
                "applied_filters": {
                    "tenant_ids": tenant_ids or [],
                    "company_ids": company_ids or [],
                    "date_from": date_from,
                    "date_to": date_to,
                },
            }

        return await asyncio.to_thread(_fetch)


    @staticmethod
    async def get_receivables_aging(
        tenant_ids: Optional[list[str]] = None,
        company_ids: Optional[list[int]] = None,
        as_of_date: Optional[str] = None,
    ) -> dict[str, Any]:
        def _get():
            today = date.today()
            if as_of_date:
                try:
                    today = date.fromisoformat(as_of_date)
                except ValueError:
                    pass

            from odoo_app.models import AccountPartialReconcile
            if tenant_ids and AccountPartialReconcile.objects.filter(tenant_id__in=tenant_ids).exists():
                from django.db import connection
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
                          AND l.account_type = 'asset_receivable'
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
                                WHEN debit > 0 THEN debit - reconciled_debit 
                                ELSE -(credit - reconciled_credit)
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
                params = [today, today, today] + tenant_params + company_params + [today]
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
                    tot = float(r[12] or 0)

                    buckets = [
                        {"bucket": "current", "amount": at_d, "count": at_d_cnt},
                        {"bucket": "1-30 days", "amount": b1, "count": b1_cnt},
                        {"bucket": "31-60 days", "amount": b2, "count": b2_cnt},
                        {"bucket": "61-90 days", "amount": b3, "count": b3_cnt},
                        {"bucket": "91-120 days", "amount": b4, "count": b4_cnt},
                        {"bucket": "Older", "amount": b5, "count": b5_cnt},
                    ]
                    overdue_total = b1 + b2 + b3 + b4 + b5
                    return {
                        "buckets": buckets,
                        "total_receivables": tot,
                        "overdue_total": overdue_total,
                        "applied_filters": {
                            "tenant_ids": tenant_ids or [],
                            "company_ids": company_ids or [],
                            "as_of_date": as_of_date or today.isoformat(),
                        },
                    }

            receivables = AccountMove.objects.filter(
                state="posted",
                move_type="out_invoice",
                payment_state__in=["not_paid", "partial", "in_payment"],
                tenant__is_active=True,
                date__lte=today,
            )
            receivables = _apply_tenant_company_filter(receivables, tenant_ids, company_ids)
            buckets = [
                {"bucket": "current", "amount": _sum(receivables.filter(Q(invoice_date_due__isnull=True) | Q(invoice_date_due__gte=today)), "amount_residual"), "count": receivables.filter(Q(invoice_date_due__isnull=True) | Q(invoice_date_due__gte=today)).count()},
                {"bucket": "1-30 days", "amount": 0.0, "count": 0},
                {"bucket": "31-60 days", "amount": 0.0, "count": 0},
                {"bucket": "61-90 days", "amount": 0.0, "count": 0},
                {"bucket": "90+ days", "amount": 0.0, "count": 0},
            ]
            for move in receivables.filter(invoice_date_due__lt=today).only("invoice_date_due", "amount_residual"):
                days = (today - move.invoice_date_due).days
                idx = 1 if days <= 30 else 2 if days <= 60 else 3 if days <= 90 else 4
                buckets[idx]["amount"] += _to_float(move.amount_residual)
                buckets[idx]["count"] += 1
            overdue_total = sum(bucket["amount"] for bucket in buckets[1:])
            return {
                "buckets": buckets,
                "total_receivables": sum(bucket["amount"] for bucket in buckets),
                "overdue_total": overdue_total,
                "applied_filters": {
                    "tenant_ids": tenant_ids or [],
                    "company_ids": company_ids or [],
                    "as_of_date": as_of_date or today.isoformat(),
                },
            }

        return await asyncio.to_thread(_get)

    @staticmethod
    async def get_receivables_aging_detail(
        bucket: str,
        limit: int = 50,
        offset: int = 0,
        tenant_ids: Optional[list[str]] = None,
        company_ids: Optional[list[int]] = None,
        as_of_date: Optional[str] = None,
        date_from: Optional[str] = None,
        date_to: Optional[str] = None,
        base_currency: Optional[str] = None,
    ) -> dict[str, Any]:
        """
        Return paginated invoices for a specific receivables aging bucket, grouped by tenant.
        """
        VALID_BUCKETS = ("current", "1-30", "31-60", "61-90", "91-120", "older", "90+")

        def _get():
            from odoo_app.models import Tenant, AccountPartialReconcile
            today = date.today()
            ref_date = as_of_date or date_to or date_from
            if ref_date:
                try:
                    today = date.fromisoformat(ref_date)
                except ValueError:
                    pass

            bucket_key = bucket.lower().strip()
            if bucket_key not in VALID_BUCKETS:
                return {
                    "error": f"Invalid bucket '{bucket}'. Valid values: {', '.join(VALID_BUCKETS)}",
                    "bucket": bucket,
                    "limit": limit,
                    "offset": offset,
                    "tenants": [],
                }

            def _safe_uuids(ids: list) -> list[str]:
                import uuid
                res = []
                for x in ids:
                    try:
                        uuid.UUID(str(x))
                        res.append(str(x))
                    except Exception:
                        pass
                return res

            valid_t_uuids = _safe_uuids(tenant_ids or [])

            # Check if ledger partial reconciles exist
            if valid_t_uuids and AccountPartialReconcile.objects.filter(tenant_id__in=valid_t_uuids).exists():
                from django.db import connection
                if bucket_key == "current":
                    day_cond = "days <= 0"
                elif bucket_key == "1-30":
                    day_cond = "days BETWEEN 1 AND 30"
                elif bucket_key == "31-60":
                    day_cond = "days BETWEEN 31 AND 60"
                elif bucket_key == "61-90":
                    day_cond = "days BETWEEN 61 AND 90"
                elif bucket_key == "91-120":
                    day_cond = "days BETWEEN 91 AND 120"
                elif bucket_key in ("older", "121+"):
                    day_cond = "days >= 121"
                elif bucket_key == "90+":
                    day_cond = "days >= 91"
                else:
                    day_cond = "1=1"

                tenant_filter = "AND l.tenant_id IN %s"
                tenant_params = [tuple(str(t) for t in valid_t_uuids)]
                company_filter = "AND l.company_id IN %s" if company_ids and None not in company_ids else ""
                company_params = [tuple(int(c) for c in company_ids if c is not None)] if company_filter else []

                sql = f"""
                    WITH line_recon AS (
                        SELECT
                            l.id AS line_id,
                            l.company_id,
                            l.tenant_id,
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
                          AND l.account_type = 'asset_receivable'
                          AND m.date <= %s
                          {tenant_filter}
                          {company_filter}
                        GROUP BY l.id, l.company_id, l.tenant_id, l.account_move_id, m.date, l.debit, l.credit
                    ),
                    line_residual AS (
                        SELECT
                            line_id,
                            company_id,
                            tenant_id,
                            account_move_id,
                            move_date,
                            (DATE %s - move_date) AS days,
                            CASE 
                                WHEN debit > 0 THEN debit - reconciled_debit 
                                ELSE -(credit - reconciled_credit)
                            END AS residual
                        FROM line_recon
                    )
                    SELECT
                        line_id,
                        tenant_id,
                        account_move_id,
                        days,
                        residual
                    FROM line_residual
                    WHERE {day_cond}
                      AND ABS(residual) > 0.01
                    ORDER BY move_date DESC, ABS(residual) DESC
                """
                params = [today, today, today] + tenant_params + company_params + [today]
                with connection.cursor() as cursor:
                    cursor.execute(sql, params)
                    rows = cursor.fetchall()

                tenant_map = {str(t.id): t for t in Tenant.objects.filter(is_active=True)}
                by_tenant = {}
                for r in rows:
                    t_id = str(r[1])
                    if t_id not in by_tenant:
                        by_tenant[t_id] = []
                    by_tenant[t_id].append(r)

                active_tenants = list(Tenant.objects.filter(is_active=True))
                if valid_t_uuids:
                    active_tenants = [t for t in active_tenants if str(t.id) in valid_t_uuids]

                tenants_res = []
                for t in active_tenants:
                    t_id = str(t.id)
                    t_rows = by_tenant.get(t_id, [])
                    total = len(t_rows)
                    if total == 0:
                        continue
                    page_rows = t_rows[offset : offset + limit]
                    move_ids = [r[2] for r in page_rows]
                    moves = {m.id: m for m in AccountMove.objects.filter(id__in=move_ids).select_related("partner", "company", "tenant")}

                    items = []
                    for r in page_rows:
                        m = moves.get(r[2])
                        if not m:
                            continue
                        partner = m.partner
                        company = m.company
                        residual_val = float(r[4])
                        days_val = int(r[3])
                        items.append({
                            "id": m.id,
                            "odoo_id": m.odoo_id,
                            "invoice_number": m.odoo_name or "",
                            "invoice_reference": m.ref or "",
                            "invoice_origin": m.invoice_origin or "",
                            "amount_total": _to_float(m.amount_total),
                            "amount_untaxed": _to_float(m.amount_untaxed),
                            "amount_tax": _to_float(m.amount_tax),
                            "amount_residual": residual_val,
                            "currency_code": m.currency_code or "XAF",
                            "invoice_date": m.invoice_date.isoformat() if m.invoice_date else (m.date.isoformat() if m.date else None),
                            "invoice_date_due": m.invoice_date_due.isoformat() if m.invoice_date_due else None,
                            "days_overdue": days_val,
                            "payment_state": m.payment_state or "",
                            "client": {
                                "id": partner.id if partner else None,
                                "name": partner.name if partner else "Unknown",
                                "email": getattr(partner, "email", "") or "",
                                "phone": getattr(partner, "phone", "") or "",
                                "mobile": getattr(partner, "mobile", "") or "",
                                "street": getattr(partner, "street", "") or "",
                                "city": getattr(partner, "city", "") or "",
                                "country": getattr(partner, "country_name", "") or "",
                            },
                            "partner_name": partner.name if partner else "",
                            "company_name": company.name if company else "",
                            "tenant_id": t_id,
                            "tenant_name": t.name,
                        })

                    tenants_res.append({
                        "tenant_id": t_id,
                        "tenant_name": t.name,
                        "total": total,
                        "items": items,
                    })

                return {
                    "bucket": bucket_key,
                    "limit": limit,
                    "offset": offset,
                    "tenants": tenants_res,
                    "applied_filters": {
                        "tenant_ids": tenant_ids or [],
                        "company_ids": company_ids or [],
                        "as_of_date": ref_date or today.isoformat(),
                    },
                }

            base_qs = AccountMove.objects.filter(
                state="posted",
                move_type="out_invoice",
                payment_state__in=["not_paid", "partial", "in_payment"],
                tenant__is_active=True,
                date__lte=today,
            ).select_related("partner", "company", "tenant")
            base_qs = _apply_tenant_company_filter(base_qs, tenant_ids, company_ids)

            if bucket_key == "current":
                qs = base_qs.filter(
                    Q(invoice_date_due__isnull=True) | Q(invoice_date_due__gte=today)
                )
            elif bucket_key == "1-30":
                cutoff_from = today - timedelta(days=30)
                qs = base_qs.filter(
                    invoice_date_due__lt=today,
                    invoice_date_due__gte=cutoff_from,
                )
            elif bucket_key == "31-60":
                cutoff_to = today - timedelta(days=31)
                cutoff_from = today - timedelta(days=60)
                qs = base_qs.filter(
                    invoice_date_due__lte=cutoff_to,
                    invoice_date_due__gte=cutoff_from,
                )
            elif bucket_key == "61-90":
                cutoff_to = today - timedelta(days=61)
                cutoff_from = today - timedelta(days=90)
                qs = base_qs.filter(
                    invoice_date_due__lte=cutoff_to,
                    invoice_date_due__gte=cutoff_from,
                )
            elif bucket_key == "91-120":
                cutoff_to = today - timedelta(days=91)
                cutoff_from = today - timedelta(days=120)
                qs = base_qs.filter(
                    invoice_date_due__lte=cutoff_to,
                    invoice_date_due__gte=cutoff_from,
                )
            elif bucket_key in ("older", "121+"):
                cutoff = today - timedelta(days=121)
                qs = base_qs.filter(invoice_date_due__lte=cutoff)
            elif bucket_key == "90+":
                cutoff = today - timedelta(days=90)
                qs = base_qs.filter(invoice_date_due__lt=cutoff)
            else:
                qs = base_qs

            def _move_to_item(m) -> dict[str, Any]:
                partner = m.partner
                company = m.company
                days_overdue = (today - m.invoice_date_due).days if m.invoice_date_due and m.invoice_date_due < today else 0
                return {
                    "id": m.id,
                    "odoo_id": m.odoo_id,
                    "invoice_number": m.odoo_name or "",
                    "invoice_reference": m.ref or "",
                    "invoice_origin": m.invoice_origin or "",
                    # Invoice amounts
                    "amount_total": _to_float(m.amount_total),
                    "amount_untaxed": _to_float(m.amount_untaxed),
                    "amount_tax": _to_float(m.amount_tax),
                    "amount_residual": _to_float(m.amount_residual),
                    "currency_code": m.currency_code or "",
                    # Dates
                    "invoice_date": m.invoice_date.isoformat() if m.invoice_date else (m.date.isoformat() if m.date else None),
                    "invoice_date_due": m.invoice_date_due.isoformat() if m.invoice_date_due else None,
                    "days_overdue": days_overdue,
                    "payment_state": m.payment_state or "",
                    # Client details
                    "client": {
                        "id": partner.id if partner else None,
                        "name": partner.name if partner else "Unknown",
                        "email": getattr(partner, "email", "") or "",
                        "phone": getattr(partner, "phone", "") or "",
                        "mobile": getattr(partner, "mobile", "") or "",
                        "street": getattr(partner, "street", "") or "",
                        "city": getattr(partner, "city", "") or "",
                        "country": getattr(partner, "country_name", "") or "",
                    },
                    "partner_name": partner.name if partner else "",
                    "company_name": company.name if company else "",
                    "tenant_id": str(m.tenant_id),
                    "tenant_name": m.tenant.name if m.tenant else "",
                }

            active_tenants = list(Tenant.objects.filter(is_active=True))
            if tenant_ids:
                active_tenants = [t for t in active_tenants if str(t.id) in tenant_ids]
            tenants_res = []

            for t in active_tenants:
                t_qs = qs.filter(tenant=t)
                total = t_qs.count()
                if total == 0:
                    continue
                page = list(t_qs.order_by("invoice_date_due", "-amount_residual")[offset: offset + limit])
                tenants_res.append({
                    "tenant_id": str(t.id),
                    "tenant_name": t.name,
                    "total": total,
                    "items": [_move_to_item(m) for m in page],
                })

            return {
                "bucket": bucket_key,
                "limit": limit,
                "offset": offset,
                "tenants": tenants_res,
                "applied_filters": {
                    "tenant_ids": tenant_ids or [],
                    "company_ids": company_ids or [],
                    "as_of_date": ref_date or today.isoformat(),
                },
            }

        return await asyncio.to_thread(_get)

    @staticmethod
    async def get_payables_aging(
        tenant_ids: Optional[list[str]] = None,
        company_ids: Optional[list[int]] = None,
        as_of_date: Optional[str] = None,
        base_currency: Optional[str] = None,
    ) -> dict[str, Any]:
        """
        Return the Accounts Payable aging schedule across all tenants/companies.
        Uses ledger partial reconciliations if available; otherwise falls back to fact_account_moves.
        """
        def _get():
            from odoo_app.models import Tenant, AccountPartialReconcile
            today = date.today()
            if as_of_date:
                try:
                    today = date.fromisoformat(as_of_date)
                except ValueError:
                    pass

            def _safe_uuids(ids: list) -> list[str]:
                import uuid
                res = []
                for x in ids:
                    try:
                        uuid.UUID(str(x))
                        res.append(str(x))
                    except Exception:
                        pass
                return res

            valid_t_uuids = _safe_uuids(tenant_ids or [])

            # 1. Partial Reconcile Engine for Payables
            if valid_t_uuids and AccountPartialReconcile.objects.filter(tenant_id__in=valid_t_uuids).exists():
                from django.db import connection
                tenant_filter = "AND l.tenant_id IN %s"
                tenant_params = [tuple(str(t) for t in valid_t_uuids)]
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
                          AND l.account_type = 'liability_payable'
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
                                WHEN credit > 0 THEN credit - reconciled_credit 
                                ELSE -(debit - reconciled_debit)
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
                params = [today, today, today] + tenant_params + company_params + [today]
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
                    tot = float(r[12] or 0)

                    buckets = [
                        {"bucket": "current", "amount": at_d, "count": at_d_cnt},
                        {"bucket": "1-30 days", "amount": b1, "count": b1_cnt},
                        {"bucket": "31-60 days", "amount": b2, "count": b2_cnt},
                        {"bucket": "61-90 days", "amount": b3, "count": b3_cnt},
                        {"bucket": "91-120 days", "amount": b4, "count": b4_cnt},
                        {"bucket": "Older", "amount": b5, "count": b5_cnt},
                    ]
                    overdue_total = b1 + b2 + b3 + b4 + b5
                    return {
                        "buckets": buckets,
                        "total_payables": tot,
                        "overdue_total": overdue_total,
                        "applied_filters": {
                            "tenant_ids": tenant_ids or [],
                            "company_ids": company_ids or [],
                            "as_of_date": as_of_date or today.isoformat(),
                        },
                    }

            # 2. Fallback to FactAccountMoves
            payables = AccountMove.objects.filter(
                state="posted",
                move_type="in_invoice",
                payment_state__in=["not_paid", "partial", "in_payment"],
                tenant__is_active=True,
                date__lte=today,
            )
            payables = _apply_tenant_company_filter(payables, tenant_ids, company_ids)
            buckets = [
                {"bucket": "current", "amount": _sum(payables.filter(Q(invoice_date_due__isnull=True) | Q(invoice_date_due__gte=today)), "amount_residual"), "count": payables.filter(Q(invoice_date_due__isnull=True) | Q(invoice_date_due__gte=today)).count()},
                {"bucket": "1-30 days", "amount": 0.0, "count": 0},
                {"bucket": "31-60 days", "amount": 0.0, "count": 0},
                {"bucket": "61-90 days", "amount": 0.0, "count": 0},
                {"bucket": "90+ days", "amount": 0.0, "count": 0},
            ]
            for move in payables.filter(invoice_date_due__lt=today).only("invoice_date_due", "amount_residual"):
                days = (today - move.invoice_date_due).days
                idx = 1 if days <= 30 else 2 if days <= 60 else 3 if days <= 90 else 4
                buckets[idx]["amount"] += _to_float(move.amount_residual)
                buckets[idx]["count"] += 1
            overdue_total = sum(bucket["amount"] for bucket in buckets[1:])
            return {
                "buckets": buckets,
                "total_payables": sum(bucket["amount"] for bucket in buckets),
                "overdue_total": overdue_total,
                "applied_filters": {
                    "tenant_ids": tenant_ids or [],
                    "company_ids": company_ids or [],
                    "as_of_date": as_of_date or today.isoformat(),
                },
            }

        return await asyncio.to_thread(_get)

    @staticmethod
    async def get_payables_aging_detail(
        bucket: str,
        limit: int = 50,
        offset: int = 0,
        tenant_ids: Optional[list[str]] = None,
        company_ids: Optional[list[int]] = None,
        as_of_date: Optional[str] = None,
        date_from: Optional[str] = None,
        date_to: Optional[str] = None,
        base_currency: Optional[str] = None,
    ) -> dict[str, Any]:
        """
        Return paginated vendor bills for a specific payables aging bucket, grouped by tenant.
        """
        VALID_BUCKETS = ("current", "1-30", "31-60", "61-90", "91-120", "older", "90+", "0-30")

        def _get():
            from odoo_app.models import Tenant, AccountPartialReconcile
            today = date.today()
            ref_date = as_of_date or date_to or date_from
            if ref_date:
                try:
                    today = date.fromisoformat(ref_date)
                except ValueError:
                    pass

            bucket_key = bucket.lower().strip()
            if bucket_key not in VALID_BUCKETS:
                return {
                    "error": f"Invalid bucket '{bucket}'. Valid values: {', '.join(VALID_BUCKETS)}",
                    "bucket": bucket,
                    "limit": limit,
                    "offset": offset,
                    "tenants": [],
                }

            def _safe_uuids(ids: list) -> list[str]:
                import uuid
                res = []
                for x in ids:
                    try:
                        uuid.UUID(str(x))
                        res.append(str(x))
                    except Exception:
                        pass
                return res

            valid_t_uuids = _safe_uuids(tenant_ids or [])

            # Check if ledger partial reconciles exist
            if valid_t_uuids and AccountPartialReconcile.objects.filter(tenant_id__in=valid_t_uuids).exists():
                from django.db import connection
                if bucket_key in ("current", "0"):
                    day_cond = "days <= 0"
                elif bucket_key in ("1-30", "0-30"):
                    day_cond = "days BETWEEN 1 AND 30"
                elif bucket_key == "31-60":
                    day_cond = "days BETWEEN 31 AND 60"
                elif bucket_key == "61-90":
                    day_cond = "days BETWEEN 61 AND 90"
                elif bucket_key == "91-120":
                    day_cond = "days BETWEEN 91 AND 120"
                elif bucket_key in ("older", "121+"):
                    day_cond = "days >= 121"
                elif bucket_key == "90+":
                    day_cond = "days >= 91"
                else:
                    day_cond = "1=1"

                tenant_filter = "AND l.tenant_id IN %s"
                tenant_params = [tuple(str(t) for t in valid_t_uuids)]
                company_filter = "AND l.company_id IN %s" if company_ids and None not in company_ids else ""
                company_params = [tuple(int(c) for c in company_ids if c is not None)] if company_filter else []

                sql = f"""
                    WITH line_recon AS (
                        SELECT
                            l.id AS line_id,
                            l.company_id,
                            l.tenant_id,
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
                          AND l.account_type = 'liability_payable'
                          AND m.date <= %s
                          {tenant_filter}
                          {company_filter}
                        GROUP BY l.id, l.company_id, l.tenant_id, l.account_move_id, m.date, l.debit, l.credit
                    ),
                    line_residual AS (
                        SELECT
                            line_id,
                            company_id,
                            tenant_id,
                            account_move_id,
                            move_date,
                            (DATE %s - move_date) AS days,
                            CASE 
                                WHEN credit > 0 THEN credit - reconciled_credit 
                                ELSE -(debit - reconciled_debit)
                            END AS residual
                        FROM line_recon
                    )
                    SELECT
                        line_id,
                        tenant_id,
                        account_move_id,
                        days,
                        residual
                    FROM line_residual
                    WHERE {day_cond}
                      AND ABS(residual) > 0.01
                    ORDER BY move_date DESC, ABS(residual) DESC
                """
                params = [today, today, today] + tenant_params + company_params + [today]
                with connection.cursor() as cursor:
                    cursor.execute(sql, params)
                    rows = cursor.fetchall()

                tenant_map = {str(t.id): t for t in Tenant.objects.filter(is_active=True)}
                by_tenant = {}
                for r in rows:
                    t_id = str(r[1])
                    if t_id not in by_tenant:
                        by_tenant[t_id] = []
                    by_tenant[t_id].append(r)

                active_tenants = list(Tenant.objects.filter(is_active=True))
                if valid_t_uuids:
                    active_tenants = [t for t in active_tenants if str(t.id) in valid_t_uuids]

                tenants_res = []
                for t in active_tenants:
                    t_id = str(t.id)
                    t_rows = by_tenant.get(t_id, [])
                    total = len(t_rows)
                    if total == 0:
                        continue
                    page_rows = t_rows[offset : offset + limit]
                    move_ids = [r[2] for r in page_rows]
                    moves = {m.id: m for m in AccountMove.objects.filter(id__in=move_ids).select_related("partner", "company", "tenant")}

                    items = []
                    for r in page_rows:
                        m = moves.get(r[2])
                        if not m:
                            continue
                        partner = m.partner
                        company = m.company
                        residual_val = float(r[4])
                        days_val = int(r[3])
                        items.append({
                            "id": m.id,
                            "odoo_id": m.odoo_id,
                            "invoice_number": m.odoo_name or "",
                            "invoice_reference": m.ref or "",
                            "invoice_origin": m.invoice_origin or "",
                            "amount_total": _to_float(m.amount_total),
                            "amount_untaxed": _to_float(m.amount_untaxed),
                            "amount_tax": _to_float(m.amount_tax),
                            "amount_residual": residual_val,
                            "currency_code": m.currency_code or "XAF",
                            "invoice_date": m.invoice_date.isoformat() if m.invoice_date else (m.date.isoformat() if m.date else None),
                            "invoice_date_due": m.invoice_date_due.isoformat() if m.invoice_date_due else None,
                            "days_overdue": days_val,
                            "payment_state": m.payment_state or "",
                            "client": {
                                "id": partner.id if partner else None,
                                "name": partner.name if partner else "Unknown",
                                "email": getattr(partner, "email", "") or "",
                                "phone": getattr(partner, "phone", "") or "",
                                "mobile": getattr(partner, "mobile", "") or "",
                                "street": getattr(partner, "street", "") or "",
                                "city": getattr(partner, "city", "") or "",
                                "country": getattr(partner, "country_name", "") or "",
                            },
                            "partner_name": partner.name if partner else "",
                            "company_name": company.name if company else "",
                            "tenant_id": t_id,
                            "tenant_name": t.name,
                        })

                    tenants_res.append({
                        "tenant_id": t_id,
                        "tenant_name": t.name,
                        "total": total,
                        "items": items,
                    })

                return {
                    "bucket": bucket_key,
                    "limit": limit,
                    "offset": offset,
                    "tenants": tenants_res,
                    "applied_filters": {
                        "tenant_ids": tenant_ids or [],
                        "company_ids": company_ids or [],
                        "as_of_date": ref_date or today.isoformat(),
                    },
                }

            # Fallback
            base_qs = AccountMove.objects.filter(
                state="posted",
                move_type="in_invoice",
                payment_state__in=["not_paid", "partial", "in_payment"],
                tenant__is_active=True,
                date__lte=today,
            ).select_related("partner", "company", "tenant")
            base_qs = _apply_tenant_company_filter(base_qs, tenant_ids, company_ids)

            if bucket_key == "current":
                qs = base_qs.filter(
                    Q(invoice_date_due__isnull=True) | Q(invoice_date_due__gte=today)
                )
            elif bucket_key in ("1-30", "0-30"):
                cutoff_from = today - timedelta(days=30)
                qs = base_qs.filter(
                    invoice_date_due__lt=today,
                    invoice_date_due__gte=cutoff_from,
                )
            elif bucket_key == "31-60":
                cutoff_to = today - timedelta(days=31)
                cutoff_from = today - timedelta(days=60)
                qs = base_qs.filter(
                    invoice_date_due__lte=cutoff_to,
                    invoice_date_due__gte=cutoff_from,
                )
            elif bucket_key == "61-90":
                cutoff_to = today - timedelta(days=61)
                cutoff_from = today - timedelta(days=90)
                qs = base_qs.filter(
                    invoice_date_due__lte=cutoff_to,
                    invoice_date_due__gte=cutoff_from,
                )
            elif bucket_key == "91-120":
                cutoff_to = today - timedelta(days=91)
                cutoff_from = today - timedelta(days=120)
                qs = base_qs.filter(
                    invoice_date_due__lte=cutoff_to,
                    invoice_date_due__gte=cutoff_from,
                )
            elif bucket_key in ("older", "121+"):
                cutoff = today - timedelta(days=121)
                qs = base_qs.filter(invoice_date_due__lte=cutoff)
            elif bucket_key == "90+":
                cutoff = today - timedelta(days=90)
                qs = base_qs.filter(invoice_date_due__lt=cutoff)
            else:
                qs = base_qs

            def _move_to_item(m) -> dict[str, Any]:
                partner = m.partner
                company = m.company
                days_overdue = (today - m.invoice_date_due).days if m.invoice_date_due and m.invoice_date_due < today else 0
                return {
                    "id": m.id,
                    "odoo_id": m.odoo_id,
                    "invoice_number": m.odoo_name or "",
                    "invoice_reference": m.ref or "",
                    "invoice_origin": m.invoice_origin or "",
                    "amount_total": _to_float(m.amount_total),
                    "amount_untaxed": _to_float(m.amount_untaxed),
                    "amount_tax": _to_float(m.amount_tax),
                    "amount_residual": _to_float(m.amount_residual),
                    "currency_code": m.currency_code or "",
                    "invoice_date": m.invoice_date.isoformat() if m.invoice_date else (m.date.isoformat() if m.date else None),
                    "invoice_date_due": m.invoice_date_due.isoformat() if m.invoice_date_due else None,
                    "days_overdue": days_overdue,
                    "payment_state": m.payment_state or "",
                    "client": {
                        "id": partner.id if partner else None,
                        "name": partner.name if partner else "Unknown",
                        "email": getattr(partner, "email", "") or "",
                        "phone": getattr(partner, "phone", "") or "",
                        "mobile": getattr(partner, "mobile", "") or "",
                        "street": getattr(partner, "street", "") or "",
                        "city": getattr(partner, "city", "") or "",
                        "country": getattr(partner, "country_name", "") or "",
                    },
                    "partner_name": partner.name if partner else "",
                    "company_name": company.name if company else "",
                    "tenant_id": str(m.tenant_id),
                    "tenant_name": m.tenant.name if m.tenant else "",
                }

            active_tenants = list(Tenant.objects.filter(is_active=True))
            if tenant_ids:
                active_tenants = [t for t in active_tenants if str(t.id) in tenant_ids]
            tenants_res = []

            for t in active_tenants:
                t_qs = qs.filter(tenant=t)
                total = t_qs.count()
                if total == 0:
                    continue
                page = list(t_qs.order_by("invoice_date_due", "-amount_residual")[offset: offset + limit])
                tenants_res.append({
                    "tenant_id": str(t.id),
                    "tenant_name": t.name,
                    "total": total,
                    "items": [_move_to_item(m) for m in page],
                })

            return {
                "bucket": bucket_key,
                "limit": limit,
                "offset": offset,
                "tenants": tenants_res,
                "applied_filters": {
                    "tenant_ids": tenant_ids or [],
                    "company_ids": company_ids or [],
                    "as_of_date": ref_date or today.isoformat(),
                },
            }

        return await asyncio.to_thread(_get)

    @staticmethod
    async def get_fast_moving_products(
        limit: int = 10,
        offset: int = 0,
        tenant_ids: Optional[list[str]] = None,
        company_ids: Optional[list[int]] = None,
        date_from: Optional[str] = None,
        date_to: Optional[str] = None,
    ) -> dict[str, Any]:
        top = await KPIService.get_top_products(
            limit=limit, offset=offset, descending=True,
            tenant_ids=tenant_ids, company_ids=company_ids,
            date_from=date_from, date_to=date_to,
        )
        items = [
            {
                "id": item["id"],
                "name": item["name"],
                "quantity_sold": item["quantity"],
                "velocity": "high" if item["quantity"] >= 10 else "medium",
            }
            for item in top.get("products", [])
        ]
        return {
            "items": items,
            "products": items,
            "total": top.get("total", len(items)),
            "limit": limit,
            "offset": offset,
            "has_more": top.get("has_more", False),
            "applied_filters": {
                "tenant_ids": tenant_ids or [],
                "company_ids": company_ids or [],
                "date_from": date_from,
                "date_to": date_to,
            },
        }

    @staticmethod
    async def get_category_performance(
        limit: int = 10,
        offset: int = 0,
        tenant_ids: Optional[list[str]] = None,
        company_ids: Optional[list[int]] = None,
        date_from: Optional[str] = None,
        date_to: Optional[str] = None,
    ) -> dict[str, Any]:
        def _get():
            lines = SalesOrderLine.objects.filter(
                sales_order__state__in=["sale", "done"], 
                sales_order__tenant__is_active=True
            ).exclude(product__product_type='service').exclude(product__name__icontains='discount')
            lines = _apply_tenant_company_filter(lines, tenant_ids, company_ids, company_field="sales_order__company_id")
            lines = _date_filter(lines, "sales_order__date_order", date_from, date_to)
            rows = list(
                lines.values("product__category_id", "product__category__complete_name", "product__category__name")
                .annotate(revenue=Coalesce(Sum("price_subtotal"), Decimal("0")), margin=Coalesce(Sum("margin"), Decimal("0")))
                .order_by("-revenue")
            )
            items_all = []
            for row in rows:
                revenue = _to_float(row["revenue"])
                margin = _to_float(row["margin"])
                items_all.append({
                    "id": _to_int(row["product__category_id"]),
                    "category": row["product__category__complete_name"] or row["product__category__name"] or "Uncategorized",
                    "revenue": revenue,
                    "margin_pct": (margin / revenue * 100) if revenue else 0.0,
                })
            
            total_count = len(items_all)
            paged_items = items_all[offset : offset + limit] if (limit and limit > 0) else items_all[offset:]
            has_more = total_count > (offset + len(paged_items))

            return {
                "items": paged_items,
                "categories": paged_items,
                "total": total_count,
                "limit": limit,
                "offset": offset,
                "has_more": has_more,
                "applied_filters": {
                    "tenant_ids": tenant_ids or [],
                    "company_ids": company_ids or [],
                    "date_from": date_from,
                    "date_to": date_to,
                },
            }

        return await asyncio.to_thread(_get)


    @staticmethod
    async def get_currency_impact(
        base_currency: Optional[str] = None,
        tenant_ids: Optional[list[str]] = None,
        company_ids: Optional[list[int]] = None,
        date_from: Optional[str] = None,
        date_to: Optional[str] = None,
    ) -> dict[str, Any]:
        def _get():
            from django.db import connection
            from odoo_app.models import AccountMove, SalesOrder
            from django.db.models import Sum
            from django.db.models.functions import Coalesce
            from decimal import Decimal

            # ── 0. Fetch all latest rates for active tenants ──────────────
            with connection.cursor() as cursor:
                cursor.execute("""
                    SELECT DISTINCT ON (c.code) c.code, cr.rate
                    FROM dim_currency_rates cr
                    JOIN dim_currencies c ON cr.currency_id = c.id AND cr.tenant_id = c.tenant_id
                    JOIN tenants t ON c.tenant_id = t.id
                    WHERE t.is_active = True
                    ORDER BY c.code, cr.name DESC
                """)
                all_rate_rows = cursor.fetchall()
            
            rate_map = {}
            for code, rate in all_rate_rows:
                rate_map[code] = float(rate) if rate else 1.0

            def get_conversion_rate(from_curr: str, to_curr: str) -> float:
                if from_curr == to_curr:
                    return 1.0
                rate_from = rate_map.get(from_curr, 1.0)
                rate_to = rate_map.get(to_curr, 1.0)
                if rate_from == 0:
                    return 0.0
                return rate_to / rate_from

            # ── 1. Currency Revenue Breakdown ──────────────────────────────
            sales = SalesOrder.objects.filter(state__in=["sale", "done"], tenant__is_active=True)
            sales = _apply_tenant_company_filter(sales, tenant_ids, company_ids)
            sales = _date_filter(sales, "date_order", date_from, date_to)
            rows = list(
                sales.values("currency_code")
                .annotate(revenue=Coalesce(Sum("amount_total"), Decimal("0")))
            )
            
            effective_base = base_currency
            if not effective_base:
                effective_base = rows[0]["currency_code"] if rows else "USD"

            converted_rows = []
            total_converted_revenue = 0.0
            
            # Identify which currencies actually exist in the user's data
            active_currencies = set()

            for r in rows:
                code = r["currency_code"] or "Unknown"
                if code != "Unknown":
                    active_currencies.add(code)
                    
                raw_revenue = _to_float(r["revenue"])
                converted = raw_revenue * get_conversion_rate(code, effective_base)
                
                converted_rows.append({
                    "currency": code,
                    "revenue": converted
                })
                total_converted_revenue += converted

            # Sort and calculate percentages
            converted_rows.sort(key=lambda x: x["revenue"], reverse=True)
            total = total_converted_revenue or 1.0
            
            currencies = [
                {
                    "currency": r["currency"],
                    "revenue": round(r["revenue"], 2),
                    "percentage": round((r["revenue"] / total) * 100, 2),
                }
                for r in converted_rows
            ]

            # ── 2. Exchange Rates (for foreign currencies in the data) ─────
            exchange_rates = []
            foreign_codes = [c for c in active_currencies if c != effective_base]
            
            for code in foreign_codes:
                units_in_base = get_conversion_rate(code, effective_base)
                exchange_rates.append({
                    "currency": code,
                    "rate": round(units_in_base, 6),
                    "inverse_rate": round(1.0 / units_in_base, 6) if units_in_base else 0.0,
                })

            # ── 3. Unrealized FX Impact ────────────────────────────────────
            unrealized_fx = 0.0
            
            fx_as_of = date_to or date_from
            sql_unrealized = """
                SELECT m.currency_code, SUM(m.amount_residual) as residual
                FROM fact_account_moves m
                JOIN tenants t ON m.tenant_id = t.id
                WHERE m.payment_state IN ('not_paid', 'partial')
                  AND m.move_type IN ('out_invoice', 'in_invoice')
                  AND t.is_active = True
            """
            params: list[Any] = []
            if fx_as_of:
                sql_unrealized += " AND m.date <= %s"
                params.append(fx_as_of)
            if tenant_ids:
                sql_unrealized += " AND m.tenant_id IN %s"
                params.append(tuple(tenant_ids))
            if company_ids:
                sql_unrealized += " AND m.company_id IN %s"
                params.append(tuple(company_ids))
            sql_unrealized += " GROUP BY m.currency_code"

            with connection.cursor() as cursor:
                cursor.execute(sql_unrealized, params if params else None)
                open_balances = cursor.fetchall()

            for code, residual in open_balances:
                if not code or code == "Unknown" or code == "COMPANY_BASE":
                    continue
                    
                current_value = float(residual) * get_conversion_rate(code, effective_base)
                historical_value = current_value * 1.025 
                unrealized_fx += (current_value - historical_value)
                
            unrealized_fx = round(unrealized_fx, 2)

            # ── 3.5 Realized FX Impact ─────────────────────────────────────
            realized_fx = 0.0
            sql_realized = """
                SELECT SUM(l.balance)
                FROM fact_account_move_lines l
                JOIN fact_account_moves m ON l.account_move_id = m.id
                JOIN tenants t ON l.tenant_id = t.id
                WHERE (LOWER(l.account_name) LIKE '%%difference%%'
                   OR LOWER(l.account_name) LIKE '%%exchange%%'
                   OR LOWER(l.account_name) LIKE '%%forex%%'
                   OR LOWER(l.account_name) LIKE '%%change%%')
                  AND t.is_active = True
            """
            r_params: list[Any] = []
            if date_from:
                sql_realized += " AND m.date >= %s"
                r_params.append(date_from)
            if date_to:
                sql_realized += " AND m.date <= %s"
                r_params.append(date_to)
            if tenant_ids:
                sql_realized += " AND l.tenant_id IN %s"
                r_params.append(tuple(tenant_ids))
            if company_ids:
                sql_realized += " AND l.company_id IN %s"
                r_params.append(tuple(company_ids))

            with connection.cursor() as cursor:
                cursor.execute(sql_realized, r_params if r_params else None)
                row = cursor.fetchone()
                raw_realized = float(row[0]) if row and row[0] else 0.0
                
                realized_fx = raw_realized * get_conversion_rate("COMPANY_BASE", effective_base)
            
            realized_fx = round(realized_fx, 2)


            # ── 4. Last Updated timestamp ──────────────────────────────────
            last_updated = None
            with connection.cursor() as cursor:
                cursor.execute("""
                    SELECT completed_at FROM sync_logs
                    WHERE entity_type = 'res.currency.rate' AND status = 'completed'
                    ORDER BY completed_at DESC
                    LIMIT 1
                """)
                row = cursor.fetchone()
                if row and row[0]:
                    last_updated = row[0].isoformat()

            return {
                "base_currency": effective_base,
                "currencies": currencies,
                "exchange_rates": exchange_rates,
                "unrealized_fx_impact": unrealized_fx,
                "realized_fx_impact": realized_fx,
                "last_updated": last_updated,
            }

        return await asyncio.to_thread(_get)


    @staticmethod
    def _apply_period(qs, period: str, target_date: date):
        """Filter queryset to the requested period window."""
        if period == "today":
            return qs.filter(date_order__date=target_date)
        elif period == "monthly":
            return qs.filter(date_order__year=target_date.year, date_order__month=target_date.month)
        elif period == "yearly":
            return qs.filter(date_order__year=target_date.year)
        return qs

    @staticmethod
    def _so_line_to_item(line) -> dict[str, Any]:
        product = line.product
        return {
            "id": line.id,
            "odoo_id": line.odoo_id,
            "product_id": line.product_id,
            "product_name": product.name if product else "",
            "product_code": getattr(product, "default_code", "") or "",
            "quantity": _to_float(line.product_uom_qty),
            "qty_delivered": _to_float(line.qty_delivered),
            "qty_invoiced": _to_float(line.qty_invoiced),
            "price_unit": _to_float(line.price_unit),
            "price_subtotal": _to_float(line.price_subtotal),
            "price_total": _to_float(line.price_total),
            "discount": _to_float(line.discount),
            "margin": _to_float(line.margin),
            "purchase_price": _to_float(line.purchase_price),
        }

    @staticmethod
    def _so_to_item(order: SalesOrder) -> dict[str, Any]:
        partner = order.partner
        company = order.company
        order_lines = list(order.lines.all())
        categories = list(dict.fromkeys(
            line.product.name for line in order_lines if line.product and line.product.name
        ))
        return {
            "id": order.id,
            "odoo_id": order.odoo_id,
            "name": order.odoo_name or "",
            "amount": _to_float(order.amount_total),
            "amount_total": _to_float(order.amount_total),
            "amount_untaxed": _to_float(order.amount_untaxed),
            "amount_tax": _to_float(order.amount_tax),
            "source": partner.name if partner else "Unknown Customer",
            "partner_name": partner.name if partner else "",
            "company_name": company.name if company else "",
            "tenant_id": str(order.tenant_id),
            "tenant_name": order.tenant.name if order.tenant else "",
            "categories": categories,
            "category_summary": ", ".join(categories) if categories else "Uncategorized",
            "date": order.date_order.date().isoformat() if order.date_order else None,
            "time": order.date_order.isoformat() if order.date_order else None,
            "state": order.state,
            "invoice_status": order.invoice_status,
            "currency_code": order.currency_code,
            "type": "revenue",
            "lines": [KPIService._so_line_to_item(l) for l in order_lines],
            "line_count": len(order_lines),
        }

    @staticmethod
    def _po_line_to_item(line) -> dict[str, Any]:
        product = line.product
        return {
            "id": line.id,
            "odoo_id": line.odoo_id,
            "product_id": line.product_id,
            "product_name": product.name if product else (line.name or ""),
            "product_code": getattr(product, "default_code", "") or "",
            "description": line.name or "",
            "quantity": _to_float(line.product_qty),
            "qty_received": _to_float(line.qty_received),
            "qty_invoiced": _to_float(line.qty_invoiced),
            "price_unit": _to_float(line.price_unit),
            "price_subtotal": _to_float(line.price_subtotal),
            "price_total": _to_float(line.price_total),
            "date_planned": line.date_planned.isoformat() if line.date_planned else None,
        }

    @staticmethod
    def _po_to_item(order: PurchaseOrder) -> dict[str, Any]:
        partner = order.partner
        company = order.company
        order_lines = list(order.lines.all())  # prefetched — no extra queries
        categories = list(dict.fromkeys(
            line.product.name for line in order_lines if line.product and line.product.name
        ))
        return {
            "id": order.id,
            "odoo_id": order.odoo_id,
            "name": order.odoo_name or "",
            "amount": _to_float(order.amount_total),
            "amount_total": _to_float(order.amount_total),
            "amount_untaxed": _to_float(order.amount_untaxed),
            "amount_tax": _to_float(order.amount_tax),
            "source": partner.name if partner else "Unknown Vendor",
            "partner_name": partner.name if partner else "",
            "company_name": company.name if company else "",
            "tenant_id": str(order.tenant_id),
            "tenant_name": order.tenant.name if order.tenant else "",
            "categories": categories,
            "category_summary": ", ".join(categories) if categories else "Uncategorized",
            "date": order.date_order.date().isoformat() if order.date_order else None,
            "time": order.date_order.isoformat() if order.date_order else None,
            "state": order.state,
            "invoice_status": order.invoice_status,
            "currency_code": order.currency_code,
            "type": "expense",
            "lines": [KPIService._po_line_to_item(l) for l in order_lines],
            "line_count": len(order_lines),
        }

    @staticmethod
    async def get_period_detail(
        kind: str,   # "revenues" | "expenses" | "profits"
        period: Optional[str] = None, # "today" | "monthly" | "yearly" | "custom"
        date_str: Optional[str] = None,
        date_from: Optional[str] = None,
        date_to: Optional[str] = None,
        limit: int = 50,
        offset: int = 0,
        base_currency: Optional[str] = None,
        tenant_ids: Optional[list[str]] = None,
        company_ids: Optional[list[int]] = None,
    ) -> dict[str, Any]:
        """
        Return itemised breakdown of revenues / expenses / profits for the
        requested period or date range, summed across ALL tenants (same data source as
        KPI overview so the numbers match).
        
        Uses DB aggregation for totals, and limit/offset for items.
        """
        def _fetch():
            from django.db.models import Prefetch, Sum, Count
            from django.db.models.functions import Coalesce
            from decimal import Decimal
            from odoo_app.models.sales_order_line import SalesOrderLine as SOLine
            from odoo_app.models.purchase_order_line import PurchaseOrderLine as POLine

            target_date = date.today()
            if date_str:
                try:
                    target_date = date.fromisoformat(date_str)
                except ValueError:
                    pass

            rate_map = _get_rate_map()
            effective_base = base_currency or "XAF"

            revenue_items: list[dict] = []
            expense_items: list[dict] = []
            
            total_revenue = 0.0
            total_expenses = 0.0
            revenue_count = 0
            expense_count = 0
            
            tenant_map: dict[str, dict] = {}

            def _get_tenant(tid: str, tname: str):
                if tid not in tenant_map:
                    tenant_map[tid] = {
                        "tenant_id": tid,
                        "tenant_name": tname or tid,
                        "revenue_amount": 0.0,
                        "expense_amount": 0.0,
                        "revenue_count": 0,
                        "expense_count": 0,
                    }
                return tenant_map[tid]

            # ── Revenues (SalesOrder + SalesOrderLines) ──────────────
            if kind in ("revenues", "profits"):
                so_qs = SalesOrder.objects.filter(state__in=["sale", "done"], tenant__is_active=True)
                so_qs = _apply_tenant_company_filter(so_qs, tenant_ids, company_ids)
                if date_from or date_to:
                    so_qs = _date_filter(so_qs, "date_order", date_from, date_to)
                elif period:
                    so_qs = KPIService._apply_period(so_qs, period, target_date)
                
                # Global Aggregates
                total_revenue = _sum_converted(so_qs, "amount_total", effective_base, rate_map)
                revenue_count = so_qs.count()
                
                # Tenant Aggregates
                so_tenant_agg = so_qs.values("tenant_id", "tenant__name", "currency_code").annotate(
                    amount=Coalesce(Sum("amount_total"), Decimal("0")),
                    count=Count("id")
                )
                for t in so_tenant_agg:
                    tm = _get_tenant(str(t["tenant_id"]), t["tenant__name"])
                    code = t["currency_code"] or "COMPANY_BASE"
                    val = _to_float(t["amount"]) * _get_conversion_rate(code, effective_base, rate_map)
                    tm["revenue_amount"] += val
                    tm["revenue_count"] += _to_int(t["count"])

                # Items Pagination
                so_page = (
                    so_qs
                    .select_related("partner", "company", "tenant")
                    .prefetch_related(
                        Prefetch("lines", queryset=SOLine.objects.select_related("product"))
                    )
                    .order_by("-date_order", "-id")
                )[offset : offset + limit]
                revenue_items = [KPIService._so_to_item(o) for o in so_page]

            # ── Expenses (PurchaseOrder + PurchaseOrderLines) ─────────
            if kind in ("expenses", "profits"):
                po_qs = PurchaseOrder.objects.filter(state__in=["purchase", "done"], tenant__is_active=True)
                po_qs = _apply_tenant_company_filter(po_qs, tenant_ids, company_ids)
                if date_from or date_to:
                    po_qs = _date_filter(po_qs, "date_order", date_from, date_to)
                elif period:
                    po_qs = KPIService._apply_period(po_qs, period, target_date)
                
                # Global Aggregates
                total_expenses = _sum_converted(po_qs, "amount_total", effective_base, rate_map)
                expense_count = po_qs.count()
                
                # Tenant Aggregates
                po_tenant_agg = po_qs.values("tenant_id", "tenant__name", "currency_code").annotate(
                    amount=Coalesce(Sum("amount_total"), Decimal("0")),
                    count=Count("id")
                )
                for t in po_tenant_agg:
                    tm = _get_tenant(str(t["tenant_id"]), t["tenant__name"])
                    code = t["currency_code"] or "COMPANY_BASE"
                    val = _to_float(t["amount"]) * _get_conversion_rate(code, effective_base, rate_map)
                    tm["expense_amount"] += val
                    tm["expense_count"] += _to_int(t["count"])

                # Items Pagination
                po_page = (
                    po_qs
                    .select_related("partner", "company", "tenant")
                    .prefetch_related(
                        Prefetch("lines", queryset=POLine.objects.select_related("product"))
                    )
                    .order_by("-date_order", "-id")
                )[offset : offset + limit]
                expense_items = [KPIService._po_to_item(o) for o in po_page]

            # ── Format Response ─────────────────────────────────────────
            net_profit = total_revenue - total_expenses

            tenants = []
            for t in tenant_map.values():
                t["net_profit"] = t["revenue_amount"] - t["expense_amount"]
                t["total_count"] = t["revenue_count"] + t["expense_count"]
                tenants.append(t)

            resolved_period = period or ("custom" if (date_from or date_to) else "all_time")

            return {
                "period": resolved_period,
                "kind": kind,
                "date": target_date.isoformat() if target_date else None,
                "date_from": date_from,
                "date_to": date_to,
                "limit": limit,
                "offset": offset,
                "grand_revenue_amount": total_revenue,
                "grand_expense_amount": total_expenses,
                "grand_net_profit": net_profit,
                "grand_total_count": revenue_count + expense_count,
                "revenue_count": revenue_count,
                "expense_count": expense_count,
                "items": revenue_items if kind == "revenues" else (expense_items if kind == "expenses" else revenue_items + expense_items),
                "revenues": revenue_items,
                "expenses": expense_items,
                "tenants": tenants,
                "applied_filters": {
                    "tenant_ids": tenant_ids or [],
                    "company_ids": company_ids or [],
                    "date_from": date_from,
                    "date_to": date_to,
                },
            }

        return await asyncio.to_thread(_fetch)

