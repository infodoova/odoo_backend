# doova_one_view/api/agent/tools_refactored/reporting/_domain_data/sales.py

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
    """Enriches data dict with Sales & Commercial telemetry (orders, top products, AOV, prior sales)."""
    from doova_one_view.api.agent.tools_refactored import reporting_v2
    get_sales_summary_tool = reporting_v2.get_sales_summary_tool
    get_top_products_tool = reporting_v2.get_top_products_tool

    try:
        sales = get_sales_summary_tool(tenant_ids=tenant_ids, company_ids=company_ids, start_date=start_date, end_date=end_date, base_currency=base_currency)
        top_prods = get_top_products_tool(tenant_ids=tenant_ids, company_ids=company_ids, start_date=start_date, end_date=end_date, limit=10, base_currency=base_currency)
        
        prior_sales = {}
        if prior_start and prior_end:
            try:
                prior_sales = get_sales_summary_tool(tenant_ids=tenant_ids, company_ids=company_ids, start_date=prior_start, end_date=prior_end, base_currency=base_currency)
            except Exception:
                pass

        sales_rev = float(sales.get("total_revenue", 0) or 0)
        prior_sales_rev = float(prior_sales.get("total_revenue", 0) or 0)
        if sales_rev > 0:
            prior_rev_ref = prior_sales_rev or pnl_ctx.get("prior_rev_f", 0.0)
            data["revenue"] = _build_kpi_variance(sales_rev, prior_rev_ref, currency, fmt="money", polarity="positive")
            data["total_revenue"] = _build_kpi_variance(sales_rev, prior_rev_ref, currency, fmt="money", polarity="positive")

        order_cnt = float(sales.get("order_count", 0) or 0)
        prior_order_cnt = float(prior_sales.get("order_count", 0) or 0)
        aov = float(sales.get("average_order_value", 0) or 0)
        prior_aov = float(prior_sales.get("average_order_value", 0) or 0)

        raw_prods = top_prods.get("products", top_prods.get("top_products", []))
        formatted_prods = []
        for p in raw_prods:
            p_name = p.get("product") or p.get("product_name") or p.get("name") or "Product"
            p_qty = float(p.get("quantity") or p.get("qty") or 0)
            p_rev = float(p.get("revenue") or p.get("total_sales") or 0)
            formatted_prods.append({
                "product": p_name,
                "name": p_name,
                "product_name": p_name,
                "quantity": f"{p_qty:,.0f}",
                "qty": f"{p_qty:,.0f}",
                "revenue": _fmt_money(p_rev, currency),
                "gross_margin": f"{float(p.get('gross_margin', 45.0)):.1f}%" if "gross_margin" in p else "—",
            })

        top_cust_rev = float(raw_prods[0].get("revenue", 0) if raw_prods else 0)
        data.update({
            "sales_volume": _build_kpi_variance(order_cnt, prior_order_cnt, currency, fmt="count", polarity="positive"),
            "order_count": _build_kpi_variance(order_cnt, prior_order_cnt, currency, fmt="count", polarity="positive"),
            "avg_order_value": _build_kpi_variance(aov, prior_aov, currency, fmt="money", polarity="positive"),
            "top_products": formatted_prods,
            "top_customer_revenue": top_cust_rev,
            "target_achievement": 100.0,
        })
        if prior_sales_rev > 0 or prior_order_cnt > 0:
            if "prior_period" not in data:
                data["prior_period"] = {}
            data["prior_period"].update({
                "sales_revenue": prior_sales_rev,
                "order_count": prior_order_cnt,
                "avg_order_value": prior_aov,
                "comparison_label": comparison_label,
            })
    except Exception as e:
        logger.warning(f"Sales domain query error: {e}")
