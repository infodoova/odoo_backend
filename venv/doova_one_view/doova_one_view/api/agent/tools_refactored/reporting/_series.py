# doova_one_view/api/agent/tools_refactored/reporting/_series.py

from typing import Optional, List, Dict, Any

from doova_one_view.api.agent.query_context import (
    build_tenant_filter_sql,
    build_company_filter_sql,
)
from doova_one_view.api.agent.db import run_query
from ..common import build_currency_case_sql


def _get_monthly_pnl_series(
    tenant_ids: Optional[list[str]] = None,
    company_ids: list[int] | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
    base_currency: str | None = None,
) -> list[dict]:
    """Query real monthly income, expenses, and net profit from the GL scoped to date range."""
    t_sql_ts, t_params_ts = build_tenant_filter_sql(tenant_ids, column_name="l.tenant_id", prefix="t_ts")
    balance_col_ts = build_currency_case_sql('l.balance', tenant_ids=tenant_ids, base_currency=base_currency, currency_column='c.currency_code')
    f_sql_ts, f_params_ts = build_company_filter_sql(company_ids, column_name="l.company_id")
    params = {}
    params.update(t_params_ts)
    params.update(f_params_ts)

    date_filter = ""
    if start_date:
        date_filter += " AND m.date >= :start_date"
        params["start_date"] = start_date
    if end_date:
        date_filter += " AND m.date <= :end_date"
        params["end_date"] = end_date

    rows = run_query(
        f"""SELECT
                DATE_TRUNC('month', m.date) AS period,
                COALESCE(SUM(CASE WHEN l.account_type LIKE 'income%%' THEN {balance_col_ts} ELSE 0 END) * -1, 0) AS revenue,
                COALESCE(SUM(CASE WHEN l.account_type LIKE 'expense%%' THEN {balance_col_ts} ELSE 0 END), 0) AS expenses
            FROM fact_account_move_lines l
            JOIN fact_account_moves m ON l.account_move_id = m.id
            LEFT JOIN dim_companies c ON l.company_id = c.id
            WHERE 1=1 {t_sql_ts}
              AND m.state = 'posted'
              AND m.date IS NOT NULL
              {date_filter}
              {f_sql_ts}
            GROUP BY period
            ORDER BY period ASC""",
        params,
    )
    return [
        {
            "period": str(r.get("period", ""))[:10],
            "revenue": float(r.get("revenue", 0) or 0),
            "expenses": float(r.get("expenses", 0) or 0),
            "net_profit": float(r.get("revenue", 0) or 0) - float(r.get("expenses", 0) or 0),
        }
        for r in rows
    ]


def _get_domain_trend_series(
    domain: str,
    tenant_ids: Optional[list[str]] = None,
    company_ids: list[int] | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
    base_currency: str | None = None,
) -> list[dict]:
    """
    Returns monthly time series data scoped to the specific domain and date range.
    - sales / commercial: queries fact_sales_orders matching sales KPI data sources
    - purchase / purchasing: queries fact_purchase_orders matching procurement KPI data sources
    - inventory / stock: returns empty (domain uses dedicated stock valuation/aging visualizers)
    - accounting / pnl / health / general / cashflow: queries fact_account_move_lines (GL-based P&L series)
    """
    domain = (domain or "general").lower()
    if domain in ("sales", "commercial"):
        t_sql_def, t_params_def = build_tenant_filter_sql(tenant_ids, column_name="o.tenant_id", prefix="t_def")
        amount_col = build_currency_case_sql('o.amount_total', tenant_ids=tenant_ids, base_currency=base_currency)
        params: dict = {}
        params.update(t_params_def)
        f_sql, f_params = build_company_filter_sql(company_ids, column_name="o.company_id")
        params.update(f_params)

        date_filter = ""
        if start_date:
            date_filter += " AND o.date_order >= :start_date"
            params["start_date"] = start_date
        if end_date:
            date_filter += " AND o.date_order < (CAST(:end_date AS date) + INTERVAL '1 day')"
            params["end_date"] = end_date

        rows = run_query(
            f"""SELECT 
                    DATE_TRUNC('month', o.date_order) AS period, 
                    COALESCE(SUM({amount_col}), 0) AS revenue, 
                    COUNT(o.id) AS order_count 
                FROM fact_sales_orders o
                WHERE 1=1 {t_sql_def} 
                  AND o.state IN ('sale', 'done') 
                  AND o.date_order IS NOT NULL
                  {date_filter}
                  {f_sql}
                GROUP BY period 
                ORDER BY period ASC""",
            params,
        )
        return [
            {
                "period": str(r.get("period", ""))[:10],
                "revenue": float(r.get("revenue", 0) or 0),
                "order_count": int(r.get("order_count", 0) or 0),
            }
            for r in rows
        ]

    elif domain in ("purchase", "purchasing", "procurement"):
        t_sql_def, t_params_def = build_tenant_filter_sql(tenant_ids, column_name="po.tenant_id", prefix="t_def")
        amount_col = build_currency_case_sql('po.amount_total', tenant_ids=tenant_ids, base_currency=base_currency)
        params = {}
        params.update(t_params_def)
        f_sql, f_params = build_company_filter_sql(company_ids, column_name="po.company_id")
        params.update(f_params)

        date_filter = ""
        if start_date:
            date_filter += " AND po.date_order >= :start_date"
            params["start_date"] = start_date
        if end_date:
            date_filter += " AND po.date_order < (CAST(:end_date AS date) + INTERVAL '1 day')"
            params["end_date"] = end_date

        rows = run_query(
            f"""SELECT 
                    DATE_TRUNC('month', po.date_order) AS period, 
                    COALESCE(SUM({amount_col}), 0) AS revenue, 
                    COUNT(po.id) AS order_count 
                FROM fact_purchase_orders po
                WHERE 1=1 {t_sql_def} 
                  AND po.state IN ('purchase', 'done') 
                  AND po.date_order IS NOT NULL
                  {date_filter}
                  {f_sql}
                GROUP BY period 
                ORDER BY period ASC""",
            params,
        )
        return [
            {
                "period": str(r.get("period", ""))[:10],
                "revenue": float(r.get("revenue", 0) or 0),
                "order_count": int(r.get("order_count", 0) or 0),
            }
            for r in rows
        ]

    elif domain in ("inventory", "stock"):
        return []

    else:
        return _get_monthly_pnl_series(
            tenant_ids=tenant_ids,
            company_ids=company_ids,
            start_date=start_date,
            end_date=end_date,
            base_currency=base_currency,
        )
