# doova_one_view/api/agent/tools_refactored/reporting/_variance.py

from typing import Optional, Union
from ._formatters import _fmt_money


def _compute_variance(current: float, prior: float) -> tuple[float, float]:
    """Returns (var_pct, var_amt). Handles zero prior safely."""
    delta = current - prior
    if abs(prior) < 0.01:
        pct = 100.0 if current > 0 else (-100.0 if current < 0 else 0.0)
    else:
        pct = (delta / abs(prior)) * 100.0
    return round(pct, 1), delta


def _build_kpi_variance(
    current: float | int | None,
    prior: float | int | None,
    currency: str = "XAF",
    fmt: str = "money",
    polarity: str = "positive",
) -> dict:
    """
    Constructs a structured KPI dictionary containing raw, formatted value,
    and variance badges against a prior period.
    """
    current_f = float(current or 0.0)
    prior_f = float(prior or 0.0) if prior is not None else 0.0

    # Format current value
    if fmt == "pct":
        fmt_str = f"{current_f:.1f}%"
    elif fmt == "count":
        fmt_str = f"{int(current_f):,}"
    elif fmt == "ratio":
        fmt_str = f"{current_f:.2f}"
    elif fmt == "runway":
        fmt_str = f"{current_f:.1f} Mos" if current_f > 0 else "0.0 Mos"
    else:
        fmt_str = _fmt_money(current_f, currency)

    result = {
        "raw": current_f,
        "formatted": fmt_str,
    }

    if abs(prior_f) < 0.001:
        # No prior comparison available
        return result

    if fmt == "pct":
        delta_pts = round(current_f - prior_f, 1)
        sign = "+" if delta_pts > 0 else ""
        result["var_text"] = f"{sign}{delta_pts:.1f} pts"
        if delta_pts > 0:
            result["arrow"] = "▲"
            result["var_class"] = "variance-positive" if polarity != "negative" else "variance-negative"
        elif delta_pts < 0:
            result["arrow"] = "▼"
            result["var_class"] = "variance-negative" if polarity != "negative" else "variance-positive"
        else:
            result["arrow"] = ""
            result["var_class"] = "variance-neutral"
    else:
        var_pct, var_amt = _compute_variance(current_f, prior_f)
        sign = "+" if var_pct > 0 else ""
        if fmt == "money":
            diff_str = _fmt_money(var_amt, currency, is_diff=True)
            result["var_text"] = f"{sign}{var_pct:.1f}% ({diff_str})"
        else:
            result["var_text"] = f"{sign}{var_pct:.1f}%"

        if polarity == "negative":
            # Higher is worse (e.g. expenses, cost, payables)
            result["arrow"] = "▲" if var_pct > 0 else "▼"
            result["var_class"] = "variance-negative" if var_pct > 5 else ("variance-neutral" if var_pct >= 0 else "variance-positive")
        elif polarity == "neutral":
            result["arrow"] = "▲" if var_pct >= 0 else "▼"
            result["var_class"] = "variance-neutral"
        else:
            # Positive: higher is better
            result["arrow"] = "▲" if var_pct >= 0 else "▼"
            result["var_class"] = "variance-positive" if var_pct >= 0 else "variance-negative"

    return result
