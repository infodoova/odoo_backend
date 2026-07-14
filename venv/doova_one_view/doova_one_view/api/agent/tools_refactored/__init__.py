# api/agent/tools_refactored/__init__.py

from .common import get_companies_tool, get_tenant_profile_tool, calculate_ratio
from .sales import (
    get_sales_summary_tool,
    get_top_products_tool,
    get_time_series_data_tool,
    get_sales_chart_data_tool,
    analyze_variance_tool,
    forecast_sales_tool,
)
from .inventory import (
    get_inventory_alerts_tool,
    get_inventory_efficiency_tool,
)
from .finance import (
    get_receivables_analysis_tool,
    get_payables_analysis_tool,
    get_cash_flow_health_tool,
    get_business_health_score_tool,
    analyze_profitability_tool,
    calculate_pnl_tool,
    get_customer_metrics_tool,
    get_balance_sheet_tool,
    get_trial_balance_tool,
    get_financial_ratios_tool,
    get_working_capital_tool,
    get_aging_analysis_tool,
    get_expense_breakdown_tool,
    get_tax_summary_tool,
    detect_anomalies_tool,
    get_period_comparison_tool,
)
from .reporting_v2 import (
    generate_report_tool,
    get_last_report_tool,
)
from .communication import (
    send_alert_tool,
    send_email_tool,
)
