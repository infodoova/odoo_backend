"""
Inventory API service.
"""

import asyncio
from datetime import date, timedelta
from typing import Any, Optional, Union

from django.db.models import Count, F, Q, Sum
from django.db.models.functions import TruncDate
from django.utils import timezone

from odoo_app.models.stock_move import StockMove
from odoo_app.models.stock_move_line import StockMoveLine
from odoo_app.models.stock_picking import StockPicking
from odoo_app.models.stock_quant import StockQuant
from doova_one_view.api.common.exceptions import NotFoundError


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


def _csv_escape(value: Any) -> str:
    s = str(value)
    if any(ch in s for ch in (",", '"', "\n", "\r")):
        return f'"{s.replace(chr(34), chr(34) + chr(34))}"'
    return s


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


def _product_obj(obj: Any) -> Optional[dict[str, Any]]:
    product = getattr(obj, "product", None)
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


def _lot_obj(obj: Any) -> Optional[dict[str, Any]]:
    lot = getattr(obj, "lot", None)
    if lot is None:
        return None
    return {
        "id": lot.id,
        "odoo_id": lot.odoo_id,
        "name": lot.name,
        "ref": lot.ref,
        "expiration_date": _iso(lot.expiration_date),
    }


def _picking_to_item(picking: StockPicking) -> dict[str, Any]:
    partner = _partner_obj(picking)
    company = _company_obj(picking)
    name = picking.odoo_name or ""
    return {
        "id": picking.id,
        "odoo_id": picking.odoo_id,
        "name": name,
        "odoo_name": name,
        "partner": partner,
        "partner_id": getattr(picking, "partner_id", None),
        "partner_name": partner["name"] if partner else "",
        "picking_type": picking.picking_type or "",
        "picking_type_code": picking.picking_type or "",
        "origin": picking.origin or "",
        "state": picking.state,
        "scheduled_date": _iso(picking.scheduled_date),
        "date_done": _iso(picking.date_done),
        "company": company,
        "company_id": getattr(picking, "company_id", None),
        "company_name": company["name"] if company else "",
        "synced_at": _iso(picking.synced_at),
    }


def _move_to_item(move: StockMove) -> dict[str, Any]:
    product = _product_obj(move)
    company = _company_obj(move)
    return {
        "id": move.id,
        "odoo_id": move.odoo_id,
        "name": move.name or "",
        "reference": move.reference or "",
        "origin": move.origin or "",
        "picking_id": getattr(move, "picking_id", None),
        "picking_local_id": getattr(move, "picking_id", None),
        "odoo_picking_id": move.odoo_picking_id,
        "location_src": move.location_src or "",
        "location_dest": move.location_dest or "",
        "product_uom_qty": _to_float(move.product_uom_qty),
        "quantity_done": _to_float(move.quantity_done),
        "date": _iso(move.date),
        "date_deadline": _iso(move.date_deadline),
        "state": move.state,
        "product": product,
        "product_id": getattr(move, "product_id", None),
        "product_name": product["name"] if product else "",
        "product_code": product.get("default_code") if product else "",
        "company": company,
        "company_id": getattr(move, "company_id", None),
        "company_name": company["name"] if company else "",
        "synced_at": _iso(move.synced_at),
    }


def _move_line_to_item(line: StockMoveLine) -> dict[str, Any]:
    product = _product_obj(line)
    company = _company_obj(line)
    lot = _lot_obj(line)
    qty_done = _to_float(line.qty_done)
    return {
        "id": line.id,
        "odoo_id": line.odoo_id,
        "product": product,
        "product_id": getattr(line, "product_id", None),
        "product_name": product["name"] if product else "",
        "product_code": product.get("default_code") if product else "",
        "lot": lot,
        "lot_id": getattr(line, "lot_id", None),
        "lot_name": lot["name"] if lot else "",
        "location_src": line.location_src or "",
        "location_dest": line.location_dest or "",
        "product_uom_qty": _to_float(line.product_uom_qty),
        "qty_done": qty_done,
        "quantity_done": qty_done,
        "date": _iso(line.date),
        "state": line.state or "",
        "company": company,
        "company_id": getattr(line, "company_id", None),
        "company_name": company["name"] if company else "",
        "synced_at": _iso(line.synced_at),
    }


def _quant_to_item(quant: StockQuant) -> dict[str, Any]:
    product = _product_obj(quant)
    company = _company_obj(quant)
    lot = _lot_obj(quant)
    return {
        "id": quant.id,
        "odoo_id": quant.odoo_id,
        "product": product,
        "product_id": getattr(quant, "product_id", None),
        "product_name": product["name"] if product else "",
        "product_code": product.get("default_code") if product else "",
        "location_name": quant.location_name or "",
        "lot": lot,
        "lot_id": getattr(quant, "lot_id", None),
        "lot_name": lot["name"] if lot else "",
        "quantity": _to_float(quant.quantity),
        "reserved_quantity": _to_float(quant.reserved_quantity),
        "available_quantity": _to_float(quant.available_quantity),
        "in_date": _iso(quant.in_date),
        "company": company,
        "company_id": getattr(quant, "company_id", None),
        "company_name": company["name"] if company else "",
        "synced_at": _iso(quant.synced_at),
    }


class InventoryService:
    """Service for inventory operations."""

    @staticmethod
    def _company_filter(qs, company_ids: Optional[list[int]]):
        if company_ids:
            qs = qs.filter(company_id__in=company_ids)
        return qs

    @staticmethod
    def _apply_search(qs, filters: list[Any], field_map: dict[str, str]):
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
        return qs

    @staticmethod
    async def get_inventory_summary(
        tenant_id: str,
        company_ids: Optional[list[int]] = None,
    ) -> dict[str, Any]:
        def _summary():
            qs = InventoryService._company_filter(
                StockQuant.objects.filter(tenant_id=tenant_id), company_ids
            )
            stats = qs.aggregate(
                total_qty=Sum("quantity"),
                total_reserved=Sum("reserved_quantity"),
                product_count=Count("product_id", distinct=True),
            )
            
            stock_value_agg = qs.filter(quantity__gt=0).select_related("product").aggregate(
                total_value=Sum(F("quantity") * F("product__standard_price"))
            )
            
            recent_since = timezone.now() - timedelta(days=7)
            recent_moves = InventoryService._company_filter(
                StockMove.objects.filter(tenant_id=tenant_id, date__gte=recent_since),
                company_ids,
            ).count()
            return {
                "total_products_in_stock": stats["product_count"] or 0,
                "total_quantity": _to_float(stats["total_qty"]),
                "total_reserved_quantity": _to_float(stats["total_reserved"]),
                "total_value": _to_float(stock_value_agg["total_value"]),
                "recent_moves_count": recent_moves,
                "applied_filters": {"tenant_id": tenant_id, "company_ids": company_ids},
            }

        return await asyncio.to_thread(_summary)

    @staticmethod
    async def get_alerts(
        tenant_id: str,
        company_ids: Optional[list[int]] = None,
        low_stock_threshold: int = 10,
        limit: int = 10,
    ) -> dict[str, Any]:
        """Return aggregated inventory alerts."""
        def _build():
            from django.utils import timezone
            from datetime import timedelta

            quants = InventoryService._company_filter(
                StockQuant.objects.filter(tenant_id=tenant_id).select_related("product", "lot"),
                company_ids
            )
            pickings = InventoryService._company_filter(
                StockPicking.objects.filter(tenant_id=tenant_id).select_related("partner"),
                company_ids
            )
            now = timezone.now()

            # 1. Low Stock
            low_qs = quants.filter(quantity__gt=0, quantity__lte=low_stock_threshold).order_by("quantity")
            low_cnt = low_qs.count()
            low_items = [
                {"id": q.id, "title": q.product.name if q.product else "Unknown", "description": f"Qty: {q.quantity}"}
                for q in low_qs[:limit]
            ]

            # 2. Out of Stock
            oos_qs = quants.filter(quantity=0).order_by("product__name")
            oos_cnt = oos_qs.count()
            oos_items = [
                {"id": q.id, "title": q.product.name if q.product else "Unknown", "description": "Qty: 0"}
                for q in oos_qs[:limit]
            ]

            # 3. Negative Stock
            neg_qs = quants.filter(quantity__lt=0).order_by("quantity")
            neg_cnt = neg_qs.count()
            neg_items = [
                {"id": q.id, "title": q.product.name if q.product else "Unknown", "description": f"Qty: {q.quantity}"}
                for q in neg_qs[:limit]
            ]

            # 4. Expiring Soon
            soon = now.date() + timedelta(days=30)
            exp_qs = quants.filter(quantity__gt=0, lot__expiration_date__lte=soon).order_by("lot__expiration_date")
            exp_cnt = exp_qs.count()
            exp_items = [
                {
                    "id": q.id, 
                    "title": q.product.name if q.product else "Unknown", 
                    "description": f"Lot: {q.lot.name if q.lot else ''}",
                    "date": _iso(q.lot.expiration_date) if q.lot else None
                }
                for q in exp_qs[:limit]
            ]

            # 5. Late Shipments
            late_qs = pickings.filter(
                picking_type='outgoing', 
                scheduled_date__lt=now
            ).exclude(state__in=['done', 'cancel']).order_by("scheduled_date")
            late_cnt = late_qs.count()
            late_items = [
                {
                    "id": p.id,
                    "title": p.odoo_name or "Unknown",
                    "description": f"State: {p.state}",
                    "date": _iso(p.scheduled_date)
                }
                for p in late_qs[:limit]
            ]

            # 6. Backorders (pickings in waiting state)
            back_qs = pickings.filter(picking_type='outgoing', state='waiting').order_by("-scheduled_date")
            back_cnt = back_qs.count()
            back_items = [
                {
                    "id": p.id,
                    "title": p.odoo_name or "Unknown",
                    "description": f"Partner: {p.partner.name if p.partner else 'None'}",
                    "date": _iso(p.scheduled_date)
                }
                for p in back_qs[:limit]
            ]

            # 7. Valuation Issues (in stock but no standard price)
            val_qs = quants.filter(
                quantity__gt=0
            ).filter(
                Q(product__standard_price__lte=0) | Q(product__standard_price__isnull=True)
            ).order_by("product__name")
            val_cnt = val_qs.count()
            val_items = [
                {
                    "id": q.id,
                    "title": q.product.name if q.product else "Unknown",
                    "description": f"Qty: {q.quantity}, Cost: {q.product.standard_price if q.product else 0}"
                }
                for q in val_qs[:limit]
            ]

            alerts = [
                {"key": "low_stock", "label": "Low Stock", "count": low_cnt, "severity": "warning", "items": low_items},
                {"key": "out_of_stock", "label": "Out of Stock", "count": oos_cnt, "severity": "danger", "items": oos_items},
                {"key": "negative_stock", "label": "Negative Stock", "count": neg_cnt, "severity": "danger", "items": neg_items},
                {"key": "expiring_soon", "label": "Expiring Soon", "count": exp_cnt, "severity": "warning", "items": exp_items},
                {"key": "late_shipments", "label": "Late Shipments", "count": late_cnt, "severity": "danger", "items": late_items},
                {"key": "backorders", "label": "Backorders", "count": back_cnt, "severity": "warning", "items": back_items},
                {"key": "valuation_issues", "label": "Valuation Issues", "count": val_cnt, "severity": "warning", "items": val_items},
            ]

            return {"alerts": alerts}

        return await asyncio.to_thread(_build)

    @staticmethod
    async def get_stock_table(
        tenant_id: str,
        table_type: str,
        company_ids: Optional[list[int]] = None,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        low_stock_threshold: int = 10,
        limit: int = 50,
        offset: int = 0,
    ) -> dict[str, Any]:
        """Return a paginated list of quants for specific stock tables."""
        def _fetch():
            from datetime import timedelta
            from django.utils import timezone
            from doova_one_view.api.inventory.schemas import StockQuantRead

            quants = InventoryService._company_filter(
                StockQuant.objects.filter(tenant_id=tenant_id).select_related("product", "lot", "company"),
                company_ids
            )

            if start_date:
                quants = quants.filter(in_date__gte=start_date)
            if end_date:
                quants = quants.filter(in_date__lte=end_date)

            if table_type == "low_stock":
                qs = quants.filter(quantity__gt=0, quantity__lte=low_stock_threshold).order_by("quantity")
            elif table_type == "out_of_stock":
                qs = quants.filter(quantity=0).order_by("product__name")
            elif table_type == "negative_stock":
                qs = quants.filter(quantity__lt=0).order_by("quantity")
            elif table_type == "expiring_soon":
                soon = timezone.now().date() + timedelta(days=30)
                qs = quants.filter(quantity__gt=0, lot__expiration_date__lte=soon).order_by("lot__expiration_date")
            elif table_type == "slow_moving":
                # items in stock with in_date older than 90 days
                old = timezone.now() - timedelta(days=90)
                qs = quants.filter(quantity__gt=0, in_date__lt=old).order_by("in_date")
            else:
                qs = quants.none()

            total = qs.count()
            items = qs[offset : offset + limit]

            return {
                "items": [StockQuantRead.model_validate(q).model_dump() for q in items],
                "total": total,
                "limit": limit,
                "offset": offset,
                "table_type": table_type
            }

        return await asyncio.to_thread(_fetch)

    @staticmethod
    async def get_top_cards(
        tenant_id: str,
        company_ids: Optional[list[int]] = None,
        low_stock_threshold: int = 10,
        limit: int = 25,
    ) -> dict[str, Any]:
        """Return the five inventory top-cards with drill-down items."""

        def _build():
            from django.db.models import Sum, Count, F, Q, Value
            from django.db.models.functions import Coalesce

            quants = InventoryService._company_filter(
                StockQuant.objects.filter(tenant_id=tenant_id)
                    .select_related("product"),
                company_ids,
            )

            def _quant_items(qs, lim):
                rows = []
                for q in qs[:lim]:
                    prod = q.product
                    rows.append({
                        "product_id": prod.id if prod else None,
                        "product_name": prod.name if prod else "Unknown",
                        "product_sku": prod.default_code if prod else None,
                        "location_name": q.location_name,
                        "quantity": _to_float(q.quantity),
                        "reserved_quantity": _to_float(q.reserved_quantity),
                        "available_quantity": _to_float(q.quantity) - _to_float(q.reserved_quantity),
                    })
                return rows

            # 1. Available Stock — quants where available qty > 0
            available_qs = quants.filter(quantity__gt=0).annotate(
                avail=F("quantity") - F("reserved_quantity")
            ).filter(avail__gt=0).order_by("-quantity")
            available_agg = available_qs.aggregate(
                total=Sum("quantity"),
                cnt=Count("id"),
            )

            # 2. Reserved Stock — quants where reserved_quantity > 0
            reserved_qs = quants.filter(reserved_quantity__gt=0).order_by("-reserved_quantity")
            reserved_agg = reserved_qs.aggregate(
                total=Sum("reserved_quantity"),
                cnt=Count("id"),
            )

            # 3. Low Stock Items — quants where 0 < quantity <= threshold
            low_qs = quants.filter(
                quantity__gt=0,
                quantity__lte=low_stock_threshold,
            ).order_by("quantity")
            low_agg = low_qs.aggregate(cnt=Count("id"))

            # 4. Out of Stock Items — quants where quantity == 0
            oos_qs = quants.filter(quantity=0).order_by("product__name")
            oos_agg = oos_qs.aggregate(cnt=Count("id"))

            # 5. Negative Stock Items — quants where quantity < 0
            neg_qs = quants.filter(quantity__lt=0).order_by("quantity")
            neg_agg = neg_qs.aggregate(
                total=Sum("quantity"),
                cnt=Count("id"),
            )

            cards = [
                {
                    "key": "available_stock",
                    "label": "Available Stock",
                    "value": int(_to_float(available_agg["total"])),
                    "unit": "qty",
                    "items": _quant_items(available_qs, limit),
                    "item_count": available_agg["cnt"] or 0,
                },
                {
                    "key": "reserved_stock",
                    "label": "Reserved Stock",
                    "value": int(_to_float(reserved_agg["total"])),
                    "unit": "qty",
                    "items": _quant_items(reserved_qs, limit),
                    "item_count": reserved_agg["cnt"] or 0,
                },
                {
                    "key": "low_stock_items",
                    "label": "Low Stock Items",
                    "value": low_agg["cnt"] or 0,
                    "unit": "items",
                    "items": _quant_items(low_qs, limit),
                    "item_count": low_agg["cnt"] or 0,
                },
                {
                    "key": "out_of_stock_items",
                    "label": "Out of Stock Items",
                    "value": oos_agg["cnt"] or 0,
                    "unit": "items",
                    "items": _quant_items(oos_qs, limit),
                    "item_count": oos_agg["cnt"] or 0,
                },
                {
                    "key": "negative_stock_items",
                    "label": "Negative Stock Items",
                    "value": neg_agg["cnt"] or 0,
                    "unit": "items",
                    "items": _quant_items(neg_qs, limit),
                    "item_count": neg_agg["cnt"] or 0,
                },
            ]

            return {
                "cards": cards,
                "applied_filters": {
                    "tenant_id": tenant_id,
                    "company_ids": company_ids,
                    "low_stock_threshold": low_stock_threshold,
                },
            }

        return await asyncio.to_thread(_build)

    @staticmethod
    async def get_dashboard(
        tenant_id: str,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        company_ids: Optional[list[int]] = None,
        base_currency: Optional[str] = None,
    ) -> dict[str, Any]:
        def _dashboard():
            quants = InventoryService._company_filter(
                StockQuant.objects.filter(tenant_id=tenant_id), company_ids
            )
            pickings = InventoryService._company_filter(
                StockPicking.objects.filter(tenant_id=tenant_id), company_ids
            )
            trend_quants = quants
            if start_date:
                trend_quants = trend_quants.filter(in_date__gte=start_date)
                pickings = pickings.filter(scheduled_date__gte=start_date)
            if end_date:
                trend_quants = trend_quants.filter(in_date__lte=end_date)
                pickings = pickings.filter(scheduled_date__lte=end_date)

            total_items = int(quants.filter(quantity__gt=0).aggregate(total=Sum("quantity"))["total"] or 0)
            stock_status_distribution = {
                "Available": quants.filter(quantity__gt=0, reserved_quantity__lt=F("quantity")).count(),
                "Reserved": quants.filter(reserved_quantity__gt=0).count(),
                "Empty": quants.filter(quantity__lte=0).count(),
            }
            company_distribution = [
                {
                    # Local database ID — use this with company_id filters and drill-downs
                    "company_id": row["company_id"],

                    # Original company ID from Odoo
                    "company_odoo_id": row["company__odoo_id"],

                    "company_name": row["company__name"] or "Unknown",
                    "count": row["count"],
                }
                for row in (
                    quants
                    .values(
                        "company_id",
                        "company__odoo_id",
                        "company__name",
                    )
                    .annotate(count=Count("id"))
                    .order_by("-count")
                )
            ]
            location_distribution = {
                row["location_name"] or "Unknown": row["count"]
                for row in quants.values("location_name").annotate(count=Count("id")).order_by("-count")[:10]
            }
            quantity_trend = [
                {"formattedDate": _iso(row["day"]), "date": _iso(row["day"]), "value": _to_float(row["value"])}
                for row in trend_quants.filter(in_date__isnull=False)
                .annotate(day=TruncDate("in_date"))
                .values("day")
                .annotate(value=Sum("quantity"))
                .order_by("day")
            ]
            incoming = pickings.exclude(state__in=["done", "cancel"]).filter(
                Q(picking_type="incoming") | Q(picking_type__icontains="receipt")
            ).count()
            outgoing = pickings.exclude(state__in=["done", "cancel"]).filter(
                Q(picking_type="outgoing") | Q(picking_type__icontains="delivery")
            ).count()
            soon = timezone.now().date() + timedelta(days=30)
            expiring = quants.filter(lot__expiration_date__lte=soon).count()
            applied = {
                "tenant_id": tenant_id,
                "start_date": start_date,
                "end_date": end_date,
                "company_ids": company_ids,
            }
            # --- Total Stock Value (quantity × standard_price) ---
            from odoo_app.models.product import Product

            stock_value_agg = quants.filter(quantity__gt=0).select_related("product").aggregate(
                total_value=Sum(F("quantity") * F("product__standard_price"))
            )
            total_stock_value = _to_float(stock_value_agg["total_value"])

            # Previous period stock value (simple: use moves from last 30 days to estimate change)
            prev_total_stock_value = 0.0
            stock_value_change_pct = 0.0

            return {
                "total_stock_value": total_stock_value,
                "prev_total_stock_value": prev_total_stock_value,
                "stock_value_change_pct": stock_value_change_pct,
                "total_items_in_stock": total_items,
                "incoming_shipments_count": incoming,
                "outgoing_shipments_count": outgoing,
                "expiring_soon_count": expiring,
                "stock_value_trend": quantity_trend,
                "inventory_value_trend": quantity_trend,
                "quantity_trend": quantity_trend,
                "stock_status_distribution": stock_status_distribution,
                "company_distribution": company_distribution,
                "location_distribution": location_distribution,
                "applied_filters": applied,
            }

        return await asyncio.to_thread(_dashboard)

    @staticmethod
    async def get_pickings(
        tenant_id: str,
        limit: int = 50,
        offset: int = 0,
        company_ids: Optional[list[int]] = None,
    ) -> dict[str, Any]:
        def _list():
            qs = InventoryService._company_filter(
                StockPicking.objects.filter(tenant_id=tenant_id), company_ids
            )
            total = qs.count()
            items = list(qs.select_related("partner", "company").order_by("-scheduled_date", "-id")[offset : offset + limit])
            return items, total

        pickings, total = await asyncio.to_thread(_list)
        return {"items": [_picking_to_item(p) for p in pickings], "total": total, "limit": limit, "offset": offset, "applied_filters": {"tenant_id": tenant_id, "company_ids": company_ids}}

    @staticmethod
    async def get_picking(
        tenant_id: str,
        picking_id: int,
        company_ids: Optional[list[int]] = None,
    ) -> dict[str, Any]:
        def _get():
            qs = InventoryService._company_filter(
                StockPicking.objects.filter(tenant_id=tenant_id), company_ids
            )
            try:
                base = qs.select_related("partner", "company")
                local = base.filter(id=picking_id).first()
                picking = local if local is not None else base.get(odoo_id=picking_id)
                moves = list(
                    picking.moves.select_related("product", "company").order_by("-date", "-id")
                )
                return picking, moves
            except StockPicking.DoesNotExist:
                raise NotFoundError("StockPicking", str(picking_id))

        picking, moves = await asyncio.to_thread(_get)
        item = _picking_to_item(picking)
        item["moves"] = [_move_to_item(m) for m in moves]
        return item

    @staticmethod
    async def get_moves(
        tenant_id: str,
        limit: int = 50,
        offset: int = 0,
        picking_id: Optional[int] = None,
        company_ids: Optional[list[int]] = None,
    ) -> dict[str, Any]:
        def _list():
            qs = InventoryService._company_filter(
                StockMove.objects.filter(tenant_id=tenant_id), company_ids
            )
            if picking_id is not None:
                qs = qs.filter(Q(picking_id=picking_id) | Q(odoo_picking_id=picking_id))
            total = qs.count()
            items = list(qs.select_related("product", "company", "picking").order_by("-date", "-id")[offset : offset + limit])
            return items, total

        moves, total = await asyncio.to_thread(_list)
        return {"items": [_move_to_item(m) for m in moves], "total": total, "limit": limit, "offset": offset, "applied_filters": {"tenant_id": tenant_id, "picking_id": picking_id, "company_ids": company_ids}}

    @staticmethod
    async def get_move(
        tenant_id: str,
        move_id: int,
        company_ids: Optional[list[int]] = None,
    ) -> dict[str, Any]:
        def _get():
            qs = InventoryService._company_filter(
                StockMove.objects.filter(tenant_id=tenant_id), company_ids
            )
            try:
                base = qs.select_related("product", "company", "picking")
                local = base.filter(id=move_id).first()
                move = local if local is not None else base.get(odoo_id=move_id)
                lines = list(
                    move.move_lines.select_related("product", "lot", "company").order_by("id")
                )
                return move, lines
            except StockMove.DoesNotExist:
                raise NotFoundError("StockMove", str(move_id))

        move, lines = await asyncio.to_thread(_get)
        item = _move_to_item(move)
        item["lines"] = [_move_line_to_item(line) for line in lines]
        return item

    @staticmethod
    async def get_quants(
        tenant_id: str,
        limit: int = 50,
        offset: int = 0,
        product_id: Optional[int] = None,
        company_ids: Optional[list[int]] = None,
    ) -> dict[str, Any]:
        def _list():
            qs = InventoryService._company_filter(
                StockQuant.objects.filter(tenant_id=tenant_id), company_ids
            )
            if product_id is not None:
                qs = qs.filter(product_id=product_id)
            total = qs.count()
            items = list(qs.select_related("product", "lot", "company").order_by("-quantity", "-id")[offset : offset + limit])
            return items, total

        quants, total = await asyncio.to_thread(_list)
        return {"items": [_quant_to_item(q) for q in quants], "total": total, "limit": limit, "offset": offset, "applied_filters": {"tenant_id": tenant_id, "product_id": product_id, "company_ids": company_ids}}

    @staticmethod
    async def search_pickings(tenant_id: str, filters: list[Any], limit: int, offset: int, company_ids: Optional[list[int]] = None) -> dict[str, Any]:
        field_map = {"odoo_id": "odoo_id", "id": "id", "name": "odoo_name", "odoo_name": "odoo_name", "partner_name": "partner__name", "picking_type": "picking_type", "picking_type_code": "picking_type", "origin": "origin", "state": "state", "scheduled_date": "scheduled_date", "date_done": "date_done", "company_name": "company__name", "synced_at": "odoo_write_date"}
        def _search():
            qs = InventoryService._company_filter(StockPicking.objects.filter(tenant_id=tenant_id), company_ids)
            qs = InventoryService._apply_search(qs, filters, field_map)
            total = qs.count()
            return list(qs.select_related("partner", "company").order_by("-scheduled_date", "-id")[offset : offset + limit]), total
        rows, total = await asyncio.to_thread(_search)
        return {"items": [_picking_to_item(x) for x in rows], "total": total, "limit": limit, "offset": offset, "applied_filters": {"tenant_id": tenant_id, "filters": [getattr(f, "model_dump", lambda: dict(f))() for f in (filters or [])], "company_ids": company_ids}}

    @staticmethod
    async def search_moves(tenant_id: str, filters: list[Any], limit: int, offset: int, company_ids: Optional[list[int]] = None) -> dict[str, Any]:
        field_map = {"odoo_id": "odoo_id", "id": "id", "name": "name", "reference": "reference", "origin": "origin", "picking_id": "picking_id", "odoo_picking_id": "odoo_picking_id", "product_id": "product_id", "product_name": "product__name", "product_code": "product__default_code", "location_src": "location_src", "location_dest": "location_dest", "product_uom_qty": "product_uom_qty", "quantity_done": "quantity_done", "state": "state", "date": "date", "company_name": "company__name", "synced_at": "odoo_write_date"}
        def _search():
            qs = InventoryService._company_filter(StockMove.objects.filter(tenant_id=tenant_id), company_ids)
            qs = InventoryService._apply_search(qs, filters, field_map)
            total = qs.count()
            return list(qs.select_related("product", "company", "picking").order_by("-date", "-id")[offset : offset + limit]), total
        rows, total = await asyncio.to_thread(_search)
        return {"items": [_move_to_item(x) for x in rows], "total": total, "limit": limit, "offset": offset, "applied_filters": {"tenant_id": tenant_id, "filters": [getattr(f, "model_dump", lambda: dict(f))() for f in (filters or [])], "company_ids": company_ids}}

    @staticmethod
    async def search_quants(tenant_id: str, filters: list[Any], limit: int, offset: int, company_ids: Optional[list[int]] = None) -> dict[str, Any]:
        field_map = {"odoo_id": "odoo_id", "id": "id", "product_id": "product_id", "product_name": "product__name", "product_code": "product__default_code", "location_name": "location_name", "lot_name": "lot__name", "quantity": "quantity", "reserved_quantity": "reserved_quantity", "available_quantity": "available_quantity", "in_date": "in_date", "company_name": "company__name", "synced_at": "odoo_write_date"}
        def _search():
            qs = InventoryService._company_filter(StockQuant.objects.filter(tenant_id=tenant_id), company_ids)
            qs = InventoryService._apply_search(qs, filters, field_map)
            total = qs.count()
            return list(qs.select_related("product", "lot", "company").order_by("-quantity", "-id")[offset : offset + limit]), total
        rows, total = await asyncio.to_thread(_search)
        return {"items": [_quant_to_item(x) for x in rows], "total": total, "limit": limit, "offset": offset, "applied_filters": {"tenant_id": tenant_id, "filters": [getattr(f, "model_dump", lambda: dict(f))() for f in (filters or [])], "company_ids": company_ids}}

    @staticmethod
    async def get_filters(tenant_id: str, company_ids: Optional[list[int]] = None) -> dict[str, Any]:
        def _filters():
            moves = InventoryService._company_filter(StockMove.objects.filter(tenant_id=tenant_id), company_ids)
            pickings = InventoryService._company_filter(StockPicking.objects.filter(tenant_id=tenant_id), company_ids)
            quants = InventoryService._company_filter(StockQuant.objects.filter(tenant_id=tenant_id), company_ids)
            products = [
                {"id": row["product_id"], "name": row["product__name"] or "", "value": str(row["product_id"]), "label": row["product__name"] or ""}
                for row in quants.filter(product_id__isnull=False).values("product_id", "product__name").distinct().order_by("product__name")
            ]
            lots = [
                {"id": row["lot_id"], "name": row["lot__name"] or "", "value": str(row["lot_id"]), "label": row["lot__name"] or ""}
                for row in quants.filter(lot_id__isnull=False).values("lot_id", "lot__name").distinct().order_by("lot__name")
            ]
            companies = [
                {"id": row["company_id"], "name": row["company__name"] or "", "value": str(row["company_id"]), "label": row["company__name"] or ""}
                for row in quants.filter(company_id__isnull=False).values("company_id", "company__name").distinct().order_by("company__name")
            ]
            return {
                "state": sorted({v for v in list(moves.values_list("state", flat=True).distinct()) + list(pickings.values_list("state", flat=True).distinct()) if v}),
                "states": sorted({v for v in list(moves.values_list("state", flat=True).distinct()) + list(pickings.values_list("state", flat=True).distinct()) if v}),
                "picking_type": sorted({v for v in pickings.values_list("picking_type", flat=True).distinct() if v}),
                "picking_types": sorted({v for v in pickings.values_list("picking_type", flat=True).distinct() if v}),
                "locations": sorted({v for v in quants.values_list("location_name", flat=True).distinct() if v}),
                "location_src": sorted({v for v in moves.values_list("location_src", flat=True).distinct() if v}),
                "location_dest": sorted({v for v in moves.values_list("location_dest", flat=True).distinct() if v}),
                "products": products,
                "product_names": [p["name"] for p in products if p["name"]],
                "lots": lots,
                "lot_names": [l["name"] for l in lots if l["name"]],
                "companies": companies,
            }
        return await asyncio.to_thread(_filters)

    @staticmethod
    async def export_pickings_csv(tenant_id: str, company_ids: Optional[list[int]] = None) -> str:
        headers = ["id", "odoo_id", "odoo_name", "partner_name", "picking_type", "origin", "state", "scheduled_date", "date_done", "company_name", "synced_at"]
        rows = (await InventoryService.get_pickings(tenant_id, 100000, 0, company_ids))["items"]
        return "\n".join([",".join(headers)] + [",".join(_csv_escape(item.get(h, "")) for h in headers) for item in rows])

    @staticmethod
    async def export_moves_csv(tenant_id: str, company_ids: Optional[list[int]] = None) -> str:
        headers = ["id", "odoo_id", "reference", "name", "origin", "picking_id", "product_name", "product_code", "location_src", "location_dest", "product_uom_qty", "quantity_done", "state", "date", "company_name", "synced_at"]
        rows = (await InventoryService.get_moves(tenant_id, 100000, 0, None, company_ids))["items"]
        return "\n".join([",".join(headers)] + [",".join(_csv_escape(item.get(h, "")) for h in headers) for item in rows])

    @staticmethod
    async def export_quants_csv(tenant_id: str, company_ids: Optional[list[int]] = None) -> str:
        headers = ["id", "odoo_id", "product_name", "product_code", "location_name", "lot_name", "quantity", "reserved_quantity", "available_quantity", "in_date", "company_name", "synced_at"]
        rows = (await InventoryService.get_quants(tenant_id, 100000, 0, None, company_ids))["items"]
        return "\n".join([",".join(headers)] + [",".join(_csv_escape(item.get(h, "")) for h in headers) for item in rows])

    # ── Drill-Down Implementations ──────────────────────────────────────────

    @staticmethod
    async def get_dashboard_metric_details(
        tenant_id: str,
        metric: str,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        company_ids: Optional[list[int]] = None,
        base_currency: Optional[str] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> dict[str, Any]:
        def _get():
            from doova_one_view.api.inventory.schemas import (
                StockQuantRead, StockPickingRead, MetricDetailCompanyGroup, MetricDetailResponse
            )
            
            quants = InventoryService._company_filter(
                StockQuant.objects.filter(tenant_id=tenant_id), company_ids
            )
            pickings = InventoryService._company_filter(
                StockPicking.objects.filter(tenant_id=tenant_id), company_ids
            )

            is_picking_metric = False
            total_metric_value = 0.0
            
            if metric in ["total_items_in_stock", "total_quantity", "total_items"]:
                qs = quants
                total_metric_value = int(qs.filter(quantity__gt=0).aggregate(total=Sum("quantity"))["total"] or 0)
            elif metric in ["incoming_shipments_count", "incoming"]:
                is_picking_metric = True
                if start_date:
                    pickings = pickings.filter(scheduled_date__gte=start_date)
                if end_date:
                    pickings = pickings.filter(scheduled_date__lte=end_date)
                qs = pickings.exclude(state__in=["done", "cancel"]).filter(
                    Q(picking_type="incoming") | Q(picking_type__icontains="receipt")
                )
                total_metric_value = float(qs.count())
            elif metric in ["outgoing_shipments_count", "outgoing"]:
                is_picking_metric = True
                if start_date:
                    pickings = pickings.filter(scheduled_date__gte=start_date)
                if end_date:
                    pickings = pickings.filter(scheduled_date__lte=end_date)
                qs = pickings.exclude(state__in=["done", "cancel"]).filter(
                    Q(picking_type="outgoing") | Q(picking_type__icontains="delivery")
                )
                total_metric_value = float(qs.count())
            elif metric in ["expiring_soon_count", "expiring"]:
                soon = timezone.now().date() + timedelta(days=30)
                qs = quants.filter(lot__expiration_date__lte=soon)
                total_metric_value = float(qs.count())
            else:
                raise ValueError(f"Metric drill-down not supported for: {metric}")

            groups = {}
            flat_items = []

            if is_picking_metric:
                pickings_list = list(qs.select_related("partner", "company").order_by("-scheduled_date", "-id"))
                total_items = len(pickings_list)
                paginated = pickings_list[offset:offset + limit]
                
                for p in pickings_list:
                    company_obj = p.company
                    cid = company_obj.odoo_id if company_obj else None
                    cname = company_obj.name if company_obj else "Unknown Company"
                    if cid not in groups:
                        groups[cid] = {
                            "company_id": cid,
                            "company_name": cname,
                            "metric_value": 0.0
                        }
                    groups[cid]["metric_value"] += 1.0

                for p in paginated:
                    flat_items.append(_picking_to_item(p))
            else:
                quants_list = list(qs.select_related("product", "lot", "company").order_by("-quantity", "-id"))
                total_items = len(quants_list)
                paginated = quants_list[offset:offset + limit]

                for q in quants_list:
                    company_obj = q.company
                    cid = company_obj.odoo_id if company_obj else None
                    cname = company_obj.name if company_obj else "Unknown Company"
                    if cid not in groups:
                        groups[cid] = {
                            "company_id": cid,
                            "company_name": cname,
                            "metric_value": 0.0
                        }
                    val = 1.0 if metric in ["expiring_soon_count", "expiring"] else _to_float(q.quantity)
                    groups[cid]["metric_value"] += val

                for q in paginated:
                    flat_items.append(_quant_to_item(q))

            company_groups = [
                MetricDetailCompanyGroup(**g) for g in groups.values()
            ]

            return MetricDetailResponse(
                metric_name=metric,
                total_metric_value=total_metric_value,
                company_groups=company_groups,
                items=flat_items,
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
        offset: int = 0,
    ) -> dict[str, Any]:
        def _get():
            from doova_one_view.api.inventory.schemas import (
                StockQuantRead, StockPickingRead, MetricDetailCompanyGroup, DailyMovesResponse
            )
            try:
                target_date = date.fromisoformat(day)
            except ValueError:
                raise ValueError("Invalid day format. Expected YYYY-MM-DD")

            quants = InventoryService._company_filter(
                StockQuant.objects.filter(tenant_id=tenant_id, in_date__date=target_date),
                company_ids
            ).select_related("product", "lot", "company")

            pickings = InventoryService._company_filter(
                StockPicking.objects.filter(tenant_id=tenant_id, scheduled_date__date=target_date),
                company_ids
            ).select_related("partner", "company")

            total_qty = _to_float(quants.aggregate(total=Sum("quantity"))["total"])
            picking_count = pickings.count()

            groups = {}
            for q in quants:
                company_obj = q.company
                cid = company_obj.odoo_id if company_obj else None
                cname = company_obj.name if company_obj else "Unknown Company"
                if cid not in groups:
                    groups[cid] = {
                        "company_id": cid,
                        "company_name": cname,
                        "metric_value": 0.0
                    }
                groups[cid]["metric_value"] += _to_float(q.quantity)

            flat_items = []
            for q in quants:
                flat_items.append(_quant_to_item(q))
            for p in pickings:
                flat_items.append(_picking_to_item(p))

            company_groups = [
                MetricDetailCompanyGroup(**g) for g in groups.values()
            ]

            total_items = len(flat_items)
            paginated = flat_items[offset:offset + limit]

            return DailyMovesResponse(
                date=day,
                total_quantity=total_qty,
                picking_count=picking_count,
                company_groups=company_groups,
                items=paginated,
                total=total_items,
                limit=limit,
                offset=offset
            ).model_dump()

        return await asyncio.to_thread(_get)

    @staticmethod
    async def get_market_breakdown_details(
        tenant_id: str,
        section: str,
        entity_id: Union[int, str],
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        company_ids: Optional[list[int]] = None,
        base_currency: Optional[str] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> dict[str, Any]:
        def _get():
            from doova_one_view.api.inventory.schemas import (
                StockQuantRead, MetricDetailCompanyGroup, MarketBreakdownResponse
            )
            
            quants = InventoryService._company_filter(
                StockQuant.objects.filter(tenant_id=tenant_id), company_ids
            )
            
            entity_name = "Unknown"
            if section in ["company_distribution", "top_companies"]:
                quants = quants.filter(company_id=entity_id)
                first = quants.first()
                if first and first.company:
                    entity_name = first.company.name
            elif section in ["location_distribution", "top_locations"]:
                quants = quants.filter(location_name=entity_id)
                entity_name = str(entity_id)
            elif section in ["stock_status_distribution", "top_statuses"]:
                status = str(entity_id).lower()
                if status == "available":
                    quants = quants.filter(quantity__gt=0, reserved_quantity__lt=F("quantity"))
                elif status == "reserved":
                    quants = quants.filter(reserved_quantity__gt=0)
                elif status == "empty":
                    quants = quants.filter(quantity__lte=0)
                entity_name = str(entity_id)
            else:
                raise ValueError(f"Invalid section: {section}")

            quants_list = list(quants.select_related("product", "lot", "company").order_by("-quantity", "-id"))
            total_qty = _to_float(quants.aggregate(total=Sum("quantity"))["total"])

            groups = {}
            for q in quants_list:
                company_obj = q.company
                cid = company_obj.odoo_id if company_obj else None
                cname = company_obj.name if company_obj else "Unknown Company"
                if cid not in groups:
                    groups[cid] = {
                        "company_id": cid,
                        "company_name": cname,
                        "metric_value": 0.0
                    }
                groups[cid]["metric_value"] += _to_float(q.quantity)

            company_groups = [
                MetricDetailCompanyGroup(**g) for g in groups.values()
            ]

            total_items = len(quants_list)
            paginated = quants_list[offset:offset + limit]

            return MarketBreakdownResponse(
                section=section,
                entity_id=entity_id,
                entity_name=entity_name,
                total_quantity=total_qty,
                company_groups=company_groups,
                items=[_quant_to_item(q) for q in paginated],
                total=total_items,
                limit=limit,
                offset=offset
            ).model_dump()

        return await asyncio.to_thread(_get)

    @staticmethod
    async def get_entity_profile(
        tenant_id: str,
        entity_type: str,
        entity_id: int,
    ) -> dict[str, Any]:
        def _get():
            from odoo_app.models import Partner
            from doova_one_view.api.inventory.schemas import EntityProfileResponse
            
            if entity_type not in ["customer", "vendor", "supplier"]:
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
    async def get_product_inventory_details(
        tenant_id: str,
        product_id: int,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        company_ids: Optional[list[int]] = None,
        base_currency: Optional[str] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> dict[str, Any]:
        def _get():
            from odoo_app.models import Product
            from doova_one_view.api.inventory.schemas import (
                ProductInventoryDetailResponse, MetricDetailCompanyGroup
            )
            try:
                product = Product.objects.get(id=product_id, tenant_id=tenant_id)
            except Product.DoesNotExist:
                raise NotFoundError("Product", str(product_id))

            quants = InventoryService._company_filter(
                StockQuant.objects.filter(tenant_id=tenant_id, product_id=product_id),
                company_ids
            )
            
            quants_list = list(quants.select_related("lot", "company").order_by("-quantity", "-id"))
            total_qty = _to_float(quants.aggregate(total=Sum("quantity"))["total"])
            total_res = _to_float(quants.aggregate(total=Sum("reserved_quantity"))["total"])

            groups = {}
            for q in quants_list:
                company_obj = q.company
                cid = company_obj.odoo_id if company_obj else None
                cname = company_obj.name if company_obj else "Unknown Company"
                if cid not in groups:
                    groups[cid] = {
                        "company_id": cid,
                        "company_name": cname,
                        "metric_value": 0.0
                    }
                groups[cid]["metric_value"] += _to_float(q.quantity)

            company_groups = [
                MetricDetailCompanyGroup(**g) for g in groups.values()
            ]

            total_items = len(quants_list)
            paginated = quants_list[offset:offset + limit]

            return ProductInventoryDetailResponse(
                product_id=product.id,
                product_name=product.name,
                product_sku=product.default_code,
                product_type=product.product_type,
                list_price=_to_float(product.list_price) if product.list_price else None,
                total_quantity=total_qty,
                total_reserved=total_res,
                line_count=total_items,
                company_groups=company_groups,
                items=[_quant_to_item(q) for q in paginated],
                total=total_items,
                limit=limit,
                offset=offset
            ).model_dump()

        return await asyncio.to_thread(_get)
