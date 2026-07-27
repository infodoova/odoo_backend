"""
Deterministic SQL Pre-Checks for Nexus Proactive Alert Intelligence.

Executes ultra-fast SQL assertions against the data warehouse before invoking LLM agents.
If all pre-checks pass (no anomalies found), the background alert job skips expensive LLM inference completely.
"""

import logging
from typing import Dict, List, Tuple, Optional
from doova_one_view.api.agent.db import run_query
from doova_one_view.api.agent.config import AgentConfig
from doova_one_view.api.agent.query_context import build_company_filter_sql, build_tenant_filter_sql, normalize_company_ids

logger = logging.getLogger(__name__)


def check_cash_drop(tenant_id: str, company_ids: Optional[List[int]] = None, tenant_ids: Optional[List[str]] = None) -> Tuple[bool, str]:
    """Check if current cash balance dropped > ALERT_CASH_DROP_PCT vs 7-day average."""
    t_sql_l, t_params_l = build_tenant_filter_sql(tenant_id, tenant_ids, column_name="l.tenant_id", prefix="t_l")
    f_sql, f_params = build_company_filter_sql(tenant_id, normalize_company_ids(companies=company_ids), column_name="l.company_id")
    params = {**t_params_l, **f_params}

    query = f"""
        WITH cash_moves AS (
            SELECT
                m.date,
                SUM(l.balance) as daily_net
            FROM fact_account_move_lines l
            JOIN fact_account_moves m ON l.account_move_id = m.id
            WHERE 1=1 {t_sql_l}
              AND l.account_type = 'asset_cash'
              AND m.state = 'posted'
              {f_sql}
            GROUP BY m.date
        ),
        stats AS (
            SELECT
                COALESCE(SUM(CASE WHEN date >= CURRENT_DATE - INTERVAL '1 day' THEN daily_net END), 0) as recent_cash,
                COALESCE(AVG(daily_net), 0) as avg_cash_7d
            FROM cash_moves
            WHERE date >= CURRENT_DATE - INTERVAL '7 days'
        )
        SELECT recent_cash, avg_cash_7d FROM stats
    """
    try:
        rows = run_query(query, params)
        if not rows:
            return False, ""
        row = rows[0]
        recent = float(row.get("recent_cash") or 0)
        avg_7d = float(row.get("avg_cash_7d") or 0)

        threshold_pct = getattr(AgentConfig, "ALERT_CASH_DROP_PCT", 20.0)
        if avg_7d > 0 and recent < avg_7d * (1 - threshold_pct / 100.0):
            drop_pct = round((1 - recent / avg_7d) * 100, 1)
            msg = f"Cash inflow/balance dropped by {drop_pct}% in recent period (vs 7-day avg of ${avg_7d:,.2f})."
            return True, msg
    except Exception as e:
        logger.error(f"Error in check_cash_drop precheck: {e}")

    return False, ""


def check_overdue_ar(tenant_id: str, company_ids: Optional[List[int]] = None, tenant_ids: Optional[List[str]] = None) -> Tuple[bool, str]:
    """Check if overdue receivables exceed ALERT_AR_OVERDUE_RATIO threshold."""
    t_sql, t_params = build_tenant_filter_sql(tenant_id, tenant_ids, column_name="tenant_id", prefix="t_ar")
    f_sql, f_params = build_company_filter_sql(tenant_id, normalize_company_ids(companies=company_ids))
    params = {**t_params, **f_params}

    query = f"""
        SELECT 
            COALESCE(SUM(amount_residual), 0) AS total_ar,
            COALESCE(SUM(CASE WHEN invoice_date_due < CURRENT_DATE THEN amount_residual ELSE 0 END), 0) AS overdue_ar
        FROM fact_account_moves
        WHERE 1=1 {t_sql}
          AND move_type = 'out_invoice'
          AND state = 'posted'
          AND payment_state IN ('not_paid', 'partial')
          {f_sql}
    """
    try:
        rows = run_query(query, params)
        if not rows:
            return False, ""
        row = rows[0]
        total_ar = float(row.get("total_ar") or 0)
        overdue_ar = float(row.get("overdue_ar") or 0)

        threshold_ratio = getattr(AgentConfig, "ALERT_AR_OVERDUE_RATIO", 0.30)
        if total_ar > 0:
            ratio = overdue_ar / total_ar
            if ratio >= threshold_ratio:
                ratio_pct = round(ratio * 100, 1)
                msg = f"High Accounts Receivable Overdue Ratio: {ratio_pct}% of AR is past due (${overdue_ar:,.2f} / ${total_ar:,.2f})."
                return True, msg
    except Exception as e:
        logger.error(f"Error in check_overdue_ar precheck: {e}")

    return False, ""


def check_revenue_anomaly(tenant_id: str, company_ids: Optional[List[int]] = None, tenant_ids: Optional[List[str]] = None) -> Tuple[bool, str]:
    """Check if revenue in last 24h deviates by > ALERT_REVENUE_DEVIATION_PCT from 30-day daily avg."""
    t_sql, t_params = build_tenant_filter_sql(tenant_id, tenant_ids, column_name="tenant_id", prefix="t_rev")
    f_sql, f_params = build_company_filter_sql(tenant_id, normalize_company_ids(companies=company_ids))
    params = {**t_params, **f_params}

    query = f"""
        WITH daily_rev AS (
            SELECT
                date,
                SUM(amount_untaxed) as rev
            FROM fact_account_moves
            WHERE 1=1 {t_sql}
              AND move_type = 'out_invoice'
              AND state = 'posted'
              AND date >= CURRENT_DATE - INTERVAL '30 days'
              {f_sql}
            GROUP BY date
        )
        SELECT
            COALESCE(SUM(CASE WHEN date >= CURRENT_DATE - INTERVAL '1 day' THEN rev END), 0) as rev_24h,
            COALESCE(AVG(rev), 0) as avg_rev_30d
        FROM daily_rev
    """
    try:
        rows = run_query(query, params)
        if not rows:
            return False, ""
        row = rows[0]
        rev_24h = float(row.get("rev_24h") or 0)
        avg_30d = float(row.get("avg_rev_30d") or 0)

        threshold_pct = getattr(AgentConfig, "ALERT_REVENUE_DEVIATION_PCT", 30.0)
        if avg_30d > 0:
            diff_pct = abs(rev_24h - avg_30d) / avg_30d * 100.0
            if diff_pct >= threshold_pct:
                direction = "spike" if rev_24h > avg_30d else "drop"
                msg = f"Revenue {direction} detected: Last 24h revenue (${rev_24h:,.2f}) deviated by {round(diff_pct, 1)}% from 30-day daily avg (${avg_30d:,.2f})."
                return True, msg
    except Exception as e:
        logger.error(f"Error in check_revenue_anomaly precheck: {e}")

    return False, ""


def check_duplicate_invoices(tenant_id: str, company_ids: Optional[List[int]] = None, tenant_ids: Optional[List[str]] = None) -> Tuple[bool, str]:
    """Check for suspicious duplicate vendor bills (same partner + amount + date within 7 days)."""
    t_sql, t_params = build_tenant_filter_sql(tenant_id, tenant_ids, column_name="tenant_id", prefix="t_dup")
    f_sql, f_params = build_company_filter_sql(tenant_id, normalize_company_ids(companies=company_ids))
    params = {**t_params, **f_params}

    query = f"""
        SELECT partner_id, amount_total, date, COUNT(*) as cnt
        FROM fact_account_moves
        WHERE 1=1 {t_sql}
          AND move_type = 'in_invoice'
          AND state = 'posted'
          AND date >= CURRENT_DATE - INTERVAL '7 days'
          {f_sql}
        GROUP BY partner_id, amount_total, date
        HAVING COUNT(*) > 1
    """
    try:
        rows = run_query(query, params)
        if rows:
            dup_cnt = len(rows)
            msg = f"Detected {dup_cnt} potential duplicate vendor bill group(s) posted in the last 7 days."
            return True, msg
    except Exception as e:
        logger.error(f"Error in check_duplicate_invoices precheck: {e}")

    return False, ""


def check_low_inventory(tenant_id: str, company_ids: Optional[List[int]] = None, tenant_ids: Optional[List[str]] = None) -> Tuple[bool, str]:
    """Check for products with available stock < ALERT_LOW_STOCK_THRESHOLD."""
    t_sql, t_params = build_tenant_filter_sql(tenant_id, tenant_ids, column_name="tenant_id", prefix="t_inv")
    f_sql, f_params = build_company_filter_sql(tenant_id, normalize_company_ids(companies=company_ids))
    params = {**t_params, **f_params}

    threshold = getattr(AgentConfig, "ALERT_LOW_STOCK_THRESHOLD", 5)
    params["threshold"] = threshold

    query = f"""
        SELECT COUNT(DISTINCT product_id) as low_stock_cnt
        FROM fact_stock_quants
        WHERE 1=1 {t_sql}
          AND (quantity - reserved_quantity) < :threshold
          {f_sql}
    """
    try:
        rows = run_query(query, params)
        if rows:
            cnt = int(rows[0].get("low_stock_cnt") or 0)
            if cnt > 0:
                msg = f"Stock Alert: {cnt} product(s) have available inventory below critical threshold ({threshold} units)."
                return True, msg
    except Exception as e:
        logger.error(f"Error in check_low_inventory precheck: {e}")

    return False, ""


def check_large_transactions(tenant_id: str, company_ids: Optional[List[int]] = None, tenant_ids: Optional[List[str]] = None) -> Tuple[bool, str]:
    """Check for unusually large single journal entry lines (> 3x average balance for account type in last 24h)."""
    t_sql_l, t_params_l = build_tenant_filter_sql(tenant_id, tenant_ids, column_name="l.tenant_id", prefix="t_l")
    f_sql, f_params = build_company_filter_sql(tenant_id, normalize_company_ids(companies=company_ids), column_name="l.company_id")
    params = {**t_params_l, **f_params}

    multiplier = getattr(AgentConfig, "ALERT_LARGE_TXN_MULTIPLIER", 3.0)
    params["multiplier"] = multiplier

    query = f"""
        WITH avg_by_type AS (
            SELECT account_type, AVG(ABS(balance)) as avg_bal
            FROM fact_account_move_lines l
            WHERE 1=1 {t_sql_l}
            GROUP BY account_type
        )
        SELECT COUNT(*) as large_cnt
        FROM fact_account_move_lines l
        JOIN fact_account_moves m ON l.account_move_id = m.id
        JOIN avg_by_type a ON l.account_type = a.account_type
        WHERE 1=1 {t_sql_l}
          AND m.state = 'posted'
          AND m.date >= CURRENT_DATE - INTERVAL '1 day'
          AND ABS(l.balance) > (a.avg_bal * :multiplier)
          AND a.avg_bal > 100
          {f_sql}
    """
    try:
        rows = run_query(query, params)
        if rows:
            cnt = int(rows[0].get("large_cnt") or 0)
            if cnt > 0:
                msg = f"Outlier Alert: {cnt} transaction line(s) in the last 24h exceed {multiplier}x the average transaction size."
                return True, msg
    except Exception as e:
        logger.error(f"Error in check_large_transactions precheck: {e}")

    return False, ""


def run_all_prechecks(tenant_id: str, company_ids: Optional[List[int]] = None, tenant_ids: Optional[List[str]] = None) -> Dict[str, any]:
    """
    Executes all deterministic SQL pre-checks for a tenant.
    """
    checks = [
        ("cash_drop", check_cash_drop),
        ("overdue_ar", check_overdue_ar),
        ("revenue_anomaly", check_revenue_anomaly),
        ("duplicate_invoices", check_duplicate_invoices),
        ("low_inventory", check_low_inventory),
        ("large_transactions", check_large_transactions),
    ]

    triggered_checks: List[str] = []
    summaries: List[str] = []

    for name, check_fn in checks:
        triggered, msg = check_fn(tenant_id, company_ids, tenant_ids=tenant_ids)
        if triggered:
            triggered_checks.append(name)
            summaries.append(f"• {msg}")

    precheck_summary = "\n".join(summaries)
    any_triggered = len(triggered_checks) > 0

    if any_triggered:
        logger.info(
            f"Alert Pre-Checks TRIGGERED for tenant={tenant_id}: "
            f"{len(triggered_checks)} check(s) flagged anomalies ({', '.join(triggered_checks)})"
        )
    else:
        logger.info(f"Alert Pre-Checks CLEAR for tenant={tenant_id}: No anomalies detected.")

    return {
        "any_triggered": any_triggered,
        "triggered_checks": triggered_checks,
        "precheck_summary": precheck_summary,
    }
