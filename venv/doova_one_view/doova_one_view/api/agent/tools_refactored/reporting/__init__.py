# doova_one_view/api/agent/tools_refactored/reporting/__init__.py

from .generate_report_tool import generate_report_tool, get_last_report_tool
from ._date_utils import _infer_comparison_label, _resolve_prior_period_dates
from ._formatters import (
    _fmt_money,
    _fmt_pct,
    _highlight_negative_numbers_html,
    _friendly_axis_formatter,
)
from ._variance import _compute_variance, _build_kpi_variance
from ._charts import (
    _render_trend_chart,
    _render_waterfall_chart,
    _render_working_capital_chart,
)
from ._series import _get_monthly_pnl_series, _get_domain_trend_series
from ._normalize import (
    _normalize_report_data,
    _normalize_markdown_tables,
    _render_charts_from_report_data,
)
from ._ai_synthesis import (
    _generate_ai_executive_summary_llm,
    _generate_ai_domain_analysis,
)
from ._autonomous_insights import _synthesize_autonomous_insights
from ._template_router import _resolve_report_template, _get_reports_dir
from ._domain_data import _fetch_domain_report_data

__all__ = [
    "generate_report_tool",
    "get_last_report_tool",
    "_infer_comparison_label",
    "_resolve_prior_period_dates",
    "_fmt_money",
    "_fmt_pct",
    "_highlight_negative_numbers_html",
    "_friendly_axis_formatter",
    "_compute_variance",
    "_build_kpi_variance",
    "_render_trend_chart",
    "_render_waterfall_chart",
    "_render_working_capital_chart",
    "_get_monthly_pnl_series",
    "_get_domain_trend_series",
    "_normalize_report_data",
    "_normalize_markdown_tables",
    "_render_charts_from_report_data",
    "_generate_ai_executive_summary_llm",
    "_generate_ai_domain_analysis",
    "_synthesize_autonomous_insights",
    "_resolve_report_template",
    "_get_reports_dir",
    "_fetch_domain_report_data",
]
