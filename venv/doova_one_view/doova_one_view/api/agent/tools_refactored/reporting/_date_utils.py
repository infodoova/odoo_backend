# doova_one_view/api/agent/tools_refactored/reporting/_date_utils.py
"""
Reporting date utilities.
Delegates to unified date_engine for deterministic comparison and period math.
"""

from typing import Optional
from doova_one_view.api.agent.date_engine import (
    _infer_comparison_label as _engine_infer_label,
    resolve_comparison_dates,
    resolve_period_dates,
    normalize_iso_date,
    format_period_label,
)


def _infer_comparison_label(days: int) -> str:
    """
    Auto-derive the comparison basis label from the span of the date range in days.
    """
    return _engine_infer_label(days)


def _resolve_prior_period_dates(
    start_date: str | None,
    end_date: str | None,
    comparison_label: str = "",
    comparison_type: str = "",
) -> tuple[str, str]:
    """
    Auto-derive the prior comparison period (prior_start, prior_end) ISO date strings
    from current period date range and comparison basis (MoM, QoQ, YoY, HoH, WoW, etc.).
    """
    p_start, p_end, _ = resolve_comparison_dates(
        start_date=start_date,
        end_date=end_date,
        comparison_label=comparison_label,
        comparison_type=comparison_type,
    )
    return p_start, p_end
