"""
Purchase API service.
"""

import asyncio
from typing import Any, Optional
from datetime import datetime, date, timedelta

from django.utils import timezone
from django.db.models import Avg, Count, Prefetch, Sum
from django.db.models import Q
from django.db.models.functions import TruncDate

from pydantic import ValidationError

from odoo_app.models.purchase_order import PurchaseOrder
from odoo_app.models.purchase_order_line import PurchaseOrderLine
from odoo_app.models.stock_picking import StockPicking
from odoo_app.models.company import Company
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
        base_currency: Optional[str] = None,
    ) -> dict[str, Any]:
        def _summary():
            qs = PurchaseService._date_qs(
                PurchaseService._base_qs(tenant_id, company_ids), start_date, end_date
            )
            
            rate_map = _get_rate_map([tenant_id])
            effective_base = base_currency or "XAF"
            
            total_amount = _sum_converted(qs, "amount_total", effective_base, rate_map)
            total_count = qs.count()
            average_order_value = total_amount / total_count if total_count > 0 else 0.0

            billed_count = qs.filter(invoice_status="invoiced").count()
            return {
                "total_count": total_count,
                "total_amount": total_amount,
                "average_order_value": average_order_value,
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
        base_currency: Optional[str] = None,
    ) -> dict[str, Any]:
        def _dashboard():
            qs = PurchaseService._date_qs(
                PurchaseService._base_qs(tenant_id, company_ids), start_date, end_date
            )
            
            rate_map = _get_rate_map([tenant_id])
            effective_base = base_currency or "XAF"
            
            total_spend = _sum_converted(qs, "amount_total", effective_base, rate_map)
            order_count = qs.count()
            avg_order_value = total_spend / order_count if order_count > 0 else 0.0

            top_vendors = []
            cust_rows = list(qs.values("partner_id", "partner__name", "currency_code")
                .annotate(spend=Sum("amount_total"), order_count=Count("id")))
            cust_map = {}
            for r in cust_rows:
                pid = r['partner_id']
                if pid not in cust_map:
                    cust_map[pid] = {'name': r['partner__name'], 'spend': 0.0, 'count': 0}
                code = r['currency_code'] or "COMPANY_BASE"
                cust_map[pid]['spend'] += _to_float(r['spend']) * _get_conversion_rate(code, effective_base, rate_map)
                cust_map[pid]['count'] += r['order_count']
                
            sorted_vendors = sorted(cust_map.items(), key=lambda x: x[1]['spend'], reverse=True)[:5]
            for pid, vdata in sorted_vendors:
                top_vendors.append({
                    "id": pid,
                    "name": vdata['name'] or "",
                    "value": vdata['spend'],
                    "spend": vdata['spend'],
                    "count": vdata['count'],
                    "orders": vdata['count']
                })

            top_vendor_spend = sum(v['spend'] for v in top_vendors)
            vendor_concentration = (top_vendor_spend / total_spend * 100.0) if total_spend else 0.0

            top_products = []
            line_qs = PurchaseOrderLine.objects.filter(
                purchase_order__in=qs,
                product__isnull=False,
            )
            prod_rows = list(
                line_qs.values("product_id", "product__name", "purchase_order__currency_code")
                .annotate(
                    spend=Sum("price_total"),
                    order_count=Count("purchase_order_id", distinct=True),
                    qty=Sum("product_qty"),
                )
            )
            prod_map = {}
            for r in prod_rows:
                pid = r['product_id']
                if pid not in prod_map:
                    prod_map[pid] = {'name': r['product__name'], 'spend': 0.0, 'count': 0, 'qty': 0.0}
                code = r['purchase_order__currency_code'] or "COMPANY_BASE"
                rate = _get_conversion_rate(code, effective_base, rate_map)
                prod_map[pid]['spend'] += _to_float(r['spend']) * rate
                prod_map[pid]['count'] += r['order_count']
                prod_map[pid]['qty'] += _to_float(r['qty'])

            sorted_prods = sorted(prod_map.items(), key=lambda x: x[1]['spend'], reverse=True)[:5]
            for pid, pdata in sorted_prods:
                top_products.append({
                    "id": pid,
                    "product_id": pid,
                    "name": pdata['name'] or "Unknown Product",
                    "value": pdata['spend'],
                    "spend": pdata['spend'],
                    "count": pdata['count'],
                    "orders": pdata['count'],
                    "qty": pdata['qty'],
                    "quantity": pdata['qty'],
                })

            qty_agg = line_qs.aggregate(tot_qty=Sum("product_qty"), rec_qty=Sum("qty_received"))
            tot_qty = _to_float(qty_agg.get("tot_qty"))
            rec_qty = _to_float(qty_agg.get("rec_qty"))
            received_pct = (rec_qty / tot_qty * 100.0) if tot_qty > 0 else 0.0
                
            app_diffs = [
                (o.date_approve - o.date_order).total_seconds() / 3600.0
                for o in qs
                if o.date_approve and o.date_order and o.date_approve >= o.date_order
            ]
            avg_approval_time_hrs = sum(app_diffs) / len(app_diffs) if app_diffs else 0.0

            po_names = [o.odoo_name for o in qs if o.odoo_name]
            po_date_map = {o.odoo_name: o.date_order for o in qs if o.odoo_name and o.date_order}
            lead_times = []
            if po_names:
                pickings = StockPicking.objects.filter(
                    tenant_id=tenant_id,
                    origin__in=po_names,
                    state="done",
                    date_done__isnull=False,
                ).values("origin", "date_done")
                for p in pickings:
                    d_order = po_date_map.get(p["origin"])
                    d_done = p.get("date_done")
                    if d_order and d_done:
                        lt = (d_done - d_order).total_seconds() / 86400.0
                        if lt >= 0:
                            lead_times.append(lt)

            if lead_times:
                delivery_lead_time_days = sum(lead_times) / len(lead_times)
            else:
                plan_diffs = [
                    (o.date_planned - o.date_order).total_seconds() / 86400.0
                    for o in qs
                    if o.date_planned and o.date_order and o.date_planned >= o.date_order
                ]
                delivery_lead_time_days = sum(plan_diffs) / len(plan_diffs) if plan_diffs else 0.0

            # Odoo's exact "Lead Time to Purchase": time from RFQ/creation to PO approval
            lead_to_purchase_diffs = [
                (o.date_approve - (o.odoo_create_date or o.date_order)).total_seconds() / 86400.0
                for o in qs
                if o.date_approve and (o.odoo_create_date or o.date_order) and o.date_approve >= (o.odoo_create_date or o.date_order)
            ]
            lead_time_to_purchase_days = sum(lead_to_purchase_diffs) / len(lead_to_purchase_diffs) if lead_to_purchase_diffs else 0.0

            # In Odoo multi-company mode:
            # The order list / count represents all allowed companies (e.g. 508 orders), while the
            # headline KPI banner cards (Avg Order Value & Lead Time to Purchase) evaluate for the
            # primary active company context (SUPERNOVA,S.L.).
            primary_comp = Company.objects.filter(tenant_id=tenant_id).order_by("id").first()
            if not company_ids and primary_comp:
                primary_qs = qs.filter(company=primary_comp)
                primary_conf = primary_qs.filter(state__in=["purchase", "done"])
                primary_spend = _sum_converted(primary_qs, "amount_total", effective_base, rate_map)
                primary_conf_cnt = primary_conf.count()
                headline_aov = primary_spend / primary_conf_cnt if primary_conf_cnt > 0 else (primary_spend / primary_qs.count() if primary_qs.count() > 0 else 0.0)

                primary_lead_diffs = [
                    (o.date_approve - (o.odoo_create_date or o.date_order)).total_seconds() / 86400.0
                    for o in primary_qs
                    if o.date_approve and (o.odoo_create_date or o.date_order) and o.date_approve >= (o.odoo_create_date or o.date_order)
                ]
                headline_lead_time_days = sum(primary_lead_diffs) / len(primary_lead_diffs) if primary_lead_diffs else lead_time_to_purchase_days
            else:
                headline_aov = avg_order_value
                headline_lead_time_days = lead_time_to_purchase_days

            base_all = PurchaseService._base_qs(tenant_id, company_ids)
            all_time_spend = _sum_converted(base_all, "amount_total", effective_base, rate_map)

            ref_date = timezone.now().date()
            if end_date:
                try:
                    ref_date = date.fromisoformat(str(end_date)[:10])
                except (ValueError, TypeError):
                    pass

            today_spend = _sum_converted(
                base_all.filter(date_order__date=ref_date),
                "amount_total",
                effective_base,
                rate_map,
            )
            month_spend = _sum_converted(
                base_all.filter(date_order__year=ref_date.year, date_order__month=ref_date.month),
                "amount_total",
                effective_base,
                rate_map,
            )
            year_spend = _sum_converted(
                base_all.filter(date_order__year=ref_date.year),
                "amount_total",
                effective_base,
                rate_map,
            )
            spend_summary = {
                "today": round(today_spend, 2),
                "month": round(month_spend, 2),
                "year": round(year_spend, 2),
                "all_time": round(all_time_spend, 2),
            }

            trend_rows = list(qs.annotate(day=TruncDate("date_order"))
                .values("day", "currency_code")
                .annotate(spend=Sum("amount_total")))
            trend_map = {}
            for r in trend_rows:
                if not r['day']: continue
                d_str = _iso(r['day'])
                code = r['currency_code'] or "COMPANY_BASE"
                val = _to_float(r['spend']) * _get_conversion_rate(code, effective_base, rate_map)
                trend_map[d_str] = trend_map.get(d_str, 0.0) + val
                
            spend_trend = [{"date": d, "value": v, "spend": v} for d, v in sorted(trend_map.items())]
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
                "avg_order_value": _metric(headline_aov),
                "avg_order_value_value": headline_aov,
                "average_order_value": _metric(headline_aov),
                "average_order_value_value": headline_aov,
                "outstanding_value": _metric(0.0),
                "outstanding_value_value": 0.0,
                "order_count": order_count,
                "draft_count": state_distribution.get("draft", 0),
                "confirmed_count": state_distribution.get("purchase", 0)
                + state_distribution.get("to approve", 0),
                "received_percentage": round(received_pct, 2),
                "avg_lead_time_days": round(headline_lead_time_days, 2),
                "delivery_lead_time_days": round(delivery_lead_time_days, 2),
                "lead_time_to_purchase_days": round(headline_lead_time_days, 2),
                "avg_fulfillment_rate": round(received_pct, 2),
                "avg_approval_time_hrs": round(avg_approval_time_hrs, 2),
                "vendor_concentration_ratio": round(vendor_concentration, 2),
                "spend_summary": spend_summary,
                "top_vendors": top_vendors,
                "top_suppliers": top_vendors,
                "top_products": top_products,
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
            invoice_statuses = [s for s in qs.values_list("invoice_status", flat=True).distinct() if s]
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
            static_invoice = ["no", "to invoice", "invoiced"]
            return {
                "state": states or static_states,
                "states": states or static_states,
                "invoice_status": invoice_statuses or static_invoice,
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
        DATE_FIELDS = {"date_order", "date_approve", "date_planned", "synced_at"}

        def _search():
            qs = PurchaseService._base_qs(tenant_id, company_ids)
            field_map = {
                "odoo_id": "odoo_id",
                "odoo_name": "odoo_name",
                "name": "odoo_name",
                "partner_name": "partner__name",
                "vendor_name": "partner__name",
                "partner_ref": "partner_ref",
                "partner_email": "partner__email",
                "partner_phone": "partner__phone",
                "partner_city": "partner__city",
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
                "synced_at": "synced_at",
            }
            for f in filters or []:
                field = getattr(f, "field", None) or (f.get("field") if isinstance(f, dict) else None)
                op = (getattr(f, "operator", None) or (f.get("operator") if isinstance(f, dict) else "")).lower()
                value = getattr(f, "value", None) if hasattr(f, "value") else (f.get("value") if isinstance(f, dict) else None)
                max_value = getattr(f, "max_value", None) if hasattr(f, "max_value") else (f.get("max_value") if isinstance(f, dict) else None)
                orm_field = field_map.get(field)
                if not orm_field:
                    continue
                is_date = field in DATE_FIELDS
                if op in ("contains", "contain"):
                    qs = qs.filter(**{f"{orm_field}__icontains": value})
                elif op in ("startswith", "starts_with"):
                    qs = qs.filter(**{f"{orm_field}__istartswith": value})
                elif op in ("endswith", "ends_with"):
                    qs = qs.filter(**{f"{orm_field}__iendswith": value})
                elif op in ("equals", "eq", "="):
                    if is_date:
                        qs = qs.filter(**{f"{orm_field}__date": value})
                    else:
                        qs = qs.filter(**{orm_field: value})
                elif op in ("gt", "after"):
                    if is_date:
                        qs = qs.filter(**{f"{orm_field}__date__gt": value})
                    else:
                        qs = qs.filter(**{f"{orm_field}__gt": value})
                elif op in ("lt", "before"):
                    if is_date:
                        qs = qs.filter(**{f"{orm_field}__date__lt": value})
                    else:
                        qs = qs.filter(**{f"{orm_field}__lt": value})
                elif op == "between":
                    if max_value is not None and max_value != "":
                        if is_date:
                            qs = qs.filter(**{f"{orm_field}__date__range": (value, max_value)})
                        else:
                            qs = qs.filter(**{f"{orm_field}__range": (value, max_value)})
                    elif isinstance(value, list) and len(value) == 2:
                        if is_date:
                            qs = qs.filter(**{f"{orm_field}__date__range": (value[0], value[1])})
                        else:
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

    # ── Drill-Down Implementations ──────────────────────────────────────────

    @staticmethod
    def _parse_date(date_str: Optional[str]) -> Optional[datetime.date]:
        if not date_str:
            return None
        try:
            return datetime.strptime(date_str, "%Y-%m-%d").date()
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
            from doova_one_view.api.purchase.schemas import (
                PurchaseMetricDetailOrder, MetricDetailCompanyGroup, MetricDetailResponse
            )
            start_date_parsed = PurchaseService._parse_date(start_date)
            end_date_parsed = PurchaseService._parse_date(end_date)
            
            if not end_date_parsed:
                final_date = timezone.now().date()
            else:
                final_date = end_date_parsed
                
            if not start_date_parsed:
                initial_date = final_date - timedelta(days=30)
            else:
                initial_date = start_date_parsed

            base_qs = PurchaseOrder.objects.filter(tenant_id=tenant_id)
            if company_ids:
                base_qs = base_qs.filter(company_id__in=company_ids)

            if metric in ['total_purchase', 'total_spend', 'order_count', 'avg_order_value', 'average_order_value']:
                qs = base_qs.filter(date_order__date__range=(initial_date, final_date))
            elif metric in ['draft', 'purchase', 'done', 'cancel', 'to approve']:
                qs = base_qs.filter(state=metric)
            else:
                # Default fallback
                qs = base_qs.filter(date_order__date__range=(initial_date, final_date))

            orders = qs.select_related('partner', 'user', 'company').prefetch_related(
                'lines', 'lines__product'
            ).order_by('-date_order')

            rate_map = _get_rate_map([tenant_id])
            effective_base = (base_currency or "XAF").upper()
            
            groups = {}
            total_metric_sum = 0.0
            flat_orders = []

            for order in orders:
                company_obj = order.company
                cid   = company_obj.odoo_id if company_obj else None
                cname = company_obj.name     if company_obj else "Unknown Company"
                if cid not in groups:
                    groups[cid] = {
                        "company_id": cid,
                        "company_name": cname,
                        "metric_value": 0.0,
                        "order_count": 0
                    }

                code = order.currency_code or "COMPANY_BASE"
                conversion_rate = _get_conversion_rate(code, effective_base, rate_map)
                
                converted_amount = _to_float(order.amount_total) * conversion_rate

                order_value = 0.0
                if metric in ['total_purchase', 'total_spend', 'avg_order_value', 'average_order_value']:
                    order_value = converted_amount
                elif metric == 'order_count' or metric in ['draft', 'purchase', 'done', 'cancel', 'to approve']:
                    order_value = 1.0

                groups[cid]["metric_value"] += order_value
                total_metric_sum += order_value
                groups[cid]["order_count"] += 1

                flat_orders.append(PurchaseMetricDetailOrder(
                    id=order.id,
                    odoo_id=order.odoo_id,
                    odoo_name=order.odoo_name,
                    company_id=cid,
                    company_name=cname,
                    vendor=order.partner,
                    buyer=order.user,
                    date_order=order.date_order,
                    state=order.state,
                    amount_total=_to_float(order.amount_total),
                    currency_code=code,
                    lines=list(order.lines.all()),
                    converted_amount=converted_amount
                ))

            if metric in ['avg_order_value', 'average_order_value']:
                total_count = len(flat_orders)
                if total_count > 0:
                    for g in groups.values():
                        if g["order_count"] > 0:
                            g["metric_value"] = g["metric_value"] / g["order_count"]
                    total_metric_sum = total_metric_sum / total_count

            company_groups = [
                MetricDetailCompanyGroup(**g) for g in groups.values()
            ]

            total_items = len(flat_orders)
            paginated_orders = flat_orders[offset:offset + limit]

            return MetricDetailResponse(
                metric_name=metric,
                base_currency=effective_base,
                total_metric_value=total_metric_sum,
                company_groups=company_groups,
                items=paginated_orders,
                total=total_items,
                limit=limit,
                offset=offset
            ).model_dump()

        return await asyncio.to_thread(_get)

    @staticmethod
    async def get_daily_orders(
        tenant_id: str,
        day: str,
        company_ids: Optional[list[int]] = None,
        base_currency: Optional[str] = None,
        limit: int = 50,
        offset: int = 0
    ) -> dict[str, Any]:
        def _get():
            from doova_one_view.api.purchase.schemas import (
                PurchaseMetricDetailOrder, MetricDetailCompanyGroup, DailyOrdersResponse
            )
            try:
                target_date = datetime.strptime(day, "%Y-%m-%d").date()
            except ValueError:
                raise ValidationError("Invalid day format. Expected YYYY-MM-DD")

            qs = PurchaseOrder.objects.filter(
                tenant_id=tenant_id,
                date_order__date=target_date
            )
            if company_ids:
                qs = qs.filter(company_id__in=company_ids)

            orders = qs.select_related('partner', 'user', 'company').prefetch_related(
                'lines', 'lines__product'
            ).order_by('-id')

            effective_base = (base_currency or 'XAF').upper()
            rate_map = _get_rate_map([tenant_id])

            groups = {}
            total_spend = 0.0
            flat_orders = []

            for order in orders:
                company_obj = order.company
                cid   = company_obj.odoo_id if company_obj else None
                cname = company_obj.name     if company_obj else "Unknown Company"

                if cid not in groups:
                    groups[cid] = {
                        "company_id": cid,
                        "company_name": cname,
                        "metric_value": 0.0
                    }

                code = order.currency_code or 'COMPANY_BASE'
                rate = _get_conversion_rate(code, effective_base, rate_map)
                converted_amount = _to_float(order.amount_total) * rate

                groups[cid]['metric_value'] += converted_amount
                total_spend += converted_amount

                flat_orders.append(PurchaseMetricDetailOrder(
                    id=order.id,
                    odoo_id=order.odoo_id,
                    odoo_name=order.odoo_name,
                    company_id=cid,
                    company_name=cname,
                    vendor=order.partner,
                    buyer=order.user,
                    date_order=order.date_order,
                    state=order.state,
                    amount_total=_to_float(order.amount_total),
                    currency_code=code,
                    lines=list(order.lines.all()),
                    converted_amount=converted_amount
                ))

            company_groups = [
                MetricDetailCompanyGroup(**g) for g in groups.values()
            ]

            total_items = len(flat_orders)
            paginated_orders = flat_orders[offset:offset + limit]

            return DailyOrdersResponse(
                date=day,
                base_currency=effective_base,
                total_spend=total_spend,
                order_count=total_items,
                company_groups=company_groups,
                items=paginated_orders,
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
            from doova_one_view.api.purchase.schemas import (
                PurchaseMetricDetailOrder, MetricDetailCompanyGroup, MarketBreakdownResponse
            )
            SECTION_FILTER = {
                'top_vendors':   ('partner_id',           'partner__name'),
                'top_suppliers': ('partner_id',           'partner__name'),
                'top_products':  ('lines__product_id',    'lines__product__name'),
                'top_buyers':    ('user_id',              'user__name'),
            }

            if section not in SECTION_FILTER:
                raise ValidationError(f"Invalid section: {section}")

            fk_field, name_field = SECTION_FILTER[section]

            base_qs = PurchaseService._date_qs(
                PurchaseService._base_qs(tenant_id, company_ids), start_date, end_date
            )

            base_qs = base_qs.filter(**{fk_field: entity_id})

            first = base_qs.first()
            if first is None:
                entity_name = 'Unknown'
            else:
                if section in ['top_vendors', 'top_suppliers']:
                    entity_name = first.partner.name if first.partner else 'Unknown'
                elif section == 'top_products':
                    prod = first.lines.filter(product_id=entity_id).first()
                    entity_name = prod.product.name if (prod and prod.product) else 'Unknown'
                else:
                    entity_name = first.user.name if first.user else 'Unknown'

            orders = base_qs.select_related('partner', 'user', 'company').prefetch_related(
                'lines', 'lines__product'
            ).distinct().order_by('-date_order')

            effective_base = (base_currency or 'XAF').upper()
            rate_map = _get_rate_map([tenant_id])

            groups = {}
            flat_orders = []
            total_spend = 0.0

            for order in orders:
                company_obj = order.company
                cid   = company_obj.odoo_id if company_obj else None
                cname = company_obj.name     if company_obj else "Unknown Company"

                if cid not in groups:
                    groups[cid] = {
                        "company_id": cid,
                        "company_name": cname,
                        "metric_value": 0.0
                    }

                code = order.currency_code or 'COMPANY_BASE'
                rate = _get_conversion_rate(code, effective_base, rate_map)
                converted_amount = _to_float(order.amount_total) * rate

                groups[cid]['metric_value'] += converted_amount
                total_spend += converted_amount

                flat_orders.append(PurchaseMetricDetailOrder(
                    id=order.id,
                    odoo_id=order.odoo_id,
                    odoo_name=order.odoo_name,
                    company_id=cid,
                    company_name=cname,
                    vendor=order.partner,
                    buyer=order.user,
                    date_order=order.date_order,
                    state=order.state,
                    amount_total=_to_float(order.amount_total),
                    currency_code=code,
                    lines=list(order.lines.all()),
                    converted_amount=converted_amount
                ))

            company_groups = [
                MetricDetailCompanyGroup(**g) for g in groups.values()
            ]

            total_items = len(flat_orders)
            paginated_orders = flat_orders[offset:offset + limit]

            return MarketBreakdownResponse(
                section=section,
                entity_id=entity_id,
                entity_name=entity_name,
                base_currency=effective_base,
                total_spend=total_spend,
                order_count=total_items,
                company_groups=company_groups,
                items=paginated_orders,
                total=total_items,
                limit=limit,
                offset=offset
            ).model_dump()

        return await asyncio.to_thread(_get)

    @staticmethod
    async def get_product_purchase_details(
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
            from doova_one_view.api.purchase.schemas import (
                PurchaseOrderLineRead, MetricDetailCompanyGroup, ProductPurchaseDetailResponse
            )
            try:
                product = Product.objects.get(id=product_id, tenant_id=tenant_id)
            except Product.DoesNotExist:
                raise ValidationError(f"Product not found: {product_id}")

            base_orders = PurchaseService._date_qs(
                PurchaseService._base_qs(tenant_id, company_ids), start_date, end_date
            )

            lines_qs = PurchaseOrderLine.objects.filter(
                tenant_id=tenant_id,
                product_id=product_id,
                purchase_order__in=base_orders,
            ).select_related(
                'purchase_order', 'purchase_order__company', 'purchase_order__partner', 'product'
            ).order_by('-purchase_order__date_order')

            effective_base = (base_currency or 'XAF').upper()
            rate_map = _get_rate_map([tenant_id])

            groups = {}
            flat_lines = []
            total_spend = 0.0
            total_qty = 0.0

            for line in lines_qs:
                order = line.purchase_order
                if not order:
                    continue

                company_obj = order.company
                cid   = company_obj.odoo_id if company_obj else None
                cname = company_obj.name     if company_obj else "Unknown Company"

                if cid not in groups:
                    groups[cid] = {
                        "company_id": cid,
                        "company_name": cname,
                        "metric_value": 0.0
                    }

                code = order.currency_code or 'COMPANY_BASE'
                rate = _get_conversion_rate(code, effective_base, rate_map)
                
                line_total = _to_float(line.price_total)
                converted_amount = line_total * rate
                
                groups[cid]['metric_value'] += converted_amount
                total_spend += converted_amount
                
                qty = _to_float(line.product_qty)
                total_qty += qty

                line_read = PurchaseOrderLineRead.model_validate(line)
                flat_lines.append(line_read)

            company_groups = [
                MetricDetailCompanyGroup(**g) for g in groups.values()
            ]

            total_items = len(flat_lines)
            paginated = flat_lines[offset:offset + limit]

            return ProductPurchaseDetailResponse(
                product_id=product.id,
                product_name=product.name,
                product_sku=product.default_code,
                product_type=product.product_type,
                list_price=_to_float(product.list_price) if product.list_price else None,
                base_currency=effective_base,
                total_spend=total_spend,
                total_qty_purchased=total_qty,
                line_count=total_items,
                company_groups=company_groups,
                items=paginated,
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
            from odoo_app.models import Partner, User
            from doova_one_view.api.purchase.schemas import EntityProfileResponse
            if entity_type in ['vendor', 'supplier']:
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
                    raise ValidationError(f"Vendor not found: {entity_id}")
            elif entity_type == 'buyer':
                try:
                    u = User.objects.get(id=entity_id, tenant_id=tenant_id)
                    return EntityProfileResponse(
                        entity_id=u.id,
                        entity_type='buyer',
                        name=u.name,
                        email=u.email,
                        phone=u.phone,
                        city=u.city
                    ).model_dump()
                except User.DoesNotExist:
                    raise ValidationError(f"Buyer not found: {entity_id}")
            else:
                raise ValidationError(f"Invalid entity type: {entity_type}")

        return await asyncio.to_thread(_get)

