from doova_one_view.api.agent.query_context import build_tenant_filter_sql
from typing import Optional
# api/agent/tools_refactored/inventory.py

from .common import run_query, normalize_company_ids, build_company_filter_sql, calculate_ratio

def get_inventory_alerts_tool(
    tenant_id: str,
    company_id: int | None = None,
    company_ids: list[int] | None = None,
    low_stock_threshold: float = 10,
    expiring_days: int = 90, tenant_ids: Optional[list[str]] = None
) -> dict:

    t_sql_l, t_params_l = build_tenant_filter_sql(tenant_id, tenant_ids, column_name="l.tenant_id", prefix="t_l")
    t_sql_q, t_params_q = build_tenant_filter_sql(tenant_id, tenant_ids, column_name="q.tenant_id", prefix="t_q")
    selected_company_ids = normalize_company_ids(company_id=company_id, companies=company_ids)
    params = {"tenant_id": tenant_id, "threshold": low_stock_threshold, "expiring_days": expiring_days}
    params.update(t_params_l)
    params.update(t_params_q)
    f_sql, f_params = build_company_filter_sql(tenant_id, selected_company_ids)
    params.update(f_params)

    low_stock_rows = run_query(f"""
        SELECT p.name AS product_name, COALESCE(SUM(q.quantity), 0) AS available, q.location_name
        FROM fact_stock_quants q
        JOIN dim_products p ON q.product_id = p.id AND q.tenant_id = p.tenant_id
        WHERE 1=1 {t_sql_q} AND q.product_id IS NOT NULL {f_sql}
        GROUP BY p.name, q.location_name
        HAVING COALESCE(SUM(q.quantity), 0) > 0 AND COALESCE(SUM(q.quantity), 0) <= :threshold
        ORDER BY available ASC LIMIT 25
    """, params)

    expiring_rows = run_query(f"""
        SELECT l.name, p.name AS product_name, l.expiration_date
        FROM dim_lots l
        JOIN dim_products p ON l.product_id = p.id AND l.tenant_id = p.tenant_id
        WHERE 1=1 {t_sql_l} AND l.expiration_date IS NOT NULL
          AND l.expiration_date >= CURRENT_DATE AND l.expiration_date < (CURRENT_DATE + (:expiring_days * INTERVAL '1 day'))
          {f_sql}
        ORDER BY l.expiration_date ASC LIMIT 25
    """, params)

    return {
        "tool_name": "get_inventory_alerts_tool",
        "low_stock_items": [{"product": r.get('product_name'), "available": float(r.get('available')), "location": r.get('location_name')} for r in low_stock_rows],
        "expiring_soon": [{"lot": r.get('name'), "product": r.get('product_name'), "expiration_date": str(r.get('expiration_date'))} for r in expiring_rows]
    }

def get_inventory_efficiency_tool(
    tenant_id: str,
    company_id: int | None = None,
    company_ids: list[int] | None = None, tenant_ids: Optional[list[str]] = None
) -> dict:

    t_sql_m, t_params_m = build_tenant_filter_sql(tenant_id, tenant_ids, column_name="m.tenant_id", prefix="t_m")
    t_sql_q, t_params_q = build_tenant_filter_sql(tenant_id, tenant_ids, column_name="q.tenant_id", prefix="t_q")
    selected_company_ids = normalize_company_ids(company_id=company_id, companies=company_ids)
    params = {"tenant_id": tenant_id}
    params.update(t_params_m)
    params.update(t_params_q)
    q_sql, q_params = build_company_filter_sql(tenant_id, selected_company_ids, column_name="q.company_id", prefix="q_company")
    m_sql, m_params = build_company_filter_sql(tenant_id, selected_company_ids, column_name="m.company_id", prefix="m_company")
    params.update(q_params)
    params.update(m_params)

    inv_rows = run_query(f"""
        SELECT COALESCE(SUM(q.quantity * COALESCE(p.standard_price, 0)), 0) AS total_value, COUNT(DISTINCT q.product_id) AS sku_count
        FROM fact_stock_quants q
        LEFT JOIN dim_products p ON p.tenant_id = q.tenant_id AND p.id = q.product_id
        WHERE 1=1 {t_sql_q} AND q.quantity > 0 {q_sql}
    """, params)

    move_rows = run_query(f"""
        SELECT COALESCE(SUM(m.quantity_done * COALESCE(p.standard_price, 0)), 0) AS move_value
        FROM fact_stock_moves m
        LEFT JOIN dim_products p ON p.tenant_id = m.tenant_id AND p.id = m.product_id
        WHERE 1=1 {t_sql_m} AND m.state = 'done' AND m.date >= CURRENT_DATE - INTERVAL '12 months' {m_sql}
    """, params)

    inv = inv_rows[0]; move = move_rows[0]
    total_val = float(inv.get('total_value')); move_val = float(move.get('move_value'))
    turnover = calculate_ratio(move_val, total_val)

    return {
        "tool_name": "get_inventory_efficiency_tool",
        "total_inventory_value": total_val,
        "turnover_ratio": turnover,
        "days_inventory_on_hand": 365 / turnover if turnover > 0 else None,
        "efficiency_rating": "High" if turnover > 6 else "Medium" if turnover >= 3 else "Low"
    }


def get_inventory_stock_table_tool(tenant_id: str, table_type: str, company_id: int | None = None, limit: int = 25, offset: int = 0, company_ids: Optional[list[int]] = None, tenant_ids: Optional[list[str]] = None) -> dict:
    from asgiref.sync import async_to_sync
    from doova_one_view.api.inventory.service import InventoryService
    from doova_one_view.api.agent.query_context import resolve_tenant_id
    from .common import normalize_company_ids
    company_ids = normalize_company_ids(company_id=company_id, companies=None)
    clean_tenant_id = resolve_tenant_id(tenant_id)
    # Coerce limit/offset to int — the LLM agent may pass them as strings
    try:
        limit = int(limit) if limit is not None else 25
    except (ValueError, TypeError):
        limit = 25
    try:
        offset = int(offset) if offset is not None else 0
    except (ValueError, TypeError):
        offset = 0
    res = async_to_sync(InventoryService.get_stock_table)(
        tenant_id=clean_tenant_id,
        table_type=table_type,
        company_ids=company_ids,
        limit=limit,
        offset=offset
    )
    return {"tool_name": "get_inventory_stock_table_tool", **res}

def get_inventory_dashboard_alerts_tool(tenant_id: str, company_id: int | None = None, company_ids: Optional[list[int]] = None, tenant_ids: Optional[list[str]] = None) -> dict:
    from doova_one_view.api.inventory.service import InventoryService
    from doova_one_view.api.agent.query_context import resolve_tenant_id
    from .common import normalize_company_ids
    company_ids = normalize_company_ids(company_id=company_id, companies=None)
    clean_tenant_id = resolve_tenant_id(tenant_id)
    res = InventoryService.get_alerts_sync(
        tenant_id=clean_tenant_id,
        company_ids=company_ids
    )
    return {"tool_name": "get_inventory_dashboard_alerts_tool", **res}

def get_inventory_valuation_tool(tenant_id: str, company_id: int | None = None, company_ids: Optional[list[int]] = None, tenant_ids: Optional[list[str]] = None) -> dict:
    from doova_one_view.api.inventory.service import InventoryService
    from doova_one_view.api.agent.query_context import resolve_tenant_id
    from .common import normalize_company_ids
    company_ids = normalize_company_ids(company_id=company_id, companies=None)
    clean_tenant_id = resolve_tenant_id(tenant_id)
    res = InventoryService.get_inventory_summary_sync(
        tenant_id=clean_tenant_id,
        company_ids=company_ids
    )
    return {"tool_name": "get_inventory_valuation_tool", **res}


