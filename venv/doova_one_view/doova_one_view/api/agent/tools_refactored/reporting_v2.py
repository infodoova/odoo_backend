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
from .finance_v2 import (
    get_cash_flow_statement_tool,
)
from .inventory import get_inventory_valuation_tool, get_inventory_alerts_tool, get_inventory_efficiency_tool
from .purchasing import get_purchase_summary_tool, get_top_vendors_tool
from .common import get_companies_tool, build_currency_case_sql
from .template_registry import TEMPLATE_REGISTRY, get_template_metadata


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
    start_date: str | None = None,
    end_date: str | None = None,
    base_currency: str | None = None,
    tenant_ids: Optional[list[str]] = None,
) -> list[dict]:
    """Query real monthly income, expenses, and net profit from the GL scoped to date range."""
    t_sql_ts, t_params_ts = build_tenant_filter_sql(tenant_id, tenant_ids, column_name="l.tenant_id", prefix="t_ts")
    balance_col_ts = build_currency_case_sql('l.balance', tenant_id, base_currency, 'l.currency_code')
    f_sql_ts, f_params_ts = build_company_filter_sql(tenant_id, company_ids, column_name="l.company_id")
    params = {"tenant_id": tenant_id}
    params.update(t_params_ts)
    params.update(f_params_ts)

    date_filter = ""
    if start_date:
        date_filter += " AND m.date >= :start_date"
        params["start_date"] = start_date
    if end_date:
        date_filter += " AND m.date <= :end_date"
        params["end_date"] = end_date

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
              {date_filter}
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
            min(0, gp),                 # Gross Profit pillar
            min(gp, ebit),              # OpEx floats between ebit and gp
            min(0, ebit),               # Operating EBIT pillar (hangs below 0 if negative)
            min(ebit, net_profit),      # Tax/Other floats between net_profit and ebit
            min(0, net_profit),         # Net Profit pillar (hangs below 0 if negative)
        ]

        heights = [
            rev,                        # Revenue
            cogs,                       # COGS
            abs(gp),                    # Gross Profit magnitude
            opex,                       # OpEx
            abs(ebit),                  # Operating EBIT magnitude
            tax_other,                  # Tax / Other
            abs(net_profit),            # Net Profit magnitude
        ]

        colors = [
            '#2563eb',  # Gross Revenue (Deep Blue)
            '#f97316',  # COGS (Amber/Orange expense)
            '#3b82f6' if gp >= 0 else '#ef4444',  # Gross Profit (Blue Subtotal or Loss Red)
            '#ea580c',  # OpEx (Red-Orange expense)
            '#0ea5e9' if ebit >= 0 else '#ef4444',  # Operating EBIT (Cyan Subtotal or Loss Red)
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
            f"={_friendly_axis_formatter(net_profit)}",
        ]

        denom = max(abs(rev), abs(gp), abs(ebit), abs(net_profit), 1.0)
        for i, (bar, label, bottom, height) in enumerate(zip(bars, labels, bottoms, heights)):
            # Determine if the bar represents a negative pillar below 0
            if i in [2, 4, 6] and [gp, ebit, net_profit][i//2 - 1] < 0:
                y_pos = bottom - (denom * 0.04)
                va = 'top'
            elif i in [1, 3, 5] and (bottom < 0 and bottom + height <= 0):
                y_pos = bottom - (denom * 0.04)
                va = 'top'
            else:
                y_pos = bottom + height + (denom * 0.04)
                va = 'bottom'
            ax.text(bar.get_x() + bar.get_width()/2, y_pos, label, ha='center', va=va, fontsize=7.2, fontweight='bold', color='#1e293b')

        ax.spines['top'].set_visible(False)
        ax.spines['right'].set_visible(False)
        ax.spines['left'].set_color('#cbd5e1')
        ax.spines['bottom'].set_color('#cbd5e1')
        ax.tick_params(colors='#64748b', labelsize=7.5)
        ax.yaxis.grid(True, linestyle=':', color='#f1f5f9', alpha=0.9, zorder=1)
        ax.xaxis.grid(False)

        # Y-axis limits with headroom for labels
        y_min = min(net_profit, ebit, gp, min(bottoms), 0) - (denom * 0.20)
        y_max = max(rev, gp, max([b + h for b, h in zip(bottoms, heights)]), 0) + (denom * 0.20)
        ax.set_ylim(y_min, y_max)

        if hasattr(ax.yaxis, "offsetText"):
            ax.yaxis.offsetText.set_visible(False)
        ax.yaxis.set_major_formatter(ticker.FuncFormatter(_friendly_axis_formatter))

        plt.xticks(rotation=10, ha='right', fontsize=7.5, color='#334155')
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


# ── Direct LLM Executive Summary Synthesis Engine ─────────────────────────────

def _generate_ai_executive_summary_llm(
    telemetry: dict,
    prompt: str = "",
    custom_content: str = "",
) -> tuple[dict, dict, list] | None:
    """
    Direct AI generation for the Executive Summary Table, Performance Drivers, and Alerts.
    Feeds live financial telemetry to Claude to generate natural, CFO-grade insights.
    Returns (exec_summary, drivers, alerts) or None if LLM is unavailable.
    """
    import json
    from ..config import AgentConfig
    if not AgentConfig.ANTHROPIC_API_KEY:
        return None

    try:
        from langchain_anthropic import ChatAnthropic
        from langchain_core.messages import SystemMessage, HumanMessage

        llm = ChatAnthropic(
            model=AgentConfig.FAST_MODEL,
            anthropic_api_key=AgentConfig.ANTHROPIC_API_KEY,
            max_tokens=4096,
        )

        system_instruction = (
            "You are a senior Chief Financial Officer (CFO) synthesizing an Executive Business Report for leadership. "
            "Analyze the provided live ERP financial telemetry and output a strict JSON object with EXACTLY 3 keys:\n\n"
            "1. 'exec_summary': An object containing all 6 required string fields:\n"
            "   - 'overall': 1-2 concise executive sentences describing top-line revenue, period growth vs prior, and overall business health.\n"
            "   - 'profitability': 1-2 sentences analyzing gross profit margin %, EBIT operating profit, and net profit retention.\n"
            "   - 'positive_driver': 1 sentence highlighting the #1 revenue-generating product/SKU or strongest commercial force.\n"
            "   - 'negative_driver': 1 sentence pinpointing the main financial drag, overdue customer receivables, cost creep, or bottleneck.\n"
            "   - 'liquidity': 1 sentence evaluating Net Working Capital, Current Ratio, cash buffer, and ability to comfortably pay supplier bills.\n"
            "   - 'action': 1-2 prioritized, realistic leadership decisions.\n\n"
            "2. 'drivers': An object with 'positive' (2-3 items) and 'negative' (2-3 items) lists (each item has 'name', 'current', 'impact', 'explanation').\n"
            "3. 'alerts': A list of 2-3 prioritized management risks (each item has 'priority', 'priority_class', 'title', 'impact', 'action', 'owner', 'status').\n\n"
            "RULES:\n"
            "- Ground all metrics, percentages, and currencies strictly in the provided telemetry numbers.\n"
            "- Write in clear, professional executive language without technical software/code jargon.\n"
            "- Output ONLY the JSON block inside ```json ... ``` tags."
        )

        user_content = f"Financial Telemetry:\n```json\n{json.dumps(telemetry, indent=2)}\n```\n"
        if prompt:
            user_content += f"\nSpecific User Focus / Prompt: {prompt}\n"
        if custom_content and len(custom_content.strip()) > 10:
            user_content += f"\nAdditional Context / Custom Analysis:\n{custom_content[:1200]}\n"

        response = llm.invoke([
            SystemMessage(content=system_instruction),
            HumanMessage(content=user_content),
        ])
        if hasattr(response, "content"):
            if isinstance(response.content, list):
                raw_text = "".join([
                    c.get("text", "") if isinstance(c, dict) and c.get("type") == "text" else (getattr(c, "text", "") if getattr(c, "type", "") == "text" else (c if isinstance(c, str) else ""))
                    for c in response.content
                ])
            else:
                raw_text = str(response.content)
        else:
            raw_text = str(response)

        match = re.search(r'```(?:json)?\s*(\{[\s\S]*?\})\s*```', raw_text)
        if not match:
            match = re.search(r'(\{[\s\S]*?"exec_summary"[\s\S]*?\})', raw_text)

        if match:
            parsed = json.loads(match.group(1))
            if isinstance(parsed, dict) and "exec_summary" in parsed:
                exec_summary = parsed.get("exec_summary", {})
                drivers = parsed.get("drivers", {"positive": [], "negative": []})
                alerts = parsed.get("alerts", [])
                required_fields = ["overall", "profitability", "positive_driver", "negative_driver", "liquidity", "action"]
                if all(field in exec_summary and bool(str(exec_summary[field]).strip()) for field in required_fields):
                    logger.info("Successfully synthesized executive summary directly via AI LLM reasoning.")
                    return exec_summary, drivers, alerts
    except Exception as e:
        logger.warning(f"_generate_ai_executive_summary_llm error (falling back to deterministic synthesis): {e}")

    return None


def _generate_ai_domain_analysis(
    domain: str,
    report_data: dict,
    prompt: str = "",
    company_name: str = "the organization",
    period_label: str = "",
    comparison_label: str = "",
    currency: str = "XAF",
    meta: dict | None = None,
) -> str:
    """
    Invokes the AI CFO/Commercial Agent to synthesize a comprehensive, CFO-grade
    markdown analysis for specialized domain reports based on live ERP database metrics.
    """
    from ..config import AgentConfig
    if not AgentConfig.ANTHROPIC_API_KEY:
        return ""

    try:
        from langchain_anthropic import ChatAnthropic
        from langchain_core.messages import SystemMessage, HumanMessage

        llm = ChatAnthropic(
            model=AgentConfig.FAST_MODEL,
            anthropic_api_key=AgentConfig.ANTHROPIC_API_KEY,
            max_tokens=4096,
            temperature=0.1,
        )

        title = (meta or {}).get("title", f"{domain.capitalize()} Executive Report")
        subtitle = (meta or {}).get("subtitle", "Comprehensive business performance analysis.")

        system_instruction = (
            f"You are a top-tier Chief Financial Officer (CFO) and Strategic Executive Advisor preparing an official management report for {company_name}.\n"
            f"Report Type: {title}\n"
            f"Reporting Period: {period_label} (vs {comparison_label})\n\n"
            "Your objective is to write a deeply intelligent, highly structured, data-grounded strategic briefing in Markdown.\n\n"
            "MANDATORY STRUCTURE:\n"
            f"## {title}\n"
            f"*{subtitle}*\n\n"
            "### 1. Executive Summary & Key Takeaways\n"
            "- A crisp, professional summary of performance, top-line scale, bottom-line results, and overall health.\n\n"
            "### 2. Operational & Financial Deep Dive\n"
            "- Granular breakdown of the relevant domain drivers (margins, cost structure, aging buckets, product velocities, liquidity).\n"
            "- Reference exact metrics and numbers from the provided telemetry.\n\n"
            "### 3. Risk Assessment & Financial Governance\n"
            "- Critical vulnerabilities, cost creep, aging exposure, or operational bottlenecks that leadership must address.\n\n"
            "### 4. Strategic Recommendations & Action Plan\n"
            "- 2–3 actionable, pragmatic next steps with clear ownership and expected financial impact.\n\n"
            "RULES:\n"
            "- Base every number, metric, and percentage directly on the provided data.\n"
            "- Bold all key financial numbers and dates.\n"
            "- If the user provided a specific prompt/question, directly answer every aspect of their request in the narrative.\n"
            "- Write in clean, publication-ready executive language."
        )

        user_content = f"Live ERP Database Telemetry for {domain.upper()}:\n```json\n{json.dumps(report_data, indent=2, default=str)}\n```\n"
        if prompt:
            user_content += f"\nUser Prompt / Executive Inquiries:\n\"{prompt}\"\n"

        response = llm.invoke([
            SystemMessage(content=system_instruction),
            HumanMessage(content=user_content),
        ])

        if hasattr(response, "content"):
            if isinstance(response.content, list):
                raw_text = "".join([
                    c.get("text", "") if isinstance(c, dict) and c.get("type") == "text" else (getattr(c, "text", "") if getattr(c, "type", "") == "text" else (c if isinstance(c, str) else ""))
                    for c in response.content
                ])
            else:
                raw_text = str(response.content)
        else:
            raw_text = str(response)

        raw_text = raw_text.strip()
        if raw_text.startswith("```markdown"):
            raw_text = raw_text[11:]
        elif raw_text.startswith("```"):
            raw_text = raw_text[3:]
        if raw_text.endswith("```"):
            raw_text = raw_text[:-3]

        return raw_text.strip()

    except Exception as e:
        logger.warning(f"_generate_ai_domain_analysis error: {e}")
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

    Primary: Direct LLM generation from live ERP financial telemetry.
    Fallback: Resilient deterministic financial heuristics.
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


# ── Markdown Table Sanitizer ──────────────────────────────────────────────────

def _normalize_markdown_tables(text: str) -> str:
    """
    Sanitizes markdown tables emitted by LLMs:
    1. Detaches inline prefixes on the same line (e.g. 'AR Aging: | Col 1 | Col 2 |' -> 'AR Aging:\n\n| Col 1 | Col 2 |').
    2. Replaces collapsed row delimiters ('| |' or '||') with proper row newlines ('|\n|').
    3. Guarantees clean blank lines before and after table blocks so Markdown converts them to HTML <table>.
    """
    if not text:
        return ""
    # 1. Detach prefixed labels (with optional bullet markers): '- Label: | Header 1 |' -> '- Label:\n\n| Header 1 |'
    text = re.sub(r'(^|\n)([\s\*\-•]*[^\n\|]+?:\s*)(\|)', r'\1\2\n\n\3', text)

    # 2. Fix collapsed rows: '||' or '| |' or '|   |' -> replace with '|\n|'
    text = re.sub(r'\|\s*\|\s*', '|\n|', text)

    # 3. Ensure a blank line before any table block starting with | if preceded by non-table text
    text = re.sub(r'([^\n\|])\n(\|)', r'\1\n\n\2', text)

    # 4. Ensure a blank line after any table block ending with | if followed by non-table text
    text = re.sub(r'(\|\n)([^\n\|])', r'\1\n\2', text)
    return text


# ── Template Router & Agent-Driven Presentation Helpers ───────────────────────

def _resolve_report_template(report_type: str | None = None, prompt_text: str = "") -> tuple[str, str, dict]:
    """
    Selects the Jinja2 template file and returns (template_filename, canonical_key, metadata).
    Delegates to ReportTypeClassifier (beside RouterNode) with 100% backward compatibility.
    """
    if not report_type and not prompt_text:
        return "report_template.html", "health", TEMPLATE_REGISTRY.get("health", {})

    from ..report_classifier import ReportTypeClassifier
    canonical_key = ReportTypeClassifier.classify(prompt=prompt_text, raw_type=report_type)

    if canonical_key in TEMPLATE_REGISTRY:
        meta = TEMPLATE_REGISTRY[canonical_key]
        return meta["template_file"], canonical_key, meta

    return "report_template.html", "health", TEMPLATE_REGISTRY.get("health", {})


def _normalize_report_data(report_data: dict, currency: str) -> dict:
    """
    Auto-formats raw numeric KPI values if passed as plain numbers or {raw: ...}.
    Handles currencies, percentages, counts, and ratios intelligently.
    """
    if not isinstance(report_data, dict):
        return {}

    normalized = dict(report_data)
    for key, val in report_data.items():
        k_lower = key.lower()
        if isinstance(val, (int, float)):
            f_val = float(val)
            if any(p in k_lower for p in ["margin", "pct", "rate", "percent", "achievement", "share"]):
                fmt_str = f"{f_val:.1f}%"
            elif any(r in k_lower for r in ["ratio", "turnover", "multiplier"]):
                fmt_str = f"{f_val:.2f}x"
            elif any(c in k_lower for c in ["count", "volume", "orders", "pos", "skus", "items"]):
                fmt_str = f"{int(f_val):,}"
            else:
                fmt_str = _fmt_money(f_val, currency)
            normalized[key] = {
                "raw": f_val,
                "formatted": fmt_str,
            }
        elif isinstance(val, dict) and "raw" in val and "formatted" not in val:
            v_raw = val["raw"]
            if isinstance(v_raw, (int, float)):
                f_val = float(v_raw)
                val_copy = dict(val)
                if any(p in k_lower for p in ["margin", "pct", "rate", "percent", "achievement", "share"]):
                    fmt_str = f"{f_val:.1f}%"
                elif any(r in k_lower for r in ["ratio", "turnover", "multiplier"]):
                    fmt_str = f"{f_val:.2f}x"
                elif any(c in k_lower for c in ["count", "volume", "orders", "pos", "skus", "items"]):
                    fmt_str = f"{int(f_val):,}"
                else:
                    fmt_str = _fmt_money(f_val, currency)
                val_copy["formatted"] = fmt_str
                normalized[key] = val_copy

    return normalized


def _render_charts_from_report_data(report_data: dict, currency: str) -> dict:
    """
    Generates chart base64 strings from agent-provided data arrays if present.
    """
    charts = {}
    if not isinstance(report_data, dict):
        return charts

    # 1. Trend Data
    trend_data = report_data.get("trend_data")
    if trend_data and isinstance(trend_data, list):
        try:
            charts["chart_1_b64"] = _render_trend_chart(trend_data, currency)
        except Exception as e:
            logger.warning(f"_render_charts_from_report_data trend error: {e}")

    # 2. Waterfall Data
    wf_data = report_data.get("waterfall_data")
    if wf_data and isinstance(wf_data, dict):
        try:
            rev_val = float(wf_data.get("revenue", 0) or 0)
            cogs_val = float(wf_data.get("cogs", 0) or 0)
            gp_val = float(wf_data.get("gross_profit", rev_val - cogs_val) or 0)
            opex_val = float(wf_data.get("opex", wf_data.get("operating_expenses", 0)) or 0)
            ebit_val = float(wf_data.get("ebit", gp_val - opex_val) or 0)
            tax_val = float(wf_data.get("tax", 0) or 0)
            net_val = float(wf_data.get("net_profit", ebit_val - tax_val) or 0)
            charts["chart_2_b64"] = _render_waterfall_chart(rev_val, cogs_val, gp_val, opex_val, ebit_val, tax_val, net_val, currency)
        except Exception as e:
            logger.warning(f"_render_charts_from_report_data waterfall error: {e}")

    # 3. Direct pre-rendered chart passthroughs
    if report_data.get("chart_1_b64"):
        charts["chart_1_b64"] = report_data["chart_1_b64"]
    if report_data.get("chart_2_b64"):
        charts["chart_2_b64"] = report_data["chart_2_b64"]

    return charts


def _fetch_domain_report_data(
    resolved_domain: str,
    tenant_id: str,
    resolved_company_ids: list[int] | None,
    start_date: str,
    end_date: str,
    base_currency: str | None,
    tenant_ids: list[str] | None,
    currency: str,
) -> dict:
    """
    Direct, authoritative database query pipeline for specialized domain reports.
    Executes domain-specific SQL queries to populate complete KPI datasets,
    aging schedules, category distributions, and ledger records.
    """
    data = {}
    try:
        pnl = calculate_pnl_tool(tenant_id, company_ids=resolved_company_ids, start_date=start_date, end_date=end_date, base_currency=base_currency, tenant_ids=tenant_ids)
    except Exception as e:
        logger.warning(f"Domain P&L fetch error: {e}")
        pnl = {}

    rev_f = float(pnl.get("total_income", 0) or 0)
    gp_f = float(pnl.get("gross_profit", 0) or 0)
    ebit_f = float(pnl.get("ebit", 0) or 0)
    net_f = float(pnl.get("net_profit", 0) or 0)
    opex_f = float(pnl.get("operating_expenses", 0) or 0)
    cogs_f = float(pnl.get("cogs", 0) or 0)

    data.update({
        "revenue": rev_f,
        "total_revenue": rev_f,
        "cogs": cogs_f,
        "gross_profit": gp_f,
        "gross_margin": float(pnl.get("gross_margin", 0) or (gp_f / rev_f * 100 if rev_f > 0 else 0)),
        "opex": opex_f,
        "total_expenses": opex_f,
        "ebit": ebit_f,
        "net_profit": net_f,
        "net_margin": float(pnl.get("net_margin", 0) or (net_f / rev_f * 100 if rev_f > 0 else 0)),
    })

    # Domain: Accounting & GL
    if resolved_domain in ("accounting", "general", "consolidated"):
        try:
            receivables = get_receivables_analysis_tool(tenant_id, company_ids=resolved_company_ids, base_currency=base_currency, tenant_ids=tenant_ids)
            payables = get_payables_analysis_tool(tenant_id, company_ids=resolved_company_ids, base_currency=base_currency, tenant_ids=tenant_ids)
            expenses_data = get_expense_breakdown_tool(tenant_id, company_ids=resolved_company_ids, start_date=start_date, end_date=end_date, base_currency=base_currency, tenant_ids=tenant_ids)
            wc = get_working_capital_tool(tenant_id, company_ids=resolved_company_ids, base_currency=base_currency, tenant_ids=tenant_ids)

            ar_total = float(receivables.get("total_receivables", 0) or 0)
            ar_buckets = receivables.get("aging_buckets", {})
            ap_total = float(payables.get("total_payables", 0) or 0)
            ap_buckets = payables.get("aging_buckets", {})

            data.update({
                "accounts_receivable": ar_total,
                "ar": ar_total,
                "accounts_payable": ap_total,
                "ap": ap_total,
                "cash": float(wc.get("cash_and_bank", 0) or 0),
                "working_capital": float(wc.get("working_capital", 0) or 0),
                "current_ratio": float(wc.get("current_ratio", 0) or 0),
                "total_assets": float(wc.get("total_current_assets", 0) or 0),
                "expense_breakdown": expenses_data.get("expenses", []),
                "ar_aging": {
                    "current": _fmt_money(float(ar_buckets.get("0-30", 0) or 0), currency),
                    "current_share": f"{(float(ar_buckets.get('0-30', 0) or 0) / ar_total * 100):.1f}%" if ar_total > 0 else "0.0%",
                    "days_30": _fmt_money(float(ar_buckets.get("31-60", 0) or 0), currency),
                    "days_30_share": f"{(float(ar_buckets.get('31-60', 0) or 0) / ar_total * 100):.1f}%" if ar_total > 0 else "0.0%",
                    "days_60": _fmt_money(float(ar_buckets.get("61-90", 0) or 0), currency),
                    "days_60_share": f"{(float(ar_buckets.get('61-90', 0) or 0) / ar_total * 100):.1f}%" if ar_total > 0 else "0.0%",
                    "days_90_plus": _fmt_money(float(ar_buckets.get("90+", 0) or 0), currency),
                    "days_90_plus_share": f"{(float(ar_buckets.get('90+', 0) or 0) / ar_total * 100):.1f}%" if ar_total > 0 else "0.0%",
                },
                "ap_aging": ap_buckets,
            })
        except Exception as e:
            logger.warning(f"Accounting domain query error: {e}")

    # Domain: Sales & Commercial
    if resolved_domain in ("sales", "general"):
        try:
            sales = get_sales_summary_tool(tenant_id, company_ids=resolved_company_ids, start_date=start_date, end_date=end_date, base_currency=base_currency, tenant_ids=tenant_ids)
            top_prods = get_top_products_tool(tenant_id, company_ids=resolved_company_ids, start_date=start_date, end_date=end_date, limit=10, base_currency=base_currency, tenant_ids=tenant_ids)
            sales_rev = float(sales.get("total_revenue", 0) or 0)
            if sales_rev > 0:
                data["revenue"] = sales_rev
                data["total_revenue"] = sales_rev

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
                "sales_volume": float(sales.get("order_count", 0) or 0),
                "order_count": float(sales.get("order_count", 0) or 0),
                "avg_order_value": float(sales.get("average_order_value", 0) or 0),
                "top_products": formatted_prods,
                "top_customer_revenue": top_cust_rev,
                "target_achievement": 100.0,
            })
        except Exception as e:
            logger.warning(f"Sales domain query error: {e}")

    # Domain: Purchasing & Procurement
    if resolved_domain in ("purchase", "purchasing"):
        try:
            purch = get_purchase_summary_tool(tenant_id, company_ids=resolved_company_ids, start_date=start_date, end_date=end_date, base_currency=base_currency, tenant_ids=tenant_ids)
            top_v = get_top_vendors_tool(tenant_id, company_ids=resolved_company_ids, start_date=start_date, end_date=end_date, limit=10, base_currency=base_currency, tenant_ids=tenant_ids)
            payables = get_payables_analysis_tool(tenant_id, company_ids=resolved_company_ids, base_currency=base_currency, tenant_ids=tenant_ids)

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

            data.update({
                "total_purchases": total_purch,
                "total_purchase_spend": total_purch,
                "purchase_spend": total_purch,
                "po_count": po_cnt,
                "avg_po_value": avg_po,
                "top_supplier_spend": top_v_spend,
                "top_vendors": formatted_vendors,
                "top_suppliers": formatted_vendors,
                "ap_aging": payables.get("aging_buckets", {}),
            })
        except Exception as e:
            logger.warning(f"Purchase domain query error: {e}")

    # Domain: Inventory
    if resolved_domain in ("inventory", "stock"):
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

            data.update({
                "inventory_valuation": float(inv_val.get("total_valuation", 0) or 0),
                "inventory_value": float(inv_val.get("total_valuation", 0) or 0),
                "sku_count": int(inv_val.get("sku_count", len(raw_alerts)) or len(raw_alerts)),
                "low_stock_count": len(raw_alerts),
                "low_stock_items": formatted_alerts,
                "low_stock_alerts": formatted_alerts,
                "stock_turnover": float(inv_eff.get("inventory_turnover", 0) or 0),
                "days_on_hand": float(inv_eff.get("days_sales_of_inventory", 0) or 0),
            })
        except Exception as e:
            logger.warning(f"Inventory domain query error: {e}")

    # Domain: Cash Flow & Liquidity
    if resolved_domain in ("cashflow", "liquidity"):
        try:
            cf = get_cash_flow_statement_tool(tenant_id, company_ids=resolved_company_ids, start_date=start_date, end_date=end_date, base_currency=base_currency, tenant_ids=tenant_ids)
            wc = get_working_capital_tool(tenant_id, company_ids=resolved_company_ids, base_currency=base_currency, tenant_ids=tenant_ids)
            cash_val = float(wc.get("cash_and_bank", 0) or 0)
            data.update({
                "cash_balance": cash_val,
                "cash": cash_val,
                "cash_and_bank": cash_val,
                "cash_from_operations": float(cf.get("operating_cash_flow", 0) or 0),
                "operating_cashflow": float(cf.get("operating_cash_flow", 0) or 0),
                "net_cash_flow": float(cf.get("net_cash_flow", 0) or 0),
                "net_cash_movement": float(cf.get("net_cash_flow", 0) or 0),
                "bank_balances": [
                    {
                        "account_name": "General Operating & Bank Accounts",
                        "name": "General Operating & Bank Accounts",
                        "currency": currency,
                        "balance": _fmt_money(cash_val, currency),
                    }
                ],
            })
        except Exception as e:
            logger.warning(f"Cashflow domain query error: {e}")

    # Domain: Balance Sheet & Solvency
    if resolved_domain in ("balance_sheet", "solvency"):
        try:
            bs = get_balance_sheet_tool(tenant_id, company_ids=resolved_company_ids, as_of_date=end_date, base_currency=base_currency, tenant_ids=tenant_ids)
            data.update({
                "total_assets": float(bs.get("total_assets", 0) or 0),
                "total_liabilities": float(bs.get("total_liabilities", 0) or 0),
                "total_equity": float(bs.get("total_equity", 0) or 0),
            })
        except Exception as e:
            logger.warning(f"Balance sheet domain query error: {e}")

    return data


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
    report_data: dict | None = None,
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
            elif re.search(r'\blast\s+quarter\b|\bpast\s+quarter\b|\bprevious\s+quarter\b|\bprior\s+quarter\b|\bqoq\b', search_text):
                # Calculate previous closed quarter based on current month
                now = datetime.now()
                curr_q = (now.month - 1) // 3 + 1
                prev_q = 4 if curr_q == 1 else curr_q - 1
                q_year = current_year - 1 if curr_q == 1 else current_year
                q_starts = {1: f"{q_year}-01-01", 2: f"{q_year}-04-01", 3: f"{q_year}-07-01", 4: f"{q_year}-10-01"}
                q_ends = {1: f"{q_year}-03-31", 2: f"{q_year}-06-30", 3: f"{q_year}-09-30", 4: f"{q_year}-12-31"}
                q_labels = {1: f"Jan 01, {q_year} – Mar 31, {q_year} (Q1)", 2: f"Apr 01, {q_year} – Jun 30, {q_year} (Q2)", 3: f"Jul 01, {q_year} – Sep 30, {q_year} (Q3)", 4: f"Oct 01, {q_year} – Dec 31, {q_year} (Q4)"}
                ytd_start = q_starts[prev_q]
                ytd_end = q_ends[prev_q]
                resolved_period_label = q_labels[prev_q]
            elif re.search(r'\bpast\s+6\s+months\b|\blast\s+6\s+months\b|\bh1\b|\bfirst half\b', search_text):
                ytd_start = f"{current_year}-01-01"
                ytd_end = f"{current_year}-06-30"
                resolved_period_label = f"Jan 01, {current_year} – Jun 30, {current_year} (H1 {current_year})"
            elif re.search(r'\blast\s+year\b|\bpast\s+year\b|\bprior\s+year\b|\bfy\s*(\d{4})', search_text):
                match_yr = re.search(r'\bfy\s*(\d{4})', search_text)
                target_yr = int(match_yr.group(1)) if match_yr else current_year - 1
                ytd_start = f"{target_yr}-01-01"
                ytd_end = f"{target_yr}-12-31"
                resolved_period_label = f"Jan 01, {target_yr} – Dec 31, {target_yr} (FY {target_yr})"
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
            else:
                ytd_start = f"{current_year}-01-01"
                ytd_end = datetime.now().strftime("%Y-%m-%d")
                resolved_period_label = f"Jan 01, {current_year} – {datetime.now().strftime('%b %d, %Y')}"
    else:
        ytd_start = raw_start or f"{current_year}-01-01"
        ytd_end = raw_end or datetime.now().strftime("%Y-%m-%d")

    # Resolve Template Selection
    template_file, resolved_domain, meta = _resolve_report_template(report_type or report_mode, prompt_text)

    # ── AGENT-DRIVEN PRESENTATION PATH ──────────────────────────────────────────
    # When report_data is provided OR when a specific domain template is selected,
    # we render the presentation template using live database queries and agent synthesis.
    if report_data or template_file != "report_template.html":
        db_domain_data = _fetch_domain_report_data(
            resolved_domain=resolved_domain,
            tenant_id=tenant_id,
            resolved_company_ids=resolved_company_ids,
            start_date=ytd_start,
            end_date=ytd_end,
            base_currency=base_currency,
            tenant_ids=tenant_ids,
            currency=currency,
        )
        merged_report_data = dict(db_domain_data)
        if report_data and isinstance(report_data, dict):
            merged_report_data.update(report_data)
        report_data = merged_report_data

        normalized_data = _normalize_report_data(report_data or {}, currency)
        agent_charts = _render_charts_from_report_data(normalized_data, currency)

        chart_1_b64 = agent_charts.get("chart_1_b64") or kwargs.get("chart_1_b64")
        chart_2_b64 = agent_charts.get("chart_2_b64") or kwargs.get("chart_2_b64")

        # Automatically build trend and waterfall charts if not supplied by agent
        if not chart_1_b64:
            try:
                m_pnl = _get_monthly_pnl_series(tenant_id, company_ids=resolved_company_ids, start_date=ytd_start, end_date=ytd_end, base_currency=base_currency, tenant_ids=tenant_ids)
                if m_pnl:
                    chart_1_b64 = _render_trend_chart(m_pnl[-12:], currency)
            except Exception:
                pass

        if not chart_2_b64:
            try:
                r_v = float(report_data.get("revenue", 0) if isinstance(report_data.get("revenue"), (int, float)) else report_data.get("revenue", {}).get("raw", 0))
                c_v = float(report_data.get("cogs", 0) if isinstance(report_data.get("cogs"), (int, float)) else report_data.get("cogs", {}).get("raw", 0))
                g_v = float(report_data.get("gross_profit", 0) if isinstance(report_data.get("gross_profit"), (int, float)) else report_data.get("gross_profit", {}).get("raw", 0))
                o_v = float(report_data.get("opex", 0) if isinstance(report_data.get("opex"), (int, float)) else report_data.get("opex", {}).get("raw", 0))
                e_v = float(report_data.get("ebit", 0) if isinstance(report_data.get("ebit"), (int, float)) else report_data.get("ebit", {}).get("raw", 0))
                n_v = float(report_data.get("net_profit", 0) if isinstance(report_data.get("net_profit"), (int, float)) else report_data.get("net_profit", {}).get("raw", 0))
                if r_v > 0:
                    chart_2_b64 = _render_waterfall_chart(r_v, c_v, g_v, o_v, e_v, max(e_v - n_v, 0), n_v, currency)
            except Exception:
                pass

        # Process Markdown Custom Content
        custom_content = replace_tenant_ids_with_names(custom_content, tenant_ids or ([tenant_id] if tenant_id else None))
        from .emoji_to_badges import normalize_status_emoji
        custom_content = normalize_status_emoji(custom_content)

        def _chart_block_replacer_agent(match):
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

        custom_content = re.sub(r'```chart\s*\n(.*?)\n```', _chart_block_replacer_agent, custom_content, flags=re.DOTALL | re.IGNORECASE)

        # Autonomous AI Agent Invocation whenever prompt is provided or custom_content is empty
        effective_prompt = kwargs.get("prompt") or prompt_text
        if not custom_content.strip() or effective_prompt:
            ai_analysis = _generate_ai_domain_analysis(
                domain=resolved_domain,
                report_data=report_data,
                prompt=effective_prompt or custom_content,
                company_name=company_name,
                period_label=resolved_period_label,
                comparison_label=resolved_comparison_label,
                currency=currency,
                meta=meta,
            )
            if ai_analysis:
                custom_content = ai_analysis

        if not custom_content.strip():
            rev_display = _fmt_money(report_data.get("revenue", 0) if isinstance(report_data.get("revenue"), (int, float)) else 0, currency)
            ebit_display = _fmt_money(report_data.get("ebit", 0) if isinstance(report_data.get("ebit"), (int, float)) else 0, currency)
            custom_content = f"""
## {meta.get('title', 'Executive Report')}
{meta.get('subtitle', 'Comprehensive business performance report.')}

### Executive Highlights
* **Operational Scope**: Generated **{rev_display}** in total activity for {resolved_period_label}.
* **Earnings Conversion**: Operating profit (EBIT) reached **{ebit_display}**, maintaining disciplined cost controls.
* **Control Observation**: General ledger entries and trade balances reflect posted journal entries in compliance with standard chart of accounts structures.
"""

        custom_content = re.sub(r'^[•\u2022]\s*', '- ', custom_content, flags=re.MULTILINE)
        custom_content = re.sub(r'^[•\u2022\-\*]\s*$', '', custom_content, flags=re.MULTILINE)
        custom_content = re.sub(r'^\d+\.\s*$', '', custom_content, flags=re.MULTILINE)
        custom_content = re.sub(r'([^\n])\s+-\s+([A-Za-z0-9])', r'\1\n- \2', custom_content)
        custom_content = re.sub(r'\n{3,}', '\n\n', custom_content)
        custom_content = _normalize_markdown_tables(custom_content)

        md = markdown.Markdown(extensions=['tables', 'fenced_code', 'sane_lists'])
        body_html = md.convert(custom_content)
        body_html = normalize_status_emoji(body_html)
        from .table_layout import add_dynamic_table_widths
        body_html = add_dynamic_table_widths(body_html)

        template_dir = Path(__file__).parent / "templates"
        env = Environment(loader=FileSystemLoader(str(template_dir)))
        template = env.get_template(template_file)

        logo_mime = "image/png"
        if not logo_b64:
            from ..utils import get_project_logo_b64
            discovered_b64, discovered_mime = get_project_logo_b64(custom_logo_path=logo_path)
            if discovered_b64:
                logo_b64 = discovered_b64
                logo_mime = discovered_mime or "image/png"

        template_kpis = dict(normalized_data)

        html_out = template.render(
            company_name=company_name,
            reporting_period=resolved_period_label,
            view_type=view_type,
            comparison_label=resolved_comparison_label,
            currency=currency,
            last_sync=f"{datetime.now().strftime('%b %d, %Y')} (Posted Ledger)",
            kpis=template_kpis,
            report_data=normalized_data,
            badge=meta.get("badge", "Executive Report"),
            title=meta.get("title", "Executive Report"),
            subtitle=meta.get("subtitle", ""),
            accent=meta.get("accent", "#2563eb"),
            template_kpis=meta.get("kpi_slots", []),
            trend_chart_b64=chart_1_b64,
            waterfall_chart_b64=chart_2_b64,
            wc_chart_b64=kwargs.get("wc_chart_b64"),
            chart_1_b64=chart_1_b64,
            chart_2_b64=chart_2_b64,
            body_html=body_html,
            logo_url=logo_url,
            logo_b64=logo_b64,
            logo_mime=logo_mime,
        )

        reports_dir = _get_reports_dir()
        filename = f"{resolved_domain}_report_{tenant_id}_{datetime.now().strftime('%Y%m%d_%H%M%S_%f')[:19]}_v2.pdf"
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

    # ── EXISTING LEGACY PATH (report_template.html, backward compatibility) ─────
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
        sales = get_sales_summary_tool(tenant_id, company_ids=resolved_company_ids, start_date=ytd_start, end_date=ytd_end, base_currency=base_currency, tenant_ids=tenant_ids)
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
        top_prods = get_top_products_tool(tenant_id, company_ids=resolved_company_ids, start_date=ytd_start, end_date=ytd_end, limit=5, base_currency=base_currency, tenant_ids=tenant_ids)
    except Exception as e:
        logger.warning(f"Top products fetch error: {e}")

    # 3. Extract Values and Compute KPI Variances
    rev_val = float(pnl.get("total_income", 0) or pnl.get("revenue", 0) or sales.get("total_revenue", 0) or 0)
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
    trend_start = ytd_start
    trend_end = ytd_end

    # If the active reporting window is short (e.g. 1 month or <= 45 days), compute a trailing 12-month trend horizon ending at trend_end
    if ytd_start and ytd_end:
        try:
            start_dt = datetime.strptime(ytd_start, "%Y-%m-%d")
            end_dt = datetime.strptime(ytd_end, "%Y-%m-%d")
            if (end_dt - start_dt).days <= 45:
                trend_start = (end_dt - timedelta(days=365)).replace(day=1).strftime("%Y-%m-%d")
        except Exception:
            pass

    try:
        monthly_pnl_data = _get_monthly_pnl_series(
            tenant_id,
            company_ids=resolved_company_ids,
            start_date=trend_start,
            end_date=trend_end,
            base_currency=base_currency,
            tenant_ids=tenant_ids,
        )
    except Exception as e:
        logger.warning(f"Monthly P&L series error: {e}")

    if not monthly_pnl_data:
        # Fallback to scoped time-series if P&L series was empty
        ts_result = {}
        try:
            ts_result = get_time_series_data_tool(
                tenant_id,
                company_ids=resolved_company_ids,
                start_date=trend_start,
                end_date=trend_end,
                granularity="month",
                base_currency=base_currency,
                tenant_ids=tenant_ids
            )
        except Exception:
            pass
        monthly_pnl_data = ts_result.get("points", []) if isinstance(ts_result, dict) else []

    # Ensure trend chart displays at most the trailing 12 data points
    if len(monthly_pnl_data) > 12:
        monthly_pnl_data = monthly_pnl_data[-12:]

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
    custom_content = _normalize_markdown_tables(custom_content)

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
    filename = f"health_report_{tenant_id}_{datetime.now().strftime('%Y%m%d_%H%M%S_%f')[:19]}_v2.pdf"
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
    files = list(reports_dir.glob(f'*_report_{tenant_id}_*_v2.pdf'))
    if not files:
        files = list(reports_dir.glob(f'*_report_{tenant_id}_*.pdf'))
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
