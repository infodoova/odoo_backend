# doova_one_view/api/agent/tools_refactored/reporting/_domain_data/__init__.py

import logging
from typing import Optional, List, Dict, Any

from . import (
    _base,
    accounting,
    sales,
    purchase,
    inventory,
    cashflow,
    balance_sheet,
    financial_analysis,
    income_statement,
)

logger = logging.getLogger(__name__)


def _fetch_domain_report_data(
    resolved_domain: str,
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
) -> dict:
    """
    Direct, authoritative database query pipeline for specialized domain reports.
    Executes domain-specific SQL queries to populate complete KPI datasets,
    prior-period comparisons, aging schedules, category distributions, and ledger records.
    """
    from doova_one_view.api.agent.tools_refactored import reporting_v2
    calculate_pnl_tool = reporting_v2.calculate_pnl_tool

    data = {}
    try:
        pnl = calculate_pnl_tool(tenant_id, company_ids=resolved_company_ids, start_date=start_date, end_date=end_date, base_currency=base_currency, tenant_ids=tenant_ids)
    except Exception as e:
        logger.warning(f"Domain P&L fetch error: {e}")
        pnl = {}

    prior_pnl = {}
    if prior_start and prior_end:
        try:
            prior_pnl = calculate_pnl_tool(tenant_id, company_ids=resolved_company_ids, start_date=prior_start, end_date=prior_end, base_currency=base_currency, tenant_ids=tenant_ids)
        except Exception as e:
            logger.warning(f"Prior P&L fetch error in domain pipeline: {e}")

    pnl_ctx = _base._build_pnl_context(pnl, prior_pnl, currency)
    data.update(_base._build_shared_kpis(pnl_ctx, currency))

    prior_rev_f = pnl_ctx["prior_rev_f"]
    prior_gp_f = pnl_ctx["prior_gp_f"]
    prior_net_f = pnl_ctx["prior_net_f"]
    prior_opex_f = pnl_ctx["prior_opex_f"]
    if prior_rev_f > 0 or prior_gp_f > 0 or prior_net_f > 0 or prior_opex_f > 0:
        data["prior_period"] = {
            "revenue": prior_rev_f,
            "cogs": pnl_ctx["prior_cogs_f"],
            "gross_profit": prior_gp_f,
            "gross_margin_pct": pnl_ctx["prior_gm_f"],
            "operating_expenses": prior_opex_f,
            "ebit": pnl_ctx["prior_ebit_f"],
            "net_profit": prior_net_f,
            "net_margin_pct": pnl_ctx["prior_net_m_f"],
            "comparison_label": comparison_label,
            "prior_start": prior_start,
            "prior_end": prior_end,
        }

    data["pnl_statement"] = _base._build_pnl_statement(pnl_ctx, currency)

    domain_dispatch = [
        (("accounting", "general", "consolidated"), accounting.enrich),
        (("sales", "general"), sales.enrich),
        (("purchase", "purchasing"), purchase.enrich),
        (("inventory", "stock"), inventory.enrich),
        (("cashflow", "liquidity"), cashflow.enrich),
        (("balance_sheet", "solvency", "financial_position"), balance_sheet.enrich),
        (("financial_analysis", "financial_health", "ratios"), financial_analysis.enrich),
        (("income_statement", "pnl"), income_statement.enrich),
    ]

    for domain_keys, enrich_fn in domain_dispatch:
        if resolved_domain in domain_keys:
            enrich_fn(
                data=data,
                pnl_ctx=pnl_ctx,
                tenant_id=tenant_id,
                resolved_company_ids=resolved_company_ids,
                start_date=start_date,
                end_date=end_date,
                base_currency=base_currency,
                tenant_ids=tenant_ids,
                currency=currency,
                prior_start=prior_start,
                prior_end=prior_end,
                comparison_label=comparison_label,
            )

    return data


__all__ = ["_fetch_domain_report_data"]
