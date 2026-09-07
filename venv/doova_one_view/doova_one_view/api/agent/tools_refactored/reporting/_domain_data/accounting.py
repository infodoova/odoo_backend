# doova_one_view/api/agent/tools_refactored/reporting/_domain_data/accounting.py

import logging
from typing import Optional, List, Dict, Any

from .._formatters import _fmt_money
from .._variance import _build_kpi_variance

logger = logging.getLogger(__name__)


def enrich(
    data: dict,
    pnl_ctx: dict,
    tenant_ids: list[str] | None = None,
    company_ids: list[int] | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
    base_currency: str | None = None,
    currency: str = "XAF",
    prior_start: str | None = None,
    prior_end: str | None = None,
    comparison_label: str = "",
) -> None:
    """Enriches data dict with Accounting & GL telemetry (6-bucket AR/AP aging, expenses, working capital)."""
    from doova_one_view.api.agent.tools_refactored.finance import (
        get_receivables_analysis_tool,
        get_payables_analysis_tool,
        get_aging_analysis_tool,
        get_expense_breakdown_tool,
        get_balance_sheet_tool,
        get_working_capital_tool,
        get_trial_balance_tool,
    )

    try:
        receivables = get_receivables_analysis_tool(tenant_ids=tenant_ids, company_ids=company_ids, base_currency=base_currency)
        payables = get_payables_analysis_tool(tenant_ids=tenant_ids, company_ids=company_ids, base_currency=base_currency)
        ar_aging_data = get_aging_analysis_tool(tenant_ids=tenant_ids, company_ids=company_ids, direction="receivable", base_currency=base_currency, as_of_date=end_date)
        ap_aging_data = get_aging_analysis_tool(tenant_ids=tenant_ids, company_ids=company_ids, direction="payable", base_currency=base_currency, as_of_date=end_date)
        expenses_data = get_expense_breakdown_tool(tenant_ids=tenant_ids, company_ids=company_ids, start_date=start_date, end_date=end_date, base_currency=base_currency)
        bs = get_balance_sheet_tool(tenant_ids=tenant_ids, company_ids=company_ids, as_of_date=end_date, base_currency=base_currency)
        wc = get_working_capital_tool(tenant_ids=tenant_ids, company_ids=company_ids, base_currency=base_currency)

        prior_bs = {}
        if prior_end:
            try:
                prior_bs = get_balance_sheet_tool(tenant_ids=tenant_ids, company_ids=company_ids, as_of_date=prior_end, base_currency=base_currency)
            except Exception:
                pass

        ar_total = float(bs.get("receivables", 0) or receivables.get("total_receivables", 0) or ar_aging_data.get("total", 0) or 0)
        ap_total = float(bs.get("payables", 0) or payables.get("total_payables", 0) or ap_aging_data.get("total", 0) or 0)

        prior_ar = float(prior_bs.get("receivables", 0) or 0.0)
        prior_ap = float(prior_bs.get("payables", 0) or 0.0)
        prior_cash = float(prior_bs.get("bank_and_cash_accounts", 0) or 0.0)
        prior_assets = float(prior_bs.get("total_assets", prior_bs.get("current_assets", 0)) or 0.0)
        prior_wc = float(prior_bs.get("current_assets", 0) or 0.0) - float(prior_bs.get("current_liabilities", 0) or 0.0)
        prior_cr = float(prior_bs.get("current_ratio", 0) or 0.0)

        # 6-Bucket AR Aging Calculation
        ar_c = float(ar_aging_data.get("current", 0) or 0.0)
        ar_c_cnt = int(ar_aging_data.get("current_cnt", 0) or 0)
        ar_d1 = float(ar_aging_data.get("1_30_days", 0) or 0.0)
        ar_d1_cnt = int(ar_aging_data.get("1_30_days_cnt", 0) or 0)
        ar_d2 = float(ar_aging_data.get("31_60_days", 0) or 0.0)
        ar_d2_cnt = int(ar_aging_data.get("31_60_days_cnt", 0) or 0)
        ar_d3 = float(ar_aging_data.get("61_90_days", 0) or 0.0)
        ar_d3_cnt = int(ar_aging_data.get("61_90_days_cnt", 0) or 0)
        ar_d4 = float(ar_aging_data.get("91_120_days", 0) or 0.0)
        ar_d4_cnt = int(ar_aging_data.get("91_120_days_cnt", 0) or 0)
        ar_older = float(ar_aging_data.get("older", 0) or 0.0)
        ar_older_cnt = int(ar_aging_data.get("older_cnt", 0) or 0)
        
        ar_calc_total = ar_c + ar_d1 + ar_d2 + ar_d3 + ar_d4 + ar_older
        if ar_total == 0:
            ar_total = ar_calc_total
        total_ar_cnt = ar_c_cnt + ar_d1_cnt + ar_d2_cnt + ar_d3_cnt + ar_d4_cnt + ar_older_cnt

        ar_aging_rows = [
            {
                "bracket": "current",
                "count": ar_c_cnt,
                "count_formatted": f"{ar_c_cnt:,} Invoices",
                "amount": _fmt_money(ar_c, currency),
                "share": f"{(ar_c / ar_total * 100):.1f}%" if ar_total > 0 else "0.0%",
                "risk": "Low",
                "badge_class": "badge-success",
            },
            {
                "bracket": "1-30 days",
                "count": ar_d1_cnt,
                "count_formatted": f"{ar_d1_cnt:,} Invoices",
                "amount": _fmt_money(ar_d1, currency),
                "share": f"{(ar_d1 / ar_total * 100):.1f}%" if ar_total > 0 else "0.0%",
                "risk": "Normal",
                "badge_class": "badge-info",
            },
            {
                "bracket": "31-60 days",
                "count": ar_d2_cnt,
                "count_formatted": f"{ar_d2_cnt:,} Invoices",
                "amount": _fmt_money(ar_d2, currency),
                "share": f"{(ar_d2 / ar_total * 100):.1f}%" if ar_total > 0 else "0.0%",
                "risk": "Moderate",
                "badge_class": "badge-warning",
            },
            {
                "bracket": "61-90 days",
                "count": ar_d3_cnt,
                "count_formatted": f"{ar_d3_cnt:,} Invoices",
                "amount": _fmt_money(ar_d3, currency),
                "share": f"{(ar_d3 / ar_total * 100):.1f}%" if ar_total > 0 else "0.0%",
                "risk": "Watch",
                "badge_class": "badge-warning",
            },
            {
                "bracket": "91-120 days",
                "count": ar_d4_cnt,
                "count_formatted": f"{ar_d4_cnt:,} Invoices",
                "amount": _fmt_money(ar_d4, currency),
                "share": f"{(ar_d4 / ar_total * 100):.1f}%" if ar_total > 0 else "0.0%",
                "risk": "Elevated",
                "badge_class": "badge-warning",
            },
            {
                "bracket": "Older",
                "count": ar_older_cnt,
                "count_formatted": f"{ar_older_cnt:,} Invoices",
                "amount": _fmt_money(ar_older, currency),
                "share": f"{(ar_older / ar_total * 100):.1f}%" if ar_total > 0 else "0.0%",
                "risk": "High Risk",
                "badge_class": "badge-danger",
            },
        ]

        # 6-Bucket AP Aging Calculation
        ap_c = float(ap_aging_data.get("current", 0) or 0.0)
        ap_c_cnt = int(ap_aging_data.get("current_cnt", 0) or 0)
        ap_d1 = float(ap_aging_data.get("1_30_days", 0) or 0.0)
        ap_d1_cnt = int(ap_aging_data.get("1_30_days_cnt", 0) or 0)
        ap_d2 = float(ap_aging_data.get("31_60_days", 0) or 0.0)
        ap_d2_cnt = int(ap_aging_data.get("31_60_days_cnt", 0) or 0)
        ap_d3 = float(ap_aging_data.get("61_90_days", 0) or 0.0)
        ap_d3_cnt = int(ap_aging_data.get("61_90_days_cnt", 0) or 0)
        ap_d4 = float(ap_aging_data.get("91_120_days", 0) or 0.0)
        ap_d4_cnt = int(ap_aging_data.get("91_120_days_cnt", 0) or 0)
        ap_older = float(ap_aging_data.get("older", 0) or 0.0)
        ap_older_cnt = int(ap_aging_data.get("older_cnt", 0) or 0)

        ap_calc_total = ap_c + ap_d1 + ap_d2 + ap_d3 + ap_d4 + ap_older
        if ap_total == 0:
            ap_total = ap_calc_total
        total_ap_cnt = ap_c_cnt + ap_d1_cnt + ap_d2_cnt + ap_d3_cnt + ap_d4_cnt + ap_older_cnt

        ap_aging_rows = [
            {
                "bracket": "current",
                "count": ap_c_cnt,
                "count_formatted": f"{ap_c_cnt:,} Bills",
                "amount": _fmt_money(ap_c, currency),
                "share": f"{(ap_c / ap_total * 100):.1f}%" if ap_total > 0 else "0.0%",
                "risk": "Low",
                "badge_class": "badge-success",
            },
            {
                "bracket": "1-30 days",
                "count": ap_d1_cnt,
                "count_formatted": f"{ap_d1_cnt:,} Bills",
                "amount": _fmt_money(ap_d1, currency),
                "share": f"{(ap_d1 / ap_total * 100):.1f}%" if ap_total > 0 else "0.0%",
                "risk": "Normal",
                "badge_class": "badge-info",
            },
            {
                "bracket": "31-60 days",
                "count": ap_d2_cnt,
                "count_formatted": f"{ap_d2_cnt:,} Bills",
                "amount": _fmt_money(ap_d2, currency),
                "share": f"{(ap_d2 / ap_total * 100):.1f}%" if ap_total > 0 else "0.0%",
                "risk": "Moderate",
                "badge_class": "badge-warning",
            },
            {
                "bracket": "61-90 days",
                "count": ap_d3_cnt,
                "count_formatted": f"{ap_d3_cnt:,} Bills",
                "amount": _fmt_money(ap_d3, currency),
                "share": f"{(ap_d3 / ap_total * 100):.1f}%" if ap_total > 0 else "0.0%",
                "risk": "Watch",
                "badge_class": "badge-warning",
            },
            {
                "bracket": "91-120 days",
                "count": ap_d4_cnt,
                "count_formatted": f"{ap_d4_cnt:,} Bills",
                "amount": _fmt_money(ap_d4, currency),
                "share": f"{(ap_d4 / ap_total * 100):.1f}%" if ap_total > 0 else "0.0%",
                "risk": "Elevated",
                "badge_class": "badge-warning",
            },
            {
                "bracket": "Older",
                "count": ap_older_cnt,
                "count_formatted": f"{ap_older_cnt:,} Bills",
                "amount": _fmt_money(ap_older, currency),
                "share": f"{(ap_older / ap_total * 100):.1f}%" if ap_total > 0 else "0.0%",
                "risk": "High Risk",
                "badge_class": "badge-danger",
            },
        ]

        # General Ledger Trial Balance & Category Classification (as of period end, matching Odoo GL cumulative state)
        tb_data = get_trial_balance_tool(
            tenant_ids=tenant_ids,
            company_ids=company_ids,
            as_of_date=end_date,
            base_currency=base_currency,
        )

        raw_accounts = tb_data.get("accounts", [])
        active_gl_accounts = [
            {
                "code": a.get("code") or "—",
                "name": a.get("name") or "—",
                "debit": _fmt_money(float(a.get("debit", 0) or 0), currency),
                "credit": _fmt_money(float(a.get("credit", 0) or 0), currency),
                "balance": _fmt_money(float(a.get("balance", 0) or 0), currency),
                "balance_raw": float(a.get("balance", 0) or 0),
            }
            for a in raw_accounts
            if abs(float(a.get("debit", 0) or 0)) > 0.01 or abs(float(a.get("credit", 0) or 0)) > 0.01 or abs(float(a.get("balance", 0) or 0)) > 0.01
        ]
        # Order by account code matching Odoo general ledger statutory sequence
        active_gl_accounts.sort(key=lambda x: str(x["code"]))

        from doova_one_view.api.agent.tools_refactored.common import run_query, build_tenant_filter_sql, build_company_filter_sql, build_currency_case_sql, normalize_company_ids
        
        t_sql_l, t_params_l = build_tenant_filter_sql(tenant_ids, column_name="l.tenant_id", prefix="t_l")
        balance_col = build_currency_case_sql('l.balance', tenant_ids=tenant_ids, base_currency=base_currency, currency_column='c.currency_code')
        debit_col = build_currency_case_sql('l.debit', tenant_ids=tenant_ids, base_currency=base_currency, currency_column='c.currency_code')
        credit_col = build_currency_case_sql('l.credit', tenant_ids=tenant_ids, base_currency=base_currency, currency_column='c.currency_code')
        f_sql, f_params = build_company_filter_sql(company_ids, column_name="l.company_id")
        
        gl_params = {"end_date": end_date}
        gl_params.update(t_params_l)
        gl_params.update(f_params)
        
        category_rows = run_query(
            f"""SELECT 
                    CASE 
                        WHEN l.account_type LIKE 'asset%' THEN '1. Assets'
                        WHEN l.account_type LIKE 'liability%' THEN '2. Liabilities'
                        WHEN l.account_type LIKE 'equity%' THEN '3. Equity'
                        WHEN l.account_type LIKE 'income%' THEN '4. Revenue & Income'
                        WHEN l.account_type LIKE 'expense%' THEN '5. Operating & Direct Expenses'
                        ELSE '6. Other Accounts'
                    END as category,
                    COUNT(DISTINCT l.account_code) as accounts_count,
                    COALESCE(SUM({debit_col}), 0) as total_debit,
                    COALESCE(SUM({credit_col}), 0) as total_credit,
                    COALESCE(SUM({balance_col}), 0) as net_balance
                FROM fact_account_move_lines l
                JOIN fact_account_moves m ON l.account_move_id = m.id
                LEFT JOIN dim_companies c ON l.company_id = c.id
                WHERE 1=1 {t_sql_l}
                  AND m.state = 'posted'
                  {f_sql}
                  AND m.date <= :end_date
                GROUP BY 1
                ORDER BY 1""",
            gl_params
        )
        
        gl_categories = []
        for r in category_rows:
            deb = float(r.get("total_debit") or 0.0)
            crd = float(r.get("total_credit") or 0.0)
            bal = float(r.get("net_balance") or 0.0)
            if deb > 0 or crd > 0 or abs(bal) > 0:
                gl_categories.append({
                    "category": r.get("category"),
                    "accounts_count": int(r.get("accounts_count") or 0),
                    "total_debit": _fmt_money(deb, currency),
                    "total_credit": _fmt_money(crd, currency),
                    "net_balance": _fmt_money(bal, currency),
                })

        data.update({
            "accounts_receivable": _build_kpi_variance(ar_total, prior_ar, currency, fmt="money", polarity="neutral"),
            "ar": _build_kpi_variance(ar_total, prior_ar, currency, fmt="money", polarity="neutral"),
            "total_receivables_formatted": _fmt_money(ar_total, currency),
            "total_ar_count_formatted": f"{total_ar_cnt:,} Invoices",
            "accounts_payable": _build_kpi_variance(ap_total, prior_ap, currency, fmt="money", polarity="negative"),
            "ap": _build_kpi_variance(ap_total, prior_ap, currency, fmt="money", polarity="negative"),
            "total_payables_formatted": _fmt_money(ap_total, currency),
            "total_ap_count_formatted": f"{total_ap_cnt:,} Bills",
            "cash": _build_kpi_variance(float(bs.get("bank_and_cash_accounts", 0) or 0), prior_cash, currency, fmt="money", polarity="positive"),
            "working_capital": _build_kpi_variance(float(wc.get("working_capital", 0) or 0), prior_wc, currency, fmt="money", polarity="positive"),
            "current_ratio": _build_kpi_variance(float(wc.get("current_ratio", 0) or 0), prior_cr, currency, fmt="ratio", polarity="positive"),
            "total_assets": _build_kpi_variance(float(bs.get("total_assets", 0) or bs.get("current_assets", 0) or 0), prior_assets, currency, fmt="money", polarity="positive"),
            "expense_breakdown": expenses_data.get("expenses", []),
            "ar_aging": ar_aging_rows,
            "ap_aging": ap_aging_rows,
            "gl_categories": gl_categories,
            "gl_accounts": active_gl_accounts,
            "gl_top_accounts": active_gl_accounts,
            "trial_balance": active_gl_accounts,
            "tb_accounts_count": len(active_gl_accounts),
            "tb_total_debit_formatted": _fmt_money(float(tb_data.get("total_debit", 0) or 0), currency),
            "tb_total_credit_formatted": _fmt_money(float(tb_data.get("total_credit", 0) or 0), currency),
            "tb_variance_formatted": _fmt_money(float(tb_data.get("variance", 0) or 0), currency),
            "tb_integrity": tb_data.get("integrity_check", "BALANCED"),
        })
    except Exception as e:
        logger.warning(f"Accounting domain query error: {e}")
