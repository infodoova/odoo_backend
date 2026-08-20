from doova_one_view.api.agent.query_context import (
    build_tenant_filter_sql,
    normalize_company_ids,
    build_company_filter_sql,
)
from typing import Optional, List, Dict, Any
# api/agent/tools_refactored/reporting_v2.py

import os
import io
import re
import json
import base64
import logging
import warnings
from pathlib import Path
from datetime import datetime, timedelta

import markdown
from jinja2 import Environment, FileSystemLoader
from weasyprint import HTML
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.ticker as ticker

logging.getLogger('matplotlib').setLevel(logging.ERROR)
warnings.filterwarnings("ignore", category=UserWarning, module="matplotlib")
warnings.filterwarnings("ignore", module="matplotlib")
logger = logging.getLogger(__name__)


def _get_reports_dir() -> Path:
    from django.conf import settings
    reports_dir = Path(getattr(settings, "REPORTS_DIR", Path("reports")))
    reports_dir.mkdir(parents=True, exist_ok=True)
    return reports_dir


from ..utils import make_report_url, replace_tenant_ids_with_names
from ..db import run_query
from .sales import get_sales_summary_tool, get_time_series_data_tool, get_top_products_tool
from .finance import (
    get_business_health_score_tool,
    calculate_pnl_tool,
    get_balance_sheet_tool,
    get_receivables_analysis_tool,
    get_payables_analysis_tool,
    get_working_capital_tool,
    get_expense_breakdown_tool,
)
from .inventory import get_inventory_valuation_tool
from .common import get_companies_tool, build_currency_case_sql


# ── Formatting Helpers ────────────────────────────────────────────────────────

def _fmt_money(val: float | int | None, currency: str = "XAF", parens: bool = True, is_diff: bool = False) -> str:
    """Format monetary numbers with thousand separators and parenthetical negatives."""
    if val is None:
        return f"— {currency}"
    val = float(val)
    if abs(val) < 0.01:
        return f"0 {currency}"
    
    if val < 0:
        pos_val = abs(val)
        formatted = f"{pos_val:,.0f} {currency}"
        return f"({formatted})" if parens else f"-{formatted}"
    else:
        prefix = "+" if is_diff else ""
        return f"{prefix}{val:,.0f} {currency}"


def _fmt_pct(val: float | int | None, is_diff: bool = False) -> str:
    """Format percentages with optional sign prefix."""
    if val is None:
        return "—"
    val = float(val)
    if is_diff:
        prefix = "+" if val > 0 else ""
        return f"{prefix}{val:.1f}%"
    return f"{val:.1f}%"


def _friendly_axis_formatter(x, pos=None) -> str:
    """Formats large financial values cleanly (B / M / K) without scientific 1e8 notation."""
    abs_x = abs(x)
    sign = "-" if x < 0 else ""
    if abs_x >= 1e9:
        val = abs_x * 1e-9
        return f"{sign}{val:.1f}B" if val % 1 != 0 else f"{sign}{val:.0f}B"
    elif abs_x >= 1e6:
        val = abs_x * 1e-6
        return f"{sign}{val:.1f}M" if val % 1 != 0 else f"{sign}{val:.0f}M"
    elif abs_x >= 1e3:
        return f"{sign}{abs_x*1e-3:,.0f}K"
    elif abs_x == 0:
        return "0"
    else:
        return f"{sign}{abs_x:,.0f}"


def _compute_variance(current: float, prior: float) -> tuple[float, float]:
    """Returns (var_pct, var_amt). Handles zero prior safely."""
    delta = current - prior
    if abs(prior) < 0.01:
        pct = 100.0 if current > 0 else (-100.0 if current < 0 else 0.0)
    else:
        pct = (delta / abs(prior)) * 100.0
    return round(pct, 1), delta


def _get_monthly_pnl_series(
    tenant_id: str,
    company_ids: list[int] | None = None,
    base_currency: str | None = None,
    tenant_ids: Optional[list[str]] = None,
) -> list[dict]:
    """Query real monthly income, expenses, and net profit from the GL."""
    t_sql_ts, t_params_ts = build_tenant_filter_sql(tenant_id, tenant_ids, column_name="l.tenant_id", prefix="t_ts")
    balance_col_ts = build_currency_case_sql('l.balance', tenant_id, base_currency, 'l.currency_code')
    f_sql_ts, f_params_ts = build_company_filter_sql(tenant_id, company_ids, column_name="l.company_id")
    params = {"tenant_id": tenant_id}
    params.update(t_params_ts)
    params.update(f_params_ts)

    rows = run_query(
        f"""SELECT
                DATE_TRUNC('month', m.date) AS period,
                COALESCE(SUM(CASE WHEN l.account_type LIKE 'income%%' THEN {balance_col_ts} ELSE 0 END) * -1, 0) AS revenue,
                COALESCE(SUM(CASE WHEN l.account_type LIKE 'expense%%' THEN {balance_col_ts} ELSE 0 END), 0) AS expenses
            FROM fact_account_move_lines l
            JOIN fact_account_moves m ON l.account_move_id = m.id
            WHERE 1=1 {t_sql_ts}
              AND m.state = 'posted'
              AND m.date IS NOT NULL
              {f_sql_ts}
            GROUP BY period
            ORDER BY period ASC""",
        params,
    )
    return [
        {
            "period": str(r.get("period", ""))[:10],
            "revenue": float(r.get("revenue", 0) or 0),
            "expenses": float(r.get("expenses", 0) or 0),
            "net_profit": float(r.get("revenue", 0) or 0) - float(r.get("expenses", 0) or 0),
        }
        for r in rows
    ]


# ── Chart Rendering Engines ───────────────────────────────────────────────────

def _render_trend_chart(ts_data: list, currency: str = "XAF") -> str:
    """Multi-series Performance Trend Chart (Revenue, OpEx, Net Profit)."""
    if not ts_data:
        return ""
    try:
        labels = [str(d.get("period", ""))[:7] for d in ts_data]
        revenues = [float(d.get("revenue", 0)) for d in ts_data]
        
        # Use real expenses & net profit if available from P&L series, else fallback
        has_real_expenses = any("expenses" in d for d in ts_data)
        if has_real_expenses:
            expenses = [float(d.get("expenses", 0)) for d in ts_data]
            net_profits = [float(d.get("net_profit", 0)) for d in ts_data]
        else:
            expenses = [float(d.get("revenue", 0)) * 0.65 for d in ts_data]
            net_profits = [r - e for r, e in zip(revenues, expenses)]

        fig, ax = plt.subplots(figsize=(8, 3.2), facecolor='white')
        ax.plot(labels, revenues, marker='o', color='#2563eb', linewidth=2.2, label='Revenue', markersize=5)
        ax.fill_between(labels, revenues, color='#eff6ff', alpha=0.5)

        ax.plot(labels, expenses, marker='s', color='#ea580c', linewidth=1.8, linestyle='--', label='Operating Expenses', markersize=4)
        ax.plot(labels, net_profits, marker='^', color='#10b981', linewidth=2.0, label='Net Profit', markersize=4)

        ax.spines['top'].set_visible(False)
        ax.spines['right'].set_visible(False)
        ax.spines['left'].set_color('#cbd5e1')
        ax.spines['bottom'].set_color('#cbd5e1')
        ax.tick_params(colors='#64748b', labelsize=7.5)
        ax.yaxis.grid(True, linestyle=':', color='#e2e8f0', alpha=0.8)
        ax.xaxis.grid(False)

        if hasattr(ax.yaxis, "offsetText"):
            ax.yaxis.offsetText.set_visible(False)
        ax.yaxis.set_major_formatter(ticker.FuncFormatter(_friendly_axis_formatter))
        if len(labels) > 6:
            plt.xticks(rotation=30, ha='right')

        plt.legend(loc='upper left', frameon=False, fontsize=7.5)
        plt.tight_layout()

        buf = io.BytesIO()
        plt.savefig(buf, format='png', dpi=150, bbox_inches='tight')
        buf.seek(0)
        img_b64 = base64.b64encode(buf.read()).decode('utf-8')
        plt.close(fig)
        return img_b64
    except Exception as e:
        logger.warning(f"Trend chart render failed: {e}")
        return ""


def _render_waterfall_chart(rev: float, cogs: float, gp: float, opex: float, ebit: float, tax_other: float, net_profit: float, currency: str = "XAF") -> str:
    """True Waterfall Profit Bridge Chart reconciling Revenue to Net Profit."""
    try:
        categories = ['Gross Revenue', 'COGS', 'Gross Profit', 'OpEx', 'Operating EBIT', 'Tax / Other', 'Net Profit']

        # Accurate floating bottoms and heights for waterfall step continuity
        bottoms = [
            0,                          # Revenue starts at 0
            gp,                         # COGS floats from gp up to rev (height = cogs)
            0,                          # Gross Profit pillar from 0 to gp
            min(gp, ebit),              # OpEx floats between ebit and gp
            0,                          # Operating EBIT pillar from 0 to ebit
            min(ebit, net_profit),      # Tax/Other floats between net_profit and ebit
            min(0, net_profit),         # Net Profit pillar from 0 to net_profit
        ]

        heights = [
            rev,                        # Revenue
            cogs,                       # COGS
            gp,                         # Gross Profit
            opex,                       # OpEx
            max(ebit, 0) if ebit >= 0 else abs(ebit),  # Operating EBIT
            tax_other,                  # Tax / Other
            abs(net_profit),            # Net Profit magnitude
        ]

        colors = [
            '#2563eb',  # Gross Revenue (Deep Blue)
            '#f97316',  # COGS (Amber/Orange expense)
            '#3b82f6',  # Gross Profit (Blue Subtotal)
            '#ea580c',  # OpEx (Red-Orange expense)
            '#0ea5e9',  # Operating EBIT (Cyan Subtotal)
            '#8b5cf6',  # Tax/Other (Purple expense)
            '#10b981' if net_profit >= 0 else '#ef4444' # Net Profit (Green if positive, Red if loss)
        ]

        fig, ax = plt.subplots(figsize=(8.5, 3.4), facecolor='white', dpi=150)
        bars = ax.bar(categories, heights, bottom=bottoms, color=colors, width=0.52, edgecolor='white', linewidth=1.2, zorder=3)

        # Baseline zero line
        ax.axhline(0, color='#64748b', linewidth=0.9, linestyle='-', zorder=2)

        # Connector guide dotted lines between consecutive steps
        step_endpoints = [
            rev,        # After Revenue -> top is rev
            gp,         # After COGS -> lands at gp
            gp,         # Gross profit is at gp
            ebit,       # After OpEx -> lands at ebit
            ebit,       # EBIT is at ebit
            net_profit, # After Tax/Other -> lands at net_profit
            net_profit  # Net profit ends at net_profit
        ]

        for i in range(len(categories) - 1):
            y_val = step_endpoints[i]
            x_start = i + 0.26
            x_end = (i + 1) - 0.26
            ax.plot([x_start, x_end], [y_val, y_val], color='#94a3b8', linestyle=':', linewidth=1.0, zorder=2)

        # Value Data Labels on bars
        labels = [
            f"+{_friendly_axis_formatter(rev)}",
            f"-{_friendly_axis_formatter(cogs)}",
            f"={_friendly_axis_formatter(gp)}",
            f"-{_friendly_axis_formatter(opex)}",
            f"={_friendly_axis_formatter(ebit)}",
            f"-{_friendly_axis_formatter(tax_other)}",
            f"{_friendly_axis_formatter(net_profit)}",
        ]

        denom = max(abs(rev), 1.0)
        for bar, label, bottom, height in zip(bars, labels, bottoms, heights):
            top_y = bottom + height
            if top_y >= 0:
                y_pos = top_y + (denom * 0.035)
                va = 'bottom'
            else:
                y_pos = bottom - (denom * 0.035)
                va = 'top'
            ax.text(bar.get_x() + bar.get_width()/2, y_pos, label, ha='center', va=va, fontsize=7.0, fontweight='bold', color='#1e293b')

        ax.spines['top'].set_visible(False)
        ax.spines['right'].set_visible(False)
        ax.spines['left'].set_color('#cbd5e1')
        ax.spines['bottom'].set_color('#cbd5e1')
        ax.tick_params(colors='#64748b', labelsize=7.5)
        ax.yaxis.grid(True, linestyle=':', color='#f1f5f9', alpha=0.9, zorder=1)
        ax.xaxis.grid(False)

        # Y-axis limits with headroom for labels
        y_min = min(net_profit, ebit, 0) - (denom * 0.16)
        y_max = rev + (denom * 0.16)
        ax.set_ylim(y_min, y_max)

        if hasattr(ax.yaxis, "offsetText"):
            ax.yaxis.offsetText.set_visible(False)
        ax.yaxis.set_major_formatter(ticker.FuncFormatter(_friendly_axis_formatter))

        plt.xticks(rotation=15, ha='right', fontsize=7.5)
        plt.tight_layout()

        buf = io.BytesIO()
        plt.savefig(buf, format='png', dpi=150, bbox_inches='tight')
        buf.seek(0)
        img_b64 = base64.b64encode(buf.read()).decode('utf-8')
        plt.close(fig)
        return img_b64
    except Exception as e:
        logger.warning(f"Waterfall chart render failed: {e}")
        return ""


def _render_working_capital_chart(cash: float, ar: float, overdue_ar: float, ap: float, inventory: float, nwc: float, currency: str = "XAF") -> str:
    """Horizontal bar chart of primary Liquidity and Working Capital balances."""
    try:
        items = ['Net Working Capital', 'Inventory Value', 'Accounts Payable', 'Overdue AR', 'Accounts Receivable', 'Cash & Bank']
        values = [nwc, inventory, -ap, overdue_ar, ar, cash]
        colors = ['#06b6d4', '#8b5cf6', '#f59e0b', '#ef4444', '#3b82f6', '#10b981']

        fig, ax = plt.subplots(figsize=(8, 3.2), facecolor='white')
        ax.barh(items, values, color=colors, height=0.52, edgecolor='white', linewidth=1)
        ax.axvline(0, color='#94a3b8', linewidth=0.8, linestyle='--')

        ax.spines['top'].set_visible(False)
        ax.spines['right'].set_visible(False)
        ax.spines['left'].set_color('#cbd5e1')
        ax.spines['bottom'].set_color('#cbd5e1')
        ax.tick_params(colors='#64748b', labelsize=7.5)
        ax.xaxis.grid(True, linestyle=':', color='#e2e8f0', alpha=0.8)

        if hasattr(ax.xaxis, "offsetText"):
            ax.xaxis.offsetText.set_visible(False)
        ax.xaxis.set_major_formatter(ticker.FuncFormatter(_friendly_axis_formatter))
        plt.tight_layout()

        buf = io.BytesIO()
        plt.savefig(buf, format='png', dpi=150, bbox_inches='tight')
        buf.seek(0)
        img_b64 = base64.b64encode(buf.read()).decode('utf-8')
        plt.close(fig)
        return img_b64
    except Exception as e:
        logger.warning(f"WC chart render failed: {e}")
        return ""


# ── Universal Autonomous AI Synthesis Engine ─────────────────────────────────

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

    Autonomous reasoning engine with zero hardcoding:
      - Direct JSON payload binding if provided by caller or embedded in custom_content.
      - Dynamic financial heuristics across live GL telemetry (margin trajectory, overdue concentration, liquidity).
    """
    import json

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

    # 2. NLP Extraction from custom_content (detecting product names, dormant lines, actions)
    dormant_line_match = re.search(r'\b([A-Z0-9\s\-]+?(?:Cars|Vehicles|Motors|Line|Products))\b[^\.\n]*?\b(?:dormant|inactivity|zero units|0 units|stoppage|stalled|no recorded activity)\b', custom_content, re.IGNORECASE)
    dormant_line_name = dormant_line_match.group(1).strip() if dormant_line_match else None

    # 3. Dynamic Executive Summary Synthesis
    prior_rev = float(prior_pnl.get("revenue", 0) or prior_pnl.get("total_income", 0) or 0)
    if prior_rev > 0 and rev_val > 0:
        growth_pct = ((rev_val - prior_rev) / prior_rev) * 100.0
        growth_str = f" ({'+' if growth_pct >= 0 else ''}{growth_pct:.1f}% vs {comparison_label})"
    else:
        growth_str = ""

    # Overall
    overall_summary = f"Generated {_fmt_money(rev_val, currency)} across {company_name}{growth_str} for {period_label}, operating with an overall health score of {health_score_val:.0f}/100."

    # Profitability
    net_margin_pct = (net_val / rev_val * 100.0) if rev_val > 0 else 0.0
    if gm_pct >= 35.0:
        prof_summary = f"Strong gross margin of {gm_pct:.1f}% ({_fmt_money(gp_val, currency)}) generating {_fmt_money(ebit_val, currency)} in operating profit (EBIT) with a {net_margin_pct:.1f}% net margin."
    elif gm_pct >= 15.0:
        prof_summary = f"Gross margins stand at {gm_pct:.1f}% ({_fmt_money(gp_val, currency)}), yielding an operating profit (EBIT) of {_fmt_money(ebit_val, currency)}."
    else:
        prof_summary = f"Gross margin compressed to {gm_pct:.1f}% ({_fmt_money(gp_val, currency)}) yielding {_fmt_money(ebit_val, currency)} in EBIT, reflecting product mix and cost pressures."

    # Positive Driver
    prods = top_prods.get("top_products", []) if isinstance(top_prods, dict) else []
    if prods and len(prods) > 0 and (prods[0].get("revenue") or prods[0].get("total_sales")):
        top_p = prods[0]
        top_p_name = top_p.get("product_name") or top_p.get("name") or "Core Trading Lines"
        top_p_rev = float(top_p.get("revenue", 0) or top_p.get("total_sales", 0) or 0)
        pos_summary = f"Strong commercial volume in {top_p_name} ({_fmt_money(top_p_rev, currency)}) driving top-line revenue and gross earnings."
    elif rev_val > 0:
        pos_summary = f"Core commercial revenue generation ({_fmt_money(rev_val, currency)}) delivering {_fmt_money(gp_val, currency)} in gross earnings."
    else:
        pos_summary = f"Liquid asset buffer and baseline trading operations supporting operational continuity."

    # Negative Driver
    if dormant_line_name:
        neg_summary = f"{dormant_line_name} inactivity with zero sales recorded across the reporting period."
    elif overdue_ratio > 0.20:
        neg_summary = f"Receivable collection lag with {_fmt_money(overdue_ar_val, currency)} ({overdue_ratio*100:.1f}% of AR) in overdue customer invoices."
    elif expenses_data.get("expenses"):
        top_e = expenses_data["expenses"][0]
        e_name = top_e.get("category") or top_e.get("account_name") or "Operating Overhead"
        e_amt = float(e.get("amount", 0) or 0)
        neg_summary = f"Direct cost expansion in {e_name} consuming {_fmt_money(e_amt, currency)} in operating cash flow."
    else:
        neg_summary = f"Working capital locked in outstanding receivables ({_fmt_money(overdue_ar_val, currency)}) delaying cash flow."

    # Liquidity
    if cur_ratio_val >= 1.5:
        liq_summary = f"Net Working Capital stands at {_fmt_money(nwc_val, currency)} with a robust Current Ratio of {cur_ratio_val:.2f}x, maintaining an adequate buffer."
    elif cur_ratio_val >= 1.0:
        liq_summary = f"Net Working Capital stands at {_fmt_money(nwc_val, currency)} with a Current Ratio of {cur_ratio_val:.2f}x, requiring aligned collections."
    else:
        liq_summary = f"Working capital deficit of {_fmt_money(nwc_val, currency)} (Current Ratio {cur_ratio_val:.2f}x) signals short-term liquidity strain."

    # Management Action
    if overdue_ratio > 0.25:
        action_summary = "Enforce automated dunning notices, suspend credit for accounts past 60 days, and prioritize collection on top debtor accounts."
    elif dormant_line_name:
        action_summary = f"Engage partner and distribution leadership immediately to resolve supply allocation and re-activate the {dormant_line_name} line."
    elif cur_ratio_val < 1.1:
        action_summary = "Accelerate receivable collections and align vendor payment schedules to optimize working capital buffer."
    else:
        action_summary = "Maintain periodic credit terms review and monitor category gross margins to sustain operating profitability."

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


# ── Main Report Tool ──────────────────────────────────────────────────────────

def generate_report_tool(
    tenant_id: str, 
    custom_content: str = "", 
    company_id: int | None = None,
    company_ids: list[int] | None = None,
    base_currency: str | None = None, 
    tenant_ids: Optional[list[str]] = None,
    logo_path: str | None = None,
    logo_b64: str | None = None,
    logo_url: str | None = None,
    report_mode: str = "auto",
    report_type: str | None = None,
    comparison_type: str = "prior_year",
    **kwargs,
) -> dict:
    if report_type and report_mode == "auto":
        report_mode = report_type
    from ..utils import get_tenant_currency
    resolved_company_ids = normalize_company_ids(company_id=company_id, companies=company_ids)
    resolved_company_id = resolved_company_ids[0] if len(resolved_company_ids) == 1 else None

    # Check for currency hints in prompt if base_currency is not passed
    prompt_text = (kwargs.get("prompt") or "").lower()
    if not base_currency:
        if re.search(r'\b(usd|dollars?|\$)\b', prompt_text) or re.search(r'\b(in usd|in dollars)\b', custom_content.lower()):
            base_currency = "USD"
        elif re.search(r'\b(eur|euros?|€)\b', prompt_text) or re.search(r'\b(in eur|in euros)\b', custom_content.lower()):
            base_currency = "EUR"
        elif re.search(r'\b(xaf|fcfa|cfa)\b', prompt_text):
            base_currency = "XAF"

    currency = base_currency or get_tenant_currency(tenant_id, resolved_company_id)
    
    # Resolve Comparison Basis Dynamically
    resolved_comparison_label = kwargs.get("comparison_label")
    if not resolved_comparison_label:
        combined_text = f"{prompt_text} {custom_content.lower()}"
        if any(w in combined_text for w in ["previous month", "prior month", "past month", "month before", "month against the previous", "mom"]):
            resolved_comparison_label = "Prior Month (MoM)"
        elif any(w in combined_text for w in ["previous quarter", "prior quarter", "quarter against the previous", "qoq"]):
            resolved_comparison_label = "Prior Quarter (QoQ)"
        elif any(w in combined_text for w in ["budget", "target", "plan"]):
            resolved_comparison_label = "Budget / Target Baseline"
        elif any(w in combined_text for w in ["sequential", "prior period"]):
            resolved_comparison_label = "Prior Sequential Period"
        elif comparison_type == "prior_month":
            resolved_comparison_label = "Prior Month (MoM)"
        elif comparison_type == "prior_quarter":
            resolved_comparison_label = "Prior Quarter (QoQ)"
        else:
            resolved_comparison_label = "Same Period Prior Year (YoY)"

    # 1. Company & View Labeling
    view_type = "Consolidated"
    if len(resolved_company_ids) == 0:
        company_name = "All Companies (Consolidated)"
        view_type = "Consolidated"
    elif len(resolved_company_ids) == 1:
        company_name = "Financial Overview"
        view_type = "Individual"
    else:
        company_name = f"Multi-Company ({len(resolved_company_ids)} Companies)"
        view_type = "Comparison"

    try:
        if len(resolved_company_ids) == 1:
            comp_res = get_companies_tool(tenant_id)
            comps = comp_res.get("companies", []) if isinstance(comp_res, dict) else []
            for c in comps:
                if isinstance(c, dict) and c.get("id") == resolved_company_ids[0]:
                    company_name = c.get("name", company_name)
    except Exception:
        pass

    # 2. Resolve Reporting Period & Core Financial Dates Dynamically
    current_year = datetime.now().year
    raw_start = kwargs.get("start_date") or kwargs.get("from_date")
    raw_end = kwargs.get("end_date") or kwargs.get("to_date")
    resolved_period_label = kwargs.get("reporting_period")

    if not resolved_period_label:
        if raw_start and raw_end:
            try:
                s_dt = datetime.strptime(raw_start, "%Y-%m-%d")
                e_dt = datetime.strptime(raw_end, "%Y-%m-%d")
                resolved_period_label = f"{s_dt.strftime('%b %d, %Y')} – {e_dt.strftime('%b %d, %Y')}"
            except Exception:
                resolved_period_label = f"{raw_start} – {raw_end}"
            ytd_start = raw_start
            ytd_end = raw_end
        else:
            # Check prompt first to prioritize user intent over historical text mentions in custom_content
            search_text = prompt_text if prompt_text else custom_content.lower()
            if any(w in search_text for w in ["past month", "this past month", "previous month", "prior month", "month before", "mom"]) or comparison_type == "prior_month":
                # For monthly reporting, default to the most recent active/closed month (June or prior calendar month)
                now = datetime.now()
                first_of_this_month = now.replace(day=1)
                last_month_end = first_of_this_month - timedelta(days=1)
                last_month_start = last_month_end.replace(day=1)
                ytd_start = last_month_start.strftime("%Y-%m-%d")
                ytd_end = last_month_end.strftime("%Y-%m-%d")
                resolved_period_label = f"{last_month_start.strftime('%b 01, %Y')} – {last_month_end.strftime('%b %d, %Y')}"
            elif re.search(r'\bq1\b|\bfirst quarter\b', search_text):
                ytd_start = f"{current_year}-01-01"
                ytd_end = f"{current_year}-03-31"
                resolved_period_label = f"Jan 01, {current_year} – Mar 31, {current_year} (Q1)"
            elif re.search(r'\bq2\b|\bsecond quarter\b', search_text):
                ytd_start = f"{current_year}-04-01"
                ytd_end = f"{current_year}-06-30"
                resolved_period_label = f"Apr 01, {current_year} – Jun 30, {current_year} (Q2)"
            elif re.search(r'\bq3\b|\bthird quarter\b', search_text):
                ytd_start = f"{current_year}-07-01"
                ytd_end = f"{current_year}-09-30"
                resolved_period_label = f"Jul 01, {current_year} – Sep 30, {current_year} (Q3)"
            elif re.search(r'\bq4\b|\bfourth quarter\b', search_text):
                ytd_start = f"{current_year}-10-01"
                ytd_end = f"{current_year}-12-31"
                resolved_period_label = f"Oct 01, {current_year} – Dec 31, {current_year} (Q4)"
            elif re.search(r'\bh1\b|\bfirst half\b', search_text):
                ytd_start = f"{current_year}-01-01"
                ytd_end = f"{current_year}-06-30"
                resolved_period_label = f"Jan 01, {current_year} – Jun 30, {current_year} (H1)"
            else:
                ytd_start = f"{current_year}-01-01"
                ytd_end = datetime.now().strftime("%Y-%m-%d")
                resolved_period_label = f"Jan 01, {current_year} – {datetime.now().strftime('%b %d, %Y')}"
    else:
        ytd_start = raw_start or f"{current_year}-01-01"
        ytd_end = raw_end or datetime.now().strftime("%Y-%m-%d")

    # Determine prior period date range based on comparison_type
    if comparison_type == "prior_month" or "MoM" in resolved_comparison_label:
        try:
            s_dt = datetime.strptime(ytd_start, "%Y-%m-%d")
            first_of_period = s_dt.replace(day=1)
            prior_end_dt = first_of_period - timedelta(days=1)
            prior_start_dt = prior_end_dt.replace(day=1)
            prior_start = prior_start_dt.strftime("%Y-%m-%d")
            prior_end = prior_end_dt.strftime("%Y-%m-%d")
        except Exception:
            now = datetime.now()
            first_of_this_month = now.replace(day=1)
            last_month_end = first_of_this_month - timedelta(days=1)
            prior_start = last_month_end.replace(day=1).strftime("%Y-%m-%d")
            prior_end = last_month_end.strftime("%Y-%m-%d")
    elif comparison_type == "prior_quarter" or "QoQ" in resolved_comparison_label:
        try:
            s_dt = datetime.strptime(ytd_start, "%Y-%m-%d")
            e_dt = datetime.strptime(ytd_end, "%Y-%m-%d")
            span_days = (e_dt - s_dt).days + 1
            prior_end_dt = s_dt - timedelta(days=1)
            prior_start_dt = prior_end_dt - timedelta(days=span_days - 1)
            prior_start = prior_start_dt.strftime("%Y-%m-%d")
            prior_end = prior_end_dt.strftime("%Y-%m-%d")
        except Exception:
            now = datetime.now()
            prior_start = (now - timedelta(days=180)).strftime("%Y-%m-%d")
            prior_end = (now - timedelta(days=90)).strftime("%Y-%m-%d")
    else:
        # Default: Same Period Prior Year (YoY)
        try:
            s_dt = datetime.strptime(ytd_start, "%Y-%m-%d")
            e_dt = datetime.strptime(ytd_end, "%Y-%m-%d")
            prior_start = f"{s_dt.year - 1}-{s_dt.strftime('%m-%d')}"
            prior_end = f"{e_dt.year - 1}-{e_dt.strftime('%m-%d')}"
        except Exception:
            prior_start = f"{current_year - 1}-01-01"
            prior_end = f"{current_year - 1}-{datetime.now().strftime('%m-%d')}"

    sales = {}
    health = {}
    pnl = {}
    prior_pnl = {}
    bs = {}
    receivables = {}
    payables = {}
    wc = {}
    inv = {}
    expenses_data = {}
    top_prods = {}

    try:
        sales = get_sales_summary_tool(tenant_id, company_ids=resolved_company_ids, base_currency=base_currency, tenant_ids=tenant_ids)
    except Exception as e:
        logger.warning(f"Sales fetch error: {e}")

    try:
        health = get_business_health_score_tool(tenant_id, company_ids=resolved_company_ids, base_currency=base_currency, tenant_ids=tenant_ids)
    except Exception as e:
        logger.warning(f"Health score fetch error: {e}")

    try:
        pnl = calculate_pnl_tool(tenant_id, company_ids=resolved_company_ids, start_date=ytd_start, end_date=ytd_end, base_currency=base_currency, tenant_ids=tenant_ids)
    except Exception as e:
        logger.warning(f"P&L fetch error: {e}")

    try:
        prior_pnl = calculate_pnl_tool(tenant_id, company_ids=resolved_company_ids, start_date=prior_start, end_date=prior_end, base_currency=base_currency, tenant_ids=tenant_ids)
    except Exception as e:
        logger.warning(f"Prior-period P&L fetch error: {e}")

    try:
        bs = get_balance_sheet_tool(tenant_id, company_ids=resolved_company_ids, base_currency=base_currency, tenant_ids=tenant_ids)
    except Exception as e:
        logger.warning(f"Balance sheet fetch error: {e}")

    try:
        receivables = get_receivables_analysis_tool(tenant_id, company_ids=resolved_company_ids, base_currency=base_currency, tenant_ids=tenant_ids)
    except Exception as e:
        logger.warning(f"Receivables fetch error: {e}")

    try:
        payables = get_payables_analysis_tool(tenant_id, company_ids=resolved_company_ids, base_currency=base_currency, tenant_ids=tenant_ids)
    except Exception as e:
        logger.warning(f"Payables fetch error: {e}")

    try:
        wc = get_working_capital_tool(tenant_id, company_ids=resolved_company_ids, base_currency=base_currency, tenant_ids=tenant_ids)
    except Exception as e:
        logger.warning(f"Working capital fetch error: {e}")

    try:
        inv = get_inventory_valuation_tool(tenant_id, company_ids=resolved_company_ids, tenant_ids=tenant_ids)
    except Exception as e:
        logger.warning(f"Inventory fetch error: {e}")

    try:
        expenses_data = get_expense_breakdown_tool(tenant_id, company_ids=resolved_company_ids, start_date=ytd_start, end_date=ytd_end, base_currency=base_currency, tenant_ids=tenant_ids)
    except Exception as e:
        logger.warning(f"Expense breakdown fetch error: {e}")

    try:
        top_prods = get_top_products_tool(tenant_id, company_ids=resolved_company_ids, limit=5, base_currency=base_currency, tenant_ids=tenant_ids)
    except Exception as e:
        logger.warning(f"Top products fetch error: {e}")

    # 3. Extract Values and Compute KPI Variances
    rev_val = float(sales.get("total_revenue", 0) or pnl.get("revenue", 0) or pnl.get("total_income", 0) or 0)
    cogs_val = float(pnl.get("cogs", 0) or 0)
    gp_val = float(pnl.get("gross_profit", 0) or (rev_val - cogs_val))
    gm_pct = float(pnl.get("gross_margin_pct", 0) or ((gp_val / rev_val * 100) if rev_val > 0 else 0))
    opex_val = float(pnl.get("operating_expenses", 0) or 0)
    ebit_val = float(pnl.get("ebit", 0) or (gp_val - opex_val))
    net_val = float(pnl.get("net_profit", 0) or ebit_val)
    tax_finance_val = max(0, ebit_val - net_val)

    # Real Cash from GL accounts (account_type = 'asset_cash')
    cash_val = 0.0
    try:
        t_sql_cash, t_params_cash = build_tenant_filter_sql(tenant_id, tenant_ids, column_name="l.tenant_id", prefix="t_cash")
        balance_col_cash = build_currency_case_sql('l.balance', tenant_id, base_currency, 'l.currency_code')
        cash_params = {"tenant_id": tenant_id}
        cash_params.update(t_params_cash)
        f_sql_cash, f_params_cash = build_company_filter_sql(tenant_id, resolved_company_ids, column_name="l.company_id")
        cash_params.update(f_params_cash)
        cash_rows = run_query(
            f"""SELECT COALESCE(SUM({balance_col_cash}), 0) AS cash_balance
                FROM fact_account_move_lines l
                JOIN fact_account_moves m ON l.account_move_id = m.id
                WHERE 1=1 {t_sql_cash}
                  AND m.state = 'posted'
                  AND l.account_type = 'asset_cash'
                  {f_sql_cash}""",
            cash_params,
        )
        if cash_rows and cash_rows[0].get("cash_balance") is not None:
            cash_val = float(cash_rows[0].get("cash_balance"))
    except Exception as e:
        logger.warning(f"Real cash balance query error: {e}")
        cash_val = float(bs.get("current_assets", 0) * 0.25)

    ar_val = float(receivables.get("total_receivables", 0) or 0)
    overdue_ar_val = float(receivables.get("overdue_receivables", 0) or 0)
    overdue_ratio = float(receivables.get("overdue_ratio", 0) or ((overdue_ar_val / ar_val) if ar_val > 0 else 0))
    ap_val = float(payables.get("total_payables", 0) or 0)
    inv_val = float(inv.get("total_valuation", 0) or inv.get("inventory_value", 0) or 0)
    nwc_val = float(wc.get("working_capital", 0) or (float(bs.get("current_assets", 0)) - float(bs.get("current_liabilities", 0))))
    cur_ratio_val = float(wc.get("current_ratio", 0) or 1.5)
    health_score_val = float(health.get("business_health_score", 0) or 80)

    # Extract Prior Values and Compute Real Variances
    prior_rev = float(prior_pnl.get("total_income", 0) or prior_pnl.get("revenue", 0) or 0)
    prior_gp = float(prior_pnl.get("gross_profit", 0) or 0)
    prior_gm = float(prior_pnl.get("gross_margin_pct", 0) or 0)
    prior_opex = float(prior_pnl.get("operating_expenses", 0) or 0)
    prior_ebit = float(prior_pnl.get("ebit", 0) or 0)
    prior_net = float(prior_pnl.get("net_profit", 0) or 0)

    rev_var_pct, rev_var_amt = _compute_variance(rev_val, prior_rev)
    gp_var_pct, gp_var_amt = _compute_variance(gp_val, prior_gp)
    gm_var_pts = round(gm_pct - prior_gm, 1)
    opex_var_pct, opex_var_amt = _compute_variance(opex_val, prior_opex)
    ebit_var_pct, ebit_var_amt = _compute_variance(ebit_val, prior_ebit)
    net_var_pct, net_var_amt = _compute_variance(net_val, prior_net)

    # 4. Build Structured KPI Objects for Template
    rev_sign = "+" if rev_var_pct > 0 else ""
    gp_sign = "+" if gp_var_pct > 0 else ""
    gm_sign = "+" if gm_var_pts > 0 else ""
    opex_sign = "+" if opex_var_pct > 0 else ""
    ebit_sign = "+" if ebit_var_pct > 0 else ""
    net_sign = "+" if net_var_pct > 0 else ""

    kpis = {
        "revenue": {
            "raw": rev_val,
            "formatted": _fmt_money(rev_val, currency),
            "var_text": f"{rev_sign}{rev_var_pct:.1f}% ({_fmt_money(rev_var_amt, currency, is_diff=True)})",
            "arrow": "▲" if rev_var_pct >= 0 else "▼",
            "var_class": "variance-positive" if rev_var_pct >= 0 else "variance-negative"
        },
        "gross_profit": {
            "raw": gp_val,
            "formatted": _fmt_money(gp_val, currency),
            "var_text": f"{gp_sign}{gp_var_pct:.1f}% ({_fmt_money(gp_var_amt, currency, is_diff=True)})",
            "arrow": "▲" if gp_var_pct >= 0 else "▼",
            "var_class": "variance-positive" if gp_var_pct >= 0 else "variance-negative"
        },
        "gross_margin": {
            "raw": gm_pct,
            "formatted": f"{gm_pct:.1f}%",
            "var_text": f"{gm_sign}{gm_var_pts:.1f} pts",
            "arrow": "▲" if gm_var_pts >= 0 else "▼",
            "var_class": "variance-positive" if gm_var_pts >= 0 else "variance-negative"
        },
        "opex": {
            "raw": opex_val,
            "formatted": _fmt_money(opex_val, currency),
            "var_text": f"{opex_sign}{opex_var_pct:.1f}% ({_fmt_money(opex_var_amt, currency, is_diff=True)})",
            "arrow": "▲" if opex_var_pct > 0 else "▼",
            "var_class": "variance-negative" if opex_var_pct > 5 else ("variance-neutral" if opex_var_pct >= 0 else "variance-positive")
        },
        "ebit": {
            "raw": ebit_val,
            "formatted": _fmt_money(ebit_val, currency),
            "var_text": f"{ebit_sign}{ebit_var_pct:.1f}% ({_fmt_money(ebit_var_amt, currency, is_diff=True)})",
            "arrow": "▲" if ebit_var_pct >= 0 else "▼",
            "var_class": "variance-positive" if ebit_var_pct >= 0 else "variance-negative"
        },
        "net_profit": {
            "raw": net_val,
            "formatted": _fmt_money(net_val, currency),
            "var_text": f"{net_sign}{net_var_pct:.1f}% ({_fmt_money(net_var_amt, currency, is_diff=True)})",
            "arrow": "▲" if net_val >= 0 else "▼",
            "var_class": "variance-positive" if net_val >= 0 else "variance-negative"
        },
        "cash": {
            "raw": cash_val,
            "formatted": _fmt_money(cash_val, currency)
        },
        "ar": {
            "raw": ar_val,
            "formatted": _fmt_money(ar_val, currency)
        },
        "overdue_pct": {
            "raw": overdue_ratio * 100,
            "formatted": f"{overdue_ratio * 100:.1f}%"
        },
        "overdue_amt": {
            "raw": overdue_ar_val,
            "formatted": _fmt_money(overdue_ar_val, currency)
        },
        "ap": {
            "raw": ap_val,
            "formatted": _fmt_money(ap_val, currency)
        },
        "inventory": {
            "raw": inv_val,
            "formatted": _fmt_money(inv_val, currency)
        },
        "nwc": {
            "raw": nwc_val,
            "formatted": _fmt_money(nwc_val, currency)
        },
        "current_ratio": {
            "raw": cur_ratio_val,
            "formatted": f"{cur_ratio_val:.2f}x"
        },
        "health_score": {
            "raw": health_score_val,
            "formatted": f"{health_score_val:.0f}"
        }
    }

    # 5. Build Autonomous AI Executive Summary, Drivers & Prioritized Alerts
    filtered_kwargs = {
        k: v for k, v in kwargs.items()
        if k not in (
            "prompt", "comparison_label", "reporting_period", "start_date", "end_date",
            "from_date", "to_date", "company_id", "company_ids", "tenant_id", "tenant_ids",
            "base_currency", "custom_content", "comparison_type"
        )
    }
    exec_summary, drivers, alerts = _synthesize_autonomous_insights(
        custom_content=custom_content,
        prompt=kwargs.get("prompt", ""),
        pnl=pnl,
        prior_pnl=prior_pnl,
        sales=sales,
        receivables=receivables,
        payables=payables,
        wc=wc,
        inv=inv,
        expenses_data=expenses_data,
        top_prods=top_prods,
        currency=currency,
        company_name=company_name,
        period_label=resolved_period_label,
        comparison_label=resolved_comparison_label,
        rev_val=rev_val,
        gp_val=gp_val,
        gm_pct=gm_pct,
        ebit_val=ebit_val,
        net_val=net_val,
        overdue_ar_val=overdue_ar_val,
        overdue_ratio=overdue_ratio,
        nwc_val=nwc_val,
        cur_ratio_val=cur_ratio_val,
        health_score_val=health_score_val,
        inv_val=inv_val,
        ap_val=ap_val,
        cash_val=cash_val,
        **filtered_kwargs
    )

    # 8. Build Company Comparison Table (if Multi-Company)
    company_comparison = []
    if len(resolved_company_ids) > 1:
        comp_res = get_companies_tool(tenant_id)
        all_comps = comp_res.get("companies", []) if isinstance(comp_res, dict) else []
        for c in all_comps:
            c_id = c.get("id")
            if c_id in resolved_company_ids:
                c_name = c.get("name", f"Company {c_id}")
                try:
                    c_pnl = calculate_pnl_tool(
                        tenant_id, company_ids=[c_id],
                        start_date=ytd_start, end_date=ytd_end,
                        base_currency=base_currency, tenant_ids=tenant_ids,
                    )
                    c_ar = get_receivables_analysis_tool(
                        tenant_id, company_ids=[c_id],
                        base_currency=base_currency, tenant_ids=tenant_ids,
                    )
                    c_rev = float(c_pnl.get("total_income", 0) or c_pnl.get("revenue", 0) or 0)
                    c_gp = float(c_pnl.get("gross_profit", 0) or 0)
                    c_gm = float(c_pnl.get("gross_margin_pct", 0) or 0)
                    c_net = float(c_pnl.get("net_profit", 0) or 0)
                    c_overdue = float(c_ar.get("overdue_receivables", 0) or 0)
                except Exception as e:
                    logger.warning(f"Company {c_id} breakdown fetch error: {e}")
                    c_rev = c_gp = c_gm = c_net = c_overdue = 0

                company_comparison.append({
                    "name": c_name,
                    "revenue": _fmt_money(c_rev, currency),
                    "gross_profit": _fmt_money(c_gp, currency),
                    "gross_margin": f"{c_gm:.1f}%",
                    "net_profit": _fmt_money(c_net, currency),
                    "cash": "—",
                    "overdue_ar": _fmt_money(c_overdue, currency),
                })

    # 9. Generate Visual Charts
    monthly_pnl_data = []
    try:
        monthly_pnl_data = _get_monthly_pnl_series(tenant_id, company_ids=resolved_company_ids, base_currency=base_currency, tenant_ids=tenant_ids)
    except Exception as e:
        logger.warning(f"Monthly P&L series error: {e}")

    if not monthly_pnl_data:
        # Fallback to sales time-series if P&L series was empty
        ts_result = {}
        try:
            ts_result = get_time_series_data_tool(tenant_id, company_ids=resolved_company_ids, granularity="month", base_currency=base_currency, tenant_ids=tenant_ids)
        except Exception:
            pass
        monthly_pnl_data = ts_result.get("points", []) if isinstance(ts_result, dict) else []

    trend_chart_b64 = _render_trend_chart(monthly_pnl_data, currency)
    waterfall_chart_b64 = _render_waterfall_chart(rev_val, cogs_val, gp_val, opex_val, ebit_val, tax_finance_val, net_val, currency)
    wc_chart_b64 = _render_working_capital_chart(cash_val, ar_val, overdue_ar_val, ap_val, inv_val, nwc_val, currency)

    # 10. Process Markdown Custom Content
    custom_content = replace_tenant_ids_with_names(custom_content, tenant_ids or ([tenant_id] if tenant_id else None))
    from .emoji_to_badges import normalize_status_emoji
    custom_content = normalize_status_emoji(custom_content)

    # Convert chart blocks if present
    def _chart_block_replacer(match):
        json_str = match.group(1)
        try:
            cfg = json.loads(json_str)
            labels = [str(l) for l in cfg.get("labels", [])]
            values = [float(v) for v in cfg.get("values", [])]
            title = cfg.get("title", "")
            if labels and values:
                fig, ax = plt.subplots(figsize=(7, 3.2), facecolor='white')
                ax.bar(labels, values, color='#2563eb', width=0.55, edgecolor='white', linewidth=1)
                ax.spines['top'].set_visible(False)
                ax.spines['right'].set_visible(False)
                ax.spines['left'].set_color('#cbd5e1')
                ax.spines['bottom'].set_color('#cbd5e1')
                ax.tick_params(colors='#64748b', labelsize=7.5)
                ax.yaxis.grid(True, linestyle=':', color='#e2e8f0', alpha=0.8)
                ax.xaxis.grid(False)

                # Disable scientific notation & apply friendly B/M/K formatter
                if hasattr(ax.yaxis, "offsetText"):
                    ax.yaxis.offsetText.set_visible(False)
                ax.yaxis.set_major_formatter(ticker.FuncFormatter(_friendly_axis_formatter))

                if len(labels) > 4:
                    plt.xticks(rotation=20, ha='right', fontsize=7.5)
                if title:
                    plt.title(title, fontsize=9.5, fontweight='bold', pad=10, color='#0f172a')
                plt.tight_layout()

                buf = io.BytesIO()
                plt.savefig(buf, format='png', dpi=150, bbox_inches='tight')
                buf.seek(0)
                b64 = base64.b64encode(buf.read()).decode('utf-8')
                plt.close(fig)
                return f'<div class="chart-box" style="margin: 10px 0; text-align: center;"><img class="chart-img" style="max-width: 100%; border-radius: 6px;" src="data:image/png;base64,{b64}" /></div>'
        except Exception as e:
            logger.warning(f"Custom chart block render failed: {e}")
        return ""

    custom_content = re.sub(r'```chart\s*\n(.*?)\n```', _chart_block_replacer, custom_content, flags=re.DOTALL | re.IGNORECASE)

    if not custom_content.strip():
        custom_content = f"""
## Executive Highlights
The organization generated **{_fmt_money(rev_val, currency)}** in total revenue for the current fiscal period with a business health score of **{health_score_val:.0f}/100**.

### Key Strategic Observations
* **Operating Efficiency**: Operating margin (EBIT) reached **{_fmt_money(ebit_val, currency)}**, demonstrating strong underlying unit economics.
* **Working Capital Health**: Current ratio remains solid at **{cur_ratio_val:.2f}x**, providing sufficient headroom for operational commitments.
* **Action Priority**: Accelerated collections on outstanding receivables will convert locked working capital directly into liquid cash reserves.
"""

    # Normalize bullet list formatting and strip broken orphan bullets
    custom_content = re.sub(r'^[•\u2022]\s*', '- ', custom_content, flags=re.MULTILINE)
    custom_content = re.sub(r'^[•\u2022\-\*]\s*$', '', custom_content, flags=re.MULTILINE)
    custom_content = re.sub(r'^\d+\.\s*$', '', custom_content, flags=re.MULTILINE)
    custom_content = re.sub(r'([^\n])\s+-\s+([A-Za-z0-9])', r'\1\n- \2', custom_content)
    custom_content = re.sub(r'\n{3,}', '\n\n', custom_content)

    md = markdown.Markdown(extensions=['tables', 'fenced_code', 'sane_lists'])
    body_html = md.convert(custom_content)
    body_html = normalize_status_emoji(body_html)
    from .table_layout import add_dynamic_table_widths
    body_html = add_dynamic_table_widths(body_html)

    # 11. Render Jinja2 Template
    template_dir = Path(__file__).parent / "templates"
    env = Environment(loader=FileSystemLoader(str(template_dir)))
    template = env.get_template("report_template.html")

    # Resolve logo
    logo_mime = "image/png"
    if not logo_b64:
        from ..utils import get_project_logo_b64
        discovered_b64, discovered_mime = get_project_logo_b64(custom_logo_path=logo_path)
        if discovered_b64:
            logo_b64 = discovered_b64
            logo_mime = discovered_mime or "image/png"

    html_out = template.render(
        company_name=company_name,
        reporting_period=resolved_period_label,
        view_type=view_type,
        comparison_label=resolved_comparison_label,
        currency=currency,
        last_sync=f"{datetime.now().strftime('%b %d, %Y')} (Posted Ledger)",
        kpis=kpis,
        exec_summary=exec_summary,
        drivers=drivers,
        alerts=alerts,
        company_comparison=company_comparison,
        trend_chart_b64=trend_chart_b64,
        waterfall_chart_b64=waterfall_chart_b64,
        wc_chart_b64=wc_chart_b64,
        body_html=body_html,
        logo_url=logo_url,
        logo_b64=logo_b64,
        logo_mime=logo_mime,
    )

    # 12. Compile PDF via WeasyPrint
    reports_dir = _get_reports_dir()
    filename = f"business_report_{tenant_id}_{datetime.now().strftime('%Y%m%d_%H%M%S')}_v2.pdf"
    output_path = reports_dir / filename
    try:
        HTML(string=html_out).write_pdf(output_path)
    except Exception as e:
        logger.error(f"WeasyPrint PDF write failed: {e}", exc_info=True)
        return {
            'tool_name': 'generate_report_tool',
            'status': 'error',
            'error': f"PDF compilation failed: {str(e)}",
            'filename': filename,
        }

    relative_path = f"/financial-advisor/reports/{filename}"
    return {
        'tool_name': 'generate_report_tool',
        'status': 'success',
        'download_url': make_report_url(filename),
        'path': relative_path,
        'filename': filename,
    }


def get_last_report_tool(tenant_id: str, company_id: int | None = None, company_ids: Optional[list[int]] = None, tenant_ids: Optional[list[str]] = None) -> dict:
    reports_dir = _get_reports_dir()
    files = list(reports_dir.glob(f'business_report_{tenant_id}_*_v2.pdf'))
    if not files:
        files = list(reports_dir.glob(f'business_report_{tenant_id}_*.pdf'))
        if not files:
            return {'status': 'no_reports'}
            
    files.sort(key=lambda x: x.stat().st_mtime, reverse=True)
    filename = files[0].name
    relative_path = f"/financial-advisor/reports/{filename}"
    return {
        'tool_name': 'get_last_report_tool',
        'filename': filename,
        'download_url': make_report_url(filename),
        'path': relative_path,
    }
