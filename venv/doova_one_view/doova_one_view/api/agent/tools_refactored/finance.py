from doova_one_view.api.agent.query_context import build_tenant_filter_sql
from typing import Optional
# api/agent/tools_refactored/finance.py

from .common import run_query, normalize_company_ids, build_company_filter_sql, calculate_ratio, build_currency_case_sql
from .sales import get_sales_summary_tool
from .inventory import get_inventory_efficiency_tool


# Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬
# 1. ACCOUNTS RECEIVABLE
# Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬

def get_receivables_analysis_tool(tenant_id: str, company_id: int | None = None, company_ids: list[int] | None = None, limit: int = 10, base_currency: str | None = None, tenant_ids: Optional[list[str]] = None) -> dict:

    t_sql_m, t_params_m = build_tenant_filter_sql(tenant_id, tenant_ids, column_name="m.tenant_id", prefix="t_m")
    t_sql_def, t_params_def = build_tenant_filter_sql(tenant_id, tenant_ids, column_name="tenant_id", prefix="t_def")
    amount_col = build_currency_case_sql('amount_total', tenant_id, base_currency)
    amount_m_col = build_currency_case_sql('m.amount_total', tenant_id, base_currency, 'm.currency_code')
    params = {"tenant_id": tenant_id, "limit": limit}
    params.update(t_params_m)
    params.update(t_params_def)
    f_sql, f_params = build_company_filter_sql(tenant_id, normalize_company_ids(company_id=company_id, companies=company_ids))
    f_sql_m, f_params_m = build_company_filter_sql(tenant_id, normalize_company_ids(company_id=company_id, companies=company_ids), column_name="m.company_id")
    params.update(f_params)
    params.update(f_params_m)

    summary = run_query(
        f"""SELECT 
                COALESCE(SUM({amount_col}), 0) AS total_receivables,
                COALESCE(SUM({amount_col}) FILTER (WHERE invoice_date_due < CURRENT_DATE), 0) AS overdue
            FROM fact_account_moves
            WHERE 1=1 {t_sql_def}
              AND move_type = 'out_invoice'
              AND state = 'posted'
              AND payment_state IN ('not_paid', 'partial')
              {f_sql}""",
        params,
    )[0]

    customer_rows = run_query(
        f"""SELECT p.name AS partner_name, COALESCE(SUM({amount_m_col}), 0) AS overdue_amount
            FROM fact_account_moves m
            JOIN dim_partners p ON m.partner_id = p.id AND m.tenant_id = p.tenant_id
            WHERE 1=1 {t_sql_m}
              AND m.move_type = 'out_invoice'
              AND m.state = 'posted'
              AND m.invoice_date_due < CURRENT_DATE
              {f_sql_m}
            GROUP BY p.name
            ORDER BY overdue_amount DESC
            LIMIT :limit""",
        params,
    )

    total = float(summary.get('total_receivables'))
    overdue = float(summary.get('overdue'))
    ratio = calculate_ratio(overdue, total)

    return {
        "tool_name": "get_receivables_analysis_tool",
        "total_receivables": total,
        "overdue_receivables": overdue,
        "overdue_ratio": ratio,
        "risk_level": "High" if ratio >= 0.5 else "Medium" if ratio >= 0.2 else "Low",
        "top_overdue_customers": [
            {"customer": r.get('partner_name'), "overdue_amount": float(r.get('overdue_amount'))}
            for r in customer_rows
        ],
    }


# Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬
# 2. ACCOUNTS PAYABLE
# Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬

def get_payables_analysis_tool(tenant_id: str, company_id: int | None = None, company_ids: list[int] | None = None, limit: int = 10, base_currency: str | None = None, tenant_ids: Optional[list[str]] = None) -> dict:

    t_sql_m, t_params_m = build_tenant_filter_sql(tenant_id, tenant_ids, column_name="m.tenant_id", prefix="t_m")
    t_sql_def, t_params_def = build_tenant_filter_sql(tenant_id, tenant_ids, column_name="tenant_id", prefix="t_def")
    amount_col = build_currency_case_sql('amount_total', tenant_id, base_currency)
    amount_m_col = build_currency_case_sql('m.amount_total', tenant_id, base_currency, 'm.currency_code')
    params = {"tenant_id": tenant_id, "limit": limit}
    params.update(t_params_m)
    params.update(t_params_def)
    f_sql, f_params = build_company_filter_sql(tenant_id, normalize_company_ids(company_id=company_id, companies=company_ids))
    f_sql_m, f_params = build_company_filter_sql(tenant_id, normalize_company_ids(company_id=company_id, companies=company_ids), column_name="m.company_id")
    params.update(f_params)

    summary = run_query(
        f"""SELECT 
                COALESCE(SUM({amount_col}), 0) AS total_payables,
                COALESCE(SUM({amount_col}) FILTER (WHERE invoice_date_due < CURRENT_DATE), 0) AS overdue
            FROM fact_account_moves
            WHERE 1=1 {t_sql_def}
              AND move_type = 'in_invoice'
              AND state = 'posted'
              AND payment_state IN ('not_paid', 'partial')
              {f_sql}""",
        params,
    )[0]

    vendor_rows = run_query(
        f"""SELECT p.name AS partner_name, COALESCE(SUM({amount_m_col}), 0) AS overdue_amount
            FROM fact_account_moves m
            JOIN dim_partners p ON m.partner_id = p.id AND m.tenant_id = p.tenant_id
            WHERE 1=1 {t_sql_m}
              AND m.move_type = 'in_invoice'
              AND m.state = 'posted'
              AND m.invoice_date_due < CURRENT_DATE
              {f_sql_m}
            GROUP BY p.name
            ORDER BY overdue_amount DESC
            LIMIT :limit""",
        params,
    )

    total = float(summary.get('total_payables'))
    overdue = float(summary.get('overdue'))

    return {
        "tool_name": "get_payables_analysis_tool",
        "total_payables": total,
        "overdue_payables": overdue,
        "overdue_ratio": calculate_ratio(overdue, total),
        "top_overdue_vendors": [
            {"vendor": r.get('partner_name'), "overdue_amount": float(r.get('overdue_amount'))}
            for r in vendor_rows
        ],
    }


# Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬
# 12. EXPENSE BREAKDOWN BY CATEGORY
# Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬

def get_expense_breakdown_tool(tenant_id: str, company_id: int | None = None, company_ids: list[int] | None = None, start_date: str | None = None, end_date: str | None = None, limit: int = 20, base_currency: str | None = None, tenant_ids: Optional[list[str]] = None) -> dict:

    t_sql_l, t_params_l = build_tenant_filter_sql(tenant_id, tenant_ids, column_name="l.tenant_id", prefix="t_l")
    balance_col = build_currency_case_sql('l.balance', tenant_id, base_currency, 'l.currency_code')
    params = {"tenant_id": tenant_id, "limit": limit}
    params.update(t_params_l)
    f_sql, f_params = build_company_filter_sql(tenant_id, normalize_company_ids(company_id=company_id, companies=company_ids), column_name="l.company_id")
    params.update(f_params)

    date_sql = ""
    if start_date:
        date_sql += " AND m.date >= :start_date"
        params["start_date"] = start_date
    if end_date:
        date_sql += " AND m.date <= :end_date"
        params["end_date"] = end_date

    rows = run_query(
        f"""SELECT
                l.account_name AS category,
                COALESCE(SUM({balance_col}), 0) AS amount
            FROM fact_account_move_lines l
            JOIN fact_account_moves m ON l.account_move_id = m.id
            WHERE 1=1 {t_sql_l}
              AND m.state = 'posted'
              AND l.account_type IN ('expenses', 'cost_of_goods_sold', 'depreciation')
              {f_sql} {date_sql}
            GROUP BY l.account_name
            ORDER BY amount DESC
            LIMIT :limit""",
        params,
    )

    total = sum(float(r.get('amount')) for r in rows)
    return {
        "tool_name": "get_expense_breakdown_tool",
        "total_expenses": total,
        "categories": [
            {"category": r.get('category'), "amount": float(r.get('amount')), "pct_of_total": round(calculate_ratio(float(r.get('amount')), total) * 100, 1)}
            for r in rows
        ],
    }


# Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬
# 13. TAX LIABILITY ESTIMATION
# Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬

def get_tax_summary_tool(tenant_id: str, company_id: int | None = None, company_ids: list[int] | None = None, base_currency: str | None = None, tenant_ids: Optional[list[str]] = None) -> dict:

    t_sql_def, t_params_def = build_tenant_filter_sql(tenant_id, tenant_ids, column_name="tenant_id", prefix="t_def")
    amount_col = build_currency_case_sql('amount_total', tenant_id, base_currency)
    params = {"tenant_id": tenant_id}
    params.update(t_params_def)
    f_sql, f_params = build_company_filter_sql(tenant_id, normalize_company_ids(company_id=company_id, companies=company_ids))
    params.update(f_params)

    rows = run_query(
        f"""SELECT
                COALESCE(SUM(amount_tax) FILTER (WHERE move_type = 'out_invoice'), 0) AS output_tax,
                COALESCE(SUM(amount_tax) FILTER (WHERE move_type = 'in_invoice'), 0) AS input_tax
            FROM fact_account_moves
            WHERE 1=1 {t_sql_def}
              AND state = 'posted'
              {f_sql}""",
        params,
    )

    row = rows[0] if rows else {}
    output = float(row.get("output_tax") or 0)
    input_tax = float(row.get("input_tax") or 0)
    net = output - input_tax

    return {
        "tool_name": "get_tax_summary_tool",
        "output_tax_collected": output,
        "input_tax_paid": input_tax,
        "net_tax_liability": net,
        "status": "Payable" if net > 0 else "Refundable",
    }


# Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬
# 14. JOURNAL ENTRY ANOMALY DETECTION (Audit)
# Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬

def detect_anomalies_tool(tenant_id: str, company_id: int | None = None, company_ids: list[int] | None = None, limit: int = 15, tenant_ids: Optional[list[str]] = None) -> dict:

    t_sql_m, t_params_m = build_tenant_filter_sql(tenant_id, tenant_ids, column_name="m.tenant_id", prefix="t_m")
    t_sql_l, t_params_l = build_tenant_filter_sql(tenant_id, tenant_ids, column_name="l.tenant_id", prefix="t_l")
    params = {"tenant_id": tenant_id, "limit": limit}
    params.update(t_params_m)
    params.update(t_params_l)
    f_sql, f_params = build_company_filter_sql(tenant_id, normalize_company_ids(company_id=company_id, companies=company_ids), column_name="l.company_id")
    params.update(f_params)

    # 1. Unbalanced journal entries (debit != credit)
    unbalanced = run_query(
        f"""SELECT m.id::text AS move_ref, SUM(l.debit) AS total_debit, SUM(l.credit) AS total_credit,
                ABS(SUM(l.debit) - SUM(l.credit)) AS variance
            FROM fact_account_move_lines l
            JOIN fact_account_moves m ON l.account_move_id = m.id
            WHERE 1=1 {t_sql_l} AND m.state = 'posted' {f_sql}
            GROUP BY m.id
            HAVING ABS(SUM(l.debit) - SUM(l.credit)) > 0.01
            ORDER BY variance DESC
            LIMIT :limit""",
        params,
    )

    # 2. Unusually large transactions (> 3x average)
    outliers = run_query(
        f"""WITH stats AS (
                SELECT AVG(ABS(l.balance)) AS avg_balance, STDDEV(ABS(l.balance)) AS std_balance
                FROM fact_account_move_lines l
                JOIN fact_account_moves m ON l.account_move_id = m.id
                WHERE 1=1 {t_sql_l} AND m.state = 'posted' {f_sql}
            )
            SELECT m.id::text AS move_ref, l.account_name, l.balance, m.date
            FROM fact_account_move_lines l
            JOIN fact_account_moves m ON l.account_move_id = m.id, stats s
            WHERE 1=1 {t_sql_l}
              AND m.state = 'posted'
              AND ABS(l.balance) > (s.avg_balance + 3 * s.std_balance)
              {f_sql}
            ORDER BY ABS(l.balance) DESC
            LIMIT :limit""",
        params,
    )

    # 3. Duplicate invoices (same partner, same amount, same date)
    f_sql_m, f_params_m = build_company_filter_sql(tenant_id, normalize_company_ids(company_id=company_id, companies=company_ids), column_name="m.company_id")
    params.update(f_params_m)
    duplicates = run_query(
        f"""SELECT m.date, p.name AS partner_name, m.amount_total AS amount, COUNT(*) AS occurrences
            FROM fact_account_moves m
            LEFT JOIN dim_partners p ON m.partner_id = p.id AND m.tenant_id = p.tenant_id
            WHERE 1=1 {t_sql_m} AND m.state = 'posted' AND m.move_type IN ('out_invoice', 'in_invoice') {f_sql_m}
            GROUP BY m.date, p.name, m.amount_total
            HAVING COUNT(*) > 1
            LIMIT :limit""",
        params,
    )

    # 4. Round numbers (amount % 1000 = 0)
    round_numbers = run_query(
        f"""SELECT m.odoo_name AS move_ref, m.amount_total, m.date
            FROM fact_account_moves m
            WHERE 1=1 {t_sql_m} AND m.state = 'posted' AND m.amount_total >= 1000 AND MOD(m.amount_total::numeric, 1000) = 0 {f_sql_m}
            LIMIT :limit""",
        params,
    )

    # 5. Weekend postings
    weekend_postings = run_query(
        f"""SELECT m.odoo_name AS move_ref, m.amount_total, m.date
            FROM fact_account_moves m
            WHERE 1=1 {t_sql_m} AND m.state = 'posted' AND EXTRACT(ISODOW FROM m.date) IN (6, 7) {f_sql_m}
            LIMIT :limit""",
        params,
    )

    return {
        "tool_name": "detect_anomalies_tool",
        "unbalanced_entries": [
            {"entry": r.get('move_ref'), "debit": float(r.get('total_debit')), "credit": float(r.get('total_credit')), "variance": float(r.get('variance'))}
            for r in unbalanced
        ],
        "statistical_outliers": [
            {"entry": r.get('move_ref'), "account": r.get('account_name'), "amount": float(r.get('balance')), "date": str(r.get('date'))}
            for r in outliers
        ],
        "duplicate_invoices": [
            {"date": str(r.get('date')), "partner": r.get('partner_name'), "amount": float(r.get('amount')), "occurrences": int(r.get('occurrences'))}
            for r in duplicates
        ],
        "round_number_entries": [
            {"entry": r.get('move_ref'), "amount": float(r.get('amount_total')), "date": str(r.get('date'))}
            for r in round_numbers
        ],
        "weekend_postings": [
            {"entry": r.get('move_ref'), "amount": float(r.get('amount_total')), "date": str(r.get('date'))}
            for r in weekend_postings
        ],
        "risk_level": "High" if len(unbalanced) > 3 or len(outliers) > 5 or duplicates else "Medium" if unbalanced or outliers or round_numbers else "Low",
    }


# Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬
# 15. MULTI-PERIOD COMPARISON (YoY / QoQ)
# Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬

def get_period_comparison_tool(tenant_id: str, company_id: int | None = None, company_ids: list[int] | None = None, granularity: str = "month", base_currency: str | None = None, tenant_ids: Optional[list[str]] = None) -> dict:

    t_sql_def, t_params_def = build_tenant_filter_sql(tenant_id, tenant_ids, column_name="tenant_id", prefix="t_def")
    amount_col = build_currency_case_sql('amount_total', tenant_id, base_currency)
    params = {"tenant_id": tenant_id}
    params.update(t_params_def)
    f_sql, f_params = build_company_filter_sql(tenant_id, normalize_company_ids(company_id=company_id, companies=company_ids))
    params.update(f_params)

    rows = run_query(
        f"""SELECT
                DATE_TRUNC('{granularity}', date_order) AS period,
                COALESCE(SUM(amount_total), 0) AS revenue,
                COUNT(*) AS orders
            FROM fact_sales_orders
            WHERE 1=1 {t_sql_def}
              AND state IN ('sale', 'done')
              {f_sql}
            GROUP BY period
            ORDER BY period DESC
            LIMIT 13""",
        params,
    )

    periods = []
    for i, r in enumerate(rows):
        entry = {
            "period": str(r.get('period')),
            "revenue": float(r.get('revenue')),
            "orders": int(r.get('orders')),
        }
        if i + 1 < len(rows):
            prev = float(rows[i + 1]["revenue"])
            change = float(r.get('revenue')) - prev
            entry["change"] = change
            entry["change_pct"] = round(calculate_ratio(change, prev) * 100, 1)
        periods.append(entry)

    return {
        "tool_name": "get_period_comparison_tool",
        "granularity": granularity,
        "periods": periods,
    }


# Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬
# 3. CASH FLOW HEALTH (Now uses real AP data)
# Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬

def get_cash_flow_health_tool(tenant_id: str, company_id: int | None = None, company_ids: list[int] | None = None, base_currency: str | None = None, tenant_ids: Optional[list[str]] = None) -> dict:
    debit_col = build_currency_case_sql('l.debit', tenant_id, base_currency, 'l.currency_code')
    credit_col = build_currency_case_sql('l.credit', tenant_id, base_currency, 'l.currency_code')
    ar = get_receivables_analysis_tool(tenant_id, company_id=company_id, company_ids=company_ids)
    ap = get_payables_analysis_tool(tenant_id, company_id=company_id, company_ids=company_ids)

    net_position = ar.get('total_receivables') - ap.get('total_payables')
    overdue_exposure = ar.get('overdue_receivables') + ap.get('overdue_payables')

    if net_position > 0 and ar.get('overdue_ratio') < 0.2:
        status = "Healthy"
    elif net_position > 0:
        status = "Stable"
    else:
        status = "Strained"

    return {
        "tool_name": "get_cash_flow_health_tool",
        "accounts_receivable": ar.get('total_receivables'),
        "accounts_payable": ap.get('total_payables'),
        "net_position": net_position,
        "total_overdue_exposure": overdue_exposure,
        "liquidity_status": status,
    }


# Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬
# 4. AR/AP AGING BUCKETS
# Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬

def get_aging_analysis_tool(tenant_id: str, company_id: int | None = None, company_ids: list[int] | None = None, direction: str = "receivable", base_currency: str | None = None, tenant_ids: Optional[list[str]] = None) -> dict:

    t_sql_def, t_params_def = build_tenant_filter_sql(tenant_id, tenant_ids, column_name="tenant_id", prefix="t_def")
    residual_col = build_currency_case_sql('amount_residual', tenant_id, base_currency)
    move_type = "out_invoice" if direction == "receivable" else "in_invoice"
    params = {"tenant_id": tenant_id}
    params.update(t_params_def)
    f_sql, f_params = build_company_filter_sql(tenant_id, normalize_company_ids(company_id=company_id, companies=company_ids))
    params.update(f_params)

    rows = run_query(
        f"""SELECT
                COALESCE(SUM(amount_total) FILTER (WHERE invoice_date_due >= CURRENT_DATE), 0) AS current_bucket,
                COALESCE(SUM(amount_total) FILTER (WHERE CURRENT_DATE - invoice_date_due BETWEEN 1 AND 30), 0) AS bucket_1_30,
                COALESCE(SUM(amount_total) FILTER (WHERE CURRENT_DATE - invoice_date_due BETWEEN 31 AND 60), 0) AS bucket_31_60,
                COALESCE(SUM(amount_total) FILTER (WHERE CURRENT_DATE - invoice_date_due BETWEEN 61 AND 90), 0) AS bucket_61_90,
                COALESCE(SUM(amount_total) FILTER (WHERE CURRENT_DATE - invoice_date_due > 90), 0) AS bucket_90_plus
            FROM fact_account_moves
            WHERE 1=1 {t_sql_def}
              AND move_type = '{move_type}'
              AND state = 'posted'
              AND payment_state IN ('not_paid', 'partial')
              {f_sql}""",
        params,
    )

    row = rows[0] if rows else {}
    return {
        "tool_name": "get_aging_analysis_tool",
        "direction": direction,
        "current": float(row.get("current_bucket", 0)),
        "1_30_days": float(row.get("bucket_1_30", 0)),
        "31_60_days": float(row.get("bucket_31_60", 0)),
        "61_90_days": float(row.get("bucket_61_90", 0)),
        "90_plus_days": float(row.get("bucket_90_plus", 0)),
    }


# Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬
# 5. PROFIT & LOSS
# Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬

def calculate_pnl_tool(tenant_id: str, company_id: int | None = None, company_ids: list[int] | None = None, start_date: str | None = None, end_date: str | None = None, tenant_ids: Optional[list[str]] = None) -> dict:

    t_sql_l, t_params_l = build_tenant_filter_sql(tenant_id, tenant_ids, column_name="l.tenant_id", prefix="t_l")
    params = {"tenant_id": tenant_id}
    params.update(t_params_l)
    f_sql, f_params = build_company_filter_sql(tenant_id, normalize_company_ids(company_id=company_id, companies=company_ids), column_name="l.company_id")
    params.update(f_params)

    date_sql = ""
    if start_date:
        date_sql += " AND m.date >= :start_date"
        params["start_date"] = start_date
    if end_date:
        date_sql += " AND m.date <= :end_date"
        params["end_date"] = end_date

    rows = run_query(
        f"""SELECT 
                SUM(CASE WHEN l.account_type LIKE 'income%' THEN l.balance ELSE 0 END) * -1 AS total_income,
                SUM(CASE WHEN l.account_type LIKE 'expense%' THEN l.balance ELSE 0 END) AS total_expenses,
                SUM(CASE WHEN l.account_type = 'expense_direct_cost' THEN l.balance ELSE 0 END) AS cogs,
                SUM(CASE WHEN l.account_type IN ('expense', 'expense_depreciation') 
                         AND NOT (l.account_code LIKE '64%' OR l.account_code LIKE '67%' OR l.account_code LIKE '69%') 
                         THEN l.balance ELSE 0 END) AS opex
            FROM fact_account_move_lines l
            JOIN fact_account_moves m ON l.account_move_id = m.id
            WHERE 1=1 {t_sql_l} AND m.state = 'posted' {f_sql} {date_sql}""",
        params,
    )

    row = rows[0] if rows else {}
    income = float(row.get("total_income") or 0)
    expenses = float(row.get("total_expenses") or 0)
    cogs = float(row.get("cogs") or 0)
    opex = float(row.get("opex") or 0)
    
    gross = income - cogs
    ebit = gross - opex
    net = income - expenses

    return {
        "tool_name": "calculate_pnl_tool",
        "total_income": income,
        "total_expenses": expenses,
        "cogs": cogs,
        "operating_expenses": opex,
        "gross_profit": gross,
        "ebit": ebit,
        "net_profit": net,
        "gross_margin_pct": round(calculate_ratio(gross, income) * 100, 2),
        "net_margin_pct": round(calculate_ratio(net, income) * 100, 2),
    }


def analyze_profitability_tool(tenant_id: str, company_id: int | None = None, company_ids: list[int] | None = None, tenant_ids: Optional[list[str]] = None) -> dict:
    pnl = calculate_pnl_tool(tenant_id, company_id=company_id, company_ids=company_ids)
    return {
        "tool_name": "analyze_profitability_tool",
        "gross_profit": pnl.get('gross_profit'),
        "net_profit": pnl.get('net_profit'),
        "gross_margin_pct": pnl.get('gross_margin_pct'),
        "net_margin_pct": pnl.get('net_margin_pct'),
        "status": "Healthy" if pnl.get('net_profit') > 0 else "Critical",
    }


# Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬
# 6. BALANCE SHEET
# Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬

def get_balance_sheet_tool(tenant_id: str, company_id: int | None = None, company_ids: list[int] | None = None, as_of_date: str | None = None, base_currency: str | None = None, tenant_ids: Optional[list[str]] = None) -> dict:

    t_sql_l, t_params_l = build_tenant_filter_sql(tenant_id, tenant_ids, column_name="l.tenant_id", prefix="t_l")
    balance_col = build_currency_case_sql('l.balance', tenant_id, base_currency, 'l.currency_code')
    params = {"tenant_id": tenant_id}
    params.update(t_params_l)
    f_sql, f_params = build_company_filter_sql(tenant_id, normalize_company_ids(company_id=company_id, companies=company_ids), column_name="l.company_id")
    params.update(f_params)
    
    date_sql = ""
    if as_of_date:
        date_sql += " AND m.date <= :as_of_date"
        params["as_of_date"] = as_of_date

    rows = run_query(
        f"""SELECT
                COALESCE(SUM({balance_col}) FILTER (WHERE l.account_type IN ('asset_receivable', 'asset_current', 'asset_cash', 'asset_prepayments')), 0) AS current_assets,
                COALESCE(SUM({balance_col}) FILTER (WHERE l.account_type IN ('asset_non_current', 'asset_fixed')), 0) AS non_current_assets,
                COALESCE(SUM({balance_col}) FILTER (WHERE l.account_type IN ('liability_current', 'liability_payable', 'liability_credit_card')), 0) * -1 AS current_liabilities,
                COALESCE(SUM({balance_col}) FILTER (WHERE l.account_type IN ('liability_non_current')), 0) * -1 AS non_current_liabilities,
                COALESCE(SUM({balance_col}) FILTER (WHERE l.account_type IN ('equity', 'equity_unaffected') OR l.account_type LIKE 'income%' OR l.account_type LIKE 'expense%'), 0) * -1 AS total_equity
            FROM fact_account_move_lines l
            JOIN fact_account_moves m ON l.account_move_id = m.id
            WHERE 1=1 {t_sql_l}
              AND m.state = 'posted'
              {f_sql} {date_sql}""",
        params,
    )

    row = rows[0] if rows else {}
    ca = float(row.get("current_assets") or 0)
    nca = float(row.get("non_current_assets") or 0)
    cl = float(row.get("current_liabilities") or 0)
    ncl = float(row.get("non_current_liabilities") or 0)
    eq = float(row.get("total_equity") or 0)

    total_assets = ca + nca
    total_liabilities = cl + ncl
    balance_check = round(total_assets - total_liabilities - eq, 2)

    return {
        "tool_name": "get_balance_sheet_tool",
        "as_of_date": as_of_date or "Current",
        "current_assets": ca,
        "non_current_assets": nca,
        "total_assets": total_assets,
        "current_liabilities": cl,
        "non_current_liabilities": ncl,
        "total_liabilities": total_liabilities,
        "total_equity": eq,
        "integrity_check": "BALANCED" if abs(balance_check) < 0.01 else f"IMBALANCED by {balance_check}",
    }


# Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬
# 7. TRIAL BALANCE
# Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬

def get_trial_balance_tool(tenant_id: str, company_id: int | None = None, company_ids: list[int] | None = None, limit: int = 50, base_currency: str | None = None, tenant_ids: Optional[list[str]] = None) -> dict:

    t_sql_l, t_params_l = build_tenant_filter_sql(tenant_id, tenant_ids, column_name="l.tenant_id", prefix="t_l")
    balance_col = build_currency_case_sql('l.balance', tenant_id, base_currency, 'l.currency_code')
    debit_col = build_currency_case_sql('l.debit', tenant_id, base_currency, 'l.currency_code')
    credit_col = build_currency_case_sql('l.credit', tenant_id, base_currency, 'l.currency_code')
    params = {"tenant_id": tenant_id, "limit": limit}
    params.update(t_params_l)
    f_sql, f_params = build_company_filter_sql(tenant_id, normalize_company_ids(company_id=company_id, companies=company_ids), column_name="l.company_id")
    params.update(f_params)

    rows = run_query(
        f"""SELECT
                l.account_code,
                l.account_name,
                COALESCE(SUM({debit_col}), 0) AS total_debit,
                COALESCE(SUM({credit_col}), 0) AS total_credit,
                COALESCE(SUM({balance_col}), 0) AS balance
            FROM fact_account_move_lines l
            JOIN fact_account_moves m ON l.account_move_id = m.id
            WHERE 1=1 {t_sql_l}
              AND m.state = 'posted'
              {f_sql}
            GROUP BY l.account_code, l.account_name
            ORDER BY l.account_code
            LIMIT :limit""",
        params,
    )

    total_debit = sum(float(r.get("total_debit", 0)) for r in rows)
    total_credit = sum(float(r.get("total_credit", 0)) for r in rows)
    variance = round(total_debit - total_credit, 2)

    return {
        "tool_name": "get_trial_balance_tool",
        "accounts": [
            {
                "code": r.get('account_code'),
                "name": r.get('account_name'),
                "debit": float(r.get('total_debit')),
                "credit": float(r.get('total_credit')),
                "balance": float(r.get('balance')),
            }
            for r in rows
        ],
        "total_debit": total_debit,
        "total_credit": total_credit,
        "variance": variance,
        "integrity_check": "BALANCED" if abs(variance) < 0.01 else f"VARIANCE of {variance}",
    }


# Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬
# 8. FINANCIAL RATIOS DASHBOARD
# Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬

def get_financial_ratios_tool(tenant_id: str, company_id: int | None = None, company_ids: list[int] | None = None, base_currency: str | None = None, tenant_ids: Optional[list[str]] = None) -> dict:
    balance_col = build_currency_case_sql('l.balance', tenant_id, base_currency, 'l.currency_code')
    residual_col = build_currency_case_sql('amount_residual', tenant_id, base_currency)
    amount_col = build_currency_case_sql('amount_total', tenant_id, base_currency)
    bs = get_balance_sheet_tool(tenant_id, company_id=company_id, company_ids=company_ids)
    pnl = calculate_pnl_tool(tenant_id, company_id=company_id, company_ids=company_ids)
    inv_data = get_inventory_efficiency_tool(tenant_id, company_id=company_id, company_ids=company_ids)
    inventory_value = inv_data.get("total_inventory_value", 0)

    current_ratio = calculate_ratio(bs.get('current_assets'), bs.get('current_liabilities'))
    quick_ratio = calculate_ratio(bs.get('current_assets') - inventory_value, bs.get('current_liabilities'))
    debt_to_equity = calculate_ratio(bs.get('total_liabilities'), bs.get('total_equity'))
    roe = calculate_ratio(pnl.get('net_profit'), bs.get('total_equity'))
    roa = calculate_ratio(pnl.get('net_profit'), bs.get('total_assets'))

    return {
        "tool_name": "get_financial_ratios_tool",
        "current_ratio": round(current_ratio, 2),
        "quick_ratio": round(quick_ratio, 2),
        "debt_to_equity": round(debt_to_equity, 2),
        "return_on_equity_pct": round(roe * 100, 2),
        "return_on_assets_pct": round(roa * 100, 2),
        "gross_margin_pct": pnl.get('gross_margin_pct'),
        "net_margin_pct": pnl.get('net_margin_pct'),
        "assessment": _assess_ratios(current_ratio, debt_to_equity),
    }


def _assess_ratios(current_ratio: float, debt_to_equity: float) -> str:
    if current_ratio >= 2.0 and debt_to_equity < 1.0:
        return "Excellent Ã¢â‚¬â€ strong liquidity and conservative leverage"
    elif current_ratio >= 1.0:
        return "Adequate Ã¢â‚¬â€ meets short-term obligations but monitor leverage"
    else:
        return "At Risk Ã¢â‚¬â€ potential liquidity constraints, immediate review advised"


# Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬
# 9. WORKING CAPITAL
# Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬

def get_working_capital_tool(tenant_id: str, company_id: int | None = None, company_ids: list[int] | None = None, base_currency: str | None = None, tenant_ids: Optional[list[str]] = None) -> dict:
    balance_col = build_currency_case_sql('l.balance', tenant_id, base_currency, 'l.currency_code')
    bs = get_balance_sheet_tool(tenant_id, company_id=company_id, company_ids=company_ids)
    wc = bs.get('current_assets') - bs.get('current_liabilities')
    wc_ratio = calculate_ratio(bs.get('current_assets'), bs.get('current_liabilities'))

    return {
        "tool_name": "get_working_capital_tool",
        "current_assets": bs.get('current_assets'),
        "current_liabilities": bs.get('current_liabilities'),
        "working_capital": wc,
        "working_capital_ratio": round(wc_ratio, 2),
        "status": "Positive" if wc > 0 else "Negative Ã¢â‚¬â€ liquidity risk",
    }


# Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬
# 10. BUSINESS HEALTH SCORE (Real weighted scoring)
# Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬

def get_business_health_score_tool(tenant_id: str, company_id: int | None = None, company_ids: list[int] | None = None, base_currency: str | None = None, tenant_ids: Optional[list[str]] = None) -> dict:
    balance_col = build_currency_case_sql('l.balance', tenant_id, base_currency, 'l.currency_code')
    amount_col = build_currency_case_sql('amount_total', tenant_id, base_currency)
    residual_col = build_currency_case_sql('amount_residual', tenant_id, base_currency)
    pnl = calculate_pnl_tool(tenant_id, company_id=company_id, company_ids=company_ids)
    ar = get_receivables_analysis_tool(tenant_id, company_id=company_id, company_ids=company_ids)
    bs = get_balance_sheet_tool(tenant_id, company_id=company_id, company_ids=company_ids)

    # Weighted scoring: Profitability (35%), Liquidity (25%), Leverage (20%), Collections (20%)
    profitability_score = min(35, max(0, pnl.get('net_margin_pct') * 3.5))
    current_ratio = calculate_ratio(bs.get('current_assets'), bs.get('current_liabilities'))
    liquidity_score = min(25, current_ratio * 12.5)
    debt_to_equity = calculate_ratio(bs.get('total_liabilities'), bs.get('total_equity'))
    leverage_score = max(0, 20 - (debt_to_equity * 10))
    collection_score = max(0, 20 - (ar.get('overdue_ratio') * 40))

    total = round(profitability_score + liquidity_score + leverage_score + collection_score, 1)

    return {
        "tool_name": "get_business_health_score_tool",
        "business_health_score": total,
        "health_status": "Excellent" if total > 80 else "Stable" if total > 50 else "At Risk",
        "breakdown": {
            "profitability": round(profitability_score, 1),
            "liquidity": round(liquidity_score, 1),
            "leverage": round(leverage_score, 1),
            "collections": round(collection_score, 1),
        },
    }


# Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬
# 11. CUSTOMER METRICS (Real SQL)
# Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬

def get_customer_metrics_tool(tenant_id: str, company_id: int | None = None, company_ids: list[int] | None = None, limit: int = 10, base_currency: str | None = None, tenant_ids: Optional[list[str]] = None) -> dict:

    t_sql_s, t_params_s = build_tenant_filter_sql(tenant_id, tenant_ids, column_name="s.tenant_id", prefix="t_s")
    amount_col = build_currency_case_sql('s.amount_total', tenant_id, base_currency, 's.currency_code')
    params = {"tenant_id": tenant_id, "limit": limit}
    params.update(t_params_s)
    f_sql, f_params = build_company_filter_sql(tenant_id, normalize_company_ids(company_id=company_id, companies=company_ids), column_name="s.company_id")
    params.update(f_params)

    # Total unique customers and repeat customers
    metrics = run_query(
        f"""SELECT
                COUNT(DISTINCT partner_id) AS total_customers,
                COUNT(DISTINCT partner_id) FILTER (WHERE order_count > 1) AS repeat_customers
            FROM (
                SELECT partner_id, COUNT(*) AS order_count
                FROM fact_sales_orders s
                WHERE 1=1 {t_sql_s} AND s.state IN ('sale', 'done') {f_sql}
                GROUP BY partner_id
            ) sub""",
        params,
    )

    row = metrics[0] if metrics else {}
    total = int(row.get("total_customers") or 0)
    repeat = int(row.get("repeat_customers") or 0)
    retention = calculate_ratio(repeat, total) * 100

    # Top customers by revenue
    top = run_query(
        f"""SELECT p.name AS partner_name, COUNT(*) AS orders, COALESCE(SUM({amount_col}), 0) AS revenue
            FROM fact_sales_orders s
            JOIN dim_partners p ON s.partner_id = p.id AND s.tenant_id = p.tenant_id
            WHERE 1=1 {t_sql_s} AND s.state IN ('sale', 'done') {f_sql}
            GROUP BY p.name
            ORDER BY revenue DESC
            LIMIT :limit""",
        params,
    )

    return {
        "tool_name": "get_customer_metrics_tool",
        "total_customers": total,
        "repeat_customers": repeat,
        "retention_rate_pct": round(retention, 1),
        "churn_risk": "Low" if retention > 60 else "Medium" if retention > 30 else "High",
        "top_customers": [
            {"name": r.get('partner_name'), "orders": int(r.get('orders')), "revenue": float(r.get('revenue'))}
            for r in top
        ],
    }


