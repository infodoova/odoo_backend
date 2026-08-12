"""
Account Partial Reconciles API service.
"""

import asyncio
from typing import Any, Optional
from django.db.models import Count, Q, F

from odoo_app.models.account_partial_reconcile import AccountPartialReconcile
from doova_one_view.api.common.exceptions import NotFoundError
from doova_one_view.api.common.schemas import PaginatedResponse
from doova_one_view.api.account_partial_reconciles.schemas import AccountPartialReconcileRead

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

class AccountPartialReconcileService:
    """Service for account partial reconciles."""

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
            
            if isinstance(value, dict) and "id" in value:
                value = value["id"]
            elif hasattr(value, "id"):
                value = value.id

            if orm_field in bool_fields:
                value = str(value).strip().lower() in ("true", "t", "1", "yes", "y")
            if orm_field.endswith("_id") or orm_field == "id":
                try:
                    int_val = int(value)
                    if op in ("contains", "contain", "startswith", "starts_with", "endswith", "ends_with", "equals", "eq", "="):
                        qs = qs.filter(**{orm_field: int_val})
                        continue
                    value = int_val
                except (ValueError, TypeError):
                    if isinstance(value, dict) and "name" in value:
                        value = value["name"]
                    elif hasattr(value, "name"):
                        value = value.name

                    if field in ("debit_move_line", "credit_move_line", "debit_move_line_id", "credit_move_line_id"):
                        orm_field = field.replace("_id", "") + "__name"
                    else:
                        continue

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
    async def get_reconciles(tenant_id: str, limit: int = 50, offset: int = 0, company_ids: Optional[list[int]] = None) -> PaginatedResponse[AccountPartialReconcileRead]:
        def _search():
            from doova_one_view.api.master_data.service import _company_filter
            qs = _company_filter(AccountPartialReconcile.objects.filter(tenant_id=tenant_id), company_ids).select_related(
                'debit_move_line', 'debit_move_line__product',
                'credit_move_line', 'credit_move_line__product',
                'company'
            )
            total = qs.count()
            items = list(qs.order_by("-id")[offset : offset + limit])
            return items, total
        items, total = await asyncio.to_thread(_search)
        return PaginatedResponse(
            items=[AccountPartialReconcileRead.model_validate(st) for st in items],
            total=total,
            limit=limit,
            offset=offset
        )

    @staticmethod
    async def search_reconciles(tenant_id: str, filters: list[Any], limit: int = 50, offset: int = 0, company_ids: Optional[list[int]] = None) -> PaginatedResponse[AccountPartialReconcileRead]:
        def _search():
            from doova_one_view.api.master_data.service import _company_filter
            field_map = {
                "id": "odoo_id", "odoo_id": "odoo_id",
                "amount": "amount", "max_date": "max_date",
                "company_id": "company_id", "company_name": "company__name",
                "debit_move_line_id": "debit_move_line_id",
                "credit_move_line_id": "credit_move_line_id",
                "debit_move_line": "debit_move_line_id",
                "credit_move_line": "credit_move_line_id",
                "debit_move_line.name": "debit_move_line__name",
                "debit_move_line.account_name": "debit_move_line__account_name",
                "debit_move_line.account_code": "debit_move_line__account_code",
                "credit_move_line.name": "credit_move_line__name",
                "credit_move_line.account_name": "credit_move_line__account_name",
                "credit_move_line.account_code": "credit_move_line__account_code",
            }
            qs = _company_filter(AccountPartialReconcile.objects.filter(tenant_id=tenant_id), company_ids).select_related(
                'debit_move_line', 'debit_move_line__product',
                'credit_move_line', 'credit_move_line__product',
                'company'
            )
            qs = AccountPartialReconcileService._apply_search(qs, filters, field_map)
            total = qs.count()
            items = list(qs.order_by("-id")[offset : offset + limit])
            return items, total
        items, total = await asyncio.to_thread(_search)
        return PaginatedResponse(
            items=[AccountPartialReconcileRead.model_validate(st) for st in items],
            total=total,
            limit=limit,
            offset=offset
        )

    @staticmethod
    async def get_reconciles_filters(tenant_id: str) -> dict[str, Any]:
        def _filters():
            return {}
        return await asyncio.to_thread(_filters)

    @staticmethod
    async def export_reconciles_csv(tenant_id: str, company_ids: Optional[list[int]] = None) -> str:
        def _export():
            from doova_one_view.api.master_data.service import _company_filter
            qs = _company_filter(AccountPartialReconcile.objects.filter(tenant_id=tenant_id), company_ids).select_related(
                'debit_move_line', 'credit_move_line', 'company'
            ).order_by("-id")
            lines = ["Odoo ID,Amount,Max Date,Debit Line Name,Debit Account,Credit Line Name,Credit Account"]
            for r in qs:
                cols = [
                    str(r.odoo_id),
                    str(r.amount or 0),
                    _iso(r.max_date) or "",
                    _csv_escape(r.debit_move_line.name if r.debit_move_line else ""),
                    _csv_escape(r.debit_move_line.account_name if r.debit_move_line else ""),
                    _csv_escape(r.credit_move_line.name if r.credit_move_line else ""),
                    _csv_escape(r.credit_move_line.account_name if r.credit_move_line else ""),
                ]
                lines.append(",".join(cols))
            return "\\n".join(lines)
        return await asyncio.to_thread(_export)

    @staticmethod
    async def get_reconcile(tenant_id: str, reconcile_id: int) -> AccountPartialReconcileRead:
        def _get():
            try:
                st = AccountPartialReconcile.objects.select_related(
                    'debit_move_line', 'debit_move_line__product',
                    'credit_move_line', 'credit_move_line__product'
                ).get(tenant_id=tenant_id, id=reconcile_id)
                return AccountPartialReconcileRead.model_validate(st)
            except AccountPartialReconcile.DoesNotExist:
                raise NotFoundError(f"Account partial reconcile {reconcile_id} not found")
        return await asyncio.to_thread(_get)
