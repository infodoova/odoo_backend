"""
Account Journals API service.
"""

import asyncio
from typing import Any, Optional
from django.db.models import Count, Q, F

from odoo_app.models.account_journal import AccountJournal
from doova_one_view.api.common.exceptions import NotFoundError
from doova_one_view.api.common.schemas import PaginatedResponse
from doova_one_view.api.account_journals.schemas import AccountJournalRead

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

def _company_filter(qs, company_ids: Optional[list[int]]):
    if company_ids and hasattr(qs.model, "company"):
        qs = qs.filter(company_id__in=company_ids)
    return qs

class AccountJournalService:
    """Service for account journals."""

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
    async def get_journals(tenant_id: str, limit: int = 50, offset: int = 0, search: Optional[str] = None, company_ids: Optional[list[int]] = None) -> PaginatedResponse[AccountJournalRead]:
        def _search():
            qs = _company_filter(AccountJournal.objects.filter(tenant_id=tenant_id), company_ids)
            if search:
                qs = qs.filter(Q(name__icontains=search) | Q(code__icontains=search))
            total = qs.count()
            items = list(qs.select_related("company").order_by("name")[offset : offset + limit])
            return items, total
        items, total = await asyncio.to_thread(_search)
        return PaginatedResponse(
            items=[AccountJournalRead.model_validate(st) for st in items],
            total=total,
            limit=limit,
            offset=offset
        )

    @staticmethod
    async def search_journals(tenant_id: str, filters: list[Any], limit: int = 50, offset: int = 0, company_ids: Optional[list[int]] = None) -> PaginatedResponse[AccountJournalRead]:
        def _search():
            field_map = {
                "id": "odoo_id", "odoo_id": "odoo_id", "name": "name",
                "code": "code", "type": "type", "currency_code": "currency_code",
                "company_id": "company_id", "company_name": "company__name", "company": "company__name"
            }
            qs = _company_filter(AccountJournal.objects.filter(tenant_id=tenant_id), company_ids)
            qs = AccountJournalService._apply_search(qs, filters, field_map)
            total = qs.count()
            items = list(qs.select_related("company").order_by("name")[offset : offset + limit])
            return items, total
        items, total = await asyncio.to_thread(_search)
        return PaginatedResponse(
            items=[AccountJournalRead.model_validate(st) for st in items],
            total=total,
            limit=limit,
            offset=offset
        )

    @staticmethod
    async def get_journals_filters(tenant_id: str, company_ids: Optional[list[int]] = None) -> dict[str, Any]:
        def _filters():
            qs = _company_filter(AccountJournal.objects.filter(tenant_id=tenant_id), company_ids)
            types = [v for v in qs.values_list("type", flat=True).distinct().order_by("type") if v]
            companies = [v for v in qs.values_list("company__name", flat=True).distinct().order_by("company__name") if v]
            return {
                "types": types,
                "companies": companies,
            }
        return await asyncio.to_thread(_filters)

    @staticmethod
    async def export_journals_csv(tenant_id: str, company_ids: Optional[list[int]] = None) -> str:
        def _export():
            qs = _company_filter(AccountJournal.objects.filter(tenant_id=tenant_id), company_ids).select_related("company").order_by("name")
            lines = ["Odoo ID,Name,Code,Type,Currency,Company"]
            for j in qs:
                cols = [
                    str(j.odoo_id),
                    _csv_escape(j.name or ""),
                    _csv_escape(j.code or ""),
                    _csv_escape(j.type or ""),
                    _csv_escape(j.currency_code or ""),
                    _csv_escape(j.company.name if j.company else ""),
                ]
                lines.append(",".join(cols))
            return "\\n".join(lines)
        return await asyncio.to_thread(_export)

    @staticmethod
    async def get_journal(tenant_id: str, journal_id: int, company_ids: Optional[list[int]] = None) -> AccountJournalRead:
        def _get():
            try:
                st = _company_filter(AccountJournal.objects.filter(tenant_id=tenant_id), company_ids).select_related("company").get(id=journal_id)
                return AccountJournalRead.model_validate(st)
            except AccountJournal.DoesNotExist:
                raise NotFoundError(f"Account journal {journal_id} not found")
        return await asyncio.to_thread(_get)
