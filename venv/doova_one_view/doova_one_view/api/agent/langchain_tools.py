# api/agent/langchain_tools.py

from typing import Optional
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
    """Fallback SQL tool for any question that no other tool can answer directly.
    Describe the business intent clearly in plain English (e.g., 'total invoiced revenue by salesperson for Q2').
    Use this when: a specialized tool returns an error, data is not available in pre-built tools,
    or the user asks a highly specific ad-hoc question. ALWAYS try the specialized tools first."""
    result = run_sql_agent(user_question=question, tenant_id=tenant_id)
    return result.get("message", "Could not answer the question.")

# ── Company Discovery ────────────────────────

@tool
def list_companies(tenant_id: str):
    """List all companies for this tenant with their names and numeric IDs.
    Use this when the user mentions a company by name but you need its company_id integer
    to pass to other tools. Run this before any other tool if company_id is unknown."""
    return get_companies_tool(tenant_id=tenant_id)

@tool
def tenant_profile(tenant_id: str, company_id: Optional[int] = None):
    """Get the company's inferred business model (Product / Service / Hybrid) and currency.
    Use this FIRST on any health check, ratio analysis, or benchmark comparison — the business
    model determines which gross margin and turnover benchmarks are applicable.
    Also use when the user asks 'what kind of company is this' or 'what currency do we use'."""
    return get_tenant_profile_tool(tenant_id, company_id)

# ── Sales Domain ─────────────────────────────

@tool
def sales_summary(tenant_id: str, company_id: Optional[int] = None, start_date: str = None, end_date: str = None, base_currency: str = None):
    """Get total sales revenue
    Always pass the target base_currency. and order count for a given period.
    Always pass explicit ISO start_date and end_date (YYYY-MM-DD) when a time period is mentioned.
    Use for: revenue totals, order volume, period-specific sales snapshots.
    Prefer this over sales_trend when the user wants a single aggregate, not a time series."""
    return get_sales_summary_tool(tenant_id, company_id, start_date=start_date, end_date=end_date, base_currency=base_currency)

@tool
def top_products(tenant_id: str, company_id: Optional[int] = None, limit: int = 10, base_currency: str = None):
    """Get the top-selling products
    Always pass the target base_currency. ranked by revenue, with quantities sold.
    Use for: 'best sellers', 'top products', 'what's driving revenue', product mix analysis.
    Increase limit beyond 10 if the user asks for a broader list (e.g., top 20, top 50)."""
    return get_top_products_tool(tenant_id, company_id, limit=limit, base_currency=base_currency)

@tool
def sales_trend(tenant_id: str, company_id: Optional[int] = None, granularity: str = "month", base_currency: str = None):
    """Get sales revenue as a time series
    Always pass the target base_currency. broken down by period.
    granularity options: 'day', 'week', 'month' (default), 'quarter', 'year'.
    Use for: trend charts, growth trajectory, seasonality patterns, time series graphs.
    Prefer this over sales_summary when the user wants change over time, not a single total."""
    return get_time_series_data_tool(tenant_id, company_id, granularity, base_currency=base_currency)

@tool
def variance_analysis(tenant_id: str, company_id: Optional[int] = None, base_currency: str = None):
    """Analyze month-over-month
    Always pass the target base_currency. sales variance — absolute change and percentage swing.
    Use for: detecting revenue spikes or drops, explaining monthly performance deviations,
    identifying which months underperformed. Run after sales_summary for deep-dive context."""
    return analyze_variance_tool(tenant_id, company_id, base_currency=base_currency)

@tool
def sales_forecast(tenant_id: str, company_id: Optional[int] = None, base_currency: str = None):
    """Generate a forward-looking sales forecast based on historical trend data.
    Use for: projected revenue, future planning, budget gap analysis.
    Always pair the forecast output with variance_analysis to show the historical baseline."""
    return forecast_sales_tool(tenant_id, company_id, base_currency=base_currency)

# ── Finance Domain ───────────────────────────

@tool
def calculate_pnl(tenant_id: str, company_id: Optional[int] = None, start_date: str = None, end_date: str = None, base_currency: str = None):
    """Calculate the Profit & Loss statement for a specific period.
    Returns: Total Income, COGS, Gross Profit, Operating Expenses, Net Profit, and all margin %.
    Always pass explicit ISO start_date and end_date when a period is mentioned.
    Use for: P&L review, income statements, margin analysis, profitability by period.
    Follow with expense_breakdown and profitability_analysis for a complete income-side picture."""
    return calculate_pnl_tool(tenant_id, company_id, start_date, end_date)

@tool
def balance_sheet(tenant_id: str, company_id: Optional[int] = None, base_currency: str = None):
    """Generate the Balance Sheet: Assets, Liabilities, and Equity with an A=L+E integrity check.
    Use for: net worth assessment, leverage analysis, equity position, solvency review.
    If the integrity check fails (A ≠ L+E), immediately call detect_anomalies to investigate.
    Run alongside financial_ratios for ratio-to-balance context."""
    return get_balance_sheet_tool(tenant_id, company_id, base_currency=base_currency)

@tool
def trial_balance(tenant_id: str, company_id: Optional[int] = None, base_currency: str = None):
    """Generate the Trial Balance with account-level debit and credit totals.
    Includes an integrity check verifying total debits = total credits.
    Use for: accounting accuracy verification, ledger review, pre-audit checks.
    If the trial balance is unbalanced, call detect_anomalies immediately."""
    return get_trial_balance_tool(tenant_id, company_id, base_currency=base_currency)

@tool
def financial_ratios(tenant_id: str, company_id: Optional[int] = None, base_currency: str = None):
    """Calculate all key financial ratios: Current Ratio, Quick Ratio, Debt-to-Equity,
    ROE, ROA, Gross Margin %, and Net Margin %.
    Use for: financial health scoring, benchmark comparisons, investor-level analysis.
    Always call tenant_profile first to know the correct industry benchmarks to compare against.
    Pair with business_health for a weighted composite score."""
    return get_financial_ratios_tool(tenant_id, company_id, base_currency=base_currency)

@tool
def working_capital(tenant_id: str, company_id: Optional[int] = None, base_currency: str = None):
    """Calculate Working Capital (Current Assets minus Current Liabilities) and the WC ratio.
    Use for: short-term liquidity assessment, operational funding buffer, cash runway estimation.
    A negative working capital is a critical red flag — flag it immediately.
    Pair with cash_flow_health and aging_analysis for full liquidity context."""
    return get_working_capital_tool(tenant_id, company_id, base_currency=base_currency)

@tool
def receivables_analysis(tenant_id: str, company_id: Optional[int] = None, base_currency: str = None):
    """Analyze Accounts Receivable: total outstanding, overdue balance, and top overdue customers.
    Use for: collections health overview, credit risk summary, DSO context.
    Prefer aging_analysis when you need bucket distribution (30/60/90 day breakdown).
    Use this for high-level AR totals; use aging_analysis for detailed overdue structure."""
    return get_receivables_analysis_tool(tenant_id, company_id, base_currency=base_currency)

@tool
def payables_analysis(tenant_id: str, company_id: Optional[int] = None, base_currency: str = None):
    """Analyze Accounts Payable: total outstanding, overdue balance, and top overdue vendors.
    Use for: supplier payment risk, DPO context, cash outflow exposure.
    Prefer aging_analysis(direction='payable') when you need bucket-level overdue breakdown.
    Use this for high-level AP totals; use aging_analysis for detailed overdue structure."""
    return get_payables_analysis_tool(tenant_id, company_id, base_currency=base_currency)

@tool
def aging_analysis(tenant_id: str, company_id: Optional[int] = None, direction: str = "receivable", base_currency: str = None):
    """Get AR or AP aging bucket distribution: Current, 1–30, 31–60, 61–90, and 90+ days overdue.
    direction='receivable' for customer AR aging (default).
    direction='payable' for supplier AP aging.
    Use for: overdue collections risk, vendor payment stress, aging-based cash flow projections.
    Prefer this over receivables_analysis/payables_analysis when you need the bucket breakdown,
    not just totals. Critical for identifying if overdue concentration is in the 90+ bucket."""
    return get_aging_analysis_tool(tenant_id, company_id, direction, base_currency=base_currency)

@tool
def cash_flow_health(tenant_id: str, company_id: Optional[int] = None, base_currency: str = None):
    """Assess overall cash flow and liquidity health using real AR and AP balances.
    Returns: net cash position, burn rate indicators, and liquidity stress signals.
    Use for: cash runway assessment, liquidity crisis detection, short-term solvency.
    Run first in any liquidity investigation before diving into working_capital or aging."""
    return get_cash_flow_health_tool(tenant_id, company_id, base_currency=base_currency)

@tool
def business_health(tenant_id: str, company_id: Optional[int] = None, base_currency: str = None):
    """Calculate the composite weighted business health score (0–100) across four dimensions:
    Profitability, Liquidity, Leverage, and Collections efficiency.
    Use for: executive health dashboards, overall company performance scoring, board summaries.
    Always run financial_ratios before this to have the underlying ratio context available."""
    return get_business_health_score_tool(tenant_id, company_id, base_currency=base_currency)

@tool
def profitability_analysis(tenant_id: str, company_id: Optional[int] = None, base_currency: str = None):
    """Analyze gross margin and net margin with exact percentage calculations.
    Use for: margin compression detection, profitability trend context, cost structure review.
    Best run after calculate_pnl to contextualize which cost lines are driving margin changes."""
    return analyze_profitability_tool(tenant_id, company_id)

@tool
def customer_metrics(tenant_id: str, company_id: Optional[int] = None, base_currency: str = None):
    """Get customer retention rate, churn risk score, and top customers ranked by revenue.
    Use for: customer concentration risk, revenue dependency analysis, churn early warning.
    If top-3 customers represent >50% of revenue, flag as high concentration risk.
    Follow with receivables_analysis and aging_analysis(receivable) to check their payment behavior."""
    return get_customer_metrics_tool(tenant_id, company_id, base_currency=base_currency)

@tool
def expense_breakdown(tenant_id: str, company_id: Optional[int] = None, start_date: str = None, end_date: str = None, base_currency: str = None):
    """Get a detailed expense breakdown by category with each category's % of total spend.
    Always pass explicit ISO start_date and end_date when a period is mentioned.
    Use for: cost structure analysis, budget overrun investigation, opex vs capex split,
    identifying the largest expense drivers. Pair with calculate_pnl for full P&L context."""
    return get_expense_breakdown_tool(tenant_id, company_id, start_date, end_date, base_currency=base_currency)

@tool
def tax_summary(tenant_id: str, company_id: Optional[int] = None, base_currency: str = None):
    """Calculate net tax position: Output Tax (collected from customers) minus Input Tax (paid to vendors).
    Returns net VAT/tax payable or reclaimable.
    Use for: tax liability assessment, VAT filing preparation, tax health review.
    Follow with expense_breakdown to verify deductible expense categories supporting input tax claims."""
    return get_tax_summary_tool(tenant_id, company_id, base_currency=base_currency)

@tool
def detect_anomalies(tenant_id: str, company_id: Optional[int] = None):
    """Audit tool: detect unbalanced journal entries and statistically unusual transactions (>3σ from mean).
    Use for: fraud indicators, data integrity checks, unexplained spikes, audit preparation.
    Always call this when: trial_balance is unbalanced, balance sheet A≠L+E, or a tool returns
    contradictory data. Also run proactively as part of any full audit sequence."""
    return detect_anomalies_tool(tenant_id, company_id)

@tool
def period_comparison(tenant_id: str, company_id: Optional[int] = None, granularity: str = "month", base_currency: str = None):
    """Compare revenue and order counts across consecutive periods with % change calculations.
    granularity options: 'month' (default), 'quarter', 'year'.
    Use for: MoM / QoQ / YoY comparisons, growth rate analysis, identifying peak periods.
    Prefer this over sales_trend when the user wants relative change %, not raw time series values."""
    return get_period_comparison_tool(tenant_id, company_id, granularity, base_currency=base_currency)

# ── Inventory Domain ─────────────────────────

@tool
def inventory_alerts(tenant_id: str, company_id: Optional[int] = None):
    """Get critical inventory alerts: low-stock items below reorder threshold and expiring lots.
    Use for: stockout risk prevention, lot expiry management, procurement urgency flags.
    Always follow with inventory_efficiency to understand if slow turnover is causing the low stock."""
    return get_inventory_alerts_tool(tenant_id, company_id)

@tool
def inventory_efficiency(tenant_id: str, company_id: Optional[int] = None):
    """Analyze inventory turnover rate and days-on-hand metrics per product category.
    Use for: dead stock identification, overstocking risk, working capital tied up in inventory.
    Compare turnover against benchmarks: >8x/yr excellent, 5–8x good, <2x stagnant/dead stock.
    Run alongside inventory_alerts for a complete inventory health picture."""
    return get_inventory_efficiency_tool(tenant_id, company_id)

# ── Reporting Domain ─────────────────────────

@tool
def create_report(tenant_id: str, custom_content: str, company_id: Optional[int] = None):
    """MANDATORY: When the user asks to 'generate a report' or 'create a report', you MUST call this tool.
    Generate a professional branded PDF executive report including vital signs and your analysis.
    You MUST pass your full markdown report analysis into the `custom_content` parameter. This parameter is REQUIRED.
    Do NOT output the report directly in the chat text. Pass it ALL into `custom_content`.
    Do NOT call this before you have gathered the data — the report cannot be regenerated mid-session."""
    
    # Generate the report. If custom_content is missing, it will use the default automated summary.
    result = generate_report_tool(tenant_id, custom_content=custom_content, company_id=company_id)
    url = result.get("download_url", "")
    
    # Return a loud, explicit string to Claude so it stops looping and responds to the user!
    return (
        f"SUCCESS! The report has been successfully generated and saved.\n"
        f"Download URL: {url}\n\n"
        f"CRITICAL INSTRUCTION: You must now STOP calling tools. Do NOT call create_report again. "
        f"Output your final response to the user containing this download link."
    )

@tool
def get_latest_report(tenant_id: str, company_id: Optional[int] = None):
    """Retrieve the download URL for the most recently generated PDF report for this tenant.
    Use when the user asks 'give me the report', 'download the last report', or 'send me the PDF'.
    If no report exists, suggest calling create_report first."""
    return get_last_report_tool(tenant_id, company_id)

# ── Communication Domain ─────────────────────

@tool
def send_alert(tenant_id: str, title: str, message: str, company_id: Optional[int] = None):
    """Send a real-time notification alert to the user's dashboard.
    Use when the user asks to be notified, or when a critical risk (e.g., overdue AR >30%, liquidity critical)
    warrants immediate dashboard notification. title should be ≤10 words; message should be ≤2 sentences."""
    return send_alert_tool(tenant_id, title, message, company_id=company_id)

@tool
def send_email(tenant_id: str, to_email: str, subject: str, body: str, company_id: Optional[int] = None):
    """Prepare and queue an email to a specified recipient.
    Use only when the user explicitly requests an email to be sent — never send without clear instruction.
    body should be professional, concise, and include the key findings from your analysis."""
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
