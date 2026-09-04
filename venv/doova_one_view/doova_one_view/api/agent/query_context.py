# api/agent/query_context.py

import re
import uuid
from datetime import date, datetime, timedelta
from typing import List, Tuple, Dict, Any, Optional, Union
from django.db import models
from .config import AgentConfig

# Financial Period Constants
DEFAULT_COMPANY_IDS = []  # Empty means all companies within the tenant context


def resolve_tenant_id(tenant_id: Optional[str]) -> Optional[str]:
    """
    Ensures tenant_id is a valid UUID string compatible with PostgreSQL UUID columns.
    If tenant_id is 'all', 'all_tenants', None, or empty, returns None (indicating cross-tenant aggregation).
    If tenant_id is 'default', resolves to the first Tenant's UUID in the database.
    If tenant_id is already a valid UUID string, returns it as-is.
    If tenant_id is a slug/name, looks up the corresponding Tenant in DB.
    """
    clean_id = str(tenant_id or "").strip()
    if not clean_id or clean_id.lower() in ("all", "all_tenants", "none", "null", ""):
        return None

    if clean_id.lower() == "default":
        try:
            from odoo_app.models.tenant import Tenant
            tenant = Tenant.objects.first()
            if tenant:
                return str(tenant.id)
        except Exception:
            pass
        return None

    try:
        val = uuid.UUID(clean_id)
        return str(val)
    except ValueError:
        pass

    # Look up by name or odoo_database slug in Django Tenant table
    try:
        from odoo_app.models.tenant import Tenant
        tenant = Tenant.objects.filter(
            models.Q(name__iexact=clean_id) | models.Q(odoo_database__iexact=clean_id)
        ).first()
        if tenant:
            return str(tenant.id)
    except Exception:
        pass

    return None

def normalize_company_ids(
    company_id: Optional[Union[int, str]] = None,
    companies: Optional[Union[List[Union[int, str]], str]] = None,
) -> List[int]:
    """
    Standardizes company identifiers into a unique list of Odoo IDs.
    Handles single inputs, lists, comma-separated strings, and string-to-int conversions gracefully.
    Also silently discards the string "None" / "null" / "" that an LLM may emit.
    """
    processed_ids: List[int] = []

    if companies:
        if isinstance(companies, str):
            if companies.lower() in ("none", "null", "", "all"):
                companies_list = []
            else:
                companies_list = [c.strip() for c in companies.split(",") if c.strip()]
        elif isinstance(companies, (list, tuple, set)):
            companies_list = list(companies)
        else:
            companies_list = [companies]

        for val in companies_list:
            if isinstance(val, str) and val.lower() in ("none", "null", "", "all"):
                continue
            try:
                processed_ids.append(int(val))
            except (ValueError, TypeError):
                continue

    if company_id is not None:
        if not (isinstance(company_id, str) and company_id.lower() in ("none", "null", "", "all")):
            try:
                processed_ids.append(int(company_id))
            except (ValueError, TypeError):
                pass

    return sorted(list(set(processed_ids)))


def normalize_tenant_ids(
    tenant_id: Optional[str] = None,
    tenant_ids: Optional[Union[List[str], str]] = None,
) -> List[str]:
    """
    Standardizes tenant identifiers into a unique list of valid UUID strings.
    Handles single inputs, lists, and comma-separated strings. Returns empty list if no valid tenants are provided
    (meaning all tenants or cross-tenant query).
    """
    processed_ids: List[str] = []

    if tenant_ids:
        if isinstance(tenant_ids, str):
            if tenant_ids.lower() in ("none", "null", "", "all"):
                tenant_list = []
            else:
                tenant_list = [t.strip() for t in tenant_ids.split(",") if t.strip()]
        elif isinstance(tenant_ids, (list, tuple, set)):
            tenant_list = list(tenant_ids)
        else:
            tenant_list = [tenant_ids]

        for val in tenant_list:
            clean = resolve_tenant_id(str(val))
            if clean:
                processed_ids.append(clean)

    if tenant_id is not None:
        clean = resolve_tenant_id(str(tenant_id))
        if clean:
            processed_ids.append(clean)

    return sorted(list(set(processed_ids)))

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

def build_tenant_filter_sql(
    tenant_id: Optional[str] = None, 
    tenant_ids: Optional[List[str]] = None,
    column_name: str = "tenant_id", 
    prefix: str = "t"
) -> Tuple[str, Dict[str, Any]]:
    """
    Generates a secure SQL filter for tenant_id using an IN clause if multiple are provided.
    If no tenants are provided, returns no filter (allowing cross-tenant queries).
    """
    ids = normalize_tenant_ids(tenant_id=tenant_id, tenant_ids=tenant_ids)
    
    if not ids:
        return "", {}
        
    placeholders = [f":{prefix}_tenant_id_{i}" for i in range(len(ids))]
    params = {f"{prefix}_tenant_id_{i}": tid for i, tid in enumerate(ids)}
    
    return f" AND {column_name} IN ({', '.join(placeholders)})", params

def extract_date_range(message: str) -> Tuple[Optional[str], Optional[str], Optional[str]]:
    """
    Sophisticated date extraction utility for financial periods.
    Returns (start_date, end_date, human_readable_description).
    Delegates to the unified date_engine.
    """
    from .date_engine import resolve_period_dates
    return resolve_period_dates(text=message, default_to_ytd=False)

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
