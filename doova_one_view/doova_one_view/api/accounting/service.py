"""
Accounting API service.
"""

import asyncio
from datetime import date, timedelta
from typing import Any, Optional

from django.db.models import Avg, Count, Prefetch, Q, Sum

from odoo_app.models.account_move import AccountMove
from odoo_app.models.account_move_line import AccountMoveLine
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


def _product_obj(line: AccountMoveLine) -> Optional[dict[str, Any]]:
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


def _move_to_item(move: AccountMove) -> dict[str, Any]:
    partner = _partner_obj(move)
    company = _company_obj(move)
    partner_name = partner["name"] if partner else ""
    company_name = company["name"] if company else ""

    return {
        "id": move.id,
        "odoo_id": move.odoo_id,
        "name": move.odoo_name or "",
        "odoo_name": move.odoo_name,
        "ref": move.ref or "",
        "date": _iso(move.date),
        "invoice_date": _iso(move.invoice_date),
        "invoice_date_due": _iso(move.invoice_date_due),
        "synced_at": _iso(move.synced_at),
        "move_type": move.move_type,
        "state": move.state,
        "payment_state": move.payment_state or "",
        "amount_untaxed": _to_float(move.amount_untaxed),
        "amount_tax": _to_float(move.amount_tax),
        "amount_total": _to_float(move.amount_total),
        "amount_residual": _to_float(move.amount_residual),
        "currency": move.currency_code,
        "currency_code": move.currency_code,
        "partner": partner,
        "partner_id": getattr(move, "partner_id", None),
        "partner_name": partner_name,
        "company": company,
        "company_id": getattr(move, "company_id", None),
        "company_name": company_name,
        "invoice_origin": move.invoice_origin,
        "journal": None,
        "journal_id": None,
        "journal_name": "",
        "user": None,
        "user_id": None,
        "user_name": "",
    }


def _line_to_item(line: AccountMoveLine) -> dict[str, Any]:
    product = _product_obj(line)
    partner = _partner_obj(line)
    company = _company_obj(line)
    price_subtotal = _to_float(line.price_subtotal)

    return {
        "id": line.id,
        "odoo_id": line.odoo_id,
        "account_id": None,
        "account_name": line.account_name or "",
        "account_code": line.account_code or "",
        "account_type": line.account_type,
        "name": line.name or "",
        "quantity": _to_float(line.quantity),
        "price_unit": _to_float(line.price_unit),
        "price_subtotal": price_subtotal,
        "price_total": price_subtotal,
        "debit": _to_float(line.debit),
        "credit": _to_float(line.credit),
        "balance": _to_float(line.balance),
        "amount_currency": _to_float(line.amount_currency),
        "currency": line.currency_code,
        "currency_code": line.currency_code,
        "product": product,
        "product_id": getattr(line, "product_id", None),
        "product_name": product["name"] if product else "",
        "partner": partner,
        "partner_id": getattr(line, "partner_id", None),
        "partner_name": partner["name"] if partner else "",
        "company": company,
        "company_id": getattr(line, "company_id", None),
        "company_name": company["name"] if company else "",
        "synced_at": _iso(line.synced_at),
    }


def _empty_aging() -> list[dict[str, Any]]:
    return [
        {"bucket": "0-30", "amount": 0.0, "count": 0},
        {"bucket": "31-60", "amount": 0.0, "count": 0},
        {"bucket": "61-90", "amount": 0.0, "count": 0},
        {"bucket": "90+", "amount": 0.0, "count": 0},
    ]


class AccountingService:
    """Service for accounting operations."""

    @staticmethod
    def _base_qs(tenant_id: str, company_ids: Optional[list[int]] = None):
        qs = AccountMove.objects.filter(tenant_id=tenant_id)
        if company_ids:
            qs = qs.filter(company_id__in=company_ids)
        return qs

    @staticmethod
    def _date_qs(qs, start_date: Optional[str], end_date: Optional[str]):
        if start_date:
            qs = qs.filter(date__gte=start_date)
        if end_date:
            qs = qs.filter(date__lte=end_date)
        return qs

    @staticmethod
    async def get_moves(
        tenant_id: str,
        limit: int = 50,
        offset: int = 0,
        partner_id: Optional[int] = None,
        company_ids: Optional[list[int]] = None,
        move_type: Optional[str] = None,
    ) -> dict[str, Any]:
        def _list():
            qs = AccountingService._base_qs(tenant_id, company_ids)
            if partner_id is not None:
                qs = qs.filter(partner_id=partner_id)
            if move_type:
                qs = qs.filter(move_type=move_type)
            total = qs.count()
            moves = list(
                qs.select_related("partner", "company")
                .order_by("-date", "-id")[offset : offset + limit]
            )
            return moves, total

        moves, total = await asyncio.to_thread(_list)
        return {
            "items": [_move_to_item(m) for m in moves],
            "total": total,
            "limit": limit,
            "offset": offset,
            "applied_filters": {
                "tenant_id": tenant_id,
                "partner_id": partner_id,
                "company_ids": company_ids,
                "move_type": move_type,
            },
        }

    @staticmethod
    async def get_move(
        tenant_id: str,
        move_id: int,
        company_ids: Optional[list[int]] = None,
    ) -> dict[str, Any]:
        def _get():
            qs = AccountingService._base_qs(tenant_id, company_ids)
            try:
                return (
                    qs.select_related("partner", "company")
                    .prefetch_related(
                        Prefetch(
                            "lines",
                            queryset=AccountMoveLine.objects.select_related(
                                "product", "partner", "company"
                            ),
                        )
                    )
                    .get(id=move_id)
                )
            except AccountMove.DoesNotExist:
                raise NotFoundError("AccountMove", str(move_id))

        move = await asyncio.to_thread(_get)
        item = _move_to_item(move)
        item["lines"] = [_line_to_item(line) for line in move.lines.all()]
        return item

    @staticmethod
    async def get_summary(
        tenant_id: str,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        company_ids: Optional[list[int]] = None,
    ) -> dict[str, Any]:
        def _summary():
            qs = AccountingService._date_qs(
                AccountingService._base_qs(tenant_id, company_ids), start_date, end_date
            )
            invoices = qs.filter(move_type="out_invoice", state="posted").aggregate(
                total=Sum("amount_total"),
                residual=Sum("amount_residual"),
            )
            bills = qs.filter(move_type="in_invoice", state="posted").aggregate(
                total=Sum("amount_total"),
                residual=Sum("amount_residual"),
            )
            total_invoiced = _to_float(invoices["total"])
            total_bills = _to_float(bills["total"])
            return {
                "total_invoiced": total_invoiced,
                "total_bills": total_bills,
                "total_receivable": _to_float(invoices["residual"]),
                "total_payable": _to_float(bills["residual"]),
                "net_profit_estimate": total_invoiced - total_bills,
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
            qs = AccountingService._date_qs(
                AccountingService._base_qs(tenant_id, company_ids), start_date, end_date
            )
            revenue_qs = qs.filter(move_type="out_invoice", state="posted")
            expense_qs = qs.filter(move_type="in_invoice", state="posted")

            total_revenue = _to_float(revenue_qs.aggregate(total=Sum("amount_total"))["total"])
            total_expenses = _to_float(expense_qs.aggregate(total=Sum("amount_total"))["total"])
            receivable_balance = _to_float(
                qs.filter(
                    move_type="out_invoice",
                    payment_state__in=["not_paid", "partial"],
                    amount_residual__gt=0,
                ).aggregate(total=Sum("amount_residual"))["total"]
            )
            payable_balance = _to_float(
                qs.filter(
                    move_type="in_invoice",
                    payment_state__in=["not_paid", "partial"],
                    amount_residual__gt=0,
                ).aggregate(total=Sum("amount_residual"))["total"]
            )

            today = date.today()
            overdue_filter = Q(invoice_date_due__lt=today) & ~Q(payment_state__in=["paid", "reversed"])
            overdue_receivable = _to_float(
                qs.filter(
                    overdue_filter,
                    move_type="out_invoice",
                    amount_residual__gt=0,
                ).aggregate(total=Sum("amount_residual"))["total"]
            )
            overdue_payable = _to_float(
                qs.filter(
                    overdue_filter,
                    move_type="in_invoice",
                    amount_residual__gt=0,
                ).aggregate(total=Sum("amount_residual"))["total"]
            )

            top_revenue_customers = [
                {
                    "id": row["partner_id"],
                    "name": row["partner__name"] or "",
                    "value": _to_float(row["value"]),
                }
                for row in revenue_qs.filter(partner_id__isnull=False)
                .values("partner_id", "partner__name")
                .annotate(value=Sum("amount_total"))
                .order_by("-value")[:5]
            ]
            top_expense_vendors = [
                {
                    "id": row["partner_id"],
                    "name": row["partner__name"] or "",
                    "value": _to_float(row["value"]),
                }
                for row in expense_qs.filter(partner_id__isnull=False)
                .values("partner_id", "partner__name")
                .annotate(value=Sum("amount_total"))
                .order_by("-value")[:5]
            ]

            revenue_trend = [
                {"date": _iso(row["date"]), "value": _to_float(row["value"])}
                for row in revenue_qs.values("date")
                .annotate(value=Sum("amount_total"))
                .order_by("date")
            ]
            expense_trend = [
                {"date": _iso(row["date"]), "value": _to_float(row["value"])}
                for row in expense_qs.values("date")
                .annotate(value=Sum("amount_total"))
                .order_by("date")
            ]
            cash_flow_map: dict[str, float] = {}
            for entry in revenue_trend:
                if entry["date"]:
                    cash_flow_map[entry["date"]] = cash_flow_map.get(entry["date"], 0.0) + entry["value"]
            for entry in expense_trend:
                if entry["date"]:
                    cash_flow_map[entry["date"]] = cash_flow_map.get(entry["date"], 0.0) - entry["value"]
            cash_flow_trend = [
                {"date": day, "value": cash_flow_map[day]} for day in sorted(cash_flow_map)
            ]

            state_distribution = {
                row["state"] or "unknown": row["count"]
                for row in qs.values("state").annotate(count=Count("id"))
            }
            payment_state_distribution = {
                row["payment_state"] or "unknown": row["count"]
                for row in qs.values("payment_state").annotate(count=Count("id"))
            }
            move_type_distribution = {
                row["move_type"] or "unknown": row["count"]
                for row in qs.values("move_type").annotate(count=Count("id"))
            }

            receivables_aging = AccountingService._aging(qs, "out_invoice")
            payables_aging = AccountingService._aging(qs, "in_invoice")

            net_profit = total_revenue - total_expenses
            net_profit_margin_pct = (net_profit / total_revenue * 100) if total_revenue else 0.0
            applied = {
                "tenant_id": tenant_id,
                "start_date": start_date,
                "end_date": end_date,
                "company_ids": company_ids,
            }
            return {
                "total_revenue": _metric(total_revenue),
                "total_expenses": _metric(total_expenses),
                "net_profit": _metric(net_profit),
                "gross_profit": _metric(net_profit),
                "ebit": _metric(net_profit),
                "net_profit_margin_pct": net_profit_margin_pct,
                "receivable_balance": receivable_balance,
                "overdue_receivable": overdue_receivable,
                "payable_balance": payable_balance,
                "overdue_payable": overdue_payable,
                "top_revenue_customers": top_revenue_customers,
                "top_expense_vendors": top_expense_vendors,
                "revenue_trend": revenue_trend,
                "expense_trend": expense_trend,
                "cash_flow_trend": cash_flow_trend,
                "state_distribution": state_distribution,
                "payment_state_distribution": payment_state_distribution,
                "payment_status_distribution": payment_state_distribution,
                "move_type_distribution": move_type_distribution,
                "receivables_aging": receivables_aging,
                "payables_aging": payables_aging,
                "ar_aging": receivables_aging,
                "ap_aging": payables_aging,
                "applied_filters": applied,
            }

        return await asyncio.to_thread(_dashboard)

    @staticmethod
    def _aging(qs, move_type: str) -> list[dict[str, Any]]:
        today = date.today()
        base = qs.filter(
            move_type=move_type,
            invoice_date_due__isnull=False,
            amount_residual__gt=0,
        ).exclude(payment_state__in=["paid", "reversed"])
        buckets = [
            ("0-30", today - timedelta(days=30), today),
            ("31-60", today - timedelta(days=60), today - timedelta(days=31)),
            ("61-90", today - timedelta(days=90), today - timedelta(days=61)),
            ("90+", None, today - timedelta(days=91)),
        ]
        out = []
        for label, start, end in buckets:
            bucket_qs = base.filter(invoice_date_due__lte=end)
            if start is not None:
                bucket_qs = bucket_qs.filter(invoice_date_due__gte=start)
            agg = bucket_qs.aggregate(amount=Sum("amount_residual"), count=Count("id"))
            out.append({
                "bucket": label,
                "amount": _to_float(agg["amount"]),
                "count": agg["count"] or 0,
            })
        return out or _empty_aging()

    @staticmethod
    async def get_filters(tenant_id: str) -> dict[str, Any]:
        def _filters():
            qs = AccountMove.objects.filter(tenant_id=tenant_id)
            move_types = [v for v in qs.values_list("move_type", flat=True).distinct() if v]
            states = [v for v in qs.values_list("state", flat=True).distinct() if v]
            payment_states = [v for v in qs.values_list("payment_state", flat=True).distinct() if v]
            currencies = [v for v in qs.values_list("currency_code", flat=True).distinct() if v]
            partners = [
                {"id": row["partner_id"], "name": row["partner__name"] or ""}
                for row in qs.filter(partner_id__isnull=False)
                .values("partner_id", "partner__name")
                .distinct()
                .order_by("partner__name")
            ]
            return {
                "move_types": move_types,
                "move_type": move_types,
                "state": states,
                "states": states,
                "payment_states": payment_states,
                "payment_state": payment_states,
                "currencies": currencies,
                "partners": partners,
                "partner_names": [p["name"] for p in partners if p["name"]],
            }

        return await asyncio.to_thread(_filters)

    @staticmethod
    async def search_moves(
        tenant_id: str,
        filters: list[Any],
        limit: int,
        offset: int,
        company_ids: Optional[list[int]] = None,
    ) -> dict[str, Any]:
        def _search():
            qs = AccountingService._base_qs(tenant_id, company_ids)
            field_map = {
                "odoo_id": "odoo_id",
                "odoo_name": "odoo_name",
                "name": "odoo_name",
                "ref": "ref",
                "partner_name": "partner__name",
                "company_name": "company__name",
                "date": "date",
                "invoice_date": "invoice_date",
                "invoice_date_due": "invoice_date_due",
                "move_type": "move_type",
                "state": "state",
                "payment_state": "payment_state",
                "amount_untaxed": "amount_untaxed",
                "amount_tax": "amount_tax",
                "amount_total": "amount_total",
                "amount_residual": "amount_residual",
                "currency_code": "currency_code",
                "synced_at": "odoo_write_date",
            }
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

            total = qs.count()
            moves = list(
                qs.select_related("partner", "company")
                .order_by("-date", "-id")[offset : offset + limit]
            )
            return moves, total

        moves, total = await asyncio.to_thread(_search)
        return {
            "items": [_move_to_item(m) for m in moves],
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
    async def export_moves_csv(
        tenant_id: str,
        company_ids: Optional[list[int]] = None,
    ) -> str:
        header_cols = [
            "id", "odoo_id", "odoo_name", "ref", "date", "invoice_date",
            "invoice_date_due", "move_type", "state", "payment_state",
            "partner_name", "company_name", "amount_untaxed", "amount_tax",
            "amount_total", "amount_residual", "currency_code", "synced_at",
        ]

        def _export():
            qs = AccountingService._base_qs(tenant_id, company_ids)
            return list(qs.select_related("partner", "company").order_by("-date", "-id"))

        moves = await asyncio.to_thread(_export)
        lines = [",".join(header_cols)]
        for move in moves:
            item = _move_to_item(move)
            lines.append(",".join(_csv_escape(item.get(col, "")) for col in header_cols))
        return "\n".join(lines)
