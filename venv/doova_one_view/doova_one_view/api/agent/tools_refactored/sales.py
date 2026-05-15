# api/agent/tools_refactored/sales.py

from .common import run_query, normalize_company_ids, build_company_filter_sql

def get_sales_summary_tool(tenant_id: str, company_id: int | None = None, company_ids: list[int] | None = None, start_date: str | None = None, end_date: str | None = None, period: str = "selected_period") -> dict:
    selected_company_ids = normalize_company_ids(company_id=company_id, companies=company_ids)
    query = "SELECT COALESCE(SUM(amount_total), 0) AS total_revenue, COUNT(*) AS order_count, COALESCE(AVG(amount_total), 0) AS average_order_value, COALESCE(MIN(date_order), NULL) AS first_order_date, COALESCE(MAX(date_order), NULL) AS last_order_date FROM fact_sales_orders WHERE tenant_id = :tenant_id AND state IN ('sale', 'done')"
    params = {"tenant_id": tenant_id}
    f_sql, f_params = build_company_filter_sql(tenant_id, selected_company_ids)
    query += f_sql
    params.update(f_params)
    if start_date: query += " AND date_order >= :start_date"; params["start_date"] = start_date
    if end_date: query += " AND date_order <= :end_date"; params["end_date"] = end_date
    rows = run_query(query, params)
    row = rows[0] if rows else {}
    return {"tool_name": "get_sales_summary_tool", "total_revenue": float(row.get("total_revenue") or 0), "order_count": int(row.get("order_count") or 0), "average_order_value": float(row.get("average_order_value") or 0)}

def get_top_products_tool(tenant_id: str, company_id: int | None = None, company_ids: list[int] | None = None, start_date: str | None = None, end_date: str | None = None, limit: int = 10) -> dict:
    selected_company_ids = normalize_company_ids(company_id=company_id, companies=company_ids)
    query = """
        SELECT 
            l.product_id, 
            p.name AS product_name, 
            COALESCE(SUM(l.product_uom_qty), 0) AS quantity, 
            COALESCE(SUM(l.price_total), 0) AS revenue 
        FROM fact_sales_order_lines l 
        JOIN fact_sales_orders o ON o.id = l.sales_order_id AND o.tenant_id = l.tenant_id 
        JOIN dim_products p ON l.product_id = p.odoo_id AND l.tenant_id = p.tenant_id
        WHERE l.tenant_id = :tenant_id 
          AND o.state IN ('sale', 'done') 
          AND l.product_id IS NOT NULL
    """
    params = {"tenant_id": tenant_id, "limit": limit}
    f_sql, f_params = build_company_filter_sql(tenant_id, selected_company_ids, column_name="l.company_id")
    query += f_sql
    params.update(f_params)
    if start_date: query += " AND o.date_order >= :start_date"; params["start_date"] = start_date
    if end_date: query += " AND o.date_order < (CAST(:end_date AS date) + INTERVAL '1 day')"; params["end_date"] = end_date
    query += " GROUP BY l.product_id, p.name ORDER BY revenue DESC LIMIT :limit"
    rows = run_query(query, params)
    return {"tool_name": "get_top_products_tool", "products": [{"product": r["product_name"], "revenue": float(r["revenue"]), "quantity": float(r["quantity"])} for r in rows]}

def get_time_series_data_tool(tenant_id: str, company_id: int | None = None, granularity: str = "month") -> dict:
    query = f"SELECT DATE_TRUNC('{granularity}', date_order) AS period, COALESCE(SUM(amount_total), 0) AS revenue, COUNT(*) AS order_count FROM fact_sales_orders WHERE tenant_id = :tenant_id AND state IN ('sale', 'done') AND date_order IS NOT NULL"
    params = {"tenant_id": tenant_id}
    f_sql, f_params = build_company_filter_sql(tenant_id, company_id)
    query += f_sql + f" GROUP BY period ORDER BY period ASC"
    params.update(f_params)
    rows = run_query(query, params)
    return {"tool_name": "get_time_series_data_tool", "points": [{"period": str(r["period"]), "revenue": float(r["revenue"]), "order_count": int(r["order_count"])} for r in rows]}

def get_sales_chart_data_tool(tenant_id: str, company_id: int | None = None, granularity: str = "month") -> dict:
    data = get_time_series_data_tool(tenant_id, company_id, granularity)
    return {"tool_name": "get_sales_chart_data_tool", "chart": {"type": "line", "data": data["points"]}}

def analyze_variance_tool(tenant_id: str, company_id: int | None = None) -> dict:
    query = "SELECT DATE_TRUNC('month', date_order) AS month, SUM(amount_total) AS revenue FROM fact_sales_orders WHERE tenant_id = :tenant_id AND state IN ('sale', 'done') GROUP BY month ORDER BY month DESC LIMIT 2"
    rows = run_query(query, {"tenant_id": tenant_id})
    if len(rows) < 2: return {"status": "not_enough_data"}
    curr, prev = rows[0], rows[1]
    change = float(curr["revenue"]) - float(prev["revenue"])
    return {"tool_name": "analyze_variance_tool", "current": float(curr["revenue"]), "previous": float(prev["revenue"]), "change": change}

def forecast_sales_tool(tenant_id: str, company_id: int | None = None) -> dict:
    params = {"tenant_id": tenant_id}
    f_sql, f_params = build_company_filter_sql(tenant_id, company_id)
    params.update(f_params)

    rows = run_query(
        f"""SELECT DATE_TRUNC('month', date_order) AS month,
                COALESCE(SUM(amount_total), 0) AS revenue
            FROM fact_sales_orders
            WHERE tenant_id = :tenant_id
              AND state IN ('sale', 'done')
              AND date_order >= CURRENT_DATE - INTERVAL '6 months'
              {f_sql}
            GROUP BY month
            ORDER BY month ASC""",
        params,
    )

    if len(rows) < 2:
        return {"tool_name": "forecast_sales_tool", "status": "insufficient_data", "message": "Need at least 2 months of data to forecast."}

    revenues = [float(r["revenue"]) for r in rows]
    avg_3m = sum(revenues[-3:]) / min(3, len(revenues[-3:]))
    trend = revenues[-1] - revenues[-2] if len(revenues) >= 2 else 0
    forecast_next = round(avg_3m + (trend * 0.5), 2)

    return {
        "tool_name": "forecast_sales_tool",
        "historical_months": [{"month": str(r["month"]), "revenue": float(r["revenue"])} for r in rows],
        "moving_average_3m": round(avg_3m, 2),
        "trend_direction": "Upward" if trend > 0 else "Downward" if trend < 0 else "Flat",
        "forecast_next_month": forecast_next,
    }
