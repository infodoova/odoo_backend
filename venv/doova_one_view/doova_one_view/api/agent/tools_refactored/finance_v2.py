from doova_one_view.api.agent.query_context import build_tenant_filter_sql
from typing import Optional
# api/agent/tools_refactored/finance_v2.py

from .common import run_query, normalize_company_ids, build_company_filter_sql, build_currency_case_sql

# Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬
# 1. CASH FLOW STATEMENT (Indirect Method Proxy)
# Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬
def get_cash_flow_statement_tool(
    tenant_id: str,
    company_id: int | None = None,
    company_ids: list[int] | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
    base_currency: str | None = None,
    tenant_ids: Optional[list[str]] = None,
    source: str = "auto"
) -> dict:
    """Generate the structured Cash Flow Statement (Operating, Investing, Financing, Unclassified) matching Odoo with full itemized details."""
    from doova_one_view.api.accounting.service import AccountingService
    c_ids = normalize_company_ids(company_id=company_id, companies=company_ids)
    cf = AccountingService._calc_cash_flow_sync(
        tenant_id=tenant_id,
        start_date=start_date,
        end_date=end_date,
        company_ids=c_ids,
        base_currency=base_currency,
        source=source
    )
    op = cf.get("operating_activities", {})
    inv = cf.get("investing_activities", {})
    fin = cf.get("financing_activities", {})
    unclass = cf.get("unclassified_activities", {})
    raw_hierarchy = cf.get("raw_hierarchy") or []
    
    details = []
    if raw_hierarchy:
        for item in raw_hierarchy:
            details.append({
                "name": item.get("name"),
                "level": item.get("level"),
                "amount": item.get("amount"),
                "line_id": item.get("line_id"),
            })

    cust_adv = op.get("customer_advances", op.get("customer_payments", 0.0))
    supp_adv = op.get("supplier_advances", op.get("supplier_payments", 0.0))
    direct_rec = op.get("cash_received_from_operating_activities", op.get("direct_receipts", 0.0))
    direct_paid = op.get("cash_paid_for_operating_activities", op.get("direct_payments", 0.0))

    return {
        "tool_name": "get_cash_flow_statement_tool",
        "beginning_balance": cf.get("beginning_balance", 0.0),
        "operating_activities": {
            "customer_advances": cust_adv,
            "customer_payments": cust_adv,
            "supplier_advances": supp_adv,
            "supplier_payments": supp_adv,
            "cash_received_from_operating_activities": direct_rec,
            "cash_paid_for_operating_activities": direct_paid,
            "direct_receipts": direct_rec,
            "direct_payments": direct_paid,
            "total": op.get("total", 0.0),
        },
        "customer_advances": cust_adv,
        "customer_payments": cust_adv,
        "supplier_advances": supp_adv,
        "supplier_payments": supp_adv,
        "cash_received_from_operating_activities": direct_rec,
        "cash_paid_for_operating_activities": direct_paid,
        "direct_receipts": direct_rec,
        "direct_payments": direct_paid,
        "net_cash_from_operating": op.get("total", 0.0),
        "investing_activities": inv,
        "net_cash_from_investing": inv.get("total", 0.0),
        "financing_activities": fin,
        "net_cash_from_financing": fin.get("total", 0.0),
        "unclassified_activities": unclass,
        "net_cash_from_unclassified": unclass.get("total", 0.0),
        "net_increase": cf.get("net_increase", 0.0),
        "net_change_in_cash": cf.get("net_increase", 0.0),
        "actual_net_change_in_cash": cf.get("actual_net_change_in_cash", cf.get("net_increase", 0.0)),
        "unexplained_difference": cf.get("unexplained_difference", 0.0),
        "closing_balance": cf.get("closing_balance", 0.0),
        "details": details,
        "raw_hierarchy": raw_hierarchy,
        "source_engine": cf.get("source_engine", "odoo_enterprise_live"),
        "execution_time_ms": cf.get("execution_time_ms"),
    }

# Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬
# 2. WORKING CAPITAL EFFICIENCY (DSO, DPO, CCC)
# Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬
def get_working_capital_efficiency_tool(
    tenant_id: str,
    company_id: int | None = None,
    company_ids: list[int] | None = None,
    base_currency: str | None = None, tenant_ids: Optional[list[str]] = None
) -> dict:
    """Calculate Days Sales Outstanding, Days Payable Outstanding, and Cash Conversion Cycle over the last 365 days."""

    t_sql_m, t_params_m = build_tenant_filter_sql(tenant_id, tenant_ids, column_name="m.tenant_id", prefix="t_m")
    t_sql_q, t_params_q = build_tenant_filter_sql(tenant_id, tenant_ids, column_name="q.tenant_id", prefix="t_q")
    selected = normalize_company_ids(company_id=company_id, companies=company_ids)
    amount_col = build_currency_case_sql('l.balance', tenant_id, base_currency, 'm.currency_code')
    params: dict = {"tenant_id": tenant_id}
    params.update(t_params_m)
    params.update(t_params_q)
    f_sql, f_params = build_company_filter_sql(tenant_id, selected, column_name="m.company_id")
    params.update(f_params)

    # We need AR, AP, Revenue, COGS, Inventory for the last 365 days.
    # AR/AP/Inventory are point-in-time balances.
    # Revenue/COGS are sums over 365 days.
    query = f"""
        WITH trailing_metrics AS (
            SELECT 
                SUM(CASE WHEN l.account_type = 'asset_receivable' THEN {amount_col} ELSE 0 END) AS total_ar,
                SUM(CASE WHEN l.account_type = 'liability_payable' THEN -{amount_col} ELSE 0 END) AS total_ap,
                SUM(CASE WHEN l.account_type = 'income' AND m.date >= CURRENT_DATE - INTERVAL '365 days' THEN -{amount_col} ELSE 0 END) AS rev_365,
                SUM(CASE WHEN l.account_type IN ('expense', 'expense_direct_cost') AND m.date >= CURRENT_DATE - INTERVAL '365 days' THEN {amount_col} ELSE 0 END) AS cogs_365
            FROM fact_account_move_lines l
            JOIN fact_account_moves m ON l.account_move_id = m.id AND l.tenant_id = m.tenant_id
            
            WHERE 1=1 {t_sql_m} AND m.state = 'posted' {f_sql}
        )
        SELECT * FROM trailing_metrics
    """
    rows = run_query(query, params)
    r = rows[0] if rows else {}
    
    ar = float(r.get("total_ar") or 0)
    ap = float(r.get("total_ap") or 0)
    rev = float(r.get("rev_365") or 0)
    cogs = float(r.get("cogs_365") or 0)
    
    # Need Inventory value
    inv_query = f"""
        SELECT COALESCE(SUM(q.quantity * p.standard_price), 0) AS inv_value
        FROM fact_stock_quants q
        JOIN dim_products p ON q.product_id = p.id AND q.tenant_id = p.tenant_id
        WHERE 1=1 {t_sql_q} AND q.quantity > 0
    """
    inv_params = {"tenant_id": tenant_id}
    q_sql, q_params = build_company_filter_sql(tenant_id, selected, column_name="q.company_id", prefix="q_")
    inv_params.update(q_params)
    inv_params.update(t_params_q)
    inv_rows = run_query(inv_query + q_sql, inv_params)
    inv = float(inv_rows[0].get("inv_value") or 0) if inv_rows else 0.0
    
    dso = (ar / rev * 365) if rev > 0 else 0
    dpo = (ap / cogs * 365) if cogs > 0 else 0
    dio = (inv / cogs * 365) if cogs > 0 else 0
    ccc = dso + dio - dpo

    return {
        "tool_name": "get_working_capital_efficiency_tool",
        "days_sales_outstanding_dso": round(dso, 1),
        "days_payable_outstanding_dpo": round(dpo, 1),
        "days_inventory_outstanding_dio": round(dio, 1),
        "cash_conversion_cycle_ccc": round(ccc, 1),
        "metrics": {
            "ar": round(ar, 2),
            "ap": round(ap, 2),
            "inventory": round(inv, 2),
            "trailing_revenue": round(rev, 2),
            "trailing_cogs": round(cogs, 2)
        }
    }

# Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬
# 3. PERIOD-OVER-PERIOD P&L COMPARISON
# Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬
def get_period_comparison_pnl_tool(
    tenant_id: str,
    period1_start: str,
    period1_end: str,
    period2_start: str,
    period2_end: str,
    company_id: int | None = None,
    company_ids: list[int] | None = None,
    base_currency: str | None = None, tenant_ids: Optional[list[str]] = None
) -> dict:
    """Compare P&L line items between two explicit date periods."""

    t_sql_m, t_params_m = build_tenant_filter_sql(tenant_id, tenant_ids, column_name="m.tenant_id", prefix="t_m")
    selected = normalize_company_ids(company_id=company_id, companies=company_ids)
    amount_col = build_currency_case_sql('l.balance', tenant_id, base_currency, 'm.currency_code')
    params: dict = {
        "tenant_id": tenant_id, 
        "p1_start": period1_start, "p1_end": period1_end,
        "p2_start": period2_start, "p2_end": period2_end
    }
    params.update(t_params_m)
    f_sql, f_params = build_company_filter_sql(tenant_id, selected, column_name="m.company_id")
    params.update(f_params)

    query = f"""
        SELECT 
            COALESCE(l.account_type, 'unknown') AS acc_type,
            SUM(CASE WHEN m.date >= :p1_start AND m.date <= :p1_end THEN -{amount_col} ELSE 0 END) AS p1_amount,
            SUM(CASE WHEN m.date >= :p2_start AND m.date <= :p2_end THEN -{amount_col} ELSE 0 END) AS p2_amount
        FROM fact_account_move_lines l
        JOIN fact_account_moves m ON l.account_move_id = m.id AND l.tenant_id = m.tenant_id
        
        WHERE 1=1 {t_sql_m}
          AND m.state = 'posted'
          AND l.account_type IN ('income', 'income_other', 'expense', 'expense_direct_cost', 'expense_depreciation')
          AND ((m.date >= :p1_start AND m.date <= :p1_end) OR (m.date >= :p2_start AND m.date <= :p2_end))
          {f_sql}
        GROUP BY l.account_type
    """
    rows = run_query(query, params)
    
    comparison = {}
    for r in rows:
        ctype = r.get("acc_type")
        v1 = float(r.get("p1_amount") or 0)
        v2 = float(r.get("p2_amount") or 0)
        variance = v2 - v1
        variance_pct = round((variance / abs(v1)) * 100, 1) if v1 != 0 else 0
        comparison[ctype] = {
            "period1_amount": round(v1, 2),
            "period2_amount": round(v2, 2),
            "variance": round(variance, 2),
            "variance_pct": variance_pct
        }
        
    return {
        "tool_name": "get_period_comparison_pnl_tool",
        "period1": f"{period1_start} to {period1_end}",
        "period2": f"{period2_start} to {period2_end}",
        "comparison": comparison
    }

# Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬
# 4. INTEREST COVERAGE RATIO
# Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬
def get_interest_coverage_tool(
    tenant_id: str,
    start_date: str | None = None,
    end_date: str | None = None,
    company_id: int | None = None,
    company_ids: list[int] | None = None,
    base_currency: str | None = None, tenant_ids: Optional[list[str]] = None
) -> dict:
    """Calculate Interest Coverage Ratio (EBIT / Interest Expense)."""

    t_sql_m, t_params_m = build_tenant_filter_sql(tenant_id, tenant_ids, column_name="m.tenant_id", prefix="t_m")
    selected = normalize_company_ids(company_id=company_id, companies=company_ids)
    amount_col = build_currency_case_sql('l.balance', tenant_id, base_currency, 'm.currency_code')
    params: dict = {"tenant_id": tenant_id}
    params.update(t_params_m)
    f_sql, f_params = build_company_filter_sql(tenant_id, selected, column_name="m.company_id")
    params.update(f_params)
    
    date_sql = ""
    if start_date:
        date_sql += " AND m.date >= :start_date"
        params["start_date"] = start_date
    if end_date:
        date_sql += " AND m.date <= :end_date"
        params["end_date"] = end_date

    # Using simplistic Odoo chart of accounts:
    # Interest expense is usually in 'expense' but often separated by code.
    # Without specific codes, we can only approximate EBIT = net income + taxes + interest.
    # Since we lack specific tax/interest flags in standard Odoo account_type, we check account names.
    query = f"""
        SELECT 
            SUM(CASE WHEN l.account_type IN ('income', 'income_other') THEN -{amount_col} ELSE 0 END) AS total_income,
            SUM(CASE WHEN l.account_type IN ('expense', 'expense_direct_cost') AND l.account_name ILIKE '%interest%' THEN {amount_col} ELSE 0 END) AS interest_expense,
            SUM(CASE WHEN l.account_type IN ('expense', 'expense_direct_cost', 'expense_depreciation') AND l.account_name NOT ILIKE '%interest%' AND l.account_name NOT ILIKE '%tax%' THEN {amount_col} ELSE 0 END) AS operating_expense
        FROM fact_account_move_lines l
        JOIN fact_account_moves m ON l.account_move_id = m.id AND l.tenant_id = m.tenant_id
        
        WHERE 1=1 {t_sql_m}
          AND m.state = 'posted'
          {f_sql} {date_sql}
    """
    rows = run_query(query, params)
    r = rows[0] if rows else {}
    
    income = float(r.get("total_income") or 0)
    opex = float(r.get("operating_expense") or 0)
    interest = float(r.get("interest_expense") or 0)
    
    ebit = income - opex
    ratio = round(ebit / interest, 2) if interest > 0 else float('inf')
    
    return {
        "tool_name": "get_interest_coverage_tool",
        "ebit": round(ebit, 2),
        "interest_expense": round(interest, 2),
        "interest_coverage_ratio": ratio,
        "status": "Safe" if ratio >= 3 else ("Warning" if ratio >= 1.5 else "Danger")
    }

# Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬
# 5. REVENUE SEGMENTATION
# Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬
def get_revenue_segmentation_tool(
    tenant_id: str,
    segment_by: str = "customer",  # options: "customer", "journal"
    start_date: str | None = None,
    end_date: str | None = None,
    company_id: int | None = None,
    company_ids: list[int] | None = None,
    limit: int = 15,
    base_currency: str | None = None, tenant_ids: Optional[list[str]] = None
) -> dict:
    """Segment revenue by customer or journal."""

    t_sql_m, t_params_m = build_tenant_filter_sql(tenant_id, tenant_ids, column_name="m.tenant_id", prefix="t_m")
    selected = normalize_company_ids(company_id=company_id, companies=company_ids)
    amount_col = build_currency_case_sql('l.balance', tenant_id, base_currency, 'm.currency_code')
    params: dict = {"tenant_id": tenant_id, "limit": limit}
    params.update(t_params_m)
    f_sql, f_params = build_company_filter_sql(tenant_id, selected, column_name="m.company_id")
    params.update(f_params)
    
    date_sql = ""
    if start_date:
        date_sql += " AND m.date >= :start_date"; params["start_date"] = start_date
    if end_date:
        date_sql += " AND m.date <= :end_date"; params["end_date"] = end_date

    segment_col = "p.name" if segment_by == "customer" else "j.name"
    join_sql = "LEFT JOIN dim_partners p ON m.partner_id = p.id AND m.tenant_id = p.tenant_id" if segment_by == "customer" else "LEFT JOIN dim_account_journals j ON m.journal_id = j.id AND m.tenant_id = j.tenant_id"

    query = f"""
        SELECT 
            COALESCE({segment_col}, 'Unassigned') AS segment,
            COALESCE(SUM(-{amount_col}), 0) AS revenue
        FROM fact_account_move_lines l
        JOIN fact_account_moves m ON l.account_move_id = m.id AND l.tenant_id = m.tenant_id
        
        {join_sql}
        WHERE 1=1 {t_sql_m}
          AND m.state = 'posted'
          AND l.account_type IN ('income', 'income_other')
          {f_sql} {date_sql}
        GROUP BY segment
        ORDER BY revenue DESC
        LIMIT :limit
    """
    rows = run_query(query, params)
    
    total = sum(float(r.get("revenue") or 0) for r in rows)
    return {
        "tool_name": "get_revenue_segmentation_tool",
        "segment_by": segment_by,
        "total_revenue": round(total, 2),
        "segments": [
            {
                "segment": r.get("segment"),
                "revenue": round(float(r.get("revenue")), 2),
                "pct_of_total": round((float(r.get("revenue")) / total) * 100, 1) if total > 0 else 0
            }
            for r in rows
        ]
    }

# Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬
# 6. PAYMENT RECONCILIATION
# Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬
def get_payment_reconciliation_tool(
    tenant_id: str,
    company_id: int | None = None,
    company_ids: list[int] | None = None,
    base_currency: str | None = None, tenant_ids: Optional[list[str]] = None
) -> dict:
    """Analyze unmatched payments and reconciliation efficiency."""

    t_sql_m, t_params_m = build_tenant_filter_sql(tenant_id, tenant_ids, column_name="m.tenant_id", prefix="t_m")
    selected = normalize_company_ids(company_id=company_id, companies=company_ids)
    amount_col = build_currency_case_sql('l.balance', tenant_id, base_currency, 'm.currency_code')
    params: dict = {"tenant_id": tenant_id}
    params.update(t_params_m)
    f_sql, f_params = build_company_filter_sql(tenant_id, selected, column_name="m.company_id")
    params.update(f_params)

    # Find customer payments (receipts) not fully reconciled
    query = f"""
        SELECT 
            p.name AS customer_name,
            m.odoo_name AS payment_ref,
            m.date,
            SUM(-{amount_col}) AS payment_amount
        FROM fact_account_move_lines l
        JOIN fact_account_moves m ON l.account_move_id = m.id AND l.tenant_id = m.tenant_id
        
        LEFT JOIN dim_partners p ON m.partner_id = p.id AND m.tenant_id = p.tenant_id
        WHERE 1=1 {t_sql_m}
          AND m.state = 'posted'
          AND l.account_type = 'asset_receivable'
          AND m.amount_residual != 0
          AND l.balance < 0 -- Credit balance on AR means payment received
          {f_sql}
        GROUP BY p.name, m.odoo_name, m.date
        ORDER BY payment_amount DESC
        LIMIT 20
    """
    rows = run_query(query, params)
    
    return {
        "tool_name": "get_payment_reconciliation_tool",
        "unreconciled_payments": [
            {
                "customer": r.get("customer_name"),
                "payment_ref": r.get("payment_ref"),
                "date": str(r.get("date")),
                "amount": round(float(r.get("payment_amount")), 2)
            }
            for r in rows
        ],
        "total_unreconciled_value": sum(float(r.get("payment_amount") or 0) for r in rows)
    }


