"""
SQL Agent – converts natural language questions into safe PostgreSQL queries.
Uses a multi-pass workflow to generate, execute, and explain results.
"""

import os
import re
from typing import Any
import anthropic
from .db import run_query
from .config import AgentConfig


from .prompts import SQL_AGENT_SYSTEM_PROMPT, SQL_FINAL_RESPONSE_PROMPT

BLOCKED_SQL_WORDS = [
    "insert",
    "update",
    "delete",
    "drop",
    "alter",
    "truncate",
    "create",
    "grant",
    "revoke",
    "merge",
    "copy",
    "replace",
    "vacuum",
    "analyze",
]

# Semantic annotations for known tables — injected alongside the raw schema so
# the SQL agent knows which columns to use for dates, tenant isolation, and joins.
_TABLE_SEMANTIC_NOTES: dict[str, str] = {
    "fact_sales_orders": (
        "Sales transaction records. "
        "DATE column: date_order (YYYY-MM-DD). "
        "Filter active orders with: state IN ('sale', 'done'). "
        "Revenue column: amount_total. "
        "ALWAYS filter with tenant_id AND company_id."
    ),
    "fact_account_move_lines": (
        "General Ledger journal entry line items. "
        "DATE column: date. "
        "Debit column: debit, Credit column: credit, Balance column: balance. "
        "Links to chart of accounts via account_id. "
        "ALWAYS filter with tenant_id AND company_id."
    ),

    "fact_stock_moves": (
        "Inventory movement records (in/out/transfer). "
        "DATE column: date. Quantity column: product_qty. "
        "state: 'done' for completed moves. "
        "ALWAYS filter with tenant_id AND company_id."
    ),
    "fact_stock_quants": (
        "Current inventory on-hand quantities per product and location. "
        "Quantity column: quantity. Reserved column: reserved_quantity. "
        "Available = quantity - reserved_quantity. "
        "ALWAYS filter with tenant_id AND company_id."
    ),

    "dim_companies": (
        "Company master data dimension. "
        "Internal primary key: id. Odoo external ID: odoo_id. "
        "Use odoo_id to join against company_id columns in fact tables. "
        "Currency column: currency_name. ALWAYS filter with tenant_id."
    ),
    "dim_products": (
        "Product catalog dimension. "
        "product_type: 'product' (physical/storable), 'service', 'consu' (consumable). "
        "Internal primary key: id. Odoo external ID: odoo_id. "
        "ALWAYS filter with tenant_id."
    ),
    "dim_partners": (
        "Customer and vendor master data. "
        "customer_rank > 0 identifies customers. supplier_rank > 0 identifies vendors. "
        "Internal primary key: id. Odoo external ID: odoo_id. "
        "ALWAYS filter with tenant_id."
    ),
    "dim_lots": (
        "Inventory lot and serial number master data. "
        "expiration_date column tracks lot expiry. "
        "ALWAYS filter with tenant_id."
    ),
    "fact_purchase_orders": (
        "Purchase transaction records (PO). "
        "DATE column: date_order (YYYY-MM-DD). "
        "state: 'purchase' or 'done' for active orders. "
        "Total amount column: amount_total. "
        "ALWAYS filter with tenant_id AND company_id."
    ),
    "fact_purchase_order_lines": (
        "Line items for purchase orders. "
        "Quantity column: product_qty. Price column: price_unit. Subtotal column: price_subtotal. "
        "Links to fact_purchase_orders via purchase_order_id. "
        "ALWAYS filter with tenant_id AND company_id."
    ),
    "fact_sales_order_lines": (
        "Line items for sales orders. "
        "Quantity column: product_uom_qty. Price column: price_unit. Subtotal column: price_subtotal. "
        "Links to fact_sales_orders via sales_order_id. "
        "ALWAYS filter with tenant_id AND company_id."
    ),
    "fact_stock_pickings": (
        "Inventory transfers and operations (receipts, deliveries, internal moves). "
        "DATE columns: scheduled_date, date_done. "
        "state: 'done' for completed transfers. "
        "ALWAYS filter with tenant_id AND company_id."
    ),
    "dim_product_categories": (
        "Hierarchy of product categories. "
        "Internal primary key: id. Odoo external ID: odoo_id. "
        "ALWAYS filter with tenant_id."
    ),
    "dim_currencies": (
        "Master data for currencies used in the system. "
        "Currency code column: code. "
        "ALWAYS filter with tenant_id."
    ),
    "dim_currency_rates": (
        "Historical exchange rates for currencies. "
        "Rate column: rate (relative to base currency). "
        "ALWAYS filter with tenant_id AND company_id."
    ),
    "fact_account_moves": (
        "Base table for all accounting journal entries, invoices, and bills (often queried via fact_invoices view). "
        "DATE column: date. "
        "state: 'posted' for confirmed entries. "
        "ALWAYS filter with tenant_id AND company_id."
    ),
    "dim_chart_of_accounts": (
        "Chart of accounts dimension (physical table backing dim_accounts). "
        "code column: account code (e.g. '411000'). name column: account label. "
        "account_type classifies: 'asset_current', 'asset_non_current', "
        "'liability_current', 'liability_non_current', 'equity', 'income', "
        "'expense', 'expense_direct_cost' (COGS). "
        "Internal primary key: id. Odoo external ID: odoo_id. "
        "ALWAYS filter with tenant_id."
    ),
    "dim_time": (
        "Date dimension for time-based analysis. "
        "Primary key: date_id (integer). full_date column: actual date value. "
        "Provides: year, quarter, month, month_name, week, day_of_month, "
        "day_of_week, day_name, is_weekend, is_holiday, fiscal_year, fiscal_quarter. "
        "Join fact tables via date_id foreign keys (e.g. date_order_id, date_done_id)."
    ),
    "dim_users": (
        "User master data. "
        "name column: user display name. email column: user email. "
        "is_active: whether the user account is active. "
        "Internal primary key: id. Odoo external ID: odoo_id. "
        "ALWAYS filter with tenant_id."
    ),
    "fact_stock_move_lines": (
        "Detailed inventory move line items (serial/lot-level granularity). "
        "DATE column: date. Quantity column: qty_done. "
        "location_src: source warehouse location. location_dest: destination location. "
        "Links to fact_stock_moves via stock_move_id and to dim_lots via lot_id. "
        "state: 'done' for completed move lines. "
        "ALWAYS filter with tenant_id AND company_id."
    ),
}


def get_database_schema() -> str:
    rows = run_query("""
        SELECT
            table_name,
            column_name,
            data_type
        FROM information_schema.columns
        WHERE table_schema = 'public'
        ORDER BY table_name, ordinal_position
    """)

    grouped: dict[str, list[str]] = {}

    for row in rows:
        table = row["table_name"]
        column = row["column_name"]
        dtype = row["data_type"]
        grouped.setdefault(table, []).append(f"{column} ({dtype})")

    lines = []

    for table, columns in grouped.items():
        note = _TABLE_SEMANTIC_NOTES.get(table)
        if note:
            lines.append(f"Table: {table}  ← {note}")
        else:
            lines.append(f"Table: {table}")
        for column in columns:
            lines.append(f"  - {column}")
        lines.append("")

    return "\n".join(lines)


def is_safe_read_only_sql(sql: str) -> bool:
    lowered = sql.lower().strip()

    if not lowered.startswith(("select", "with")):
        return False

    for word in BLOCKED_SQL_WORDS:
        if re.search(rf"\b{word}\b", lowered):
            return False

    return True


def extract_sql_from_text(text: str) -> str | None:
    def looks_like_sql(candidate: str) -> bool:
        lowered = candidate.lower().strip()

        if lowered.startswith("select"):
            return " from " in lowered or "\nfrom " in lowered

        if lowered.startswith("with"):
            # Real CTE should normally contain AS (...) and then SELECT.
            return " as " in lowered and "select" in lowered and " from " in lowered

        return False

    code_block = re.search(r"```sql\s*(.*?)```", text, re.DOTALL | re.IGNORECASE)
    if code_block:
        candidate = code_block.group(1).strip()
        return candidate if looks_like_sql(candidate) else None

    generic_block = re.search(r"```\s*(.*?)```", text, re.DOTALL)
    if generic_block:
        candidate = generic_block.group(1).strip()
        return candidate if looks_like_sql(candidate) else None

    # Prefer SQL-looking lines only. Do not extract normal English beginning with "with".
    match = re.search(r"((?:with\s+.+?select\s+.+?)|(?:select\s+.+?))(?:;|$)", text, re.DOTALL | re.IGNORECASE)
    if match:
        candidate = match.group(1).strip()
        return candidate if looks_like_sql(candidate) else None

    return None


def format_rows_for_prompt(rows: list[dict[str, Any]], limit: int = 30) -> str:
    if not rows:
        return "No rows returned."

    preview = rows[:limit]
    return str(preview)


def run_sql_agent(
    user_question: str,
    chat_history: str = "",
    tenant_id: str | None = None,
) -> dict[str, Any]:
    question_lower = (user_question or "").lower()

    # Refuse destructive requests before asking Claude to generate SQL.
    for word in BLOCKED_SQL_WORDS:
        if re.search(rf"\b{word}\b", question_lower):
            return {
                "success": False,
                "message": "I can only run safe read-only SELECT queries. I cannot modify, delete, drop, or alter database data.",
                "sql": None,
                "rows": [],
            }

    schema = get_database_schema()

    client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

    tenant_note = ""
    if tenant_id:
        tenant_note = (
            f"\nImportant tenant rule:\n"
            f"- The current tenant_id is `{tenant_id}`.\n"
            f"- If a table has a tenant_id column, always filter with tenant_id = '{tenant_id}'.\n"
        )

    prompt = SQL_AGENT_SYSTEM_PROMPT.format(
        schema=schema + tenant_note,
        chat_history=chat_history or "No prior conversation.",
        input=user_question,
    )

    first_response = client.messages.create(
        model=getattr(AgentConfig, "SQL_AGENT_MODEL", "claude-haiku-4-5-20251001"),
        max_tokens=1200,
        temperature=0,
        messages=[
            {
                "role": "user",
                "content": prompt,
            }
        ],
    )

    first_text = first_response.content[0].text
    sql = extract_sql_from_text(first_text)

    if not sql:
        return {
            "success": False,
            "message": first_text,
            "sql": None,
            "rows": [],
        }

    if not is_safe_read_only_sql(sql):
        return {
            "success": False,
            "message": "I can only run safe read-only SELECT queries.",
            "sql": sql,
            "rows": [],
        }

    try:
        rows = run_query(sql)
    except Exception as exc:
        return {
            "success": False,
            "message": f"SQL execution failed: {exc}",
            "sql": sql,
            "rows": [],
        }

    result_preview = format_rows_for_prompt(rows)

    result_preview = format_rows_for_prompt(rows)
    final_prompt = SQL_FINAL_RESPONSE_PROMPT.format(
        user_question=user_question,
        sql=sql,
        result_preview=result_preview
    )

    final_response = client.messages.create(
        model=getattr(AgentConfig, "SQL_AGENT_MODEL", "claude-haiku-4-5-20251001"),
        max_tokens=1200,
        temperature=0,
        messages=[
            {
                "role": "user",
                "content": final_prompt,
            }
        ],
    )

    final_text = final_response.content[0].text

    return {
        "success": True,
        "message": final_text,
        "sql": sql,
        "rows": rows[:50],
    }