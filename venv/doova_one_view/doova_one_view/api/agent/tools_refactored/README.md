# Doova Agent Tools: Refactored Financial Intelligence

This directory contains the modularized "hands" of the Finance Brain. These tools are high-level Python functions that interact with the Odoo database to provide structured financial insights.

## 📂 Module Breakdown

- **`finance.py`**: The largest module. Implements core accounting logic:
  - Profit and Loss (P&L) generation
  - Balance Sheet and Trial Balance
  - Financial Ratios (Liquidity, Solvency, Profitability)
  - Business Health Scoring
- **`sales.py`**: Revenue intelligence:
  - Top products and customers
  - Sales trend analysis
  - Margin analysis per product/category
- **`inventory.py`**: Supply chain efficiency:
  - Inventory valuation
  - SKU turnover rates
  - Low stock alerts
- **`reporting.py`**: Document generation:
  - AI-authored PDF report generation using `ReportLab`
  - Automated executive summaries
- **`communication.py`**: External integrations:
  - Emailing reports to stakeholders
- **`common.py`**: Base utilities for data normalization, SQL execution, and tenant context handling.

## 🛠 Tool Development Guidelines

1. **Tenant Isolation**: Every tool must accept a `tenant_id` and ensure all SQL queries filter by it.
2. **Schema Accuracy**: Tools should primarily query the "fact" and "dim" tables (e.g., `fact_sales_orders`, `dim_products`) to ensure consistency.
3. **Structured Returns**: Tools should return clean, descriptive strings or structured dictionaries that the LLM can easily interpret.
4. **Error Handling**: Use the common error logging patterns to ensure failures are captured in `agent_execution.log`.
