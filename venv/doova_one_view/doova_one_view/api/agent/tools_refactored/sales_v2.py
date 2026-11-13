# api/agent/tools_refactored/sales_v2.py
from typing import Optional
from .common import (
    run_query,
    build_company_filter_sql,
    build_tenant_filter_sql,
    build_currency_case_sql,
)


def get_salesperson_performance_tool(
    tenant_ids: Optional[list[str]] = None,
    company_ids: Optional[list[int]] = None,
    start_date: str | None = None,
    end_date: str | None = None,
    base_currency: str | None = None,
) -> dict:
    t_sql_o, t_params_o = build_tenant_filter_sql(tenant_ids, column_name="o.tenant_id", prefix="t_o")
    amount_col = build_currency_case_sql('o.amount_total', tenant_ids=tenant_ids, base_currency=base_currency, currency_column='o.currency_code', is_transaction_currency=True)
    margin_col = build_currency_case_sql('o.margin', tenant_ids=tenant_ids, base_currency=base_currency, currency_column='o.currency_code', is_transaction_currency=True)
    
    query = f"""
        SELECT 
            u.name AS salesperson,
            COALESCE(SUM({amount_col}), 0) AS total_revenue,
            COUNT(o.id) AS order_count,
            COALESCE(SUM({margin_col}), 0) AS total_margin
        FROM fact_sales_orders o
        JOIN dim_users u ON o.user_id = u.id AND o.tenant_id = u.tenant_id
        WHERE 1=1 {t_sql_o} AND o.state IN ('sale', 'done')
    """
    params = {}
    params.update(t_params_o)
    f_sql, f_params = build_company_filter_sql(company_ids, column_name="o.company_id")
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
        
    query += " GROUP BY u.name ORDER BY total_revenue DESC"
    
    rows = run_query(query, params)
    
    performance = []
    for r in rows:
        rev = float(r.get("total_revenue", 0))
        margin = float(r.get("total_margin", 0))
        orders = int(r.get("order_count", 0))
        
        performance.append({
            "salesperson": r.get("salesperson"),
            "total_revenue": rev,
            "order_count": orders,
            "avg_order_value": rev / orders if orders > 0 else 0,
            "margin_pct": (margin / rev * 100) if rev > 0 else 0
        })
        
    return {
        "tool_name": "get_salesperson_performance_tool",
        "performance": performance
    }


def get_sales_pipeline_tool(
    tenant_ids: Optional[list[str]] = None,
    company_ids: Optional[list[int]] = None,
    start_date: str | None = None,
    end_date: str | None = None,
    base_currency: str | None = None,
) -> dict:
    t_sql_def, t_params_def = build_tenant_filter_sql(tenant_ids, column_name="tenant_id", prefix="t_def")
    amount_col = build_currency_case_sql('amount_total', tenant_ids=tenant_ids, base_currency=base_currency, is_transaction_currency=True)
    
    query = f"""
        SELECT 
            state,
            COUNT(id) AS order_count,
            COALESCE(SUM({amount_col}), 0) AS total_value
        FROM fact_sales_orders
        WHERE 1=1 {t_sql_def}
    """
    params = {}
    params.update(t_params_def)
    f_sql, f_params = build_company_filter_sql(company_ids)
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
        
    query += " GROUP BY state"
    
    rows = run_query(query, params)
    
    pipeline = {
        "open_quotes_count": 0,
        "open_quotes_value": 0.0,
        "won_orders_count": 0,
        "won_orders_value": 0.0,
        "lost_cancelled_count": 0,
        "total_count": 0
    }
    
    for r in rows:
        state = r.get("state")
        count = int(r.get("order_count", 0))
        val = float(r.get("total_value", 0))
        
        pipeline["total_count"] += count
        
        if state in ('draft', 'sent'):
            pipeline["open_quotes_count"] += count
            pipeline["open_quotes_value"] += val
        elif state in ('sale', 'done'):
            pipeline["won_orders_count"] += count
            pipeline["won_orders_value"] += val
        elif state == 'cancel':
            pipeline["lost_cancelled_count"] += count
            
    won = pipeline["won_orders_count"]
    total = pipeline["total_count"]
    pipeline["conversion_rate_pct"] = (won / total * 100) if total > 0 else 0
    
    return {
        "tool_name": "get_sales_pipeline_tool",
        "pipeline": pipeline
    }


def get_discount_leakage_tool(
    tenant_ids: Optional[list[str]] = None,
    company_ids: Optional[list[int]] = None,
    start_date: str | None = None,
    end_date: str | None = None,
    base_currency: str | None = None,
) -> dict:
    t_sql_l, t_params_l = build_tenant_filter_sql(tenant_ids, column_name="l.tenant_id", prefix="t_l")
    price_col = build_currency_case_sql('l.price_unit', tenant_ids=tenant_ids, base_currency=base_currency, currency_column='o.currency_code')
    
    query = f"""
        SELECT 
            SUM(l.product_uom_qty * {price_col} * (COALESCE(l.discount, 0) / 100.0)) AS total_discount_given,
            AVG(COALESCE(l.discount, 0)) AS avg_discount_pct,
            MAX(COALESCE(l.discount, 0)) AS max_discount_pct
        FROM fact_sales_order_lines l
        JOIN fact_sales_orders o ON o.id = l.sales_order_id AND o.tenant_id = l.tenant_id
        WHERE 1=1 {t_sql_l} AND o.state IN ('sale', 'done')
    """
    params = {}
    params.update(t_params_l)
    f_sql, f_params = build_company_filter_sql(company_ids, column_name="o.company_id")
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
        
    rows = run_query(query, params)
    
    # Also get top discounted products
    top_query = f"""
        SELECT 
            p.name AS product_name,
            AVG(COALESCE(l.discount, 0)) AS avg_discount,
            SUM(l.product_uom_qty * {price_col} * (COALESCE(l.discount, 0) / 100.0)) AS discount_value
        FROM fact_sales_order_lines l
        JOIN fact_sales_orders o ON o.id = l.sales_order_id AND o.tenant_id = l.tenant_id
        JOIN dim_products p ON l.product_id = p.id AND l.tenant_id = p.tenant_id
        WHERE 1=1 {t_sql_l} AND o.state IN ('sale', 'done') AND COALESCE(l.discount, 0) > 0
    """
    top_query += f_sql
    if start_date and end_date:
        top_query += " AND (o.date_order)::date BETWEEN CAST(:start_date AS date) AND CAST(:end_date AS date)"
    elif start_date:
        top_query += " AND (o.date_order)::date >= CAST(:start_date AS date)"
    elif end_date:
        top_query += " AND (o.date_order)::date <= CAST(:end_date AS date)"
    top_query += " GROUP BY p.name ORDER BY discount_value DESC LIMIT 5"
    
    top_rows = run_query(top_query, params)
    
    res = rows[0] if rows else {}
    return {
        "tool_name": "get_discount_leakage_tool",
        "total_discount_value": float(res.get("total_discount_given") or 0),
        "average_discount_pct": float(res.get("avg_discount_pct") or 0),
        "max_discount_pct": float(res.get("max_discount_pct") or 0),
        "top_discounted_products": [
            {
                "product": r.get("product_name"), 
                "avg_discount_pct": float(r.get("avg_discount") or 0),
                "total_discount_value": float(r.get("discount_value") or 0)
            } for r in top_rows
        ]
    }


def get_customer_lifetime_value_tool(
    tenant_ids: Optional[list[str]] = None,
    company_ids: Optional[list[int]] = None,
    base_currency: str | None = None,
    limit: int = 10,
) -> dict:
    t_sql_o, t_params_o = build_tenant_filter_sql(tenant_ids, column_name="o.tenant_id", prefix="t_o")
    amount_col = build_currency_case_sql('o.amount_total', tenant_ids=tenant_ids, base_currency=base_currency, currency_column='o.currency_code', is_transaction_currency=True)
    
    query = f"""
        SELECT 
            p.name AS customer_name,
            COALESCE(SUM({amount_col}), 0) AS lifetime_revenue,
            COUNT(o.id) AS order_count,
            MIN(o.date_order) AS first_order_date,
            MAX(o.date_order) AS last_order_date
        FROM fact_sales_orders o
        JOIN dim_partners p ON o.partner_id = p.id AND o.tenant_id = p.tenant_id
        WHERE 1=1 {t_sql_o} AND o.state IN ('sale', 'done')
    """
    params = {"limit": limit}
    params.update(t_params_o)
    f_sql, f_params = build_company_filter_sql(company_ids, column_name="o.company_id")
    query += f_sql
    params.update(f_params)
    
    query += " GROUP BY p.name ORDER BY lifetime_revenue DESC LIMIT :limit"
    
    rows = run_query(query, params)
    
    clv_list = []
    for r in rows:
        rev = float(r.get("lifetime_revenue", 0))
        orders = int(r.get("order_count", 0))
        tier = "Bronze"
        if rev > 100000: tier = "Platinum"
        elif rev > 50000: tier = "Gold"
        elif rev > 10000: tier = "Silver"
        
        first = r.get("first_order_date")
        last = r.get("last_order_date")
        
        clv_list.append({
            "customer": r.get("customer_name"),
            "lifetime_revenue": rev,
            "order_count": orders,
            "average_order_value": rev / orders if orders > 0 else 0,
            "tier": tier,
            "first_order": first.strftime("%Y-%m-%d") if first else None,
            "last_order": last.strftime("%Y-%m-%d") if last else None
        })
        
    return {
        "tool_name": "get_customer_lifetime_value_tool",
        "top_customers": clv_list
    }


def get_order_to_cash_cycle_tool(
    tenant_ids: Optional[list[str]] = None,
    company_ids: Optional[list[int]] = None,
    start_date: str | None = None,
    end_date: str | None = None,
    base_currency: str | None = None,
) -> dict:
    t_sql_o, t_params_o = build_tenant_filter_sql(tenant_ids, column_name="o.tenant_id", prefix="t_o")
    
    query = f"""
        SELECT 
            AVG(EXTRACT(EPOCH FROM (am.invoice_date::timestamp - o.date_order::timestamp))/86400.0) AS avg_days_to_invoice,
            COUNT(o.id) AS matched_orders
        FROM fact_sales_orders o
        JOIN fact_account_moves am ON am.invoice_origin = o.odoo_name AND am.tenant_id = o.tenant_id
        WHERE 1=1 {t_sql_o} 
          AND o.state IN ('sale', 'done')
          AND am.move_type = 'out_invoice'
          AND am.state = 'posted'
    """
    params = {}
    params.update(t_params_o)
    f_sql, f_params = build_company_filter_sql(company_ids, column_name="o.company_id")
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
        
    rows = run_query(query, params)
    res = rows[0] if rows else {}
    
    return {
        "tool_name": "get_order_to_cash_cycle_tool",
        "avg_days_to_invoice": float(res.get("avg_days_to_invoice") or 0),
        "matched_orders_analyzed": int(res.get("matched_orders") or 0),
        "note": "Payment timing is highly dependent on partial reconciles. Average days to invoice is currently the most precise O2C measure available."
    }


def get_revenue_by_category_tool(
    tenant_ids: Optional[list[str]] = None,
    company_ids: Optional[list[int]] = None,
    start_date: str | None = None,
    end_date: str | None = None,
    base_currency: str | None = None,
) -> dict:
    t_sql_l, t_params_l = build_tenant_filter_sql(tenant_ids, column_name="l.tenant_id", prefix="t_l")
    price_col = build_currency_case_sql('l.price_subtotal', tenant_ids=tenant_ids, base_currency=base_currency, currency_column='o.currency_code')
    
    query = f"""
        SELECT 
            c.complete_name AS category_name,
            COALESCE(SUM({price_col}), 0) AS revenue,
            COALESCE(SUM(l.product_uom_qty), 0) AS volume
        FROM fact_sales_order_lines l
        JOIN fact_sales_orders o ON o.id = l.sales_order_id AND o.tenant_id = l.tenant_id
        JOIN dim_products p ON l.product_id = p.id AND l.tenant_id = p.tenant_id
        JOIN dim_product_categories c ON p.category_id = c.id AND p.tenant_id = c.tenant_id
        WHERE 1=1 {t_sql_l} 
          AND o.state IN ('sale', 'done')
    """
    params = {}
    params.update(t_params_l)
    f_sql, f_params = build_company_filter_sql(company_ids, column_name="o.company_id")
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
        
    query += " GROUP BY c.complete_name ORDER BY revenue DESC"
    
    rows = run_query(query, params)
    
    total_rev = sum(float(r.get("revenue", 0)) for r in rows)
    
    categories = []
    for r in rows:
        rev = float(r.get("revenue", 0))
        categories.append({
            "category": r.get("category_name") or "Uncategorized",
            "revenue": rev,
            "volume": float(r.get("volume", 0)),
            "pct_of_total": (rev / total_rev * 100) if total_rev > 0 else 0
        })
        
    return {
        "tool_name": "get_revenue_by_category_tool",
        "total_revenue": total_rev,
        "categories": categories
    }
