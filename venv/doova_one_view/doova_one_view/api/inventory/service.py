"""
Inventory API service.
"""

import asyncio
from datetime import timedelta
from typing import Any, Optional

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
            recent_since = timezone.now() - timedelta(days=7)
            recent_moves = InventoryService._company_filter(
                StockMove.objects.filter(tenant_id=tenant_id, date__gte=recent_since),
                company_ids,
            ).count()
            return {
                "total_products_in_stock": stats["product_count"] or 0,
                "total_quantity": _to_float(stats["total_qty"]),
                "total_reserved_quantity": _to_float(stats["total_reserved"]),
                "recent_moves_count": recent_moves,
                "applied_filters": {"tenant_id": tenant_id, "company_ids": company_ids},
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

            total_items = _to_float(quants.aggregate(total=Sum("quantity"))["total"])
            stock_status_distribution = {
                "Available": quants.filter(quantity__gt=0, reserved_quantity__lt=F("quantity")).count(),
                "Reserved": quants.filter(reserved_quantity__gt=0).count(),
                "Empty": quants.filter(quantity__lte=0).count(),
            }
            company_distribution = {
                row["company__name"] or "Unknown": row["count"]
                for row in quants.values("company__name").annotate(count=Count("id"))
            }
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
            return {
                "total_stock_value": 0.0,
                "prev_total_stock_value": 0.0,
                "stock_value_change_pct": 0.0,
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
