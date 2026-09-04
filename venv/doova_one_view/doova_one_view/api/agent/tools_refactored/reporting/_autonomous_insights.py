# doova_one_view/api/agent/tools_refactored/reporting/_autonomous_insights.py

import re
import json
import logging
from typing import Optional, Dict, Any, Tuple, List

from ._formatters import _fmt_money
from ._ai_synthesis import _generate_ai_executive_summary_llm

logger = logging.getLogger(__name__)


def _synthesize_autonomous_insights(
    custom_content: str,
    prompt: str,
    pnl: dict,
    prior_pnl: dict,
    sales: dict,
    receivables: dict,
    payables: dict,
    wc: dict,
    inv: dict,
    expenses_data: dict,
    top_prods: dict,
    currency: str,
    company_name: str,
    period_label: str,
    comparison_label: str,
    rev_val: float,
    gp_val: float,
    gm_pct: float,
    ebit_val: float,
    net_val: float,
    overdue_ar_val: float,
    overdue_ratio: float,
    nwc_val: float,
    cur_ratio_val: float,
    health_score_val: float,
    inv_val: float,
    ap_val: float,
    cash_val: float = 0.0,
    **kwargs
) -> tuple[dict, dict, list]:
    """
    Universally synthesizes:
      1. exec_summary (dict with 6 fields: overall, profitability, positive_driver, negative_driver, liquidity, action)
      2. drivers (dict with positive and negative lists: name, current, impact, explanation)
      3. alerts (list of dicts: priority, priority_class, title, impact, action, owner, status)

    Primary: Direct LLM generation from live ERP financial telemetry.
    Fallback: Resilient deterministic financial heuristics.
    """
    # 1. Check for explicit JSON payload in custom_content or kwargs
    if kwargs.get("exec_summary") and kwargs.get("drivers") and kwargs.get("alerts"):
        return kwargs["exec_summary"], kwargs["drivers"], kwargs["alerts"]

    json_match = re.search(r'```(?:json)?\s*(\{\s*"exec_summary".*?\})\s*```', custom_content, re.DOTALL)
    if json_match:
        try:
            parsed = json.loads(json_match.group(1))
            if isinstance(parsed, dict) and "exec_summary" in parsed:
                return parsed.get("exec_summary", {}), parsed.get("drivers", {}), parsed.get("alerts", [])
        except Exception:
            pass

    # 2. PRIMARY PATH: Generate narrative directly from AI via LLM
    prior_rev = float(prior_pnl.get("revenue", 0) or prior_pnl.get("total_income", 0) or 0)
    growth_pct = ((rev_val - prior_rev) / prior_rev * 100.0) if prior_rev > 0 and rev_val > 0 else 0.0

    prods_list = top_prods.get("top_products", []) if isinstance(top_prods, dict) else []
    top_products_summary = [
        {"name": p.get("product_name") or p.get("name"), "revenue": float(p.get("revenue", 0) or p.get("total_sales", 0) or 0)}
        for p in prods_list[:5]
    ]

    exps_list = expenses_data.get("expenses", []) if isinstance(expenses_data, dict) else []
    top_expenses_summary = [
        {"category": e.get("category") or e.get("account_name"), "amount": float(e.get("amount", 0) or 0)}
        for e in exps_list[:5]
    ]

    telemetry = {
        "company_name": company_name,
        "reporting_period": period_label,
        "comparison_basis": comparison_label,
        "currency": currency,
        "revenue": rev_val,
        "cogs": float(pnl.get("cogs", 0) or 0),
        "gross_profit": gp_val,
        "gross_margin_pct": gm_pct,
        "operating_expenses": float(pnl.get("operating_expenses", 0) or 0),
        "operating_ebit": ebit_val,
        "net_profit": net_val,
        "net_margin_pct": (net_val / rev_val * 100.0) if rev_val > 0 else 0.0,
        "prior_period": {
            "prior_revenue": prior_rev,
            "growth_pct": round(growth_pct, 1),
            "prior_gross_profit": float(prior_pnl.get("gross_profit", 0) or 0),
            "prior_net_profit": float(prior_pnl.get("net_profit", 0) or 0),
        },
        "liquidity_and_solvency": {
            "cash_and_bank_balance": cash_val,
            "net_working_capital": nwc_val,
            "current_ratio": round(cur_ratio_val, 2),
            "health_score": round(health_score_val, 0),
        },
        "receivables_and_payables": {
            "total_accounts_receivable": float(receivables.get("total_receivables", 0) or 0),
            "overdue_receivables_amt": overdue_ar_val,
            "overdue_receivables_ratio_pct": round(overdue_ratio * 100.0, 1),
            "total_accounts_payable": ap_val,
        },
        "inventory_valuation": inv_val,
        "top_products": top_products_summary,
        "top_operating_expenses": top_expenses_summary,
    }

    ai_result = _generate_ai_executive_summary_llm(
        telemetry=telemetry,
        prompt=prompt,
        custom_content=custom_content,
    )
    if ai_result:
        return ai_result[0], ai_result[1], ai_result[2]

    # 3. FALLBACK PATH: Resilient deterministic financial synthesis
    logger.info("Executing deterministic executive summary fallback...")
    dormant_line_match = re.search(r'\b([A-Z0-9\s\-]+?(?:Cars|Vehicles|Motors|Line|Products))\b[^\.\n]*?\b(?:dormant|inactivity|zero units|0 units|stoppage|stalled|no recorded activity)\b', custom_content, re.IGNORECASE)
    dormant_line_name = dormant_line_match.group(1).strip() if dormant_line_match else None

    if prior_rev > 0 and rev_val > 0:
        growth_str = f" ({'+' if growth_pct >= 0 else ''}{growth_pct:.1f}% vs {comparison_label})"
    else:
        growth_str = ""

    # Overall
    status_phrase = "demonstrating strong commercial performance" if health_score_val >= 75 else "maintaining steady business operations" if health_score_val >= 50 else "facing operational and cash flow pressures"
    overall_summary = f"Generated {_fmt_money(rev_val, currency)} across {company_name}{growth_str} for {period_label}, {status_phrase} with an overall business health score of {health_score_val:.0f}/100."

    # Profitability
    net_margin_pct = (net_val / rev_val * 100.0) if rev_val > 0 else 0.0
    if gm_pct >= 35.0:
        prof_summary = f"Strong gross profit margin of {gm_pct:.1f}% ({_fmt_money(gp_val, currency)}) generating {_fmt_money(ebit_val, currency)} in Operating Profit (EBIT) with a {net_margin_pct:.1f}% net margin, confirming healthy core profitability."
    elif gm_pct >= 15.0:
        prof_summary = f"Gross profit margin stands at {gm_pct:.1f}% ({_fmt_money(gp_val, currency)}), yielding an Operating Profit (EBIT) of {_fmt_money(ebit_val, currency)} with steady operating margins."
    else:
        prof_summary = f"Gross profit margin compressed to {gm_pct:.1f}% ({_fmt_money(gp_val, currency)}) yielding {_fmt_money(ebit_val, currency)} in Operating Profit (EBIT), indicating high direct product costs and pricing pressure."

    # Positive Driver
    prods = top_prods.get("top_products", []) if isinstance(top_prods, dict) else []
    if prods and len(prods) > 0 and (prods[0].get("revenue") or prods[0].get("total_sales")):
        top_p = prods[0]
        top_p_name = top_p.get("product_name") or top_p.get("name") or "Core Trading Products"
        top_p_rev = float(top_p.get("revenue", 0) or top_p.get("total_sales", 0) or 0)
        pos_summary = f"Strong sales volume in {top_p_name} ({_fmt_money(top_p_rev, currency)}) serving as the primary driver for top-line revenue and gross profit."
    elif rev_val > 0:
        pos_summary = f"Core commercial sales ({_fmt_money(rev_val, currency)}) successfully delivering {_fmt_money(gp_val, currency)} in gross profit contribution."
    else:
        pos_summary = f"Available cash reserves and baseline trading operations supporting ongoing business continuity."

    # Negative Driver
    if dormant_line_name:
        neg_summary = f"{dormant_line_name} inactivity with zero sales recorded across the reporting period."
    elif overdue_ratio > 0.20:
        neg_summary = f"Delayed customer collections with {_fmt_money(overdue_ar_val, currency)} ({overdue_ratio*100:.1f}% of unpaid customer invoices) currently past due."
    elif expenses_data.get("expenses"):
        top_e = expenses_data["expenses"][0]
        e_name = top_e.get("category") or top_e.get("account_name") or "Operating Overhead"
        e_amt = float(top_e.get("amount", 0) or 0)
        neg_summary = f"Operating cost growth in {e_name} consuming {_fmt_money(e_amt, currency)} of cash flow."
    else:
        neg_summary = f"Working capital locked in unpaid customer invoices ({_fmt_money(overdue_ar_val, currency)}) delaying incoming cash flow."

    # Liquidity
    if cur_ratio_val >= 1.5:
        liq_summary = f"Net Working Capital is {_fmt_money(nwc_val, currency)} with a healthy Current Ratio of {cur_ratio_val:.2f}x (ability to pay short-term bills), maintaining a comfortable safety buffer."
    elif cur_ratio_val >= 1.0:
        liq_summary = f"Net Working Capital stands at {_fmt_money(nwc_val, currency)} with a Current Ratio of {cur_ratio_val:.2f}x, requiring prompt customer invoice collections to maintain bill payments."
    else:
        liq_summary = f"Working capital deficit of {_fmt_money(nwc_val, currency)} (Current Ratio {cur_ratio_val:.2f}x) signals short-term cash flow strain when paying supplier bills."

    # Management Action
    if overdue_ratio > 0.25:
        action_summary = "Send automated payment reminders to late customers, pause new credit for accounts past 60 days overdue, and prioritize direct outreach on top debtor accounts."
    elif dormant_line_name:
        action_summary = f"Engage partner and distribution leadership immediately to resolve product supply allocation and restart sales for the {dormant_line_name} line."
    elif cur_ratio_val < 1.1:
        action_summary = "Accelerate overdue invoice collections and coordinate vendor payment schedules to protect cash flow reserves."
    else:
        action_summary = "Maintain periodic customer credit reviews and monitor product profit margins to sustain long-term business growth."

    exec_summary = {
        "overall": overall_summary,
        "profitability": prof_summary,
        "positive_driver": pos_summary,
        "negative_driver": neg_summary,
        "liquidity": liq_summary,
        "action": action_summary
    }

    # 4. Dynamic Performance Drivers Table
    actual_margin_ratio = (gm_pct / 100.0) if gm_pct > 0 else 0.35
    pos_drivers = []
    for p in prods[:3]:
        p_name = p.get("product_name") or p.get("name") or "Core Trade Goods"
        p_rev = float(p.get("revenue", 0) or p.get("total_sales", 0) or 0)
        p_impact = p_rev * actual_margin_ratio
        pos_drivers.append({
            "name": p_name,
            "current": _fmt_money(p_rev, currency),
            "impact": _fmt_money(p_impact, currency),
            "explanation": f"High demand and commercial velocity driving {_fmt_money(p_rev, currency)} in category expansion."
        })

    if not pos_drivers:
        pos_drivers.append({
            "name": "Commercial Trading Revenue",
            "current": _fmt_money(rev_val, currency),
            "impact": _fmt_money(gp_val, currency),
            "explanation": f"Core commercial trading volume delivering {_fmt_money(gp_val, currency)} in gross margin contribution."
        })
        if cash_val > 0:
            pos_drivers.append({
                "name": "Liquid Bank & Cash Reserves",
                "current": _fmt_money(cash_val, currency),
                "impact": _fmt_money(cash_val, currency),
                "explanation": "Liquid book balances providing operating runway and working capital support."
            })
        elif ebit_val > 0:
            pos_drivers.append({
                "name": "Operating Earnings (EBIT)",
                "current": _fmt_money(ebit_val, currency),
                "impact": _fmt_money(ebit_val, currency),
                "explanation": f"Positive operating profitability ({gm_pct:.1f}% gross margin) supporting business continuity."
            })

    neg_drivers = []
    if dormant_line_name:
        neg_drivers.append({
            "name": f"{dormant_line_name} Inactivity",
            "current": _fmt_money(0, currency),
            "impact": _fmt_money(0, currency),
            "explanation": "Category sales stoppage with zero units sold and zero revenue contribution across the period."
        })

    if overdue_ar_val > 0:
        neg_drivers.append({
            "name": "Overdue Customer Receivables",
            "current": _fmt_money(overdue_ar_val, currency),
            "impact": _fmt_money(overdue_ar_val, currency),
            "explanation": f"Capital locked in outstanding invoices ({overdue_ratio*100:.1f}% overdue) delaying operating cash flow."
        })

    exps = expenses_data.get("expenses", []) if isinstance(expenses_data, dict) else []
    for e in exps[:2]:
        e_name = e.get("category") or e.get("account_name") or "Operational Overhead"
        e_amt = float(e.get("amount", 0) or 0)
        neg_drivers.append({
            "name": e_name,
            "current": _fmt_money(e_amt, currency),
            "impact": _fmt_money(e_amt, currency),
            "explanation": "Direct operational expenditure requiring ongoing procurement cost controls."
        })

    if not neg_drivers:
        neg_drivers.append({
            "name": "Operational Overhead & Cost Baseline",
            "current": _fmt_money(float(pnl.get('cogs', 0) or 0), currency),
            "impact": _fmt_money(float(pnl.get('cogs', 0) or 0), currency),
            "explanation": "Cost of goods and operational baseline requiring disciplined procurement management."
        })

    drivers = {
        "positive": pos_drivers,
        "negative": neg_drivers
    }

    # 5. Dynamic Prioritized Management Alerts Table
    alerts = []
    if overdue_ratio > 0.15 or overdue_ar_val > 0:
        is_crit = overdue_ratio > 0.40
        alerts.append({
            "priority": "Critical" if is_crit else "High",
            "priority_class": "critical" if is_crit else "high",
            "title": f"Overdue Receivables Exposure ({overdue_ratio*100:.1f}%)",
            "impact": _fmt_money(overdue_ar_val, currency),
            "action": "Trigger automated dunning workflow, suspend credit for accounts past 60 days, and prioritize collection outreach.",
            "owner": "Credit & Collections",
            "status": "Action Required"
        })

    if dormant_line_name:
        alerts.append({
            "priority": "Critical",
            "priority_class": "critical",
            "title": f"{dormant_line_name} Inactivity",
            "impact": _fmt_money(0, currency),
            "action": f"Engage distributor leadership immediately to resolve supply allocation, financing, or demand bottlenecks.",
            "owner": "Commercial & Distribution",
            "status": "Action Required"
        })

    prior_gm = float(prior_pnl.get("gross_margin_pct", 0) or 0)
    if prior_gm > 0 and gm_pct < prior_gm - 5.0:
        alerts.append({
            "priority": "High",
            "priority_class": "high",
            "title": f"Gross Margin Contraction (-{prior_gm - gm_pct:.1f} pts)",
            "impact": _fmt_money(abs(gp_val - float(prior_pnl.get('gross_profit', 0) or 0)), currency),
            "action": "Audit product sales mix pricing, review customer discounting thresholds, and renegotiate supplier purchase costs.",
            "owner": "Commercial & Pricing",
            "status": "Action Required"
        })

    if cur_ratio_val < 1.3 and cur_ratio_val > 0:
        alerts.append({
            "priority": "High" if cur_ratio_val < 1.0 else "Medium",
            "priority_class": "high" if cur_ratio_val < 1.0 else "medium",
            "title": f"Tight Liquidity Buffer (CR {cur_ratio_val:.2f}x)",
            "impact": _fmt_money(nwc_val, currency),
            "action": "Align vendor disbursements with confirmed incoming customer collections schedule to safeguard cash flow.",
            "owner": "Treasury",
            "status": "Monitoring"
        })

    alerts.append({
        "priority": "Medium",
        "priority_class": "medium",
        "title": "Inventory Capital & Reorder Optimization",
        "impact": _fmt_money(inv_val, currency),
        "action": "Execute fast-track reordering for low-stock SKUs and conduct slow-moving stock audit to free working capital.",
        "owner": "Supply Chain",
        "status": "In Progress"
    })

    return exec_summary, drivers, alerts
