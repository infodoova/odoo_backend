# api/agent/tools_refactored/template_registry.py

"""
Domain-Specific Report Templates Registry (Pro Plan v3 — Agent-Driven).

Defines metadata, KPI slots, table slots, and NLP keyword routing for all 12 domain templates
plus legacy health report compatibility.
"""

from typing import Dict, Any, List

TEMPLATE_REGISTRY: Dict[str, Dict[str, Any]] = {
    "sales": {
        "template_file": "sales_report.html",
        "badge": "Sales & Revenue",
        "title": "Sales Performance Report",
        "subtitle": "Revenue analysis, customer insights, volume trends, and product performance.",
        "accent": "#2563eb",
        "kpi_slots": [
            {"key": "revenue", "label": "Total Revenue", "bar_class": "bar-blue"},
            {"key": "sales_volume", "label": "Sales Volume / Units", "bar_class": "bar-cyan"},
            {"key": "avg_order_value", "label": "Avg Order Value", "bar_class": "bar-green"},
            {"key": "revenue_growth", "label": "Revenue Growth", "bar_class": "bar-purple"},
            {"key": "top_customer_revenue", "label": "Top Customer Spend", "bar_class": "bar-amber"},
            {"key": "target_achievement", "label": "Target Achievement", "bar_class": "bar-green"},
        ],
        "table_slots": ["top_products", "top_customers", "sales_by_person"],
        "chart_types": ["trend", "waterfall"],
        "nlp_keywords": [
            "sales", "revenue", "commercial", "orders", "top selling", "top products",
            "customers", "pipeline", "merchandise", "sales performance", "units sold", "sales volume"
        ],
        "aliases": ["commercial", "revenue", "sales_performance", "merchandise"],
    },
    "purchase": {
        "template_file": "purchase_report.html",
        "badge": "Procurement & Supply",
        "title": "Procurement & Purchase Report",
        "subtitle": "Vendor spend, purchase order velocity, supplier concentration, and payables aging.",
        "accent": "#7c3aed",
        "kpi_slots": [
            {"key": "total_purchases", "label": "Total Purchase Spend", "bar_class": "bar-purple"},
            {"key": "po_count", "label": "Active PO Count", "bar_class": "bar-blue"},
            {"key": "avg_po_value", "label": "Avg PO Value", "bar_class": "bar-cyan"},
            {"key": "accounts_payable", "label": "Total Accounts Payable", "bar_class": "bar-red"},
            {"key": "overdue_payables_pct", "label": "Overdue Payables %", "bar_class": "bar-amber"},
            {"key": "top_supplier_spend", "label": "Top Vendor Spend", "bar_class": "bar-purple"},
        ],
        "table_slots": ["top_suppliers", "po_status", "ap_aging"],
        "chart_types": ["trend", "vendor_spend"],
        "nlp_keywords": [
            "purchase", "purchases", "procurement", "po", "purchase order", "suppliers",
            "vendors", "vendor spend", "ap", "accounts payable", "buying", "sourcing"
        ],
        "aliases": ["purchases", "procurement", "vendor", "supplier", "sourcing"],
    },
    "cashflow": {
        "template_file": "cashflow_report.html",
        "badge": "Liquidity & Treasury",
        "title": "Cash Flow & Treasury Report",
        "subtitle": "Operating, investing, and financing cash movements, bank balances, and liquidity runway.",
        "accent": "#059669",
        "kpi_slots": [
            {"key": "cash_balance", "label": "Liquid Cash & Bank", "bar_class": "bar-green"},
            {"key": "cash_from_operations", "label": "Operating Cash Flow", "bar_class": "bar-blue"},
            {"key": "cash_from_investing", "label": "Investing Cash Flow", "bar_class": "bar-cyan"},
            {"key": "cash_from_financing", "label": "Financing Cash Flow", "bar_class": "bar-purple"},
            {"key": "net_cash_movement", "label": "Net Cash Movement", "bar_class": "bar-green"},
            {"key": "cash_runway", "label": "Cash Runway (Months)", "bar_class": "bar-amber"},
        ],
        "table_slots": ["cash_inflows", "cash_outflows", "bank_balances"],
        "chart_types": ["trend", "cash_bridge"],
        "nlp_keywords": [
            "cash", "cashflow", "cash flow", "liquidity", "bank", "treasury", "disbursement",
            "collection", "runway", "operating cash", "cash balance", "bank balance"
        ],
        "aliases": ["cash_flow", "treasury", "liquidity", "bank"],
    },
    "inventory": {
        "template_file": "inventory_report.html",
        "badge": "Stock & Warehousing",
        "title": "Inventory & Warehouse Health Report",
        "subtitle": "Stock valuation, inventory turnover velocity, days on hand, and reorder risk controls.",
        "accent": "#ea580c",
        "kpi_slots": [
            {"key": "inventory_value", "label": "Total Stock Valuation", "bar_class": "bar-amber"},
            {"key": "sku_count", "label": "Active SKU Count", "bar_class": "bar-blue"},
            {"key": "stock_turnover", "label": "Inventory Turnover", "bar_class": "bar-green"},
            {"key": "days_on_hand", "label": "Days Inventory (DIO)", "bar_class": "bar-cyan"},
            {"key": "low_stock_count", "label": "Stockout Risk SKUs", "bar_class": "bar-red"},
            {"key": "dead_stock_value", "label": "Slow / Dead Stock Value", "bar_class": "bar-red"},
        ],
        "table_slots": ["top_inventory_items", "low_stock_alerts", "slow_moving", "warehouse_distribution"],
        "chart_types": ["stock_aging", "category_valuation"],
        "nlp_keywords": [
            "inventory", "stock", "warehouse", "skus", "dio", "turnover", "stockout",
            "reorder", "low stock", "dead stock", "stock valuation", "supply chain"
        ],
        "aliases": ["stock", "warehouse", "supply_chain", "logistics"],
    },
    "income_statement": {
        "template_file": "income_statement_report.html",
        "badge": "Income Statement",
        "title": "Comprehensive Income Statement",
        "subtitle": "Revenue performance, cost of goods, operating expenses, and net profit retention.",
        "accent": "#0284c7",
        "kpi_slots": [
            {"key": "revenue", "label": "Total Revenue", "bar_class": "bar-blue"},
            {"key": "cogs", "label": "Cost of Goods (COGS)", "bar_class": "bar-amber"},
            {"key": "gross_profit", "label": "Gross Profit", "bar_class": "bar-green"},
            {"key": "operating_expenses", "label": "Operating Expenses (OpEx)", "bar_class": "bar-purple"},
            {"key": "ebit", "label": "Operating Profit (EBIT)", "bar_class": "bar-cyan"},
            {"key": "net_profit", "label": "Net Profit / Loss", "bar_class": "bar-green"},
        ],
        "table_slots": ["pnl_statement", "expense_breakdown"],
        "chart_types": ["waterfall", "trend"],
        "nlp_keywords": [
            "income statement", "pnl", "p&l", "profit and loss", "ebit", "ebitda",
            "gross margin", "net profit", "cogs", "operating profit", "financial statement"
        ],
        "aliases": ["pnl", "p_and_l", "profit_loss", "income_statement"],
    },
    "balance_sheet": {
        "template_file": "balance_sheet_report.html",
        "badge": "Balance Sheet",
        "title": "Balance Sheet & Financial Position",
        "subtitle": "Asset structure, debt and liabilities profile, working capital, and equity capitalization.",
        "accent": "#0f766e",
        "kpi_slots": [
            {"key": "total_assets", "label": "Total Assets", "bar_class": "bar-blue"},
            {"key": "current_assets", "label": "Current Assets", "bar_class": "bar-cyan"},
            {"key": "total_liabilities", "label": "Total Liabilities", "bar_class": "bar-red"},
            {"key": "equity", "label": "Total Equity", "bar_class": "bar-green"},
            {"key": "current_ratio", "label": "Current Ratio", "bar_class": "bar-purple"},
            {"key": "nwc", "label": "Net Working Capital", "bar_class": "bar-green"},
        ],
        "table_slots": ["balance_sheet", "working_capital_details"],
        "chart_types": ["asset_liability_split", "working_capital"],
        "nlp_keywords": [
            "balance sheet", "assets", "liabilities", "equity", "current ratio", "solvency",
            "net worth", "capital structure", "financial position", "working capital"
        ],
        "aliases": ["balance_sheet", "bs", "financial_position", "solvency"],
    },
    "financial_analysis": {
        "template_file": "financial_analysis_report.html",
        "badge": "Financial Analysis",
        "title": "Financial Ratio & Health Analysis",
        "subtitle": "Profitability, liquidity, leverage, efficiency ratios, and multi-factor health index.",
        "accent": "#be123c",
        "kpi_slots": [
            {"key": "health_score", "label": "Business Health Score", "bar_class": "bar-green"},
            {"key": "gross_margin", "label": "Gross Margin %", "bar_class": "bar-blue"},
            {"key": "net_margin", "label": "Net Profit Margin %", "bar_class": "bar-green"},
            {"key": "current_ratio", "label": "Current Ratio", "bar_class": "bar-cyan"},
            {"key": "quick_ratio", "label": "Quick / Acid Ratio", "bar_class": "bar-purple"},
            {"key": "roe", "label": "Return on Equity (ROE)", "bar_class": "bar-amber"},
        ],
        "table_slots": ["profitability_ratios", "liquidity_ratios", "leverage_ratios", "activity_ratios"],
        "chart_types": ["ratio_benchmarks", "health_breakdown"],
        "nlp_keywords": [
            "financial analysis", "ratios", "financial ratios", "health score", "profitability",
            "efficiency", "leverage", "roe", "roa", "quick ratio", "dupont"
        ],
        "aliases": ["analysis", "ratios", "financial_health", "financial_analysis"],
    },
    "monthly_pnl": {
        "template_file": "monthly_pnl_report.html",
        "badge": "Monthly Performance",
        "title": "Monthly P&L & Seasonality Grid",
        "subtitle": "Month-by-month revenue, expense run-rates, seasonality, and variance trajectories.",
        "accent": "#4f46e5",
        "kpi_slots": [
            {"key": "ytd_revenue", "label": "YTD Revenue", "bar_class": "bar-blue"},
            {"key": "ytd_gross_profit", "label": "YTD Gross Profit", "bar_class": "bar-cyan"},
            {"key": "ytd_opex", "label": "YTD OpEx Baseline", "bar_class": "bar-amber"},
            {"key": "ytd_net_profit", "label": "YTD Net Profit", "bar_class": "bar-green"},
            {"key": "avg_monthly_rev", "label": "Avg Monthly Revenue", "bar_class": "bar-purple"},
            {"key": "best_month", "label": "Peak Revenue Month", "bar_class": "bar-green"},
        ],
        "table_slots": ["monthly_data", "quarterly_summary"],
        "chart_types": ["monthly_trend", "seasonal_bars"],
        "nlp_keywords": [
            "monthly", "monthly pnl", "monthly p&l", "seasonality", "month by month",
            "12 month", "run rate", "annual trend", "monthly revenue", "quarterly"
        ],
        "aliases": ["monthly", "seasonality", "monthly_pnl", "monthly_summary"],
    },
    "proforma": {
        "template_file": "proforma_report.html",
        "badge": "Financial Forecast",
        "title": "Pro Forma & Growth Projections",
        "subtitle": "Forward-looking revenue forecast, expense modeling, scenario analysis, and targets.",
        "accent": "#9333ea",
        "kpi_slots": [
            {"key": "projected_revenue", "label": "Projected Revenue", "bar_class": "bar-purple"},
            {"key": "projected_growth", "label": "Projected Growth %", "bar_class": "bar-blue"},
            {"key": "projected_margin", "label": "Projected Margin %", "bar_class": "bar-cyan"},
            {"key": "projected_net_profit", "label": "Projected Net Profit", "bar_class": "bar-green"},
            {"key": "projected_cash", "label": "Projected Cash Position", "bar_class": "bar-green"},
            {"key": "projection_confidence", "label": "Confidence Level", "bar_class": "bar-amber"},
        ],
        "table_slots": ["proforma_pnl", "proforma_scenarios", "action_steps"],
        "chart_types": ["forecast_trend", "scenario_comparison"],
        "nlp_keywords": [
            "proforma", "pro forma", "forecast", "projection", "projections", "predict",
            "future", "scenario", "outlook", "target", "budget forecast", "model"
        ],
        "aliases": ["forecast", "projections", "proforma", "predictive"],
    },
    "consolidated": {
        "template_file": "consolidated_report.html",
        "badge": "Consolidated Financials",
        "title": "Consolidated Financial Statements",
        "subtitle": "Full corporate pack combining P&L, balance sheet, cash flow, and multi-entity metrics.",
        "accent": "#0f172a",
        "kpi_slots": [
            {"key": "revenue", "label": "Gross Revenue", "bar_class": "bar-blue"},
            {"key": "gross_profit", "label": "Gross Profit", "bar_class": "bar-cyan"},
            {"key": "net_profit", "label": "Net Profit", "bar_class": "bar-green"},
            {"key": "total_assets", "label": "Total Assets", "bar_class": "bar-purple"},
            {"key": "total_liabilities", "label": "Total Liabilities", "bar_class": "bar-red"},
            {"key": "cash_balance", "label": "Cash Reserves", "bar_class": "bar-green"},
        ],
        "table_slots": ["pnl_statement", "balance_sheet", "cashflow_statement", "key_ratios"],
        "chart_types": ["waterfall", "trend", "working_capital"],
        "nlp_keywords": [
            "consolidated", "all statements", "financial pack", "board pack",
            "complete financials", "master report", "full financial statements", "group financials"
        ],
        "aliases": ["consolidated", "board_pack", "financial_pack", "complete"],
    },
    "accounting": {
        "template_file": "accounting_report.html",
        "badge": "General Ledger",
        "title": "Accounting & Ledger Integrity Report",
        "subtitle": "Trial balance health, debtor/creditor aging, journal consistency, and control checks.",
        "accent": "#475569",
        "kpi_slots": [
            {"key": "revenue", "label": "Posted Income", "bar_class": "bar-blue"},
            {"key": "total_expenses", "label": "Posted Expenses", "bar_class": "bar-amber"},
            {"key": "net_profit", "label": "Net Result", "bar_class": "bar-green"},
            {"key": "total_assets", "label": "GL Asset Balance", "bar_class": "bar-cyan"},
            {"key": "accounts_receivable", "label": "Open AR (Debtors)", "bar_class": "bar-purple"},
            {"key": "accounts_payable", "label": "Open AP (Creditors)", "bar_class": "bar-red"},
        ],
        "table_slots": ["annual_summary", "ar_aging", "ap_aging", "expense_breakdown", "audit_findings"],
        "chart_types": ["aging_breakdown", "expense_distribution"],
        "nlp_keywords": [
            "accounting", "audit", "general ledger", "gl", "trial balance", "journal",
            "integrity", "reconciliation", "compliance", "aging", "ledger", "bookkeeping"
        ],
        "aliases": ["accounting", "audit", "gl", "ledger", "compliance", "integrity"],
    },
    "general": {
        "template_file": "general_report.html",
        "badge": "Executive Intelligence",
        "title": "Business Intelligence Briefing",
        "subtitle": "Operational snapshot, executive findings, core vital signs, and strategic takeaways.",
        "accent": "#2563eb",
        "kpi_slots": [
            {"key": "revenue", "label": "Total Revenue", "bar_class": "bar-blue"},
            {"key": "gross_profit", "label": "Gross Profit", "bar_class": "bar-cyan"},
            {"key": "net_profit", "label": "Net Profit", "bar_class": "bar-green"},
            {"key": "cash_balance", "label": "Liquid Cash", "bar_class": "bar-green"},
            {"key": "accounts_receivable", "label": "Receivables (AR)", "bar_class": "bar-amber"},
            {"key": "accounts_payable", "label": "Payables (AP)", "bar_class": "bar-red"},
        ],
        "table_slots": ["top_products", "management_alerts"],
        "chart_types": ["trend"],
        "nlp_keywords": [
            "general", "executive brief", "briefing", "intelligence", "overview",
            "business summary", "management summary", "snapshot", "status"
        ],
        "aliases": ["general", "briefing", "intelligence", "executive_brief", "snapshot"],
    },
    "health": {
        "template_file": "report_template.html",
        "badge": "Finance & Operations",
        "title": "Executive Business Health Report",
        "subtitle": "Financial performance, liquidity, working capital, and management action.",
        "accent": "#2563eb",
        "kpi_slots": [
            {"key": "revenue", "label": "Revenue", "bar_class": "bar-blue"},
            {"key": "gross_profit", "label": "Gross Profit", "bar_class": "bar-cyan"},
            {"key": "gross_margin", "label": "Gross Margin %", "bar_class": "bar-green"},
            {"key": "opex", "label": "Operating Expenses", "bar_class": "bar-amber"},
            {"key": "ebit", "label": "Operating Profit (EBIT)", "bar_class": "bar-purple"},
            {"key": "net_profit", "label": "Net Profit", "bar_class": "bar-green"},
        ],
        "table_slots": ["company_comparison", "drivers", "alerts"],
        "chart_types": ["trend", "waterfall", "working_capital"],
        "nlp_keywords": [
            "health", "business health", "vital signs", "health score", "executive health"
        ],
        "aliases": ["health", "executive_health", "business_health"],
    }
}


def get_template_metadata(template_key: str) -> Dict[str, Any]:
    """Retrieves metadata dict for given template key, falling back to 'general'."""
    key = template_key.lower().strip() if template_key else "general"
    if key in TEMPLATE_REGISTRY:
        return TEMPLATE_REGISTRY[key]
    
    # Check aliases
    for k, meta in TEMPLATE_REGISTRY.items():
        if key in meta.get("aliases", []):
            return meta
            
    return TEMPLATE_REGISTRY["general"]
