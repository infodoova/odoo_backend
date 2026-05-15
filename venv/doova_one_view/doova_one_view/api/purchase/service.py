"""
Purchase API service.
"""

import asyncio
from typing import Any, Optional

from django.db.models import Avg, Count, Prefetch, Sum
from django.db.models import Q
from django.db.models.functions import TruncDate

from odoo_app.models.purchase_order import PurchaseOrder
from odoo_app.models.purchase_order_line import PurchaseOrderLine
from doova_one_view.api.common.exceptions import NotFoundError


def _to_float(value: Any) -> float:
    if value is None:
        return 0.0
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _s(value: Any) -> str:
    if value is None:
        return ""
    return str(value)


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


def _partner_obj(order: PurchaseOrder) -> Optional[dict[str, Any]]:
    partner = getattr(order, "partner", None)
    if partner is None:
        return None
    return {
        "id": partner.id,
        "odoo_id": partner.odoo_id,
        "name": partner.name,
        "ref": _s(getattr(order, "partner_ref", None)),
        "email": getattr(partner, "email", None),
        "phone": getattr(partner, "phone", None),
        "country_code": getattr(partner, "country_code", None),
        "city": getattr(partner, "city", None),
        "is_customer": getattr(partner, "is_customer", False),
        "is_supplier": getattr(partner, "is_supplier", False),
    }


def _user_obj(order: PurchaseOrder) -> Optional[dict[str, Any]]:
    user = getattr(order, "user", None)
    if user is None:
        return None
    return {
        "id": user.id,
        "odoo_id": user.odoo_id,
        "name": user.name,
        "email": getattr(user, "email", None),
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


def _product_obj(line: PurchaseOrderLine) -> Optional[dict[str, Any]]:
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


def _order_to_item(order: PurchaseOrder) -> dict[str, Any]:
    amount_total = _to_float(order.amount_total)
    amount_untaxed = _to_float(order.amount_untaxed)
    amount_tax = _to_float(getattr(order, "amount_tax", 0))
    if amount_tax == 0.0 and amount_total != amount_untaxed:
        amount_tax = round(amount_total - amount_untaxed, 2)

    partner = _partner_obj(order)
    user = _user_obj(order)
    company = _company_obj(order)
    partner_name = partner["name"] if partner else ""

    return {
        "id": order.id,
        "odoo_id": order.odoo_id,
        "name": order.odoo_name or "",
        "odoo_name": order.odoo_name,
        "date_order": _iso(order.date_order),
        "date_approve": _iso(getattr(order, "date_approve", None)),
        "date_planned": _iso(getattr(order, "date_planned", None)),
        "state": order.state,
        "invoice_status": order.invoice_status,
        "amount_untaxed": amount_untaxed,
        "amount_tax": amount_tax,
        "amount_total": amount_total,
        "currency": order.currency_code,
        "currency_code": order.currency_code,
        "synced_at": _iso(order.synced_at),
        "partner": partner,
        "vendor": partner,
        "partner_id": getattr(order, "partner_id", None),
        "partner_name": partner_name,
        "partner_ref": _s(getattr(order, "partner_ref", None)),
        "partner_email": partner.get("email") if partner else "",
        "partner_phone": partner.get("phone") if partner else "",
        "partner_city": partner.get("city") if partner else "",
        "vendor_id": getattr(order, "partner_id", None),
        "vendor_name": partner_name,
        "user": user,
        "user_id": getattr(order, "user_id", None),
        "user_name": user["name"] if user else "",
        "company": company,
        "company_id": getattr(order, "company_id", None),
        "company_name": company["name"] if company else "",
    }


def _line_to_item(line: PurchaseOrderLine) -> dict[str, Any]:
    product = _product_obj(line)
    product_qty = _to_float(line.product_qty)
    qty_received = _to_float(line.qty_received)
    qty_invoiced = _to_float(line.qty_invoiced)
    price_subtotal = _to_float(line.price_subtotal)
    price_total = _to_float(line.price_total)

    return {
        "id": line.id,
        "odoo_id": line.odoo_id,
        "product": product,
        "product_id": getattr(line, "product_id", None),
        "product_name": product["name"] if product else "",
        "product_code": product.get("default_code") if product else "",
        "uom": product.get("uom_name") if product else "",
        "name": line.name or "",
        "company": _company_obj(line),
        "company_id": getattr(line, "company_id", None),
        "date_planned": _iso(getattr(line, "date_planned", None)),
        "product_qty": product_qty,
        "quantity": product_qty,
        "qty": product_qty,
        "product_uom_qty": product_qty,
        "qty_received": qty_received,
        "received_qty": qty_received,
        "qty_delivered": qty_received,
        "qty_invoiced": qty_invoiced,
        "billed_qty": qty_invoiced,
        "price_unit": _to_float(line.price_unit),
        "price_subtotal": price_subtotal,
        "subtotal": price_subtotal,
        "price_total": price_total,
        "total": price_total,
        "discount": 0.0,
        "margin": 0.0,
        "purchase_price": 0.0,
        "synced_at": _iso(line.synced_at),
    }


class PurchaseService:
    """Service for purchase operations."""

    @staticmethod
    def _base_qs(tenant_id: str, company_ids: Optional[list[int]] = None):
        qs = PurchaseOrder.objects.filter(tenant_id=tenant_id)
        if company_ids:
            qs = qs.filter(company_id__in=company_ids)
        return qs

    @staticmethod
    def _date_qs(qs, start_date: Optional[str], end_date: Optional[str]):
        if start_date:
            qs = qs.filter(date_order__date__gte=start_date)
        if end_date:
            qs = qs.filter(date_order__date__lte=end_date)
        return qs

    @staticmethod
    async def get_orders(
        tenant_id: str,
        limit: int = 50,
        offset: int = 0,
        partner_id: Optional[int] = None,
        company_ids: Optional[list[int]] = None,
    ) -> dict[str, Any]:
        def _list():
            qs = PurchaseService._base_qs(tenant_id, company_ids)
            if partner_id is not None:
                qs = qs.filter(partner_id=partner_id)
            total = qs.count()
            orders = list(
                qs.select_related("partner", "user", "company")
                .order_by("-date_order", "-id")[offset : offset + limit]
            )
            return orders, total

        orders, total = await asyncio.to_thread(_list)
        return {
            "items": [_order_to_item(o) for o in orders],
            "total": total,
            "limit": limit,
            "offset": offset,
            "applied_filters": {
                "tenant_id": tenant_id,
                "partner_id": partner_id,
                "company_ids": company_ids,
            },
        }

    @staticmethod
    async def get_order(
        tenant_id: str,
        order_id: int,
        company_ids: Optional[list[int]] = None,
    ) -> dict[str, Any]:
        def _get():
            qs = PurchaseService._base_qs(tenant_id, company_ids)
            try:
                return (
                    qs.select_related("partner", "user", "company")
                    .prefetch_related(
                        Prefetch(
                            "lines",
                            queryset=PurchaseOrderLine.objects.select_related("product", "company"),
                        )
                    )
                    .get(id=order_id)
                )
            except PurchaseOrder.DoesNotExist:
                raise NotFoundError("PurchaseOrder", str(order_id))

        order = await asyncio.to_thread(_get)
        item = _order_to_item(order)
        item["lines"] = [_line_to_item(line) for line in order.lines.all()]
        return item

    @staticmethod
    async def get_summary(
        tenant_id: str,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        company_ids: Optional[list[int]] = None,
    ) -> dict[str, Any]:
        def _summary():
            qs = PurchaseService._date_qs(
                PurchaseService._base_qs(tenant_id, company_ids), start_date, end_date
            )
            stats = qs.aggregate(
                total_count=Count("id"),
                total_amount=Sum("amount_total"),
                average_order_value=Avg("amount_total"),
            )
            total_count = stats["total_count"] or 0
            billed_count = qs.filter(invoice_status="invoiced").count()
            return {
                "total_count": total_count,
                "total_amount": _to_float(stats["total_amount"]),
                "average_order_value": _to_float(stats["average_order_value"]),
                "billed_percentage": (billed_count / total_count * 100) if total_count else 0.0,
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
    ) -> dict[str, Any]:
        def _dashboard():
            qs = PurchaseService._date_qs(
                PurchaseService._base_qs(tenant_id, company_ids), start_date, end_date
            )
            stats = qs.aggregate(
                total_spend=Sum("amount_total"),
                order_count=Count("id"),
                avg_order_value=Avg("amount_total"),
            )
            total_spend = _to_float(stats["total_spend"])
            order_count = stats["order_count"] or 0
            avg_order_value = _to_float(stats["avg_order_value"])

            top_vendors = [
                {
                    "id": row["partner_id"],
                    "name": row["partner__name"] or "",
                    "value": _to_float(row["spend"]),
                    "spend": _to_float(row["spend"]),
                    "count": row["order_count"],
                    "orders": row["order_count"],
                }
                for row in qs.values("partner_id", "partner__name")
                .annotate(spend=Sum("amount_total"), order_count=Count("id"))
                .order_by("-spend")[:5]
            ]
            spend_trend = [
                {"date": _iso(row["day"]), "value": _to_float(row["spend"]), "spend": _to_float(row["spend"])}
                for row in qs.annotate(day=TruncDate("date_order"))
                .values("day")
                .annotate(spend=Sum("amount_total"))
                .order_by("day")
            ]
            state_distribution = {
                row["state"] or "unknown": row["state_count"]
                for row in qs.values("state").annotate(state_count=Count("id"))
            }
            applied = {
                "tenant_id": tenant_id,
                "start_date": start_date,
                "end_date": end_date,
                "company_ids": company_ids,
            }
            return {
                "total_purchase": _metric(total_spend),
                "total_purchase_value": total_spend,
                "total_spend": _metric(total_spend),
                "total_spend_value": total_spend,
                "avg_order_value": _metric(avg_order_value),
                "avg_order_value_value": avg_order_value,
                "average_order_value": _metric(avg_order_value),
                "average_order_value_value": avg_order_value,
                "outstanding_value": _metric(0.0),
                "outstanding_value_value": 0.0,
                "order_count": order_count,
                "draft_count": state_distribution.get("draft", 0),
                "confirmed_count": state_distribution.get("purchase", 0)
                + state_distribution.get("to approve", 0),
                "received_percentage": 0.0,
                "avg_lead_time_days": 0.0,
                "avg_fulfillment_rate": 0.0,
                "avg_approval_time_hrs": 0.0,
                "vendor_concentration_ratio": 0.0,
                "spend_summary": {
                    "today": 0.0,
                    "month": 0.0,
                    "year": 0.0,
                    "all_time": total_spend,
                },
                "top_vendors": top_vendors,
                "top_suppliers": top_vendors,
                "top_products": [],
                "spend_trend": spend_trend,
                "state_distribution": state_distribution,
                "applied_filters": applied,
            }

        return await asyncio.to_thread(_dashboard)

    @staticmethod
    async def get_filters(tenant_id: str) -> dict[str, Any]:
        def _filters():
            qs = PurchaseOrder.objects.filter(tenant_id=tenant_id)
            states = [s for s in qs.values_list("state", flat=True).distinct() if s]
            currencies = [c for c in qs.values_list("currency_code", flat=True).distinct() if c]
            partners = [
                {"id": row["partner_id"], "name": row["partner__name"] or ""}
                for row in qs.filter(partner_id__isnull=False)
                .values("partner_id", "partner__name")
                .distinct()
                .order_by("partner__name")
            ]
            vendor_names = [p["name"] for p in partners if p["name"]]
            static_states = ["draft", "sent", "to approve", "purchase", "done", "cancel"]
            return {
                "state": states or static_states,
                "states": states or static_states,
                "currencies": currencies,
                "vendor_names": vendor_names,
                "partners": partners,
            }

        return await asyncio.to_thread(_filters)

    @staticmethod
    async def search_orders(
        tenant_id: str,
        filters: list[Any],
        limit: int,
        offset: int,
        company_ids: Optional[list[int]] = None,
    ) -> dict[str, Any]:
        def _search():
            qs = PurchaseService._base_qs(tenant_id, company_ids)
            field_map = {
                "odoo_id": "odoo_id",
                "odoo_name": "odoo_name",
                "name": "odoo_name",
                "partner_name": "partner__name",
                "vendor_name": "partner__name",
                "partner_ref": "partner_ref",
                "user_name": "user__name",
                "company_name": "company__name",
                "date_order": "date_order",
                "date_approve": "date_approve",
                "date_planned": "date_planned",
                "state": "state",
                "invoice_status": "invoice_status",
                "currency_code": "currency_code",
                "amount_total": "amount_total",
                "amount_untaxed": "amount_untaxed",
            }
            for f in filters or []:
                field = getattr(f, "field", None) or (f.get("field") if isinstance(f, dict) else None)
                op = (getattr(f, "operator", None) or (f.get("operator") if isinstance(f, dict) else "")).lower()
                value = getattr(f, "value", None) if hasattr(f, "value") else (f.get("value") if isinstance(f, dict) else None)
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
                elif op == "between" and isinstance(value, list) and len(value) == 2:
                    qs = qs.filter(**{f"{orm_field}__range": (value[0], value[1])})

            total = qs.count()
            orders = list(
                qs.select_related("partner", "user", "company")
                .order_by("-date_order", "-id")[offset : offset + limit]
            )
            return orders, total

        orders, total = await asyncio.to_thread(_search)
        return {
            "items": [_order_to_item(o) for o in orders],
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
    async def export_orders_csv(
        tenant_id: str,
        company_ids: Optional[list[int]] = None,
    ) -> str:
        header_cols = [
            "id", "odoo_id", "odoo_name", "date_order", "date_approve",
            "date_planned", "state", "invoice_status",
            "amount_untaxed", "amount_tax", "amount_total", "currency_code",
            "partner_name", "partner_ref", "partner_email", "partner_phone",
            "partner_city", "user_name", "company_name", "synced_at",
        ]

        def _export():
            qs = PurchaseService._base_qs(tenant_id, company_ids)
            return list(qs.select_related("partner", "user", "company").order_by("-date_order", "-id"))

        orders = await asyncio.to_thread(_export)
        lines = [",".join(header_cols)]
        for order in orders:
            item = _order_to_item(order)
            lines.append(",".join(_csv_escape(item.get(col, "")) for col in header_cols))
        return "\n".join(lines)
