# doova_one_view/api/agent/tools_refactored/reporting/_normalize.py

import re
import logging
from typing import Optional, Dict, Any

from ._formatters import _fmt_money
from ._charts import _render_trend_chart, _render_waterfall_chart

logger = logging.getLogger(__name__)


def _normalize_markdown_tables(text: str) -> str:
    """
    Sanitizes markdown tables emitted by LLMs:
    1. Replaces collapsed row delimiters ('| |' or '||') with proper row newlines ('|\n|').
    2. Detaches any prefix on the same line before a table header (e.g. '3. Section Name | Col 1 | Col 2 |' -> '3. Section Name\n\n| Col 1 | Col 2 |').
    3. Guarantees clean blank lines before and after table blocks so Markdown converts them to HTML <table>.
    """
    if not text:
        return ""

    # 1. Fix collapsed rows on a single line separated by '| |' or '||'
    text = re.sub(r'\|\s*\|\s*', '|\n|', text)

    # 2. Split any prefix preceding a table header on the same line (numbered items, headings, bullet points, labels)
    text = re.sub(
        r'(^|\n)([^\n\|]+?)(\|[^|\n]+\|[^|\n]+\|)',
        lambda m: f"{m.group(1)}{m.group(2).strip()}\n\n{m.group(3)}" if m.group(2).strip() else m.group(0),
        text
    )

    # 3. Ensure a blank line before any table block starting with | if preceded by non-table text
    text = re.sub(r'([^\n\|])\n+(\|)', r'\1\n\n\2', text)

    # 4. Ensure a blank line after any table block ending with | if followed by non-table text
    text = re.sub(r'(\|\n+)([^\n\|])', r'\1\n\n\2', text)

    return text


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
            if any(p in k_lower for p in ["margin", "pct", "rate", "percent", "achievement", "share", "roe", "roa", "roi"]):
                fmt_str = f"{f_val:.1f}%"
            elif any(s in k_lower for s in ["score", "health"]):
                fmt_str = f"{f_val:.0f}"
            elif any(c in k_lower for c in ["count", "volume", "orders", "pos", "skus", "items"]):
                fmt_str = f"{int(f_val):,}"
            elif re.search(r'(?:^|_)(?:current_ratio|quick_ratio|ratio|turnover|multiplier)(?:_|$)', k_lower) or k_lower in ("ratio", "current_ratio", "quick_ratio", "stock_turnover", "inventory_turnover", "working_capital_ratio"):
                fmt_str = f"{f_val:.2f}"
            elif "runway" in k_lower:
                fmt_str = f"{f_val:.1f} Mos" if f_val > 0 else "0.0 Mos"
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
                if any(p in k_lower for p in ["margin", "pct", "rate", "percent", "achievement", "share", "roe", "roa", "roi"]):
                    fmt_str = f"{f_val:.1f}%"
                elif any(s in k_lower for s in ["score", "health"]):
                    fmt_str = f"{f_val:.0f}"
                elif any(c in k_lower for c in ["count", "volume", "orders", "pos", "skus", "items"]):
                    fmt_str = f"{int(f_val):,}"
                elif re.search(r'(?:^|_)(?:current_ratio|quick_ratio|ratio|turnover|multiplier)(?:_|$)', k_lower) or k_lower in ("ratio", "current_ratio", "quick_ratio", "stock_turnover", "inventory_turnover", "working_capital_ratio"):
                    fmt_str = f"{f_val:.2f}"
                elif "runway" in k_lower:
                    fmt_str = f"{f_val:.1f} Mos" if f_val > 0 else "0.0 Mos"
                else:
                    fmt_str = _fmt_money(f_val, currency)
                val_copy["formatted"] = fmt_str
                normalized[key] = val_copy

    return normalized


def _render_charts_from_report_data(report_data: dict, currency: str, domain: str = "general") -> dict:
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
            charts["chart_1_b64"] = _render_trend_chart(trend_data, currency, domain=domain)
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
