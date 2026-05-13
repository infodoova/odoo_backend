from __future__ import annotations

import asyncio
from datetime import date
from decimal import Decimal
from typing import Any, Optional

from django.db.models import Avg, Count, DecimalField, ExpressionWrapper, F, Q, Sum, Value
from django.db.models.functions import Coalesce, TruncMonth

from odoo_app.models import AccountMove, PurchaseOrder, SalesOrder, SalesOrderLine, StockQuant


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


def _company_filter(qs, company_ids: Optional[list[int]]):
    if company_ids:
        qs = qs.filter(company_id__in=company_ids)
    return qs


def _tenant_filter(qs, tenant_ids: list[str]):
    return qs.filter(tenant_id__in=tenant_ids)


def _date_filter(qs, field: str, date_from: Optional[str], date_to: Optional[str]):
    if date_from:
        qs = qs.filter(**{f"{field}__date__gte": date_from})
    if date_to:
        qs = qs.filter(**{f"{field}__date__lte": date_to})
    return qs


def _sum(qs, field: str) -> float:
    return _to_float(qs.aggregate(value=Coalesce(Sum(field), Decimal("0")))["value"])


def _empty_overview(tenant_ids: list[str], date_from, date_to, company_ids):
    return {
        "kpis": {
            "dashboard_revenue": {"today": 0.0, "month": 0.0, "year": 0.0},
            "dashboard_expenses": {"today": 0.0, "month": 0.0, "year": 0.0},
            "dashboard_profit": {"today": 0.0, "month": 0.0, "year": 0.0},
            "revenue": _metric(0),
            "gross_margin": _metric(0),
            "orders": _metric(0),
            "average_order_value": _metric(0),
            "receivables": {"value": 0.0, "overdue": 0.0},
            "inventory_value": {"value": 0.0},
        },
        "tenant_benchmarks": [],
        "applied_filters": {"tenant_ids": tenant_ids, "date_from": date_from, "date_to": date_to, "company_ids": company_ids},
    }


class KPIService:
    @staticmethod
    async def get_overview(
        tenant_ids: list[str],
        date_from: Optional[str],
        date_to: Optional[str],
        company_ids: Optional[list[int]] = None,
    ) -> dict[str, Any]:
        def _get():
            today = date.today()
            sales = _company_filter(_tenant_filter(SalesOrder.objects.filter(state__in=["sale", "done"]), tenant_ids), company_ids)
            sales = _date_filter(sales, "date_order", date_from, date_to)
            if not sales.exists():
                return _empty_overview(tenant_ids, date_from, date_to, company_ids)

            purchases = _company_filter(_tenant_filter(PurchaseOrder.objects.filter(state__in=["purchase", "done"]), tenant_ids), company_ids)
            purchases = _date_filter(purchases, "date_order", date_from, date_to)

            sales_stats = sales.aggregate(
                total_revenue=Coalesce(Sum("amount_total"), Decimal("0")),
                order_count=Count("id"),
                avg_order_value=Coalesce(Avg("amount_total"), Decimal("0")),
                gross_margin=Coalesce(Sum("margin"), Decimal("0")),
            )
            total_revenue = _to_float(sales_stats["total_revenue"])
            total_expenses = _sum(purchases, "amount_total")
            order_count = _to_int(sales_stats["order_count"])
            avg_order_value = _to_float(sales_stats["avg_order_value"])
            gross_margin_value = _to_float(sales_stats["gross_margin"]) or (total_revenue - total_expenses)
            gross_margin_pct = (gross_margin_value / total_revenue * 100) if total_revenue else 0.0

            revenue_today = _sum(sales.filter(date_order__date=today), "amount_total")
            revenue_month = _sum(sales.filter(date_order__year=today.year, date_order__month=today.month), "amount_total")
            revenue_year = _sum(sales.filter(date_order__year=today.year), "amount_total")
            expenses_today = _sum(purchases.filter(date_order__date=today), "amount_total")
            expenses_month = _sum(purchases.filter(date_order__year=today.year, date_order__month=today.month), "amount_total")
            expenses_year = _sum(purchases.filter(date_order__year=today.year), "amount_total")

            receivables = _company_filter(
                _tenant_filter(
                    AccountMove.objects.filter(
                    state="posted",
                    move_type="out_invoice",
                    payment_state__in=["not_paid", "partial", "in_payment"],
                ),
                    tenant_ids,
                ),
                company_ids,
            )
            receivables_value = _sum(receivables, "amount_residual")
            overdue_value = _sum(receivables.filter(invoice_date_due__lt=today), "amount_residual")

            inventory_expr = ExpressionWrapper(
                F("quantity") * Coalesce(F("product__standard_price"), Value(0)),
                output_field=DecimalField(max_digits=20, decimal_places=4),
            )
            quants = _company_filter(_tenant_filter(StockQuant.objects.all(), tenant_ids), company_ids)
            inventory_value = _to_float(quants.aggregate(value=Coalesce(Sum(inventory_expr), Decimal("0")))["value"])
            tenant_rows = list(
                sales.values("tenant_id", "tenant__name")
                .annotate(revenue=Coalesce(Sum("amount_total"), Decimal("0")), order_count=Count("id"), margin=Coalesce(Sum("margin"), Decimal("0")))
                .order_by("-revenue")
            )

            return {
                "kpis": {
                    "dashboard_revenue": {"today": revenue_today, "month": revenue_month, "year": revenue_year},
                    "dashboard_expenses": {"today": expenses_today, "month": expenses_month, "year": expenses_year},
                    "dashboard_profit": {
                        "today": revenue_today - expenses_today,
                        "month": revenue_month - expenses_month,
                        "year": revenue_year - expenses_year,
                    },
                    "revenue": _metric(total_revenue),
                    "gross_margin": _metric(gross_margin_pct),
                    "orders": _metric(order_count),
                    "average_order_value": _metric(avg_order_value),
                    "receivables": {"value": receivables_value, "overdue": overdue_value},
                    "inventory_value": {"value": inventory_value},
                },
                "tenant_benchmarks": [
                    {
                        "tenant_id": str(row["tenant_id"]),
                        "tenant_name": row["tenant__name"] or str(row["tenant_id"]),
                        "revenue": _to_float(row["revenue"]),
                        "order_count": _to_int(row["order_count"]),
                        "margin": _to_float(row["margin"]),
                        "margin_rate_pct": (_to_float(row["margin"]) / _to_float(row["revenue"]) * 100) if _to_float(row["revenue"]) else 0.0,
                    }
                    for row in tenant_rows
                ],
                "applied_filters": {
                    "tenant_ids": tenant_ids,
                    "date_from": date_from,
                    "date_to": date_to,
                    "company_ids": company_ids,
                },
            }

        return await asyncio.to_thread(_get)

    @staticmethod
    async def get_trends(
        tenant_ids: list[str],
        date_from: Optional[str],
        date_to: Optional[str],
        company_ids: Optional[list[int]] = None,
    ) -> dict[str, Any]:
        def _get():
            sales = _company_filter(_tenant_filter(SalesOrder.objects.filter(state__in=["sale", "done"]), tenant_ids), company_ids)
            sales = _date_filter(sales, "date_order", date_from, date_to)
            purchases = _company_filter(_tenant_filter(PurchaseOrder.objects.filter(state__in=["purchase", "done"]), tenant_ids), company_ids)
            purchases = _date_filter(purchases, "date_order", date_from, date_to)

            sales_rows = list(
                sales.annotate(month=TruncMonth("date_order"))
                .values("month")
                .annotate(revenue=Coalesce(Sum("amount_total"), Decimal("0")), orders=Count("id"), margin=Coalesce(Sum("margin"), Decimal("0")))
                .order_by("month")
            )
            purchase_rows = list(
                purchases.annotate(month=TruncMonth("date_order"))
                .values("month")
                .annotate(expenses=Coalesce(Sum("amount_total"), Decimal("0")))
                .order_by("month")
            )

            expense_by_month = {r["month"].strftime("%Y-%m"): _to_float(r["expenses"]) for r in purchase_rows if r["month"]}
            revenue_trend = []
            orders_trend = []
            profit_trend = []
            margin_trend = []

            for row in sales_rows:
                if not row["month"]:
                    continue
                key = row["month"].strftime("%Y-%m")
                revenue = _to_float(row["revenue"])
                expenses = expense_by_month.get(key, 0.0)
                profit = revenue - expenses
                margin_pct = (profit / revenue * 100) if revenue else 0.0
                revenue_trend.append({"month": key, "date": key, "value": revenue})
                orders_trend.append({"month": key, "date": key, "value": _to_float(row["orders"])})
                profit_trend.append({"month": key, "date": key, "value": profit, "profit": profit})
                margin_trend.append({"month": key, "date": key, "value": margin_pct, "margin": profit, "margin_pct": margin_pct})

            procurement_trend = [
                {"month": r["month"].strftime("%Y-%m"), "date": r["month"].strftime("%Y-%m"), "value": _to_float(r["expenses"])}
                for r in purchase_rows
                if r["month"]
            ]

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
                    "tenant_revenue": revenue_trend,
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
                "applied_filters": {"tenant_ids": tenant_ids, "date_from": date_from, "date_to": date_to, "company_ids": company_ids},
            }

        return await asyncio.to_thread(_get)

    @staticmethod
    async def get_top_products(tenant_ids: list[str], limit: int, company_ids: Optional[list[int]] = None, descending: bool = True) -> dict[str, Any]:
        def _get():
            lines = _tenant_filter(SalesOrderLine.objects.filter(sales_order__state__in=["sale", "done"]), tenant_ids)
            lines = _company_filter(lines, company_ids)
            ordering = "-revenue" if descending else "revenue"
            rows = list(
                lines.values("product_id", "product__name", "product__default_code")
                .annotate(
                    revenue=Coalesce(Sum("price_subtotal"), Decimal("0")),
                    quantity=Coalesce(Sum("product_uom_qty"), Decimal("0")),
                    margin=Coalesce(Sum("margin"), Decimal("0")),
                )
                .order_by(ordering)[:limit]
            )
            products = []
            for row in rows:
                revenue = _to_float(row["revenue"])
                margin = _to_float(row["margin"])
                products.append({
                    "id": _to_int(row["product_id"]),
                    "name": row["product__name"] or "Unknown Product",
                    "product__name": row["product__name"] or "Unknown Product",
                    "product__default_code": row["product__default_code"] or "",
                    "revenue": revenue,
                    "quantity": _to_float(row["quantity"]),
                    "margin_pct": (margin / revenue * 100) if revenue else 0.0,
                })
            return {"products": products, "items": products, "total": len(products)}

        return await asyncio.to_thread(_get)

    @staticmethod
    async def get_top_customers(tenant_ids: list[str], limit: int, company_ids: Optional[list[int]] = None) -> dict[str, Any]:
        def _get():
            sales = _company_filter(_tenant_filter(SalesOrder.objects.filter(state__in=["sale", "done"]), tenant_ids), company_ids)
            rows = list(
                sales.values("partner_id", "partner__name")
                .annotate(revenue=Coalesce(Sum("amount_total"), Decimal("0")), orders=Count("id"))
                .order_by("-revenue")[:limit]
            )
            customers = [
                {"id": _to_int(r["partner_id"]), "name": r["partner__name"] or "Unknown Customer", "revenue": _to_float(r["revenue"]), "orders": _to_int(r["orders"])}
                for r in rows
            ]
            return {"customers": customers, "items": customers, "total": len(customers)}

        return await asyncio.to_thread(_get)

    @staticmethod
    async def get_receivables_aging(tenant_ids: list[str], company_ids: Optional[list[int]] = None) -> dict[str, Any]:
        def _get():
            today = date.today()
            receivables = _company_filter(
                _tenant_filter(
                    AccountMove.objects.filter(
                    state="posted",
                    move_type="out_invoice",
                    payment_state__in=["not_paid", "partial", "in_payment"],
                ),
                    tenant_ids,
                ),
                company_ids,
            )
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
            return {"buckets": buckets, "total_receivables": sum(bucket["amount"] for bucket in buckets), "overdue_total": overdue_total}

        return await asyncio.to_thread(_get)

    @staticmethod
    async def get_fast_moving_products(tenant_ids: list[str], limit: int, company_ids: Optional[list[int]] = None) -> dict[str, Any]:
        top = await KPIService.get_top_products(tenant_ids, limit, company_ids, descending=True)
        items = [
            {
                "id": item["id"],
                "name": item["name"],
                "quantity_sold": item["quantity"],
                "velocity": "high" if item["quantity"] >= 10 else "medium",
            }
            for item in top.get("products", [])
        ]
        return {"items": items, "products": items, "total": len(items)}

    @staticmethod
    async def get_category_performance(tenant_ids: list[str], company_ids: Optional[list[int]] = None) -> dict[str, Any]:
        def _get():
            lines = _tenant_filter(SalesOrderLine.objects.filter(sales_order__state__in=["sale", "done"]), tenant_ids)
            lines = _company_filter(lines, company_ids)
            rows = list(
                lines.values("product__category_id", "product__category__complete_name", "product__category__name")
                .annotate(revenue=Coalesce(Sum("price_subtotal"), Decimal("0")), margin=Coalesce(Sum("margin"), Decimal("0")))
                .order_by("-revenue")
            )
            items = []
            for row in rows:
                revenue = _to_float(row["revenue"])
                margin = _to_float(row["margin"])
                items.append({
                    "id": _to_int(row["product__category_id"]),
                    "category": row["product__category__complete_name"] or row["product__category__name"] or "Uncategorized",
                    "revenue": revenue,
                    "margin_pct": (margin / revenue * 100) if revenue else 0.0,
                })
            return {"items": items, "categories": items, "total": len(items)}

        return await asyncio.to_thread(_get)

    @staticmethod
    async def get_currency_impact(tenant_ids: list[str], company_ids: Optional[list[int]] = None) -> dict[str, Any]:
        def _get():
            sales = _company_filter(_tenant_filter(SalesOrder.objects.filter(state__in=["sale", "done"]), tenant_ids), company_ids)
            rows = list(
                sales.values("currency_code")
                .annotate(revenue=Coalesce(Sum("amount_total"), Decimal("0")))
                .order_by("-revenue")
            )
            total = sum(_to_float(r["revenue"]) for r in rows) or 1.0
            items = [
                {"currency": r["currency_code"] or "Unknown", "revenue": _to_float(r["revenue"]), "percentage": (_to_float(r["revenue"]) / total) * 100}
                for r in rows
            ]
            return {"items": items, "currencies": items, "base_currency": items[0]["currency"] if items else "USD"}

        return await asyncio.to_thread(_get)
