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


BUSINESS_MODEL_BASELINES = {
    "product": {  # Retail, FMCG, Supermarket, E-commerce
        "cash_drop_pct": 12.0,
        "ar_overdue_ratio": 0.15,
        "revenue_deviation_pct": 20.0,
        "low_stock_threshold": 15,
        "large_txn_multiplier": 2.5,
    },
    "service": {  # Consultancy, Agency, Legal, IT Services
        "cash_drop_pct": 35.0,
        "ar_overdue_ratio": 0.40,
        "revenue_deviation_pct": 45.0,
        "low_stock_threshold": 0,  # Physical inventory ignored for service model
        "large_txn_multiplier": 3.5,
    },
    "hybrid": {  # Wholesale, Manufacturing, Contracting
        "cash_drop_pct": 20.0,
        "ar_overdue_ratio": 0.30,
        "revenue_deviation_pct": 30.0,
        "low_stock_threshold": 5,
        "large_txn_multiplier": 3.0,
    }
}


def resolve_effective_thresholds(tenant_id: str, custom_thresholds: Optional[Dict[str, any]] = None) -> Dict[str, float]:
    """
    Resolves effective alert precheck thresholds using a 3-tier precedence hierarchy:
    1. Custom schedule-level overrides (highest priority)
    2. Inferred business-model profile defaults (Product vs Service vs Hybrid)
    3. Global AgentConfig fallback thresholds (lowest priority)
    """
    effective = {
        "cash_drop_pct": float(getattr(AgentConfig, "ALERT_CASH_DROP_PCT", 20.0)),
        "ar_overdue_ratio": float(getattr(AgentConfig, "ALERT_AR_OVERDUE_RATIO", 0.30)),
        "revenue_deviation_pct": float(getattr(AgentConfig, "ALERT_REVENUE_DEVIATION_PCT", 30.0)),
        "low_stock_threshold": float(getattr(AgentConfig, "ALERT_LOW_STOCK_THRESHOLD", 5)),
        "large_txn_multiplier": float(getattr(AgentConfig, "ALERT_LARGE_TXN_MULTIPLIER", 3.0)),
    }

    try:
        from doova_one_view.api.agent.tools_refactored.common import get_tenant_profile_tool
        profile = get_tenant_profile_tool(tenant_id=tenant_id)
        b_type = (profile.get("business_type") or "").lower()
        if b_type in BUSINESS_MODEL_BASELINES:
            effective.update(BUSINESS_MODEL_BASELINES[b_type])
    except Exception:
        pass

    if custom_thresholds and isinstance(custom_thresholds, dict):
        for key in effective.keys():
            if key in custom_thresholds and custom_thresholds[key] is not None:
                try:
                    effective[key] = float(custom_thresholds[key])
                except (ValueError, TypeError):
                    pass

    return effective


def check_cash_drop(tenant_id: str, company_ids: Optional[List[int]] = None, tenant_ids: Optional[List[str]] = None, thresholds: Optional[Dict[str, any]] = None) -> Tuple[bool, str]:
    """Check if current cash balance dropped > cash_drop_pct vs 7-day average."""
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

        eff = resolve_effective_thresholds(tenant_id, thresholds)
        threshold_pct = eff["cash_drop_pct"]
        if avg_7d > 0 and recent < avg_7d * (1 - threshold_pct / 100.0):
            drop_pct = round((1 - recent / avg_7d) * 100, 1)
            msg = f"Cash inflow/balance dropped by {drop_pct}% in recent period (vs 7-day avg of ${avg_7d:,.2f}, threshold: {threshold_pct}%)."
            return True, msg
    except Exception as e:
        logger.error(f"Error in check_cash_drop precheck: {e}")

    return False, ""


def check_overdue_ar(tenant_id: str, company_ids: Optional[List[int]] = None, tenant_ids: Optional[List[str]] = None, thresholds: Optional[Dict[str, any]] = None) -> Tuple[bool, str]:
    """Check if overdue receivables exceed ar_overdue_ratio threshold."""
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

        eff = resolve_effective_thresholds(tenant_id, thresholds)
        threshold_ratio = eff["ar_overdue_ratio"]
        if total_ar > 0:
            ratio = overdue_ar / total_ar
            if ratio >= threshold_ratio:
                ratio_pct = round(ratio * 100, 1)
                msg = f"High Accounts Receivable Overdue Ratio: {ratio_pct}% of AR is past due (${overdue_ar:,.2f} / ${total_ar:,.2f}, threshold: {int(threshold_ratio * 100)}%)."
                return True, msg
    except Exception as e:
        logger.error(f"Error in check_overdue_ar precheck: {e}")

    return False, ""


def check_revenue_anomaly(tenant_id: str, company_ids: Optional[List[int]] = None, tenant_ids: Optional[List[str]] = None, thresholds: Optional[Dict[str, any]] = None) -> Tuple[bool, str]:
    """Check if revenue in last 24h deviates by > revenue_deviation_pct from 30-day daily avg."""
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

        eff = resolve_effective_thresholds(tenant_id, thresholds)
        threshold_pct = eff["revenue_deviation_pct"]
        if avg_30d > 0 and rev_24h < avg_30d:
            drop_pct = (avg_30d - rev_24h) / avg_30d * 100.0
            if drop_pct >= threshold_pct:
                msg = f"Severe Revenue Drop detected: Last 24h revenue (${rev_24h:,.2f}) dropped by {round(drop_pct, 1)}% from 30-day daily avg (${avg_30d:,.2f}, threshold: {threshold_pct}%)."
                return True, msg, "warning"
    except Exception as e:
        logger.error(f"Error in check_revenue_anomaly precheck: {e}")

    return False, ""


def check_duplicate_invoices(tenant_id: str, company_ids: Optional[List[int]] = None, tenant_ids: Optional[List[str]] = None, thresholds: Optional[Dict[str, any]] = None) -> Tuple[bool, str]:
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


def check_low_inventory(tenant_id: str, company_ids: Optional[List[int]] = None, tenant_ids: Optional[List[str]] = None, thresholds: Optional[Dict[str, any]] = None) -> Tuple[bool, str]:
    """Check for products with available stock < low_stock_threshold."""
    eff = resolve_effective_thresholds(tenant_id, thresholds)
    threshold = int(eff["low_stock_threshold"])

    # If inventory check is disabled for this profile (e.g., Service companies)
    if threshold <= 0:
        return False, ""

    t_sql, t_params = build_tenant_filter_sql(tenant_id, tenant_ids, column_name="tenant_id", prefix="t_inv")
    f_sql, f_params = build_company_filter_sql(tenant_id, normalize_company_ids(companies=company_ids))
    params = {**t_params, **f_params}
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
                msg = f"Stock Alert: {cnt} product(s) have available inventory below threshold ({threshold} units)."
                return True, msg
    except Exception as e:
        logger.error(f"Error in check_low_inventory precheck: {e}")

    return False, ""


def check_large_transactions(tenant_id: str, company_ids: Optional[List[int]] = None, tenant_ids: Optional[List[str]] = None, thresholds: Optional[Dict[str, any]] = None) -> Tuple[bool, str]:
    """Check for unusually large single journal entry lines (> large_txn_multiplier x average balance in last 24h)."""
    t_sql_l, t_params_l = build_tenant_filter_sql(tenant_id, tenant_ids, column_name="l.tenant_id", prefix="t_l")
    f_sql, f_params = build_company_filter_sql(tenant_id, normalize_company_ids(companies=company_ids), column_name="l.company_id")
    params = {**t_params_l, **f_params}

    eff = resolve_effective_thresholds(tenant_id, thresholds)
    multiplier = eff["large_txn_multiplier"]
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


def check_unbalanced_journals(tenant_id: str, company_ids: Optional[List[int]] = None, tenant_ids: Optional[List[str]] = None, thresholds: Optional[Dict[str, any]] = None) -> Tuple[bool, str]:
    """Check for posted unbalanced journal entries (debit != credit variance > 0.01)."""
    t_sql_l, t_params_l = build_tenant_filter_sql(tenant_id, tenant_ids, column_name="l.tenant_id", prefix="t_l")
    f_sql, f_params = build_company_filter_sql(tenant_id, normalize_company_ids(companies=company_ids), column_name="l.company_id")
    params = {**t_params_l, **f_params}

    query = f"""
        SELECT COUNT(DISTINCT m.id) as unbalanced_cnt
        FROM fact_account_move_lines l
        JOIN fact_account_moves m ON l.account_move_id = m.id
        WHERE 1=1 {t_sql_l} AND m.state = 'posted' {f_sql}
        GROUP BY m.id
        HAVING ABS(SUM(l.debit) - SUM(l.credit)) > 0.01
    """
    try:
        rows = run_query(query, params)
        if rows:
            cnt = len(rows)
            msg = f"Audit Alert: {cnt} posted journal entry/entries are unbalanced (debit != credit)."
            return True, msg
    except Exception as e:
        logger.error(f"Error in check_unbalanced_journals precheck: {e}")

    return False, ""


def check_weekend_postings(tenant_id: str, company_ids: Optional[List[int]] = None, tenant_ids: Optional[List[str]] = None, thresholds: Optional[Dict[str, any]] = None) -> Tuple[bool, str]:
    """Check for suspicious weekend journal postings (ISODOW 6 or 7) in last 7 days."""
    t_sql_m, t_params_m = build_tenant_filter_sql(tenant_id, tenant_ids, column_name="m.tenant_id", prefix="t_m")
    f_sql, f_params = build_company_filter_sql(tenant_id, normalize_company_ids(companies=company_ids), column_name="m.company_id")
    params = {**t_params_m, **f_params}

    query = f"""
        SELECT COUNT(*) as weekend_cnt
        FROM fact_account_moves m
        WHERE 1=1 {t_sql_m} AND m.state = 'posted'
          AND m.date >= CURRENT_DATE - INTERVAL '7 days'
          AND EXTRACT(ISODOW FROM m.date) IN (6, 7)
          {f_sql}
    """
    try:
        rows = run_query(query, params)
        if rows:
            cnt = int(rows[0].get("weekend_cnt") or 0)
            if cnt > 0:
                msg = f"Audit Alert: {cnt} posted transaction(s) occurred on weekends in the last 7 days."
                return True, msg
    except Exception as e:
        logger.error(f"Error in check_weekend_postings precheck: {e}")

    return False, ""


def run_all_prechecks(tenant_id: str, company_ids: Optional[List[int]] = None, tenant_ids: Optional[List[str]] = None, thresholds: Optional[Dict[str, any]] = None) -> Dict[str, any]:
    """
    Executes deterministic SQL pre-checks for severe financial and audit risks using dynamic effective thresholds.
    """
    checks = [
        ("cash_drop", check_cash_drop),
        ("overdue_ar", check_overdue_ar),
        ("revenue_anomaly", check_revenue_anomaly),
        ("duplicate_invoices", check_duplicate_invoices),
        ("low_inventory", check_low_inventory),
        ("large_transactions", check_large_transactions),
        ("unbalanced_journals", check_unbalanced_journals),
        ("weekend_postings", check_weekend_postings),
    ]

    triggered_checks: List[str] = []
    summaries: List[str] = []
    highest_severity = "info"
    severity_rank = {"critical": 3, "warning": 2, "info": 0}

    for name, check_fn in checks:
        res = check_fn(tenant_id, company_ids, tenant_ids=tenant_ids, thresholds=thresholds)
        if isinstance(res, tuple) and len(res) == 3:
            triggered, msg, sev = res
        elif isinstance(res, tuple) and len(res) == 2:
            triggered, msg = res
            sev = "critical" if name == "unbalanced_journals" else "warning"
        else:
            triggered, msg, sev = False, "", "info"

        if triggered and msg:
            triggered_checks.append(name)
            summaries.append(f"• {msg}")
            if severity_rank.get(sev, 0) > severity_rank.get(highest_severity, 0):
                highest_severity = sev

    precheck_summary = "\n".join(summaries)
    any_triggered = len(triggered_checks) > 0

    if any_triggered:
        logger.info(
            f"Alert Pre-Checks TRIGGERED for tenant={tenant_id}: "
            f"{len(triggered_checks)} check(s) flagged (Severity: {highest_severity}, {', '.join(triggered_checks)})"
        )
    else:
        logger.info(f"Alert Pre-Checks CLEAR for tenant={tenant_id}: No anomalies or milestones detected.")

    return {
        "any_triggered": any_triggered,
        "triggered_checks": triggered_checks,
        "precheck_summary": precheck_summary,
        "highest_severity": highest_severity,
    }

