# doova_one_view/api/agent/tools_refactored/reporting/_domain_data/financial_analysis.py

import logging
from typing import Optional, List, Dict, Any

from .._variance import _build_kpi_variance

logger = logging.getLogger(__name__)


def enrich(
    data: dict,
    pnl_ctx: dict,
    tenant_id: str,
    resolved_company_ids: list[int] | None,
    start_date: str,
    end_date: str,
    base_currency: str | None,
    tenant_ids: list[str] | None,
    currency: str,
    prior_start: str | None = None,
    prior_end: str | None = None,
    comparison_label: str = "",
    **kwargs
) -> None:
    """Enriches data dict with Financial Health & Ratio Analysis telemetry (ROE, ROI, Current/Quick ratios, benchmark matrix)."""
    from doova_one_view.api.agent.tools_refactored import reporting_v2
    get_business_health_score_tool = reporting_v2.get_business_health_score_tool
    get_balance_sheet_tool = reporting_v2.get_balance_sheet_tool
    get_working_capital_tool = reporting_v2.get_working_capital_tool

    try:
        health = get_business_health_score_tool(tenant_id, company_ids=resolved_company_ids, base_currency=base_currency, tenant_ids=tenant_ids)
        bs = get_balance_sheet_tool(tenant_id, company_ids=resolved_company_ids, as_of_date=end_date, base_currency=base_currency, tenant_ids=tenant_ids)
        wc = get_working_capital_tool(tenant_id, company_ids=resolved_company_ids, base_currency=base_currency, tenant_ids=tenant_ids)

        prior_bs = {}
        if prior_end:
            try:
                prior_bs = get_balance_sheet_tool(tenant_id, company_ids=resolved_company_ids, as_of_date=prior_end, base_currency=base_currency, tenant_ids=tenant_ids)
            except Exception:
                pass

        rev_f = pnl_ctx["rev_f"]
        gp_f = pnl_ctx["gp_f"]
        ebit_f = pnl_ctx["ebit_f"]
        net_f = pnl_ctx["net_f"]
        prior_rev_f = pnl_ctx["prior_rev_f"]
        prior_ebit_f = pnl_ctx["prior_ebit_f"]
        prior_gm_f = pnl_ctx["prior_gm_f"]
        prior_net_m_f = pnl_ctx["prior_net_m_f"]

        ca_val = float(bs.get("current_assets", 0) or 0)
        cl_val = float(bs.get("current_liabilities", 0) or 0)
        cash_val = float(bs.get("bank_and_cash_accounts", 0) or 0)
        ar_val = float(bs.get("receivables", 0) or 0)
        eq_val = float(bs.get("total_equity", 0) or 0)
        ta_val = float(bs.get("total_assets", 0) or 0)
        tl_val = float(bs.get("total_liabilities", 0) or 0)

        cur_ratio = float(bs.get("current_ratio") or wc.get("current_ratio") or (ca_val / cl_val if cl_val else 0.0))
        quick_ratio = ((cash_val + ar_val) / cl_val) if cl_val > 0 else 0.0
        roe_val = (net_f / eq_val * 100.0) if eq_val > 0 else 0.0
        roi_val = (net_f / ta_val * 100.0) if ta_val > 0 else 0.0
        gross_margin_pct = (gp_f / rev_f * 100.0) if rev_f > 0 else 0.0
        net_margin_pct = (net_f / rev_f * 100.0) if rev_f > 0 else 0.0
        ebit_margin_pct = (ebit_f / rev_f * 100.0) if rev_f > 0 else 0.0
        d_to_e = (tl_val / eq_val * 100.0) if eq_val > 0 else 0.0
        equity_ratio = (eq_val / ta_val * 100.0) if ta_val > 0 else 0.0
        health_score_val = float(health.get("business_health_score", 0.0) or 80.0)

        prior_ca = float(prior_bs.get("current_assets", 0) or 0)
        prior_cl = float(prior_bs.get("current_liabilities", 0) or 0)
        prior_cur_ratio = (prior_ca / prior_cl) if prior_cl else 0.0

        ratio_benchmark_matrix = [
            {"category": "Profitability", "name": "Gross Profit Margin", "formatted_value": f"{gross_margin_pct:.1f}%", "benchmark": "> 40.0%", "status": "Moderate" if gross_margin_pct >= 30 else "Low", "badge_class": "badge-info" if gross_margin_pct >= 30 else "badge-warning"},
            {"category": "Profitability", "name": "Net Profit Margin", "formatted_value": f"{net_margin_pct:.1f}%", "benchmark": "> 10.0%", "status": "Healthy" if net_margin_pct > 0 else "Loss", "badge_class": "badge-success" if net_margin_pct > 0 else "badge-danger"},
            {"category": "Profitability", "name": "Operating / EBIT Margin", "formatted_value": f"{ebit_margin_pct:.1f}%", "benchmark": "> 15.0%", "status": "Healthy" if ebit_margin_pct > 0 else "Negative", "badge_class": "badge-success" if ebit_margin_pct > 0 else "badge-danger"},
            {"category": "Profitability", "name": "Return on Investment (ROI)", "formatted_value": f"{roi_val:.1f}%", "benchmark": "> 10.0%", "status": "Healthy" if roi_val > 0 else "Deficit", "badge_class": "badge-success" if roi_val > 0 else "badge-danger"},
            {"category": "Profitability", "name": "Return on Equity (ROE)", "formatted_value": f"{roe_val:.1f}%", "benchmark": "> 15.0%", "status": "Healthy" if roe_val > 0 else "Deficit", "badge_class": "badge-success" if roe_val > 0 else "badge-danger"},
            {"category": "Liquidity", "name": "Current Ratio", "formatted_value": f"{cur_ratio:.2f}", "benchmark": "1.50 – 2.50x", "status": "Adequate" if cur_ratio >= 1.5 else ("Tight" if cur_ratio >= 1.0 else "Critical"), "badge_class": "badge-success" if cur_ratio >= 1.5 else "badge-warning"},
            {"category": "Liquidity", "name": "Quick / Acid Ratio", "formatted_value": f"{quick_ratio:.2f}", "benchmark": "> 1.00x", "status": "Adequate" if quick_ratio >= 1.0 else "Tight", "badge_class": "badge-success" if quick_ratio >= 1.0 else "badge-warning"},
            {"category": "Leverage", "name": "Debt-to-Equity", "formatted_value": f"{d_to_e:.1f}%", "benchmark": "< 100.0%", "status": "Acceptable" if d_to_e <= 100 else "High Leverage", "badge_class": "badge-info" if d_to_e <= 100 else "badge-warning"},
            {"category": "Leverage", "name": "Equity Ratio", "formatted_value": f"{equity_ratio:.1f}%", "benchmark": "> 50.0%", "status": "Sound" if equity_ratio >= 50 else "Leveraged", "badge_class": "badge-success" if equity_ratio >= 50 else "badge-warning"},
        ]

        data.update({
            "health_score": _build_kpi_variance(health_score_val, 0, currency, fmt="count", polarity="positive"),
            "gross_margin": _build_kpi_variance(gross_margin_pct, prior_gm_f, currency, fmt="pct", polarity="positive"),
            "net_margin": _build_kpi_variance(net_margin_pct, prior_net_m_f, currency, fmt="pct", polarity="positive"),
            "ebit_margin": _build_kpi_variance(ebit_margin_pct, (prior_ebit_f / prior_rev_f * 100) if prior_rev_f > 0 else 0, currency, fmt="pct", polarity="positive"),
            "current_ratio": _build_kpi_variance(cur_ratio, prior_cur_ratio, currency, fmt="ratio", polarity="positive"),
            "quick_ratio": round(quick_ratio, 2),
            "roi": round(roi_val, 1),
            "roi_pct": round(roi_val, 1),
            "return_on_investment": round(roi_val, 1),
            "roe": round(roe_val, 1),
            "return_on_equity": round(roe_val, 1),
            "nwc": float(wc.get("working_capital", 0) or (ca_val - cl_val)),
            "working_capital": float(wc.get("working_capital", 0) or (ca_val - cl_val)),
            "ratios": ratio_benchmark_matrix,
        })
        if prior_gm_f > 0 or prior_cur_ratio > 0:
            if "prior_period" not in data:
                data["prior_period"] = {}
            data["prior_period"].update({
                "gross_margin_pct": prior_gm_f,
                "net_margin_pct": prior_net_m_f,
                "current_ratio": prior_cur_ratio,
                "comparison_label": comparison_label,
            })
    except Exception as e:
        logger.warning(f"Financial analysis domain query error: {e}")
