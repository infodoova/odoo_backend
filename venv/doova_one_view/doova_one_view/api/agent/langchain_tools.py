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
    get_inventory_stock_table_tool,
    get_inventory_dashboard_alerts_tool,
    get_inventory_valuation_tool,
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
    get_bank_cash_summary_tool,
    get_journal_cards_tool,
    get_bank_statement_summary_tool,
    get_companies_tool,
    get_tenant_profile_tool,
    get_purchase_summary_tool,
    get_top_vendors_tool,
    get_vendor_performance_tool,
    get_procurement_category_breakdown_tool,
    get_purchase_vs_sales_margin_tool,
    get_po_fulfillment_tool,
    get_purchase_trend_tool,
    get_cash_flow_statement_tool,
    get_working_capital_efficiency_tool,
    get_period_comparison_pnl_tool,
    get_interest_coverage_tool,
    get_revenue_segmentation_tool,
    get_payment_reconciliation_tool,
    get_salesperson_performance_tool,
    get_sales_pipeline_tool,
    get_discount_leakage_tool,
    get_customer_lifetime_value_tool,
    get_order_to_cash_cycle_tool,
    get_revenue_by_category_tool,
)

# ── SQL Fallback ─────────────────────────────

@tool
def ask_database_custom_question(tenant_id: Optional[str], question: str, tenant_ids: Optional[list[str]] = None):
    """Fallback SQL tool for any question that no other tool can answer directly.
    Describe the business intent clearly in plain English (e.g., 'total invoiced revenue by salesperson for Q2').
    Use this when: a specialized tool returns an error, data is not available in pre-built tools,
    or the user asks a highly specific ad-hoc question. ALWAYS try the specialized tools first."""
    result = run_sql_agent(user_question=question, tenant_id=tenant_id, tenant_ids=tenant_ids)
    return result.get("message", "Could not answer the question.")

# ── Company Discovery ────────────────────────

@tool
def list_companies(tenant_id: Optional[str], tenant_ids: Optional[list[str]] = None):
    """List all companies for this tenant with their names and numeric IDs.
    Use this when the user mentions a company by name but you need its company_id integer
    to pass to other tools. Run this before any other tool if company_id is unknown."""
    return get_companies_tool(tenant_id=tenant_id, tenant_ids=tenant_ids)

@tool
def tenant_profile(tenant_id: Optional[str], company_id: Optional[int] = None, company_ids: Optional[list[int]] = None, tenant_ids: Optional[list[str]] = None):
    """Get the company's inferred business model (Product / Service / Hybrid) and currency.
    Use this FIRST on any health check, ratio analysis, or benchmark comparison — the business
    model determines which gross margin and turnover benchmarks are applicable.
    Also use when the user asks 'what kind of company is this' or 'what currency do we use'."""
    return get_tenant_profile_tool(tenant_id=tenant_id, tenant_ids=tenant_ids, company_id=company_id, company_ids=company_ids)

# ── Sales Domain ─────────────────────────────

@tool
def sales_summary(tenant_id: Optional[str], company_id: Optional[int] = None, company_ids: Optional[list[int]] = None, start_date: str = None, end_date: str = None, base_currency: str = None, tenant_ids: Optional[list[str]] = None):
    """Get total sales revenue
    Always pass the target base_currency. and order count for a given period.
    Always pass explicit ISO start_date and end_date (YYYY-MM-DD) when a time period is mentioned.
    Use for: revenue totals, order volume, period-specific sales snapshots.
    Prefer this over sales_trend when the user wants a single aggregate, not a time series."""
    return get_sales_summary_tool(tenant_id=tenant_id, tenant_ids=tenant_ids, company_id=company_id, company_ids=company_ids, start_date=start_date, end_date=end_date, base_currency=base_currency)

@tool
def top_products(tenant_id: Optional[str], company_id: Optional[int] = None, company_ids: Optional[list[int]] = None, limit: int = 10, base_currency: str = None, tenant_ids: Optional[list[str]] = None):
    """Get the top-selling products
    Always pass the target base_currency. ranked by revenue, with quantities sold.
    Use for: 'best sellers', 'top products', 'what's driving revenue', product mix analysis.
    Increase limit beyond 10 if the user asks for a broader list (e.g., top 20, top 50)."""
    return get_top_products_tool(tenant_id=tenant_id, tenant_ids=tenant_ids, company_id=company_id, company_ids=company_ids, limit=limit, base_currency=base_currency)

@tool
def sales_trend(tenant_id: Optional[str], company_id: Optional[int] = None, company_ids: Optional[list[int]] = None, granularity: str = "month", base_currency: str = None, tenant_ids: Optional[list[str]] = None):
    """Get sales revenue as a time series
    Always pass the target base_currency. broken down by period.
    granularity options: 'day', 'week', 'month' (default), 'quarter', 'year'.
    Use for: trend charts, growth trajectory, seasonality patterns, time series graphs.
    Prefer this over sales_summary when the user wants change over time, not a single total."""
    return get_time_series_data_tool(tenant_id=tenant_id, tenant_ids=tenant_ids, company_id=company_id, company_ids=company_ids, granularity=granularity, base_currency=base_currency)

@tool
def variance_analysis(tenant_id: Optional[str], company_id: Optional[int] = None, company_ids: Optional[list[int]] = None, base_currency: str = None, tenant_ids: Optional[list[str]] = None):
    """Analyze month-over-month
    Always pass the target base_currency. sales variance — absolute change and percentage swing.
    Use for: detecting revenue spikes or drops, explaining monthly performance deviations,
    identifying which months underperformed. Run after sales_summary for deep-dive context."""
    return analyze_variance_tool(tenant_id=tenant_id, tenant_ids=tenant_ids, company_id=company_id, company_ids=company_ids, base_currency=base_currency)

@tool
def sales_forecast(tenant_id: Optional[str], company_id: Optional[int] = None, company_ids: Optional[list[int]] = None, base_currency: str = None, tenant_ids: Optional[list[str]] = None):
    """Generate a forward-looking sales forecast based on historical trend data.
    Use for: projected revenue, future planning, budget gap analysis.
    Always pair the forecast output with variance_analysis to show the historical baseline."""
    return forecast_sales_tool(tenant_id=tenant_id, tenant_ids=tenant_ids, company_id=company_id, company_ids=company_ids, base_currency=base_currency)

@tool
def salesperson_performance(tenant_id: Optional[str], company_id: Optional[int] = None, company_ids: Optional[list[int]] = None, start_date: str = None, end_date: str = None, base_currency: str = None, tenant_ids: Optional[list[str]] = None):
    """Rank sales representatives by total revenue, order count, and margin.
    Use for: 'who is our best salesperson?', 'sales team performance review',
    'revenue by user', 'sales rep commissions'."""
    return get_salesperson_performance_tool(tenant_id=tenant_id, tenant_ids=tenant_ids, company_id=company_id, company_ids=company_ids, start_date=start_date, end_date=end_date, base_currency=base_currency)

@tool
def sales_pipeline(tenant_id: Optional[str], company_id: Optional[int] = None, company_ids: Optional[list[int]] = None, start_date: str = None, end_date: str = None, base_currency: str = None, tenant_ids: Optional[list[str]] = None):
    """Analyze the sales pipeline by counting open quotes vs won orders and calculating conversion rates.
    Use for: 'how is our pipeline?', 'what is our close rate?', 'open quotations value'."""
    return get_sales_pipeline_tool(tenant_id=tenant_id, tenant_ids=tenant_ids, company_id=company_id, company_ids=company_ids, start_date=start_date, end_date=end_date, base_currency=base_currency)

@tool
def discount_leakage(tenant_id: Optional[str], company_id: Optional[int] = None, company_ids: Optional[list[int]] = None, start_date: str = None, end_date: str = None, base_currency: str = None, tenant_ids: Optional[list[str]] = None):
    """Identify margin leakage through explicit discounts on sales orders.
    Use for: 'are we discounting too much?', 'margin leakage', 'top discounted products'."""
    return get_discount_leakage_tool(tenant_id=tenant_id, tenant_ids=tenant_ids, company_id=company_id, company_ids=company_ids, start_date=start_date, end_date=end_date, base_currency=base_currency)

@tool
def customer_lifetime_value(tenant_id: Optional[str], company_id: Optional[int] = None, company_ids: Optional[list[int]] = None, base_currency: str = None, tenant_ids: Optional[list[str]] = None):
    """Calculate the lifetime value (CLV) of top customers and group them into tiers (Platinum, Gold, Silver, Bronze).
    Use for: 'who are our most valuable customers?', 'CLV analysis', 'top clients by lifetime revenue'."""
    return get_customer_lifetime_value_tool(tenant_id=tenant_id, tenant_ids=tenant_ids, company_id=company_id, company_ids=company_ids, base_currency=base_currency)

@tool
def order_to_cash_cycle(tenant_id: Optional[str], company_id: Optional[int] = None, company_ids: Optional[list[int]] = None, start_date: str = None, end_date: str = None, base_currency: str = None, tenant_ids: Optional[list[str]] = None):
    """Measure the Order-to-Cash (O2C) cycle by calculating the average days between sales order confirmation and invoicing.
    Use for: 'how long does it take to get paid?', 'O2C cycle time', 'order to invoice speed'."""
    return get_order_to_cash_cycle_tool(tenant_id=tenant_id, tenant_ids=tenant_ids, company_id=company_id, company_ids=company_ids, start_date=start_date, end_date=end_date, base_currency=base_currency)

@tool
def revenue_by_category(tenant_id: Optional[str], company_id: Optional[int] = None, company_ids: Optional[list[int]] = None, start_date: str = None, end_date: str = None, base_currency: str = None, tenant_ids: Optional[list[str]] = None):
    """Break down total sales revenue by product category hierarchy.
    Use for: 'which product categories drive our revenue?', 'sales by category'."""
    return get_revenue_by_category_tool(tenant_id=tenant_id, tenant_ids=tenant_ids, company_id=company_id, company_ids=company_ids, start_date=start_date, end_date=end_date, base_currency=base_currency)

# ── Finance Domain ───────────────────────────

@tool
def calculate_pnl(tenant_id: Optional[str], company_id: Optional[int] = None, company_ids: Optional[list[int]] = None, start_date: str = None, end_date: str = None, base_currency: str = None, tenant_ids: Optional[list[str]] = None):
    """Calculate the Profit & Loss statement for a specific period.
    Returns: Total Income, COGS, Gross Profit, Operating Expenses, Net Profit, and all margin %.
    Always pass explicit ISO start_date and end_date when a period is mentioned.
    Use for: P&L review, income statements, margin analysis, profitability by period.
    Follow with expense_breakdown and profitability_analysis for a complete income-side picture."""
    return calculate_pnl_tool(tenant_id=tenant_id, tenant_ids=tenant_ids, company_id=company_id, company_ids=company_ids, start_date=start_date, end_date=end_date, base_currency=base_currency)

@tool
def balance_sheet(tenant_id: Optional[str], company_id: Optional[int] = None, company_ids: Optional[list[int]] = None, base_currency: str = None, tenant_ids: Optional[list[str]] = None):
    """Generate the Balance Sheet: Assets, Liabilities, and Equity with an A=L+E integrity check.
    Use for: net worth assessment, leverage analysis, equity position, solvency review.
    If the integrity check fails (A ≠ L+E), immediately call detect_anomalies to investigate.
    Run alongside financial_ratios for ratio-to-balance context."""
    return get_balance_sheet_tool(tenant_id=tenant_id, tenant_ids=tenant_ids, company_id=company_id, company_ids=company_ids, base_currency=base_currency)

@tool
def trial_balance(tenant_id: Optional[str], company_id: Optional[int] = None, company_ids: Optional[list[int]] = None, base_currency: str = None, tenant_ids: Optional[list[str]] = None):
    """Generate the Trial Balance with account-level debit and credit totals.
    Includes an integrity check verifying total debits = total credits.
    Use for: accounting accuracy verification, ledger review, pre-audit checks.
    If the trial balance is unbalanced, call detect_anomalies immediately."""
    return get_trial_balance_tool(tenant_id=tenant_id, tenant_ids=tenant_ids, company_id=company_id, company_ids=company_ids, base_currency=base_currency)

@tool
def financial_ratios(tenant_id: Optional[str], company_id: Optional[int] = None, company_ids: Optional[list[int]] = None, base_currency: str = None, tenant_ids: Optional[list[str]] = None):
    """Calculate all key financial ratios: Current Ratio, Quick Ratio, Debt-to-Equity,
    ROE, ROA, Gross Margin %, and Net Margin %.
    Use for: financial health scoring, benchmark comparisons, investor-level analysis.
    Always call tenant_profile first to know the correct industry benchmarks to compare against.
    Pair with business_health for a weighted composite score."""
    return get_financial_ratios_tool(tenant_id=tenant_id, tenant_ids=tenant_ids, company_id=company_id, company_ids=company_ids, base_currency=base_currency)

@tool
def working_capital(tenant_id: Optional[str], company_id: Optional[int] = None, company_ids: Optional[list[int]] = None, base_currency: str = None, tenant_ids: Optional[list[str]] = None):
    """Calculate Working Capital (Current Assets minus Current Liabilities) and the WC ratio.
    Use for: short-term liquidity assessment, operational funding buffer, cash runway estimation.
    A negative working capital is a critical red flag — flag it immediately.
    Pair with cash_flow_health and aging_analysis for full liquidity context."""
    return get_working_capital_tool(tenant_id=tenant_id, tenant_ids=tenant_ids, company_id=company_id, company_ids=company_ids, base_currency=base_currency)

@tool
def receivables_analysis(tenant_id: Optional[str], company_id: Optional[int] = None, company_ids: Optional[list[int]] = None, base_currency: str = None, tenant_ids: Optional[list[str]] = None):
    """Analyze Accounts Receivable: total outstanding, overdue balance, and top overdue customers.
    Use for: collections health overview, credit risk summary, DSO context.
    Prefer aging_analysis when you need bucket distribution (30/60/90 day breakdown).
    Use this for high-level AR totals; use aging_analysis for detailed overdue structure."""
    return get_receivables_analysis_tool(tenant_id=tenant_id, tenant_ids=tenant_ids, company_id=company_id, company_ids=company_ids, base_currency=base_currency)

@tool
def payables_analysis(tenant_id: Optional[str], company_id: Optional[int] = None, company_ids: Optional[list[int]] = None, base_currency: str = None, tenant_ids: Optional[list[str]] = None):
    """Analyze Accounts Payable: total outstanding, overdue balance, and top overdue vendors.
    Use for: supplier payment risk, DPO context, cash outflow exposure.
    Prefer aging_analysis(direction='payable') when you need bucket-level overdue breakdown.
    Use this for high-level AP totals; use aging_analysis for detailed overdue structure."""
    return get_payables_analysis_tool(tenant_id=tenant_id, tenant_ids=tenant_ids, company_id=company_id, company_ids=company_ids, base_currency=base_currency)

@tool
def aging_analysis(tenant_id: Optional[str], company_id: Optional[int] = None, company_ids: Optional[list[int]] = None, direction: str = "receivable", base_currency: str = None, tenant_ids: Optional[list[str]] = None):
    """Get AR or AP aging bucket distribution: Current, 1–30, 31–60, 61–90, and 90+ days overdue.
    direction='receivable' for customer AR aging (default).
    direction='payable' for supplier AP aging.
    Use for: overdue collections risk, vendor payment stress, aging-based cash flow projections.
    Prefer this over receivables_analysis/payables_analysis when you need the bucket breakdown,
    not just totals. Critical for identifying if overdue concentration is in the 90+ bucket."""
    return get_aging_analysis_tool(tenant_id=tenant_id, tenant_ids=tenant_ids, company_id=company_id, company_ids=company_ids, direction=direction, base_currency=base_currency)

@tool
def cash_flow_health(tenant_id: Optional[str], company_id: Optional[int] = None, company_ids: Optional[list[int]] = None, base_currency: str = None, tenant_ids: Optional[list[str]] = None):
    """Assess overall cash flow and liquidity health using real AR and AP balances.
    Returns: net cash position, burn rate indicators, and liquidity stress signals.
    Use for: cash runway assessment, liquidity crisis detection, short-term solvency.
    Run first in any liquidity investigation before diving into working_capital or aging."""
    return get_cash_flow_health_tool(tenant_id=tenant_id, tenant_ids=tenant_ids, company_id=company_id, company_ids=company_ids, base_currency=base_currency)

@tool
def business_health(tenant_id: Optional[str], company_id: Optional[int] = None, company_ids: Optional[list[int]] = None, base_currency: str = None, tenant_ids: Optional[list[str]] = None):
    """Calculate the composite weighted business health score (0–100) across four dimensions:
    Profitability, Liquidity, Leverage, and Collections efficiency.
    Use for: executive health dashboards, overall company performance scoring, board summaries.
    Always run financial_ratios before this to have the underlying ratio context available."""
    return get_business_health_score_tool(tenant_id=tenant_id, tenant_ids=tenant_ids, company_id=company_id, company_ids=company_ids, base_currency=base_currency)

@tool
def profitability_analysis(tenant_id: Optional[str], company_id: Optional[int] = None, company_ids: Optional[list[int]] = None, base_currency: str = None, tenant_ids: Optional[list[str]] = None):
    """Analyze gross margin and net margin with exact percentage calculations.
    Use for: margin compression detection, profitability trend context, cost structure review.
    Best run after calculate_pnl to contextualize which cost lines are driving margin changes."""
    return analyze_profitability_tool(tenant_id=tenant_id, tenant_ids=tenant_ids, company_id=company_id, company_ids=company_ids)

@tool
def customer_metrics(tenant_id: Optional[str], company_id: Optional[int] = None, company_ids: Optional[list[int]] = None, base_currency: str = None, tenant_ids: Optional[list[str]] = None):
    """Get customer retention rate, churn risk score, and top customers ranked by revenue.
    Use for: customer concentration risk, revenue dependency analysis, churn early warning.
    If top-3 customers represent >50% of revenue, flag as high concentration risk.
    Follow with receivables_analysis and aging_analysis(receivable) to check their payment behavior."""
    return get_customer_metrics_tool(tenant_id=tenant_id, tenant_ids=tenant_ids, company_id=company_id, company_ids=company_ids, base_currency=base_currency)

@tool
def expense_breakdown(tenant_id: Optional[str], company_id: Optional[int] = None, company_ids: Optional[list[int]] = None, start_date: str = None, end_date: str = None, base_currency: str = None, tenant_ids: Optional[list[str]] = None):
    """Get a detailed expense breakdown by category with each category's % of total spend.
    Always pass explicit ISO start_date and end_date when a period is mentioned.
    Use for: cost structure analysis, budget overrun investigation, opex vs capex split,
    identifying the largest expense drivers. Pair with calculate_pnl for full P&L context."""
    return get_expense_breakdown_tool(tenant_id=tenant_id, tenant_ids=tenant_ids, company_id=company_id, company_ids=company_ids, start_date=start_date, end_date=end_date, base_currency=base_currency)

@tool
def tax_summary(tenant_id: Optional[str], company_id: Optional[int] = None, company_ids: Optional[list[int]] = None, base_currency: str = None, tenant_ids: Optional[list[str]] = None):
    """Calculate net tax position: Output Tax (collected from customers) minus Input Tax (paid to vendors).
    Returns net VAT/tax payable or reclaimable.
    Use for: tax liability assessment, VAT filing preparation, tax health review.
    Follow with expense_breakdown to verify deductible expense categories supporting input tax claims."""
    return get_tax_summary_tool(tenant_id=tenant_id, tenant_ids=tenant_ids, company_id=company_id, company_ids=company_ids, base_currency=base_currency)

@tool
def detect_anomalies(tenant_id: Optional[str], company_id: Optional[int] = None, company_ids: Optional[list[int]] = None, tenant_ids: Optional[list[str]] = None):
    """Audit tool: detect unbalanced journal entries and statistically unusual transactions (>3σ from mean).
    Use for: fraud indicators, data integrity checks, unexplained spikes, audit preparation.
    Always call this when: trial_balance is unbalanced, balance sheet A≠L+E, or a tool returns
    contradictory data. Also run proactively as part of any full audit sequence."""
    return detect_anomalies_tool(tenant_id=tenant_id, tenant_ids=tenant_ids, company_id=company_id, company_ids=company_ids)

@tool
def period_comparison(tenant_id: Optional[str], company_id: Optional[int] = None, company_ids: Optional[list[int]] = None, granularity: str = "month", base_currency: str = None, tenant_ids: Optional[list[str]] = None):
    """Compare revenue and order counts across consecutive periods with % change calculations.
    granularity options: 'month' (default), 'quarter', 'year'.
    Use for: MoM / QoQ / YoY comparisons, growth rate analysis, identifying peak periods.
    Prefer this over sales_trend when the user wants relative change %, not raw time series values."""
    return get_period_comparison_tool(tenant_id=tenant_id, tenant_ids=tenant_ids, company_id=company_id, company_ids=company_ids, granularity=granularity, base_currency=base_currency)

# ── Inventory Domain ─────────────────────────

@tool
def inventory_alerts(tenant_id: Optional[str], company_id: Optional[int] = None, company_ids: Optional[list[int]] = None, tenant_ids: Optional[list[str]] = None):
    """Get critical inventory alerts: low-stock items below reorder threshold and expiring lots.
    Use for: stockout risk prevention, lot expiry management, procurement urgency flags.
    Always follow with inventory_efficiency to understand if slow turnover is causing the low stock."""
    return get_inventory_alerts_tool(tenant_id=tenant_id, tenant_ids=tenant_ids, company_id=company_id, company_ids=company_ids)

@tool
def inventory_efficiency(tenant_id: Optional[str], company_id: Optional[int] = None, company_ids: Optional[list[int]] = None, tenant_ids: Optional[list[str]] = None):
    """Analyze inventory turnover rate and days-on-hand metrics per product category.
    Use for: dead stock identification, overstocking risk, working capital tied up in inventory.
    Compare turnover against benchmarks: >8x/yr excellent, 5–8x good, <2x stagnant/dead stock.
    Run alongside inventory_alerts for a complete inventory health picture."""
    return get_inventory_efficiency_tool(tenant_id=tenant_id, tenant_ids=tenant_ids, company_id=company_id, company_ids=company_ids)

@tool
def inventory_stock_table(tenant_id: Optional[str], table_type: str, company_id: Optional[int] = None, company_ids: Optional[list[int]] = None, limit: int = 50, offset: int = 0, tenant_ids: Optional[list[str]] = None):
    """Get stock overview tables. table_type must be one of: 'low_stock', 'aging_stock', 'fast_moving'.
    Use for: drill-down into specific inventory conditions after viewing dashboard alerts."""
    return get_inventory_stock_table_tool(tenant_id=tenant_id, tenant_ids=tenant_ids, table_type=table_type, company_id=company_id, company_ids=company_ids, limit=limit, offset=offset)

@tool
def inventory_dashboard_alerts(tenant_id: Optional[str], company_id: Optional[int] = None, company_ids: Optional[list[int]] = None, tenant_ids: Optional[list[str]] = None):
    """Get summarized dashboard counts of all 7 inventory alerts (low stock, expiring, slow moving, etc.).
    Always use this as a first step for inventory investigations before diving into raw tables or sql queries."""
    return get_inventory_dashboard_alerts_tool(tenant_id=tenant_id, tenant_ids=tenant_ids, company_id=company_id, company_ids=company_ids)

@tool
def inventory_valuation(tenant_id: Optional[str], company_id: Optional[int] = None, company_ids: Optional[list[int]] = None, tenant_ids: Optional[list[str]] = None):
    """Get total inventory valuation and a count of products missing cost values.
    Use for: inventory reconciliation, assessing balance sheet asset values."""
    return get_inventory_valuation_tool(tenant_id=tenant_id, tenant_ids=tenant_ids, company_id=company_id, company_ids=company_ids)

# ── Banking Domain ──

@tool
def bank_cash_summary(tenant_id: Optional[str], start_date: str = None, end_date: str = None, company_id: Optional[int] = None, company_ids: Optional[list[int]] = None, base_currency: str = None, tenant_ids: Optional[list[str]] = None):
    """Get high-level bank balance, opening/closing cash balances, and cash flow breakdowns.
    Use for: checking current liquidity, daily banking summaries, top-level cash movements."""
    return get_bank_cash_summary_tool(tenant_id=tenant_id, tenant_ids=tenant_ids, start_date=start_date, end_date=end_date, company_id=company_id, company_ids=company_ids, base_currency=base_currency)

@tool
def journal_cards(tenant_id: Optional[str], start_date: str = None, end_date: str = None, company_id: Optional[int] = None, company_ids: Optional[list[int]] = None, base_currency: str = None, tenant_ids: Optional[list[str]] = None):
    """Get performance cards broken down by Accounting Journal (Bank, Cash, Vendor Bills, etc).
    Use for: journal-level reconciliation and viewing activity across different accounts."""
    return get_journal_cards_tool(tenant_id=tenant_id, tenant_ids=tenant_ids, start_date=start_date, end_date=end_date, company_id=company_id, company_ids=company_ids, base_currency=base_currency)

@tool
def bank_statement_summary(tenant_id: Optional[str], company_id: Optional[int] = None, company_ids: Optional[list[int]] = None, tenant_ids: Optional[list[str]] = None):
    """Get a list of the 20 most recent bank statements with opening and closing balances.
    Use for: checking recent reconciliation activity, verifying bank feeds are up to date."""
    return get_bank_statement_summary_tool(tenant_id=tenant_id, tenant_ids=tenant_ids, company_id=company_id, company_ids=company_ids)

# ── Purchasing Domain ────────────────────────

@tool
def purchase_summary(tenant_id: Optional[str], company_id: Optional[int] = None, company_ids: Optional[list[int]] = None, start_date: str = None, end_date: str = None, base_currency: str = None, tenant_ids: Optional[list[str]] = None):
    """Get total confirmed purchase spend, PO count, and average PO value for a given period.
    Always pass explicit ISO start_date and end_date (YYYY-MM-DD) when a time period is mentioned.
    Use for: total procurement spend, vendor payment totals, purchase volume metrics.
    This is the procurement counterpart to sales_summary — use it whenever procurement questions arise."""
    return get_purchase_summary_tool(tenant_id=tenant_id, tenant_ids=tenant_ids, company_id=company_id, company_ids=company_ids, start_date=start_date, end_date=end_date, base_currency=base_currency)

@tool
def top_vendors(tenant_id: Optional[str], company_id: Optional[int] = None, company_ids: Optional[list[int]] = None, start_date: str = None, end_date: str = None, limit: int = 10, base_currency: str = None, tenant_ids: Optional[list[str]] = None):
    """Rank vendors/suppliers by total confirmed purchase spend.
    Returns: vendor name, total spend, PO count, average PO value.
    Use for: 'who are our top suppliers?', 'biggest vendors', 'where are we spending most?',
    vendor concentration risk analysis. Increase limit for broader lists."""
    return get_top_vendors_tool(tenant_id=tenant_id, tenant_ids=tenant_ids, company_id=company_id, company_ids=company_ids, start_date=start_date, end_date=end_date, limit=limit, base_currency=base_currency)

@tool
def vendor_performance(tenant_id: Optional[str], company_id: Optional[int] = None, company_ids: Optional[list[int]] = None, limit: int = 10, base_currency: str = None, tenant_ids: Optional[list[str]] = None):
    """Get vendor performance scorecard: on-time delivery rate and average lead time in days.
    Uses purchase orders linked to incoming stock receipts for actual delivery data.
    Use for: 'which suppliers deliver on time?', 'vendor reliability', 'supplier scorecard',
    'who is always late?'. Run after top_vendors for context on which vendors to focus on."""
    return get_vendor_performance_tool(tenant_id=tenant_id, tenant_ids=tenant_ids, company_id=company_id, company_ids=company_ids, limit=limit, base_currency=base_currency)

@tool
def procurement_spend_by_category(tenant_id: Optional[str], company_id: Optional[int] = None, company_ids: Optional[list[int]] = None, start_date: str = None, end_date: str = None, limit: int = 20, base_currency: str = None, tenant_ids: Optional[list[str]] = None):
    """Break down procurement spend by product category with % of total spend per category.
    Use for: 'where is our purchase budget going?', 'procurement spend analysis',
    'which categories cost the most?', cost structure review by procurement category.
    The purchasing counterpart to expense_breakdown — shows spend by what we buy, not GL accounts."""
    return get_procurement_category_breakdown_tool(tenant_id=tenant_id, tenant_ids=tenant_ids, company_id=company_id, company_ids=company_ids, start_date=start_date, end_date=end_date, limit=limit, base_currency=base_currency)

@tool
def purchase_vs_sales_margin(tenant_id: Optional[str], company_id: Optional[int] = None, company_ids: Optional[list[int]] = None, limit: int = 20, base_currency: str = None, tenant_ids: Optional[list[str]] = None):
    """Compare average buy price vs average sell price per product to reveal true product margins.
    Returns: product name, avg buy price, avg sell price, margin, margin %, qty bought vs qty sold.
    Use for: 'are we buying too expensive?', 'product margin analysis', 'cost vs revenue per product',
    identifying products with shrinking margins. Run after top_products for revenue-side context."""
    return get_purchase_vs_sales_margin_tool(tenant_id=tenant_id, tenant_ids=tenant_ids, company_id=company_id, company_ids=company_ids, limit=limit, base_currency=base_currency)

@tool
def po_fulfillment(tenant_id: Optional[str], company_id: Optional[int] = None, company_ids: Optional[list[int]] = None, base_currency: str = None, tenant_ids: Optional[list[str]] = None):
    """Track PO fulfillment: overdue purchase orders and partial receipts.
    Returns: overdue PO count and value, top late vendors, lines with qty_received < qty_ordered.
    Use for: 'are our orders arriving on time?', 'late deliveries', 'pending receipts',
    'backlog from vendors', supply chain disruption detection. Critical for procurement risk."""
    return get_po_fulfillment_tool(tenant_id=tenant_id, tenant_ids=tenant_ids, company_id=company_id, company_ids=company_ids, base_currency=base_currency)

@tool
def purchase_trend(tenant_id: Optional[str], company_id: Optional[int] = None, company_ids: Optional[list[int]] = None, granularity: str = "month", base_currency: str = None, tenant_ids: Optional[list[str]] = None):
    """Get procurement spend as a time series broken down by period.
    granularity options: 'day', 'week', 'month' (default), 'quarter', 'year'.
    Use for: procurement trend charts, spending trajectory, seasonal procurement patterns.
    The purchasing counterpart to sales_trend — use when the user asks about spend over time."""
    return get_purchase_trend_tool(tenant_id=tenant_id, tenant_ids=tenant_ids, company_id=company_id, company_ids=company_ids, granularity=granularity, base_currency=base_currency)

# ── Reporting Domain ─────────────────────────

@tool
def create_report(
    tenant_id: Optional[str],
    custom_content: str,
    company_id: Optional[int] = None,
    company_ids: Optional[list[int]] = None,
    tenant_ids: Optional[list[str]] = None,
    logo_path: Optional[str] = None,
):
    """MANDATORY: When the user asks to 'generate a report' or 'create a report', you MUST call this tool.
    Generate a professional branded PDF executive report including vital signs and your analysis.
    You MUST pass your full markdown report analysis into the `custom_content` parameter. This parameter is REQUIRED.
    Do NOT output the report directly in the chat text. Pass it ALL into `custom_content`.
    Do NOT call this before you have gathered the data — the report cannot be regenerated mid-session."""
    
    # Generate the report. If custom_content is missing, it will use the default automated summary.
    result = generate_report_tool(
        tenant_id,
        custom_content=custom_content,
        company_id=company_id,
        company_ids=company_ids,
        tenant_ids=tenant_ids,
        logo_path=logo_path,
    )
    url = result.get("download_url", "")
    
    # Return a loud, explicit string to Claude so it stops looping and responds to the user!
    return (
        f"SUCCESS! The report has been successfully generated and saved.\n"
        f"Download URL: {url}\n\n"
        f"CRITICAL INSTRUCTION: You must now STOP calling tools. Do NOT call create_report again. "
        f"Output your final response to the user containing this download link."
    )

@tool
def get_latest_report(tenant_id: Optional[str], company_id: Optional[int] = None, company_ids: Optional[list[int]] = None, tenant_ids: Optional[list[str]] = None):
    """Retrieve the download URL for the most recently generated PDF report for this tenant.
    Use when the user asks 'give me the report', 'download the last report', or 'send me the PDF'.
    If no report exists, suggest calling create_report first."""
    return get_last_report_tool(tenant_id=tenant_id, company_id=company_id, company_ids=company_ids)

# ── Communication Domain ─────────────────────

@tool
def send_alert(tenant_id: Optional[str], title: str, message: str, company_id: Optional[int] = None, company_ids: Optional[list[int]] = None, tenant_ids: Optional[list[str]] = None):
    """Send a real-time notification alert to the user's dashboard.
    Use when the user asks to be notified, or when a critical risk (e.g., overdue AR >30%, liquidity critical)
    warrants immediate dashboard notification. title should be ≤10 words; message should be ≤2 sentences."""
    return send_alert_tool(tenant_id=tenant_id, tenant_ids=tenant_ids, title=title, message=message, company_id=company_id, company_ids=company_ids)

@tool
def send_email(tenant_id: Optional[str], to_email: str, subject: str, body: str, company_id: Optional[int] = None, company_ids: Optional[list[int]] = None, tenant_ids: Optional[list[str]] = None):
    """Prepare and queue an email to a specified recipient.
    Use only when the user explicitly requests an email to be sent — never send without clear instruction.
    body should be professional, concise, and include the key findings from your analysis."""
    return send_email_tool(tenant_id=tenant_id, tenant_ids=tenant_ids, to_email=to_email, subject=subject, body=body, company_id=company_id, company_ids=company_ids)

@tool
def cash_flow_statement(tenant_id: Optional[str], company_id: Optional[int] = None, company_ids: Optional[list[int]] = None, start_date: str = None, end_date: str = None, base_currency: str = None, tenant_ids: Optional[list[str]] = None):
    """Generate a standard Cash Flow Statement (Operating, Investing, Financing activities).
    Use for: 'where is the cash going?', 'cash flow summary', 'liquidity analysis'.
    Returns net cash from operations, investments, and financing, and the net change in cash."""
    return get_cash_flow_statement_tool(tenant_id=tenant_id, tenant_ids=tenant_ids, company_id=company_id, company_ids=company_ids, start_date=start_date, end_date=end_date, base_currency=base_currency)

@tool
def working_capital_efficiency(tenant_id: Optional[str], company_id: Optional[int] = None, company_ids: Optional[list[int]] = None, base_currency: str = None, tenant_ids: Optional[list[str]] = None):
    """Calculate Cash Conversion Cycle (CCC), Days Sales Outstanding (DSO), Days Inventory Outstanding (DIO), and Days Payable Outstanding (DPO).
    Use for: working capital analysis, cash cycle duration, how fast we turn inventory into cash."""
    return get_working_capital_efficiency_tool(tenant_id=tenant_id, tenant_ids=tenant_ids, company_id=company_id, company_ids=company_ids, base_currency=base_currency)

@tool
def period_comparison_pnl(tenant_id: Optional[str], current_start: str, current_end: str, prior_start: str, prior_end: str, company_id: Optional[int] = None, company_ids: Optional[list[int]] = None, base_currency: str = None, tenant_ids: Optional[list[str]] = None):
    """Perform a variance analysis comparing P&L across two distinct periods (e.g. this month vs last month, this year vs last year).
    Returns detailed variances for Revenue, COGS, Gross Profit, Expenses, and Net Profit.
    Requires explicit ISO dates for current and prior periods."""
    return get_period_comparison_pnl_tool(tenant_id=tenant_id, tenant_ids=tenant_ids, period1_start=current_start, period1_end=current_end, period2_start=prior_start, period2_end=prior_end, company_id=company_id, company_ids=company_ids, base_currency=base_currency)

@tool
def interest_coverage(tenant_id: Optional[str], company_id: Optional[int] = None, company_ids: Optional[list[int]] = None, start_date: str = None, end_date: str = None, base_currency: str = None, tenant_ids: Optional[list[str]] = None):
    """Calculate the Interest Coverage Ratio (EBIT / Interest Expense).
    Use for: debt service capacity, risk of default, ability to pay interest."""
    return get_interest_coverage_tool(tenant_id=tenant_id, tenant_ids=tenant_ids, company_id=company_id, company_ids=company_ids, start_date=start_date, end_date=end_date, base_currency=base_currency)

@tool
def revenue_segmentation(tenant_id: Optional[str], company_id: Optional[int] = None, company_ids: Optional[list[int]] = None, segment_by: str = "customer", start_date: str = None, end_date: str = None, limit: int = 10, base_currency: str = None, tenant_ids: Optional[list[str]] = None):
    """Break down total revenue by 'customer' or 'journal'.
    Use for: customer concentration risk, revenue streams, top clients by invoice revenue."""
    return get_revenue_segmentation_tool(tenant_id=tenant_id, tenant_ids=tenant_ids, company_id=company_id, company_ids=company_ids, segment_by=segment_by, start_date=start_date, end_date=end_date, limit=limit, base_currency=base_currency)

@tool
def payment_reconciliation(tenant_id: Optional[str], company_id: Optional[int] = None, company_ids: Optional[list[int]] = None, base_currency: str = None, tenant_ids: Optional[list[str]] = None):
    """Identify unreconciled customer payments (payments received but not applied to an invoice).
    Use for: 'unapplied cash', 'payments not matched', 'AR reconciliation issues'."""
    return get_payment_reconciliation_tool(tenant_id=tenant_id, tenant_ids=tenant_ids, company_id=company_id, company_ids=company_ids, base_currency=base_currency)

# ── Phase 4: Inventory & Operations ─────────────────
from doova_one_view.api.agent.tools_refactored import (
    get_reorder_recommendations_tool,
    get_abc_analysis_tool,
    get_warehouse_utilization_tool,
    get_fulfillment_rate_tool,
    get_backorder_aging_tool,
    get_supplier_lead_time_tool,
)

@tool
def reorder_recommendations(tenant_id: Optional[str], company_id: Optional[int] = None, company_ids: Optional[list[int]] = None, days_history: int = 30, tenant_ids: Optional[list[str]] = None):
    """Recommend reorder quantities for products where current stock is too low compared to recent sales velocity.
    Use for: 'what should we order?', 'low stock warnings', 'replenishment suggestions'."""
    return get_reorder_recommendations_tool(tenant_id=tenant_id, tenant_ids=tenant_ids, company_id=company_id, company_ids=company_ids, days_history=days_history)

@tool
def abc_analysis(tenant_id: Optional[str], company_id: Optional[int] = None, company_ids: Optional[list[int]] = None, tenant_ids: Optional[list[str]] = None):
    """Classify inventory into A (high value), B (medium), and C (low) categories based on revenue contribution.
    Use for: 'inventory classification', 'what are our most important products?', 'ABC analysis'."""
    return get_abc_analysis_tool(tenant_id=tenant_id, tenant_ids=tenant_ids, company_id=company_id, company_ids=company_ids)

@tool
def warehouse_utilization(tenant_id: Optional[str], company_id: Optional[int] = None, company_ids: Optional[list[int]] = None, tenant_ids: Optional[list[str]] = None):
    """Analyze stock quantities and valuation grouped by physical warehouse location.
    Use for: 'stock by location', 'warehouse value', 'where is our inventory?'."""
    return get_warehouse_utilization_tool(tenant_id=tenant_id, tenant_ids=tenant_ids, company_id=company_id, company_ids=company_ids)

@tool
def fulfillment_rate(tenant_id: Optional[str], company_id: Optional[int] = None, company_ids: Optional[list[int]] = None, tenant_ids: Optional[list[str]] = None):
    """Calculate the percentage of outgoing deliveries that were delivered on-time.
    Use for: 'fulfillment rate', 'on time delivery', 'shipping performance'."""
    return get_fulfillment_rate_tool(tenant_id=tenant_id, tenant_ids=tenant_ids, company_id=company_id, company_ids=company_ids)

@tool
def backorder_aging(tenant_id: Optional[str], company_id: Optional[int] = None, company_ids: Optional[list[int]] = None, tenant_ids: Optional[list[str]] = None):
    """Identify the oldest unfulfilled stock moves (backorders) and their aging in days.
    Use for: 'oldest backorders', 'pending shipments', 'what orders are delayed?'."""
    return get_backorder_aging_tool(tenant_id=tenant_id, tenant_ids=tenant_ids, company_id=company_id, company_ids=company_ids)

@tool
def supplier_lead_time(tenant_id: Optional[str], company_id: Optional[int] = None, company_ids: Optional[list[int]] = None, tenant_ids: Optional[list[str]] = None):
    """Calculate average actual lead time vs scheduled for incoming stock pickings by supplier.
    Use for: 'which suppliers are late?', 'supplier delivery performance', 'average delay'."""
# ── Consolidated Agent Tools ─────────────────

agent_tools = [
    # Discovery
    ask_database_custom_question, list_companies, tenant_profile,
    # Sales
    sales_summary, top_products, sales_trend, variance_analysis, sales_forecast,
    salesperson_performance, sales_pipeline, discount_leakage, customer_lifetime_value, order_to_cash_cycle, revenue_by_category,
    # Finance — Core Statements
    calculate_pnl, balance_sheet, trial_balance, cash_flow_statement,
    # Finance — Analysis
    financial_ratios, working_capital, profitability_analysis, expense_breakdown, working_capital_efficiency, interest_coverage, period_comparison_pnl,
    # Finance — AR/AP & Cash
    receivables_analysis, payables_analysis, aging_analysis, cash_flow_health, payment_reconciliation,
    # Finance — Tax & Audit
    tax_summary, detect_anomalies,
    # Finance — Intelligence
    period_comparison, business_health, customer_metrics, revenue_segmentation,
    # Banking
    bank_cash_summary, journal_cards, bank_statement_summary,
    # Purchasing
    purchase_summary, top_vendors, vendor_performance,
    procurement_spend_by_category, purchase_vs_sales_margin,
    po_fulfillment, purchase_trend,
    # Inventory
    inventory_alerts, inventory_efficiency, inventory_stock_table, inventory_dashboard_alerts, inventory_valuation,
    reorder_recommendations, abc_analysis, warehouse_utilization, fulfillment_rate, backorder_aging, supplier_lead_time,
    # Reporting & Communication
    create_report, get_latest_report, send_alert, send_email,
]
