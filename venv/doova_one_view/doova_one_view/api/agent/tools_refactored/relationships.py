"""
Does the business already trade with a company?

Used before calling a company a competitor. The assistant used to search the records with the
company's full public name ("CFAO Motors"), which misses how the company is saved in Odoo
("cfao MOBILTY"), so two runs of the same question could reach opposite conclusions. This tool
does the matching in code: it drops legal and generic words, searches the distinctive words at
the start of a word, and checks sales orders, customer invoices, purchase orders and vendor bills
in one call.

The result is facts only. Whether a company is a competitor depends on what it sells and to whom;
a trading relationship is context, not a verdict.
"""

from __future__ import annotations

import re
from typing import Any, Optional

from ..db import run_query
from ..query_context import (
    build_company_filter_sql,
    build_tenant_filter_sql,
    normalize_company_ids,
    normalize_tenant_ids,
)
from .common import build_currency_case_sql

TOOL = "get_company_relationship_tool"
MAX_MATCHES = 15

# Words that say what kind of company it is, or where, but not which company.
_GENERIC_WORDS = {
    # legal forms
    "sa", "sl", "sas", "sarl", "sau", "slu", "ltd", "llc", "inc", "plc", "gmbh", "bv", "nv", "spa", "srl",
    "co", "corp", "corporation", "company", "cie", "limited", "fze", "fzco", "fzc", "sal", "offshore",
    # generic business words
    "group", "groupe", "grupo", "holding", "holdings", "international", "intl", "trading", "trade", "traders",
    "motors", "motor", "automotive", "automobiles", "mobility", "mobilty", "services", "service", "solutions",
    "enterprise", "enterprises", "commercial", "comercial", "general", "industries", "industry", "distribution",
    "distributor", "distributors", "import", "export", "imports", "exports", "store", "stores", "shop", "shops",
    "electronics", "electronic", "appliances", "center", "centre", "centro", "comercio",
    # articles and connectors
    "the", "and", "et", "y", "de", "del", "la", "le", "les", "el", "los", "las", "of", "du", "des",
    # places and nationalities that are not part of a name
    "guinea", "guinee", "ecuatorial", "equatorial", "equatoriale", "malabo", "bata", "mongomo",
    "guinean", "guineana", "guineano", "equato", "ecuato", "equatoguinean", "ecuatoguineana", "ecuatoguineano",
    "africa", "african", "afrique", "central", "cemac",
}
_WORD = re.compile(r"[^\W_]+", re.UNICODE)


def acronyms(company_name: str) -> list[str]:
    """Upper-case short codes in the name ("EGTC", "CFAO"), lower-cased. An acronym is the most
    distinctive part of a name, so finding it alone identifies the company."""
    out = []
    for w in _WORD.findall(company_name or ""):
        low = w.lower()
        if 3 <= len(w) <= 6 and w.isalpha() and w.isupper() and low not in _GENERIC_WORDS and low not in out:
            out.append(low)
    return out


def search_terms(company_name: str) -> list[str]:
    """Distinctive words of a company name: acronyms first, then the longest words.

    "CFAO Motors Guinea Ecuatorial" -> ["cfao"]; "Steel Proyect S.L." -> ["proyect", "steel"];
    "EGTC Equato Guinean Trading Company" -> ["egtc"].
    If every word is generic, the longest word (3+ letters) is used so the search still runs.
    """
    words = [w.lower() for w in _WORD.findall(company_name or "")]
    distinctive = [w for w in words if len(w) >= 3 and not w.isdigit() and w not in _GENERIC_WORDS]
    if not distinctive:
        distinctive = sorted((w for w in words if len(w) >= 3 and not w.isdigit()), key=len, reverse=True)[:1]
    ordered: list[str] = [a for a in acronyms(company_name) if a in distinctive]
    for w in sorted(distinctive, key=len, reverse=True):
        if w not in ordered:
            ordered.append(w)
    return ordered


def _word_start_pattern(term: str) -> str:
    # Postgres regex: the term must start a word ("egtc" matches "EGTC BATA" and "jaber-egtc",
    # not "megtcx"). Terms are letters and digits only, so escaping is a formality.
    return r"\m" + re.escape(term)


def _starts_a_word(term: str, name: str) -> bool:
    return re.search(r"(?<![^\W_])" + re.escape(term), name.lower()) is not None


def _money(value: Any) -> float:
    try:
        return round(float(value or 0), 2)
    except (TypeError, ValueError):
        return 0.0


def _activity_rows(sql: str, params: dict) -> dict[int, dict]:
    out: dict[int, dict] = {}
    for r in run_query(sql, params):
        out[int(r["partner_id"])] = {
            "count": int(r["n"] or 0),
            "total": _money(r["total"]),
            "last": str(r["last"]) if r.get("last") else None,
        }
    return out


def get_company_relationship_tool(
    company_name: str,
    tenant_ids: Optional[list[str]] = None,
    company_ids: Optional[list[int]] = None,
) -> dict:
    """Is ``company_name`` a customer, a supplier, both, a contact only, or unknown to the business?"""
    tenants = normalize_tenant_ids(tenant_ids)
    if not tenants:
        return {"tool_name": TOOL, "status": "ERROR", "message": "No tenant selected."}
    terms = search_terms(company_name)
    if not terms:
        return {"tool_name": TOOL, "status": "ERROR",
                "message": "Give a company name with at least one word of 3 or more letters."}

    companies = normalize_company_ids(company_ids)
    t_sql, t_params = build_tenant_filter_sql(tenant_ids=tenants, column_name="p.tenant_id", prefix="t_rel")
    params: dict[str, Any] = dict(t_params)
    likes = []
    for i, term in enumerate(terms):
        params[f"rel_term_{i}"] = _word_start_pattern(term)
        likes.append(f"p.name ~* :rel_term_{i}")

    partners = run_query(
        f"""SELECT p.id, p.name, p.city
            FROM dim_partners p
            WHERE 1=1 {t_sql} AND ({' OR '.join(likes)})
            ORDER BY p.name
            LIMIT 200""",
        params,
    )

    from doova_one_view.api.agent.utils import get_tenant_currency
    currency = get_tenant_currency(tenant_ids=tenants)

    if not partners:
        return {
            "tool_name": TOOL,
            "status": "SUCCESS",
            "searched_for": company_name,
            "search_terms": terms,
            "relationship": "none found",
            "summary": f"No customer, supplier or contact matching {', '.join(terms)} in this business's records.",
            "matches": [],
            "total_matches": 0,
            "currency": currency,
        }

    ids = [int(p["id"]) for p in partners]
    base: dict[str, Any] = {"rel_ids": ids}
    tt_sql, tt_params = build_tenant_filter_sql(tenant_ids=tenants, column_name="tenant_id", prefix="t_act")
    c_sql, c_params = build_company_filter_sql(company_ids=companies, column_name="company_id", prefix="c_act")
    base.update(tt_params)
    base.update(c_params)
    scope = f"{tt_sql} {c_sql} AND partner_id = ANY(:rel_ids)"
    order_amount = build_currency_case_sql(
        "amount_total", tenant_ids=tenants, currency_column="currency_code", is_transaction_currency=True
    )

    sales = _activity_rows(
        f"""SELECT partner_id, COUNT(*) n, SUM({order_amount}) total, MAX(date_order)::date last
            FROM fact_sales_orders WHERE state IN ('sale', 'done') {scope} GROUP BY partner_id""", base)
    purchases = _activity_rows(
        f"""SELECT partner_id, COUNT(*) n, SUM({order_amount}) total, MAX(date_order)::date last
            FROM fact_purchase_orders WHERE state IN ('purchase', 'done') {scope} GROUP BY partner_id""", base)
    # amount_total_signed is already in the company currency
    invoices = _activity_rows(
        f"""SELECT partner_id, COUNT(*) n, SUM(ABS(amount_total_signed)) total,
                   MAX(COALESCE(invoice_date, date)) last
            FROM fact_account_moves WHERE move_type = 'out_invoice' AND state = 'posted' {scope}
            GROUP BY partner_id""", base)
    bills = _activity_rows(
        f"""SELECT partner_id, COUNT(*) n, SUM(ABS(amount_total_signed)) total,
                   MAX(COALESCE(invoice_date, date)) last
            FROM fact_account_moves WHERE move_type = 'in_invoice' AND state = 'posted' {scope}
            GROUP BY partner_id""", base)

    codes = acronyms(company_name)

    def strength(name: str) -> str:
        # The whole name, or its acronym, identifies the company; anything less is only a hint.
        if all(_starts_a_word(t, name) for t in terms) or any(_starts_a_word(a, name) for a in codes):
            return "full name"
        return "partial"

    matches = []
    for p in partners:
        pid = int(p["id"])
        name = p["name"] or ""
        so, inv, po, bill = sales.get(pid), invoices.get(pid), purchases.get(pid), bills.get(pid)
        is_customer = bool(so or inv)
        is_supplier = bool(po or bill)
        role = ("customer and supplier" if is_customer and is_supplier else
                "customer" if is_customer else "supplier" if is_supplier else "contact only")
        activity = {}
        for key, data in (("sales_orders", so), ("customer_invoices", inv), ("purchase_orders", po), ("vendor_bills", bill)):
            if data:
                activity[key] = data
        matches.append({
            "name": name,
            "match": strength(name),
            "role": role,
            "city": p.get("city") or None,
            "activity": activity,
            "_weight": sum(a["total"] for a in activity.values()),
        })

    # Full-name matches first, trading partners before plain contacts, biggest first.
    matches.sort(key=lambda m: (m["match"] != "full name", m["role"] == "contact only", -m["_weight"], m["name"]))
    for m in matches:
        m.pop("_weight", None)

    strong = [m for m in matches if m["match"] == "full name"]
    basis = strong or matches
    customer = any(m["role"] in ("customer", "customer and supplier") for m in basis)
    supplier = any(m["role"] in ("supplier", "customer and supplier") for m in basis)
    relationship = ("customer and supplier" if customer and supplier else
                    "customer" if customer else "supplier" if supplier else
                    "contact only (no orders, invoices or bills)")
    if not strong:
        relationship = f"possible {relationship} (only part of the name matched: check the names)"

    labels = {"sales_orders": "sales order", "customer_invoices": "customer invoice",
              "purchase_orders": "purchase order", "vendor_bills": "vendor bill"}

    def describe(m: dict) -> str:
        parts = [
            f"{a['count']} {labels[k]}{'' if a['count'] == 1 else 's'} ({a['total']:,.0f} {currency}, last {a['last']})"
            for k, a in m["activity"].items()
        ]
        return f"'{m['name']}' ({m['role']}): " + ("; ".join(parts) if parts else "no orders, invoices or bills")

    shown = matches[:MAX_MATCHES]
    summary = " | ".join(describe(m) for m in shown[:5])
    if len(matches) > 5:
        summary += f" | and {len(matches) - 5} more matching contact(s)"

    return {
        "tool_name": TOOL,
        "status": "SUCCESS",
        "searched_for": company_name,
        "search_terms": terms,
        "relationship": relationship,
        "summary": summary,
        "matches": shown,
        "total_matches": len(matches),
        "currency": currency,
        "note": (
            "A trading relationship does not decide whether this company is a competitor: judge that by what "
            "it sells and to whom. Shops that buy this business's products to resell them are customers, not "
            "competitors. Check that a matched name really is the same company before relying on it."
        ),
    }
