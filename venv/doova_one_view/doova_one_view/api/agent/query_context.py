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

def normalize_company_ids(company_ids: Any = None) -> List[int]:
    """
    Standardizes company identifiers into a unique list of integer IDs.
    Accepts:
      - list/tuple/set of ints or strings: [36, 37] or ["36", "37"]
      - single int or string: 36 or "36"
      - comma-separated string: "36, 37"
      - JSON array string: "[36, 37]" or "['36', '37']"
    Returns:
      Sorted unique list of int. Discards null, none, all, and empty strings.
    """
    if company_ids is None:
        return []

    processed_ids: List[int] = []
    items = company_ids if isinstance(company_ids, (list, tuple, set)) else [company_ids]

    for item in items:
        if item is None:
            continue
        if isinstance(item, int):
            processed_ids.append(item)
        elif isinstance(item, str):
            s = item.strip()
            if s.lower() in ("none", "null", "all", ""):
                continue
            for m in re.findall(r'-?\d+', s):
                try:
                    processed_ids.append(int(m))
                except (ValueError, TypeError):
                    pass
        elif isinstance(item, (list, tuple, set)):
            for sub in item:
                if sub is None:
                    continue
                if isinstance(sub, int):
                    processed_ids.append(sub)
                elif isinstance(sub, str):
                    s = sub.strip()
                    if s.lower() in ("none", "null", "all", ""):
                        continue
                    for m in re.findall(r'-?\d+', s):
                        try:
                            processed_ids.append(int(m))
                        except (ValueError, TypeError):
                            pass

    return sorted(list(set(processed_ids)))


def normalize_tenant_ids(tenant_ids: Any = None) -> List[str]:
    """
    Standardizes tenant identifiers into a unique list of valid UUID strings.
    Accepts:
      - list/tuple/set of UUID strings
      - single UUID string or slug/name
      - comma-separated string
      - JSON array string: "['uuid1', 'uuid2']"
    Returns:
      Sorted unique list of valid UUID strings. Discards null, none, all, and empty strings.
    """
    if tenant_ids is None:
        return []

    processed_ids: List[str] = []
    items = []
    if isinstance(tenant_ids, (list, tuple, set)):
        items = list(tenant_ids)
    elif isinstance(tenant_ids, str):
        s = tenant_ids.strip()
        if s.lower() in ("none", "null", "all", ""):
            items = []
        else:
            found_uuids = re.findall(r'[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}', s)
            if found_uuids:
                items = found_uuids
            else:
                items = [t.strip().strip("'\"") for t in s.strip("[]").split(",") if t.strip()]
    else:
        items = [tenant_ids]

    for val in items:
        clean = resolve_tenant_id(str(val))
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


def build_scope_filter_sql(
    column_name: str,
    ids: List[Union[int, str]],
    prefix: str = "scope",
) -> Tuple[str, Dict[str, Any]]:
    """
    Core SQL condition generator following the dynamic operator contract:
      - len(ids) == 0 -> ("", {})  (no condition / full scope)
      - len(ids) == 1 -> (" AND {column_name} = :{prefix}_0", {f"{prefix}_0": ids[0]})  (exact equality '=')
      - len(ids) > 1  -> (" AND {column_name} IN (:{prefix}_0, ...)", {...})  (inclusion set 'IN')
    """
    if not ids:
        return "", {}

    if len(ids) == 1:
        param_name = f"{prefix}_0"
        return f" AND {column_name} = :{param_name}", {param_name: ids[0]}

    placeholders = [f":{prefix}_{i}" for i in range(len(ids))]
    params = {f"{prefix}_{i}": val for i, val in enumerate(ids)}
    return f" AND {column_name} IN ({', '.join(placeholders)})", params


def build_company_filter_sql(
    company_ids: Any = None,
    column_name: str = "company_id",
    prefix: str = "comp",
) -> Tuple[str, Dict[str, Any]]:
    """
    Generates dynamic SQL condition for company filtering:
      - 0 companies: ("", {})
      - 1 company:   (" AND {column_name} = :comp_0", {"comp_0": ...})
      - >1 company:  (" AND {column_name} IN (:comp_0, :comp_1)", {"comp_0": ..., "comp_1": ...})
    """
    c_ids = normalize_company_ids(company_ids)
    return build_scope_filter_sql(column_name, c_ids, prefix=prefix)


def build_tenant_filter_sql(
    tenant_ids: Any = None,
    column_name: str = "tenant_id",
    prefix: str = "t",
) -> Tuple[str, Dict[str, Any]]:
    """
    Generates dynamic SQL condition for tenant filtering:
      - 0 tenants: ("", {})
      - 1 tenant:   (" AND {column_name} = :t_tenant_id_0", {"t_tenant_id_0": ...})
      - >1 tenants: (" AND {column_name} IN (:t_tenant_id_0, :t_tenant_id_1)", ...)
    """
    t_ids = normalize_tenant_ids(tenant_ids)
    param_prefix = f"{prefix}_tenant_id" if not prefix.endswith("tenant_id") else prefix
    return build_scope_filter_sql(column_name, t_ids, prefix=param_prefix)


def apply_scope_filter_orm(
    queryset,
    field_name: str,
    ids: List[Union[int, str]],
):
    """
    Applies ORM filtering dynamically based on list cardinality:
      - len(ids) == 0 -> queryset (unfiltered)
      - len(ids) == 1 -> queryset.filter(**{field_name: ids[0]})  (emits SQL '=')
      - len(ids) > 1  -> queryset.filter(**{f"{field_name}__in": ids})  (emits SQL 'IN')
    """
    if not ids:
        return queryset
    if len(ids) == 1:
        return queryset.filter(**{field_name: ids[0]})
    return queryset.filter(**{f"{field_name}__in": ids})


def build_scope_q(
    field_name: str,
    ids: List[Union[int, str]],
) -> models.Q:
    """
    Builds a Django Q object dynamically:
      - len(ids) == 0 -> Q() (empty)
      - len(ids) == 1 -> Q(**{field_name: ids[0]})
      - len(ids) > 1  -> Q(**{f"{field_name}__in": ids})
    """
    if not ids:
        return models.Q()
    if len(ids) == 1:
        return models.Q(**{field_name: ids[0]})
    return models.Q(**{f"{field_name}__in": ids})

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
