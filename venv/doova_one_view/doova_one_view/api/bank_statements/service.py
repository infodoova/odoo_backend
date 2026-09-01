"""
Bank Statements API service.
"""

import asyncio
from typing import Any, Optional
from django.db.models import Count, Q, F

from odoo_app.models.bank_statement import BankStatement
from odoo_app.models.bank_statement_line import BankStatementLine
from doova_one_view.api.common.exceptions import NotFoundError
from doova_one_view.api.common.schemas import PaginatedResponse
from doova_one_view.api.bank_statements.schemas import BankStatementRead, BankStatementLineRead

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

def _date_filter(qs, start_date: Optional[str] = None, end_date: Optional[str] = None):
    if start_date:
        qs = qs.filter(date__gte=start_date)
    if end_date:
        qs = qs.filter(date__lte=end_date)
    return qs

class BankStatementService:
    """Service for bank statements and lines."""

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
    async def get_statements(tenant_id: str, limit: int = 50, offset: int = 0, search: Optional[str] = None, company_ids: Optional[list[int]] = None, start_date: Optional[str] = None, end_date: Optional[str] = None) -> PaginatedResponse[BankStatementRead]:
        def _search():
            qs = _date_filter(_company_filter(BankStatement.objects.filter(tenant_id=tenant_id), company_ids), start_date, end_date)
            if search:
                qs = qs.filter(Q(odoo_name__icontains=search) | Q(journal_name__icontains=search))
            total = qs.count()
            items = list(qs.select_related("company").order_by(F("date").desc(nulls_last=True), "-id")[offset : offset + limit])
            return items, total
        items, total = await asyncio.to_thread(_search)
        return PaginatedResponse(
            items=[BankStatementRead.model_validate(st) for st in items],
            total=total,
            limit=limit,
            offset=offset
        )

    @staticmethod
    async def search_statements(tenant_id: str, filters: list[Any], limit: int = 50, offset: int = 0, company_ids: Optional[list[int]] = None) -> PaginatedResponse[BankStatementRead]:
        def _search():
            field_map = {
                "id": "odoo_id", "odoo_id": "odoo_id", "odoo_name": "odoo_name",
                "journal_name": "journal_name", "journal": "journal_name",
                "date": "date", "state": "state",
                "balance_start": "balance_start", "balance_end_real": "balance_end_real",
                "company_id": "company_id", "company_name": "company__name", "company": "company__name"
            }
            qs = _company_filter(BankStatement.objects.filter(tenant_id=tenant_id), company_ids)
            qs = BankStatementService._apply_search(qs, filters, field_map)
            total = qs.count()
            items = list(qs.select_related("company").order_by(F("date").desc(nulls_last=True), "-id")[offset : offset + limit])
            return items, total
        items, total = await asyncio.to_thread(_search)
        return PaginatedResponse(
            items=[BankStatementRead.model_validate(st) for st in items],
            total=total,
            limit=limit,
            offset=offset
        )

    @staticmethod
    async def get_statements_filters(tenant_id: str, company_ids: Optional[list[int]] = None) -> dict[str, Any]:
        def _filters():
            qs = _company_filter(BankStatement.objects.filter(tenant_id=tenant_id), company_ids)
            journals = [v for v in qs.values_list("journal_name", flat=True).distinct().order_by("journal_name") if v]
            states = [v for v in qs.values_list("state", flat=True).distinct().order_by("state") if v]
            companies = [v for v in qs.values_list("company__name", flat=True).distinct().order_by("company__name") if v]
            return {
                "journals": journals,
                "states": states,
                "companies": companies,
            }
        return await asyncio.to_thread(_filters)

    @staticmethod
    async def export_statements_csv(tenant_id: str, company_ids: Optional[list[int]] = None) -> str:
        def _export():
            qs = _company_filter(BankStatement.objects.filter(tenant_id=tenant_id), company_ids).select_related("company").order_by(F("date").desc(nulls_last=True), "-id")
            lines = ["Odoo ID,Name,Date,Journal,Start Balance,End Balance,State,Company"]
            for st in qs:
                cols = [
                    str(st.odoo_id),
                    _csv_escape(st.odoo_name or ""),
                    _iso(st.date) or "",
                    _csv_escape(st.journal_name or ""),
                    str(st.balance_start or 0),
                    str(st.balance_end_real or 0),
                    _csv_escape(st.state or ""),
                    _csv_escape(st.company.name if st.company else ""),
                ]
                lines.append(",".join(cols))
            return "\n".join(lines)
        return await asyncio.to_thread(_export)

    @staticmethod
    async def get_statement(tenant_id: str, statement_id: int, company_ids: Optional[list[int]] = None) -> BankStatementRead:
        def _get():
            try:
                st = _company_filter(BankStatement.objects.filter(tenant_id=tenant_id), company_ids).select_related("company").get(id=statement_id)
                return BankStatementRead.model_validate(st)
            except BankStatement.DoesNotExist:
                raise NotFoundError(f"Bank statement {statement_id} not found")
        return await asyncio.to_thread(_get)

    @staticmethod
    async def get_statement_lines(tenant_id: str, statement_id: Optional[int] = None, limit: int = 50, offset: int = 0, search: Optional[str] = None, company_ids: Optional[list[int]] = None, start_date: Optional[str] = None, end_date: Optional[str] = None) -> PaginatedResponse[BankStatementLineRead]:
        def _search():
            qs = _date_filter(_company_filter(BankStatementLine.objects.filter(tenant_id=tenant_id), company_ids), start_date, end_date)
            if statement_id is not None:
                qs = qs.filter(statement_id=statement_id)
            if search:
                qs = qs.filter(Q(name__icontains=search) | Q(ref__icontains=search))
            total = qs.count()
            items = list(qs.select_related("company", "partner", "statement").order_by(F("date").desc(nulls_last=True), "-id")[offset : offset + limit])
            return items, total
        items, total = await asyncio.to_thread(_search)
        return PaginatedResponse(
            items=[BankStatementLineRead.model_validate(line) for line in items],
            total=total,
            limit=limit,
            offset=offset
        )

    @staticmethod
    async def search_statement_lines(tenant_id: str, filters: list[Any], limit: int = 50, offset: int = 0, company_ids: Optional[list[int]] = None) -> PaginatedResponse[BankStatementLineRead]:
        def _search():
            field_map = {
                "id": "odoo_id", "odoo_id": "odoo_id", "name": "name", "date": "date",
                "amount": "amount", "ref": "ref", "statement_id": "statement_id",
                "company_id": "company_id", "partner_id": "partner_id",
                "company_name": "company__name", "company": "company__name",
                "partner_name": "partner__name", "partner": "partner__name",
                "journal": "statement__journal_name", "journal_name": "statement__journal_name"
            }
            bool_fields = {"is_customer", "is_supplier"}
            qs = _company_filter(BankStatementLine.objects.filter(tenant_id=tenant_id), company_ids)
            qs = BankStatementService._apply_search(qs, filters, field_map, bool_fields)
            total = qs.count()
            items = list(qs.select_related("company", "partner", "statement").order_by(F("date").desc(nulls_last=True), "-id")[offset : offset + limit])
            return items, total
        items, total = await asyncio.to_thread(_search)
        return PaginatedResponse(
            items=[BankStatementLineRead.model_validate(line) for line in items],
            total=total,
            limit=limit,
            offset=offset
        )

    @staticmethod
    async def get_statement_lines_filters(tenant_id: str, company_ids: Optional[list[int]] = None) -> dict[str, Any]:
        def _filters():
            qs = _company_filter(BankStatementLine.objects.filter(tenant_id=tenant_id), company_ids)
            partners = [v for v in qs.values_list("partner__name", flat=True).distinct().order_by("partner__name") if v]
            companies = [v for v in qs.values_list("company__name", flat=True).distinct().order_by("company__name") if v]
            return {
                "partners": partners,
                "companies": companies,
            }
        return await asyncio.to_thread(_filters)

    @staticmethod
    async def export_statement_lines_csv(tenant_id: str, company_ids: Optional[list[int]] = None, start_date: Optional[str] = None, end_date: Optional[str] = None) -> str:
        def _export():
            qs = _date_filter(_company_filter(BankStatementLine.objects.filter(tenant_id=tenant_id), company_ids), start_date, end_date).select_related("company", "partner", "statement").order_by(F("date").desc(nulls_last=True), "-id")
            lines = ["Odoo ID,Statement Name,Date,Description,Amount,Partner,Reference,Company"]
            for l in qs:
                cols = [
                    str(l.odoo_id),
                    _csv_escape(l.statement.odoo_name if l.statement else ""),
                    _iso(l.date) or "",
                    _csv_escape(l.name or ""),
                    str(l.amount or 0),
                    _csv_escape(l.partner.name if l.partner else ""),
                    _csv_escape(l.ref or ""),
                    _csv_escape(l.company.name if l.company else ""),
                ]
                lines.append(",".join(cols))
            return "\n".join(lines)
        return await asyncio.to_thread(_export)

    @staticmethod
    async def get_statement_line(tenant_id: str, line_id: int, company_ids: Optional[list[int]] = None) -> BankStatementLineRead:
        def _get():
            try:
                line = _company_filter(BankStatementLine.objects.filter(tenant_id=tenant_id), company_ids).select_related("company", "partner", "statement").get(id=line_id)
                return BankStatementLineRead.model_validate(line)
            except BankStatementLine.DoesNotExist:
                raise NotFoundError(f"Bank statement line {line_id} not found")
        return await asyncio.to_thread(_get)

    @staticmethod
    async def get_lines_for_statement(tenant_id: str, statement_id: int, limit: int = 50, offset: int = 0, company_ids: Optional[list[int]] = None) -> PaginatedResponse[BankStatementLineRead]:
        def _search():
            qs = _company_filter(BankStatementLine.objects.filter(tenant_id=tenant_id, statement_id=statement_id), company_ids)
            total = qs.count()
            items = list(qs.select_related("company", "partner", "statement").order_by(F("date").desc(nulls_last=True), "-id")[offset : offset + limit])
            return items, total
        items, total = await asyncio.to_thread(_search)
        return PaginatedResponse(
            items=[BankStatementLineRead.model_validate(line) for line in items],
            total=total,
            limit=limit,
            offset=offset
        )
