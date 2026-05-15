# api/agent/langchain_tools.py

from langchain_core.tools import tool
from .sql_agent import run_sql_agent
from .tools_refactored import (
    get_sales_summary_tool,
    get_top_products_tool,
    get_time_series_data_tool,
    get_sales_chart_data_tool,
    analyze_variance_tool,
    forecast_sales_tool,
    get_inventory_alerts_tool,
    get_inventory_efficiency_tool,
    get_receivables_analysis_tool,
    get_payables_analysis_tool,
    get_cash_flow_health_tool,
    get_business_health_score_tool,
    analyze_profitability_tool,
    get_customer_metrics_tool,
    get_balance_sheet_tool,
    get_trial_balance_tool,
    get_financial_ratios_tool,
    get_working_capital_tool,
    get_aging_analysis_tool,
    calculate_pnl_tool,
    get_expense_breakdown_tool,
    get_tax_summary_tool,
    detect_anomalies_tool,
    get_period_comparison_tool,
    generate_report_tool,
    get_last_report_tool,
    send_alert_tool,
    send_email_tool,
    get_companies_tool,
    get_tenant_profile_tool,
)

# ── SQL Fallback ─────────────────────────────

@tool
def ask_database_custom_question(tenant_id: str, question: str):
    """Fallback tool for custom database questions that other tools cannot answer."""
    result = run_sql_agent(user_question=question, tenant_id=tenant_id)
    return result.get("message", "Could not answer the question.")

# ── Company Discovery ────────────────────────

@tool
def list_companies(tenant_id: str):
    """List all companies associated with this tenant, including their names and IDs.
    Use this if the user mentions a company by name but you need its ID."""
    return get_companies_tool(tenant_id=tenant_id)

@tool
def tenant_profile(tenant_id: str, company_id: int = None):
    """Get the company's industry, business model (Product/Service/Hybrid), and currency.
    Use this FIRST when you need industry context to interpret financial benchmarks correctly."""
    return get_tenant_profile_tool(tenant_id, company_id)

# ── Sales Domain ─────────────────────────────

@tool
def sales_summary(tenant_id: str, company_id: int = None, start_date: str = None, end_date: str = None):
    """Get a summary of sales revenue and order counts."""
    return get_sales_summary_tool(tenant_id, company_id, start_date=start_date, end_date=end_date)

@tool
def top_products(tenant_id: str, company_id: int = None, limit: int = 10):
    """Get the top-selling products by revenue."""
    return get_top_products_tool(tenant_id, company_id, limit=limit)

@tool
def sales_trend(tenant_id: str, company_id: int = None, granularity: str = "month"):
    """Get sales revenue trend data over time."""
    return get_time_series_data_tool(tenant_id, company_id, granularity)

@tool
def variance_analysis(tenant_id: str, company_id: int = None):
    """Analyze month-over-month sales variance."""
    return analyze_variance_tool(tenant_id, company_id)

@tool
def sales_forecast(tenant_id: str, company_id: int = None):
    """Get a future sales forecast based on historical data."""
    return forecast_sales_tool(tenant_id, company_id)

# ── Finance Domain ───────────────────────────

@tool
def calculate_pnl(tenant_id: str, company_id: int = None, start_date: str = None, end_date: str = None):
    """Calculate the Profit and Loss (PnL) for a specific period.
    Returns Total Income, Total Expenses, COGS, Gross Profit, Net Profit, and margin percentages."""
    return calculate_pnl_tool(tenant_id, company_id, start_date, end_date)

@tool
def balance_sheet(tenant_id: str, company_id: int = None):
    """Generate a Balance Sheet showing Assets, Liabilities, and Equity.
    Includes an integrity check verifying Assets = Liabilities + Equity."""
    return get_balance_sheet_tool(tenant_id, company_id)

@tool
def trial_balance(tenant_id: str, company_id: int = None):
    """Generate a Trial Balance with account-level debit/credit breakdown.
    Includes integrity check verifying total debits equal total credits."""
    return get_trial_balance_tool(tenant_id, company_id)

@tool
def financial_ratios(tenant_id: str, company_id: int = None):
    """Calculate key financial ratios: Current Ratio, Quick Ratio, Debt-to-Equity,
    Return on Equity (ROE), Return on Assets (ROA), and margin percentages."""
    return get_financial_ratios_tool(tenant_id, company_id)

@tool
def working_capital(tenant_id: str, company_id: int = None):
    """Calculate Working Capital (Current Assets - Current Liabilities) and its ratio."""
    return get_working_capital_tool(tenant_id, company_id)

@tool
def receivables_analysis(tenant_id: str, company_id: int = None):
    """Analyze accounts receivable: total outstanding, overdue amounts, and top overdue customers."""
    return get_receivables_analysis_tool(tenant_id, company_id)

@tool
def payables_analysis(tenant_id: str, company_id: int = None):
    """Analyze accounts payable: total outstanding, overdue amounts, and top overdue vendors."""
    return get_payables_analysis_tool(tenant_id, company_id)

@tool
def aging_analysis(tenant_id: str, company_id: int = None, direction: str = "receivable"):
    """Get AR or AP aging buckets (Current, 1-30, 31-60, 61-90, 90+ days).
    Set direction='receivable' for AR aging or direction='payable' for AP aging."""
    return get_aging_analysis_tool(tenant_id, company_id, direction)

@tool
def cash_flow_health(tenant_id: str, company_id: int = None):
    """Check the overall cash flow and liquidity status using real AR and AP data."""
    return get_cash_flow_health_tool(tenant_id, company_id)

@tool
def business_health(tenant_id: str, company_id: int = None):
    """Calculate the weighted business health score based on Profitability, Liquidity, Leverage, and Collections."""
    return get_business_health_score_tool(tenant_id, company_id)

@tool
def profitability_analysis(tenant_id: str, company_id: int = None):
    """Analyze gross and net profit margins with percentage calculations."""
    return analyze_profitability_tool(tenant_id, company_id)

@tool
def customer_metrics(tenant_id: str, company_id: int = None):
    """Get customer retention rate, churn risk, and top customers by revenue."""
    return get_customer_metrics_tool(tenant_id, company_id)

@tool
def expense_breakdown(tenant_id: str, company_id: int = None, start_date: str = None, end_date: str = None):
    """Get a detailed breakdown of expenses by category with percentage of total."""
    return get_expense_breakdown_tool(tenant_id, company_id, start_date, end_date)

@tool
def tax_summary(tenant_id: str, company_id: int = None):
    """Calculate tax liability: Output Tax collected minus Input Tax paid. Shows net VAT/Tax position."""
    return get_tax_summary_tool(tenant_id, company_id)

@tool
def detect_anomalies(tenant_id: str, company_id: int = None):
    """Audit tool: Detect unbalanced journal entries and statistically unusual transactions (>3σ from mean)."""
    return detect_anomalies_tool(tenant_id, company_id)

@tool
def period_comparison(tenant_id: str, company_id: int = None, granularity: str = "month"):
    """Compare revenue and order counts across periods (month/quarter/year) with change percentages."""
    return get_period_comparison_tool(tenant_id, company_id, granularity)

# ── Inventory Domain ─────────────────────────

@tool
def inventory_alerts(tenant_id: str, company_id: int = None):
    """Get alerts for low stock items and expiring lots."""
    return get_inventory_alerts_tool(tenant_id, company_id)

@tool
def inventory_efficiency(tenant_id: str, company_id: int = None):
    """Analyze inventory turnover and days on hand."""
    return get_inventory_efficiency_tool(tenant_id, company_id)

# ── Reporting Domain ─────────────────────────

@tool
def create_report(tenant_id: str, custom_content: str, company_id: int = None):
    """Generate a professional PDF business summary report.
    The 'custom_content' should be a professional executive summary of your findings and recommendations."""
    return generate_report_tool(tenant_id, company_id, custom_content=custom_content)

@tool
def get_latest_report(tenant_id: str, company_id: int = None):
    """Get the download link for the most recent report."""
    return get_last_report_tool(tenant_id, company_id)

# ── Communication Domain ─────────────────────

@tool
def send_alert(tenant_id: str, title: str, message: str, company_id: int = None):
    """Send a notification alert to the dashboard."""
    return send_alert_tool(tenant_id, title, message, company_id=company_id)

@tool
def send_email(tenant_id: str, to_email: str, subject: str, body: str, company_id: int = None):
    """Prepare an email to be sent to a user."""
    return send_email_tool(tenant_id, to_email, subject, body, company_id=company_id)

# ── Consolidated Agent Tools ─────────────────

agent_tools = [
    # Discovery
    ask_database_custom_question, list_companies, tenant_profile,
    # Sales
    sales_summary, top_products, sales_trend, variance_analysis, sales_forecast,
    # Finance — Core Statements
    calculate_pnl, balance_sheet, trial_balance,
    # Finance — Analysis
    financial_ratios, working_capital, profitability_analysis, expense_breakdown,
    # Finance — AR/AP & Cash
    receivables_analysis, payables_analysis, aging_analysis, cash_flow_health,
    # Finance — Tax & Audit
    tax_summary, detect_anomalies,
    # Finance — Intelligence
    period_comparison, business_health, customer_metrics,
    # Inventory
    inventory_alerts, inventory_efficiency,
    # Reporting & Communication
    create_report, get_latest_report, send_alert, send_email,
]
