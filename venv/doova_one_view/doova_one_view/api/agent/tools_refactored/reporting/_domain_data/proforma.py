# doova_one_view/api/agent/tools_refactored/reporting/_domain_data/proforma.py

import logging
from typing import Optional, List, Dict, Any
import re

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
    """Enriches data dict with Pro Forma / Forecast modeling, KPI cards, and Scenario analysis."""
    from doova_one_view.api.agent.tools_refactored import reporting_v2
    get_working_capital_tool = reporting_v2.get_working_capital_tool

    rev_f = pnl_ctx.get("rev_f", 0.0)
    gp_f = pnl_ctx.get("gp_f", 0.0)
    net_f = pnl_ctx.get("net_f", 0.0)
    gm_f = pnl_ctx.get("gm_f", 0.0)
    prior_rev_f = pnl_ctx.get("prior_rev_f", 0.0)

    # Current liquid cash position
    cash_val = 0.0
    try:
        wc = get_working_capital_tool(tenant_ids=tenant_ids, company_ids=company_ids, base_currency=base_currency)
        cash_val = float(wc.get("cash_and_bank", 0) or wc.get("cash", 0) or 0.0)
    except Exception as e:
        logger.warning(f"Failed to fetch cash for proforma forecast: {e}")

    curr = data.get("currency") or currency

    # Format agent-provided forecast data structures if present
    if isinstance(data.get("revenue_bridge"), list):
        for rb in data["revenue_bridge"]:
            if isinstance(rb, dict) and "amount" in rb:
                try:
                    amt_f = float(rb["amount"])
                    prefix = "-" if amt_f < 0 else ("+" if rb.get("type") == "add" else "")
                    rb["amount_formatted"] = f"{prefix}{_fmt_money(abs(amt_f), curr)}" if prefix else _fmt_money(amt_f, curr)
                except (ValueError, TypeError):
                    pass

    if isinstance(data.get("reorder_recommendations"), list):
        for rec in data["reorder_recommendations"]:
            if isinstance(rec, dict):
                if "recommended_order_value" in rec:
                    try:
                        v_f = float(rec["recommended_order_value"])
                        rec["recommended_order_value_formatted"] = _fmt_money(v_f, curr)
                    except (ValueError, TypeError):
                        pass
                for u_key in ("current_stock_units", "reorder_point_units", "recommended_order_units"):
                    if u_key in rec:
                        try:
                            rec[f"{u_key}_formatted"] = f"{int(float(rec[u_key])):,}"
                        except (ValueError, TypeError):
                            pass
                if "daily_demand_rate_units" in rec:
                    try:
                        rec["daily_demand_rate_formatted"] = f"{float(rec['daily_demand_rate_units']):,.1f}"
                    except (ValueError, TypeError):
                        pass

    if isinstance(data.get("inventory_position"), dict):
        inv_pos = data["inventory_position"]
        for p_key in (
            "opening_stock_value", "capital_tied_up_value", "projected_demand_value",
            "safety_stock_requirement_value", "recommended_replenishment_value"
        ):
            if p_key in inv_pos:
                try:
                    val_f = float(inv_pos[p_key])
                    inv_pos[f"{p_key}_formatted"] = _fmt_money(val_f, curr)
                except (ValueError, TypeError):
                    pass

    has_agent_forecast = bool(
        data.get("revenue_bridge")
        or data.get("reorder_recommendations")
        or data.get("scenarios")
        or data.get("demand_scenarios")
        or data.get("inventory_position")
    )

    if has_agent_forecast:
        # Agent provided a rich structured forecast; do NOT overwrite with synthetic scenarios
        if "projected_revenue" not in data and data.get("value"):
            data["projected_revenue"] = {"raw": 0, "formatted": str(data["value"])}
        if "projection_confidence" not in data and data.get("confidence"):
            c_val = data["confidence"]
            data["projection_confidence"] = {"raw": c_val, "formatted": f"{c_val}%" if str(c_val).isdigit() else str(c_val)}
        return

    # Fallback synthetic calculations when no agent forecast is present
    base_growth = 8.5
    proj_rev = rev_f * (1 + base_growth / 100.0) if rev_f > 0 else 0.0
    proj_net = net_f * (1 + (base_growth + 2.0) / 100.0) if net_f > 0 else (net_f * 0.9)
    proj_cash = max(0.0, cash_val + (proj_net * 0.5))
    proj_conf = 80.0

    # Sensitivity Scenarios (Bull / Base / Bear)
    bull_growth = 18.0
    bull_rev = rev_f * (1 + bull_growth / 100.0)
    bull_net = net_f * (1 + (bull_growth + 5.0) / 100.0)

    bear_growth = -10.0
    bear_rev = rev_f * (1 + bear_growth / 100.0)
    bear_net = net_f * 0.85

    scenarios = [
        {
            "name": "Bull Case (Aggressive Expansion)",
            "growth": f"+{bull_growth:.1f}%",
            "growth_rate": f"+{bull_growth:.1f}%",
            "revenue": _fmt_money(bull_rev, currency),
            "projected_revenue": _fmt_money(bull_rev, currency),
            "net_profit": _fmt_money(bull_net, currency),
            "projected_net_profit": _fmt_money(bull_net, currency),
            "likelihood": "Growth Target",
            "badge_class": "badge-success",
        },
        {
            "name": "Base Case (Weighted Run-Rate)",
            "growth": f"+{base_growth:.1f}%",
            "growth_rate": f"+{base_growth:.1f}%",
            "revenue": _fmt_money(proj_rev, currency),
            "projected_revenue": _fmt_money(proj_rev, currency),
            "net_profit": _fmt_money(proj_net, currency),
            "projected_net_profit": _fmt_money(proj_net, currency),
            "likelihood": "High Confidence",
            "badge_class": "badge-info",
        },
        {
            "name": "Bear Case (Conservative Buffer)",
            "growth": f"{bear_growth:.1f}%",
            "growth_rate": f"{bear_growth:.1f}%",
            "revenue": _fmt_money(bear_rev, currency),
            "projected_revenue": _fmt_money(bear_rev, currency),
            "net_profit": _fmt_money(bear_net, currency),
            "projected_net_profit": _fmt_money(bear_net, currency),
            "likelihood": "Downside Buffer",
            "badge_class": "badge-warning",
        },
    ]

    # Populate KPIs only if not already provided by user/agent payload
    if "projected_revenue" not in data:
        data["projected_revenue"] = _build_kpi_variance(proj_rev, rev_f, currency, fmt="money", polarity="positive")
    if "projected_growth" not in data:
        data["projected_growth"] = _build_kpi_variance(base_growth, 0, currency, fmt="pct", polarity="positive")
    if "projected_margin" not in data:
        data["projected_margin"] = _build_kpi_variance(gm_f, 0, currency, fmt="pct", polarity="positive")
    if "projected_net_profit" not in data:
        data["projected_net_profit"] = _build_kpi_variance(proj_net, net_f, currency, fmt="money", polarity="positive")
    if "projected_cash" not in data:
        data["projected_cash"] = _build_kpi_variance(proj_cash, 0, currency, fmt="money", polarity="positive")
    if "projection_confidence" not in data:
        data["projection_confidence"] = _build_kpi_variance(proj_conf, 0, currency, fmt="count", polarity="positive")

    if "proforma_scenarios" not in data:
        data["proforma_scenarios"] = scenarios
