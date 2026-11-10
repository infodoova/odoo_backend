"""
SQL Agent – converts natural language questions into safe PostgreSQL queries.
Uses a multi-pass workflow to generate, execute, and explain results.
Includes self-correcting retry logic: if a query fails, the error is fed
back to the LLM to produce a corrected query (up to MAX_SQL_RETRIES attempts).
"""

import os
import re
from typing import Any
import anthropic
from .db import run_query
from .config import AgentConfig
from .logger import logger
from .cache import ttl_cache
from .query_context import resolve_tenant_id


from .prompts import SQL_AGENT_SYSTEM_PROMPT, SQL_FINAL_RESPONSE_PROMPT, SQL_RETRY_PROMPT

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

# ──────────────────────────────────────────────────────────────────────────────
# Semantic annotations for every table in the data warehouse.
# Injected alongside the raw information_schema so the SQL agent can
# resolve column names, FK join paths, valid enum values, and
# date/amount conventions without guessing.
#
# CONVENTIONS used below:
#   PK   = primary key column
#   FK   = foreign-key column (Django stores Many2one as <field>_id in the DB)
#   DATE = the column the agent should use for date-range filtering
#   $$   = the column the agent should use for monetary amounts
# ──────────────────────────────────────────────────────────────────────────────
_TABLE_SEMANTIC_NOTES: dict[str, str] = {

    # ── FACT TABLES ──────────────────────────────────────────────────────────

    "fact_sales_orders": (
        "Sales order headers (Odoo sale.order). "
        "PK: id (bigint). FK: tenant_id (uuid→tenants), company_id (bigint→dim_companies.id), "
        "partner_id (bigint→dim_partners.id), user_id (bigint→dim_users.id), "
        "date_order_id (int→dim_time.date_id). "
        "DATE column: date_order (timestamp). "
        "$$: amount_untaxed, amount_tax, amount_total, margin. "
        "currency_code: ISO currency string (e.g. 'USD'). "
        "odoo_name: order reference (e.g. 'S00042'). "
        "state values: 'draft' (Quotation), 'sent' (Quotation Sent), 'sale' (Confirmed), "
        "'done' (Locked), 'cancel' (Cancelled). "
        "To get confirmed revenue use: state IN ('sale','done'). "
        "invoice_status values: 'to invoice', 'invoiced', 'no'. "
        "Join lines: fact_sales_order_lines.sales_order_id = fact_sales_orders.id. "
        "Join time dim: dim_time.date_id = fact_sales_orders.date_order_id. "
        "ALWAYS filter with tenant_id AND company_id."
    ),

    "fact_sales_order_lines": (
        "Sales order line items (Odoo sale.order.line). "
        "PK: id. FK: tenant_id, sales_order_id (bigint→fact_sales_orders.id), "
        "product_id (bigint→dim_products.id), company_id (bigint→dim_companies.id). "
        "Ordered qty: product_uom_qty. Delivered qty: qty_delivered. Invoiced qty: qty_invoiced. "
        "$$: price_unit (unit price), price_subtotal (excl. tax), price_total (incl. tax), "
        "discount (percentage 0–100), margin, purchase_price (cost). "
        "Margin % = margin / NULLIF(price_subtotal, 0). "
        "Join header: fact_sales_orders.id = fact_sales_order_lines.sales_order_id. "
        "Join product: dim_products.id = fact_sales_order_lines.product_id. "
        "ALWAYS filter with tenant_id AND company_id."
    ),

    "fact_purchase_orders": (
        "Purchase order headers (Odoo purchase.order). "
        "PK: id. FK: tenant_id, company_id (→dim_companies.id), partner_id (→dim_partners.id), "
        "user_id (→dim_users.id), date_order_id (→dim_time.date_id). "
        "DATE column: date_order (timestamp). "
        "$$: amount_untaxed, amount_tax, amount_total. "
        "currency_code: ISO currency string. "
        "odoo_name: PO reference (e.g. 'P00015'). "
        "state values: 'draft' (RFQ), 'sent' (RFQ Sent), 'to approve', "
        "'purchase' (Confirmed PO), 'done' (Locked), 'cancel'. "
        "Confirmed spend: state IN ('purchase','done'). "
        "invoice_status values: 'no', 'to invoice', 'invoiced'. "
        "date_planned: expected receipt timestamp. date_approve: approval timestamp. "
        "partner_ref: vendor's reference number. "
        "Join lines: fact_purchase_order_lines.purchase_order_id = fact_purchase_orders.id. "
        "ALWAYS filter with tenant_id AND company_id."
    ),

    "fact_purchase_order_lines": (
        "Purchase order line items (Odoo purchase.order.line). "
        "PK: id. FK: tenant_id, purchase_order_id (→fact_purchase_orders.id), "
        "product_id (→dim_products.id), company_id (→dim_companies.id). "
        "Ordered qty: product_qty. Received qty: qty_received. Billed qty: qty_invoiced. "
        "$$: price_unit, price_subtotal (excl. tax), price_total (incl. tax). "
        "date_planned: expected delivery (timestamp). name: line description. "
        "Join header: fact_purchase_orders.id = purchase_order_id. "
        "ALWAYS filter with tenant_id AND company_id."
    ),

    "fact_account_moves": (
        "Accounting journal entries, invoices, bills, and credit notes (Odoo account.move). "
        "PK: id. FK: tenant_id, company_id (→dim_companies.id), partner_id (→dim_partners.id), "
        "date_id (→dim_time.date_id), invoice_date_id (→dim_time.date_id). "
        "DATE column: date (date). Also: invoice_date (date), invoice_date_due (date). "
        "$$: amount_untaxed, amount_tax, amount_total, amount_residual (outstanding balance). "
        "currency_code: ISO currency string. "
        "odoo_name: entry number (e.g. 'INV/2025/0001'). "
        "move_type values: 'out_invoice' (Customer Invoice), 'in_invoice' (Vendor Bill), "
        "'out_refund' (Customer Credit Note), 'in_refund' (Vendor Credit Note), "
        "'entry' (Journal Entry). "
        "state values: 'draft', 'posted', 'cancel'. Use state='posted' for confirmed entries. "
        "payment_state values: 'not_paid', 'in_payment', 'paid', 'partial', 'reversed'. "
        "invoice_origin: source document (e.g. SO number). ref: payment reference. "
        "To get customer invoices: move_type = 'out_invoice' AND state = 'posted'. "
        "To get vendor bills: move_type = 'in_invoice' AND state = 'posted'. "
        "Overdue invoices: payment_state NOT IN ('paid','reversed') AND invoice_date_due < CURRENT_DATE. "
        "Join lines: fact_account_move_lines.account_move_id = fact_account_moves.id. "
        "ALWAYS filter with tenant_id AND company_id."
    ),

    "fact_account_move_lines": (
        "General ledger journal-entry line items (Odoo account.move.line). "
        "PK: id. FK: tenant_id, account_move_id (→fact_account_moves.id), "
        "product_id (→dim_products.id), partner_id (→dim_partners.id), "
        "company_id (→dim_companies.id). "
        "Columns: debit, credit, balance (= debit − credit). "
        "amount_currency: amount in the transaction currency. currency_code: ISO code. "
        "account_code: chart-of-accounts code (e.g. '411000'). "
        "account_name: account label. "
        "account_type values: 'asset_current', 'asset_non_current', 'asset_receivable', "
        "'asset_cash', 'asset_fixed', 'asset_prepayments', "
        "'liability_current', 'liability_non_current', 'liability_payable', "
        "'equity', 'equity_unaffected', "
        "'income', 'income_other', "
        "'expense', 'expense_direct_cost' (COGS), 'expense_depreciation', "
        "'off_balance'. "
        "quantity, price_unit, price_subtotal: for invoice lines. "
        "name: line description. "
        "Revenue queries: account_type = 'income'. "
        "Expense queries: account_type LIKE 'expense%'. "
        "COGS: account_type = 'expense_direct_cost'. "
        "OPEX: account_type IN ('expense', 'expense_depreciation') AND account_code NOT LIKE '67%' AND account_code NOT LIKE '69%'. "
        "Taxes/Interest: account_code LIKE '67%' OR account_code LIKE '69%'. "
        "Receivables: account_type = 'asset_receivable'. "
        "Payables: account_type = 'liability_payable'. "
        "P&L = SUM(credit) − SUM(debit) WHERE account_type IN ('income','income_other','expense','expense_direct_cost','expense_depreciation'). "
        "Trial Balance: GROUP BY account_code, account_name → SUM(debit), SUM(credit), SUM(balance). "
        "Join chart: dim_chart_of_accounts.code = fact_account_move_lines.account_code "
        "(AND same tenant_id) for reconcile flag or full account metadata. "
        "ALWAYS filter with tenant_id AND company_id."
    ),

    "fact_stock_pickings": (
        "Warehouse transfer operations: receipts, deliveries, internal moves (Odoo stock.picking). "
        "PK: id. FK: tenant_id, company_id (→dim_companies.id), partner_id (→dim_partners.id), "
        "scheduled_date_id (→dim_time.date_id), date_done_id (→dim_time.date_id). "
        "DATE columns: scheduled_date (planned), date_done (completed) — both timestamps. "
        "odoo_name: transfer reference (e.g. 'WH/OUT/00042'). "
        "picking_type values: 'incoming' (Receipt), 'outgoing' (Delivery), 'internal' (Transfer). "
        "state values: 'draft', 'waiting', 'confirmed', 'assigned' (Ready), 'done', 'cancel'. "
        "origin: source document (e.g. SO or PO name). "
        "Completed deliveries: state = 'done' AND picking_type = 'outgoing'. "
        "Completed receipts: state = 'done' AND picking_type = 'incoming'. "
        "Join moves: fact_stock_moves.picking_id = fact_stock_pickings.id. "
        "ALWAYS filter with tenant_id AND company_id."
    ),

    "fact_stock_moves": (
        "Inventory movement records per product (Odoo stock.move). "
        "PK: id. FK: tenant_id, picking_id (→fact_stock_pickings.id, nullable), "
        "product_id (→dim_products.id), company_id (→dim_companies.id), "
        "date_id (→dim_time.date_id). "
        "DATE column: date (timestamp). "
        "product_uom_qty: demanded qty. quantity_done: actually moved qty. "
        "location_src / location_dest: warehouse location display names. "
        "state values: 'draft', 'waiting', 'confirmed', 'assigned', 'done', 'cancel'. "
        "Use state = 'done' for completed movements. "
        "origin: source document. reference: transfer ref. name: move description. "
        "date_deadline: expected completion date. "
        "Join detail lines: fact_stock_move_lines.stock_move_id = fact_stock_moves.id. "
        "ALWAYS filter with tenant_id AND company_id."
    ),

    "fact_stock_move_lines": (
        "Detailed move lines with serial/lot granularity (Odoo stock.move.line). "
        "PK: id. FK: tenant_id, stock_move_id (→fact_stock_moves.id), "
        "product_id (→dim_products.id), lot_id (→dim_lots.id, nullable), "
        "company_id (→dim_companies.id). "
        "qty_done: quantity actually processed. product_uom_qty: demanded qty. "
        "location_src / location_dest: warehouse location names. "
        "DATE column: date (timestamp). "
        "state values: 'done' for completed. "
        "Use this table for lot/serial traceability queries. "
        "ALWAYS filter with tenant_id AND company_id."
    ),

    "fact_stock_quants": (
        "Current on-hand inventory snapshot per product + location (Odoo stock.quant). "
        "PK: id. FK: tenant_id, product_id (→dim_products.id), "
        "lot_id (→dim_lots.id, nullable), company_id (→dim_companies.id). "
        "quantity: total on-hand. reserved_quantity: reserved for orders. "
        "Available = quantity − reserved_quantity. "
        "location_name: warehouse location display name. "
        "in_date: date the stock entered the location. "
        "This is a STATE table (not transactional) — it reflects the latest inventory position. "
        "For stock valuation: JOIN dim_products ON product_id to get standard_price. "
        "ALWAYS filter with tenant_id AND company_id."
    ),

    "fact_bank_statements": (
        "Bank statement headers (Odoo account.bank.statement). "
        "PK: id. FK: tenant_id, company_id (→dim_companies.id), "
        "date_id (→dim_time.date_id). "
        "DATE column: date (date). "
        "$$: balance_start (opening balance), balance_end_real (closing balance). "
        "journal_name: bank journal display name (e.g. 'Bank', 'Cash'). "
        "odoo_name: statement reference. "
        "state values: 'open', 'confirm', 'posted'. "
        "Net movement = balance_end_real − balance_start. "
        "Join lines: fact_bank_statement_lines.statement_id = fact_bank_statements.id. "
        "ALWAYS filter with tenant_id AND company_id."
    ),

    "fact_bank_statement_lines": (
        "Individual bank transactions (Odoo account.bank.statement.line). "
        "PK: id. FK: tenant_id, statement_id (→fact_bank_statements.id), "
        "partner_id (→dim_partners.id, nullable), company_id (→dim_companies.id), "
        "date_id (→dim_time.date_id). "
        "DATE column: date (date). "
        "$$: amount (positive = deposit/inflow, negative = withdrawal/outflow). "
        "name: transaction label/memo. ref: payment reference. "
        "Total deposits: SUM(amount) FILTER (WHERE amount > 0). "
        "Total withdrawals: SUM(amount) FILTER (WHERE amount < 0). "
        "ALWAYS filter with tenant_id AND company_id."
    ),

    # ── DIMENSION TABLES ─────────────────────────────────────────────────────

    "dim_companies": (
        "Company master data (Odoo res.company). "
        "PK: id (bigint). tenant_id (uuid→tenants). odoo_id: Odoo external ID. "
        "Columns: name, display_name, currency_id (Odoo FK int), currency_name, currency_code, "
        "country_id, country_name, country_code, is_active. "
        "Fact tables reference this as company_id = dim_companies.id. "
        "ALWAYS filter with tenant_id."
    ),

    "dim_products": (
        "Product catalog (Odoo product.product). "
        "PK: id. tenant_id. odoo_id. "
        "name: product display name. default_code: internal reference / SKU. barcode. "
        "product_type values: 'product' (Storable), 'consu' (Consumable), 'service'. "
        "category_id (→dim_product_categories.id): product category FK. "
        "list_price: sales price. standard_price: cost price. "
        "uom_name: unit of measure label. is_active: whether product is active. "
        "Margin analysis: JOIN fact_sales_order_lines on product_id, "
        "use purchase_price (cost) and price_subtotal (revenue). "
        "ALWAYS filter with tenant_id."
    ),

    "dim_product_categories": (
        "Product category hierarchy (Odoo product.category). "
        "PK: id. tenant_id. odoo_id. "
        "name: category label. complete_name: full path (e.g. 'All / Saleable / Furniture'). "
        "parent_id (→dim_product_categories.id, nullable): self-referencing parent FK. "
        "Join products: dim_products.category_id = dim_product_categories.id. "
        "ALWAYS filter with tenant_id."
    ),

    "dim_partners": (
        "Customer and vendor master data (Odoo res.partner). "
        "PK: id. tenant_id. odoo_id. "
        "name, email, phone, city, country_code. "
        "customer_rank (int): > 0 means customer. supplier_rank (int): > 0 means vendor. "
        "is_customer (bool), is_supplier (bool): convenience flags. "
        "partner_type: contact classification. is_active. "
        "Top customers: JOIN fact_sales_orders ON partner_id, GROUP BY partner, ORDER BY SUM(amount_total) DESC. "
        "Top vendors: JOIN fact_purchase_orders ON partner_id. "
        "ALWAYS filter with tenant_id."
    ),

    "dim_users": (
        "Salesperson / user dimension (Odoo res.users). "
        "PK: id. tenant_id. odoo_id. "
        "name: display name. email. is_active. "
        "Referenced by: fact_sales_orders.user_id, fact_purchase_orders.user_id. "
        "Salesperson performance: JOIN fact_sales_orders ON user_id. "
        "ALWAYS filter with tenant_id."
    ),

    "dim_lots": (
        "Inventory lot and serial number master data (Odoo stock.lot). "
        "PK: id. FK: tenant_id, product_id (→dim_products.id), company_id (→dim_companies.id). "
        "name: lot/serial number. ref: internal reference. "
        "expiration_date, use_date, removal_date, alert_date: lifecycle dates. "
        "Expiring lots: expiration_date < CURRENT_DATE + INTERVAL '30 days'. "
        "Join quants: fact_stock_quants.lot_id = dim_lots.id. "
        "Join move lines: fact_stock_move_lines.lot_id = dim_lots.id. "
        "ALWAYS filter with tenant_id."
    ),

    "dim_chart_of_accounts": (
        "Chart of accounts (Odoo account.account). "
        "PK: id. tenant_id. odoo_id. "
        "code: account code (e.g. '411000'). name: account label (e.g. 'Revenue'). "
        "account_type values: 'asset_current', 'asset_non_current', 'asset_receivable', "
        "'asset_cash', 'asset_fixed', 'asset_prepayments', "
        "'liability_current', 'liability_non_current', 'liability_payable', "
        "'equity', 'equity_unaffected', "
        "'income', 'income_other', "
        "'expense', 'expense_direct_cost' (COGS), 'expense_depreciation', "
        "'off_balance'. "
        "reconcile: whether the account supports reconciliation. "
        "deprecated: whether the account is deprecated. "
        "Join to move lines: fact_account_move_lines.account_code = dim_chart_of_accounts.code "
        "(AND same tenant_id). "
        "ALWAYS filter with tenant_id."
    ),

    "dim_currencies": (
        "Currency master data (Odoo res.currency). "
        "PK: id. tenant_id. odoo_id. "
        "code: ISO 4217 code (e.g. 'USD', 'EUR'). symbol: display symbol (e.g. '$'). "
        "symbol_position: 'before' or 'after'. rounding: decimal precision. "
        "is_active. "
        "Join rates: dim_currency_rates.currency_id = dim_currencies.id. "
        "ALWAYS filter with tenant_id."
    ),

    "dim_currency_rates": (
        "Historical daily exchange rates (Odoo res.currency.rate). "
        "PK: id. FK: tenant_id, currency_id (→dim_currencies.id), company_id (→dim_companies.id). "
        "name: rate date (date type — this is the DATE column). "
        "rate: exchange rate relative to company base currency. "
        "To convert amount: amount / rate (where rate is for the target currency). "
        "Latest rate: ORDER BY name DESC LIMIT 1 per currency. "
        "ALWAYS filter with tenant_id AND company_id."
    ),

    "dim_time": (
        "Pre-populated calendar/date dimension for time-based analysis. "
        "PK: date_id (integer, format YYYYMMDD). full_date: actual date value. "
        "year, quarter (1–4), month (1–12), month_name (e.g. 'January'), "
        "week (ISO week 1–53), day_of_month (1–31), day_of_week (0=Mon–6=Sun), "
        "day_name (e.g. 'Monday'), is_weekend (bool), is_holiday (bool), "
        "fiscal_year, fiscal_quarter. "
        "FK columns in fact tables that join here: "
        "fact_sales_orders.date_order_id, fact_purchase_orders.date_order_id, "
        "fact_account_moves.date_id, fact_account_moves.invoice_date_id, "
        "fact_stock_moves.date_id, fact_stock_pickings.scheduled_date_id, "
        "fact_stock_pickings.date_done_id, fact_bank_statements.date_id, "
        "fact_bank_statement_lines.date_id. "
        "Monthly aggregation: GROUP BY t.year, t.month, t.month_name. "
        "Quarterly aggregation: GROUP BY t.year, t.quarter. "
        "No tenant_id filter needed — shared across tenants."
    ),

    "dim_account_journals": (
        "Accounting journals for organizing entries (Odoo account.journal). "
        "PK: id. FK: tenant_id, company_id (→dim_companies.id). "
        "name: journal name (e.g. 'Bank', 'Vendor Bills'). "
        "type values: 'sale', 'purchase', 'cash', 'bank', 'general'. "
        "default_account_code: primary GL account for this journal. "
        "ALWAYS filter with tenant_id AND company_id."
    ),

    "fact_account_partial_reconciles": (
        "Reconciliation links matching payments to invoices (Odoo account.partial.reconcile). "
        "PK: id. FK: tenant_id, company_id (→dim_companies.id), "
        "debit_move_line_id (→fact_account_move_lines.id), "
        "credit_move_line_id (→fact_account_move_lines.id). "
        "$$: amount (in company currency). "
        "max_date: the date the reconciliation happened. "
        "Used for tracking exact payment allocations and aging calculations. "
        "ALWAYS filter with tenant_id AND company_id."
    )
}


@ttl_cache(ttl_seconds=AgentConfig.CACHE_TTL_SCHEMA, name="schema")
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
            # Real CTE should contain AS (...) and then SELECT FROM
            return (" as (" in lowered or " as\n(" in lowered or " as (" in lowered) and "select" in lowered and (" from " in lowered or "\nfrom " in lowered)

        return False

    def clean_candidate(candidate: str) -> str:
        # Strip any trailing markdown fence or explanation text
        c = re.sub(r"```.*", "", candidate, flags=re.DOTALL).strip()
        # Strip trailing semicolon
        c = c.rstrip(";").strip()
        return c

    # 1. Closed ```sql block
    code_block = re.search(r"```sql\s*(.*?)```", text, re.DOTALL | re.IGNORECASE)
    if code_block:
        candidate = clean_candidate(code_block.group(1))
        if looks_like_sql(candidate):
            return candidate

    # 2. Generic ``` block
    generic_block = re.search(r"```\s*(.*?)```", text, re.DOTALL)
    if generic_block:
        candidate = clean_candidate(generic_block.group(1))
        if looks_like_sql(candidate):
            return candidate

    # 3. Unclosed ```sql block (if response ends at token limit)
    unclosed_sql = re.search(r"```sql\s*(.*)", text, re.DOTALL | re.IGNORECASE)
    if unclosed_sql:
        candidate = clean_candidate(unclosed_sql.group(1))
        if looks_like_sql(candidate):
            return candidate

    # 4. Raw SQL without markdown backticks
    match = re.search(r"((?:with\s+[a-zA-Z0-9_]+\s+as\s*\(.+?select\s+.+?)|(?:select\s+.+?))(?:;|\n\s*```|$)", text, re.DOTALL | re.IGNORECASE)
    if match:
        candidate = clean_candidate(match.group(1))
        if looks_like_sql(candidate):
            return candidate

    return None


def format_rows_for_prompt(rows: list[dict[str, Any]], limit: int = 100) -> str:
    if not rows:
        return "No rows returned."

    preview = rows[:limit]
    return str(preview)


# Requests that plainly ask to change data. Ordinary words such as "analyze", "update"
# (as in "latest update") or "create" must not be refused: the generated SQL is checked
# separately by is_safe_read_only_sql, which is the real safeguard.
_DESTRUCTIVE_REQUEST = re.compile(
    r"\b(?:drop|truncate)\s+(?:table|database|schema)\b"
    r"|\bdelete\s+(?:from|all|every|the)\b"
    r"|\balter\s+table\b"
    r"|\binsert\s+into\b"
    r"|\bupdate\s+\w+\s+set\b"
    r"|\b(?:grant|revoke)\s+\w+",
    re.IGNORECASE,
)

MAX_RETURNED_ROWS = 100


def _plain(value: Any) -> Any:
    """Make a database value safe to show or serialize (Decimal, date, datetime)."""
    import datetime as _dt
    from decimal import Decimal

    if value is None:
        return ""
    if isinstance(value, Decimal):
        number = float(value)
        return int(number) if number == int(number) else round(number, 2)
    if isinstance(value, _dt.datetime):
        return value.isoformat(sep=" ", timespec="seconds")
    if isinstance(value, _dt.date):
        return value.isoformat()
    return value


def rows_to_markdown(rows: list[dict[str, Any]], max_rows: int = MAX_RETURNED_ROWS) -> str:
    """Render query rows as a markdown table, exactly as returned (no summarizing)."""
    if not rows:
        return ""
    columns = list(rows[0].keys())

    def cell(value: Any) -> str:
        value = _plain(value)
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            text = f"{value:,}"
        else:
            text = str(value)
        return text.replace("|", "\\|").replace("\r", " ").replace("\n", " ").strip()

    lines = ["| " + " | ".join(str(c) for c in columns) + " |", "|" + "|".join(["---"] * len(columns)) + "|"]
    for row in rows[:max_rows]:
        lines.append("| " + " | ".join(cell(row.get(c)) for c in columns) + " |")
    shown = min(len(rows), max_rows)
    lines.append("")
    lines.append(f"*Showing {shown:,} of {len(rows):,} rows returned by the query.*")
    return "\n".join(lines)


# ──────────────────────────────────────────────────────────────────────────────
# Self-correcting retry helpers
# ──────────────────────────────────────────────────────────────────────────────

def _build_retry_prompt(
    user_question: str,
    schema: str,
    failed_sql: str,
    error_message: str,
    attempt_history: list[dict],
) -> str:
    """Build the retry prompt with accumulated error context."""
    previous_attempts = ""
    if len(attempt_history) > 1:
        lines = ["PREVIOUS FAILED ATTEMPTS (do NOT repeat these mistakes):"]
        for i, attempt in enumerate(attempt_history[:-1], 1):
            lines.append(f"  Attempt {i}: {attempt['error']}")
        previous_attempts = "\n".join(lines)

    return SQL_RETRY_PROMPT.format(
        user_question=user_question,
        schema=schema,
        failed_sql=failed_sql,
        error_message=error_message,
        previous_attempts=previous_attempts,
    )


def _attempt_sql_correction(
    client: anthropic.Anthropic,
    retry_prompt: str,
    model: str,
) -> str | None:
    """Ask the LLM to produce a corrected SQL query. Returns the SQL or None."""
    correction_model = model
    if getattr(AgentConfig, "ENABLE_ADVISOR_TOOL", False):
        correction_model = getattr(AgentConfig, "ADVISOR_MODEL", "claude-sonnet-5-5")

    response = client.messages.create(
        model=correction_model,
        max_tokens=2500,
        temperature=0,
        messages=[{"role": "user", "content": retry_prompt}],
    )
    return extract_sql_from_text(response.content[0].text)


# ──────────────────────────────────────────────────────────────────────────────
# Main SQL Agent
# ──────────────────────────────────────────────────────────────────────────────

def run_sql_agent(
    user_question: str,
    chat_history: str = "",
    tenant_ids: list[str] | None = None,
    company_ids: list[int] | None = None,
) -> dict[str, Any]:
    from doova_one_view.api.agent.query_context import normalize_tenant_ids, normalize_company_ids
    tenants = normalize_tenant_ids(tenant_ids)
    companies = normalize_company_ids(company_ids)
    question_lower = (user_question or "").lower()

    # Refuse requests that plainly ask to change data before asking Claude to generate SQL.
    if _DESTRUCTIVE_REQUEST.search(question_lower):
        return {
            "success": False,
            "message": "I can only run safe read-only SELECT queries. I cannot modify, delete, drop, or alter database data.",
            "sql": None,
            "rows": [],
        }

    schema = get_database_schema()

    client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
    if getattr(AgentConfig, "ENABLE_ADVISOR_TOOL", False):
        model = getattr(AgentConfig, "EXECUTOR_MODEL", "claude-haiku-5-5")
    else:
        model = getattr(AgentConfig, "SQL_AGENT_MODEL", "claude-haiku-5-5")
    max_retries = getattr(AgentConfig, "MAX_SQL_RETRIES", 3)

    tenant_note = ""
    if tenants:
        if len(tenants) == 1:
            tenant_note = (
                f"\nImportant tenant rule:\n"
                f"- The current tenant_id is `{tenants[0]}`.\n"
                f"- If a table has a tenant_id column, always filter with tenant_id = '{tenants[0]}'.\n"
            )
        else:
            tenants_list_str = ", ".join(f"'{t}'" for t in tenants)
            tenant_note = (
                f"\nImportant tenant rule:\n"
                f"- The current tenants are {tenants_list_str}.\n"
                f"- If a table has a tenant_id column, always filter using IN: tenant_id IN ({tenants_list_str}).\n"
            )

    company_note = ""
    if companies:
        company_list = ", ".join(str(c) for c in companies)
        company_note = (
            f"\nImportant company rule:\n"
            f"- The user selected company id(s) {company_list} (dim_companies.id).\n"
            f"- If a table has a company_id column, also filter with company_id "
            f"{'= ' + str(companies[0]) if len(companies) == 1 else 'IN (' + company_list + ')'}.\n"
            f"- For dim_companies itself, filter with id instead.\n"
        )

    schema_with_tenant = schema + tenant_note + company_note

    prompt = SQL_AGENT_SYSTEM_PROMPT.format(
        schema=schema_with_tenant,
        chat_history=chat_history or "No prior conversation.",
        input=user_question,
    )

    # ── Pass 1: Generate initial SQL ──────────────────────────────────────

    first_response = client.messages.create(
        model=model,
        max_tokens=2500,
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

    # ── Pass 2: Execute with self-correcting retry loop ───────────────────

    attempt_history: list[dict] = []
    rows = None

    for attempt in range(1, max_retries + 1):
        try:
            rows = run_query(sql)
            logger.info(
                f"SQL AGENT SUCCESS\n"
                f"   Attempt: {attempt}/{max_retries}\n"
                f"   SQL: {sql[:200]}{'...' if len(sql) > 200 else ''}"
            )
            break  # Success — exit retry loop
        except Exception as exc:
            error_msg = str(exc)
            attempt_history.append({"sql": sql, "error": error_msg})

            logger.warning(
                f"SQL AGENT RETRY\n"
                f"   Attempt: {attempt}/{max_retries}\n"
                f"   Error: {error_msg}\n"
                f"   Failed SQL: {sql[:200]}{'...' if len(sql) > 200 else ''}"
            )

            if attempt >= max_retries:
                # All retries exhausted
                logger.error(
                    f"SQL AGENT FAILED\n"
                    f"   All {max_retries} attempts exhausted.\n"
                    f"   Last error: {error_msg}"
                )
                return {
                    "success": False,
                    "message": (
                        f"I attempted to query the database {max_retries} times but could not "
                        f"produce a valid query. Last error: {error_msg}"
                    ),
                    "sql": sql,
                    "rows": [],
                    "attempts": attempt_history,
                }

            # Build retry prompt with error context and ask LLM to fix
            retry_prompt = _build_retry_prompt(
                user_question=user_question,
                schema=schema_with_tenant,
                failed_sql=sql,
                error_message=error_msg,
                attempt_history=attempt_history,
            )

            corrected_sql = _attempt_sql_correction(client, retry_prompt, model)

            if not corrected_sql:
                logger.error(
                    f"SQL AGENT FAILED\n"
                    f"   LLM could not produce corrected SQL on attempt {attempt}."
                )
                return {
                    "success": False,
                    "message": (
                        f"Query failed and I could not generate a corrected version. "
                        f"Error: {error_msg}"
                    ),
                    "sql": sql,
                    "rows": [],
                    "attempts": attempt_history,
                }

            if not is_safe_read_only_sql(corrected_sql):
                return {
                    "success": False,
                    "message": "I can only run safe read-only SELECT queries.",
                    "sql": corrected_sql,
                    "rows": [],
                }

            # Use corrected SQL for the next attempt
            sql = corrected_sql

    # ── Pass 3: Synthesize results ────────────────────────────────────────

    from doova_one_view.api.agent.utils import get_tenant_currency
    from doova_one_view.api.kpi.service import _get_rate_map
    from doova_one_view.api.agent.tools_refactored.common import get_per_tenant_exchange_rates
    
    tenant_curr = get_tenant_currency(tenant_ids=tenants)
    rate_map = _get_rate_map(tenant_ids=tenants)
    per_tenant_rates = get_per_tenant_exchange_rates(tenant_ids=tenants)
    
    currency_context = (
        f"\n\nTENANT & COMPANY MULTI-CURRENCY CONTEXT:\n"
        f"- Tenant Base Currency: {tenant_curr}\n"
        f"- System Active Exchange Rates Map: {rate_map}\n"
        f"- Per-Tenant Exchange Rates Breakdown: {per_tenant_rates}\n"
        f"CRITICAL MULTI-CURRENCY RULE:\n"
        f"If (and ONLY IF) the user query asks for revenue/spend/amounts in 'all currencies', 'multi-currency', or converted currencies:\n"
        f"1. State the Tenant Base Currency for each tenant.\n"
        f"2. Display the exact tenant exchange rates from above (e.g. 1 {tenant_curr} = X target currency).\n"
        f"3. Apply these exchange rates to convert the SQL query result numbers into every target currency.\n"
        f"4. Output a clear Multi-Currency Breakdown Table displaying: Target Currency, Converted Amount, Exchange Rate Applied.\n"
        f"CRITICAL TABLE FORMATTING RULE: Map each target rate key to its exact currency code (XAF, EUR, USD). NEVER repeat the base currency code for converted currency rows (e.g. write 'XAF → USD 0.001639' for USD; NEVER write 'XAF → XAF 0.001639' for USD).\n"
        f"Otherwise, if the user did NOT request multi-currency, answer normally using the native base currency ({tenant_curr}) without adding a multi-currency conversion table.\n"
    )

    result_preview = format_rows_for_prompt(rows) + currency_context
    final_prompt = SQL_FINAL_RESPONSE_PROMPT.format(
        user_question=user_question,
        sql=sql,
        result_preview=result_preview
    )

    final_response = client.messages.create(
        model=model,
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

    result = {
        "success": True,
        "message": final_text,
        "sql": sql,
        "rows": [{k: _plain(v) for k, v in r.items()} for r in rows[:MAX_RETURNED_ROWS]],
        "row_count": len(rows),
    }

    # Include retry metadata if corrections were needed
    if attempt_history:
        result["self_corrections"] = len(attempt_history)
        result["attempts"] = attempt_history

    return result