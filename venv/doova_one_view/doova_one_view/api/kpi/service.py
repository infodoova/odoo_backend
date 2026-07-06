from __future__ import annotations

import asyncio
from datetime import date, timedelta
from decimal import Decimal
from typing import Any, Optional

from django.db.models import Avg, Count, DecimalField, ExpressionWrapper, F, Q, Sum, Value
from django.db.models.functions import Coalesce, TruncMonth

from odoo_app.models import AccountMove, PurchaseOrder, SalesOrder, SalesOrderLine, StockQuant
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
        date_from: Optional[str],
        date_to: Optional[str],
    ) -> dict[str, Any]:
        def _get():
            today = date.today()
            # Dashboard metrics (Today/Month/Year) - Independent of filters
            dashboard_sales = SalesOrder.objects.filter(state__in=["sale", "done"])
            dashboard_purchases = PurchaseOrder.objects.filter(state__in=["purchase", "done"])

            revenue_today = _sum(dashboard_sales.filter(date_order__date=today), "amount_total")
            revenue_month = _sum(dashboard_sales.filter(date_order__year=today.year, date_order__month=today.month), "amount_total")
            revenue_year = _sum(dashboard_sales.filter(date_order__year=today.year), "amount_total")
            
            expenses_today = _sum(dashboard_purchases.filter(date_order__date=today), "amount_total")
            expenses_month = _sum(dashboard_purchases.filter(date_order__year=today.year, date_order__month=today.month), "amount_total")
            expenses_year = _sum(dashboard_purchases.filter(date_order__year=today.year), "amount_total")

            # Receivables and Inventory - Independent of filters
            receivables = AccountMove.objects.filter(
                state="posted",
                move_type="out_invoice",
                payment_state__in=["not_paid", "partial", "in_payment"],
            )
            receivables_value = _sum(receivables, "amount_residual")
            overdue_value = _sum(receivables.filter(invoice_date_due__lt=today), "amount_residual")

            inventory_expr = ExpressionWrapper(
                F("quantity") * Coalesce(F("product__standard_price"), Value(0)),
                output_field=DecimalField(max_digits=20, decimal_places=4),
            )
            # Only count positive inventory for the dashboard value
            quants = StockQuant.objects.filter(quantity__gt=0)
            inventory_value = _to_float(quants.aggregate(value=Coalesce(Sum(inventory_expr), Decimal("0")))["value"])

            # Historical Metrics - Dependent on filters
            sales = SalesOrder.objects.filter(state__in=["sale", "done"])
            sales = _date_filter(sales, "date_order", date_from, date_to)
            
            # ── Inventory Risk Metrics ─────────────────────────────
            quant_stats = StockQuant.objects.aggregate(
                total_qty=Coalesce(Sum("quantity"), Decimal("0")),
                total_reserved=Coalesce(Sum("reserved_quantity"), Decimal("0")),
            )
            total_qty = _to_float(quant_stats["total_qty"])
            total_reserved = _to_float(quant_stats["total_reserved"])
            reservation_pressure = (total_reserved / total_qty * 100) if total_qty > 0 else 0.0

            # Low Stock: Products with quantity < 5 (Threshold)
            low_stock_count = StockQuant.objects.filter(quantity__lt=5, quantity__gt=0).count()

            # Expiring Soon: Lots expiring in the next 30 days with positive quantity
            thirty_days_later = today + timedelta(days=30)
            expiring_soon_count = StockQuant.objects.filter(
                lot__expiration_date__range=(today, thirty_days_later),
                quantity__gt=0
            ).count()

            # Dead Stock: Products with stock but no sales in the last 90 days
            ninety_days_ago = today - timedelta(days=90)
            sold_product_ids = SalesOrderLine.objects.filter(
                sales_order__date_order__gte=ninety_days_ago,
                sales_order__state__in=["sale", "done"]
            ).values_list("product_id", flat=True).distinct()
            
            dead_stock_quants = StockQuant.objects.filter(quantity__gt=0).exclude(product_id__in=sold_product_ids)
            dead_stock_product_count = dead_stock_quants.values("product_id").distinct().count()
            total_sku_count = StockQuant.objects.filter(quantity__gt=0).values("product_id").distinct().count()
            dead_stock_rate = (dead_stock_product_count / total_sku_count * 100) if total_sku_count > 0 else 0.0

            # ── Return Values ─────────────────────────────────────
            if not sales.exists():
                return {
                    "kpis": {
                        "dashboard_revenue": {"today": revenue_today, "month": revenue_month, "year": revenue_year},
                        "dashboard_expenses": {"today": expenses_today, "month": expenses_month, "year": expenses_year},
                        "dashboard_profit": {
                            "today": revenue_today - expenses_today,
                            "month": revenue_month - expenses_month,
                            "year": revenue_year - expenses_year,
                        },
                        "revenue": _metric(0),
                        "gross_margin": _metric(0),
                        "orders": _metric(0),
                        "average_order_value": _metric(0),
                        "receivables": {"value": receivables_value, "overdue": overdue_value},
                        "inventory_value": {"value": inventory_value},
                        "inventory_risk": {
                            "inventory_reservation_pressure_pct": reservation_pressure,
                            "dead_stock_rate_pct": dead_stock_rate,
                            "dead_stock_product_count": dead_stock_product_count,
                            "low_stock_count": low_stock_count,
                            "expiring_soon_count": expiring_soon_count
                        },
                    },
                    "tenant_benchmarks": [],
                    "applied_filters": {
                        "tenant_ids": [],
                        "date_from": date_from,
                        "date_to": date_to,
                        "company_ids": [],
                    },
                }

            purchases = PurchaseOrder.objects.filter(state__in=["purchase", "done"])
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
                    "inventory_risk": {
                        "inventory_reservation_pressure_pct": reservation_pressure,
                        "dead_stock_rate_pct": dead_stock_rate,
                        "dead_stock_product_count": dead_stock_product_count,
                        "low_stock_count": low_stock_count,
                        "expiring_soon_count": expiring_soon_count
                    },
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
                    "tenant_ids": [],
                    "date_from": date_from,
                    "date_to": date_to,
                    "company_ids": [],
                },
            }

        return await asyncio.to_thread(_get)

    @staticmethod
    async def get_trends(
        date_from: Optional[str],
        date_to: Optional[str],
    ) -> dict[str, Any]:
        def _get():
            sales = SalesOrder.objects.filter(state__in=["sale", "done"])
            sales = _date_filter(sales, "date_order", date_from, date_to)
            purchases = PurchaseOrder.objects.filter(state__in=["purchase", "done"])
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

            tenant_sales = list(
                sales.annotate(month=TruncMonth("date_order"))
                .values("month", "tenant__name")
                .annotate(revenue=Coalesce(Sum("amount_total"), Decimal("0")))
                .order_by("month")
            )
            
            tenant_revenue = []
            for row in tenant_sales:
                if not row["month"]:
                    continue
                tenant_revenue.append({
                    "month": row["month"].strftime("%Y-%m"),
                    "tenant_name": row["tenant__name"] or "Unknown Tenant",
                    "revenue": _to_float(row["revenue"])
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
                "applied_filters": {"tenant_ids": [], "date_from": date_from, "date_to": date_to, "company_ids": []},
            }

        return await asyncio.to_thread(_get)

    @staticmethod
    async def get_top_products(limit: int, descending: bool = True) -> dict[str, Any]:
        def _get():
            lines = SalesOrderLine.objects.filter(sales_order__state__in=["sale", "done"])
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
    async def get_top_customers(limit: int) -> dict[str, Any]:
        def _get():
            sales = SalesOrder.objects.filter(state__in=["sale", "done"])
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
    async def get_receivables_aging() -> dict[str, Any]:
        def _get():
            today = date.today()
            receivables = AccountMove.objects.filter(
                state="posted",
                move_type="out_invoice",
                payment_state__in=["not_paid", "partial", "in_payment"],
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
    async def get_fast_moving_products(limit: int) -> dict[str, Any]:
        top = await KPIService.get_top_products(limit, descending=True)
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
    async def get_category_performance() -> dict[str, Any]:
        def _get():
            lines = SalesOrderLine.objects.filter(sales_order__state__in=["sale", "done"])
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
    async def get_currency_impact() -> dict[str, Any]:
        def _get():
            sales = SalesOrder.objects.filter(state__in=["sale", "done"])
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
        period: str, # "today"    | "monthly"  | "yearly"
        date_str: Optional[str] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> dict[str, Any]:
        """
        Return itemised breakdown of revenues / expenses / profits for the
        requested period, summed across ALL tenants (same data source as
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
                so_qs = SalesOrder.objects.filter(state__in=["sale", "done"])
                so_qs = KPIService._apply_period(so_qs, period, target_date)
                
                # Global Aggregates
                so_agg = so_qs.aggregate(amount=Coalesce(Sum("amount_total"), Decimal("0")), count=Count("id"))
                total_revenue = _to_float(so_agg["amount"])
                revenue_count = _to_int(so_agg["count"])
                
                # Tenant Aggregates
                so_tenant_agg = so_qs.values("tenant_id", "tenant__name").annotate(
                    amount=Coalesce(Sum("amount_total"), Decimal("0")),
                    count=Count("id")
                )
                for t in so_tenant_agg:
                    tm = _get_tenant(str(t["tenant_id"]), t["tenant__name"])
                    tm["revenue_amount"] += _to_float(t["amount"])
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
                po_qs = PurchaseOrder.objects.filter(state__in=["purchase", "done"])
                po_qs = KPIService._apply_period(po_qs, period, target_date)
                
                # Global Aggregates
                po_agg = po_qs.aggregate(amount=Coalesce(Sum("amount_total"), Decimal("0")), count=Count("id"))
                total_expenses = _to_float(po_agg["amount"])
                expense_count = _to_int(po_agg["count"])
                
                # Tenant Aggregates
                po_tenant_agg = po_qs.values("tenant_id", "tenant__name").annotate(
                    amount=Coalesce(Sum("amount_total"), Decimal("0")),
                    count=Count("id")
                )
                for t in po_tenant_agg:
                    tm = _get_tenant(str(t["tenant_id"]), t["tenant__name"])
                    tm["expense_amount"] += _to_float(t["amount"])
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

            return {
                "period": period,
                "kind": kind,
                "date": target_date.isoformat(),
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
            }

        return await asyncio.to_thread(_fetch)
