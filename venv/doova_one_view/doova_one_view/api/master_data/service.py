"""
Master Data API service.
"""

import asyncio
from typing import Any, Optional

from django.db.models import Count, Q

from odoo_app.models.company import Company
from odoo_app.models.currency import Currency
from odoo_app.models.lot import Lot
from odoo_app.models.partner import Partner
from odoo_app.models.product import Product
from odoo_app.models.product_category import ProductCategory
from odoo_app.models.chart_of_accounts import ChartOfAccounts
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


def _bool_to_csv(value: Any) -> str:
    return "Yes" if bool(value) else "No"


def _company_filter(qs, company_ids: Optional[list[int]]):
    if company_ids and hasattr(qs.model, "company"):
        qs = qs.filter(company_id__in=company_ids)
    return qs


def _company_to_item(company: Company) -> dict[str, Any]:
    return {
        "id": company.id,
        "tenant_id": str(company.tenant_id) if company.tenant_id is not None else None,
        "odoo_id": company.odoo_id,
        "name": company.name,
        "display_name": company.display_name,
        "currency_id": company.currency_id,
        "currency_name": company.currency_name,
        "currency_code": company.currency_code or "",
        "country_id": company.country_id,
        "country_name": company.country_name,
        "country_code": company.country_code,
        "is_active": company.is_active,
        "synced_at": _iso(company.odoo_write_date),
    }


def _currency_to_item(currency: Currency) -> dict[str, Any]:
    return {
        "id": currency.id,
        "odoo_id": currency.odoo_id,
        "code": currency.code,
        "symbol": currency.symbol,
        "is_active": currency.is_active,
        "symbol_position": currency.symbol_position,
        "rounding": _to_float(currency.rounding),
        "synced_at": _iso(currency.synced_at),
    }


def _partner_to_item(partner: Partner) -> dict[str, Any]:
    company = getattr(partner, "company", None)
    return {
        "id": partner.id,
        "odoo_id": partner.odoo_id,
        "name": partner.name,
        "display_name": partner.name,
        "partner_type": partner.partner_type,
        "ref": "",
        "email": partner.email,
        "phone": partner.phone,
        "mobile": "",
        "country_code": partner.country_code,
        "city": partner.city,
        "is_customer": partner.is_customer,
        "is_supplier": partner.is_supplier,
        "customer_rank": partner.customer_rank,
        "supplier_rank": partner.supplier_rank,
        "is_active": partner.is_active,
        "company": {"id": company.id, "name": company.name} if company else None,
        "company_id": getattr(partner, "company_id", None),
        "company_name": company.name if company else "",
        "synced_at": _iso(partner.created_at),
    }


def _product_to_item(product: Product) -> dict[str, Any]:
    category = getattr(product, "category", None)
    company = getattr(product, "company", None)
    return {
        "id": product.id,
        "odoo_id": product.odoo_id,
        "odoo_template_id": product.odoo_template_id,
        "name": product.name,
        "default_code": product.default_code or "",
        "barcode": product.barcode or "",
        "product_type": product.product_type or "",
        "category_id": getattr(product, "category_id", None),
        "category": category.complete_name or category.name if category else "",
        "list_price": _to_float(product.list_price),
        "standard_price": _to_float(product.standard_price),
        "uom_name": product.uom_name or "",
        "is_active": product.is_active,
        "company": {"id": company.id, "name": company.name} if company else None,
        "company_id": getattr(product, "company_id", None),
        "company_name": company.name if company else "",
        "synced_at": _iso(product.created_at),
    }


def _lot_to_item(lot: Lot) -> dict[str, Any]:
    product = getattr(lot, "product", None)
    company = getattr(lot, "company", None)
    return {
        "id": lot.id,
        "odoo_id": lot.odoo_id,
        "name": lot.name,
        "ref": lot.ref or "",
        "product_id": getattr(lot, "product_id", None),
        "product_name": product.name if product else "",
        "product": (
            {"id": product.id, "name": product.name, "default_code": product.default_code}
            if product else None
        ),
        "company_id": getattr(lot, "company_id", None),
        "company_name": company.name if company else "",
        "company": {"id": company.id, "name": company.name} if company else None,
        "expiration_date": _iso(lot.expiration_date),
        "use_date": _iso(lot.use_date),
        "removal_date": _iso(lot.removal_date),
        "alert_date": _iso(lot.alert_date),
        "synced_at": _iso(lot.synced_at),
    }


def _coa_to_item(coa: ChartOfAccounts) -> dict[str, Any]:
    company = getattr(coa, "company", None)
    return {
        "id": coa.id,
        "odoo_id": coa.odoo_id,
        "code": coa.code,
        "name": coa.name,
        "account_type": coa.account_type,
        "reconcile": coa.reconcile,
        "deprecated": coa.deprecated,
        "company_id": getattr(coa, "company_id", None),
        "company_name": company.name if company else "",
        "company": {"id": company.id, "name": company.name} if company else None,
        "synced_at": _iso(coa.synced_at),
    }


def _category_to_node(category: ProductCategory, product_count: Optional[int] = None) -> dict[str, Any]:
    return {
        "id": category.id,
        "odoo_id": category.odoo_id,
        "name": category.name,
        "complete_name": category.complete_name or category.name,
        "parent_id": getattr(category, "parent_id", None),
        "parent_odoo_id": category.parent.odoo_id if category.parent else None,
        "parent_name": category.parent.name if category.parent else "",
        "product_count": product_count if product_count is not None else 0,
        "active": True,
        "company": "",
        "synced_at": None,
        "created_at": None,
        "updated_at": None,
    }


class MasterDataService:
    """Service for master data dimensions."""

    @staticmethod
    def _apply_search(qs, filters: list[Any], field_map: dict[str, str], bool_fields: set[str] | None = None):
        bool_fields = bool_fields or set()
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
            if orm_field in bool_fields:
                value = str(value).strip().lower() in ("true", "t", "1", "yes", "y")
            if op in ("contains", "contain"):
                qs = qs.filter(**{f"{orm_field}__icontains": value})
            elif op in ("startswith", "starts_with"):
                qs = qs.filter(**{f"{orm_field}__istartswith": value})
            elif op in ("endswith", "ends_with"):
                qs = qs.filter(**{f"{orm_field}__iendswith": value})
            elif op in ("equals", "eq", "="):
                qs = qs.filter(**{orm_field: value})
            elif op in ("in",):
                if isinstance(value, list):
                    qs = qs.filter(**{f"{orm_field}__in": value})
                elif isinstance(value, (str, int)):
                    from doova_one_view.api.common.utils import parse_company_ids
                    c_ids = parse_company_ids(value)
                    if c_ids:
                        qs = qs.filter(**{f"{orm_field}__in": c_ids})
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
    async def get_companies(tenant_id: str, limit: int = 50, offset: int = 0, active_only: bool = False) -> dict[str, Any]:
        def _list():
            qs = Company.objects.filter(tenant_id=tenant_id)
            if active_only:
                qs = qs.filter(is_active=True)
            total = qs.count()
            items = [_company_to_item(c) for c in qs.order_by("name", "id")[offset : offset + limit]]
            return {"items": items, "total": total, "limit": limit, "offset": offset}
        return await asyncio.to_thread(_list)

    @staticmethod
    async def get_currencies(tenant_id: str, limit: int = 50, offset: int = 0, active_only: bool = True) -> dict[str, Any]:
        def _list():
            qs = Currency.objects.filter(tenant_id=tenant_id)
            if active_only:
                qs = qs.filter(is_active=True)
            total = qs.count()
            items = [_currency_to_item(c) for c in qs.order_by("code", "id")[offset : offset + limit]]
            return {"items": items, "total": total, "limit": limit, "offset": offset}
        return await asyncio.to_thread(_list)

    @staticmethod
    async def get_partners(
        tenant_id: str,
        limit: int = 50,
        offset: int = 0,
        search: Optional[str] = None,
        is_customer: Optional[bool] = None,
        is_supplier: Optional[bool] = None,
        company_ids: Optional[list[int]] = None,
    ) -> dict[str, Any]:
        def _list():
            qs = _company_filter(Partner.objects.filter(tenant_id=tenant_id), company_ids)
            if is_customer is not None:
                qs = qs.filter(is_customer=is_customer)
            if is_supplier is not None:
                qs = qs.filter(is_supplier=is_supplier)
            if search:
                qs = qs.filter(Q(name__icontains=search) | Q(email__icontains=search) | Q(phone__icontains=search))
            total = qs.count()
            items = [_partner_to_item(p) for p in qs.select_related("company").order_by("name", "id")[offset : offset + limit]]
            return {"items": items, "total": total, "limit": limit, "offset": offset, "applied_filters": {"tenant_id": tenant_id, "company_ids": company_ids}}
        return await asyncio.to_thread(_list)

    @staticmethod
    async def search_partners(tenant_id: str, filters: list[Any], limit: int, offset: int, company_ids: Optional[list[int]] = None) -> dict[str, Any]:
        field_map = {
            "id": "id", "odoo_id": "odoo_id", "name": "name",
            "display_name": "name", "partner_type": "partner_type",
            "email": "email", "phone": "phone", "city": "city",
            "is_customer": "is_customer", "is_supplier": "is_supplier",
            "is_active": "is_active",
            "company_id": "company_id", "company_name": "company__name",
        }
        def _search():
            qs = _company_filter(Partner.objects.filter(tenant_id=tenant_id), company_ids)
            qs = MasterDataService._apply_search(
                qs,
                filters,
                field_map,
                {"is_customer", "is_supplier", "is_active"},
            )
            total = qs.count()
            items = [_partner_to_item(p) for p in qs.select_related("company").order_by("name", "id")[offset : offset + limit]]
            return {"items": items, "total": total, "limit": limit, "offset": offset, "applied_filters": {"tenant_id": tenant_id, "filters": [getattr(f, "model_dump", lambda: dict(f))() for f in (filters or [])], "company_ids": company_ids}}
        return await asyncio.to_thread(_search)

    @staticmethod
    async def get_products(
        tenant_id: str,
        limit: int = 50,
        offset: int = 0,
        search: Optional[str] = None,
        company_ids: Optional[list[int]] = None,
    ) -> dict[str, Any]:
        def _list():
            qs = _company_filter(Product.objects.filter(tenant_id=tenant_id), company_ids)
            if search:
                qs = qs.filter(Q(name__icontains=search) | Q(default_code__icontains=search) | Q(barcode__icontains=search))
            total = qs.count()
            items = [_product_to_item(p) for p in qs.select_related("category", "company").order_by("name", "id")[offset : offset + limit]]
            return {"items": items, "total": total, "limit": limit, "offset": offset, "applied_filters": {"tenant_id": tenant_id, "company_ids": company_ids}}
        return await asyncio.to_thread(_list)

    @staticmethod
    async def search_products(tenant_id: str, filters: list[Any], limit: int, offset: int, company_ids: Optional[list[int]] = None) -> dict[str, Any]:
        field_map = {
            "id": "id", "odoo_id": "odoo_id", "name": "name",
            "default_code": "default_code", "barcode": "barcode",
            "product_type": "product_type", "category": "category__name",
            "list_price": "list_price", "standard_price": "standard_price",
            "uom_name": "uom_name", "is_active": "is_active",
            "company_id": "company_id", "company_name": "company__name",
        }
        def _search():
            qs = _company_filter(Product.objects.filter(tenant_id=tenant_id), company_ids)
            qs = MasterDataService._apply_search(qs, filters, field_map, {"is_active"})
            total = qs.count()
            items = [_product_to_item(p) for p in qs.select_related("category", "company").order_by("name", "id")[offset : offset + limit]]
            return {"items": items, "total": total, "limit": limit, "offset": offset, "applied_filters": {"tenant_id": tenant_id, "filters": [getattr(f, "model_dump", lambda: dict(f))() for f in (filters or [])], "company_ids": company_ids}}
        return await asyncio.to_thread(_search)

    @staticmethod
    async def get_categories_tree(tenant_id: str) -> list[dict[str, Any]]:
        def _tree():
            categories = list(ProductCategory.objects.filter(tenant_id=tenant_id).select_related("parent").order_by("complete_name", "name", "id"))
            counts = dict(Product.objects.filter(tenant_id=tenant_id, category_id__isnull=False).values_list("category_id").annotate(c=Count("id")))
            nodes = {cat.id: {**_category_to_node(cat, counts.get(cat.id, 0)), "children": []} for cat in categories}
            roots = []
            for cat in categories:
                node = nodes[cat.id]
                if cat.parent_id and cat.parent_id in nodes:
                    nodes[cat.parent_id]["children"].append(node)
                else:
                    roots.append(node)
            return roots
        return await asyncio.to_thread(_tree)

    @staticmethod
    async def get_category(tenant_id: str, category_id: int, include_products: bool = False) -> dict[str, Any]:
        def _get():
            qs = ProductCategory.objects.filter(tenant_id=tenant_id).select_related("parent")
            category = qs.filter(id=category_id).first()
            if category is None:
                try:
                    category = qs.get(odoo_id=category_id)
                except ProductCategory.DoesNotExist:
                    raise NotFoundError("ProductCategory", str(category_id))
            count = Product.objects.filter(tenant_id=tenant_id, category_id=category.id).count()
            node = _category_to_node(category, count)
            if include_products:
                products = Product.objects.filter(tenant_id=tenant_id, category_id=category.id).select_related("category").order_by("name", "id")
                node["products"] = [_product_to_item(p) for p in products]
            else:
                node["products"] = []
            return node
        return await asyncio.to_thread(_get)

    @staticmethod
    async def get_lots(tenant_id: str, limit: int = 50, offset: int = 0, company_ids: Optional[list[int]] = None) -> dict[str, Any]:
        def _list():
            qs = _company_filter(Lot.objects.filter(tenant_id=tenant_id), company_ids)
            total = qs.count()
            items = [_lot_to_item(l) for l in qs.select_related("product", "company").order_by("name", "id")[offset : offset + limit]]
            return {"items": items, "total": total, "limit": limit, "offset": offset, "applied_filters": {"tenant_id": tenant_id, "company_ids": company_ids}}
        return await asyncio.to_thread(_list)

    @staticmethod
    async def search_lots(tenant_id: str, filters: list[Any], limit: int, offset: int, company_ids: Optional[list[int]] = None) -> dict[str, Any]:
        field_map = {
            "id": "id", "odoo_id": "odoo_id", "name": "name", "ref": "ref",
            "product_name": "product__name", "expiration_date": "expiration_date",
            "use_date": "use_date", "removal_date": "removal_date",
            "alert_date": "alert_date", "company_name": "company__name",
        }
        def _search():
            qs = _company_filter(Lot.objects.filter(tenant_id=tenant_id), company_ids)
            qs = MasterDataService._apply_search(qs, filters, field_map)
            total = qs.count()
            items = [_lot_to_item(l) for l in qs.select_related("product", "company").order_by("name", "id")[offset : offset + limit]]
            return {"items": items, "total": total, "limit": limit, "offset": offset, "applied_filters": {"tenant_id": tenant_id, "filters": [getattr(f, "model_dump", lambda: dict(f))() for f in (filters or [])], "company_ids": company_ids}}
        return await asyncio.to_thread(_search)

    @staticmethod
    async def get_lots_filters(tenant_id: str, company_ids: Optional[list[int]] = None) -> dict[str, Any]:
        def _filters():
            qs = _company_filter(Lot.objects.filter(tenant_id=tenant_id), company_ids)
            products = [v for v in qs.values_list("product__name", flat=True).distinct().order_by("product__name") if v]
            refs = [v for v in qs.values_list("ref", flat=True).distinct().order_by("ref") if v]
            companies = [v for v in qs.values_list("company__name", flat=True).distinct().order_by("company__name") if v]
            return {
                "products": products,
                "product_names": products,
                "refs": refs,
                "companies": companies,
                "company": companies,
                "applied_filters": {"tenant_id": tenant_id, "company_ids": company_ids},
            }
        return await asyncio.to_thread(_filters)

    @staticmethod
    async def get_products_filters(tenant_id: str, company_ids: Optional[list[int]] = None) -> dict[str, Any]:
        def _filters():
            products = Product.objects.filter(tenant_id=tenant_id)
            companies = Company.objects.filter(tenant_id=tenant_id)
            return {
                "product_types": sorted({v for v in products.values_list("product_type", flat=True).distinct() if v}),
                "categories": sorted({v for v in products.values_list("category__name", flat=True).distinct() if v}),
                "uom_names": sorted({v for v in products.values_list("uom_name", flat=True).distinct() if v}),
                "products": [
                    {"id": row["id"], "name": row["name"], "value": str(row["id"]), "label": row["name"]}
                    for row in products.values("id", "name").order_by("name")[:1000]
                ],
                "companies": [
                    {"id": c.id, "name": c.name, "value": str(c.id), "label": c.name}
                    for c in companies.order_by("name")
                ],
                "applied_filters": {"tenant_id": tenant_id, "company_ids": company_ids},
            }
        return await asyncio.to_thread(_filters)

    @staticmethod
    async def get_partners_filters(tenant_id: str) -> dict[str, Any]:
        def _filters():
            partners = Partner.objects.filter(tenant_id=tenant_id)
            companies = Company.objects.filter(tenant_id=tenant_id)
            return {
                "partner_types": sorted({v for v in partners.values_list("partner_type", flat=True).distinct() if v}),
                "cities": sorted({v for v in partners.values_list("city", flat=True).distinct() if v}),
                "country_codes": sorted({v for v in partners.values_list("country_code", flat=True).distinct() if v}),
                "partners": [
                    {"id": row["id"], "name": row["name"], "value": str(row["id"]), "label": row["name"]}
                    for row in partners.values("id", "name").order_by("name")[:1000]
                ],
                "companies": [
                    {"id": c.id, "name": c.name, "value": str(c.id), "label": c.name}
                    for c in companies.order_by("name")
                ],
                "applied_filters": {"tenant_id": tenant_id},
            }
        return await asyncio.to_thread(_filters)

    @staticmethod
    async def get_enums(tenant_id: str) -> dict[str, Any]:
        def _enums():
            return {
                "product_types": [choice[0] for choice in Product.PRODUCT_TYPE_CHOICES],
                "partner_types": sorted({v for v in Partner.objects.filter(tenant_id=tenant_id).values_list("partner_type", flat=True).distinct() if v}),
                "currency_codes": sorted({v for v in Currency.objects.filter(tenant_id=tenant_id).values_list("code", flat=True).distinct() if v}),
            }
        return await asyncio.to_thread(_enums)

    @staticmethod
    async def get_filters(tenant_id: str, company_ids: Optional[list[int]] = None) -> dict[str, Any]:
        def _filters():
            products = Product.objects.filter(tenant_id=tenant_id).select_related("category")
            partners = Partner.objects.filter(tenant_id=tenant_id)
            lots = _company_filter(Lot.objects.filter(tenant_id=tenant_id), company_ids)
            companies = Company.objects.filter(tenant_id=tenant_id)
            return {
                "product_types": sorted({v for v in products.values_list("product_type", flat=True).distinct() if v}),
                "categories": sorted({v for v in products.values_list("category__name", flat=True).distinct() if v}),
                "partner_types": sorted({v for v in partners.values_list("partner_type", flat=True).distinct() if v}),
                "cities": sorted({v for v in partners.values_list("city", flat=True).distinct() if v}),
                "products": [
                    {"id": row["id"], "name": row["name"], "value": str(row["id"]), "label": row["name"]}
                    for row in products.values("id", "name").order_by("name")[:1000]
                ],
                "lots": [
                    {"id": row["id"], "name": row["name"], "value": str(row["id"]), "label": row["name"]}
                    for row in lots.values("id", "name").order_by("name")[:1000]
                ],
                "companies": [
                    {"id": c.id, "name": c.name, "value": str(c.id), "label": c.name}
                    for c in companies.order_by("name")
                ],
                "applied_filters": {"tenant_id": tenant_id, "company_ids": company_ids},
            }
        return await asyncio.to_thread(_filters)

    @staticmethod
    async def export_partners_csv(tenant_id: str) -> str:
        headers = ["Odoo ID", "Name", "Email", "Phone", "City", "Customer", "Supplier", "Active"]
        rows = (await MasterDataService.get_partners(tenant_id, 100000, 0))["items"]
        return "\n".join([",".join(headers)] + [",".join([
            _csv_escape(row.get("odoo_id") or ""),
            _csv_escape(row.get("name") or ""),
            _csv_escape(row.get("email") or ""),
            _csv_escape(row.get("phone") or ""),
            _csv_escape(row.get("city") or ""),
            _bool_to_csv(row.get("is_customer")),
            _bool_to_csv(row.get("is_supplier")),
            _bool_to_csv(row.get("is_active")),
        ]) for row in rows])

    @staticmethod
    async def export_products_csv(tenant_id: str, company_ids: Optional[list[int]] = None) -> str:
        headers = ["Odoo ID", "Name", "Reference", "Barcode", "Type", "Category", "Price", "Cost", "UOM", "Active", "Company", "Synced"]
        rows = (await MasterDataService.get_products(tenant_id, 100000, 0, None, company_ids))["items"]
        return "\n".join([",".join(headers)] + [",".join([
            _csv_escape(row.get("odoo_id") or ""),
            _csv_escape(row.get("name") or ""),
            _csv_escape(row.get("default_code") or ""),
            _csv_escape(row.get("barcode") or ""),
            _csv_escape(row.get("product_type") or ""),
            _csv_escape(row.get("category") or ""),
            _csv_escape(row.get("list_price")),
            _csv_escape(row.get("standard_price")),
            _csv_escape(row.get("uom_name") or ""),
            _bool_to_csv(row.get("is_active")),
            _csv_escape(row.get("company") or ""),
            _csv_escape(row.get("synced_at") or ""),
        ]) for row in rows])

    @staticmethod
    async def export_lots_csv(tenant_id: str, company_ids: Optional[list[int]] = None) -> str:
        headers = ["Odoo ID", "Lot/Serial Number", "Product", "Reference", "Expiration Date", "Use Date", "Removal Date", "Alert Date", "Company", "Synced"]
        rows = (await MasterDataService.get_lots(tenant_id, 100000, 0, company_ids))["items"]
        return "\n".join([",".join(headers)] + [",".join([
            _csv_escape(row.get("odoo_id") or ""),
            _csv_escape(row.get("name") or ""),
            _csv_escape(row.get("product_name") or ""),
            _csv_escape(row.get("ref") or ""),
            _csv_escape(row.get("expiration_date") or ""),
            _csv_escape(row.get("use_date") or ""),
            _csv_escape(row.get("removal_date") or ""),
            _csv_escape(row.get("alert_date") or ""),
            _csv_escape(row.get("company_name") or ""),
            _csv_escape(row.get("synced_at") or ""),
        ]) for row in rows])

    @staticmethod
    async def get_chart_of_accounts(tenant_id: str, limit: int = 50, offset: int = 0, search: Optional[str] = None, company_ids: Optional[list[int]] = None) -> dict[str, Any]:
        def _list():
            qs = _company_filter(ChartOfAccounts.objects.filter(tenant_id=tenant_id), company_ids)
            if search:
                qs = qs.filter(Q(name__icontains=search) | Q(code__icontains=search))
            total = qs.count()
            items = [_coa_to_item(c) for c in qs.select_related("company").order_by("code", "id")[offset : offset + limit]]
            return {"items": items, "total": total, "limit": limit, "offset": offset, "applied_filters": {"tenant_id": tenant_id, "company_ids": company_ids}}
        return await asyncio.to_thread(_list)

    @staticmethod
    async def search_chart_of_accounts(tenant_id: str, filters: list[Any], limit: int, offset: int, company_ids: Optional[list[int]] = None) -> dict[str, Any]:
        field_map = {
            "id": "id", "odoo_id": "odoo_id", "code": "code", "name": "name",
            "account_type": "account_type", "reconcile": "reconcile", "deprecated": "deprecated",
            "company_id": "company_id", "company_name": "company__name",
        }
        def _search():
            qs = _company_filter(ChartOfAccounts.objects.filter(tenant_id=tenant_id), company_ids)
            qs = MasterDataService._apply_search(qs, filters, field_map)
            total = qs.count()
            items = [_coa_to_item(c) for c in qs.select_related("company").order_by("code", "id")[offset : offset + limit]]
            return {"items": items, "total": total, "limit": limit, "offset": offset, "applied_filters": {"tenant_id": tenant_id, "filters": [getattr(f, "model_dump", lambda: dict(f))() for f in (filters or [])], "company_ids": company_ids}}
        return await asyncio.to_thread(_search)

    @staticmethod
    async def get_chart_of_accounts_filters(tenant_id: str) -> dict[str, Any]:
        def _filters():
            qs = ChartOfAccounts.objects.filter(tenant_id=tenant_id)
            account_types = [v for v in qs.values_list("account_type", flat=True).distinct().order_by("account_type") if v]
            return {
                "account_types": account_types,
                "applied_filters": {"tenant_id": tenant_id},
            }
        return await asyncio.to_thread(_filters)

    @staticmethod
    async def export_chart_of_accounts_csv(tenant_id: str) -> str:
        headers = ["Odoo ID", "Code", "Name", "Account Type", "Reconcile", "Deprecated", "Synced"]
        rows = (await MasterDataService.get_chart_of_accounts(tenant_id, 100000, 0))["items"]
        return "\n".join([",".join(headers)] + [",".join([
            _csv_escape(row.get("odoo_id") or ""),
            _csv_escape(row.get("code") or ""),
            _csv_escape(row.get("name") or ""),
            _csv_escape(row.get("account_type") or ""),
            _bool_to_csv(row.get("reconcile")),
            _bool_to_csv(row.get("deprecated")),
            _csv_escape(row.get("synced_at") or ""),
        ]) for row in rows])


    # Backward-compatible method names used by older routes/tests.
    list_products = get_products
    list_partners = get_partners
    list_currencies = get_currencies
    list_companies = get_companies
