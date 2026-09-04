# doova_one_view/api/agent/tools_refactored/reporting/_formatters.py

import re
from typing import Optional, Union


def _fmt_money(val: float | int | None, currency: str = "XAF", parens: bool = False, is_diff: bool = False) -> str:
    """Format monetary numbers with thousand separators and minus sign for negatives."""
    if val is None:
        return f"— {currency}"
    val = float(val)
    if abs(val) < 0.01:
        return f"0 {currency}"
    
    if val < 0:
        pos_val = abs(val)
        formatted = f"{pos_val:,.0f} {currency}"
        return f"-{formatted}" if not parens else f"({formatted})"
    else:
        prefix = "+" if is_diff else ""
        return f"{prefix}{val:,.0f} {currency}"


def _highlight_negative_numbers_html(html: str) -> str:
    """
    Transforms any negative parenthesized numbers into minus format
    (e.g., (26,239,082 XAF) -> -26,239,082 XAF, ($82,405,168) -> -$82,405,168)
    and ensures all negative values in KPI cards and table cells are styled bold and red.
    """
    if not html:
        return html

    # 1. Convert parenthesized currencies and percentages into minus format
    html = re.sub(r'\(([0-9,]+(?:\.[0-9]+)?\s*(?:[A-Z]{3}|\$|€|£|%))\)', r'-\1', html)
    html = re.sub(r'\(([A-Z]{3}|\$|€|£)\s*([0-9,]+(?:\.[0-9]+)?)\)', r'-\1\2', html)

    # 2. In KPI values, add 'neg-val' class if value begins with a minus
    html = re.sub(
        r'(<div\s+class="kpi-value)([^"]*">)\s*(-[0-9$€£A-Za-z])',
        r'\1 neg-val\2\3',
        html
    )

    # 3. In table cells (<td>), wrap negative amounts / percentages in <span class="neg-val">
    def _wrap_td_neg(match):
        open_tag = match.group(1)
        val = match.group(2).strip()
        close_tag = match.group(3)
        if '<span' in val:
            return match.group(0)
        return f'{open_tag}<span class="neg-val">{val}</span>{close_tag}'

    html = re.sub(
        r'(<td[^>]*>)\s*(-(?:\$|€|£|[A-Z]{3}\s*)?[0-9,]+(?:\.[0-9]+)?(?:\s*[A-Z]{3}|%)?)\s*(</td>)',
        _wrap_td_neg,
        html
    )

    return html


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
