# doova_one_view/api/agent/tools_refactored/reporting/_charts.py

import io
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
