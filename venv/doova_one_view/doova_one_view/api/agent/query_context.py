# api/agent/query_context.py

import re
from datetime import date, datetime, timedelta
from typing import List, Tuple, Dict, Any, Optional, Union
from .config import AgentConfig

# Financial Period Constants
DEFAULT_COMPANY_IDS = []  # Empty means all companies within the tenant context

def normalize_company_ids(
    company_id: Optional[Union[int, str]] = None,
    companies: Optional[List[Union[int, str]]] = None,
) -> List[int]:
    """
    Standardizes company identifiers into a unique list of Odoo IDs.
    Handles single inputs, lists, and string-to-int conversions gracefully.
    """
    processed_ids: List[int] = []

    if companies:
        for val in companies:
            try:
                processed_ids.append(int(val))
            except (ValueError, TypeError):
                continue

    if company_id is not None:
        try:
            processed_ids.append(int(company_id))
        except (ValueError, TypeError):
            pass

    # Deduplicate while preserving order (if any)
    unique_ids = list(dict.fromkeys(processed_ids))
    return unique_ids if unique_ids else DEFAULT_COMPANY_IDS

def resolve_company_ids_to_local(tenant_id: str, odoo_ids: List[int]) -> List[int]:
    """
    Maps external Odoo IDs to internal Primary Keys for a specific tenant.
    Critical for maintaining isolation between tenant data environments.
    """
    if not odoo_ids:
        return []
    
    from odoo_app.models.company import Company
    return list(
        Company.objects.filter(tenant_id=tenant_id, odoo_id__in=odoo_ids)
        .values_list('id', flat=True)
    )

def build_company_filter_sql(
    tenant_id: str, 
    company_ids: Optional[Union[int, List[int]]] = None, 
    column_name: str = "company_id", 
    prefix: str = "comp"
) -> Tuple[str, Dict[str, Any]]:
    """
    Generates a secure SQL 'IN' clause for company filtering.
    Returns the SQL snippet and the parameter dictionary to prevent injection.
    """
    ids = normalize_company_ids(
        company_id=company_ids if isinstance(company_ids, (int, str)) else None,
        companies=company_ids if isinstance(company_ids, list) else None
    )
    
    if not ids:
        return "", {}
        
    placeholders = [f":{prefix}_{i}" for i in range(len(ids))]
    params = {f"{prefix}_{i}": cid for i, cid in enumerate(ids)}
    
    return f" AND {column_name} IN ({', '.join(placeholders)})", params

def extract_date_range(message: str) -> Tuple[Optional[str], Optional[str], Optional[str]]:
    """
    Sophisticated date extraction utility for financial periods.
    Returns (start_date, end_date, human_readable_description).
    """
    text = (message or "").lower()
    today = date.today()

    # 1. Financial Period Shortcuts
    if "today" in text:
        return today.isoformat(), today.isoformat(), "Today"
    if "yesterday" in text:
        yest = today - timedelta(days=1)
        return yest.isoformat(), yest.isoformat(), "Yesterday"
    if "this month" in text:
        start = today.replace(day=1)
        return start.isoformat(), today.isoformat(), "MDT (Month to Date)"
    if "last month" in text:
        last_month_end = today.replace(day=1) - timedelta(days=1)
        last_month_start = last_month_end.replace(day=1)
        return last_month_start.isoformat(), last_month_end.isoformat(), last_month_start.strftime("%B %Y")
    if "this year" in text:
        return today.replace(month=1, day=1).isoformat(), today.isoformat(), f"YTD {today.year}"

    # 2. ISO Date Pattern Matching (YYYY-MM-DD)
    iso_matches = re.findall(r'(\d{4}-\d{2}-\d{2})', text)
    if iso_matches:
        if len(iso_matches) >= 2:
            return iso_matches[0], iso_matches[1], f"From {iso_matches[0]} to {iso_matches[1]}"
        return iso_matches[0], today.isoformat(), f"Since {iso_matches[0]}"

    return None, None, None

def is_strategic_finance_query(message: str) -> bool:
    """
    Enterprise-grade heuristic to identify queries requiring deep financial intelligence.
    """
    text = (message or "").lower()
    
    strategic_indicators = {
        'management': ['revenue', 'variance', 'forecast', 'budget', 'margin', 'kpi'],
        'reporting': ['pnl', 'balance sheet', 'cash flow', 'statement', 'report'],
        'compliance': ['tax', 'vat', 'audit', 'regulation', 'filing'],
        'operations': ['inventory', 'stock', 'turnover', 'churn', 'retention']
    }
    
    # Flatten indicators for check
    all_keywords = [kw for sublist in strategic_indicators.values() for kw in sublist]
    return any(kw in text for kw in all_keywords)
