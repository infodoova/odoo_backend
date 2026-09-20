# doova_one_view/api/agent/tools_refactored/reporting/_charts.py

import io
import re
import json
import ast
import base64
import logging
import warnings

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.ticker as ticker

from ._formatters import _friendly_axis_formatter

logging.getLogger('matplotlib').setLevel(logging.ERROR)
warnings.filterwarnings("ignore", category=UserWarning, module="matplotlib")
warnings.filterwarnings("ignore", module="matplotlib")
logger = logging.getLogger(__name__)


def _render_trend_chart(ts_data: list, currency: str = "XAF", domain: str = "general") -> str:
    """Multi-series Performance Trend Chart (Revenue, Procurement Spend, OpEx, Net Profit)."""
    if not ts_data:
        return ""
    try:
        labels = [str(d.get("period", ""))[:7] for d in ts_data]
        revenues = [float(d.get("revenue", d.get("spend", 0))) for d in ts_data]
        
        domain_lower = (domain or "general").lower()
        if domain_lower in ("purchase", "purchasing", "procurement"):
            primary_label = "Procurement Spend"
            primary_color = "#0284c7"
            primary_fill = "#f0f9ff"
        elif domain_lower in ("inventory", "stock"):
            primary_label = "Stock Valuation"
            primary_color = "#0d9488"
            primary_fill = "#f0fdfa"
        else:
            primary_label = "Revenue"
            primary_color = "#2563eb"
            primary_fill = "#eff6ff"

        # Use real expenses & net profit if available from P&L series; do NOT fabricate fake expenses
        has_real_expenses = any("expenses" in d and d.get("expenses") is not None for d in ts_data)

        fig, ax = plt.subplots(figsize=(8, 3.2), facecolor='white')
        ax.plot(labels, revenues, marker='o', color=primary_color, linewidth=2.2, label=primary_label, markersize=5)
        ax.fill_between(labels, revenues, color=primary_fill, alpha=0.5)

        if has_real_expenses and domain_lower not in ("purchase", "purchasing", "procurement", "inventory", "stock", "sales", "commercial"):
            expenses = [float(d.get("expenses", 0) or 0) for d in ts_data]
            net_profits = [float(d.get("net_profit", 0) or 0) for d in ts_data]
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


def _parse_numeric_value(val) -> float | None:
    """
    Safely parses numeric values from numbers or strings, stripping currencies,
    commas, percentages, and handling magnitude suffixes (K, M, B) and negative formats.
    """
    if val is None:
        return None
    if isinstance(val, (int, float)):
        return float(val)
    s = str(val).strip()
    if not s:
        return None

    is_neg = False
    if s.startswith("(") and s.endswith(")"):
        is_neg = True
        s = s[1:-1].strip()
    elif s.startswith("-"):
        is_neg = True
        s = s[1:].strip()

    multiplier = 1.0
    last_char = s[-1].lower() if s and s[-1].isalpha() else ""
    if last_char == 'k':
        multiplier = 1000.0
        s = s[:-1].strip()
    elif last_char == 'm':
        multiplier = 1000000.0
        s = s[:-1].strip()
    elif last_char == 'b':
        multiplier = 1000000000.0
        s = s[:-1].strip()

    cleaned = re.sub(r'[^\d.-]', '', s)
    if not cleaned or cleaned in ('.', '-'):
        return None
    try:
        num = float(cleaned) * multiplier
        return -num if is_neg else num
    except (ValueError, TypeError):
        return None


def _parse_chart_config(raw_str: str) -> dict | None:
    """
    Robust multi-tier parser for chart configuration blocks:
    1. Standard json.loads
    2. Python ast.literal_eval for single quotes & python literals
    3. Structural repair (trailing commas, unquoted keys, missing brackets)
    4. Heuristic regex extraction
    """
    if not raw_str:
        return None
    cleaned = raw_str.strip()

    cleaned = re.sub(r'^```(?:chart|json|graph)?\s*', '', cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r'\s*```$', '', cleaned)
    cleaned = cleaned.strip()

    cleaned = cleaned.replace('“', '"').replace('”', '"').replace('‘', "'").replace('’', "'")

    # Tier 1: Standard JSON
    try:
        res = json.loads(cleaned)
        if isinstance(res, dict):
            return res
    except Exception:
        pass

    # Tier 2: Python AST literal_eval (handles single quotes: {'chart_type': 'bar'})
    try:
        res = ast.literal_eval(cleaned)
        if isinstance(res, dict):
            return res
    except Exception:
        pass

    # Tier 3: Structural JSON Repair
    try:
        repaired = cleaned
        repaired = re.sub(r'\bTrue\b', 'true', repaired)
        repaired = re.sub(r'\bFalse\b', 'false', repaired)
        repaired = re.sub(r'\bNone\b', 'null', repaired)
        repaired = re.sub(r',\s*([\]\}])', r'\1', repaired)
        repaired = re.sub(r'([{,]\s*)([a-zA-Z_][a-zA-Z0-9_]*)\s*:', r'\1"\2":', repaired)
        open_b = repaired.count('{') - repaired.count('}')
        if open_b > 0:
            repaired += '}' * open_b
        open_sq = repaired.count('[') - repaired.count(']')
        if open_sq > 0:
            repaired += ']' * open_sq
        res = json.loads(repaired)
        if isinstance(res, dict):
            return res
    except Exception:
        pass

    # Tier 4: Heuristic Regex extraction (if LLM produced a malformed or cut-off payload)
    try:
        cfg = {}
        m_title = re.search(r'["\']title["\']\s*:\s*["\']([^"\']+)["\']', cleaned)
        if m_title:
            cfg["title"] = m_title.group(1).strip()
        m_type = re.search(r'["\'](?:chart_type|type)["\']\s*:\s*["\']([^"\']+)["\']', cleaned)
        if m_type:
            cfg["chart_type"] = m_type.group(1).strip()
        m_labels = re.search(r'["\'](?:labels|categories)["\']\s*:\s*\[([\s\S]*?)\]', cleaned)
        if m_labels:
            raw_labels = re.findall(r'["\']([^"\']+)["\']', m_labels.group(1))
            if raw_labels:
                cfg["labels"] = raw_labels
        m_values = re.search(r'["\'](?:values|data)["\']\s*:\s*\[([\s\S]*?)\]', cleaned)
        if m_values:
            raw_vals = [v.strip().strip('"\'') for v in m_values.group(1).split(',') if v.strip()]
            cfg["values"] = raw_vals
        if cfg.get("labels") and cfg.get("values"):
            return cfg
    except Exception:
        pass

    return None


def _normalize_chart_data(cfg: dict) -> dict:
    """
    Standardizes any chart config format (labels/values, datasets, series, list of objects, key-value dict)
    into a unified structure ready for plotting:
    {
        'title': str,
        'chart_type': str,
        'labels': list[str],
        'values': list[float],
        'series': list[dict],
        'is_multi_series': bool
    }
    """
    if not isinstance(cfg, dict):
        return {}

    title = str(cfg.get("title") or "").strip()
    raw_type = str(cfg.get("chart_type") or cfg.get("type") or "bar").lower().strip()

    if any(k in raw_type for k in ["barh", "horizontal", "h_bar", "aging"]):
        chart_type = "horizontal_bar"
    elif any(k in raw_type for k in ["pie", "donut", "doughnut"]):
        chart_type = "donut"
    elif any(k in raw_type for k in ["line", "trend"]):
        chart_type = "line"
    elif "area" in raw_type:
        chart_type = "area"
    elif "waterfall" in raw_type:
        chart_type = "waterfall"
    elif any(k in raw_type for k in ["stacked", "stack"]):
        chart_type = "stacked_bar"
    elif any(k in raw_type for k in ["group", "multi"]):
        chart_type = "grouped_bar"
    else:
        chart_type = "bar"

    labels = []
    values = []
    series = []
    is_multi_series = False

    inner_chart = cfg.get("chart")
    if isinstance(inner_chart, dict):
        inner_norm = _normalize_chart_data(inner_chart)
        if not title and cfg.get("title"):
            inner_norm["title"] = str(cfg["title"]).strip()
        return inner_norm

    inner_data = cfg.get("data")
    if isinstance(inner_data, dict) and "labels" in inner_data:
        labels = [str(l) for l in inner_data.get("labels", [])]
        datasets = inner_data.get("datasets", [])
        if isinstance(datasets, list) and datasets:
            if len(datasets) == 1 and isinstance(datasets[0], dict):
                raw_v = datasets[0].get("data", [])
                values = [_parse_numeric_value(v) for v in raw_v if _parse_numeric_value(v) is not None]
            else:
                is_multi_series = True
                for ds in datasets:
                    if isinstance(ds, dict):
                        s_name = str(ds.get("label", ds.get("name", "Series")))
                        s_vals = [_parse_numeric_value(v) for v in ds.get("data", [])]
                        series.append({"name": s_name, "values": [v or 0.0 for v in s_vals]})

    elif isinstance(cfg.get("series"), list) and cfg.get("series"):
        is_multi_series = True
        labels = [str(l) for l in (cfg.get("labels") or cfg.get("categories") or [])]
        for s in cfg["series"]:
            if isinstance(s, dict):
                s_name = str(s.get("name", s.get("label", "Series")))
                s_vals = [_parse_numeric_value(v) for v in (s.get("values") or s.get("data") or [])]
                series.append({"name": s_name, "values": [v or 0.0 for v in s_vals]})

    elif isinstance(inner_data, list) and inner_data:
        for item in inner_data:
            if isinstance(item, dict):
                lbl = str(item.get("name") or item.get("label") or item.get("x") or item.get("category") or "")
                val = _parse_numeric_value(item.get("value") or item.get("y") or item.get("amount") or item.get("val"))
                if lbl and val is not None:
                    labels.append(lbl)
                    values.append(val)

    elif cfg.get("labels") or cfg.get("categories") or cfg.get("x"):
        raw_labels = cfg.get("labels") or cfg.get("categories") or cfg.get("x") or []
        raw_values = cfg.get("values") or cfg.get("data") or cfg.get("y") or []
        for l in raw_labels:
            labels.append(str(l))
        for v in raw_values:
            parsed = _parse_numeric_value(v)
            if parsed is not None:
                values.append(parsed)

    elif isinstance(inner_data, dict):
        for k, v in inner_data.items():
            parsed = _parse_numeric_value(v)
            if parsed is not None:
                labels.append(str(k))
                values.append(parsed)

    # Intelligent Auto-Orientation:
    # If standard vertical bar is requested, but labels are long strings (e.g. Accounts Receivable Aging,
    # customer names, product categories), auto-switch to horizontal_bar so text is completely readable.
    if chart_type in ("bar", "column") and not is_multi_series and labels:
        avg_len = sum(len(l) for l in labels) / max(len(labels), 1)
        if avg_len > 9 or (len(labels) >= 4 and any(len(l) > 12 for l in labels)):
            chart_type = "horizontal_bar"

    return {
        "title": title,
        "chart_type": chart_type,
        "labels": labels,
        "values": values,
        "series": series,
        "is_multi_series": is_multi_series,
    }


def _render_chart_graphic(info: dict) -> str:
    """
    Renders matplotlib chart from normalized chart info into a base64 encoded PNG image.
    Thread-safe, high-resolution (DPI 160), professional executive color palette.
    """
    if not info:
        return ""

    labels = info.get("labels", [])
    values = info.get("values", [])
    series = info.get("series", [])
    is_multi_series = info.get("is_multi_series", False)
    chart_type = info.get("chart_type", "bar")
    title = info.get("title", "")

    if is_multi_series:
        if not series or not any(s.get("values") for s in series):
            return ""
        if not labels:
            max_len = max(len(s.get("values", [])) for s in series)
            labels = [f"Item {i+1}" for i in range(max_len)]
    else:
        if not labels or not values or len(labels) != len(values):
            min_len = min(len(labels), len(values))
            if min_len >= 1:
                labels = labels[:min_len]
                values = values[:min_len]
            else:
                return ""

    n_items = len(labels)
    fig_height = 3.5
    if chart_type == "horizontal_bar":
        fig_height = max(3.0, 0.45 * n_items + 1.2)
    elif chart_type in ("donut", "pie"):
        fig_height = 3.6

    fig, ax = plt.subplots(figsize=(8.0, fig_height), facecolor='white', dpi=160)

    try:
        palette = ['#2563eb', '#06b6d4', '#10b981', '#f59e0b', '#8b5cf6', '#ec4899', '#f97316', '#64748b']

        if chart_type == "horizontal_bar":
            bars = ax.barh(labels, values, color='#2563eb', height=0.52, edgecolor='white', linewidth=1.2, zorder=3)
            ax.invert_yaxis()
            ax.xaxis.grid(True, linestyle=':', color='#e2e8f0', alpha=0.8, zorder=1)
            ax.yaxis.grid(False)
            ax.xaxis.set_major_formatter(ticker.FuncFormatter(_friendly_axis_formatter))
            max_v = max(abs(v) for v in values) if values else 1.0
            offset = max_v * 0.02
            for bar, val in zip(bars, values):
                txt = _friendly_axis_formatter(val)
                x_pos = val + offset if val >= 0 else val - offset
                ha = 'left' if val >= 0 else 'right'
                ax.text(x_pos, bar.get_y() + bar.get_height()/2, txt, va='center', ha=ha,
                        fontsize=7.8, fontweight='bold', color='#1e293b')

        elif chart_type in ("line", "trend", "area"):
            ax.plot(labels, values, color='#2563eb', marker='o', linewidth=2.2, markersize=5.5,
                    markerfacecolor='white', markeredgecolor='#2563eb', markeredgewidth=1.8, zorder=4)
            if chart_type == "area":
                ax.fill_between(range(len(labels)), values, color='#2563eb', alpha=0.12, zorder=2)
            ax.yaxis.grid(True, linestyle=':', color='#e2e8f0', alpha=0.8, zorder=1)
            ax.xaxis.grid(False)
            ax.yaxis.set_major_formatter(ticker.FuncFormatter(_friendly_axis_formatter))
            for idx, val in enumerate(values):
                ax.annotate(_friendly_axis_formatter(val), (idx, val), textcoords="offset points",
                            xytext=(0, 6), ha='center', fontsize=7.5, fontweight='bold', color='#334155')
            if len(labels) > 4:
                plt.xticks(rotation=22, ha='right', fontsize=7.8)

        elif chart_type in ("donut", "pie"):
            colors = (palette * ((len(values) // len(palette)) + 1))[:len(values)]
            wedges, texts, autotexts = ax.pie(
                values,
                labels=labels if len(labels) <= 6 else None,
                autopct='%1.1f%%',
                pctdistance=0.75,
                colors=colors,
                startangle=140,
                wedgeprops=dict(width=0.48, edgecolor='white', linewidth=1.8)
            )
            for at in autotexts:
                at.set_fontsize(7.8)
                at.set_fontweight('bold')
                at.set_color('#ffffff')
            if len(labels) > 6:
                ax.legend(wedges, labels, loc="center left", bbox_to_anchor=(1, 0, 0.5, 1), fontsize=7.5)

        elif is_multi_series or chart_type in ("grouped_bar", "stacked_bar"):
            import numpy as np
            n_series = len(series)
            x_indices = np.arange(len(labels))
            if chart_type == "stacked_bar":
                bottom_accum = np.zeros(len(labels))
                for s_idx, s in enumerate(series):
                    s_vals = np.array(s.get("values", [])[:len(labels)])
                    color = palette[s_idx % len(palette)]
                    ax.bar(x_indices, s_vals, bottom=bottom_accum, label=s.get("name", f"Series {s_idx+1}"),
                           color=color, width=0.52, edgecolor='white', linewidth=1)
                    bottom_accum += s_vals
            else:
                total_w = 0.7
                sub_w = total_w / max(n_series, 1)
                for s_idx, s in enumerate(series):
                    s_vals = s.get("values", [])[:len(labels)]
                    s_x = x_indices - (total_w / 2) + (s_idx + 0.5) * sub_w
                    color = palette[s_idx % len(palette)]
                    ax.bar(s_x, s_vals, label=s.get("name", f"Series {s_idx+1}"),
                           color=color, width=sub_w * 0.9, edgecolor='white', linewidth=0.8)
            ax.set_xticks(x_indices)
            ax.set_xticklabels(labels)
            ax.yaxis.grid(True, linestyle=':', color='#e2e8f0', alpha=0.8)
            ax.xaxis.grid(False)
            ax.yaxis.set_major_formatter(ticker.FuncFormatter(_friendly_axis_formatter))
            ax.legend(loc='upper right', fontsize=7.5, frameon=True)
            if len(labels) > 4:
                plt.xticks(rotation=22, ha='right', fontsize=7.8)

        elif chart_type == "waterfall":
            bottoms = []
            heights = []
            curr = 0.0
            colors = []
            for idx, (lbl, v) in enumerate(zip(labels, values)):
                is_subtotal = any(k in lbl.lower() for k in ["total", "net", "ebit", "profit"]) and idx > 0
                if is_subtotal:
                    bottoms.append(0.0)
                    heights.append(curr)
                    colors.append('#2563eb' if curr >= 0 else '#ef4444')
                else:
                    if v >= 0:
                        bottoms.append(curr)
                        heights.append(v)
                        curr += v
                        colors.append('#10b981')
                    else:
                        curr += v
                        bottoms.append(curr)
                        heights.append(abs(v))
                        colors.append('#ef4444')
            ax.bar(labels, heights, bottom=bottoms, color=colors, width=0.52, edgecolor='white', linewidth=1)
            ax.axhline(0, color='#64748b', linewidth=0.8, linestyle='-')
            ax.yaxis.grid(True, linestyle=':', color='#e2e8f0', alpha=0.8)
            ax.xaxis.grid(False)
            ax.yaxis.set_major_formatter(ticker.FuncFormatter(_friendly_axis_formatter))
            if len(labels) > 4:
                plt.xticks(rotation=22, ha='right', fontsize=7.8)

        else:
            bars = ax.bar(labels, values, color='#2563eb', width=0.52, edgecolor='white', linewidth=1.2, zorder=3)
            ax.yaxis.grid(True, linestyle=':', color='#e2e8f0', alpha=0.8, zorder=1)
            ax.xaxis.grid(False)
            ax.axhline(0, color='#94a3b8', linewidth=0.8, linestyle='-')
            ax.yaxis.set_major_formatter(ticker.FuncFormatter(_friendly_axis_formatter))
            max_v = max(abs(v) for v in values) if values else 1.0
            offset = max_v * 0.03
            for bar, val in zip(bars, values):
                txt = _friendly_axis_formatter(val)
                y_pos = val + offset if val >= 0 else val - offset
                va = 'bottom' if val >= 0 else 'top'
                ax.text(bar.get_x() + bar.get_width()/2, y_pos, txt, va=va, ha='center',
                        fontsize=7.8, fontweight='bold', color='#1e293b')
            if len(labels) > 4:
                plt.xticks(rotation=22, ha='right', fontsize=7.8)

        if chart_type not in ("pie", "donut"):
            ax.spines['top'].set_visible(False)
            ax.spines['right'].set_visible(False)
            ax.spines['left'].set_color('#cbd5e1')
            ax.spines['bottom'].set_color('#cbd5e1')
            ax.tick_params(colors='#64748b', labelsize=7.8)
            if hasattr(ax.yaxis, "offsetText"):
                ax.yaxis.offsetText.set_visible(False)
            if hasattr(ax.xaxis, "offsetText"):
                ax.xaxis.offsetText.set_visible(False)

        if title:
            plt.title(title, fontsize=9.8, fontweight='bold', pad=12, color='#0f172a')

        plt.tight_layout()

        buf = io.BytesIO()
        plt.savefig(buf, format='png', dpi=160, bbox_inches='tight')
        buf.seek(0)
        img_b64 = base64.b64encode(buf.read()).decode('utf-8')
        return img_b64

    except Exception as e:
        logger.warning(f"_render_chart_graphic error: {e}")
        return ""
    finally:
        plt.close(fig)


def _render_custom_chart_blocks(content: str) -> str:
    """
    Universal chart converter:
    Detects and converts ANY ```chart ... ```, ```json {"chart_type": ...} ```,
    ```graph ... ```, unclosed chart fences, or bare chart JSON into base64 embedded
    matplotlib images inside <div class="chart-box">.
    Guarantees ZERO code leakage: unparseable blocks are converted to executive tables
    or cleanly removed so literal code never reaches the report.
    """
    if not content:
        return ""

    if not any(k in content.lower() for k in ["chart", "graph", "labels", "values"]):
        return content

    def _replace_match(match):
        raw_payload = match.group(1).strip()
        cfg = _parse_chart_config(raw_payload)
        if cfg:
            info = _normalize_chart_data(cfg)
            b64 = _render_chart_graphic(info)
            if b64:
                title_attr = f' alt="{info.get("title", "Chart")}"'
                return (
                    f'<div class="chart-box" style="margin: 16px 0; text-align: center; background: #ffffff; '
                    f'border: 1px solid #e2e8f0; border-radius: 8px; padding: 12px; page-break-inside: avoid;">'
                    f'<img class="chart-img" style="max-width: 100%; height: auto; display: block; margin: 0 auto; border-radius: 4px;" '
                    f'src="data:image/png;base64,{b64}"{title_attr} /></div>'
                )
            labels = info.get("labels", [])
            values = info.get("values", [])
            title = info.get("title", "Metric Breakdown")
            if labels and values:
                rows_html = "".join(f'<tr><td style="padding: 4px 8px; border-bottom: 1px solid #e2e8f0; font-size: 8pt;">{l}</td>'
                                    f'<td style="padding: 4px 8px; border-bottom: 1px solid #e2e8f0; font-weight: bold; text-align: right; font-size: 8pt;">{_friendly_axis_formatter(v)}</td></tr>'
                                    for l, v in zip(labels, values))
                return (
                    f'<div class="chart-box" style="margin: 14px 0; padding: 10px 14px; background: #f8fafc; '
                    f'border: 1px solid #e2e8f0; border-radius: 6px; page-break-inside: avoid;">'
                    f'<div style="font-weight: bold; font-size: 9pt; color: #0f172a; margin-bottom: 6px;">{title}</div>'
                    f'<table style="width: 100%; border-collapse: collapse;">{rows_html}</table></div>'
                )

        return ""

    # 1. Standard or same-line ```chart {...} ``` or ```json {"chart_type"...} ```
    pattern = r'```(?:chart\b[:\s]*|json\s*(?=\{[\s\S]*?(?:"chart_type"|"type"\s*:\s*"(?:chart|graph)"|"labels"\s*:|"values"\s*:))|graph\b[:\s]*)\s*(\{[\s\S]*?\})\s*```'
    content = re.sub(pattern, _replace_match, content, flags=re.IGNORECASE)

    # 2. Unclosed chart block at end of text (e.g. LLM token cutoff: ```chart { ... )
    unclosed_pattern = r'```(?:chart\b[:\s]*|graph\b[:\s]*)\s*(\{[\s\S]*?)(?:```|$)'
    content = re.sub(unclosed_pattern, _replace_match, content, flags=re.IGNORECASE)

    # 3. Bare JSON blocks containing "chart_type": "..."
    bare_pattern = r'(?:^|\n)\s*(\{\s*"(?:chart_type|type)"\s*:\s*"(?:chart|bar|line|pie|donut|waterfall|horizontal_bar)"[\s\S]*?\})(?=\s*$|\s*\n)'
    content = re.sub(bare_pattern, _replace_match, content, flags=re.IGNORECASE)

    # 4. Final Defense Sweep: remove any leftover orphaned ```chart ... ``` blocks
    content = re.sub(r'```chart[\s\S]*?```', '', content, flags=re.IGNORECASE)
    content = re.sub(r'```chart[\s\S]*?$', '', content, flags=re.IGNORECASE)

    return content


def _sanitize_rendered_report_html(html: str) -> str:
    """
    Final defense post-processor on generated HTML:
    If markdown conversion ever turned an escaped chart block into
    <pre><code class="language-chart">...</code></pre> or <pre><code>{"chart_type"...</code></pre>,
    this intercepts it, renders the chart graphic, and replaces the code block with the chart box.
    Guarantees raw chart code NEVER appears in the rendered PDF document.
    """
    if not html or ("language-chart" not in html and "chart_type" not in html):
        return html

    def _replace_code_block(match):
        code_text = match.group(1).strip()
        code_text = code_text.replace("&quot;", '"').replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">")
        cfg = _parse_chart_config(code_text)
        if cfg:
            info = _normalize_chart_data(cfg)
            b64 = _render_chart_graphic(info)
            if b64:
                return (
                    f'<div class="chart-box" style="margin: 16px 0; text-align: center; background: #ffffff; '
                    f'border: 1px solid #e2e8f0; border-radius: 8px; padding: 12px; page-break-inside: avoid;">'
                    f'<img class="chart-img" style="max-width: 100%; height: auto; display: block; margin: 0 auto; border-radius: 4px;" '
                    f'src="data:image/png;base64,{b64}" alt="{info.get("title", "Chart")}" /></div>'
                )
        return ""

    html = re.sub(
        r'<pre><code(?:\s+class="[^"]*(?:chart|json)[^"]*")?>([\s\S]*?\{[\s\S]*?"chart_type"[\s\S]*?\})</code></pre>',
        _replace_code_block,
        html,
        flags=re.IGNORECASE
    )
    html = re.sub(
        r'<pre><code\s+class="language-chart">([\s\S]*?)</code></pre>',
        _replace_code_block,
        html,
        flags=re.IGNORECASE
    )
    return html

