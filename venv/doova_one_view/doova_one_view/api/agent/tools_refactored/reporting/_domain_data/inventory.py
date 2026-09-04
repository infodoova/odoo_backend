# doova_one_view/api/agent/tools_refactored/reporting/_domain_data/inventory.py

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
    comparison_label: str = "",
    **kwargs
) -> None:
    """Enriches data dict with Inventory & Warehouse telemetry (stock valuation, turnover, low stock alerts)."""
    from doova_one_view.api.agent.tools_refactored import reporting_v2
    get_inventory_valuation_tool = getattr(reporting_v2, "get_inventory_valuation_tool", None)
    get_inventory_alerts_tool = getattr(reporting_v2, "get_inventory_alerts_tool", None)
    get_inventory_efficiency_tool = getattr(reporting_v2, "get_inventory_efficiency_tool", None)

    if not get_inventory_valuation_tool:
        from doova_one_view.api.agent.tools_refactored.inventory import get_inventory_valuation_tool
    if not get_inventory_alerts_tool:
        from doova_one_view.api.agent.tools_refactored.inventory import get_inventory_alerts_tool
    if not get_inventory_efficiency_tool:
        from doova_one_view.api.agent.tools_refactored.inventory import get_inventory_efficiency_tool

    try:
        inv_val = get_inventory_valuation_tool(tenant_id, company_ids=resolved_company_ids, tenant_ids=tenant_ids)
        inv_alerts = get_inventory_alerts_tool(tenant_id, company_ids=resolved_company_ids, tenant_ids=tenant_ids)
        inv_eff = get_inventory_efficiency_tool(tenant_id, company_ids=resolved_company_ids, tenant_ids=tenant_ids)

        raw_alerts = inv_alerts.get("low_stock_items", inv_alerts.get("alerts", []))
        formatted_alerts = []
        for a in raw_alerts:
            a_name = a.get("product_name") or a.get("product") or a.get("name") or "Product"
            a_qty = float(a.get("quantity") or a.get("qty") or a.get("available_qty") or 0)
            a_min = float(a.get("min_qty") or a.get("threshold") or 0)
            formatted_alerts.append({
                "product": a_name,
                "name": a_name,
                "product_name": a_name,
                "quantity": f"{a_qty:,.0f}",
                "qty": f"{a_qty:,.0f}",
                "min_qty": f"{a_min:,.0f}" if a_min > 0 else "—",
                "threshold": f"{a_min:,.0f}" if a_min > 0 else "—",
            })

        inv_tot_val = float(inv_val.get("total_value", inv_val.get("total_valuation", 0)) or 0)
        if base_currency:
            from doova_one_view.api.kpi.service import _get_rate_map
            rate_map = _get_rate_map(tenant_id=tenant_id)
            if base_currency in rate_map:
                inv_tot_val = inv_tot_val * rate_map[base_currency]

        sku_cnt = int(inv_val.get("total_products_in_stock", inv_val.get("sku_count", len(raw_alerts))) or len(raw_alerts))
        tot_qty = float(inv_val.get("total_quantity", 0) or 0)
        tot_reserved = float(inv_val.get("total_reserved_quantity", 0) or 0)

        current_cogs = float(pnl_ctx.get("cogs_f", 0.0) or 0.0)
        prior_cogs = float(pnl_ctx.get("prior_cogs_f", 0.0) or 0.0)

        if inv_tot_val > 0 and current_cogs > 0:
            turnover_val = round((current_cogs * 4.0) / inv_tot_val, 2)
            prior_turnover = round((prior_cogs * 4.0) / inv_tot_val, 2) if prior_cogs > 0 else 0.0
            days_on_h = round(inv_tot_val / (current_cogs / 90.0))
            prior_doh = round(inv_tot_val / (prior_cogs / 90.0)) if prior_cogs > 0 else 0.0
        else:
            turnover_val = float(inv_eff.get("turnover_ratio", inv_eff.get("inventory_turnover", 0)) or 0)
            prior_turnover = 0.0
            days_on_h = float(inv_eff.get("days_inventory_on_hand", inv_eff.get("days_sales_of_inventory", 0)) or 0)
            prior_doh = 0.0

        data.update({
            "inventory_valuation": _build_kpi_variance(inv_tot_val, 0, currency, fmt="money", polarity="neutral"),
            "inventory_value": _build_kpi_variance(inv_tot_val, 0, currency, fmt="money", polarity="neutral"),
            "sku_count": _build_kpi_variance(sku_cnt, 0, currency, fmt="count", polarity="neutral"),
            "low_stock_count": _build_kpi_variance(len(raw_alerts), 0, currency, fmt="count", polarity="negative"),
            "low_stock_count_int": len(raw_alerts),
            "low_stock_items": formatted_alerts,
            "low_stock_alerts": formatted_alerts,
            "stock_turnover": _build_kpi_variance(turnover_val, prior_turnover, currency, fmt="ratio", polarity="positive"),
            "days_on_hand": _build_kpi_variance(days_on_h, prior_doh, currency, fmt="count", polarity="negative"),
            "total_units": _build_kpi_variance(tot_qty, 0, currency, fmt="count", polarity="positive"),
            "total_quantity": _build_kpi_variance(tot_qty, 0, currency, fmt="count", polarity="positive"),
            "reserved_units": _build_kpi_variance(tot_reserved, 0, currency, fmt="count", polarity="neutral"),
        })
        if "prior_period" not in data:
            data["prior_period"] = {}
        data["prior_period"].update({
            "approx_prior_cogs": pnl_ctx.get("prior_cogs_f", 0.0),
            "comparison_label": comparison_label,
            "note": "Inventory valuation and SKU counts are point-in-time snapshots.",
        })
    except Exception as e:
        logger.warning(f"Inventory domain query error: {e}")
