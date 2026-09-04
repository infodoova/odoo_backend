# doova_one_view/api/agent/tools_refactored/reporting/_domain_data/purchase.py

import logging
from typing import Optional, List, Dict, Any

from .._formatters import _fmt_money
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
    """Enriches data dict with Purchasing & Procurement telemetry (PO count, spend, AP aging, top vendors)."""
    from doova_one_view.api.agent.tools_refactored import reporting_v2
    get_purchase_summary_tool = reporting_v2.get_purchase_summary_tool
    get_top_vendors_tool = reporting_v2.get_top_vendors_tool
    get_payables_analysis_tool = reporting_v2.get_payables_analysis_tool
    get_aging_analysis_tool = reporting_v2.get_aging_analysis_tool

    try:
        purch = get_purchase_summary_tool(tenant_id, company_ids=resolved_company_ids, start_date=start_date, end_date=end_date, base_currency=base_currency, tenant_ids=tenant_ids)
        top_v = get_top_vendors_tool(tenant_id, company_ids=resolved_company_ids, start_date=start_date, end_date=end_date, limit=10, base_currency=base_currency, tenant_ids=tenant_ids)
        payables = get_payables_analysis_tool(tenant_id, company_ids=resolved_company_ids, base_currency=base_currency, tenant_ids=tenant_ids)

        prior_purch = {}
        if prior_start and prior_end:
            try:
                prior_purch = get_purchase_summary_tool(tenant_id, company_ids=resolved_company_ids, start_date=prior_start, end_date=prior_end, base_currency=base_currency, tenant_ids=tenant_ids)
            except Exception:
                pass

        raw_vendors = top_v.get("vendors", top_v.get("top_vendors", []))
        formatted_vendors = []
        top_v_spend = 0.0
        for v in raw_vendors:
            v_name = v.get("vendor") or v.get("vendor_name") or v.get("name") or "Vendor"
            v_spend = float(v.get("total_spend") or v.get("amount") or v.get("total_purchases") or 0)
            v_pos = int(v.get("po_count") or v.get("orders") or 0)
            if not top_v_spend:
                top_v_spend = v_spend
            formatted_vendors.append({
                "vendor": v_name,
                "name": v_name,
                "vendor_name": v_name,
                "amount": _fmt_money(v_spend, currency),
                "total_spent": _fmt_money(v_spend, currency),
                "po_count": f"{v_pos:,}",
                "orders": f"{v_pos:,}",
                "outstanding": "—",
            })

        total_purch = float(purch.get("total_spend", purch.get("total_purchases", 0)) or 0)
        po_cnt = int(purch.get("po_count", purch.get("order_count", 0)) or 0)
        avg_po = float(purch.get("avg_po_value", purch.get("average_order_value", 0)) or (total_purch / po_cnt if po_cnt > 0 else 0))

        prior_total_purch = float(prior_purch.get("total_spend", prior_purch.get("total_purchases", 0)) or 0)
        prior_po_cnt = int(prior_purch.get("po_count", prior_purch.get("order_count", 0)) or 0)
        prior_avg_po = float(prior_purch.get("avg_po_value", prior_purch.get("average_order_value", 0)) or (prior_total_purch / prior_po_cnt if prior_po_cnt > 0 else 0))

        ap_aging_tool = get_aging_analysis_tool(tenant_id, direction="payable", company_ids=resolved_company_ids, base_currency=base_currency, tenant_ids=tenant_ids)
        ap_c = float(ap_aging_tool.get("current", 0) or 0.0)
        ap_c_cnt = int(ap_aging_tool.get("current_cnt", 0) or 0)
        ap_d1 = float(ap_aging_tool.get("1_30_days", 0) or 0.0)
        ap_d1_cnt = int(ap_aging_tool.get("1_30_days_cnt", 0) or 0)
        ap_d2 = float(ap_aging_tool.get("31_60_days", 0) or 0.0)
        ap_d2_cnt = int(ap_aging_tool.get("31_60_days_cnt", 0) or 0)
        ap_d3 = float(ap_aging_tool.get("61_90_days", 0) or 0.0)
        ap_d3_cnt = int(ap_aging_tool.get("61_90_days_cnt", 0) or 0)
        ap_d4 = float(ap_aging_tool.get("91_120_days", 0) or 0.0)
        ap_d4_cnt = int(ap_aging_tool.get("91_120_days_cnt", 0) or 0)
        ap_older = float(ap_aging_tool.get("older", 0) or 0.0)
        ap_older_cnt = int(ap_aging_tool.get("older_cnt", 0) or 0)

        ap_t = ap_c + ap_d1 + ap_d2 + ap_d3 + ap_d4 + ap_older or 1.0
        overdue_ap = ap_d1 + ap_d2 + ap_d3 + ap_d4 + ap_older
        overdue_pct = (overdue_ap / ap_t * 100.0) if ap_t > 0 else 0.0

        ap_aging_rows = [
            {"bracket": "current", "count": ap_c_cnt, "count_formatted": f"{ap_c_cnt:,} Bills", "amount": _fmt_money(ap_c, currency), "share": f"{(ap_c / ap_t * 100):.1f}%", "risk": "Low", "badge_class": "badge-success"},
            {"bracket": "1-30 days", "count": ap_d1_cnt, "count_formatted": f"{ap_d1_cnt:,} Bills", "amount": _fmt_money(ap_d1, currency), "share": f"{(ap_d1 / ap_t * 100):.1f}%", "risk": "Normal", "badge_class": "badge-info"},
            {"bracket": "31-60 days", "count": ap_d2_cnt, "count_formatted": f"{ap_d2_cnt:,} Bills", "amount": _fmt_money(ap_d2, currency), "share": f"{(ap_d2 / ap_t * 100):.1f}%", "risk": "Moderate", "badge_class": "badge-warning"},
            {"bracket": "61-90 days", "count": ap_d3_cnt, "count_formatted": f"{ap_d3_cnt:,} Bills", "amount": _fmt_money(ap_d3, currency), "share": f"{(ap_d3 / ap_t * 100):.1f}%", "risk": "Watch", "badge_class": "badge-warning"},
            {"bracket": "91-120 days", "count": ap_d4_cnt, "count_formatted": f"{ap_d4_cnt:,} Bills", "amount": _fmt_money(ap_d4, currency), "share": f"{(ap_d4 / ap_t * 100):.1f}%", "risk": "Elevated", "badge_class": "badge-warning"},
            {"bracket": "Older", "count": ap_older_cnt, "count_formatted": f"{ap_older_cnt:,} Bills", "amount": _fmt_money(ap_older, currency), "share": f"{(ap_older / ap_t * 100):.1f}%", "risk": "High Risk", "badge_class": "badge-danger"},
        ]

        data.update({
            "total_purchases": _build_kpi_variance(total_purch, prior_total_purch, currency, fmt="money", polarity="negative"),
            "total_purchase_spend": _build_kpi_variance(total_purch, prior_total_purch, currency, fmt="money", polarity="negative"),
            "purchase_spend": _build_kpi_variance(total_purch, prior_total_purch, currency, fmt="money", polarity="negative"),
            "po_count": _build_kpi_variance(po_cnt, prior_po_cnt, currency, fmt="count", polarity="positive"),
            "avg_po_value": _build_kpi_variance(avg_po, prior_avg_po, currency, fmt="money", polarity="neutral"),
            "top_supplier_spend": _build_kpi_variance(top_v_spend, 0, currency, fmt="money", polarity="negative"),
            "accounts_payable": _build_kpi_variance(ap_t, 0, currency, fmt="money", polarity="negative"),
            "overdue_payables_pct": _build_kpi_variance(overdue_pct, 0, currency, fmt="pct", polarity="negative"),
            "top_vendors": formatted_vendors,
            "top_suppliers": formatted_vendors,
            "ap_aging": ap_aging_rows,
        })
        if prior_total_purch > 0 or prior_po_cnt > 0:
            if "prior_period" not in data:
                data["prior_period"] = {}
            data["prior_period"].update({
                "total_purchases": prior_total_purch,
                "po_count": prior_po_cnt,
                "avg_po_value": prior_avg_po,
                "comparison_label": comparison_label,
            })
    except Exception as e:
        logger.warning(f"Purchase domain query error: {e}")
