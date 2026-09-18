from typing import Optional
# api/agent/tools_refactored/sales.py

from ..query_context import (
    normalize_tenant_ids,
    normalize_company_ids,
    build_tenant_filter_sql,
    build_company_filter_sql,
)
from .common import (
    run_query,
    build_currency_case_sql,
    get_multi_currency_conversions,
)
from ..utils import get_tenant_currency

def get_sales_summary_tool(
    tenant_ids: Optional[list[str]] = None,
    company_ids: Optional[list[int]] = None,
    start_date: str | None = None,
    end_date: str | None = None,
    period: str = "selected_period",
    base_currency: str | None = None,
    tenant_id: Optional[str] = None,
) -> dict:
    if tenant_id and not tenant_ids:
        tenant_ids = [tenant_id]
    t_sql_def, t_params_def = build_tenant_filter_sql(tenant_ids=tenant_ids, column_name="tenant_id", prefix="t_def")
    selected_company_ids = normalize_company_ids(company_ids=company_ids)
    amount_col = build_currency_case_sql('amount_total', tenant_ids=tenant_ids, base_currency=base_currency)
    query = f"SELECT COALESCE(SUM({amount_col}), 0) AS total_revenue, COUNT(*) AS order_count, COALESCE(AVG({amount_col}), 0) AS average_order_value, COALESCE(MIN(date_order), NULL) AS first_order_date, COALESCE(MAX(date_order), NULL) AS last_order_date FROM fact_sales_orders WHERE 1=1 {t_sql_def} AND state IN ('sale', 'done')"
    params = {}
    params.update(t_params_def)
    f_sql, f_params = build_company_filter_sql(company_ids=selected_company_ids)
    query += f_sql
    params.update(f_params)
    if start_date and end_date:
        query += " AND (date_order)::date BETWEEN CAST(:start_date AS date) AND CAST(:end_date AS date)"
        params["start_date"] = start_date
        params["end_date"] = end_date
    elif start_date:
        query += " AND (date_order)::date >= CAST(:start_date AS date)"
        params["start_date"] = start_date
    elif end_date:
        query += " AND (date_order)::date <= CAST(:end_date AS date)"
        params["end_date"] = end_date
    rows = run_query(query, params)
    row = rows[0] if rows else {}
    rev = float(row.get("total_revenue") or 0)
    
    t_ids = normalize_tenant_ids(tenant_ids=tenant_ids)
    first_tid = t_ids[0] if t_ids else None
    native_curr = base_currency or get_tenant_currency(tenant_ids=tenant_ids, company_ids=selected_company_ids)

    has_data = rev > 0 or int(row.get("order_count") or 0) > 0
    return {
        "tool_name": "get_sales_summary_tool",
        "status": "SUCCESS" if has_data else "NO_DATA",
        "message": "Sales summary retrieved successfully." if has_data else "No sales orders found for the specified period and filters.",
        "total_revenue": rev, 
        "order_count": int(row.get("order_count") or 0), 
        "average_order_value": float(row.get("average_order_value") or 0),
        "currency": native_curr,
        "currency_conversions": get_multi_currency_conversions(rev, tenant_ids=tenant_ids, company_ids=selected_company_ids, base_currency=base_currency, start_date=start_date, end_date=end_date),
    }

def get_top_products_tool(
    tenant_ids: Optional[list[str]] = None,
    company_ids: Optional[list[int]] = None,
    start_date: str | None = None,
    end_date: str | None = None,
    limit: int = 10,
    base_currency: str | None = None,
    tenant_id: Optional[str] = None,
) -> dict:
    if tenant_id and not tenant_ids:
        tenant_ids = [tenant_id]
    t_sql_l, t_params_l = build_tenant_filter_sql(tenant_ids=tenant_ids, column_name="l.tenant_id", prefix="t_l")
    selected_company_ids = normalize_company_ids(company_ids=company_ids)
    price_col = build_currency_case_sql('l.price_total', tenant_ids=tenant_ids, base_currency=base_currency, currency_column='o.currency_code')
    query = f"""
        SELECT 
            l.product_id, 
            p.name AS product_name, 
            COALESCE(SUM(l.product_uom_qty), 0) AS quantity, 
            COALESCE(SUM({price_col}), 0) AS revenue 
        FROM fact_sales_order_lines l 
        JOIN fact_sales_orders o ON o.id = l.sales_order_id AND o.tenant_id = l.tenant_id 
        JOIN dim_products p ON l.product_id = p.id AND l.tenant_id = p.tenant_id
        WHERE 1=1 {t_sql_l} 
          AND o.state IN ('sale', 'done') 
          AND l.product_id IS NOT NULL
    """
    params = {"limit": limit}
    params.update(t_params_l)
    f_sql, f_params = build_company_filter_sql(company_ids=selected_company_ids, column_name="l.company_id")
    query += f_sql
    params.update(f_params)
    if start_date and end_date:
        query += " AND (o.date_order)::date BETWEEN CAST(:start_date AS date) AND CAST(:end_date AS date)"
        params["start_date"] = start_date
        params["end_date"] = end_date
    elif start_date:
        query += " AND (o.date_order)::date >= CAST(:start_date AS date)"
        params["start_date"] = start_date
    elif end_date:
        query += " AND (o.date_order)::date <= CAST(:end_date AS date)"
        params["end_date"] = end_date
    query += " GROUP BY l.product_id, p.name ORDER BY revenue DESC LIMIT :limit"
    rows = run_query(query, params)
    return {
        "tool_name": "get_top_products_tool",
        "status": "SUCCESS" if rows else "NO_DATA",
        "message": "Top products retrieved successfully." if rows else "No products or sales records found for the specified period and filters.",
        "products": [{"product": r.get('product_name'), "revenue": float(r.get('revenue')), "quantity": float(r.get('quantity'))} for r in rows]
    }

def get_time_series_data_tool(
    tenant_ids: Optional[list[str]] = None,
    company_ids: Optional[list[int]] = None,
    granularity: str = "month",
    base_currency: str | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
    tenant_id: Optional[str] = None,
) -> dict:
    if tenant_id and not tenant_ids:
        tenant_ids = [tenant_id]
    t_sql_def, t_params_def = build_tenant_filter_sql(tenant_ids=tenant_ids, column_name="tenant_id", prefix="t_def")
    amount_col = build_currency_case_sql('amount_total', tenant_ids=tenant_ids, base_currency=base_currency)
    params = {}
    params.update(t_params_def)
    f_sql, f_params = build_company_filter_sql(company_ids=company_ids)
    params.update(f_params)

    date_filter = ""
    if start_date and end_date:
        date_filter += " AND (date_order)::date BETWEEN CAST(:start_date AS date) AND CAST(:end_date AS date)"
        params["start_date"] = start_date
        params["end_date"] = end_date
    elif start_date:
        date_filter += " AND (date_order)::date >= CAST(:start_date AS date)"
        params["start_date"] = start_date
    elif end_date:
        date_filter += " AND (date_order)::date <= CAST(:end_date AS date)"
        params["end_date"] = end_date

    query = f"SELECT DATE_TRUNC('{granularity}', date_order) AS period, COALESCE(SUM({amount_col}), 0) AS revenue, COUNT(*) AS order_count FROM fact_sales_orders WHERE 1=1 {t_sql_def} AND state IN ('sale', 'done') AND date_order IS NOT NULL {date_filter} {f_sql} GROUP BY period ORDER BY period ASC"
    rows = run_query(query, params)
    return {"tool_name": "get_time_series_data_tool", "points": [{"period": str(r.get('period')), "revenue": float(r.get('revenue')), "order_count": int(r.get('order_count'))} for r in rows]}

def get_sales_chart_data_tool(
    tenant_ids: Optional[list[str]] = None,
    company_ids: Optional[list[int]] = None,
    granularity: str = "month",
    base_currency: str | None = None,
    tenant_id: Optional[str] = None,
) -> dict:
    data = get_time_series_data_tool(tenant_ids=tenant_ids, company_ids=company_ids, granularity=granularity, base_currency=base_currency, tenant_id=tenant_id)
    return {"tool_name": "get_sales_chart_data_tool", "chart": {"type": "line", "data": data.get('points')}}

def analyze_variance_tool(
    tenant_ids: Optional[list[str]] = None,
    company_ids: Optional[list[int]] = None,
    base_currency: str | None = None,
    tenant_id: Optional[str] = None,
) -> dict:
    if tenant_id and not tenant_ids:
        tenant_ids = [tenant_id]
    t_sql_def, t_params_def = build_tenant_filter_sql(tenant_ids=tenant_ids, column_name="tenant_id", prefix="t_def")
    selected_company_ids = normalize_company_ids(company_ids=company_ids)
    f_sql, f_params = build_company_filter_sql(company_ids=selected_company_ids)
    amount_col = build_currency_case_sql('amount_total', tenant_ids=tenant_ids, base_currency=base_currency)
    query = f"SELECT DATE_TRUNC('month', date_order) AS month, SUM({amount_col}) AS revenue FROM fact_sales_orders WHERE 1=1 {t_sql_def} AND state IN ('sale', 'done') {f_sql} GROUP BY month ORDER BY month DESC LIMIT 2"
    params = {}
    params.update(t_params_def)
    params.update(f_params)
    rows = run_query(query, params)
    if len(rows) < 2:
        return {"status": "not_enough_data"}
    curr, prev = rows[0], rows[1]
    change = float(curr.get('revenue')) - float(prev.get('revenue'))
    return {"tool_name": "analyze_variance_tool", "current": float(curr.get('revenue')), "previous": float(prev.get('revenue')), "change": change}

def forecast_sales_tool(
    tenant_ids: Optional[list[str]] = None,
    company_ids: Optional[list[int]] = None,
    base_currency: str | None = None,
    tenant_id: Optional[str] = None,
) -> dict:
    if tenant_id and not tenant_ids:
        tenant_ids = [tenant_id]
    t_sql_def, t_params_def = build_tenant_filter_sql(tenant_ids=tenant_ids, column_name="tenant_id", prefix="t_def")
    params = {}
    params.update(t_params_def)
    f_sql, f_params = build_company_filter_sql(company_ids=company_ids)
    params.update(f_params)
    amount_col = build_currency_case_sql('amount_total', tenant_ids=tenant_ids, base_currency=base_currency)

    rows = run_query(
        f"""SELECT DATE_TRUNC('month', date_order) AS month,
                COALESCE(SUM({amount_col}), 0) AS revenue
            FROM fact_sales_orders
            WHERE 1=1 {t_sql_def}
              AND state IN ('sale', 'done')
              AND date_order >= CURRENT_DATE - INTERVAL '6 months'
              {f_sql}
            GROUP BY month
            ORDER BY month ASC""",
        params,
    )

    if len(rows) < 2:
        return {"tool_name": "forecast_sales_tool", "status": "insufficient_data", "message": "Need at least 2 months of data to forecast."}

    revenues = [float(r.get('revenue')) for r in rows]
    avg_3m = sum(revenues[-3:]) / min(3, len(revenues[-3:]))
    trend = revenues[-1] - revenues[-2] if len(revenues) >= 2 else 0
    forecast_next = round(avg_3m + (trend * 0.5), 2)

    return {
        "tool_name": "forecast_sales_tool",
        "historical_months": [{"month": str(r.get('month')), "revenue": float(r.get('revenue'))} for r in rows],
        "moving_average_3m": round(avg_3m, 2),
        "trend_direction": "Upward" if trend > 0 else "Downward" if trend < 0 else "Flat",
        "forecast_next_month": forecast_next,
    }
