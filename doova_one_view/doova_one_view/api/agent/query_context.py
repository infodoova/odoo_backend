"""
Query context utilities for the AI agent.
Handles multi-tenant company filtering and natural language date range parsing.
"""

from __future__ import annotations

import re
from datetime import date, timedelta
from typing import Any


# Default companies to include if none are specified
DEFAULT_COMPANY_IDS = [2, 3, 4, 5, 11]


def normalize_company_ids(
    company_id: int | None = None,
    companies: list[int] | list[str] | None = None,
) -> list[int]:
    """Ensure we have a unique list of integer company IDs (Odoo IDs)."""
    ids: list[int] = []

    if companies:
        for value in companies:
            try:
                ids.append(int(value))
            except Exception:
                pass

    if company_id is not None:
        try:
            ids.append(int(company_id))
        except Exception:
            pass

    if not ids:
        ids = DEFAULT_COMPANY_IDS[:]

    return list(dict.fromkeys(ids))


def resolve_company_ids_to_local(tenant_id: str, odoo_ids: list[int]) -> list[int]:
    """
    Resolve a list of Odoo company IDs to their local primary keys for the given tenant.
    This is necessary because fact tables use local PKs as FKs.
    """
    from odoo_app.models.company import Company
    return list(Company.objects.filter(tenant_id=tenant_id, odoo_id__in=odoo_ids).values_list('id', flat=True))


def build_company_filter_sql(
    tenant_id: str,
    company_ids: list[int] | None,
    column_name: str = "company_id",
    prefix: str = "company",
) -> tuple[str, dict[str, Any]]:
    """Generate SQL IN clause and parameters for company filtering, resolving Odoo IDs to local PKs."""
    odoo_ids = normalize_company_ids(companies=company_ids)
    local_ids = resolve_company_ids_to_local(tenant_id, odoo_ids)

    if not local_ids:
        # Return a filter that matches nothing to ensure isolation
        return f" AND {column_name} = -1", {}

    placeholders = []
    params: dict[str, Any] = {}

    for index, cid in enumerate(local_ids):
        key = f"{prefix}_{index}"
        placeholders.append(f":{key}")
        params[key] = cid

    return f" AND {column_name} IN ({', '.join(placeholders)})", params


def extract_date_range(message: str) -> tuple[str | None, str | None, str | None]:
    """Parse natural language date phrases into start/end ISO dates."""
    text = (message or "").lower().strip()

    month_map = {
        "january": 1, "jan": 1, "february": 2, "feb": 2, "march": 3, "mar": 3,
        "april": 4, "apr": 4, "may": 5, "june": 6, "jun": 6, "july": 7, "jul": 7,
        "august": 8, "aug": 8, "september": 9, "sep": 9, "sept": 9,
        "october": 10, "oct": 10, "november": 11, "nov": 11, "december": 12, "dec": 12,
    }

    if "today" in text:
        today = date.today()
        return today.isoformat(), today.isoformat(), today.strftime("%B %d, %Y")

    if "yesterday" in text:
        d = date.today() - timedelta(days=1)
        return d.isoformat(), d.isoformat(), d.strftime("%B %d, %Y")

    if "last month" in text:
        today = date.today()
        first_this_month = today.replace(day=1)
        last_prev_month = first_this_month - timedelta(days=1)
        start = last_prev_month.replace(day=1)
        end = last_prev_month
        return start.isoformat(), end.isoformat(), start.strftime("%B %Y")

    # Match month year (e.g., "January 2024")
    match = re.search(
        r"\b(january|jan|february|feb|march|mar|april|apr|may|june|jun|july|jul|august|aug|september|sep|sept|october|oct|november|nov|december|dec)\s+(\d{4})\b",
        text,
    )
    if match:
        month_name = match.group(1)
        year = int(match.group(2))
        month = month_map[month_name]

        start = date(year, month, 1)
        if month == 12:
            end = date(year, 12, 31)
        else:
            end = date(year, month + 1, 1) - timedelta(days=1)

        return start.isoformat(), end.isoformat(), start.strftime("%B %Y")

    # dd-mm-yyyy or dd/mm/yyyy
    match = re.search(r"\b(\d{1,2})[-/](\d{1,2})[-/](\d{4})\b", text)
    if match:
        day = int(match.group(1))
        month = int(match.group(2))
        year = int(match.group(3))

        try:
            d = date(year, month, day)
            return d.isoformat(), d.isoformat(), d.strftime("%B %d, %Y")
        except ValueError:
            return None, None, None

    return None, None, None


def is_business_data_question(message: str) -> bool:
    """Heuristic check to see if a question relates to business metrics."""
    text = (message or "").lower()

    keywords = [
        "revenue", "sales", "orders", "customers", "products",
        "inventory", "stock", "low stock", "cash flow",
        "receivables", "payables", "profit", "margin",
        "forecast", "trend", "graph", "chart", "report",
        "business health", "database",
    ]

    return any(keyword in text for keyword in keywords)
