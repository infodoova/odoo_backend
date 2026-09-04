# doova_one_view/api/agent/tools_refactored/reporting/_domain_data/_base.py

from typing import Dict, Any, List
from .._formatters import _fmt_money
from .._variance import _compute_variance, _build_kpi_variance


def _pnl_row_var(curr: float, prev: float) -> str:
    if abs(prev) < 0.001:
        return "—"
    v_pct, _ = _compute_variance(curr, prev)
    pfx = "+" if v_pct > 0 else ""
    return f"{pfx}{v_pct:.1f}%"


def _build_pnl_context(pnl: dict, prior_pnl: dict, currency: str) -> dict:
    """Extracts and normalizes the standard 12 P&L floats and their prior counterparts."""
    rev_f = float(pnl.get("total_income", 0) or pnl.get("revenue", 0) or 0)
    gp_f = float(pnl.get("gross_profit", 0) or 0)
    ebit_f = float(pnl.get("ebit", 0) or 0)
    net_f = float(pnl.get("net_profit", 0) or 0)
    opex_f = float(pnl.get("operating_expenses", 0) or 0)
    cogs_f = float(pnl.get("cogs", 0) or 0)
    gm_f = float(pnl.get("gross_margin", 0) or (gp_f / rev_f * 100 if rev_f > 0 else 0))
    net_m_f = float(pnl.get("net_margin", 0) or (net_f / rev_f * 100 if rev_f > 0 else 0))

    prior_rev_f = float(prior_pnl.get("total_income", 0) or prior_pnl.get("revenue", 0) or 0)
    prior_gp_f = float(prior_pnl.get("gross_profit", 0) or 0)
    prior_ebit_f = float(prior_pnl.get("ebit", 0) or 0)
    prior_net_f = float(prior_pnl.get("net_profit", 0) or 0)
    prior_opex_f = float(prior_pnl.get("operating_expenses", 0) or 0)
    prior_cogs_f = float(prior_pnl.get("cogs", 0) or 0)
    prior_gm_f = float(prior_pnl.get("gross_margin_pct", 0) or prior_pnl.get("gross_margin", 0) or (prior_gp_f / prior_rev_f * 100 if prior_rev_f > 0 else 0))
    prior_net_m_f = float(prior_pnl.get("net_margin", 0) or (prior_net_f / prior_rev_f * 100 if prior_rev_f > 0 else 0))

    return {
        "pnl": pnl,
        "prior_pnl": prior_pnl,
        "rev_f": rev_f,
        "gp_f": gp_f,
        "ebit_f": ebit_f,
        "net_f": net_f,
        "opex_f": opex_f,
        "cogs_f": cogs_f,
        "gm_f": gm_f,
        "net_m_f": net_m_f,
        "prior_rev_f": prior_rev_f,
        "prior_gp_f": prior_gp_f,
        "prior_ebit_f": prior_ebit_f,
        "prior_net_f": prior_net_f,
        "prior_opex_f": prior_opex_f,
        "prior_cogs_f": prior_cogs_f,
        "prior_gm_f": prior_gm_f,
        "prior_net_m_f": prior_net_m_f,
    }


def _build_shared_kpis(pnl_ctx: dict, currency: str) -> dict:
    """Builds standard baseline KPI variance metrics from P&L context."""
    return {
        "revenue": _build_kpi_variance(pnl_ctx["rev_f"], pnl_ctx["prior_rev_f"], currency, fmt="money", polarity="positive"),
        "total_revenue": _build_kpi_variance(pnl_ctx["rev_f"], pnl_ctx["prior_rev_f"], currency, fmt="money", polarity="positive"),
        "cogs": _build_kpi_variance(pnl_ctx["cogs_f"], pnl_ctx["prior_cogs_f"], currency, fmt="money", polarity="negative"),
        "gross_profit": _build_kpi_variance(pnl_ctx["gp_f"], pnl_ctx["prior_gp_f"], currency, fmt="money", polarity="positive"),
        "gross_margin": _build_kpi_variance(pnl_ctx["gm_f"], pnl_ctx["prior_gm_f"], currency, fmt="pct", polarity="positive"),
        "gross_margin_pct": _build_kpi_variance(pnl_ctx["gm_f"], pnl_ctx["prior_gm_f"], currency, fmt="pct", polarity="positive"),
        "opex": _build_kpi_variance(pnl_ctx["opex_f"], pnl_ctx["prior_opex_f"], currency, fmt="money", polarity="negative"),
        "operating_expenses": _build_kpi_variance(pnl_ctx["opex_f"], pnl_ctx["prior_opex_f"], currency, fmt="money", polarity="negative"),
        "total_expenses": _build_kpi_variance(pnl_ctx["opex_f"], pnl_ctx["prior_opex_f"], currency, fmt="money", polarity="negative"),
        "ebit": _build_kpi_variance(pnl_ctx["ebit_f"], pnl_ctx["prior_ebit_f"], currency, fmt="money", polarity="positive"),
        "net_profit": _build_kpi_variance(pnl_ctx["net_f"], pnl_ctx["prior_net_f"], currency, fmt="money", polarity="positive"),
        "net_margin": _build_kpi_variance(pnl_ctx["net_m_f"], pnl_ctx["prior_net_m_f"], currency, fmt="pct", polarity="positive"),
        "net_margin_pct": _build_kpi_variance(pnl_ctx["net_m_f"], pnl_ctx["prior_net_m_f"], currency, fmt="pct", polarity="positive"),
    }


def _build_pnl_statement(pnl_ctx: dict, currency: str) -> list[dict]:
    """Assembles structured Income Statement rows with current, prior, and variance %."""
    rev_f = pnl_ctx["rev_f"]
    prior_rev_f = pnl_ctx["prior_rev_f"]
    cogs_f = pnl_ctx["cogs_f"]
    prior_cogs_f = pnl_ctx["prior_cogs_f"]
    gp_f = pnl_ctx["gp_f"]
    prior_gp_f = pnl_ctx["prior_gp_f"]
    opex_f = pnl_ctx["opex_f"]
    prior_opex_f = pnl_ctx["prior_opex_f"]
    ebit_f = pnl_ctx["ebit_f"]
    prior_ebit_f = pnl_ctx["prior_ebit_f"]
    net_f = pnl_ctx["net_f"]
    prior_net_f = pnl_ctx["prior_net_f"]

    return [
        {"name": "REVENUE & TURNOVER", "is_header": True, "is_bold": True, "current": "", "prior": "", "variance": ""},
        {"name": "Gross Operating Revenue", "is_bold": True, "current": _fmt_money(rev_f, currency), "prior": _fmt_money(prior_rev_f, currency) if prior_rev_f else "—", "variance": _pnl_row_var(rev_f, prior_rev_f)},
        {"name": "COST OF GOODS SOLD", "is_header": True, "is_bold": True, "current": "", "prior": "", "variance": ""},
        {"name": "Direct Cost of Sales (COGS)", "is_bold": False, "current": _fmt_money(cogs_f, currency), "prior": _fmt_money(prior_cogs_f, currency) if prior_cogs_f else "—", "variance": _pnl_row_var(cogs_f, prior_cogs_f)},
        {"name": "GROSS PROFIT", "is_total": True, "is_bold": True, "current": _fmt_money(gp_f, currency), "prior": _fmt_money(prior_gp_f, currency) if prior_gp_f else "—", "variance": _pnl_row_var(gp_f, prior_gp_f)},
        {"name": "OPERATING EXPENSES (OPEX)", "is_header": True, "is_bold": True, "current": "", "prior": "", "variance": ""},
        {"name": "Total Operating Expenses", "is_bold": False, "current": _fmt_money(opex_f, currency), "prior": _fmt_money(prior_opex_f, currency) if prior_opex_f else "—", "variance": _pnl_row_var(opex_f, prior_opex_f)},
        {"name": "OPERATING PROFIT (EBIT)", "is_bold": True, "current": _fmt_money(ebit_f, currency), "prior": _fmt_money(prior_ebit_f, currency) if prior_ebit_f else "—", "variance": _pnl_row_var(ebit_f, prior_ebit_f)},
        {"name": "NET PROFIT", "is_total": True, "is_bold": True, "current": _fmt_money(net_f, currency), "prior": _fmt_money(prior_net_f, currency) if prior_net_f else "—", "variance": _pnl_row_var(net_f, prior_net_f)},
    ]
