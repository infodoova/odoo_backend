# api/agent/tools_refactored/records.py
"""
Record-level tools.

* ``get_invoice_summary_tool``: how many invoices and how much, with credit notes shown
  separately. (``get_sales_summary_tool`` counts confirmed sales ORDERS, not invoices.)
* ``list_records_tool``: the actual rows of orders, invoices and bills, with the true
  total, paging and sorting. The table is rendered here, by the server, so the model
  never has to retype rows.

Both refuse to run without a tenant scope.
"""

from datetime import date, datetime
from typing import Any, Optional

from ..db import run_query
from ..query_context import (
    build_company_filter_sql,
    build_tenant_filter_sql,
    normalize_company_ids,
    normalize_tenant_ids,
)
from ..table_sink import register_table
from .common import build_currency_case_sql

DEFAULT_LIST_ROWS = 20
MAX_LIST_ROWS = 100

_ORDER_DATE = "(t.date_order)::date"
_MOVE_DATE = "COALESCE(t.invoice_date, t.date)"

# record_type -> how to read it. "default_states" is what "confirmed" means for that type.
RECORD_TYPES: dict[str, dict[str, Any]] = {
    "sales_orders": {
        "table": "fact_sales_orders", "date_expr": _ORDER_DATE, "partner_label": "Customer",
        "default_states": ("sale", "done"), "allowed_states": ("draft", "sent", "sale", "done", "cancel"),
        "move_types": None, "has_unpaid": False,
    },
    "purchase_orders": {
        "table": "fact_purchase_orders", "date_expr": _ORDER_DATE, "partner_label": "Vendor",
        "default_states": ("purchase", "done"), "allowed_states": ("draft", "sent", "to approve", "purchase", "done", "cancel"),
        "move_types": None, "has_unpaid": False,
    },
    "customer_invoices": {
        "table": "fact_account_moves", "date_expr": _MOVE_DATE, "partner_label": "Customer",
        "default_states": ("posted",), "allowed_states": ("draft", "posted", "cancel"),
        "move_types": ("out_invoice",), "has_unpaid": True,
    },
    "credit_notes": {
        "table": "fact_account_moves", "date_expr": _MOVE_DATE, "partner_label": "Customer",
        "default_states": ("posted",), "allowed_states": ("draft", "posted", "cancel"),
        "move_types": ("out_refund",), "has_unpaid": True,
    },
    "vendor_bills": {
        "table": "fact_account_moves", "date_expr": _MOVE_DATE, "partner_label": "Vendor",
        "default_states": ("posted",), "allowed_states": ("draft", "posted", "cancel"),
        "move_types": ("in_invoice",), "has_unpaid": True,
    },
    "vendor_credit_notes": {
        "table": "fact_account_moves", "date_expr": _MOVE_DATE, "partner_label": "Vendor",
        "default_states": ("posted",), "allowed_states": ("draft", "posted", "cancel"),
        "move_types": ("in_refund",), "has_unpaid": True,
    },
}

SORTS = ("date_desc", "date_asc", "amount_desc", "amount_asc")


def _num(value: Any) -> float:
    if value is None:
        return 0.0
    return round(float(value), 2)


def _fmt_amount(value: Any) -> str:
    number = _num(value)
    return f"{int(number):,}" if number == int(number) else f"{number:,.2f}"


def _cell(value: Any) -> str:
    text = "" if value is None else str(value)
    return text.replace("|", "\\|").replace("\r", " ").replace("\n", " ").strip()


def _iso(value: Any) -> str:
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    return "" if value is None else str(value)


def _error(tool: str, message: str) -> dict:
    return {"tool_name": tool, "status": "ERROR", "message": message}


def _require_tenants(tool: str, tenant_ids: Any) -> tuple[Optional[list[str]], Optional[dict]]:
    tenants = normalize_tenant_ids(tenant_ids)
    if not tenants:
        return None, _error(tool, "No tenant is selected, so there is nothing to read. Ask the user to choose a business first.")
    return tenants, None


def _date_clause(date_expr: str, start_date: Optional[str], end_date: Optional[str]) -> tuple[str, dict]:
    if start_date and end_date:
        return f" AND {date_expr} BETWEEN CAST(:rec_start AS date) AND CAST(:rec_end AS date)", {"rec_start": start_date, "rec_end": end_date}
    if start_date:
        return f" AND {date_expr} >= CAST(:rec_start AS date)", {"rec_start": start_date}
    if end_date:
        return f" AND {date_expr} <= CAST(:rec_end AS date)", {"rec_end": end_date}
    return "", {}


# ── Invoice summary ───────────────────────────────────────────────────────────

def get_invoice_summary_tool(
    tenant_ids: Optional[list[str]] = None,
    company_ids: Optional[list[int]] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    direction: str = "customer",
    base_currency: Optional[str] = None,
) -> dict:
    """Posted invoices and credit notes: counts and totals, kept separate, plus the net."""
    tool = "get_invoice_summary_tool"
    tenants, problem = _require_tenants(tool, tenant_ids)
    if problem:
        return problem

    side = (direction or "customer").strip().lower()
    if side not in ("customer", "vendor"):
        return _error(tool, "direction must be 'customer' (sales invoices) or 'vendor' (vendor bills).")
    invoice_type, credit_type = ("out_invoice", "out_refund") if side == "customer" else ("in_invoice", "in_refund")
    invoice_label, credit_label = ("invoices", "credit notes") if side == "customer" else ("vendor bills", "vendor credit notes")

    companies = normalize_company_ids(company_ids)
    t_sql, t_params = build_tenant_filter_sql(tenant_ids=tenants, column_name="t.tenant_id", prefix="t_inv")
    c_sql, c_params = build_company_filter_sql(company_ids=companies, column_name="t.company_id", prefix="c_inv")
    d_sql, d_params = _date_clause(_MOVE_DATE, start_date, end_date)
    where = f"WHERE 1=1 {t_sql} {c_sql} AND t.state = 'posted' AND t.move_type IN ('{invoice_type}', '{credit_type}') {d_sql}"
    params = {**t_params, **c_params, **d_params}

    try:
        rows = run_query(
            f"""SELECT t.move_type, t.currency_code, COUNT(*) AS doc_count,
                       COALESCE(SUM(t.amount_total), 0) AS total,
                       COALESCE(SUM(t.amount_residual), 0) AS unpaid,
                       MIN({_MOVE_DATE}) AS first_date, MAX({_MOVE_DATE}) AS last_date
                FROM fact_account_moves t
                {where}
                GROUP BY t.move_type, t.currency_code""",
            params,
        )
        converted_rows = []
        if base_currency:
            converted = build_currency_case_sql(
                "t.amount_total", tenant_ids=tenants, base_currency=base_currency, currency_column="t.currency_code"
            )
            converted_rows = run_query(
                f"SELECT t.move_type, COALESCE(SUM({converted}), 0) AS total FROM fact_account_moves t {where} GROUP BY t.move_type",
                params,
            )
    except Exception as exc:  # database or date-format problems must reach the model as an error, not a crash
        return _error(tool, f"Could not read invoices: {exc}")

    by_currency: dict[str, dict[str, float]] = {}
    count = {invoice_type: 0, credit_type: 0}
    unpaid: dict[str, float] = {}
    first_date = last_date = None
    for r in rows:
        kind, cur = r["move_type"], r["currency_code"] or "UNKNOWN"
        count[kind] += int(r["doc_count"] or 0)
        bucket = by_currency.setdefault(cur, {"invoices": 0.0, "credit_notes": 0.0})
        bucket["invoices" if kind == invoice_type else "credit_notes"] += _num(r["total"])
        if kind == invoice_type:
            unpaid[cur] = round(unpaid.get(cur, 0.0) + _num(r["unpaid"]), 2)
        if r["first_date"] is not None and (first_date is None or r["first_date"] < first_date):
            first_date = r["first_date"]
        if r["last_date"] is not None and (last_date is None or r["last_date"] > last_date):
            last_date = r["last_date"]

    result: dict[str, Any] = {
        "tool_name": tool,
        "direction": side,
        "period": {"start_date": start_date, "end_date": end_date},
        "invoice_count": count[invoice_type],
        "credit_note_count": count[credit_type],
        "invoice_label": invoice_label,
        "credit_note_label": credit_label,
        "totals_by_currency": {
            cur: {
                "invoices": round(v["invoices"], 2),
                "credit_notes": round(v["credit_notes"], 2),
                "net": round(v["invoices"] - v["credit_notes"], 2),
            }
            for cur, v in sorted(by_currency.items())
        },
        "unpaid_by_currency": unpaid,
        "first_document_date": _iso(first_date),
        "last_document_date": _iso(last_date),
    }

    if len(by_currency) == 1:
        cur, v = next(iter(result["totals_by_currency"].items()))
        result["currency"] = cur
        result["invoice_total"] = v["invoices"]
        result["credit_note_total"] = v["credit_notes"]
        result["net_total"] = v["net"]
        if count[invoice_type]:
            result["average_invoice_value"] = round(v["invoices"] / count[invoice_type], 2)

    if base_currency and converted_rows:
        sums = {r["move_type"]: _num(r["total"]) for r in converted_rows}
        result["converted"] = {
            "currency": base_currency,
            "invoice_total": sums.get(invoice_type, 0.0),
            "credit_note_total": sums.get(credit_type, 0.0),
            "net_total": round(sums.get(invoice_type, 0.0) - sums.get(credit_type, 0.0), 2),
        }

    if not rows:
        result["status"] = "NO_DATA"
        result["message"] = f"No posted {invoice_label} or {credit_label} found for the selected scope and period."
    else:
        result["status"] = "SUCCESS"
        result["message"] = (
            f"{count[invoice_type]} posted {invoice_label} and {count[credit_type]} {credit_label}. "
            f"Report {invoice_label} and {credit_label} separately; the net is {invoice_label} minus {credit_label}. "
            "These are accounting documents; they are not the same as sales orders."
        )
    return result


# ── Record listing ────────────────────────────────────────────────────────────

def render_records_table(
    rows: list[dict],
    partner_label: str,
    offset: int,
    total_count: int,
    totals_by_currency: dict[str, float],
    show_unpaid: bool,
) -> str:
    """Markdown table for the given rows, plus a one-line footer with the true totals."""
    companies = {r["company"] for r in rows if r.get("company")}
    show_company = len(companies) > 1

    headers = ["#", "Reference", "Date", partner_label]
    if show_company:
        headers.append("Company")
    headers += ["Amount", "Currency"]
    if show_unpaid:
        headers.append("Unpaid")
    headers.append("Status")

    lines = ["| " + " | ".join(headers) + " |", "|" + "|".join(["---"] * len(headers)) + "|"]
    for i, r in enumerate(rows, start=offset + 1):
        cells = [str(i), _cell(r["reference"]), _cell(r["date"]), _cell(r["partner"])]
        if show_company:
            cells.append(_cell(r["company"]))
        cells += [_fmt_amount(r["amount"]), _cell(r["currency"])]
        if show_unpaid:
            cells.append(_fmt_amount(r.get("unpaid")))
        cells.append(_cell(r["status"]))
        lines.append("| " + " | ".join(cells) + " |")

    first, last = (offset + 1, offset + len(rows)) if rows else (0, 0)
    totals = ", ".join(f"{cur} {_fmt_amount(v)}" for cur, v in totals_by_currency.items())
    lines.append("")
    lines.append(f"*Rows {first}-{last} of {total_count:,}. Total of all {total_count:,}: {totals}.*")
    return "\n".join(lines)


def list_records_tool(
    tenant_ids: Optional[list[str]] = None,
    company_ids: Optional[list[int]] = None,
    record_type: str = "customer_invoices",
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    partner_name: Optional[str] = None,
    status: Optional[str] = None,
    limit: Any = DEFAULT_LIST_ROWS,
    offset: Any = 0,
    sort: str = "date_desc",
) -> dict:
    """Rows of sales orders, purchase orders, invoices, credit notes or vendor bills."""
    tool = "list_records_tool"
    tenants, problem = _require_tenants(tool, tenant_ids)
    if problem:
        return problem

    kind = (record_type or "").strip().lower()
    spec = RECORD_TYPES.get(kind)
    if spec is None:
        return _error(tool, f"record_type must be one of: {', '.join(RECORD_TYPES)}.")

    notes: list[str] = []
    wanted = (status or "").strip().lower()
    if wanted in ("", "default", "confirmed", "posted"):
        states: Optional[tuple] = spec["default_states"]
    elif wanted == "all":
        states = None
    elif wanted in spec["allowed_states"]:
        states = (wanted,)
    else:
        return _error(tool, f"status for {kind} must be 'all' or one of: {', '.join(spec['allowed_states'])}.")

    order_key = (sort or "date_desc").strip().lower()
    if order_key not in SORTS:
        notes.append(f"Unknown sort '{sort}', used date_desc. Valid sorts: {', '.join(SORTS)}.")
        order_key = "date_desc"

    try:
        requested = int(limit)
    except (TypeError, ValueError):
        requested = DEFAULT_LIST_ROWS
    page_size = max(1, min(requested, MAX_LIST_ROWS))
    if requested > MAX_LIST_ROWS:
        notes.append(f"limit was capped at {MAX_LIST_ROWS} rows per page; use offset for the next page.")
    try:
        skip = max(0, int(offset))
    except (TypeError, ValueError):
        skip = 0

    date_expr = spec["date_expr"]
    order_by = {
        "date_desc": f"{date_expr} DESC, t.id DESC",
        "date_asc": f"{date_expr} ASC, t.id ASC",
        "amount_desc": "t.amount_total DESC, t.id DESC",
        "amount_asc": "t.amount_total ASC, t.id ASC",
    }[order_key]

    companies = normalize_company_ids(company_ids)
    t_sql, params = build_tenant_filter_sql(tenant_ids=tenants, column_name="t.tenant_id", prefix="t_rec")
    c_sql, c_params = build_company_filter_sql(company_ids=companies, column_name="t.company_id", prefix="c_rec")
    d_sql, d_params = _date_clause(date_expr, start_date, end_date)
    params = {**params, **c_params, **d_params}

    where = f"WHERE 1=1 {t_sql} {c_sql} {d_sql}"
    if spec["move_types"]:
        where += " AND t.move_type IN (" + ", ".join(f"'{m}'" for m in spec["move_types"]) + ")"
    if states:
        names = []
        for i, s in enumerate(states):
            params[f"rec_state_{i}"] = s
            names.append(f":rec_state_{i}")
        where += f" AND t.state IN ({', '.join(names)})"
    if partner_name and partner_name.strip():
        params["rec_partner"] = f"%{partner_name.strip()}%"
        where += " AND p.name ILIKE :rec_partner"

    unpaid_select = ", t.amount_residual AS unpaid" if spec["has_unpaid"] else ""
    joins = (
        "LEFT JOIN dim_partners p ON p.id = t.partner_id AND p.tenant_id = t.tenant_id "
        "LEFT JOIN dim_companies c ON c.id = t.company_id"
    )
    try:
        data = run_query(
            f"""SELECT t.odoo_name AS reference, {date_expr} AS doc_date, p.name AS partner,
                       c.name AS company, t.amount_total AS amount, t.currency_code AS currency,
                       t.state AS status{unpaid_select}
                FROM {spec['table']} t {joins}
                {where}
                ORDER BY {order_by}
                LIMIT :rec_limit OFFSET :rec_offset""",
            {**params, "rec_limit": page_size, "rec_offset": skip},
        )
        totals = run_query(
            f"""SELECT t.currency_code AS currency, COUNT(*) AS n, COALESCE(SUM(t.amount_total), 0) AS total
                FROM {spec['table']} t {joins}
                {where}
                GROUP BY t.currency_code ORDER BY t.currency_code""",
            params,
        )
    except Exception as exc:  # database or date-format problems must reach the model as an error, not a crash
        return _error(tool, f"Could not read {kind}: {exc}")

    total_count = sum(int(r["n"] or 0) for r in totals)
    totals_by_currency = {(r["currency"] or "UNKNOWN"): _num(r["total"]) for r in totals}

    rows = [
        {
            "reference": r["reference"] or "",
            "date": _iso(r["doc_date"]),
            "partner": r["partner"] or "",
            "company": r["company"] or "",
            "amount": _num(r["amount"]),
            "currency": r["currency"] or "",
            "status": r["status"] or "",
            **({"unpaid": _num(r["unpaid"])} if spec["has_unpaid"] else {}),
        }
        for r in data
    ]

    result: dict[str, Any] = {
        "tool_name": tool,
        "record_type": kind,
        "filters": {
            "start_date": start_date, "end_date": end_date, "partner_name": partner_name,
            "status": wanted or "default", "sort": order_key,
        },
        "total_count": total_count,
        "returned": len(rows),
        "offset": skip,
        "has_more": skip + len(rows) < total_count,
        "totals_by_currency": totals_by_currency,
        "rows": rows,
    }
    if notes:
        result["notes"] = notes

    if not rows:
        result["status"] = "NO_DATA"
        result["message"] = (
            f"No {kind.replace('_', ' ')} match these filters."
            if total_count == 0
            else f"Offset {skip} is past the end: there are only {total_count:,} {kind.replace('_', ' ')}."
        )
        return result

    table = render_records_table(rows, spec["partner_label"], skip, total_count, totals_by_currency, spec["has_unpaid"])
    marker = register_table(table, always_show=True)
    result["status"] = "SUCCESS"
    more = f" {total_count - skip - len(rows):,} more exist; use offset={skip + len(rows)} for the next page." if result["has_more"] else ""
    if marker:
        result["table"] = marker
        result["display_instruction"] = (
            f"Write {marker} on its own line where the table belongs in your answer; the server replaces it with the exact "
            "rows. Do not retype, reorder, shorten or rebuild these rows in your own table or list. "
            f"You may add one or two sentences of context.{more}"
        )
    else:
        result["table_markdown"] = table
        result["display_instruction"] = (
            f"Show table_markdown exactly as given, without changing any row.{more}"
        )
    return result
