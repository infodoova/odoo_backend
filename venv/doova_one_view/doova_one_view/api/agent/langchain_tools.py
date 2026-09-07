# api/agent/langchain_tools.py

from typing import Optional, Union, List, Any

# Robust type aliases for LLM parameter resilience
CompanyIdsType = Optional[Union[List[Union[int, str]], str]]
TenantIdsType = Optional[Union[List[str], str]]
from langchain_core.tools import tool
from .sql_agent import run_sql_agent
from .date_engine import resolve_period_dates, resolve_comparison_dates, normalize_iso_date, resolve_as_of_date


def _resolve_and_sync_period(start_date: Optional[str] = None, end_date: Optional[str] = None) -> tuple[Optional[str], Optional[str]]:
    """
    Inherits active date window if dates are omitted, resolves any period strings to ISO,
    and syncs the active date window to the session.
    """
    from .session_context import get_active_date_window, update_active_date_window
    if not start_date and not end_date:
        active = get_active_date_window()
        if active:
            start_date = active.get("start_date")
            end_date = active.get("end_date")

    if start_date or end_date:
        s_iso, e_iso, label = resolve_period_dates(start_date=start_date, end_date=end_date)
        if s_iso and e_iso:
            update_active_date_window(s_iso, e_iso, label)
            return s_iso, e_iso
        return s_iso or start_date, e_iso or end_date

    return None, None


def _resolve_and_sync_as_of(as_of_date: Optional[str] = None, *other_date_args) -> str:
    """
    Resolves snapshot date from ISO, period string (e.g. 'Q3 2026'), or active session window.
    """
    from .session_context import get_active_date_window
    raw = as_of_date
    for arg in other_date_args:
        if raw:
            break
        raw = arg

    fallback = None
    if not raw:
        active = get_active_date_window()
        if active:
            fallback = active.get("end_date")

    return resolve_as_of_date(raw, fallback_date=fallback)
from .tools_refactored import (
    get_sales_summary_tool,
    get_top_products_tool,
    get_time_series_data_tool,
    get_sales_chart_data_tool,
    analyze_variance_tool,
    forecast_sales_tool,
    get_inventory_efficiency_tool,
    get_inventory_stock_table_tool,
    get_inventory_dashboard_alerts_tool,
    get_inventory_valuation_tool,
    get_receivables_analysis_tool,
    get_payables_analysis_tool,
    get_cash_flow_health_tool,
    get_business_health_score_tool,
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
    get_unrealized_currency_gains_losses_tool,
    get_general_ledger_tool,
    get_partner_ledger_tool,
    get_customer_statement_tool,
    get_followup_report_tool,
    get_executive_summary_tool,
    generate_report_tool,
    get_last_report_tool,
    send_alert_tool,
    send_email_tool,
    get_bank_cash_summary_tool,
    get_journal_cards_tool,
    get_bank_statement_summary_tool,
    get_journal_audit_tool,
    get_companies_tool,
    get_tenant_profile_tool,
    get_purchase_summary_tool,
    get_top_vendors_tool,
    get_vendor_performance_tool,
    get_procurement_category_breakdown_tool,
    get_purchase_vs_sales_margin_tool,
    get_po_fulfillment_tool,
    get_purchase_trend_tool,
    get_product_purchase_history_tool,
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
    get_reorder_recommendations_tool,
    get_abc_analysis_tool,
    get_warehouse_utilization_tool,
    get_fulfillment_rate_tool,
    get_backorder_aging_tool,
    get_supplier_lead_time_tool,
)

# ── SQL Fallback ─────────────────────────────

@tool
def ask_database_custom_question( question: str = None, tenant_ids: TenantIdsType = None):
    """Fallback SQL tool for any question that no other tool can answer directly.
    Describe the business intent clearly in plain English (e.g., 'total invoiced revenue by salesperson for Q2').
    Use this when: a specialized tool returns an error, data is not available in pre-built tools,
    or the user asks a highly specific ad-hoc question. ALWAYS try the specialized tools first."""
    result = run_sql_agent(user_question=question, tenant_ids=tenant_ids)
    return result.get("message", "Could not answer the question.")

# ── Company Discovery ────────────────────────

@tool
def list_companies( tenant_ids: TenantIdsType = None):
    """List all companies for this tenant with their names and numeric IDs.
    Use this when the user mentions a company by name but you need its company_id integer
    to pass to other tools. Run this before any other tool if company_id is unknown."""
    return get_companies_tool(tenant_ids=tenant_ids)

@tool
def tenant_profile( company_ids: CompanyIdsType = None, tenant_ids: TenantIdsType = None):
    """Get the company's inferred business model (Product / Service / Hybrid) and currency.
    Use this FIRST on any health check, ratio analysis, or benchmark comparison — the business
    model determines which gross margin and turnover benchmarks are applicable.
    Also use when the user asks 'what kind of company is this' or 'what currency do we use'."""
    return get_tenant_profile_tool(tenant_ids=tenant_ids, company_ids=company_ids)

# ── Sales Domain ─────────────────────────────

@tool
def sales_summary( company_ids: CompanyIdsType = None, start_date: str = None, end_date: str = None, base_currency: str = None, tenant_ids: TenantIdsType = None):
    """Get total sales revenue
    Always pass the target base_currency. and order count for a given period.
    Always pass explicit ISO start_date and end_date (YYYY-MM-DD) when a time period is mentioned.
    Use for: revenue totals, order volume, period-specific sales snapshots.
    Prefer this over sales_trend when the user wants a single aggregate, not a time series."""
    s_iso, e_iso = _resolve_and_sync_period(start_date, end_date)
    return get_sales_summary_tool(tenant_ids=tenant_ids, company_ids=company_ids, start_date=s_iso or start_date, end_date=e_iso or end_date, base_currency=base_currency)

@tool
def top_products( company_ids: CompanyIdsType = None, limit: Optional[Union[int, str]] = 10, base_currency: str = None, tenant_ids: TenantIdsType = None):
    """Get the top-selling products
    Always pass the target base_currency. ranked by revenue, with quantities sold.
    Use for: 'best sellers', 'top products', 'what's driving revenue', product mix analysis.
    Increase limit beyond 10 if the user asks for a broader list (e.g., top 20, top 50)."""
    return get_top_products_tool(tenant_ids=tenant_ids, company_ids=company_ids, limit=limit, base_currency=base_currency)

@tool
def sales_trend( company_ids: CompanyIdsType = None, granularity: str = "month", base_currency: str = None, tenant_ids: TenantIdsType = None):
    """Get sales revenue as a time series
    Always pass the target base_currency. broken down by period.
    granularity options: 'day', 'week', 'month' (default), 'quarter', 'year'.
    Use for: trend charts, growth trajectory, seasonality patterns, time series graphs.
    Prefer this over sales_summary when the user wants change over time, not a single total."""
    return get_time_series_data_tool(tenant_ids=tenant_ids, company_ids=company_ids, granularity=granularity, base_currency=base_currency)

@tool
def variance_analysis( company_ids: CompanyIdsType = None, base_currency: str = None, tenant_ids: TenantIdsType = None):
    """Analyze month-over-month
    Always pass the target base_currency. sales variance — absolute change and percentage swing.
    Use for: detecting revenue spikes or drops, explaining monthly performance deviations,
    identifying which months underperformed. Run after sales_summary for deep-dive context."""
    return analyze_variance_tool(tenant_ids=tenant_ids, company_ids=company_ids, base_currency=base_currency)

@tool
def sales_forecast( company_ids: CompanyIdsType = None, base_currency: str = None, tenant_ids: TenantIdsType = None):
    """Generate a forward-looking sales forecast based on historical trend data.
    Use for: projected revenue, future planning, budget gap analysis.
    Always pair the forecast output with variance_analysis to show the historical baseline."""
    return forecast_sales_tool(tenant_ids=tenant_ids, company_ids=company_ids, base_currency=base_currency)

@tool
def salesperson_performance( company_ids: CompanyIdsType = None, start_date: str = None, end_date: str = None, base_currency: str = None, tenant_ids: TenantIdsType = None):
    """Rank sales representatives by total revenue, order count, and margin.
    Use for: 'who is our best salesperson?', 'sales team performance review',
    'revenue by user', 'sales rep commissions'."""
    return get_salesperson_performance_tool(tenant_ids=tenant_ids, company_ids=company_ids, start_date=start_date, end_date=end_date, base_currency=base_currency)

@tool
def sales_pipeline( company_ids: CompanyIdsType = None, start_date: str = None, end_date: str = None, base_currency: str = None, tenant_ids: TenantIdsType = None):
    """Analyze the sales pipeline by counting open quotes vs won orders and calculating conversion rates.
    Use for: 'how is our pipeline?', 'what is our close rate?', 'open quotations value'."""
    return get_sales_pipeline_tool(tenant_ids=tenant_ids, company_ids=company_ids, start_date=start_date, end_date=end_date, base_currency=base_currency)

@tool
def discount_leakage( company_ids: CompanyIdsType = None, start_date: str = None, end_date: str = None, base_currency: str = None, tenant_ids: TenantIdsType = None):
    """Identify margin leakage through explicit discounts on sales orders.
    Use for: 'are we discounting too much?', 'margin leakage', 'top discounted products'."""
    return get_discount_leakage_tool(tenant_ids=tenant_ids, company_ids=company_ids, start_date=start_date, end_date=end_date, base_currency=base_currency)

@tool
def customer_lifetime_value( company_ids: CompanyIdsType = None, base_currency: str = None, tenant_ids: TenantIdsType = None):
    """Calculate the lifetime value (CLV) of top customers and group them into tiers (Platinum, Gold, Silver, Bronze).
    Use for: 'who are our most valuable customers?', 'CLV analysis', 'top clients by lifetime revenue'."""
    return get_customer_lifetime_value_tool(tenant_ids=tenant_ids, company_ids=company_ids, base_currency=base_currency)

@tool
def order_to_cash_cycle( company_ids: CompanyIdsType = None, start_date: str = None, end_date: str = None, base_currency: str = None, tenant_ids: TenantIdsType = None):
    """Measure the Order-to-Cash (O2C) cycle by calculating the average days between sales order confirmation and invoicing.
    Use for: 'how long does it take to get paid?', 'O2C cycle time', 'order to invoice speed'."""
    return get_order_to_cash_cycle_tool(tenant_ids=tenant_ids, company_ids=company_ids, start_date=start_date, end_date=end_date, base_currency=base_currency)

@tool
def revenue_by_category( company_ids: CompanyIdsType = None, start_date: str = None, end_date: str = None, base_currency: str = None, tenant_ids: TenantIdsType = None):
    """Break down total sales revenue by product category hierarchy.
    Use for: 'which product categories drive our revenue?', 'sales by category'."""
    return get_revenue_by_category_tool(tenant_ids=tenant_ids, company_ids=company_ids, start_date=start_date, end_date=end_date, base_currency=base_currency)

# ── Finance Domain ───────────────────────────

@tool
def calculate_pnl( company_ids: CompanyIdsType = None, start_date: str = None, end_date: str = None, base_currency: str = None, tenant_ids: TenantIdsType = None):
    """Calculate the Profit & Loss statement for a specific period.
    Returns: Total Income, COGS, Gross Profit, Operating Expenses, Net Profit, and all margin %.
    Always pass explicit ISO start_date and end_date when a period is mentioned.
    Use for: P&L review, income statements, margin analysis, gross margin %, net margin %, profitability by period.
    This is the comprehensive income statement tool — gross and net margins are already calculated directly here.
    Follow with expense_breakdown for deeper category analysis."""
    s_iso, e_iso = _resolve_and_sync_period(start_date, end_date)
    return calculate_pnl_tool(tenant_ids=tenant_ids, company_ids=company_ids, start_date=s_iso or start_date, end_date=e_iso or end_date, base_currency=base_currency)

@tool
def executive_summary( company_ids: CompanyIdsType = None, start_date: str = None, end_date: str = None, base_currency: str = None, tenant_ids: TenantIdsType = None):
    """Generate the official 5-pillar Executive Business Summary matching Odoo Report ID 6.
    Returns reconciled pillars:
    1. Cash: Cash received, cash spent, cash surplus, closing bank balance
    2. Profitability: Revenue, Cost of Revenue, Gross profit, Operating Expenses, Net profit
    3. Balance Sheet: Receivables, Payables, Net assets
    4. Performance: Gross margin %, Net margin %, ROI %
    5. Position: DSO (Debtors days), DPO (Creditors days), Short term cash forecast, Current Ratio
    Use for: Executive overviews, management briefings, CFO dashboards, periodic health evaluations."""
    s_iso, e_iso = _resolve_and_sync_period(start_date, end_date)
    return get_executive_summary_tool(tenant_ids=tenant_ids, company_ids=company_ids, start_date=s_iso or start_date, end_date=e_iso or end_date, base_currency=base_currency)

@tool
def balance_sheet(
    company_ids: CompanyIdsType = None,
    as_of_date: Optional[str] = None,
    date_to: Optional[str] = None,
    end_date: Optional[str] = None,
    start_date: Optional[str] = None,
    base_currency: str = None,
    tenant_ids: TenantIdsType = None,
):
    """Generate the Balance Sheet: Assets, Liabilities, and Equity with an A=L+E integrity check.
    as_of_date: snapshot date ISO 'YYYY-MM-DD' or period label (e.g. '2026-09-30' or 'Q3 2026').
    Use for: net worth assessment, leverage analysis, equity position, solvency review.
    If the integrity check fails (A ≠ L+E), immediately call detect_anomalies to investigate.
    Run alongside financial_ratios for ratio-to-balance context."""
    resolved_as_of = _resolve_and_sync_as_of(as_of_date, date_to, end_date, start_date)
    return get_balance_sheet_tool(tenant_ids=tenant_ids, company_ids=company_ids, as_of_date=resolved_as_of, base_currency=base_currency)

@tool
def trial_balance( company_ids: CompanyIdsType = None, base_currency: str = None, tenant_ids: TenantIdsType = None, date_from: str = None, date_to: str = None, as_of_date: str = None):
    """Generate the Trial Balance with account-level debit and credit totals.
    Includes an integrity check verifying total debits = total credits.
    Use for: accounting accuracy verification, ledger review, pre-audit checks, multi-company trial balances.
    If the trial balance is unbalanced, call detect_anomalies immediately."""
    return get_trial_balance_tool(tenant_ids=tenant_ids, company_ids=company_ids, base_currency=base_currency, date_from=date_from, date_to=date_to, as_of_date=as_of_date)

@tool
def general_ledger( company_ids: CompanyIdsType = None, account_code: str = None, account_name: str = None, date_from: str = None, date_to: str = None, as_of_date: str = None, include_lines: bool = False, limit_accounts: int = None, base_currency: str = None, tenant_ids: TenantIdsType = None):
    """Generate the complete General Ledger matching Odoo.
    Returns account-level Debit, Credit, and Net Balance for all accounts across active companies,
    along with grand totals (e.g. 68.92B FCFA), integrity checks (Debit == Credit), and optional granular move lines.
    Use for: 'general ledger', 'grand livre', 'account breakdown', 'ledger balances', 'full accounting statements'."""
    return get_general_ledger_tool(tenant_ids=tenant_ids, company_ids=company_ids, account_code=account_code, account_name=account_name, date_from=date_from, date_to=date_to, as_of_date=as_of_date, include_lines=include_lines, limit_accounts=limit_accounts, base_currency=base_currency)

@tool
def partner_ledger( company_ids: CompanyIdsType = None, partner_name: str = None, partner_id: int = None, account_type: str = None, date_from: str = None, date_to: str = None, as_of_date: str = None, unreconciled_only: bool = False, include_lines: bool = False, limit_partners: int = None, base_currency: str = None, tenant_ids: TenantIdsType = None):
    """Generate the complete Partner Ledger (Grand Livre des Tiers) matching Odoo.
    Returns partner-level Debit, Credit, and Net Balance for all customers and suppliers across companies,
    along with grand totals, Net Receivable / Net Payable status, and optional move lines (invoices, matching, currency).
    Set `unreconciled_only=True` when the user asks for unreconciled entries only, open items, unsettled balances, non lettré, or pending reconciliations.
    Use for: 'partner ledger', 'grand livre des tiers', 'unreconciled partner ledger', 'customer ledger', 'vendor ledger', 'partner balances', 'who owes what per partner'."""
    return get_partner_ledger_tool(tenant_ids=tenant_ids, company_ids=company_ids, partner_name=partner_name, partner_id=partner_id, account_type=account_type, date_from=date_from, date_to=date_to, as_of_date=as_of_date, unreconciled_only=unreconciled_only, include_lines=include_lines, limit_partners=limit_partners, base_currency=base_currency)

@tool
def customer_statement( company_ids: CompanyIdsType = None, partner_name: str = None, partner_id: int = None, date_from: str = None, date_to: str = None, as_of_date: str = None, include_lines: bool = False, limit_partners: int = None, base_currency: str = None, tenant_ids: TenantIdsType = None):
    """Generate the Customer Statement (Relevé Client, Odoo Report 15) matching Odoo exactly.
    Returns partner-level Amount and Balance with exact columns:
    Invoice Date, Due Date, Amount, Amount Currency, Balance.
    Use for: 'customer statement', 'releve client', 'statement of account', 'customer balance statement'."""
    return get_customer_statement_tool(tenant_ids=tenant_ids, company_ids=company_ids, partner_name=partner_name, partner_id=partner_id, date_from=date_from, date_to=date_to, as_of_date=as_of_date, include_lines=include_lines, limit_partners=limit_partners, base_currency=base_currency)

@tool
def followup_report( company_ids: CompanyIdsType = None, partner_name: str = None, partner_id: int = None, as_of_date: str = None, date_to: str = None, include_lines: bool = False, limit_partners: int = None, base_currency: str = None, tenant_ids: TenantIdsType = None):
    """Generate the Follow-Up Report (Rapport de Relance, Odoo Report 16) matching Odoo exactly.
    Returns partner-level Amount and Balance for receivables with exact columns:
    Invoice Date, Due Date, Amount, Amount Currency, Balance.
    Use for: 'follow up report', 'rapport de relance', 'customer follow up', 'relance clients', 'overdue follow up'."""
    return get_followup_report_tool(tenant_ids=tenant_ids, company_ids=company_ids, partner_name=partner_name, partner_id=partner_id, as_of_date=as_of_date, date_to=date_to, include_lines=include_lines, limit_partners=limit_partners, base_currency=base_currency)

@tool
def financial_ratios( company_ids: CompanyIdsType = None, base_currency: str = None, tenant_ids: TenantIdsType = None):
    """Calculate all key financial ratios: Current Ratio, Quick Ratio, Debt-to-Equity,
    ROE, ROA, Gross Margin %, and Net Margin %.
    Use for: financial health scoring, benchmark comparisons, in-depth financial analysis.
    Always call tenant_profile first to know the correct industry benchmarks to compare against.
    Pair with business_health for a weighted composite score."""
    return get_financial_ratios_tool(tenant_ids=tenant_ids, company_ids=company_ids, base_currency=base_currency)

@tool
def working_capital( company_ids: CompanyIdsType = None, base_currency: str = None, tenant_ids: TenantIdsType = None):
    """Calculate Working Capital (Current Assets minus Current Liabilities) and the WC ratio.
    Use for: short-term liquidity assessment, operational funding buffer, cash runway estimation.
    When short-term bills exceed short-term assets (negative working capital), that's a critical warning.
    Pair with cash_flow_health and aging_analysis for full liquidity context."""
    return get_working_capital_tool(tenant_ids=tenant_ids, company_ids=company_ids, base_currency=base_currency)

@tool
def receivables_analysis( company_ids: CompanyIdsType = None, base_currency: str = None, tenant_ids: TenantIdsType = None):
    """Analyze Accounts Receivable: total outstanding, overdue balance, and top overdue customers.
    Use for: collections health overview, credit risk summary, DSO context.
    Prefer aging_analysis when you need bucket distribution (30/60/90 day breakdown).
    Use this for high-level AR totals; use aging_analysis for detailed overdue structure."""
    return get_receivables_analysis_tool(tenant_ids=tenant_ids, company_ids=company_ids, base_currency=base_currency)

@tool
def payables_analysis( company_ids: CompanyIdsType = None, base_currency: str = None, tenant_ids: TenantIdsType = None):
    """Analyze Accounts Payable: total outstanding, overdue balance, and top overdue vendors.
    Use for: supplier payment risk, DPO context, cash outflow exposure.
    Prefer aging_analysis(direction='payable') when you need bucket-level overdue breakdown.
    Use this for high-level AP totals; use aging_analysis for detailed overdue structure."""
    return get_payables_analysis_tool(tenant_ids=tenant_ids, company_ids=company_ids, base_currency=base_currency)

@tool
def aging_analysis(
    company_ids: CompanyIdsType = None,
    direction: str = "receivable",
    base_currency: str = None,
    tenant_ids: TenantIdsType = None,
    as_of_date: str = None,
    date_to: str = None,
    end_date: str = None,
    start_date: str = None,
):
    """Get AR or AP aging bucket distribution: Current, 1–30, 31–60, 61–90, and 90+ days overdue.
    direction='receivable' for customer AR aging (default).
    direction='payable' for supplier AP aging.
    as_of_date: snapshot date ISO 'YYYY-MM-DD' or period (e.g. '2026-09-30' or 'last month').
    Use for: overdue collections risk, vendor payment stress, aging-based cash flow projections.
    Prefer this over receivables_analysis/payables_analysis when you need the bucket breakdown,
    not just totals. Critical for identifying if overdue concentration is in the 90+ bucket."""
    resolved_as_of = _resolve_and_sync_as_of(as_of_date, date_to, end_date, start_date)
    return get_aging_analysis_tool(tenant_ids=tenant_ids, company_ids=company_ids, direction=direction, base_currency=base_currency, as_of_date=resolved_as_of)
@tool
def unrealized_currency_gains_losses( company_ids: CompanyIdsType = None, as_of_date: str = None, tenant_ids: TenantIdsType = None):
    """Compute statutory Unrealized Currency Gains/Losses (Balance Sheet Revaluation) matching Odoo.
    Evaluates foreign-currency-denominated accounts (Payables, Receivables, Cash, Bank) at the 
    operation rate vs current market rate as of the given date, and computes required balance adjustments.
    Use for: 'unrealized currency gains losses', 'FX balance sheet revaluation', 'foreign currency adjustment', 'gain ou perte de change latente'."""
    return get_unrealized_currency_gains_losses_tool(tenant_ids=tenant_ids, company_ids=company_ids, as_of_date=as_of_date)

@tool
def cash_flow_health( company_ids: CompanyIdsType = None, base_currency: str = None, tenant_ids: TenantIdsType = None):
    """Assess overall cash flow and liquidity health using real AR and AP balances.
    Returns: net cash position, spending rate indicators, and cash pressure signals.
    Use for: cash runway assessment, cash crunch detection, short-term solvency.
    Run first in any liquidity investigation before diving into working_capital or aging."""
    return get_cash_flow_health_tool(tenant_ids=tenant_ids, company_ids=company_ids, base_currency=base_currency)

@tool
def business_health( company_ids: CompanyIdsType = None, base_currency: str = None, tenant_ids: TenantIdsType = None):
    """Calculate the composite weighted business health score (0–100) across four dimensions:
    profitability, cash availability, debt levels, and how well you collect payments.
    Use for: overall business health checks, company performance scoring, summary dashboards.
    Always run financial_ratios before this to have the underlying ratio context available."""
    return get_business_health_score_tool(tenant_ids=tenant_ids, company_ids=company_ids, base_currency=base_currency)

@tool
def customer_metrics( company_ids: CompanyIdsType = None, base_currency: str = None, tenant_ids: TenantIdsType = None):
    """Get customer retention rate, churn risk score, and top customers ranked by revenue.
    Use for: customer concentration risk, revenue dependency analysis, churn early warning.
    If top-3 customers represent >50% of revenue, flag as high concentration risk.
    Follow with receivables_analysis and aging_analysis(receivable) to check their payment behavior."""
    return get_customer_metrics_tool(tenant_ids=tenant_ids, company_ids=company_ids, base_currency=base_currency)

@tool
def expense_breakdown( company_ids: CompanyIdsType = None, start_date: str = None, end_date: str = None, base_currency: str = None, tenant_ids: TenantIdsType = None):
    """Get a detailed expense breakdown by category with each category's % of total spend.
    Always pass explicit ISO start_date and end_date when a period is mentioned.
    Use for: cost structure analysis, budget overrun investigation, opex vs capex split,
    identifying the largest expense drivers. Pair with calculate_pnl for full P&L context."""
    s_iso, e_iso = _resolve_and_sync_period(start_date, end_date)
    return get_expense_breakdown_tool(tenant_ids=tenant_ids, company_ids=company_ids, start_date=s_iso or start_date, end_date=e_iso or end_date, base_currency=base_currency)

@tool
def tax_summary( company_ids: CompanyIdsType = None, base_currency: str = None, tenant_ids: TenantIdsType = None):
    """Calculate net tax position: Output Tax (collected from customers) minus Input Tax (paid to vendors).
    Returns net VAT/tax payable or reclaimable.
    Use for: tax liability assessment, VAT filing preparation, tax health review.
    Follow with expense_breakdown to verify deductible expense categories supporting input tax claims."""
    return get_tax_summary_tool(tenant_ids=tenant_ids, company_ids=company_ids, base_currency=base_currency)

@tool
def detect_anomalies( company_ids: CompanyIdsType = None, tenant_ids: TenantIdsType = None):
    """Audit tool: detect unbalanced journal entries and statistically unusual transactions (significantly outside the normal range).
    Use for: data integrity checks, unexplained spikes, spotting errors, audit preparation.
    Always call this when: trial_balance is unbalanced, balance sheet A≠L+E, or a tool returns
    contradictory data. Also run proactively as part of any full audit sequence."""
    return detect_anomalies_tool(tenant_ids=tenant_ids, company_ids=company_ids)

@tool
def period_comparison( company_ids: CompanyIdsType = None, granularity: str = "month", base_currency: str = None, tenant_ids: TenantIdsType = None):
    """Compare revenue and order counts across consecutive periods with % change calculations.
    granularity options: 'month' (default), 'quarter', 'year'.
    Use for: MoM / QoQ / YoY comparisons, growth rate analysis, identifying peak periods.
    Prefer this over sales_trend when the user wants relative change %, not raw time series values."""
    return get_period_comparison_tool(tenant_ids=tenant_ids, company_ids=company_ids, granularity=granularity, base_currency=base_currency)

# ── Inventory Domain ─────────────────────────
@tool
def inventory_efficiency( company_ids: CompanyIdsType = None, tenant_ids: TenantIdsType = None):
    """Analyze inventory turnover rate and days-on-hand metrics per product category.
    Use for: dead stock identification, overstocking risk, working capital tied up in inventory.
    Compare turnover against benchmarks: >8x/yr excellent, 5–8x good, <2x stagnant/dead stock.
    Run alongside inventory_dashboard_alerts for a complete inventory health picture."""
    return get_inventory_efficiency_tool(tenant_ids=tenant_ids, company_ids=company_ids)

@tool
def inventory_stock_table( table_type: str = None, company_ids: CompanyIdsType = None, limit: Optional[Union[int, str]] = 50, offset: Optional[Union[int, str]] = 0, tenant_ids: TenantIdsType = None):
    """Get stock overview tables. table_type must be one of: 'low_stock', 'out_of_stock', 'negative_stock', 'expiring_soon', 'slow_moving', 'fast_moving'.
    Use for: drill-down into specific inventory conditions after viewing dashboard alerts."""
    return get_inventory_stock_table_tool(tenant_ids=tenant_ids, table_type=table_type, company_ids=company_ids, limit=limit, offset=offset)

@tool
def inventory_dashboard_alerts( company_ids: CompanyIdsType = None, tenant_ids: TenantIdsType = None):
    """Get comprehensive dashboard counts and item details for all 7 inventory alerts:
    low stock below reorder threshold, out of stock, negative stock, expiring soon, slow moving, fast moving, and backorders.
    Use for: stockout risk prevention, low stock warnings, reorder urgencies, lot expiry management, and general inventory risk overview.
    Always use this comprehensive tool first for any inventory alert questions."""
    return get_inventory_dashboard_alerts_tool(tenant_ids=tenant_ids, company_ids=company_ids)

@tool
def inventory_valuation( company_ids: CompanyIdsType = None, tenant_ids: TenantIdsType = None):
    """Get total inventory valuation and a count of products missing cost values.
    Use for: inventory reconciliation, assessing balance sheet asset values."""
    return get_inventory_valuation_tool(tenant_ids=tenant_ids, company_ids=company_ids)

# ── Banking Domain ──

@tool
def bank_cash_summary( start_date: str = None, end_date: str = None, company_ids: CompanyIdsType = None, base_currency: str = None, tenant_ids: TenantIdsType = None):
    """Get high-level bank balance, opening/closing cash balances, and cash flow breakdowns.
    Use for: checking current liquidity, daily banking summaries, top-level cash movements."""
    return get_bank_cash_summary_tool(tenant_ids=tenant_ids, start_date=start_date, end_date=end_date, company_ids=company_ids, base_currency=base_currency)

@tool
def journal_cards( start_date: str = None, end_date: str = None, company_ids: CompanyIdsType = None, base_currency: str = None, tenant_ids: TenantIdsType = None):
    """Get performance cards broken down by Accounting Journal (Bank, Cash, Vendor Bills, etc).
    Use for: journal-level reconciliation and viewing activity across different accounts."""
    return get_journal_cards_tool(tenant_ids=tenant_ids, start_date=start_date, end_date=end_date, company_ids=company_ids, base_currency=base_currency)

@tool
def bank_statement_summary( company_ids: CompanyIdsType = None, tenant_ids: TenantIdsType = None):
    """Get a list of the 20 most recent bank statements with opening and closing balances.
    Use for: checking recent reconciliation activity, verifying bank feeds are up to date."""
    return get_bank_statement_summary_tool(tenant_ids=tenant_ids, company_ids=company_ids)

@tool
def journal_audit( start_date: str = None, end_date: str = None, date_from: str = None, date_to: str = None, company_ids: CompanyIdsType = None, base_currency: str = None, tenant_ids: TenantIdsType = None):
    """Official Journal Audit report matching Odoo Report 20.
    Returns complete debit, credit, and balance summary for all posted accounting journals (Cash, Bank, Invoices, Vendor Bills, Landed Costs, Stock moves, JVs) + Tax Summary breakdown.
    Use for: auditing journal activity, verifying all posted debit/credit balances across journals, and tax due reconciliations."""
    return get_journal_audit_tool(tenant_ids=tenant_ids, start_date=start_date, end_date=end_date, date_from=date_from, date_to=date_to, company_ids=company_ids, base_currency=base_currency)

# ── Purchasing Domain ────────────────────────

@tool
def purchase_summary( company_ids: CompanyIdsType = None, start_date: str = None, end_date: str = None, base_currency: str = None, tenant_ids: TenantIdsType = None):
    """Get total confirmed purchase spend, PO count, and average PO value for a given period.
    Always pass explicit ISO start_date and end_date (YYYY-MM-DD) when a time period is mentioned.
    Use for: total procurement spend, vendor payment totals, purchase volume metrics.
    This is the procurement counterpart to sales_summary — use it whenever procurement questions arise."""
    s_iso, e_iso = _resolve_and_sync_period(start_date, end_date)
    return get_purchase_summary_tool(tenant_ids=tenant_ids, company_ids=company_ids, start_date=s_iso or start_date, end_date=e_iso or end_date, base_currency=base_currency)

@tool
def top_vendors( company_ids: CompanyIdsType = None, start_date: str = None, end_date: str = None, limit: Optional[Union[int, str]] = 10, base_currency: str = None, tenant_ids: TenantIdsType = None):
    """Rank vendors/suppliers by total confirmed purchase spend.
    Returns: vendor name, total spend, PO count, average PO value.
    Use for: 'who are our top suppliers?', 'biggest vendors', 'where are we spending most?',
    vendor concentration risk analysis. Increase limit for broader lists."""
    return get_top_vendors_tool(tenant_ids=tenant_ids, company_ids=company_ids, start_date=start_date, end_date=end_date, limit=limit, base_currency=base_currency)

@tool
def vendor_performance( company_ids: CompanyIdsType = None, limit: Optional[Union[int, str]] = 10, base_currency: str = None, tenant_ids: TenantIdsType = None):
    """Get vendor performance scorecard: on-time delivery rate and average lead time in days.
    Uses purchase orders linked to incoming stock receipts for actual delivery data.
    Use for: 'which suppliers deliver on time?', 'vendor reliability', 'supplier scorecard',
    'who is always late?'. Run after top_vendors for context on which vendors to focus on."""
    return get_vendor_performance_tool(tenant_ids=tenant_ids, company_ids=company_ids, limit=limit, base_currency=base_currency)

@tool
def procurement_spend_by_category( company_ids: CompanyIdsType = None, start_date: str = None, end_date: str = None, limit: Optional[Union[int, str]] = 20, base_currency: str = None, tenant_ids: TenantIdsType = None):
    """Break down procurement spend by product category with % of total spend per category.
    Use for: 'where is our purchase budget going?', 'procurement spend analysis',
    'which categories cost the most?', cost structure review by procurement category.
    The purchasing counterpart to expense_breakdown — shows spend by what we buy, not GL accounts."""
    return get_procurement_category_breakdown_tool(tenant_ids=tenant_ids, company_ids=company_ids, start_date=start_date, end_date=end_date, limit=limit, base_currency=base_currency)

@tool
def purchase_vs_sales_margin( company_ids: CompanyIdsType = None, limit: Optional[Union[int, str]] = 20, base_currency: str = None, tenant_ids: TenantIdsType = None):
    """Compare average buy price vs average sell price per product to reveal true product margins.
    Returns: product name, avg buy price, avg sell price, margin, margin %, qty bought vs qty sold.
    Use for: 'are we buying too expensive?', 'product margin analysis', 'cost vs revenue per product',
    identifying products with shrinking margins. Run after top_products for revenue-side context."""
    return get_purchase_vs_sales_margin_tool(tenant_ids=tenant_ids, company_ids=company_ids, limit=limit, base_currency=base_currency)

@tool
def po_fulfillment( company_ids: CompanyIdsType = None, base_currency: str = None, tenant_ids: TenantIdsType = None):
    """Track PO fulfillment: overdue purchase orders and partial receipts.
    Returns: overdue PO count and value, top late vendors, lines with qty_received < qty_ordered.
    Use for: 'are our orders arriving on time?', 'late deliveries', 'pending receipts',
    'backlog from vendors', supply chain disruption detection. Critical for procurement risk."""
    return get_po_fulfillment_tool(tenant_ids=tenant_ids, company_ids=company_ids, base_currency=base_currency)

@tool
def purchase_trend( company_ids: CompanyIdsType = None, granularity: str = "month", base_currency: str = None, tenant_ids: TenantIdsType = None):
    """Get procurement spend as a time series broken down by period.
    granularity options: 'day', 'week', 'month' (default), 'quarter', 'year'.
    Use for: procurement trend charts, spending trajectory, seasonal procurement patterns.
    The purchasing counterpart to sales_trend — use when the user asks about spend over time."""
    return get_purchase_trend_tool(tenant_ids=tenant_ids, company_ids=company_ids, granularity=granularity, base_currency=base_currency)

@tool
def product_purchase_history(
    product_name: Optional[str] = None,
    vendor_name: Optional[str] = None,
    company_ids: CompanyIdsType = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    limit: Optional[Union[int, str]] = 50,
    base_currency: Optional[str] = None,
    tenant_ids: TenantIdsType = None
):
    """Get detailed purchase order line history and unit purchase costs for specific products or vendors.
    Returns: product name, SKU, vendor name, PO reference, PO date, quantity ordered/received, original currency, unit price, and converted base currency totals.
    Use for: 'what did we pay for Hisense ACs?', 'purchase orders for product X', 'supplier unit cost history', 'average buy price for product'.
    Always use this specialized tool instead of ask_database_custom_question when analyzing specific product purchase costs."""
    return get_product_purchase_history_tool(
        tenant_ids=tenant_ids,
        product_name=product_name,
        vendor_name=vendor_name,
        company_ids=company_ids,
        start_date=start_date,
        end_date=end_date,
        limit=int(limit) if limit else 50,
        base_currency=base_currency
    )

# ── Reporting Domain ─────────────────────────

@tool
def create_report(
    custom_content: Optional[str] = None,
    company_ids: CompanyIdsType = None,
    tenant_ids: TenantIdsType = None,
    logo_path: Optional[str] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    reporting_period: Optional[str] = None,
    comparison_label: Optional[str] = None,
    base_currency: Optional[str] = None,
    report_type: Optional[str] = "health",
    report_data: Optional[dict] = None,
    prompt: Optional[str] = None,
):
    """MANDATORY: When the user asks to 'generate a report' or 'create a report', you MUST call this tool.
    Generate a professional branded PDF executive report including vital signs and your analysis.
    Pass your full markdown report analysis into the `custom_content` parameter if available.
    Pass explicit `start_date` and `end_date` (ISO 'YYYY-MM-DD') and `reporting_period` (e.g. 'Aug 01, 2026 – Aug 31, 2026' or 'Q2 2026') resolved from the user prompt or conversation history per STEP 0B. If no timeframe was specified, default start_date to Jan 01 of current year and end_date to today.
    Pass `comparison_label` (e.g. 'Prior Month (MoM)', 'Prior Quarter (QoQ)', 'Same Period Prior Year (YoY)') if specified or leave None to auto-infer from date delta.
    Pass `base_currency` (e.g. 'USD', 'EUR') if the user requested a specific currency.
    Pass `report_type` (e.g. 'sales', 'purchase', 'inventory', 'cashflow', 'health', 'financial_analysis', etc.) if applicable.
    Pass `report_data` dictionary with structured KPIs, table rows, and charts if available.
    Pass original user message or intent into `prompt` if available.
    Do NOT output the report directly in the chat text. Pass it ALL into `custom_content`.
    Do NOT call this before you have gathered the data — the report cannot be regenerated mid-session."""
    
    # Check active session date window if dates omitted
    from .session_context import get_active_date_window, update_active_date_window
    if not start_date and not end_date:
        active = get_active_date_window()
        if active:
            start_date = active.get("start_date")
            end_date = active.get("end_date")

    # Resolve reporting period & ISO dates deterministically via date_engine
    s_iso, e_iso, auto_period_label = resolve_period_dates(
        text=prompt or custom_content,
        start_date=start_date,
        end_date=end_date,
    )
    resolved_rep_period = reporting_period or auto_period_label
    if s_iso and e_iso:
        update_active_date_window(s_iso, e_iso, resolved_rep_period)

    # Generate the report. If custom_content is missing, it will use the default automated summary.
    result = generate_report_tool(
        tenant_ids=tenant_ids,
        company_ids=company_ids,
        custom_content=custom_content,
        logo_path=logo_path,
        start_date=s_iso or start_date,
        end_date=e_iso or end_date,
        reporting_period=resolved_rep_period,
        comparison_label=comparison_label,
        base_currency=base_currency,
        report_type=report_type,
        report_data=report_data,
        prompt=prompt,
    )
    url = result.get("download_url", "")
    
    # Return a loud, explicit string to Claude so it stops looping and responds to the user!
    return (
        f"SUCCESS! The report has been successfully generated and saved.\n"
        f"Download URL: {url}\n"
        f"[📥 **Download Full PDF Report**]({url})\n\n"
        f"CRITICAL INSTRUCTION: You must now STOP calling tools. Do NOT call create_report again. "
        f"Output your final response to the user containing this download link."
    )

@tool
def get_latest_report( company_ids: CompanyIdsType = None, tenant_ids: TenantIdsType = None):
    """Retrieve the download URL for the most recently generated PDF report for this tenant.
    Use when the user asks 'give me the report', 'download the last report', or 'send me the PDF'.
    If no report exists, suggest calling create_report first."""
    return get_last_report_tool(tenant_ids=tenant_ids, company_ids=company_ids)

# ── Communication Domain ─────────────────────

@tool
def send_alert( title: str = None, message: str = None, company_ids: CompanyIdsType = None, tenant_ids: TenantIdsType = None):
    """Send a real-time notification alert to the user's dashboard.
    Use when the user asks to be notified, or when a critical risk (e.g., overdue AR >30%, liquidity critical)
    warrants immediate dashboard notification. title should be ≤10 words; message should be ≤2 sentences."""
    return send_alert_tool(tenant_ids=tenant_ids, title=title, message=message, company_ids=company_ids)

@tool
def send_email( to_email: str = None, subject: str = None, body: str = None, company_ids: CompanyIdsType = None, tenant_ids: TenantIdsType = None):
    """Prepare and queue an email to a specified recipient.
    Use only when the user explicitly requests an email to be sent — never send without clear instruction.
    body should be professional, concise, and include the key findings from your analysis."""
    return send_email_tool(tenant_ids=tenant_ids, to_email=to_email, subject=subject, body=body, company_ids=company_ids)

@tool
def cash_flow_statement( company_ids: CompanyIdsType = None, start_date: str = None, end_date: str = None, base_currency: str = None, tenant_ids: TenantIdsType = None):
    """Generate a standard Cash Flow Statement (Operating, Investing, Financing activities).
    Use for: 'where is the cash going?', 'cash flow summary', 'liquidity analysis'.
    Returns net cash from operations, investments, and financing, and the net change in cash."""
    s_iso, e_iso = _resolve_and_sync_period(start_date, end_date)
    return get_cash_flow_statement_tool(tenant_ids=tenant_ids, company_ids=company_ids, start_date=s_iso or start_date, end_date=e_iso or end_date, base_currency=base_currency)

@tool
def working_capital_efficiency( company_ids: CompanyIdsType = None, base_currency: str = None, tenant_ids: TenantIdsType = None):
    """Calculate Cash Conversion Cycle (CCC), Days Sales Outstanding (DSO), Days Inventory Outstanding (DIO), and Days Payable Outstanding (DPO).
    Use for: working capital analysis, cash cycle duration, how fast we turn inventory into cash."""
    return get_working_capital_efficiency_tool(tenant_ids=tenant_ids, company_ids=company_ids, base_currency=base_currency)

@tool
def period_comparison_pnl(
    current_start: Optional[str] = None,
    current_end: Optional[str] = None,
    prior_start: Optional[str] = None,
    prior_end: Optional[str] = None,
    company_ids: CompanyIdsType = None,
    base_currency: str = None,
    tenant_ids: TenantIdsType = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    comparison_label: Optional[str] = None,
):
    """Perform a variance analysis comparing P&L across two distinct periods (e.g. this month vs last month, this year vs last year, Q3 vs Q2).
    Returns detailed variances for Revenue, COGS, Gross Profit, Expenses, and Net Profit.
    If prior_start and prior_end are omitted, they will be automatically and deterministically calculated from current_start and current_end."""
    c_s = current_start or start_date
    c_e = current_end or end_date
    c_s_iso, c_e_iso, _ = resolve_period_dates(start_date=c_s, end_date=c_e) if (c_s or c_e) else (c_s, c_e, None)

    if not prior_start or not prior_end:
        p_s_iso, p_e_iso, _ = resolve_comparison_dates(c_s_iso, c_e_iso, comparison_label=comparison_label)
    else:
        p_s_iso, p_e_iso, _ = resolve_period_dates(start_date=prior_start, end_date=prior_end)

    return get_period_comparison_pnl_tool(
        tenant_ids=tenant_ids,
        period1_start=c_s_iso,
        period1_end=c_e_iso,
        period2_start=p_s_iso,
        period2_end=p_e_iso,
        company_ids=company_ids,
        base_currency=base_currency,
    )

@tool
def interest_coverage( company_ids: CompanyIdsType = None, start_date: str = None, end_date: str = None, base_currency: str = None, tenant_ids: TenantIdsType = None):
    """Calculate the Interest Coverage Ratio (EBIT / Interest Expense).
    Use for: debt service capacity, risk of default, ability to pay interest."""
    return get_interest_coverage_tool(tenant_ids=tenant_ids, company_ids=company_ids, start_date=start_date, end_date=end_date, base_currency=base_currency)

@tool
def revenue_segmentation( company_ids: CompanyIdsType = None, segment_by: str = "customer", start_date: str = None, end_date: str = None, limit: Optional[Union[int, str]] = 10, base_currency: str = None, tenant_ids: TenantIdsType = None):
    """Break down total revenue by 'customer' or 'journal'.
    Use for: customer concentration risk, revenue streams, top clients by invoice revenue."""
    return get_revenue_segmentation_tool(tenant_ids=tenant_ids, company_ids=company_ids, segment_by=segment_by, start_date=start_date, end_date=end_date, limit=limit, base_currency=base_currency)

@tool
def payment_reconciliation( company_ids: CompanyIdsType = None, base_currency: str = None, tenant_ids: TenantIdsType = None):
    """Identify unreconciled customer payments (payments received but not applied to an invoice).
    Use for: 'unapplied cash', 'payments not matched', 'AR reconciliation issues'."""
    return get_payment_reconciliation_tool(tenant_ids=tenant_ids, company_ids=company_ids, base_currency=base_currency)

# ── Phase 4: Inventory & Operations ─────────────────

@tool
def reorder_recommendations( company_ids: CompanyIdsType = None, days_history: Optional[Union[int, str]] = 30, tenant_ids: TenantIdsType = None):
    """Recommend reorder quantities for products where current stock is too low compared to recent sales velocity.
    Use for: 'what should we order?', 'low stock warnings', 'replenishment suggestions'."""
    return get_reorder_recommendations_tool(tenant_ids=tenant_ids, company_ids=company_ids, days_history=days_history)

@tool
def abc_analysis( company_ids: CompanyIdsType = None, tenant_ids: TenantIdsType = None):
    """Classify inventory into A (high value), B (medium), and C (low) categories based on revenue contribution.
    Use for: 'inventory classification', 'what are our most important products?', 'ABC analysis'."""
    return get_abc_analysis_tool(tenant_ids=tenant_ids, company_ids=company_ids)

@tool
def warehouse_utilization( company_ids: CompanyIdsType = None, tenant_ids: TenantIdsType = None):
    """Analyze stock quantities and valuation grouped by physical warehouse location.
    Use for: 'stock by location', 'warehouse value', 'where is our inventory?'."""
    return get_warehouse_utilization_tool(tenant_ids=tenant_ids, company_ids=company_ids)

@tool
def fulfillment_rate( company_ids: CompanyIdsType = None, tenant_ids: TenantIdsType = None):
    """Calculate the percentage of outgoing deliveries that were delivered on-time.
    Use for: 'fulfillment rate', 'on time delivery', 'shipping performance'."""
    return get_fulfillment_rate_tool(tenant_ids=tenant_ids, company_ids=company_ids)

@tool
def backorder_aging( company_ids: CompanyIdsType = None, tenant_ids: TenantIdsType = None):
    """Identify the oldest unfulfilled stock moves (backorders) and their aging in days.
    Use for: 'oldest backorders', 'pending shipments', 'what orders are delayed?'."""
    return get_backorder_aging_tool(tenant_ids=tenant_ids, company_ids=company_ids)

@tool
def supplier_lead_time( company_ids: CompanyIdsType = None, tenant_ids: TenantIdsType = None):
    """Calculate average actual lead time vs scheduled for incoming stock pickings by supplier.
    Use for: 'which suppliers are late?', 'supplier delivery performance', 'average delay'."""
    return get_supplier_lead_time_tool(tenant_ids=tenant_ids, company_ids=company_ids)

@tool
def consult_strategic_advisor(
    problem_type: str = None,
    question: str = None,
    context_details: Optional[str] = "",
) -> str:
    """Consult the high-reasoning Strategic Financial & Technical Advisor.
    Use for:
    - 'sql_planning': Planning multi-table SQL joins across reconciliations, moves, and orders.
    - 'error_diagnosis': Diagnosing why a query or calculation failed and getting the exact corrected SQL.
    - 'financial_strategy': Formulating CFO-grade anomaly assessments, working capital optimization, and executive actions."""
    from .advisor_tool import consult_strategic_advisor_tool
    return consult_strategic_advisor_tool(problem_type=problem_type, question=question, context_details=context_details or "")

# ── Consolidated Agent Tools ─────────────────

agent_tools = [
    # Discovery
    ask_database_custom_question, list_companies, tenant_profile,
    # Sales
    sales_summary, top_products, sales_trend, variance_analysis, sales_forecast,
    salesperson_performance, sales_pipeline, discount_leakage, customer_lifetime_value, order_to_cash_cycle, revenue_by_category,
    # Finance — Core Statements
    executive_summary, calculate_pnl, balance_sheet, trial_balance, general_ledger, partner_ledger, customer_statement, followup_report, cash_flow_statement,
    # Finance — Analysis
    financial_ratios, working_capital, expense_breakdown, working_capital_efficiency, interest_coverage, period_comparison_pnl,
    # Finance — AR/AP & Cash
    receivables_analysis, payables_analysis, aging_analysis, unrealized_currency_gains_losses, cash_flow_health, payment_reconciliation,
    # Finance — Tax & Audit
    tax_summary, detect_anomalies,
    # Finance — Intelligence
    period_comparison, business_health, customer_metrics, revenue_segmentation,
    # Banking
    bank_cash_summary, journal_cards, bank_statement_summary, journal_audit,
    # Purchasing
    purchase_summary, top_vendors, vendor_performance,
    procurement_spend_by_category, purchase_vs_sales_margin,
    po_fulfillment, purchase_trend, product_purchase_history,
    # Inventory
    inventory_efficiency, inventory_stock_table, inventory_dashboard_alerts, inventory_valuation,
    reorder_recommendations, abc_analysis, warehouse_utilization, fulfillment_rate, backorder_aging, supplier_lead_time,
    # Reporting & Communication
    create_report, get_latest_report, send_alert, send_email,
]

from .config import AgentConfig
if getattr(AgentConfig, "ENABLE_ADVISOR_TOOL", False):
    agent_tools.append(consult_strategic_advisor)

