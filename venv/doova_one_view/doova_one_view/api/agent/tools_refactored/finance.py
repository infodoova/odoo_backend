from typing import Optional
# api/agent/tools_refactored/finance.py

import uuid
from ..query_context import (
    normalize_tenant_ids,
    normalize_company_ids,
    build_tenant_filter_sql,
    build_company_filter_sql,
)
from .common import (
    run_query,
    calculate_ratio,
    build_currency_case_sql,
    get_multi_currency_conversions,
)
from .sales import get_sales_summary_tool
from .inventory import get_inventory_efficiency_tool
import uuid


def _safe_uuids(ids: list) -> list[str]:
    res = []
    for x in ids:
        try:
            uuid.UUID(str(x))
            res.append(str(x))
        except Exception:
            pass
    return res


# Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬
# 1. ACCOUNTS RECEIVABLE
# Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬

def get_receivables_analysis_tool(tenant_ids: Optional[list[str]] = None, company_ids: Optional[list[int]] = None, limit: int = 10, base_currency: str | None = None) -> dict:

    t_sql_m, t_params_m = build_tenant_filter_sql(tenant_ids=tenant_ids, column_name="m.tenant_id", prefix="t_m")
    t_sql_def, t_params_def = build_tenant_filter_sql(tenant_ids=tenant_ids, column_name="tenant_id", prefix="t_def")
    amount_col = build_currency_case_sql('amount_residual', tenant_ids=tenant_ids, base_currency=base_currency)
    amount_m_col = build_currency_case_sql('m.amount_residual', tenant_ids=tenant_ids, base_currency=base_currency, currency_column='m.currency_code')
    params = {"limit": limit}
    params.update(t_params_m)
    params.update(t_params_def)
    f_sql, f_params = build_company_filter_sql(company_ids=company_ids)
    f_sql_m, f_params_m = build_company_filter_sql(company_ids=company_ids, column_name="m.company_id")
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
              AND m.payment_state IN ('not_paid', 'partial')
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

    def _safe_uuids(ids: list) -> list[str]:
        import uuid
        res = []
        for x in ids:
            try:
                uuid.UUID(str(x))
                res.append(str(x))
            except Exception:
                pass
        return res

    t_ids = normalize_tenant_ids(tenant_ids=tenant_ids)
    valid_t_uuids = _safe_uuids(t_ids)
    c_ids = normalize_company_ids(company_ids=company_ids)
    from odoo_app.models import AccountPartialReconcile
    aging = {}
    if valid_t_uuids and AccountPartialReconcile.objects.filter(tenant_id__in=valid_t_uuids).exists():
        from django.db import connection
        t_filter = "AND l.tenant_id IN %s"
        t_params = [tuple(str(t) for t in valid_t_uuids)]
        c_filter = "AND l.company_id IN %s" if c_ids else ""
        c_params = [tuple(int(c) for c in c_ids)] if c_filter else []
        
        sql = f"""
            WITH line_recon AS (
                SELECT
                    l.id AS line_id,
                    m.date AS move_date,
                    l.debit,
                    l.credit,
                    COALESCE(SUM(pr_deb.amount), 0) AS reconciled_debit,
                    COALESCE(SUM(pr_cred.amount), 0) AS reconciled_credit
                FROM fact_account_move_lines l
                JOIN fact_account_moves m ON l.account_move_id = m.id
                LEFT JOIN fact_account_partial_reconciles pr_deb 
                    ON pr_deb.debit_move_line_id = l.id AND pr_deb.max_date <= CURRENT_DATE
                LEFT JOIN fact_account_partial_reconciles pr_cred 
                    ON pr_cred.credit_move_line_id = l.id AND pr_cred.max_date <= CURRENT_DATE
                WHERE m.state = 'posted'
                  AND l.account_type = 'asset_receivable'
                  AND m.date <= CURRENT_DATE
                  {t_filter}
                  {c_filter}
                GROUP BY l.id, m.date, l.debit, l.credit
            ),
            line_residual AS (
                SELECT
                    line_id,
                    move_date,
                    (CURRENT_DATE - move_date) AS days,
                    CASE WHEN debit > 0 THEN debit - reconciled_debit ELSE -(credit - reconciled_credit) END AS residual
                FROM line_recon
            )
            SELECT
                COALESCE(SUM(CASE WHEN days <= 0 THEN residual ELSE 0 END), 0) AS at_date,
                COALESCE(SUM(CASE WHEN days BETWEEN 1 AND 30 THEN residual ELSE 0 END), 0) AS b_1_30,
                COALESCE(SUM(CASE WHEN days BETWEEN 31 AND 60 THEN residual ELSE 0 END), 0) AS b_31_60,
                COALESCE(SUM(CASE WHEN days BETWEEN 61 AND 90 THEN residual ELSE 0 END), 0) AS b_61_90,
                COALESCE(SUM(CASE WHEN days BETWEEN 91 AND 120 THEN residual ELSE 0 END), 0) AS b_91_120,
                COALESCE(SUM(CASE WHEN days >= 121 THEN residual ELSE 0 END), 0) AS b_older,
                COALESCE(SUM(residual), 0) AS total
            FROM line_residual
        """
        with connection.cursor() as cursor:
            cursor.execute(sql, t_params + c_params)
            r = cursor.fetchone()
            aging = {
                "at_date": float(r[0] or 0),
                "1-30 days": float(r[1] or 0),
                "31-60 days": float(r[2] or 0),
                "61-90 days": float(r[3] or 0),
                "91-120 days": float(r[4] or 0),
                "older": float(r[5] or 0),
            }
            gl_total = float(r[6] or 0)
            if gl_total > 0:
                total = gl_total

    aging_buckets = {
        "current": float(aging.get("at_date", 0) or 0),
        "1-30": float(aging.get("1-30 days", 0) or 0),
        "31-60": float(aging.get("31-60 days", 0) or 0),
        "61-90": float(aging.get("61-90 days", 0) or 0),
        "90+": float(aging.get("91-120 days", 0) or 0) + float(aging.get("older", 0) or 0),
    }

    return {
        "tool_name": "get_receivables_analysis_tool",
        "total_receivables": total,
        "overdue_receivables": overdue,
        "overdue_ratio": ratio,
        "risk_level": "High" if ratio >= 0.5 else "Medium" if ratio >= 0.2 else "Low",
        "aging": aging,
        "aging_buckets": aging_buckets,
        "top_overdue_customers": [
            {"customer": r.get('partner_name'), "overdue_amount": float(r.get('overdue_amount'))}
            for r in customer_rows
        ],
    }


# ────────────────────────────────────────────────────────────────────────────────
# 2. ACCOUNTS PAYABLE
# ────────────────────────────────────────────────────────────────────────────────

def get_payables_analysis_tool(tenant_ids: Optional[list[str]] = None, company_ids: Optional[list[int]] = None, limit: int = 10, base_currency: str | None = None) -> dict:

    t_sql_m, t_params_m = build_tenant_filter_sql(tenant_ids=tenant_ids, column_name="m.tenant_id", prefix="t_m")
    t_sql_def, t_params_def = build_tenant_filter_sql(tenant_ids=tenant_ids, column_name="tenant_id", prefix="t_def")
    amount_col = build_currency_case_sql('amount_total', tenant_ids=tenant_ids, base_currency=base_currency)
    amount_m_col = build_currency_case_sql('m.amount_total', tenant_ids=tenant_ids, base_currency=base_currency, currency_column='m.currency_code')
    params = {"limit": limit}
    params.update(t_params_m)
    params.update(t_params_def)
    f_sql, f_params = build_company_filter_sql(company_ids=company_ids)
    f_sql_m, f_params = build_company_filter_sql(company_ids=company_ids, column_name="m.company_id")
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

    t_ids = normalize_tenant_ids(tenant_ids=tenant_ids)
    valid_t_uuids = _safe_uuids(t_ids)
    c_ids = normalize_company_ids(company_ids=company_ids)
    from odoo_app.models import AccountPartialReconcile
    aging = {}
    if valid_t_uuids and AccountPartialReconcile.objects.filter(tenant_id__in=valid_t_uuids).exists():
        from django.db import connection
        t_filter = "AND l.tenant_id IN %s"
        t_params = [tuple(str(t) for t in valid_t_uuids)]
        c_filter = "AND l.company_id IN %s" if c_ids else ""
        c_params = [tuple(int(c) for c in c_ids)] if c_filter else []
        
        sql = f"""
            WITH line_recon AS (
                SELECT
                    l.id AS line_id,
                    m.date AS move_date,
                    l.debit,
                    l.credit,
                    COALESCE(SUM(pr_deb.amount), 0) AS reconciled_debit,
                    COALESCE(SUM(pr_cred.amount), 0) AS reconciled_credit
                FROM fact_account_move_lines l
                JOIN fact_account_moves m ON l.account_move_id = m.id
                LEFT JOIN fact_account_partial_reconciles pr_deb 
                    ON pr_deb.debit_move_line_id = l.id AND pr_deb.max_date <= CURRENT_DATE
                LEFT JOIN fact_account_partial_reconciles pr_cred 
                    ON pr_cred.credit_move_line_id = l.id AND pr_cred.max_date <= CURRENT_DATE
                WHERE m.state = 'posted'
                  AND l.account_type = 'liability_payable'
                  AND m.date <= CURRENT_DATE
                  {t_filter}
                  {c_filter}
                GROUP BY l.id, m.date, l.debit, l.credit
            ),
            line_residual AS (
                SELECT
                    line_id,
                    move_date,
                    (CURRENT_DATE - move_date) AS days,
                    CASE WHEN credit > 0 THEN credit - reconciled_credit ELSE -(debit - reconciled_debit) END AS residual
                FROM line_recon
            )
            SELECT
                COALESCE(SUM(CASE WHEN days <= 0 THEN residual ELSE 0 END), 0) AS at_date,
                COALESCE(SUM(CASE WHEN days BETWEEN 1 AND 30 THEN residual ELSE 0 END), 0) AS b_1_30,
                COALESCE(SUM(CASE WHEN days BETWEEN 31 AND 60 THEN residual ELSE 0 END), 0) AS b_31_60,
                COALESCE(SUM(CASE WHEN days BETWEEN 61 AND 90 THEN residual ELSE 0 END), 0) AS b_61_90,
                COALESCE(SUM(CASE WHEN days BETWEEN 91 AND 120 THEN residual ELSE 0 END), 0) AS b_91_120,
                COALESCE(SUM(CASE WHEN days >= 121 THEN residual ELSE 0 END), 0) AS b_older,
                COALESCE(SUM(residual), 0) AS total
            FROM line_residual
        """
        with connection.cursor() as cursor:
            cursor.execute(sql, t_params + c_params)
            r = cursor.fetchone()
            aging = {
                "at_date": float(r[0] or 0),
                "1-30 days": float(r[1] or 0),
                "31-60 days": float(r[2] or 0),
                "61-90 days": float(r[3] or 0),
                "91-120 days": float(r[4] or 0),
                "older": float(r[5] or 0),
            }
            gl_total = float(r[6] or 0)
            if gl_total > 0:
                total = gl_total

    aging_buckets = {
        "current": float(aging.get("at_date", 0) or 0),
        "1-30": float(aging.get("1-30 days", 0) or 0),
        "31-60": float(aging.get("31-60 days", 0) or 0),
        "61-90": float(aging.get("61-90 days", 0) or 0),
        "90+": float(aging.get("91-120 days", 0) or 0) + float(aging.get("older", 0) or 0),
    }

    return {
        "tool_name": "get_payables_analysis_tool",
        "total_payables": total,
        "overdue_payables": overdue,
        "overdue_ratio": calculate_ratio(overdue, total),
        "aging": aging,
        "aging_buckets": aging_buckets,
        "top_overdue_vendors": [
            {"vendor": r.get('partner_name'), "overdue_amount": float(r.get('overdue_amount'))}
            for r in vendor_rows
        ],
    }


# Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬
# 12. EXPENSE BREAKDOWN BY CATEGORY
# Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬

def get_expense_breakdown_tool(tenant_ids: Optional[list[str]] = None, company_ids: Optional[list[int]] = None, start_date: str | None = None, end_date: str | None = None, limit: int = 20, base_currency: str | None = None) -> dict:

    from doova_one_view.api.accounting.service import AccountingService
    c_ids = normalize_company_ids(company_ids=company_ids)
    pnl = AccountingService._calc_pnl_sync(tenant_ids=tenant_ids, start_date=start_date, end_date=end_date, company_ids=c_ids, base_currency=base_currency)
    total_opex = float(pnl.get("operating_expenses") or 0.0)

    tag4_ids = AccountingService._get_tag4_account_ids(tenant_ids=tenant_ids)
    t_sql_l, t_params_l = build_tenant_filter_sql(tenant_ids=tenant_ids, column_name="l.tenant_id", prefix="t_l")
    balance_col = build_currency_case_sql('l.balance', tenant_ids=tenant_ids, base_currency=base_currency, currency_column='c.currency_code')
    params = {"limit": limit}
    params.update(t_params_l)
    f_sql, f_params = build_company_filter_sql(company_ids=c_ids, column_name="l.company_id")
    params.update(f_params)

    date_sql = ""
    if start_date:
        date_sql += " AND m.date >= :start_date"
        params["start_date"] = start_date
    if end_date:
        date_sql += " AND m.date <= :end_date"
        params["end_date"] = end_date

    tag4_clause = ""
    if tag4_ids:
        tag4_list_str = ",".join(str(tid) for tid in tag4_ids)
        tag4_clause = f"AND (l.account_odoo_id IS NOT NULL AND l.account_odoo_id NOT IN ({tag4_list_str}))"

    rows = run_query(
        f"""SELECT
                COALESCE(l.account_name, l.account_code, 'Uncategorized Expense') AS category,
                COALESCE(SUM({balance_col}), 0) AS amount
            FROM fact_account_move_lines l
            JOIN fact_account_moves m ON l.account_move_id = m.id
            LEFT JOIN dim_companies c ON l.company_id = c.id
            WHERE 1=1 {t_sql_l}
              AND m.state = 'posted'
              AND l.account_type = 'expense'
              {tag4_clause}
              {f_sql} {date_sql}
            GROUP BY COALESCE(l.account_name, l.account_code, 'Uncategorized Expense')
            ORDER BY amount DESC
            LIMIT :limit""",
        params,
    )

    categories = [
        {
            "category": r.get('category'),
            "amount": float(r.get('amount')),
            "pct_of_total": round(calculate_ratio(float(r.get('amount')), total_opex) * 100, 1)
        }
        for r in rows
    ]

    return {
        "tool_name": "get_expense_breakdown_tool",
        "start_date": start_date,
        "end_date": end_date,
        "total_expenses": total_opex,
        "operating_expenses": total_opex,
        "cogs": float(pnl.get("cogs") or 0.0),
        "depreciation": float(pnl.get("depreciation") or 0.0),
        "categories": categories,
    }


# Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬
# 13. TAX LIABILITY ESTIMATION
# Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬

def get_tax_summary_tool(tenant_ids: Optional[list[str]] = None, company_ids: Optional[list[int]] = None, base_currency: str | None = None) -> dict:

    t_sql_def, t_params_def = build_tenant_filter_sql(tenant_ids=tenant_ids, column_name="tenant_id", prefix="t_def")
    amount_col = build_currency_case_sql('amount_total', tenant_ids=tenant_ids, base_currency=base_currency)
    params = {}
    params.update(t_params_def)
    f_sql, f_params = build_company_filter_sql(company_ids=company_ids)
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

def detect_anomalies_tool(tenant_ids: Optional[list[str]] = None, company_ids: Optional[list[int]] = None, limit: int = 15) -> dict:

    t_sql_m, t_params_m = build_tenant_filter_sql(tenant_ids=tenant_ids, column_name="m.tenant_id", prefix="t_m")
    t_sql_l, t_params_l = build_tenant_filter_sql(tenant_ids=tenant_ids, column_name="l.tenant_id", prefix="t_l")
    params = {"limit": limit}
    params.update(t_params_m)
    params.update(t_params_l)
    f_sql, f_params = build_company_filter_sql(company_ids=company_ids, column_name="l.company_id")
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
    f_sql_m, f_params_m = build_company_filter_sql(company_ids=company_ids, column_name="m.company_id")
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

    from doova_one_view.api.jobs.alert_prechecks import run_all_prechecks
    prechecks = run_all_prechecks(
        tenant_ids=tenant_ids,
        company_ids=normalize_company_ids(company_ids=company_ids),
    )

    return {
        "tool_name": "detect_anomalies_tool",
        "macro_prechecks": prechecks,
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
        "risk_level": "High" if prechecks.get("any_triggered") or len(unbalanced) > 3 or len(outliers) > 5 or duplicates else "Medium" if unbalanced or outliers or round_numbers else "Low",
    }


# Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬
# 15. MULTI-PERIOD COMPARISON (YoY / QoQ)
# Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬

def get_period_comparison_tool(tenant_ids: Optional[list[str]] = None, company_ids: Optional[list[int]] = None, granularity: str = "month", base_currency: str | None = None) -> dict:

    t_sql_def, t_params_def = build_tenant_filter_sql(tenant_ids=tenant_ids, column_name="tenant_id", prefix="t_def")
    amount_col = build_currency_case_sql('amount_total', tenant_ids=tenant_ids, base_currency=base_currency)
    params = {}
    params.update(t_params_def)
    f_sql, f_params = build_company_filter_sql(company_ids=company_ids)
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

def get_cash_flow_health_tool(tenant_ids: Optional[list[str]] = None, company_ids: Optional[list[int]] = None, base_currency: str | None = None) -> dict:
    debit_col = build_currency_case_sql('l.debit', tenant_ids=tenant_ids, base_currency=base_currency, currency_column='l.currency_code')
    credit_col = build_currency_case_sql('l.credit', tenant_ids=tenant_ids, base_currency=base_currency, currency_column='l.currency_code')
    ar = get_receivables_analysis_tool(tenant_ids=tenant_ids, company_ids=company_ids)
    ap = get_payables_analysis_tool(tenant_ids=tenant_ids, company_ids=company_ids)

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

def get_aging_analysis_tool(tenant_ids: Optional[list[str]] = None, company_ids: Optional[list[int]] = None, direction: str = "receivable", base_currency: str | None = None, as_of_date: str | None = None) -> dict:

    def _safe_uuids(ids: list) -> list[str]:
        import uuid
        res = []
        for x in ids:
            try:
                uuid.UUID(str(x))
                res.append(str(x))
            except Exception:
                pass
        return res

    t_ids = normalize_tenant_ids(tenant_ids=tenant_ids)
    valid_t_uuids = _safe_uuids(t_ids)
    c_ids = normalize_company_ids(company_ids=company_ids)
    account_type = "asset_receivable" if direction == "receivable" else "liability_payable"

    from odoo_app.models import AccountPartialReconcile
    if valid_t_uuids and AccountPartialReconcile.objects.filter(tenant_id__in=valid_t_uuids).exists():
        from django.db import connection
        t_filter = "AND l.tenant_id IN %s"
        t_params = [tuple(str(t) for t in valid_t_uuids)]
        c_filter = "AND l.company_id IN %s" if c_ids else ""
        c_params = [tuple(int(c) for c in c_ids)] if c_filter else []

        target_date_sql = "DATE %s" if as_of_date else "CURRENT_DATE"
        d_params = [as_of_date, as_of_date, as_of_date] if as_of_date else []
        d_param_post = [as_of_date] if as_of_date else []

        sql = f"""
            WITH line_recon AS (
                SELECT
                    l.id AS line_id,
                    m.date AS move_date,
                    l.debit,
                    l.credit,
                    COALESCE(SUM(pr_deb.amount), 0) AS reconciled_debit,
                    COALESCE(SUM(pr_cred.amount), 0) AS reconciled_credit
                FROM fact_account_move_lines l
                JOIN fact_account_moves m ON l.account_move_id = m.id
                LEFT JOIN fact_account_partial_reconciles pr_deb 
                    ON pr_deb.debit_move_line_id = l.id AND pr_deb.max_date <= {target_date_sql}
                LEFT JOIN fact_account_partial_reconciles pr_cred 
                    ON pr_cred.credit_move_line_id = l.id AND pr_cred.max_date <= {target_date_sql}
                WHERE m.state = 'posted'
                  AND l.account_type = '{account_type}'
                  AND m.date <= {target_date_sql}
                  {t_filter}
                  {c_filter}
                GROUP BY l.id, m.date, l.debit, l.credit
            ),
            line_residual AS (
                SELECT
                    line_id,
                    move_date,
                    ({target_date_sql} - move_date) AS days,
                    CASE 
                        WHEN '{account_type}' = 'asset_receivable' THEN
                            CASE WHEN debit > 0 THEN debit - reconciled_debit ELSE -(credit - reconciled_credit) END
                        ELSE
                            CASE WHEN credit > 0 THEN credit - reconciled_credit ELSE -(debit - reconciled_debit) END
                    END AS residual
                FROM line_recon
            )
            SELECT
                COALESCE(SUM(CASE WHEN days <= 0 THEN residual ELSE 0 END), 0) AS current_bucket,
                COALESCE(COUNT(CASE WHEN days <= 0 AND ABS(residual) > 0.01 THEN 1 END), 0) AS current_cnt,
                COALESCE(SUM(CASE WHEN days BETWEEN 1 AND 30 THEN residual ELSE 0 END), 0) AS b_1_30,
                COALESCE(COUNT(CASE WHEN days BETWEEN 1 AND 30 AND ABS(residual) > 0.01 THEN 1 END), 0) AS b_1_30_cnt,
                COALESCE(SUM(CASE WHEN days BETWEEN 31 AND 60 THEN residual ELSE 0 END), 0) AS b_31_60,
                COALESCE(COUNT(CASE WHEN days BETWEEN 31 AND 60 AND ABS(residual) > 0.01 THEN 1 END), 0) AS b_31_60_cnt,
                COALESCE(SUM(CASE WHEN days BETWEEN 61 AND 90 THEN residual ELSE 0 END), 0) AS b_61_90,
                COALESCE(COUNT(CASE WHEN days BETWEEN 61 AND 90 AND ABS(residual) > 0.01 THEN 1 END), 0) AS b_61_90_cnt,
                COALESCE(SUM(CASE WHEN days BETWEEN 91 AND 120 THEN residual ELSE 0 END), 0) AS b_91_120,
                COALESCE(COUNT(CASE WHEN days BETWEEN 91 AND 120 AND ABS(residual) > 0.01 THEN 1 END), 0) AS b_91_120_cnt,
                COALESCE(SUM(CASE WHEN days >= 121 THEN residual ELSE 0 END), 0) AS b_older,
                COALESCE(COUNT(CASE WHEN days >= 121 AND ABS(residual) > 0.01 THEN 1 END), 0) AS b_older_cnt,
                COALESCE(SUM(residual), 0) AS total,
                COALESCE(COUNT(CASE WHEN ABS(residual) > 0.01 THEN 1 END), 0) AS total_cnt
            FROM line_residual
        """
        all_params = d_params + t_params + c_params + d_param_post
        with connection.cursor() as cursor:
            cursor.execute(sql, all_params)
            r = cursor.fetchone()
            c_val = float(r[0] or 0)
            c_cnt = int(r[1] or 0)
            d1_val = float(r[2] or 0)
            d1_cnt = int(r[3] or 0)
            d2_val = float(r[4] or 0)
            d2_cnt = int(r[5] or 0)
            d3_val = float(r[6] or 0)
            d3_cnt = int(r[7] or 0)
            d4_val = float(r[8] or 0)
            d4_cnt = int(r[9] or 0)
            d_older_val = float(r[10] or 0)
            d_older_cnt = int(r[11] or 0)
            d90_val = d4_val + d_older_val
            tot_val = float(r[12] or 0)
            tot_cnt = int(r[13] or 0)

            if base_currency:
                from doova_one_view.api.kpi.service import _get_rate_map
                rate_map = _get_rate_map(tenant_ids=t_ids)
                if base_currency in rate_map:
                    fx_rate = rate_map[base_currency]
                    c_val *= fx_rate
                    d1_val *= fx_rate
                    d2_val *= fx_rate
                    d3_val *= fx_rate
                    d4_val *= fx_rate
                    d_older_val *= fx_rate
                    d90_val *= fx_rate
                    tot_val *= fx_rate
            return {
                "tool_name": "get_aging_analysis_tool",
                "direction": direction,
                "current": c_val,
                "current_cnt": c_cnt,
                "1_30_days": d1_val,
                "1_30_days_cnt": d1_cnt,
                "31_60_days": d2_val,
                "31_60_days_cnt": d2_cnt,
                "61_90_days": d3_val,
                "61_90_days_cnt": d3_cnt,
                "91_120_days": d4_val,
                "91_120_days_cnt": d4_cnt,
                "older": d_older_val,
                "older_cnt": d_older_cnt,
                "90_plus_days": d90_val,
                "total": tot_val,
                "total_cnt": tot_cnt,
                "aging_buckets": {
                    "current": c_val,
                    "1-30": d1_val,
                    "31-60": d2_val,
                    "61-90": d3_val,
                    "91-120": d4_val,
                    "older": d_older_val,
                    "90+": d90_val,
                },
                "counts": {
                    "current": c_cnt,
                    "1-30": d1_cnt,
                    "31-60": d2_cnt,
                    "61-90": d3_cnt,
                    "91-120": d4_cnt,
                    "older": d_older_cnt,
                    "total": tot_cnt,
                }
            }

    t_sql_def, t_params_def = build_tenant_filter_sql(tenant_ids=tenant_ids, column_name="tenant_id", prefix="t_def")
    residual_col = build_currency_case_sql('amount_residual', tenant_ids=tenant_ids, base_currency=base_currency)
    move_type = "out_invoice" if direction == "receivable" else "in_invoice"
    params = {}
    params.update(t_params_def)
    f_sql, f_params = build_company_filter_sql(company_ids=company_ids)
    params.update(f_params)

    rows = run_query(
        f"""SELECT
                COALESCE(SUM(amount_total) FILTER (WHERE invoice_date_due >= CURRENT_DATE), 0) AS current_bucket,
                COALESCE(COUNT(*) FILTER (WHERE invoice_date_due >= CURRENT_DATE), 0) AS current_cnt,
                COALESCE(SUM(amount_total) FILTER (WHERE CURRENT_DATE - invoice_date_due BETWEEN 1 AND 30), 0) AS bucket_1_30,
                COALESCE(COUNT(*) FILTER (WHERE CURRENT_DATE - invoice_date_due BETWEEN 1 AND 30), 0) AS bucket_1_30_cnt,
                COALESCE(SUM(amount_total) FILTER (WHERE CURRENT_DATE - invoice_date_due BETWEEN 31 AND 60), 0) AS bucket_31_60,
                COALESCE(COUNT(*) FILTER (WHERE CURRENT_DATE - invoice_date_due BETWEEN 31 AND 60), 0) AS bucket_31_60_cnt,
                COALESCE(SUM(amount_total) FILTER (WHERE CURRENT_DATE - invoice_date_due BETWEEN 61 AND 90), 0) AS bucket_61_90,
                COALESCE(COUNT(*) FILTER (WHERE CURRENT_DATE - invoice_date_due BETWEEN 61 AND 90), 0) AS bucket_61_90_cnt,
                COALESCE(SUM(amount_total) FILTER (WHERE CURRENT_DATE - invoice_date_due BETWEEN 91 AND 120), 0) AS bucket_91_120,
                COALESCE(COUNT(*) FILTER (WHERE CURRENT_DATE - invoice_date_due BETWEEN 91 AND 120), 0) AS bucket_91_120_cnt,
                COALESCE(SUM(amount_total) FILTER (WHERE CURRENT_DATE - invoice_date_due >= 121), 0) AS bucket_older,
                COALESCE(COUNT(*) FILTER (WHERE CURRENT_DATE - invoice_date_due >= 121), 0) AS bucket_older_cnt,
                COALESCE(SUM(amount_total), 0) AS total,
                COALESCE(COUNT(*), 0) AS total_cnt
            FROM fact_account_moves
            WHERE 1=1 {t_sql_def}
              AND move_type = '{move_type}'
              AND state = 'posted'
              AND payment_state IN ('not_paid', 'partial')
              {f_sql}""",
        params,
    )

    row = rows[0] if rows else {}
    c_val = float(row.get("current_bucket", 0))
    c_cnt = int(row.get("current_cnt", 0))
    d1_val = float(row.get("bucket_1_30", 0))
    d1_cnt = int(row.get("bucket_1_30_cnt", 0))
    d2_val = float(row.get("bucket_31_60", 0))
    d2_cnt = int(row.get("bucket_31_60_cnt", 0))
    d3_val = float(row.get("bucket_61_90", 0))
    d3_cnt = int(row.get("bucket_61_90_cnt", 0))
    d4_val = float(row.get("bucket_91_120", 0))
    d4_cnt = int(row.get("bucket_91_120_cnt", 0))
    d_older_val = float(row.get("bucket_older", 0))
    d_older_cnt = int(row.get("bucket_older_cnt", 0))
    d90_val = d4_val + d_older_val
    tot_val = float(row.get("total", 0))
    tot_cnt = int(row.get("total_cnt", 0))

    return {
        "tool_name": "get_aging_analysis_tool",
        "direction": direction,
        "current": c_val,
        "current_cnt": c_cnt,
        "1_30_days": d1_val,
        "1_30_days_cnt": d1_cnt,
        "31_60_days": d2_val,
        "31_60_days_cnt": d2_cnt,
        "61_90_days": d3_val,
        "61_90_days_cnt": d3_cnt,
        "91_120_days": d4_val,
        "91_120_days_cnt": d4_cnt,
        "older": d_older_val,
        "older_cnt": d_older_cnt,
        "90_plus_days": d90_val,
        "total": tot_val,
        "total_cnt": tot_cnt,
        "aging_buckets": {
            "current": c_val,
            "1-30": d1_val,
            "31-60": d2_val,
            "61-90": d3_val,
            "91-120": d4_val,
            "older": d_older_val,
            "90+": d90_val,
        },
        "counts": {
            "current": c_cnt,
            "1-30": d1_cnt,
            "31-60": d2_cnt,
            "61-90": d3_cnt,
            "91-120": d4_cnt,
            "older": d_older_cnt,
            "total": tot_cnt,
        }
    }


# Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬
# 5. PROFIT & LOSS
# Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬

def calculate_pnl_tool(tenant_ids: Optional[list[str]] = None, company_ids: Optional[list[int]] = None, start_date: str | None = None, end_date: str | None = None, base_currency: str | None = None) -> dict:
    from doova_one_view.api.accounting.service import AccountingService
    c_ids = normalize_company_ids(company_ids=company_ids)
    stats = AccountingService._calc_pnl_sync(
        start_date=start_date,
        end_date=end_date,
        company_ids=c_ids,
        base_currency=base_currency,
        tenant_ids=tenant_ids,
    )
    income = float(stats.get("revenue") or 0.0)
    expenses = float(stats.get("total_expenses") or 0.0)
    cogs = float(stats.get("cogs") or 0.0)
    opex = float(stats.get("operating_expenses") or 0.0)
    gross = float(stats.get("gross_profit") or 0.0)
    ebit = float(stats.get("ebit") or 0.0)
    net = float(stats.get("net_profit") or 0.0)

    from doova_one_view.api.agent.tools_refactored.common import get_multi_currency_conversions
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
        "currency_conversions": get_multi_currency_conversions(income, tenant_ids=tenant_ids, company_ids=c_ids, base_currency=base_currency, start_date=start_date, end_date=end_date, domain="finance"),
    }


def analyze_profitability_tool(tenant_ids: Optional[list[str]] = None, company_ids: Optional[list[int]] = None) -> dict:
    pnl = calculate_pnl_tool(tenant_ids=tenant_ids, company_ids=company_ids)
    return {
        "tool_name": "analyze_profitability_tool",
        "gross_profit": pnl.get('gross_profit'),
        "net_profit": pnl.get('net_profit'),
        "gross_margin_pct": pnl.get('gross_margin_pct'),
        "net_margin_pct": pnl.get('net_margin_pct'),
        "status": "Healthy" if pnl.get('net_profit') > 0 else "Critical",
    }


def get_executive_summary_tool(tenant_ids: Optional[list[str]] = None, company_ids: Optional[list[int]] = None, start_date: str | None = None, end_date: str | None = None, base_currency: str | None = None) -> dict:
    """Returns the official 5-pillar Executive Business Summary matching Odoo Report 6."""
    from doova_one_view.api.accounting.service import AccountingService
    c_ids = normalize_company_ids(company_ids=company_ids)
    summary = AccountingService._calc_executive_summary_sync(
        tenant_id=tenant_id,
        start_date=start_date,
        end_date=end_date,
        company_ids=c_ids,
        base_currency=base_currency,
        tenant_ids=tenant_ids,
    )
    summary["tool_name"] = "get_executive_summary_tool"
    return summary


# Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬
# 6. BALANCE SHEET
# Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬

def get_balance_sheet_tool(tenant_ids: Optional[list[str]] = None, company_ids: Optional[list[int]] = None, as_of_date: str | None = None, base_currency: str | None = None) -> dict:

    t_sql_l, t_params_l = build_tenant_filter_sql(tenant_ids=tenant_ids, column_name="l.tenant_id", prefix="t_l")
    balance_col = build_currency_case_sql('l.balance', tenant_ids=tenant_ids, base_currency=base_currency, currency_column='c.currency_code')
    params = {}
    params.update(t_params_l)
    f_sql, f_params = build_company_filter_sql(company_ids=company_ids, column_name="l.company_id")
    params.update(f_params)
    
    date_sql = ""
    if as_of_date:
        date_sql += " AND m.date <= :as_of_date"
        params["as_of_date"] = as_of_date

    rows = run_query(
        f"""SELECT
                COALESCE(SUM({balance_col}) FILTER (WHERE l.account_type = 'asset_cash'), 0) AS bank_cash,
                COALESCE(SUM({balance_col}) FILTER (WHERE l.account_type = 'asset_receivable'), 0) AS receivables,
                COALESCE(SUM({balance_col}) FILTER (WHERE l.account_type = 'asset_prepayments'), 0) AS prepayments,
                COALESCE(SUM({balance_col}) FILTER (WHERE l.account_type = 'asset_fixed'), 0) AS fixed_assets,
                COALESCE(SUM({balance_col}) FILTER (WHERE l.account_type = 'liability_payable'), 0) * -1 AS payables,
                COALESCE(SUM({balance_col}) FILTER (WHERE l.account_type IN ('asset_receivable', 'asset_current', 'asset_cash', 'asset_prepayments')), 0) AS current_assets,
                COALESCE(SUM({balance_col}) FILTER (WHERE l.account_type IN ('asset_non_current', 'asset_fixed')), 0) AS non_current_assets,
                COALESCE(SUM({balance_col}) FILTER (WHERE l.account_type IN ('liability_current', 'liability_payable', 'liability_credit_card')), 0) * -1 AS current_liabilities,
                COALESCE(SUM({balance_col}) FILTER (WHERE l.account_type IN ('liability_non_current')), 0) * -1 AS non_current_liabilities,
                COALESCE(SUM({balance_col}) FILTER (WHERE l.account_type = 'equity'), 0) * -1 AS retained_earnings,
                COALESCE(SUM({balance_col}) FILTER (WHERE l.account_type = 'equity_unaffected' OR l.account_type LIKE 'income%' OR l.account_type LIKE 'expense%'), 0) * -1 AS unallocated_earnings,
                COALESCE(SUM({balance_col}) FILTER (WHERE l.account_type IN ('equity', 'equity_unaffected') OR l.account_type LIKE 'income%' OR l.account_type LIKE 'expense%'), 0) * -1 AS total_equity
            FROM fact_account_move_lines l
            JOIN fact_account_moves m ON l.account_move_id = m.id
            LEFT JOIN dim_companies c ON l.company_id = c.id
            WHERE 1=1 {t_sql_l}
              AND m.state = 'posted'
              {f_sql} {date_sql}""",
        params,
    )

    row = rows[0] if rows else {}
    bc = float(row.get("bank_cash") or 0)
    rec = float(row.get("receivables") or 0)
    prep = float(row.get("prepayments") or 0)
    fa = float(row.get("fixed_assets") or 0)
    pay = float(row.get("payables") or 0)
    ca = float(row.get("current_assets") or 0)
    nca = float(row.get("non_current_assets") or 0)
    cl = float(row.get("current_liabilities") or 0)
    ncl = float(row.get("non_current_liabilities") or 0)
    re = float(row.get("retained_earnings") or 0)
    ue = float(row.get("unallocated_earnings") or 0)
    eq = float(row.get("total_equity") or 0)

    total_assets = ca + nca
    total_liabilities = cl + ncl
    net_assets = total_assets - total_liabilities
    current_ratio = round(ca / cl, 2) if cl else 0.0
    balance_check = round(total_assets - total_liabilities - eq, 2)

    return {
        "tool_name": "get_balance_sheet_tool",
        "as_of_date": as_of_date or "Current",
        "bank_and_cash_accounts": bc,
        "receivables": rec,
        "prepayments": prep,
        "current_assets": ca,
        "fixed_assets": fa,
        "non_current_assets": nca,
        "total_assets": total_assets,
        "payables": pay,
        "current_liabilities": cl,
        "non_current_liabilities": ncl,
        "total_liabilities": total_liabilities,
        "retained_earnings": re,
        "unallocated_earnings": ue,
        "total_equity": eq,
        "net_assets": net_assets,
        "current_assets_to_liabilities": current_ratio,
        "current_ratio": current_ratio,
        "integrity_check": "BALANCED" if abs(balance_check) < 0.01 else f"IMBALANCED by {balance_check}",
    }


# Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬
# 7. TRIAL BALANCE
# Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬

def get_trial_balance_tool(tenant_ids: Optional[list[str]] = None, company_ids: Optional[list[int]] = None, limit: int | None = None, base_currency: str | None = None, date_from: str | None = None, date_to: str | None = None, as_of_date: str | None = None) -> dict:

    t_sql_l, t_params_l = build_tenant_filter_sql(tenant_ids=tenant_ids, column_name="l.tenant_id", prefix="t_l")
    balance_col = build_currency_case_sql('l.balance', tenant_ids=tenant_ids, base_currency=base_currency, currency_column='c.currency_code')
    debit_col = build_currency_case_sql('l.debit', tenant_ids=tenant_ids, base_currency=base_currency, currency_column='c.currency_code')
    credit_col = build_currency_case_sql('l.credit', tenant_ids=tenant_ids, base_currency=base_currency, currency_column='c.currency_code')
    
    date_sql = ""
    date_params = {}
    if date_from:
        date_sql += " AND m.date >= :date_from"
        date_params["date_from"] = date_from
    if date_to or as_of_date:
        date_sql += " AND m.date <= :date_to"
        date_params["date_to"] = date_to or as_of_date

    params = {}
    params.update(t_params_l)
    params.update(date_params)
    f_sql, f_params = build_company_filter_sql(company_ids=company_ids, column_name="l.company_id")
    params.update(f_params)

    tot_row = run_query(
        f"""SELECT
                COALESCE(SUM({debit_col}), 0) AS total_debit,
                COALESCE(SUM({credit_col}), 0) AS total_credit,
                COALESCE(SUM({balance_col}), 0) AS balance
            FROM fact_account_move_lines l
            JOIN fact_account_moves m ON l.account_move_id = m.id
            LEFT JOIN dim_companies c ON l.company_id = c.id
            WHERE 1=1 {t_sql_l}
              AND m.state = 'posted'
              {f_sql}
              {date_sql}""",
        params,
    )
    tot = tot_row[0] if tot_row else {}
    grand_total_debit = float(tot.get("total_debit") or 0)
    grand_total_credit = float(tot.get("total_credit") or 0)
    variance = round(grand_total_debit - grand_total_credit, 2)

    limit_sql = f"LIMIT {int(limit)}" if limit else ""

    rows = run_query(
        f"""SELECT
                l.account_code,
                l.account_name,
                COALESCE(SUM({debit_col}), 0) AS total_debit,
                COALESCE(SUM({credit_col}), 0) AS total_credit,
                COALESCE(SUM({balance_col}), 0) AS balance
            FROM fact_account_move_lines l
            JOIN fact_account_moves m ON l.account_move_id = m.id
            LEFT JOIN dim_companies c ON l.company_id = c.id
            WHERE 1=1 {t_sql_l}
              AND m.state = 'posted'
              {f_sql}
              {date_sql}
            GROUP BY l.account_code, l.account_name
            ORDER BY l.account_code
            {limit_sql}""",
        params,
    )

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
        "total_accounts_count": len(rows),
        "total_debit": grand_total_debit,
        "total_credit": grand_total_credit,
        "variance": variance,
        "integrity_check": "BALANCED" if abs(variance) < 0.01 else f"VARIANCE of {variance}",
    }


# Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬
# 8. FINANCIAL RATIOS DASHBOARD
# Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬

def get_financial_ratios_tool(tenant_ids: Optional[list[str]] = None, company_ids: Optional[list[int]] = None, start_date: str | None = None, end_date: str | None = None, as_of_date: str | None = None, base_currency: str | None = None) -> dict:
    bs = get_balance_sheet_tool(tenant_ids=tenant_ids, company_ids=company_ids, as_of_date=as_of_date or end_date, base_currency=base_currency)
    pnl = calculate_pnl_tool(company_ids=company_ids, start_date=start_date, end_date=end_date, base_currency=base_currency, tenant_ids=tenant_ids)
    inv_data = get_inventory_efficiency_tool(tenant_ids=tenant_ids, company_ids=company_ids)
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
        "return_on_investment_pct": round(roa * 100, 2),
        "roi_pct": round(roa * 100, 2),
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

def get_working_capital_tool(tenant_ids: Optional[list[str]] = None, company_ids: Optional[list[int]] = None, base_currency: str | None = None) -> dict:
    bs = get_balance_sheet_tool(tenant_ids=tenant_ids, company_ids=company_ids, base_currency=base_currency)
    ca = float(bs.get('current_assets') or 0)
    cl = float(bs.get('current_liabilities') or 0)
    wc = ca - cl
    wc_ratio = calculate_ratio(ca, cl)

    return {
        "tool_name": "get_working_capital_tool",
        "current_assets": bs.get('current_assets'),
        "current_liabilities": bs.get('current_liabilities'),
        "working_capital": wc,
        "working_capital_ratio": round(wc_ratio, 2),
        "current_ratio": round(wc_ratio, 2),
        "status": "Positive" if wc > 0 else "Negative Ã¢â‚¬â€ liquidity risk",
    }


# Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬
# 10. BUSINESS HEALTH SCORE (Real weighted scoring)
# Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬

def get_business_health_score_tool(tenant_ids: Optional[list[str]] = None, company_ids: Optional[list[int]] = None, base_currency: str | None = None) -> dict:
    balance_col = build_currency_case_sql('l.balance', tenant_ids=tenant_ids, base_currency=base_currency, currency_column='l.currency_code')
    amount_col = build_currency_case_sql('amount_total', tenant_ids=tenant_ids, base_currency=base_currency)
    residual_col = build_currency_case_sql('amount_residual', tenant_ids=tenant_ids, base_currency=base_currency)
    pnl = calculate_pnl_tool(tenant_ids=tenant_ids, company_ids=company_ids)
    ar = get_receivables_analysis_tool(tenant_ids=tenant_ids, company_ids=company_ids)
    bs = get_balance_sheet_tool(tenant_ids=tenant_ids, company_ids=company_ids)

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

def get_customer_metrics_tool(tenant_ids: Optional[list[str]] = None, company_ids: Optional[list[int]] = None, limit: int = 10, base_currency: str | None = None) -> dict:

    t_sql_s, t_params_s = build_tenant_filter_sql(tenant_ids=tenant_ids, column_name="s.tenant_id", prefix="t_s")
    amount_col = build_currency_case_sql('s.amount_total', tenant_ids=tenant_ids, base_currency=base_currency, currency_column='s.currency_code')
    params = {"limit": limit}
    params.update(t_params_s)
    f_sql, f_params = build_company_filter_sql(company_ids=company_ids, column_name="s.company_id")
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


# ────────────────────────────────────────────────────────────────────────────────
# 12. UNREALIZED CURRENCY GAINS / LOSSES (BALANCE SHEET REVALUATION)
# ────────────────────────────────────────────────────────────────────────────────

def get_unrealized_currency_gains_losses_tool(tenant_ids: Optional[list[str]] = None, company_ids: Optional[list[int]] = None, as_of_date: str | None = None) -> dict:
    """
    Computes statutory Unrealized Currency Gains/Losses (Balance Sheet Revaluation) matching Odoo.
    Evaluates foreign-currency-denominated accounts (Payables, Receivables, Cash, Bank) at the 
    operation rate vs current market rate as of the given date, and computes the required adjustment.
    """
    def _safe_uuids(ids: list) -> list[str]:
        import uuid
        res = []
        for x in ids:
            try:
                uuid.UUID(str(x))
                res.append(str(x))
            except Exception:
                pass
        return res

    t_ids = normalize_tenant_ids(tenant_ids=tenant_ids)
    valid_t_uuids = _safe_uuids(t_ids)
    c_ids = normalize_company_ids(company_ids=company_ids)

    from django.db import connection
    from datetime import date
    target_date = as_of_date or date.today().isoformat()

    rate_map = {}
    if valid_t_uuids:
        with connection.cursor() as cursor:
            cursor.execute("""
                SELECT DISTINCT ON (c.code) c.code, cr.rate
                FROM dim_currency_rates cr
                JOIN dim_currencies c ON cr.currency_id = c.id AND cr.tenant_id = c.tenant_id
                WHERE cr.tenant_id IN %s
                  AND cr.name <= %s
                ORDER BY c.code, cr.name DESC
            """, [tuple(str(t) for t in valid_t_uuids), target_date])
            for code, rate in cursor.fetchall():
                rate_map[code] = float(rate) if rate else 1.0

    t_filter = "AND l.tenant_id IN %s" if valid_t_uuids else ""
    t_params = [tuple(str(t) for t in valid_t_uuids)] if valid_t_uuids else []
    c_filter = "AND l.company_id IN %s" if c_ids else ""
    c_params = [tuple(int(c) for c in c_ids)] if c_filter else []

    sql = f"""
        SELECT 
            l.account_code,
            l.account_name,
            l.account_type,
            l.currency_code as line_currency,
            c.currency_code as company_currency,
            COALESCE(SUM(l.amount_currency), 0) as foreign_balance,
            COALESCE(SUM(l.balance), 0) as operation_balance
        FROM fact_account_move_lines l
        JOIN fact_account_moves m ON l.account_move_id = m.id
        JOIN dim_companies c ON l.company_id = c.id
        WHERE 1=1 {t_filter} {c_filter}
          AND m.state = 'posted'
          AND m.date <= %s
          AND l.currency_code IS NOT NULL 
          AND l.currency_code != c.currency_code 
          AND l.currency_code != 'COMPANY_BASE'
          AND l.account_type IN ('asset_receivable', 'liability_payable', 'asset_cash', 'liability_current', 'asset_current')
        GROUP BY l.account_code, l.account_name, l.account_type, l.currency_code, c.currency_code
        HAVING ABS(SUM(l.amount_currency)) > 0.001 OR ABS(SUM(l.balance)) > 0.001
        ORDER BY l.currency_code, l.account_code
    """
    params = t_params + c_params + [target_date]
    with connection.cursor() as cursor:
        cursor.execute(sql, params)
        rows = cursor.fetchall()

    accounts_to_adjust = []
    total_adjustment = 0.0

    for r in rows:
        acct_code, acct_name, acct_type, line_curr, comp_curr, f_bal, op_bal = r
        f_bal = float(f_bal)
        op_bal = float(op_bal)
        rate = float(rate_map.get(line_curr, 1.0))

        if rate > 0:
            curr_bal = abs(f_bal) / rate
        else:
            curr_bal = 0.0

        adj = curr_bal - abs(op_bal)
        total_adjustment += adj

        accounts_to_adjust.append({
            "account_code": acct_code,
            "account_name": acct_name,
            "account_type": acct_type,
            "currency": line_curr,
            "rate_info": f"1 {comp_curr} = {rate:.8f} {line_curr}" if rate else "",
            "balance_foreign_currency": round(abs(f_bal), 2),
            "balance_operation_rate": round(abs(op_bal), 2),
            "balance_current_rate": round(curr_bal, 2),
            "adjustment": round(adj, 2),
        })

    return {
        "tool_name": "get_unrealized_currency_gains_losses_tool",
        "as_of_date": target_date,
        "accounts_to_adjust": accounts_to_adjust,
        "total_accounts_count": len(accounts_to_adjust),
        "total_net_adjustment": round(total_adjustment, 2),
        "status": "Net Unrealized Loss" if total_adjustment > 0 else "Net Unrealized Gain",
    }


# ────────────────────────────────────────────────────────────────────────────────
# 13. GENERAL LEDGER
# ────────────────────────────────────────────────────────────────────────────────

def get_general_ledger_tool(tenant_ids: Optional[list[str]] = None, company_ids: Optional[list[int]] = None, account_code: str | None = None, account_name: str | None = None, date_from: str | None = None, date_to: str | None = None, as_of_date: str | None = None, include_lines: bool = False, limit_accounts: int | None = None, limit_lines_per_account: int = 25, base_currency: str | None = None) -> dict:
    """
    Generates the complete General Ledger matching Odoo.
    Returns account-level Debit, Credit, and Net Balance for all accounts across active companies,
    along with grand totals, integrity verification (Debit == Credit), and optional granular move lines.
    """
    t_sql_l, t_params_l = build_tenant_filter_sql(tenant_ids=tenant_ids, column_name="l.tenant_id", prefix="t_l")
    balance_col = build_currency_case_sql('l.balance', tenant_ids=tenant_ids, base_currency=base_currency, currency_column='l.currency_code')
    debit_col = build_currency_case_sql('l.debit', tenant_ids=tenant_ids, base_currency=base_currency, currency_column='l.currency_code')
    credit_col = build_currency_case_sql('l.credit', tenant_ids=tenant_ids, base_currency=base_currency, currency_column='l.currency_code')

    date_sql = ""
    date_params = {}
    if date_from:
        date_sql += " AND m.date >= :date_from"
        date_params["date_from"] = date_from
    if date_to or as_of_date:
        date_sql += " AND m.date <= :date_to"
        date_params["date_to"] = date_to or as_of_date

    acct_sql = ""
    acct_params = {}
    if account_code:
        acct_sql += " AND (l.account_code ILIKE :acct_code OR l.account_name ILIKE :acct_code)"
        acct_params["acct_code"] = f"%{account_code}%"
    if account_name:
        acct_sql += " AND (l.account_name ILIKE :acct_name OR l.account_code ILIKE :acct_name)"
        acct_params["acct_name"] = f"%{account_name}%"

    params = {}
    params.update(t_params_l)
    params.update(date_params)
    params.update(acct_params)
    f_sql, f_params = build_company_filter_sql(company_ids=company_ids, column_name="l.company_id")
    params.update(f_params)

    # 1. Grand totals across the entire ledger
    tot_row = run_query(
        f"""SELECT
                COALESCE(SUM({debit_col}), 0) AS total_debit,
                COALESCE(SUM({credit_col}), 0) AS total_credit,
                COALESCE(SUM({balance_col}), 0) AS net_balance
            FROM fact_account_move_lines l
            JOIN fact_account_moves m ON l.account_move_id = m.id
            WHERE 1=1 {t_sql_l}
              AND m.state = 'posted'
              {f_sql}
              {date_sql}""",
        params,
    )
    tot = tot_row[0] if tot_row else {}
    grand_total_debit = float(tot.get("total_debit") or 0)
    grand_total_credit = float(tot.get("total_credit") or 0)
    variance = round(grand_total_debit - grand_total_credit, 2)

    limit_sql = f"LIMIT {int(limit_accounts)}" if limit_accounts else ""

    # 2. Account level breakdown
    rows = run_query(
        f"""SELECT
                c.name AS company_name,
                l.account_code,
                l.account_name,
                l.account_type,
                c.currency_code AS base_currency,
                COALESCE(SUM({debit_col}), 0) AS total_debit,
                COALESCE(SUM({credit_col}), 0) AS total_credit,
                COALESCE(SUM({balance_col}), 0) AS balance
            FROM fact_account_move_lines l
            JOIN fact_account_moves m ON l.account_move_id = m.id
            JOIN dim_companies c ON l.company_id = c.id
            WHERE 1=1 {t_sql_l}
              AND m.state = 'posted'
              {f_sql}
              {date_sql}
              {acct_sql}
            GROUP BY c.name, l.account_code, l.account_name, l.account_type, c.currency_code
            ORDER BY l.account_code, c.name
            {limit_sql}""",
        params,
    )

    accounts = []
    for r in rows:
        acc_dict = {
            "company": r.get('company_name'),
            "code": r.get('account_code'),
            "name": r.get('account_name'),
            "account_type": r.get('account_type'),
            "currency": r.get('base_currency'),
            "debit": float(r.get('total_debit')),
            "credit": float(r.get('total_credit')),
            "balance": float(r.get('balance')),
        }

        if include_lines or account_code:
            line_params = params.copy()
            line_params["acc_code"] = r.get('account_code')
            line_params["comp_name"] = r.get('company_name')
            line_params["line_limit"] = int(limit_lines_per_account)
            lines_data = run_query(
                f"""SELECT
                        m.date AS entry_date,
                        COALESCE(m.odoo_name, m.ref, l.name, '') AS move_number,
                        l.name AS communication,
                        p.name AS partner_name,
                        l.currency_code,
                        COALESCE({debit_col}, 0) AS debit,
                        COALESCE({credit_col}, 0) AS credit,
                        COALESCE({balance_col}, 0) AS balance
                    FROM fact_account_move_lines l
                    JOIN fact_account_moves m ON l.account_move_id = m.id
                    JOIN dim_companies c ON l.company_id = c.id
                    LEFT JOIN dim_partners p ON l.partner_id = p.id AND l.tenant_id = p.tenant_id
                    WHERE 1=1 {t_sql_l}
                      AND m.state = 'posted'
                      AND l.account_code = :acc_code
                      AND c.name = :comp_name
                      {date_sql}
                    ORDER BY m.date DESC, l.id DESC
                    LIMIT :line_limit""",
                line_params,
            )
            acc_dict["lines"] = [
                {
                    "date": str(line.get('entry_date')),
                    "move_number": line.get('move_number'),
                    "communication": line.get('communication') or "",
                    "partner": line.get('partner_name') or "—",
                    "currency": line.get('currency_code') or r.get('base_currency'),
                    "debit": float(line.get('debit') or 0),
                    "credit": float(line.get('credit') or 0),
                    "balance": float(line.get('balance') or 0),
                }
                for line in lines_data
            ]
        accounts.append(acc_dict)

    return {
        "tool_name": "get_general_ledger_tool",
        "date_from": date_from,
        "date_to": date_to or as_of_date,
        "total_accounts_count": len(accounts),
        "total_debit": grand_total_debit,
        "total_credit": grand_total_credit,
        "net_balance": round(grand_total_debit - grand_total_credit, 2),
        "integrity_check": "BALANCED" if abs(variance) < 0.01 else f"VARIANCE of {variance}",
        "accounts": accounts,
    }


# ────────────────────────────────────────────────────────────────────────────────
# 14. PARTNER LEDGER
# ────────────────────────────────────────────────────────────────────────────────

def get_partner_ledger_tool(tenant_ids: Optional[list[str]] = None, company_ids: Optional[list[int]] = None, partner_name: str | None = None, partner_id: int | None = None, account_type: str | None = None, date_from: str | None = None, date_to: str | None = None, as_of_date: str | None = None, unreconciled_only: bool = False, include_lines: bool = False, limit_partners: int | None = None, limit_lines_per_partner: int = 50, base_currency: str | None = None) -> dict:
    """
    Generates the complete Partner Ledger (Grand Livre des Tiers) matching Odoo exactly.
    Complies with Odoo's Balance Sheet accounting formula:
    - Calculates dynamically via parameterized SQL queries on fact_account_move_lines.
    - Ensures Grand Totals and drill-down table rows are 100% synchronized (Rule 1).
    - Dynamically incorporates all partners meeting Odoo's report criteria:
      1. Has lifetime transactional activity (debit > 0 or credit > 0)
      2. And either:
         a. Has non-zero ending balance at period close
         b. Had posted transactions within the requested date range (date >= date_from)
         c. Holds unreconciled or unallocated entries (including historical zero-balance settled partners)
    - When granular move lines are requested, presents the exact Odoo columns:
      Journal, Account, Invoice Date, Due Date, Matching, Debit, Credit, Amount Currency, and running Balance.
    """
    target_end_date = date_to or as_of_date

    raw_cids = normalize_company_ids(company_ids=company_ids)
    t_ids = normalize_tenant_ids(tenant_ids=tenant_ids)
    resolved_company_ids = []
    company_names = []
    try:
        from odoo_app.models.company import Company
        from django.db.models import Q
        c_qs = Company.objects.all()
        if t_ids:
            c_qs = c_qs.filter(tenant_id__in=t_ids)
        if raw_cids:
            matched_c = c_qs.filter(Q(id__in=raw_cids) | Q(odoo_id__in=raw_cids))
            resolved_company_ids = list(matched_c.values_list('id', flat=True))
            company_names = list(matched_c.values_list('name', flat=True))
        else:
            resolved_company_ids = list(c_qs.values_list('id', flat=True))
            company_names = list(c_qs.values_list('name', flat=True))
    except Exception:
        resolved_company_ids = raw_cids
    scope_str = ", ".join(company_names) if company_names else ("Consolidated" if not raw_cids else f"Companies {raw_cids}")

    # Format period label
    if date_from and target_end_date:
        period_label = f"{date_from} to {target_end_date}"
    elif target_end_date:
        period_label = f"As of {target_end_date}"
    else:
        period_label = "All Time"

    # Dynamic SQL query with Cross-Partner Partial Reconciliation UNION
    t_sql_l, t_params_l = build_tenant_filter_sql(tenant_ids=tenant_ids, column_name="l.tenant_id", prefix="t_l")
    t_sql_pr1, t_params_pr1 = build_tenant_filter_sql(tenant_ids=tenant_ids, column_name="pr.tenant_id", prefix="t_pr1")
    t_sql_pr2, t_params_pr2 = build_tenant_filter_sql(tenant_ids=tenant_ids, column_name="pr.tenant_id", prefix="t_pr2")
    t_sql_prd, t_params_prd = build_tenant_filter_sql(tenant_ids=tenant_ids, column_name="tenant_id", prefix="t_prd")
    t_sql_prc, t_params_prc = build_tenant_filter_sql(tenant_ids=tenant_ids, column_name="tenant_id", prefix="t_prc")

    f_sql_l, f_params_l = build_company_filter_sql(company_ids=resolved_company_ids, column_name="l.company_id", prefix="comp_l")
    f_sql_deb, f_params_deb = build_company_filter_sql(company_ids=resolved_company_ids, column_name="l_deb.company_id", prefix="comp_deb")
    f_sql_crd, f_params_crd = build_company_filter_sql(company_ids=resolved_company_ids, column_name="l_crd.company_id", prefix="comp_crd")

    balance_col = build_currency_case_sql('l.balance', tenant_ids=tenant_ids, base_currency=base_currency, currency_column='l.currency_code')
    debit_col = build_currency_case_sql('l.debit', tenant_ids=tenant_ids, base_currency=base_currency, currency_column='l.currency_code')
    credit_col = build_currency_case_sql('l.credit', tenant_ids=tenant_ids, base_currency=base_currency, currency_column='l.currency_code')

    norm_acct_type = str(account_type).lower().strip() if account_type else None
    if norm_acct_type in ("receivable", "asset_receivable", "customer", "customers"):
        norm_acct_type = "asset_receivable"
    elif norm_acct_type in ("payable", "liability_payable", "vendor", "supplier", "suppliers", "vendors"):
        norm_acct_type = "liability_payable"

    if norm_acct_type:
        acct_type_filter_l = f"AND l.account_type = '{norm_acct_type}'"
        acct_type_filter_deb = f"AND l_deb.account_type = '{norm_acct_type}'"
        acct_type_filter_crd = f"AND l_crd.account_type = '{norm_acct_type}'"
    else:
        acct_type_filter_l = "AND l.account_type IN ('asset_receivable', 'liability_payable')"
        acct_type_filter_deb = "AND l_deb.account_type IN ('asset_receivable', 'liability_payable')"
        acct_type_filter_crd = "AND l_crd.account_type IN ('asset_receivable', 'liability_payable')"

    params = {}
    params.update(t_params_l)
    params.update(t_params_pr1)
    params.update(t_params_pr2)
    params.update(t_params_prd)
    params.update(t_params_prc)
    params.update(f_params_l)
    params.update(f_params_deb)
    params.update(f_params_crd)

    end_date_sql = ""
    pr_end_date_sql = ""
    pr_sub_end_date = ""
    if target_end_date:
        end_date_sql = " AND m.date <= :target_end_date"
        pr_end_date_sql = " AND pr.max_date <= :target_end_date"
        pr_sub_end_date = " AND max_date <= :target_end_date"
        params["target_end_date"] = target_end_date

    partner_sql = ""
    if partner_id:
        partner_sql += " AND (u.partner_id = :partner_id OR p.odoo_id = :partner_id)"
        params["partner_id"] = partner_id
    if partner_name:
        partner_sql += " AND p.name ILIKE :partner_name"
        params["partner_name"] = f"%{partner_name}%"

    if date_from:
        params["date_from"] = date_from
        init_bal_expr = "COALESCE(SUM(CASE WHEN u.date < :date_from THEN u.balance ELSE 0 END), 0)"
        init_deb_expr = "COALESCE(SUM(CASE WHEN u.date < :date_from THEN u.debit ELSE 0 END), 0)"
        init_crd_expr = "COALESCE(SUM(CASE WHEN u.date < :date_from THEN u.credit ELSE 0 END), 0)"
        period_debit_expr = "COALESCE(SUM(CASE WHEN u.date >= :date_from THEN u.debit ELSE 0 END), 0)"
        period_credit_expr = "COALESCE(SUM(CASE WHEN u.date >= :date_from THEN u.credit ELSE 0 END), 0)"
    else:
        init_bal_expr = "0.0"
        init_deb_expr = "0.0"
        init_crd_expr = "0.0"
        period_debit_expr = "COALESCE(SUM(u.debit), 0)"
        period_credit_expr = "COALESCE(SUM(u.credit), 0)"

    limit_sql = f"LIMIT {int(limit_partners)}" if limit_partners else ""

    # Partner level query with dynamic Odoo filter:
    # 1. Partner must have lifetime transactional activity (debit > 0 or credit > 0).
    # 2. When unreconciled_only=True: must have non-zero balance or unallocated/open lines.
    # 3. Default (unfiltered view matching Odoo): includes partners with:
    #    a. Non-zero ending balance (ABS(balance) > 0.001)
    #    b. Transactions within requested period (u.date >= date_from)
    #    c. Unreconciled / open items (no partial reconcile record or remaining unallocated balance)
    date_from_check = "u.date >= :date_from" if date_from else "1=1"
    unrec_line_filter = "AND l.full_reconcile_id IS NULL" if unreconciled_only else ""
    cross_pr_filter = "AND 1=0" if unreconciled_only else ""
    if unreconciled_only:
        having_clause = f"""HAVING 
            (COALESCE(SUM(u.debit), 0) > 0.001 OR COALESCE(SUM(u.credit), 0) > 0.001)
            AND (
                (ABS(COALESCE(SUM(u.balance), 0)) > 0.001)
                OR (COALESCE(SUM(CASE WHEN (u.debit > 0 AND (u.debit - COALESCE(pr_d.rec_d, 0)) > 0.01)
                                        OR (u.credit > 0 AND (u.credit - COALESCE(pr_c.rec_c, 0)) > 0.01) THEN 1 ELSE 0 END), 0) > 0)
                OR (COALESCE(SUM(CASE WHEN {date_from_check} THEN 1 ELSE 0 END), 0) > 0)
            )
        """
    else:
        having_clause = f"""HAVING 
            (COALESCE(SUM(u.debit), 0) > 0.001 OR COALESCE(SUM(u.credit), 0) > 0.001)
            AND (
                (ABS(COALESCE(SUM(u.balance), 0)) > 0.001)
                OR (COALESCE(SUM(CASE WHEN {date_from_check} THEN 1 ELSE 0 END), 0) > 0)
                OR (COALESCE(SUM(CASE WHEN u.line_id IS NOT NULL AND pr_d.rec_d IS NULL AND pr_c.rec_c IS NULL THEN 1 ELSE 0 END), 0) > 0)
                OR (COALESCE(SUM(CASE WHEN u.line_id IS NULL THEN 1 ELSE 0 END), 0) > 0)
            )
        """

    query = f"""
        WITH unioned_entries AS (
            SELECT 
                l.partner_id,
                l.company_id,
                l.tenant_id,
                m.date,
                {debit_col} AS debit,
                {credit_col} AS credit,
                {balance_col} AS balance,
                l.id AS line_id
            FROM fact_account_move_lines l
            JOIN fact_account_moves m ON l.account_move_id = m.id
            WHERE 1=1 {t_sql_l}
              AND m.state = 'posted'
              {acct_type_filter_l}
              {f_sql_l}
              {end_date_sql}
              {unrec_line_filter}

            UNION ALL

            -- Cross-partner partial reconcile: credit side of debit partner
            SELECT 
                l_deb.partner_id,
                l_deb.company_id,
                l_deb.tenant_id,
                pr.max_date AS date,
                0.00 AS debit,
                pr.amount AS credit,
                -pr.amount AS balance,
                NULL AS line_id
            FROM fact_account_partial_reconciles pr
            JOIN fact_account_move_lines l_deb ON pr.debit_move_line_id = l_deb.id
            JOIN fact_account_move_lines l_crd ON pr.credit_move_line_id = l_crd.id
            WHERE 1=1 {t_sql_pr1}
              {pr_end_date_sql}
              {f_sql_deb}
              {acct_type_filter_deb}
              {acct_type_filter_crd}
              AND (l_deb.partner_id IS DISTINCT FROM l_crd.partner_id)
              {cross_pr_filter}

            UNION ALL

            -- Cross-partner partial reconcile: debit side of credit partner
            SELECT 
                l_crd.partner_id,
                l_crd.company_id,
                l_crd.tenant_id,
                pr.max_date AS date,
                pr.amount AS debit,
                0.00 AS credit,
                pr.amount AS balance,
                NULL AS line_id
            FROM fact_account_partial_reconciles pr
            JOIN fact_account_move_lines l_deb ON pr.debit_move_line_id = l_deb.id
            JOIN fact_account_move_lines l_crd ON pr.credit_move_line_id = l_crd.id
            WHERE 1=1 {t_sql_pr2}
              {pr_end_date_sql}
              {f_sql_crd}
              {acct_type_filter_deb}
              {acct_type_filter_crd}
              AND (l_deb.partner_id IS DISTINCT FROM l_crd.partner_id)
              {cross_pr_filter}
        )
        SELECT 
            COALESCE(p.name, 'Unknown Partner') AS partner_name,
            p.odoo_id,
            u.partner_id,
            MAX(c.currency_code) AS base_currency,
            COALESCE(SUM(u.debit), 0) AS total_debit,
            COALESCE(SUM(u.credit), 0) AS total_credit,
            COALESCE(SUM(u.balance), 0) AS balance,
            {init_bal_expr} AS initial_balance,
            {init_deb_expr} AS initial_debit,
            {init_crd_expr} AS initial_credit,
            {period_debit_expr} AS period_debit,
            {period_credit_expr} AS period_credit
        FROM unioned_entries u
        LEFT JOIN dim_partners p ON u.partner_id = p.id AND u.tenant_id = p.tenant_id
        LEFT JOIN dim_companies c ON u.company_id = c.id
        LEFT JOIN (
            SELECT debit_move_line_id, SUM(amount) AS rec_d
            FROM fact_account_partial_reconciles
            WHERE 1=1 {t_sql_prd}
            GROUP BY debit_move_line_id
        ) pr_d ON u.line_id = pr_d.debit_move_line_id
        LEFT JOIN (
            SELECT credit_move_line_id, SUM(amount) AS rec_c
            FROM fact_account_partial_reconciles
            WHERE 1=1 {t_sql_prc}
            GROUP BY credit_move_line_id
        ) pr_c ON u.line_id = pr_c.credit_move_line_id
        WHERE 1=1
          {partner_sql}
        GROUP BY p.odoo_id, p.name, u.partner_id
        {having_clause}
        ORDER BY p.name NULLS LAST
        {limit_sql}
    """
    rows = run_query(query, params)

    partners = []
    for r in rows:
        bal = float(r.get('balance') or 0)
        init_bal = float(r.get('initial_balance') or 0)
        init_deb = float(r.get('initial_debit') or 0)
        init_crd = float(r.get('initial_credit') or 0)
        deb_val = float(r.get('total_debit') or 0)
        crd_val = float(r.get('total_credit') or 0)

        p_dict = {
            "partner_name": r.get('partner_name'),
            "partner_id": r.get('partner_id'),
            "odoo_id": r.get('odoo_id'),
            "currency": r.get('base_currency') or base_currency or "XAF",
            "debit": deb_val,
            "credit": crd_val,
            "balance": bal,
            "initial_balance": init_bal,
            "initial_debit": init_deb,
            "initial_credit": init_crd,
            "period_debit": float(r.get('period_debit') or 0),
            "period_credit": float(r.get('period_credit') or 0),
            "status": "Net Receivable" if bal > 0.01 else "Net Payable" if bal < -0.01 else "Settled",
        }

        if include_lines or partner_name or partner_id:
            line_params = params.copy()
            line_params["p_id"] = r.get('partner_id')
            line_params["line_limit"] = int(limit_lines_per_partner)
            p_filter_l = "AND l.partner_id = :p_id" if r.get('partner_id') else "AND l.partner_id IS NULL"
            p_filter_deb = "AND l_deb.partner_id = :p_id" if r.get('partner_id') else "AND l_deb.partner_id IS NULL"
            p_filter_crd = "AND l_crd.partner_id = :p_id" if r.get('partner_id') else "AND l_crd.partner_id IS NULL"

            lines_date_filter_l = ""
            lines_date_filter_pr = ""
            if date_from:
                lines_date_filter_l = "AND m.date >= :date_from"
                lines_date_filter_pr = "AND pr.max_date >= :date_from"

            lines_query = f"""
                WITH partner_detail_lines AS (
                    SELECT
                        m.date AS entry_date,
                        COALESCE(j.code, 'MISC') AS journal,
                        l.account_code,
                        m.invoice_date,
                        m.invoice_date_due AS due_date,
                        COALESCE(m.odoo_name, m.ref, l.name, '') AS matching,
                        l.currency_code,
                        l.amount_currency,
                        COALESCE({debit_col}, 0) AS debit,
                        COALESCE({credit_col}, 0) AS credit,
                        COALESCE({balance_col}, 0) AS balance,
                        l.id AS sort_id
                    FROM fact_account_move_lines l
                    JOIN fact_account_moves m ON l.account_move_id = m.id
                    LEFT JOIN dim_account_journals j ON m.journal_id = j.id
                    JOIN dim_companies c ON l.company_id = c.id
                    WHERE 1=1 {t_sql_l}
                      AND m.state = 'posted'
                      {acct_type_filter_l}
                      {p_filter_l}
                      {f_sql_l}
                      {end_date_sql}
                      {lines_date_filter_l}
                      {unrec_line_filter}

                    UNION ALL

                    -- Cross-partner partial reconcile credit side (for debit partner)
                    SELECT
                        pr.max_date AS entry_date,
                        COALESCE(j_crd.code, 'RECON') AS journal,
                        l_deb.account_code,
                        pr.max_date AS invoice_date,
                        NULL AS due_date,
                        COALESCE(m_crd.odoo_name, m_crd.ref, 'Cross-Partner Reconcile Offset') AS matching,
                        l_deb.currency_code,
                        -pr.amount AS amount_currency,
                        0.00 AS debit,
                        pr.amount AS credit,
                        -pr.amount AS balance,
                        999999999 AS sort_id
                    FROM fact_account_partial_reconciles pr
                    JOIN fact_account_move_lines l_deb ON pr.debit_move_line_id = l_deb.id
                    JOIN fact_account_move_lines l_crd ON pr.credit_move_line_id = l_crd.id
                    JOIN fact_account_moves m_crd ON l_crd.account_move_id = m_crd.id
                    LEFT JOIN dim_account_journals j_crd ON m_crd.journal_id = j_crd.id
                    WHERE 1=1 {t_sql_pr1}
                      {pr_end_date_sql}
                      {lines_date_filter_pr}
                      {f_sql_deb}
                      {acct_type_filter_deb}
                      {acct_type_filter_crd}
                      {p_filter_deb}
                      AND (l_deb.partner_id IS DISTINCT FROM l_crd.partner_id)
                      {cross_pr_filter}

                    UNION ALL

                    -- Cross-partner partial reconcile debit side (for credit partner)
                    SELECT
                        pr.max_date AS entry_date,
                        COALESCE(j_deb.code, 'RECON') AS journal,
                        l_crd.account_code,
                        pr.max_date AS invoice_date,
                        NULL AS due_date,
                        COALESCE(m_deb.odoo_name, m_deb.ref, 'Cross-Partner Reconcile Offset') AS matching,
                        l_crd.currency_code,
                        pr.amount AS amount_currency,
                        pr.amount AS debit,
                        0.00 AS credit,
                        pr.amount AS balance,
                        999999999 AS sort_id
                    FROM fact_account_partial_reconciles pr
                    JOIN fact_account_move_lines l_deb ON pr.debit_move_line_id = l_deb.id
                    JOIN fact_account_move_lines l_crd ON pr.credit_move_line_id = l_crd.id
                    JOIN fact_account_moves m_deb ON l_deb.account_move_id = m_deb.id
                    LEFT JOIN dim_account_journals j_deb ON m_deb.journal_id = j_deb.id
                    WHERE 1=1 {t_sql_pr2}
                      {pr_end_date_sql}
                      {lines_date_filter_pr}
                      {f_sql_crd}
                      {acct_type_filter_deb}
                      {acct_type_filter_crd}
                      {p_filter_crd}
                      AND (l_deb.partner_id IS DISTINCT FROM l_crd.partner_id)
                      {cross_pr_filter}
                )
                SELECT *
                FROM partner_detail_lines
                ORDER BY entry_date ASC, sort_id ASC
                LIMIT :line_limit
            """
            lines_data = run_query(lines_query, line_params)

            p_lines = []
            running_bal = init_bal
            if date_from and (abs(init_deb) > 0.001 or abs(init_crd) > 0.001 or abs(init_bal) > 0.001):
                p_lines.append({
                    "date": date_from,
                    "journal": "INIT",
                    "account_code": "",
                    "invoice_date": None,
                    "due_date": None,
                    "matching": "Initial Balance",
                    "currency": p_dict["currency"],
                    "amount_currency": init_bal,
                    "debit": init_deb,
                    "credit": init_crd,
                    "balance": init_bal,
                })

            for line in lines_data:
                l_debit = float(line.get('debit') or 0)
                l_credit = float(line.get('credit') or 0)
                running_bal += l_debit - l_credit
                p_lines.append({
                    "date": str(line.get('entry_date')),
                    "journal": line.get('journal') or "MISC",
                    "account_code": line.get('account_code') or "",
                    "invoice_date": str(line.get('invoice_date')) if line.get('invoice_date') else None,
                    "due_date": str(line.get('due_date')) if line.get('due_date') else None,
                    "matching": line.get('matching') or "",
                    "currency": line.get('currency_code') or p_dict["currency"],
                    "amount_currency": float(line.get('amount_currency')) if line.get('amount_currency') is not None else None,
                    "debit": l_debit,
                    "credit": l_credit,
                    "balance": round(running_bal, 2),
                })
            p_dict["lines"] = p_lines

        partners.append(p_dict)

    grand_total_debit = sum(p["debit"] for p in partners)
    grand_total_credit = sum(p["credit"] for p in partners)
    grand_net_balance = sum(p["balance"] for p in partners)

    # Format period label
    if date_from and target_end_date:
        period_label = f"{date_from} to {target_end_date}"
    elif target_end_date:
        period_label = f"As of {target_end_date}"
    else:
        period_label = "All Time"

    return {
        "tool_name": "get_partner_ledger_tool",
        "scope": scope_str,
        "period": period_label,
        "date_from": date_from,
        "date_to": target_end_date,
        "unreconciled_only": unreconciled_only,
        "columns": [
            "Journal", "Account", "Invoice Date", "Due Date",
            "Matching", "Debit", "Credit", "Amount Currency", "Balance"
        ],
        "total_partners_count": len(partners),
        "total_debit": grand_total_debit,
        "total_credit": grand_total_credit,
        "net_balance": grand_net_balance,
        "currency": base_currency or "XAF",
        "status": "Net Receivable" if grand_net_balance > 0 else "Net Payable",
        "partners": partners,
    }


# ────────────────────────────────────────────────────────────────────────────────
# 15. CUSTOMER STATEMENT (Report 15)
# ────────────────────────────────────────────────────────────────────────────────

def get_customer_statement_tool(tenant_ids: Optional[list[str]] = None, company_ids: Optional[list[int]] = None, partner_name: str | None = None, partner_id: int | None = None, account_type: str | None = "asset_receivable", date_from: str | None = None, date_to: str | None = None, as_of_date: str | None = None, include_lines: bool = False, limit_partners: int | None = None, limit_lines_per_partner: int = 50, base_currency: str | None = None) -> dict:
    """
    Generates the Customer Statement (Relevé Client, Odoo Report 15) matching Odoo exactly.
    Columns presented:
    - Invoice Date, Due Date, Amount, Amount Currency, Balance
    - Calculates dynamically via SQL queries on fact_account_move_lines (account_type='asset_receivable').
    """
    target_end_date = date_to or as_of_date

    raw_cids = normalize_company_ids(company_ids=company_ids)
    t_ids = normalize_tenant_ids(tenant_ids=tenant_ids)
    resolved_company_ids = []
    company_names = []
    try:
        from odoo_app.models.company import Company
        from django.db.models import Q
        c_qs = Company.objects.all()
        if t_ids:
            c_qs = c_qs.filter(tenant_id__in=t_ids)
        if raw_cids:
            matched_c = c_qs.filter(Q(id__in=raw_cids) | Q(odoo_id__in=raw_cids))
            resolved_company_ids = list(matched_c.values_list('id', flat=True))
            company_names = list(matched_c.values_list('name', flat=True))
        else:
            resolved_company_ids = list(c_qs.values_list('id', flat=True))
            company_names = list(c_qs.values_list('name', flat=True))
    except Exception:
        resolved_company_ids = raw_cids
    scope_str = ", ".join(company_names) if company_names else ("Consolidated" if not raw_cids else f"Companies {raw_cids}")

    # Format period label
    if date_from and target_end_date:
        period_label = f"From {date_from} to {target_end_date}"
    elif target_end_date:
        period_label = f"As of {target_end_date}"
    else:
        period_label = "All Time"

    # Dynamic SQL query on fact_account_move_lines
    t_sql_l, t_params_l = build_tenant_filter_sql(tenant_ids=tenant_ids, column_name="l.tenant_id", prefix="t_l")
    balance_col = build_currency_case_sql('l.balance', tenant_ids=tenant_ids, base_currency=base_currency, currency_column='l.currency_code')

    end_date_sql = ""
    params = {}
    if target_end_date:
        end_date_sql = " AND m.date <= :target_end_date"
        params["target_end_date"] = target_end_date

    partner_sql = ""
    if partner_id:
        partner_sql += " AND (l.partner_id = :partner_id OR p.odoo_id = :partner_id)"
        params["partner_id"] = partner_id
    if partner_name:
        partner_sql += " AND p.name ILIKE :partner_name"
        params["partner_name"] = f"%{partner_name}%"

    f_sql, f_params = build_company_filter_sql(company_ids=resolved_company_ids, column_name="l.company_id")
    params.update(t_params_l)
    params.update(f_params)

    if account_type == "liability_payable":
        acct_type_sql = "AND l.account_type = 'liability_payable'"
    elif account_type in ("both", "all"):
        acct_type_sql = "AND l.account_type IN ('asset_receivable', 'liability_payable')"
    else:
        acct_type_sql = "AND l.account_type = 'asset_receivable'"

    limit_sql = f"LIMIT {int(limit_partners)}" if limit_partners else ""

    date_from_check = "m.date >= :date_from" if date_from else "1=1"
    if date_from:
        params["date_from"] = date_from

    rows = run_query(
        f"""SELECT
                COALESCE(p.name, 'Unknown Partner') AS partner_name,
                l.partner_id,
                COALESCE(SUM({balance_col}), 0) AS balance,
                COALESCE(SUM({balance_col}), 0) AS amount
            FROM fact_account_move_lines l
            JOIN fact_account_moves m ON l.account_move_id = m.id
            LEFT JOIN dim_partners p ON l.partner_id = p.id AND l.tenant_id = p.tenant_id
            WHERE 1=1 {t_sql_l}
              AND m.state = 'posted'
              {acct_type_sql}
              {f_sql}
              {end_date_sql}
              {partner_sql}
            GROUP BY p.name, l.partner_id
            HAVING ABS(COALESCE(SUM({balance_col}), 0)) > 0.001 
                OR ABS(COALESCE(SUM(CASE WHEN {date_from_check} THEN {balance_col} ELSE 0 END), 0)) > 0.001
            ORDER BY p.name NULLS LAST
            {limit_sql}""",
        params,
    )

    partners = []
    for r in rows:
        bal = float(r.get('balance') or 0)
        amt = float(r.get('amount') if r.get('amount') is not None else bal)
        partners.append({
            "partner_name": r.get('partner_name') or "Unknown Partner",
            "partner_id": r.get('partner_id'),
            "currency": base_currency or "XAF",
            "amount": amt,
            "amount_currency": None,
            "balance": bal,
            "status": "Net Receivable" if bal > 0.01 else "Net Payable" if bal < -0.01 else "Settled",
        })

    grand_total_amount = sum(p["amount"] for p in partners)
    grand_net_balance = sum(p["balance"] for p in partners)

    return {
        "tool_name": "get_customer_statement_tool",
        "scope": scope_str,
        "period": period_label,
        "date_from": date_from,
        "date_to": target_end_date,
        "columns": ["Invoice Date", "Due Date", "Amount", "Amount Currency", "Balance"],
        "total_partners_count": len(partners),
        "total_amount": grand_total_amount,
        "net_balance": grand_net_balance,
        "currency": base_currency or "XAF",
        "status": "Net Receivable" if grand_net_balance > 0 else "Net Payable",
        "partners": partners,
    }


# ────────────────────────────────────────────────────────────────────────────────
# 16. FOLLOW-UP REPORT (Report 16)
# ────────────────────────────────────────────────────────────────────────────────

def get_followup_report_tool(tenant_ids: Optional[list[str]] = None, company_ids: Optional[list[int]] = None, partner_name: str | None = None, partner_id: int | None = None, as_of_date: str | None = None, date_to: str | None = None, include_lines: bool = False, limit_partners: int | None = None, limit_lines_per_partner: int = 50, base_currency: str | None = None) -> dict:
    """
    Generates the Follow-Up Report (Rapport de Relance, Odoo Report 16) matching Odoo exactly.
    Columns presented:
    - Invoice Date, Due Date, Amount, Amount Currency, Balance
    - Calculates dynamically via SQL queries on fact_account_move_lines (account_type='asset_receivable').
    """
    raw_date = date_to or as_of_date
    if raw_date and str(raw_date).lower() == "today":
        import datetime
        target_end_date = datetime.date.today().isoformat()
    elif raw_date and str(raw_date).strip().isdigit() and len(str(raw_date).strip()) == 4:
        target_end_date = f"{str(raw_date).strip()}-12-31"
    else:
        target_end_date = raw_date

    # Resolve company scope display name
    raw_cids = normalize_company_ids(company_ids=company_ids)
    t_ids = normalize_tenant_ids(tenant_ids=tenant_ids)
    resolved_company_ids = []
    company_names = []
    try:
        from odoo_app.models.company import Company
        from django.db.models import Q
        c_qs = Company.objects.all()
        if t_ids:
            c_qs = c_qs.filter(tenant_id__in=t_ids)
        if raw_cids:
            matched_c = c_qs.filter(Q(id__in=raw_cids) | Q(odoo_id__in=raw_cids))
            resolved_company_ids = list(matched_c.values_list('id', flat=True))
            company_names = list(matched_c.values_list('name', flat=True))
        else:
            resolved_company_ids = list(c_qs.values_list('id', flat=True))
            company_names = list(c_qs.values_list('name', flat=True))
    except Exception:
        resolved_company_ids = raw_cids
    scope_str = ", ".join(company_names) if company_names else ("Consolidated" if not raw_cids else f"Companies {raw_cids}")

    period_label = f"As of {target_end_date}" if target_end_date else "All Time"

    # Dynamic SQL query (receivables only)
    t_sql_l, t_params_l = build_tenant_filter_sql(tenant_ids=tenant_ids, column_name="l.tenant_id", prefix="t_l")
    balance_col = build_currency_case_sql('l.balance', tenant_ids=tenant_ids, base_currency=base_currency, currency_column='l.currency_code')

    end_date_sql = ""
    params = {}
    if target_end_date:
        end_date_sql = " AND m.date <= :target_end_date"
        params["target_end_date"] = target_end_date

    partner_sql = ""
    if partner_id:
        partner_sql += " AND (l.partner_id = :partner_id OR p.odoo_id = :partner_id)"
        params["partner_id"] = partner_id
    if partner_name:
        partner_sql += " AND p.name ILIKE :partner_name"
        params["partner_name"] = f"%{partner_name}%"

    f_sql, f_params = build_company_filter_sql(company_ids=resolved_company_ids, column_name="l.company_id")
    params.update(t_params_l)
    params.update(f_params)

    limit_sql = f"LIMIT {int(limit_partners)}" if limit_partners else ""

    rows = run_query(
        f"""SELECT
                COALESCE(p.name, 'Unknown Partner') AS partner_name,
                l.partner_id,
                COALESCE(SUM({balance_col}), 0) AS balance,
                COALESCE(SUM({balance_col}), 0) AS amount
            FROM fact_account_move_lines l
            JOIN fact_account_moves m ON l.account_move_id = m.id
            LEFT JOIN dim_partners p ON l.partner_id = p.id AND l.tenant_id = p.tenant_id
            WHERE 1=1 {t_sql_l}
              AND m.state = 'posted'
              AND l.account_type = 'asset_receivable'
              {f_sql}
              {end_date_sql}
              {partner_sql}
            GROUP BY p.name, l.partner_id
            HAVING COALESCE(SUM({balance_col}), 0) > 0.001
            ORDER BY balance DESC, p.name NULLS LAST
            {limit_sql}""",
        params,
    )

    partners = []
    for r in rows:
        bal = float(r.get('balance') or 0)
        amt = float(r.get('amount') if r.get('amount') is not None else bal)
        p_dict = {
            "partner_name": r.get('partner_name') or "Unknown Partner",
            "partner_id": r.get('partner_id'),
            "currency": base_currency or "XAF",
            "amount": amt,
            "amount_currency": None,
            "balance": bal,
            "status": "Overdue" if bal > 0.01 else "Settled",
        }

        if include_lines or partner_name or partner_id:
            line_params = params.copy()
            line_params["p_id"] = r.get('partner_id')
            line_params["line_limit"] = int(limit_lines_per_partner)
            p_filter = "AND l.partner_id = :p_id" if r.get('partner_id') else "AND l.partner_id IS NULL"
            lines_data = run_query(
                f"""SELECT
                        m.invoice_date,
                        m.invoice_date_due AS due_date,
                        COALESCE(m.odoo_name, m.ref, l.name, '') AS name,
                        l.currency_code,
                        l.amount_currency,
                        COALESCE({balance_col}, 0) AS amount,
                        COALESCE({balance_col}, 0) AS balance
                    FROM fact_account_move_lines l
                    JOIN fact_account_moves m ON l.account_move_id = m.id
                    LEFT JOIN dim_partners p ON l.partner_id = p.id
                    WHERE 1=1 {t_sql_l}
                      AND m.state = 'posted'
                      AND l.account_type = 'asset_receivable'
                      {p_filter}
                      {f_sql}
                      {end_date_sql}
                    ORDER BY m.date ASC, l.id ASC
                    LIMIT :line_limit""",
                line_params,
            )
            p_lines = []
            running_bal = 0.0
            for line in lines_data:
                l_amt = float(line.get("amount") or 0)
                running_bal += l_amt
                p_lines.append({
                    "invoice_date": str(line.get("invoice_date")) if line.get("invoice_date") else None,
                    "due_date": str(line.get("due_date")) if line.get("due_date") else None,
                    "name": line.get("name") or "",
                    "amount": l_amt,
                    "currency": line.get("currency_code") or p_dict["currency"],
                    "amount_currency": float(line.get("amount_currency")) if line.get("amount_currency") is not None else None,
                    "balance": round(running_bal, 2),
                })
            p_dict["lines"] = p_lines

        partners.append(p_dict)

    grand_total_amount = sum(p["amount"] for p in partners)
    grand_net_balance = sum(p["balance"] for p in partners)

    return {
        "tool_name": "get_followup_report_tool",
        "scope": scope_str,
        "period": period_label,
        "as_of_date": target_end_date,
        "columns": ["Invoice Date", "Due Date", "Amount", "Amount Currency", "Balance"],
        "total_partners_count": len(partners),
        "total_amount": grand_total_amount,
        "net_balance": grand_net_balance,
        "currency": base_currency or "XAF",
        "status": "Net Receivable" if grand_net_balance > 0 else "Net Payable",
        "partners": partners,
    }


