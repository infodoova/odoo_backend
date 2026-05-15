# api/agent/tools_refactored/inventory.py

from .common import run_query, normalize_company_ids, build_company_filter_sql, calculate_ratio

def get_inventory_alerts_tool(
    tenant_id: str,
    company_id: int | None = None,
    company_ids: list[int] | None = None,
    low_stock_threshold: float = 10,
    expiring_days: int = 90,
) -> dict:
    selected_company_ids = normalize_company_ids(company_id=company_id, companies=company_ids)
    params = {"tenant_id": tenant_id, "threshold": low_stock_threshold, "expiring_days": expiring_days}
    f_sql, f_params = build_company_filter_sql(tenant_id, selected_company_ids)
    params.update(f_params)

    low_stock_rows = run_query(f"""
        SELECT product_name, COALESCE(SUM(available_quantity), 0) AS available, location_name
        FROM fact_inventory_quants
        WHERE tenant_id = :tenant_id AND product_id IS NOT NULL {f_sql}
        GROUP BY product_name, location_name
        HAVING COALESCE(SUM(available_quantity), 0) > 0 AND COALESCE(SUM(available_quantity), 0) <= :threshold
        ORDER BY available ASC LIMIT 25
    """, params)

    expiring_rows = run_query(f"""
        SELECT name, product_name, expiration_date
        FROM dim_lots
        WHERE tenant_id = :tenant_id AND expiration_date IS NOT NULL
          AND expiration_date >= CURRENT_DATE AND expiration_date < (CURRENT_DATE + (:expiring_days * INTERVAL '1 day'))
          {f_sql}
        ORDER BY expiration_date ASC LIMIT 25
    """, params)

    return {
        "tool_name": "get_inventory_alerts_tool",
        "low_stock_items": [{"product": r["product_name"], "available": float(r["available"]), "location": r["location_name"]} for r in low_stock_rows],
        "expiring_soon": [{"lot": r["name"], "product": r["product_name"], "expiration_date": str(r["expiration_date"])} for r in expiring_rows]
    }

def get_inventory_efficiency_tool(
    tenant_id: str,
    company_id: int | None = None,
    company_ids: list[int] | None = None,
) -> dict:
    selected_company_ids = normalize_company_ids(company_id=company_id, companies=company_ids)
    params = {"tenant_id": tenant_id}
    q_sql, q_params = build_company_filter_sql(tenant_id, selected_company_ids, column_name="q.company_id", prefix="q_company")
    m_sql, m_params = build_company_filter_sql(tenant_id, selected_company_ids, column_name="m.company_id", prefix="m_company")
    params.update(q_params)
    params.update(m_params)

    inv_rows = run_query(f"""
        SELECT COALESCE(SUM(q.available_quantity * COALESCE(p.standard_price, 0)), 0) AS total_value, COUNT(DISTINCT q.product_id) AS sku_count
        FROM fact_inventory_quants q
        LEFT JOIN dim_products p ON p.tenant_id = q.tenant_id AND p.odoo_id = q.product_id
        WHERE q.tenant_id = :tenant_id AND q.available_quantity > 0 {q_sql}
    """, params)

    move_rows = run_query(f"""
        SELECT COALESCE(SUM(m.quantity_done * COALESCE(p.standard_price, 0)), 0) AS move_value
        FROM fact_inventory_moves m
        LEFT JOIN dim_products p ON p.tenant_id = m.tenant_id AND p.odoo_id = m.product_id
        WHERE m.tenant_id = :tenant_id AND m.state = 'done' AND m.date >= CURRENT_DATE - INTERVAL '12 months' {m_sql}
    """, params)

    inv = inv_rows[0]; move = move_rows[0]
    total_val = float(inv["total_value"]); move_val = float(move["move_value"])
    turnover = calculate_ratio(move_val, total_val)

    return {
        "tool_name": "get_inventory_efficiency_tool",
        "total_inventory_value": total_val,
        "turnover_ratio": turnover,
        "days_inventory_on_hand": 365 / turnover if turnover > 0 else None,
        "efficiency_rating": "High" if turnover > 6 else "Medium" if turnover >= 3 else "Low"
    }
