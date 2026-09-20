# doova_one_view/api/agent/tools_refactored/reporting_v2.py
# ─────────────────────────────────────────────────────────────────────────────
# BACKWARD-COMPATIBILITY SHIM
# All reporting logic has moved to the modular `reporting/` package.
# This file re-exports the complete public API and internal tool dependencies
# so that all existing callers and unittest.mock.patch references continue working
# with 100% compatibility (zero behavioral or API breakage).
# ─────────────────────────────────────────────────────────────────────────────

from .reporting import (
    generate_report_tool,
    get_last_report_tool,
    _infer_comparison_label,
    _resolve_prior_period_dates,
    _fmt_money,
    _fmt_pct,
    _highlight_negative_numbers_html,
    _friendly_axis_formatter,
    _compute_variance,
    _build_kpi_variance,
    _render_trend_chart,
    _render_waterfall_chart,
    _render_working_capital_chart,
    _render_custom_chart_blocks,
    _sanitize_rendered_report_html,
    _get_monthly_pnl_series,
    _get_domain_trend_series,
    _normalize_report_data,
    _normalize_markdown_tables,
    _render_charts_from_report_data,
    _generate_ai_executive_summary_llm,
    _generate_ai_domain_analysis,
    _synthesize_autonomous_insights,
    _resolve_report_template,
    _get_reports_dir,
    _fetch_domain_report_data,
)

# Re-export internal tool dependencies for unittest.mock.patch compatibility
from .finance import (
    calculate_pnl_tool,
    get_business_health_score_tool,
    get_balance_sheet_tool,
    get_receivables_analysis_tool,
    get_payables_analysis_tool,
    get_aging_analysis_tool,
    get_working_capital_tool,
    get_expense_breakdown_tool,
)
from .purchasing import (
    get_purchase_summary_tool,
    get_top_vendors_tool,
    get_purchase_trend_tool,
)
from .inventory import (
    get_inventory_valuation_tool,
    get_inventory_alerts_tool,
    get_inventory_efficiency_tool,
)
from .sales import (
    get_sales_summary_tool,
    get_time_series_data_tool,
    get_top_products_tool,
)
from .common import (
    get_companies_tool,
    build_currency_case_sql,
)
from .template_registry import (
    TEMPLATE_REGISTRY,
    get_template_metadata,
)

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
    "_render_custom_chart_blocks",
    "_sanitize_rendered_report_html",
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
    # Tool re-exports
    "calculate_pnl_tool",
    "get_business_health_score_tool",
    "get_balance_sheet_tool",
    "get_receivables_analysis_tool",
    "get_payables_analysis_tool",
    "get_aging_analysis_tool",
    "get_working_capital_tool",
    "get_expense_breakdown_tool",
    "get_purchase_summary_tool",
    "get_top_vendors_tool",
    "get_purchase_trend_tool",
    "get_inventory_valuation_tool",
    "get_inventory_alerts_tool",
    "get_inventory_efficiency_tool",
    "get_sales_summary_tool",
    "get_time_series_data_tool",
    "get_top_products_tool",
    "get_companies_tool",
    "build_currency_case_sql",
    "TEMPLATE_REGISTRY",
    "get_template_metadata",
]
