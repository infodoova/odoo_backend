# api/agent/tools_refactored/finance.py

from .common import run_query, normalize_company_ids, build_company_filter_sql, calculate_ratio
from .sales import get_sales_summary_tool
from .inventory import get_inventory_efficiency_tool


# ──────────────────────────────────────────────
# 1. ACCOUNTS RECEIVABLE
# ──────────────────────────────────────────────

def get_receivables_analysis_tool(tenant_id: str, company_id: int | None = None, limit: int = 10) -> dict:
    params = {"tenant_id": tenant_id, "limit": limit}
    f_sql, f_params = build_company_filter_sql(tenant_id, company_id)
    f_sql_m, f_params_m = build_company_filter_sql(tenant_id, company_id, column_name="m.company_id")
    params.update(f_params)
    params.update(f_params_m)

    summary = run_query(
        f"""SELECT 
                COALESCE(SUM(amount_total), 0) AS total_receivables,
                COALESCE(SUM(amount_total) FILTER (WHERE invoice_date_due < CURRENT_DATE), 0) AS overdue
            FROM fact_account_moves
            WHERE tenant_id = :tenant_id
              AND move_type = 'out_invoice'
              AND state = 'posted'
              AND payment_state IN ('not_paid', 'partial')
              {f_sql}""",
        params,
    )[0]

    customer_rows = run_query(
        f"""SELECT p.name AS partner_name, COALESCE(SUM(m.amount_total), 0) AS overdue_amount
            FROM fact_account_moves m
            JOIN dim_partners p ON m.partner_id = p.odoo_id AND m.tenant_id = p.tenant_id
            WHERE m.tenant_id = :tenant_id
              AND m.move_type = 'out_invoice'
              AND m.state = 'posted'
              AND m.invoice_date_due < CURRENT_DATE
              {f_sql_m}
            GROUP BY p.name
            ORDER BY overdue_amount DESC
            LIMIT :limit""",
        params,
    )

    total = float(summary["total_receivables"])
    overdue = float(summary["overdue"])
    ratio = calculate_ratio(overdue, total)

    return {
        "tool_name": "get_receivables_analysis_tool",
        "total_receivables": total,
        "overdue_receivables": overdue,
        "overdue_ratio": ratio,
        "risk_level": "High" if ratio >= 0.5 else "Medium" if ratio >= 0.2 else "Low",
        "top_overdue_customers": [
            {"customer": r["partner_name"], "overdue_amount": float(r["overdue_amount"])}
            for r in customer_rows
        ],
    }


# ──────────────────────────────────────────────
# 2. ACCOUNTS PAYABLE
# ──────────────────────────────────────────────

def get_payables_analysis_tool(tenant_id: str, company_id: int | None = None, limit: int = 10) -> dict:
    params = {"tenant_id": tenant_id, "limit": limit}
    f_sql, f_params = build_company_filter_sql(tenant_id, company_id)
    f_sql_m, f_params = build_company_filter_sql(tenant_id, company_id, column_name="m.company_id")
    params.update(f_params)

    summary = run_query(
        f"""SELECT 
                COALESCE(SUM(amount_total), 0) AS total_payables,
                COALESCE(SUM(amount_total) FILTER (WHERE invoice_date_due < CURRENT_DATE), 0) AS overdue
            FROM fact_account_moves
            WHERE tenant_id = :tenant_id
              AND move_type = 'in_invoice'
              AND state = 'posted'
              AND payment_state IN ('not_paid', 'partial')
              {f_sql}""",
        params,
    )[0]

    vendor_rows = run_query(
        f"""SELECT p.name AS partner_name, COALESCE(SUM(m.amount_total), 0) AS overdue_amount
            FROM fact_account_moves m
            JOIN dim_partners p ON m.partner_id = p.odoo_id AND m.tenant_id = p.tenant_id
            WHERE m.tenant_id = :tenant_id
              AND m.move_type = 'in_invoice'
              AND m.state = 'posted'
              AND m.invoice_date_due < CURRENT_DATE
              {f_sql_m}
            GROUP BY p.name
            ORDER BY overdue_amount DESC
            LIMIT :limit""",
        params,
    )

    total = float(summary["total_payables"])
    overdue = float(summary["overdue"])

    return {
        "tool_name": "get_payables_analysis_tool",
        "total_payables": total,
        "overdue_payables": overdue,
        "overdue_ratio": calculate_ratio(overdue, total),
        "top_overdue_vendors": [
            {"vendor": r["partner_name"], "overdue_amount": float(r["overdue_amount"])}
            for r in vendor_rows
        ],
    }


# ──────────────────────────────────────────────
# 12. EXPENSE BREAKDOWN BY CATEGORY
# ──────────────────────────────────────────────

def get_expense_breakdown_tool(tenant_id: str, company_id: int | None = None, start_date: str | None = None, end_date: str | None = None, limit: int = 20) -> dict:
    params = {"tenant_id": tenant_id, "limit": limit}
    f_sql, f_params = build_company_filter_sql(tenant_id, company_id, column_name="l.company_id")
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
                COALESCE(SUM(l.balance), 0) AS amount
            FROM fact_account_move_lines l
            JOIN fact_account_moves m ON l.account_move_id = m.id
            WHERE l.tenant_id = :tenant_id
              AND m.state = 'posted'
              AND l.account_type IN ('expenses', 'cost_of_goods_sold', 'depreciation')
              {f_sql} {date_sql}
            GROUP BY l.account_name
            ORDER BY amount DESC
            LIMIT :limit""",
        params,
    )

    total = sum(float(r["amount"]) for r in rows)
    return {
        "tool_name": "get_expense_breakdown_tool",
        "total_expenses": total,
        "categories": [
            {"category": r["category"], "amount": float(r["amount"]), "pct_of_total": round(calculate_ratio(float(r["amount"]), total) * 100, 1)}
            for r in rows
        ],
    }


# ──────────────────────────────────────────────
# 13. TAX LIABILITY ESTIMATION
# ──────────────────────────────────────────────

def get_tax_summary_tool(tenant_id: str, company_id: int | None = None) -> dict:
    params = {"tenant_id": tenant_id}
    f_sql, f_params = build_company_filter_sql(tenant_id, company_id)
    params.update(f_params)

    rows = run_query(
        f"""SELECT
                COALESCE(SUM(amount_tax), 0) FILTER (WHERE move_type = 'out_invoice') AS output_tax,
                COALESCE(SUM(amount_tax), 0) FILTER (WHERE move_type = 'in_invoice') AS input_tax
            FROM fact_account_moves
            WHERE tenant_id = :tenant_id
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


# ──────────────────────────────────────────────
# 14. JOURNAL ENTRY ANOMALY DETECTION (Audit)
# ──────────────────────────────────────────────

def detect_anomalies_tool(tenant_id: str, company_id: int | None = None, limit: int = 15) -> dict:
    params = {"tenant_id": tenant_id, "limit": limit}
    f_sql, f_params = build_company_filter_sql(tenant_id, company_id, column_name="l.company_id")
    params.update(f_params)

    # 1. Unbalanced journal entries (debit != credit)
    unbalanced = run_query(
        f"""SELECT m.id::text AS move_ref, SUM(l.debit) AS total_debit, SUM(l.credit) AS total_credit,
                ABS(SUM(l.debit) - SUM(l.credit)) AS variance
            FROM fact_account_move_lines l
            JOIN fact_account_moves m ON l.account_move_id = m.id
            WHERE l.tenant_id = :tenant_id AND m.state = 'posted' {f_sql}
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
                WHERE l.tenant_id = :tenant_id AND m.state = 'posted' {f_sql}
            )
            SELECT m.id::text AS move_ref, l.account_name, l.balance, m.date
            FROM fact_account_move_lines l
            JOIN fact_account_moves m ON l.account_move_id = m.id, stats s
            WHERE l.tenant_id = :tenant_id
              AND m.state = 'posted'
              AND ABS(l.balance) > (s.avg_balance + 3 * s.std_balance)
              {f_sql}
            ORDER BY ABS(l.balance) DESC
            LIMIT :limit""",
        params,
    )

    return {
        "tool_name": "detect_anomalies_tool",
        "unbalanced_entries": [
            {"entry": r["move_ref"], "debit": float(r["total_debit"]), "credit": float(r["total_credit"]), "variance": float(r["variance"])}
            for r in unbalanced
        ],
        "statistical_outliers": [
            {"entry": r["move_ref"], "account": r["account_name"], "amount": float(r["balance"]), "date": str(r["date"])}
            for r in outliers
        ],
        "risk_level": "High" if len(unbalanced) > 3 or len(outliers) > 5 else "Medium" if unbalanced or outliers else "Low",
    }


# ──────────────────────────────────────────────
# 15. MULTI-PERIOD COMPARISON (YoY / QoQ)
# ──────────────────────────────────────────────

def get_period_comparison_tool(tenant_id: str, company_id: int | None = None, granularity: str = "month") -> dict:
    params = {"tenant_id": tenant_id}
    f_sql, f_params = build_company_filter_sql(tenant_id, company_id)
    params.update(f_params)

    rows = run_query(
        f"""SELECT
                DATE_TRUNC('{granularity}', date_order) AS period,
                COALESCE(SUM(amount_total), 0) AS revenue,
                COUNT(*) AS orders
            FROM fact_sales_orders
            WHERE tenant_id = :tenant_id
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
            "period": str(r["period"]),
            "revenue": float(r["revenue"]),
            "orders": int(r["orders"]),
        }
        if i + 1 < len(rows):
            prev = float(rows[i + 1]["revenue"])
            change = float(r["revenue"]) - prev
            entry["change"] = change
            entry["change_pct"] = round(calculate_ratio(change, prev) * 100, 1)
        periods.append(entry)

    return {
        "tool_name": "get_period_comparison_tool",
        "granularity": granularity,
        "periods": periods,
    }


# ──────────────────────────────────────────────
# 3. CASH FLOW HEALTH (Now uses real AP data)
# ──────────────────────────────────────────────

def get_cash_flow_health_tool(tenant_id: str, company_id: int | None = None) -> dict:
    ar = get_receivables_analysis_tool(tenant_id, company_id)
    ap = get_payables_analysis_tool(tenant_id, company_id)

    net_position = ar["total_receivables"] - ap["total_payables"]
    overdue_exposure = ar["overdue_receivables"] + ap["overdue_payables"]

    if net_position > 0 and ar["overdue_ratio"] < 0.2:
        status = "Healthy"
    elif net_position > 0:
        status = "Stable"
    else:
        status = "Strained"

    return {
        "tool_name": "get_cash_flow_health_tool",
        "accounts_receivable": ar["total_receivables"],
        "accounts_payable": ap["total_payables"],
        "net_position": net_position,
        "total_overdue_exposure": overdue_exposure,
        "liquidity_status": status,
    }


# ──────────────────────────────────────────────
# 4. AR/AP AGING BUCKETS
# ──────────────────────────────────────────────

def get_aging_analysis_tool(tenant_id: str, company_id: int | None = None, direction: str = "receivable") -> dict:
    move_type = "out_invoice" if direction == "receivable" else "in_invoice"
    params = {"tenant_id": tenant_id}
    f_sql, f_params = build_company_filter_sql(tenant_id, company_id)
    params.update(f_params)

    rows = run_query(
        f"""SELECT
                COALESCE(SUM(amount_total) FILTER (WHERE invoice_date_due >= CURRENT_DATE), 0) AS current_bucket,
                COALESCE(SUM(amount_total) FILTER (WHERE CURRENT_DATE - invoice_date_due BETWEEN 1 AND 30), 0) AS bucket_1_30,
                COALESCE(SUM(amount_total) FILTER (WHERE CURRENT_DATE - invoice_date_due BETWEEN 31 AND 60), 0) AS bucket_31_60,
                COALESCE(SUM(amount_total) FILTER (WHERE CURRENT_DATE - invoice_date_due BETWEEN 61 AND 90), 0) AS bucket_61_90,
                COALESCE(SUM(amount_total) FILTER (WHERE CURRENT_DATE - invoice_date_due > 90), 0) AS bucket_90_plus
            FROM fact_account_moves
            WHERE tenant_id = :tenant_id
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


# ──────────────────────────────────────────────
# 5. PROFIT & LOSS
# ──────────────────────────────────────────────

def calculate_pnl_tool(tenant_id: str, company_id: int | None = None, start_date: str | None = None, end_date: str | None = None) -> dict:
    params = {"tenant_id": tenant_id}
    f_sql, f_params = build_company_filter_sql(tenant_id, company_id, column_name="l.company_id")
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
                SUM(CASE WHEN l.account_type IN ('income', 'other_income') THEN l.balance ELSE 0 END) * -1 AS total_income,
                SUM(CASE WHEN l.account_type IN ('expenses', 'cost_of_goods_sold', 'depreciation') THEN l.balance ELSE 0 END) AS total_expenses,
                SUM(CASE WHEN l.account_type = 'cost_of_goods_sold' THEN l.balance ELSE 0 END) AS cogs
            FROM fact_account_move_lines l
            JOIN fact_account_moves m ON l.account_move_id = m.id
            WHERE l.tenant_id = :tenant_id AND m.state = 'posted' {f_sql} {date_sql}""",
        params,
    )

    row = rows[0] if rows else {}
    income = float(row.get("total_income") or 0)
    expenses = float(row.get("total_expenses") or 0)
    cogs = float(row.get("cogs") or 0)
    gross = income - cogs
    net = income - expenses

    return {
        "tool_name": "calculate_pnl_tool",
        "total_income": income,
        "total_expenses": expenses,
        "cogs": cogs,
        "gross_profit": gross,
        "net_profit": net,
        "gross_margin_pct": round(calculate_ratio(gross, income) * 100, 2),
        "net_margin_pct": round(calculate_ratio(net, income) * 100, 2),
    }


def analyze_profitability_tool(tenant_id: str, company_id: int | None = None) -> dict:
    pnl = calculate_pnl_tool(tenant_id, company_id)
    return {
        "tool_name": "analyze_profitability_tool",
        "gross_profit": pnl["gross_profit"],
        "net_profit": pnl["net_profit"],
        "gross_margin_pct": pnl["gross_margin_pct"],
        "net_margin_pct": pnl["net_margin_pct"],
        "status": "Healthy" if pnl["net_profit"] > 0 else "Critical",
    }


# ──────────────────────────────────────────────
# 6. BALANCE SHEET
# ──────────────────────────────────────────────

def get_balance_sheet_tool(tenant_id: str, company_id: int | None = None) -> dict:
    params = {"tenant_id": tenant_id}
    f_sql, f_params = build_company_filter_sql(tenant_id, company_id, column_name="l.company_id")
    params.update(f_params)

    rows = run_query(
        f"""SELECT
                COALESCE(SUM(l.balance) FILTER (WHERE l.account_type IN ('asset_receivable', 'asset_current', 'bank_and_cash')), 0) AS current_assets,
                COALESCE(SUM(l.balance) FILTER (WHERE l.account_type IN ('asset_non_current', 'asset_fixed')), 0) AS non_current_assets,
                COALESCE(SUM(l.balance) FILTER (WHERE l.account_type IN ('liability_current', 'liability_payable')), 0) * -1 AS current_liabilities,
                COALESCE(SUM(l.balance) FILTER (WHERE l.account_type IN ('liability_non_current')), 0) * -1 AS non_current_liabilities,
                COALESCE(SUM(l.balance) FILTER (WHERE l.account_type IN ('equity', 'equity_unaffected')), 0) * -1 AS total_equity
            FROM fact_account_move_lines l
            JOIN fact_account_moves m ON l.account_move_id = m.id
            WHERE l.tenant_id = :tenant_id
              AND m.state = 'posted'
              {f_sql}""",
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
        "current_assets": ca,
        "non_current_assets": nca,
        "total_assets": total_assets,
        "current_liabilities": cl,
        "non_current_liabilities": ncl,
        "total_liabilities": total_liabilities,
        "total_equity": eq,
        "integrity_check": "BALANCED" if abs(balance_check) < 0.01 else f"IMBALANCED by {balance_check}",
    }


# ──────────────────────────────────────────────
# 7. TRIAL BALANCE
# ──────────────────────────────────────────────

def get_trial_balance_tool(tenant_id: str, company_id: int | None = None, limit: int = 50) -> dict:
    params = {"tenant_id": tenant_id, "limit": limit}
    f_sql, f_params = build_company_filter_sql(tenant_id, company_id, column_name="l.company_id")
    params.update(f_params)

    rows = run_query(
        f"""SELECT
                l.account_code,
                l.account_name,
                COALESCE(SUM(l.debit), 0) AS total_debit,
                COALESCE(SUM(l.credit), 0) AS total_credit,
                COALESCE(SUM(l.balance), 0) AS balance
            FROM fact_account_move_lines l
            JOIN fact_account_moves m ON l.account_move_id = m.id
            WHERE l.tenant_id = :tenant_id
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
                "code": r["account_code"],
                "name": r["account_name"],
                "debit": float(r["total_debit"]),
                "credit": float(r["total_credit"]),
                "balance": float(r["balance"]),
            }
            for r in rows
        ],
        "total_debit": total_debit,
        "total_credit": total_credit,
        "variance": variance,
        "integrity_check": "BALANCED" if abs(variance) < 0.01 else f"VARIANCE of {variance}",
    }


# ──────────────────────────────────────────────
# 8. FINANCIAL RATIOS DASHBOARD
# ──────────────────────────────────────────────

def get_financial_ratios_tool(tenant_id: str, company_id: int | None = None) -> dict:
    bs = get_balance_sheet_tool(tenant_id, company_id)
    pnl = calculate_pnl_tool(tenant_id, company_id)

    current_ratio = calculate_ratio(bs["current_assets"], bs["current_liabilities"])
    # Quick ratio approximation: current assets minus inventory value
    quick_ratio = calculate_ratio(bs["current_assets"] * 0.8, bs["current_liabilities"])
    debt_to_equity = calculate_ratio(bs["total_liabilities"], bs["total_equity"])
    roe = calculate_ratio(pnl["net_profit"], bs["total_equity"])
    roa = calculate_ratio(pnl["net_profit"], bs["total_assets"])

    return {
        "tool_name": "get_financial_ratios_tool",
        "current_ratio": round(current_ratio, 2),
        "quick_ratio": round(quick_ratio, 2),
        "debt_to_equity": round(debt_to_equity, 2),
        "return_on_equity_pct": round(roe * 100, 2),
        "return_on_assets_pct": round(roa * 100, 2),
        "gross_margin_pct": pnl["gross_margin_pct"],
        "net_margin_pct": pnl["net_margin_pct"],
        "assessment": _assess_ratios(current_ratio, debt_to_equity),
    }


def _assess_ratios(current_ratio: float, debt_to_equity: float) -> str:
    if current_ratio >= 2.0 and debt_to_equity < 1.0:
        return "Excellent — strong liquidity and conservative leverage"
    elif current_ratio >= 1.0:
        return "Adequate — meets short-term obligations but monitor leverage"
    else:
        return "At Risk — potential liquidity constraints, immediate review advised"


# ──────────────────────────────────────────────
# 9. WORKING CAPITAL
# ──────────────────────────────────────────────

def get_working_capital_tool(tenant_id: str, company_id: int | None = None) -> dict:
    bs = get_balance_sheet_tool(tenant_id, company_id)
    wc = bs["current_assets"] - bs["current_liabilities"]
    wc_ratio = calculate_ratio(bs["current_assets"], bs["current_liabilities"])

    return {
        "tool_name": "get_working_capital_tool",
        "current_assets": bs["current_assets"],
        "current_liabilities": bs["current_liabilities"],
        "working_capital": wc,
        "working_capital_ratio": round(wc_ratio, 2),
        "status": "Positive" if wc > 0 else "Negative — liquidity risk",
    }


# ──────────────────────────────────────────────
# 10. BUSINESS HEALTH SCORE (Real weighted scoring)
# ──────────────────────────────────────────────

def get_business_health_score_tool(tenant_id: str, company_id: int | None = None) -> dict:
    pnl = calculate_pnl_tool(tenant_id, company_id)
    ar = get_receivables_analysis_tool(tenant_id, company_id)
    bs = get_balance_sheet_tool(tenant_id, company_id)

    # Weighted scoring: Profitability (35%), Liquidity (25%), Leverage (20%), Collections (20%)
    profitability_score = min(35, max(0, pnl["net_margin_pct"] * 3.5))
    current_ratio = calculate_ratio(bs["current_assets"], bs["current_liabilities"])
    liquidity_score = min(25, current_ratio * 12.5)
    debt_to_equity = calculate_ratio(bs["total_liabilities"], bs["total_equity"])
    leverage_score = max(0, 20 - (debt_to_equity * 10))
    collection_score = max(0, 20 - (ar["overdue_ratio"] * 40))

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


# ──────────────────────────────────────────────
# 11. CUSTOMER METRICS (Real SQL)
# ──────────────────────────────────────────────

def get_customer_metrics_tool(tenant_id: str, company_id: int | None = None, limit: int = 10) -> dict:
    params = {"tenant_id": tenant_id, "limit": limit}
    f_sql, f_params = build_company_filter_sql(tenant_id, company_id, column_name="s.company_id")
    params.update(f_params)

    # Total unique customers and repeat customers
    metrics = run_query(
        f"""SELECT
                COUNT(DISTINCT partner_id) AS total_customers,
                COUNT(DISTINCT partner_id) FILTER (WHERE order_count > 1) AS repeat_customers
            FROM (
                SELECT partner_id, COUNT(*) AS order_count
                FROM fact_sales_orders s
                WHERE s.tenant_id = :tenant_id AND s.state IN ('sale', 'done') {f_sql}
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
        f"""SELECT p.name AS partner_name, COUNT(*) AS orders, COALESCE(SUM(s.amount_total), 0) AS revenue
            FROM fact_sales_orders s
            JOIN dim_partners p ON s.partner_id = p.odoo_id AND s.tenant_id = p.tenant_id
            WHERE s.tenant_id = :tenant_id AND s.state IN ('sale', 'done') {f_sql}
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
            {"name": r["partner_name"], "orders": int(r["orders"]), "revenue": float(r["revenue"])}
            for r in top
        ],
    }
