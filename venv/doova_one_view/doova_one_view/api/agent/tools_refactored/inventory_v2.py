# api/agent/tools_refactored/inventory_v2.py
from typing import Optional, Dict, Any, List
from .common import run_query, build_company_filter_sql, build_tenant_filter_sql


def get_reorder_recommendations_tool(
    tenant_ids: Optional[list[str]] = None,
    company_ids: Optional[list[int]] = None,
    days_history: int = 30,
) -> Dict[str, Any]:
    """
    Identifies products where current available stock is too low compared to recent sales velocity.
    Recommends reorder quantities to cover the next N days based on historical sales.
    """
    t_sql_p, t_params_p = build_tenant_filter_sql(tenant_ids, column_name="p.tenant_id", prefix="t_p")
    t_sql_l, t_params_l = build_tenant_filter_sql(tenant_ids, column_name="l.tenant_id", prefix="t_l")
    t_sql_def, t_params_def = build_tenant_filter_sql(tenant_ids, column_name="tenant_id", prefix="t_def")
    c_sql_o, c_params_o = build_company_filter_sql(company_ids, column_name="o.company_id", prefix="co")
    c_sql_q, c_params_q = build_company_filter_sql(company_ids, column_name="company_id", prefix="cq")

    params = {}
    params.update(t_params_p)
    params.update(t_params_l)
    params.update(t_params_def)
    params.update(c_params_o)
    params.update(c_params_q)

    sql = f"""
        WITH sales_velocity AS (
            SELECT 
                l.product_id,
                COALESCE(SUM(l.product_uom_qty), 0) AS units_sold
            FROM fact_sales_order_lines l
            JOIN fact_sales_orders o ON o.id = l.sales_order_id AND o.tenant_id = l.tenant_id
            WHERE 1=1 {t_sql_l} 
              AND o.state IN ('sale', 'done')
              AND o.date_order >= CURRENT_DATE - INTERVAL '{days_history} days'
              {c_sql_o}
            GROUP BY l.product_id
        ),
        current_stock AS (
            SELECT 
                product_id,
                SUM(quantity) AS total_qty,
                SUM(reserved_quantity) AS reserved_qty
            FROM fact_stock_quants
            WHERE 1=1 {t_sql_def}
              {c_sql_q}
            GROUP BY product_id
        )
        SELECT 
            p.name AS product_name,
            COALESCE(s.units_sold, 0) AS sold_past_{days_history}_days,
            COALESCE(c.total_qty, 0) - COALESCE(c.reserved_qty, 0) AS available_qty,
            GREATEST(0, COALESCE(s.units_sold, 0) - (COALESCE(c.total_qty, 0) - COALESCE(c.reserved_qty, 0))) AS suggested_reorder_qty
        FROM dim_products p
        JOIN current_stock c ON p.id = c.product_id
        LEFT JOIN sales_velocity s ON p.id = s.product_id
        WHERE 1=1 {t_sql_p} AND p.product_type = 'product'
          AND (COALESCE(c.total_qty, 0) - COALESCE(c.reserved_qty, 0)) < COALESCE(s.units_sold, 0)
        ORDER BY suggested_reorder_qty DESC
        LIMIT 20
    """

    rows = run_query(sql, params)
    return {
        "tool_name": "get_reorder_recommendations_tool",
        "days_history": days_history,
        "recommendations": rows
    }


def get_abc_analysis_tool(
    tenant_ids: Optional[list[str]] = None,
    company_ids: Optional[list[int]] = None,
) -> Dict[str, Any]:
    """
    Classifies inventory into A (high value), B (medium), and C (low) categories based on all-time revenue contribution.
    Uses the 80/15/5 Pareto principle.
    """
    t_sql_p, t_params_p = build_tenant_filter_sql(tenant_ids, column_name="p.tenant_id", prefix="t_p")
    t_sql_l, t_params_l = build_tenant_filter_sql(tenant_ids, column_name="l.tenant_id", prefix="t_l")
    c_sql_o, c_params_o = build_company_filter_sql(company_ids, column_name="o.company_id", prefix="co")

    params = {}
    params.update(t_params_p)
    params.update(t_params_l)
    params.update(c_params_o)

    sql = f"""
        WITH product_revenue AS (
            SELECT 
                l.product_id,
                SUM(l.price_total) AS total_revenue
            FROM fact_sales_order_lines l
            JOIN fact_sales_orders o ON o.id = l.sales_order_id AND o.tenant_id = l.tenant_id
            WHERE 1=1 {t_sql_l} AND o.state IN ('sale', 'done')
              {c_sql_o}
            GROUP BY l.product_id
        ),
        ranked_products AS (
            SELECT 
                p.id,
                p.name,
                COALESCE(r.total_revenue, 0) AS revenue,
                SUM(COALESCE(r.total_revenue, 0)) OVER () AS grand_total_revenue,
                SUM(COALESCE(r.total_revenue, 0)) OVER (ORDER BY COALESCE(r.total_revenue, 0) DESC) AS cumulative_revenue
            FROM dim_products p
            LEFT JOIN product_revenue r ON p.id = r.product_id
            WHERE 1=1 {t_sql_p} AND p.product_type = 'product'
        ),
        categorized AS (
            SELECT 
                name,
                revenue,
                CASE 
                    WHEN grand_total_revenue = 0 THEN 'C'
                    WHEN cumulative_revenue <= 0.8 * grand_total_revenue THEN 'A'
                    WHEN cumulative_revenue <= 0.95 * grand_total_revenue THEN 'B'
                    ELSE 'C'
                END AS abc_class
            FROM ranked_products
            ORDER BY revenue DESC
        )
        SELECT 
            abc_class,
            COUNT(*) AS product_count,
            SUM(revenue) AS total_revenue
        FROM categorized
        GROUP BY abc_class
        ORDER BY abc_class
    """

    rows = run_query(sql, params)
    return {
        "tool_name": "get_abc_analysis_tool",
        "abc_summary": rows
    }


def get_warehouse_utilization_tool(
    tenant_ids: Optional[list[str]] = None,
    company_ids: Optional[list[int]] = None,
) -> Dict[str, Any]:
    """
    Analyzes stock quantities and valuation by physical location.
    """
    t_sql_q, t_params_q = build_tenant_filter_sql(tenant_ids, column_name="q.tenant_id", prefix="t_q")
    c_sql_q, c_params_q = build_company_filter_sql(company_ids, column_name="q.company_id", prefix="cq")

    params = {}
    params.update(t_params_q)
    params.update(c_params_q)

    sql = f"""
        SELECT 
            q.location_name,
            COUNT(DISTINCT q.product_id) AS unique_products,
            SUM(q.quantity) AS total_units,
            SUM(q.quantity * p.standard_price) AS estimated_value
        FROM fact_stock_quants q
        JOIN dim_products p ON q.product_id = p.id AND q.tenant_id = p.tenant_id
        WHERE 1=1 {t_sql_q}
          {c_sql_q}
        GROUP BY q.location_name
        ORDER BY estimated_value DESC
    """

    rows = run_query(sql, params)
    return {
        "tool_name": "get_warehouse_utilization_tool",
        "locations": rows
    }


def get_fulfillment_rate_tool(
    tenant_ids: Optional[list[str]] = None,
    company_ids: Optional[list[int]] = None,
) -> Dict[str, Any]:
    """
    Calculates the % of outgoing deliveries that were delivered on-time (done on or before scheduled date).
    """
    t_sql_def, t_params_def = build_tenant_filter_sql(tenant_ids, column_name="tenant_id", prefix="t_def")
    c_sql, c_params = build_company_filter_sql(company_ids, column_name="company_id", prefix="c")

    params = {}
    params.update(t_params_def)
    params.update(c_params)

    sql = f"""
        WITH outbound AS (
            SELECT 
                id,
                state,
                scheduled_date,
                date_done,
                CASE 
                    WHEN state = 'done' AND date_done <= scheduled_date THEN 1 
                    ELSE 0 
                END AS is_on_time
            FROM fact_stock_pickings
            WHERE 1=1 {t_sql_def} 
              {c_sql}
        )
        SELECT 
            COUNT(*) AS total_pickings,
            SUM(CASE WHEN state = 'done' THEN 1 ELSE 0 END) AS total_completed,
            SUM(is_on_time) AS total_on_time,
            ROUND(
                SUM(is_on_time)::numeric / NULLIF(SUM(CASE WHEN state = 'done' THEN 1 ELSE 0 END), 0) * 100, 
                2
            ) AS on_time_delivery_pct
        FROM outbound
    """

    rows = run_query(sql, params)
    return {
        "tool_name": "get_fulfillment_rate_tool",
        "metrics": rows[0] if rows else {}
    }


def get_backorder_aging_tool(
    tenant_ids: Optional[list[str]] = None,
    company_ids: Optional[list[int]] = None,
) -> Dict[str, Any]:
    """
    Identifies the oldest unfulfilled stock moves (backorders).
    """
    t_sql_m, t_params_m = build_tenant_filter_sql(tenant_ids, column_name="m.tenant_id", prefix="t_m")
    c_sql_m, c_params_m = build_company_filter_sql(company_ids, column_name="m.company_id", prefix="cm")

    params = {}
    params.update(t_params_m)
    params.update(c_params_m)

    sql = f"""
        SELECT 
            m.name AS reference,
            p.name AS product_name,
            m.product_uom_qty AS requested_qty,
            m.quantity_done AS done_qty,
            m.date AS order_date,
            CURRENT_DATE - m.date::date AS days_aging,
            m.state
        FROM fact_stock_moves m
        JOIN dim_products p ON m.product_id = p.id AND m.tenant_id = p.tenant_id
        WHERE 1=1 {t_sql_m} 
          AND m.state NOT IN ('done', 'cancel', 'draft')
          {c_sql_m}
        ORDER BY m.date ASC
        LIMIT 20
    """

    rows = run_query(sql, params)
    return {
        "tool_name": "get_backorder_aging_tool",
        "aging_backorders": rows
    }


def get_supplier_lead_time_tool(
    tenant_ids: Optional[list[str]] = None,
    company_ids: Optional[list[int]] = None,
) -> Dict[str, Any]:
    """
    Calculates average actual lead time (in days) from expected date vs actual done date for received items.
    """
    t_sql_sp, t_params_sp = build_tenant_filter_sql(tenant_ids, column_name="sp.tenant_id", prefix="t_sp")
    c_sql_sp, c_params_sp = build_company_filter_sql(company_ids, column_name="sp.company_id", prefix="csp")

    params = {}
    params.update(t_params_sp)
    params.update(c_params_sp)

    sql = f"""
        SELECT 
            p.name AS vendor_name,
            COUNT(sp.id) AS total_receipts,
            AVG(EXTRACT(EPOCH FROM (sp.date_done - sp.scheduled_date))/86400.0) AS avg_days_late
        FROM fact_stock_pickings sp
        JOIN dim_partners p ON sp.partner_id = p.id AND sp.tenant_id = p.tenant_id
        WHERE 1=1 {t_sql_sp} 
          AND sp.state = 'done'
          AND p.is_supplier = TRUE
          {c_sql_sp}
        GROUP BY p.id, p.name
        HAVING COUNT(sp.id) > 0
        ORDER BY avg_days_late DESC
        LIMIT 15
    """

    rows = run_query(sql, params)
    return {
        "tool_name": "get_supplier_lead_time_tool",
        "supplier_performance": rows
    }
