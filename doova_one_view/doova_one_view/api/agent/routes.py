"""
Agent routes – FastAPI endpoints for the AI Financial Advisor.
Supports multi-tenant chat, reasoning, reporting, and file processing.
"""

from uuid import uuid4
from typing import Any, Dict, List, Optional
from pathlib import Path
from html import escape
import re
from datetime import date, datetime, timedelta
import os
import shutil

from fastapi import APIRouter, HTTPException, Body, UploadFile, File
from fastapi.responses import FileResponse, JSONResponse

from .db import run_query
from .schemas import AgentChatRequest, AgentChatResponse
from .router import RouterNode
from .fast_path import FastPathNode
from .reasoning import ReasoningNode
from .memory import SessionMemory
from .sql_agent import run_sql_agent
from .tools import (
    is_graph_request,
    extract_graph_data,
    run_fast_tool,
    generate_report_tool,
    get_last_report_tool,
    normalize_business_text_for_intent,
    is_pdf_request,
    generate_pdf,
)

# ─────────────────────────────
# Router
# ─────────────────────────────
router = APIRouter(tags=["Agent"])


# ─────────────────────────────
# Agent Nodes
# ─────────────────────────────
router_node = RouterNode()
fast_node = FastPathNode()
reasoning_node = ReasoningNode()
memory = SessionMemory()


# ─────────────────────────────
# Local dev upload/report storage
# ─────────────────────────────
UPLOAD_DIR = Path("uploads")
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

REPORTS_DIR = Path("reports")
REPORTS_DIR.mkdir(parents=True, exist_ok=True)

uploaded_files: dict[str, dict] = {}


# ─────────────────────────────
# Helpers
# ─────────────────────────────
def parse_optional_int(value):
    if value is None or value == "" or value == "null":
        return None

    try:
        return int(value)
    except Exception:
        return None
def parse_company_ids_for_agent(company_id: int | None = None, companies: list[int] | None = None) -> list[int]:
    ids: list[int] = []

    if companies:
        for value in companies:
            try:
                ids.append(int(value))
            except Exception:
                pass

    if company_id is not None:
        try:
            ids.append(int(company_id))
        except Exception:
            pass

    # Default visible dashboard companies if frontend/session sends nothing.
    if not ids:
        ids = [2, 3, 4, 5, 11]

    return list(dict.fromkeys(ids))


def _month_range_from_message(message: str) -> tuple[str | None, str | None, str | None]:
    text = (message or "").lower().strip()

    month_map = {
        "january": 1, "jan": 1,
        "february": 2, "feb": 2,
        "march": 3, "mar": 3,
        "april": 4, "apr": 4,
        "may": 5,
        "june": 6, "jun": 6,
        "july": 7, "jul": 7,
        "august": 8, "aug": 8,
        "september": 9, "sep": 9, "sept": 9,
        "october": 10, "oct": 10,
        "november": 11, "nov": 11,
        "december": 12, "dec": 12,
    }

    month_pattern = (
        r"january|jan|february|feb|march|mar|april|apr|may|june|jun|"
        r"july|jul|august|aug|september|sep|sept|october|oct|"
        r"november|nov|december|dec"
    )

    if "today" in text:
        today = date.today()
        return today.isoformat(), today.isoformat(), today.strftime("%B %d, %Y")

    if "yesterday" in text:
        d = date.today() - timedelta(days=1)
        return d.isoformat(), d.isoformat(), d.strftime("%B %d, %Y")

    if "last month" in text:
        today = date.today()
        first_this_month = today.replace(day=1)
        last_prev_month = first_this_month - timedelta(days=1)
        start = last_prev_month.replace(day=1)
        end = last_prev_month
        return start.isoformat(), end.isoformat(), start.strftime("%B %Y")

    # Example: February 2025 / Feb 2025 / feb 2025
    match = re.search(rf"\b({month_pattern})\s+(\d{{4}})\b", text)
    if match:
        month_name = match.group(1)
        year = int(match.group(2))
        month = month_map[month_name]

        start = date(year, month, 1)
        if month == 12:
            end = date(year, 12, 31)
        else:
            end = date(year, month + 1, 1) - timedelta(days=1)

        return start.isoformat(), end.isoformat(), start.strftime("%B %Y")

    # Example: 10 March 2025 / 10 mar 2025
    match = re.search(rf"\b(\d{{1,2}})\s+({month_pattern})\s+(\d{{4}})\b", text)
    if match:
        day = int(match.group(1))
        month_name = match.group(2)
        year = int(match.group(3))
        month = month_map[month_name]

        try:
            d = date(year, month, day)
            return d.isoformat(), d.isoformat(), d.strftime("%B %d, %Y")
        except ValueError:
            return None, None, None

    # Example: 11-5-2026 or 11/5/2026
    # Interpreted as day-month-year.
    match = re.search(r"\b(\d{1,2})[-/](\d{1,2})[-/](\d{4})\b", text)
    if match:
        day = int(match.group(1))
        month = int(match.group(2))
        year = int(match.group(3))

        try:
            d = date(year, month, day)
            return d.isoformat(), d.isoformat(), d.strftime("%B %d, %Y")
        except ValueError:
            return None, None, None

    return None, None, None


def _month_name_without_year(message: str) -> str | None:
    text = (message or "").lower().strip()

    month_names = {
        "january": "January", "jan": "January",
        "february": "February", "feb": "February",
        "march": "March", "mar": "March",
        "april": "April", "apr": "April",
        "may": "May",
        "june": "June", "jun": "June",
        "july": "July", "jul": "July",
        "august": "August", "aug": "August",
        "september": "September", "sep": "September", "sept": "September",
        "october": "October", "oct": "October",
        "november": "November", "nov": "November",
        "december": "December", "dec": "December",
    }

    cleaned = text.replace("?", "").replace(".", "").strip()
    return month_names.get(cleaned)








def _is_reasoning_question(message: str | None) -> bool:
    text = normalize_business_text_for_intent(message or "")

    reasoning_phrases = [
        "why",
        "what should we do",
        "what can we do",
        "recommend",
        "recommendation",
        "analyze",
        "analysis",
        "compare",
        "explain",
        "reason",
        "cause",
        "root cause",
        "drop",
        "decrease",
        "increase",
        "higher than",
        "lower than",
        "improve",
        "prioritize",
        "which should we",
        "what is the best action",
    ]

    return any(phrase in text for phrase in reasoning_phrases)



def _agent_revenue_answer(
    tenant_id: str,
    message: str,
    context: str | None,
    company_id: int | None = None,
    companies: list[int] | None = None,
) -> str | None:
    

    text = normalize_business_text_for_intent(message)
    context_text = normalize_business_text_for_intent(context or "")

    # Do not answer "why/compare/analyze/recommend" questions as a simple revenue lookup.
    # These belong to reasoning mode.
    if _is_reasoning_question(message):
        return None

    blocked_tool_phrases = [
        "top products",
        "best-selling",
        "best selling",
        "inventory alerts",
        "low stock",
        "cash flow",
        "receivables",
        "payables",
        "forecast",
        "predict",
        "business health",
        "health score",
        "profitability",
        "profit margin",
        "report",
        "pdf",
        "graph",
        "chart",
        "trend",

        # Reasoning / explanation phrases.
        # These should not be answered as a simple revenue lookup.
        "why",
        "explain",
        "compare",
        "analyze",
        "analyse",
        "recommend",
        "recommendation",
        "what should",
        "should we",
        "higher than",
        "lower than",
        "difference",
        "drop",
        "dropped",
        "decrease",
        "increased",
        "increase",
        "root cause",
        "cause",
    ]

    if any(phrase in text for phrase in blocked_tool_phrases):
        return None

    is_sales_summary = "sales summary" in text

    is_plain_sales_period_question = (
        "sales in" in text
        or text.startswith("sales ")
        or text.startswith("sale ")
        or "sales for" in text
        or "sales during" in text
        or "how much did we sell" in text
        or "how much we sell" in text
        or "how much have we sold" in text
        or "what did we sell" in text
        or "what we sold" in text
    )

    is_sales_revenue = (
        "sales revenue" in text
        or "revenue sales" in text
        or "total sales" in text
        or "sales total" in text
        or is_sales_summary
        or is_plain_sales_period_question
        or "sales" in context_text
    )

    is_revenue_question = (
        "revenue" in text
        or "total sales" in text
        or "sales total" in text
        or "sales" in text
        or "sale " in text
        or "how much did we make" in text
        or "income" in text
        or is_sales_summary
        or is_plain_sales_period_question
    )

    if not is_revenue_question:
        return None

    start_date, end_date, period_label = _month_range_from_message(message)

    if not start_date or not end_date:
        if is_sales_revenue:
            return "Which date or period should I use for the sales revenue calculation?"
        return "Which date or period should I use for the revenue calculation?"

    company_ids = parse_company_ids_for_agent(company_id=company_id, companies=companies)








    params = {
        "tenant_id": tenant_id,
        "start_date": start_date,
        "end_date": end_date,
    }

    company_placeholders = []
    for index, cid in enumerate(company_ids):
        key = f"company_{index}"
        company_placeholders.append(f":{key}")
        params[key] = cid

    company_sql = ", ".join(company_placeholders)

    # If the user/frontend context says Sales, use sales orders.
    # Otherwise for Accounting/revenue, use account moves.
    use_sales = (
        "sales" in context_text
        or "sales revenue" in text
        or "sales summary" in text
        or "total sales" in text
        or "sales total" in text
        or text.startswith("give me the sales")
        or text.startswith("show me the sales")
    )


    if use_sales:
        rows = run_query(
            f"""
            SELECT
                COALESCE(SUM(amount_total), 0) AS revenue,
                COUNT(*) AS count
            FROM fact_sales_orders
            WHERE tenant_id = :tenant_id
              AND company_id IN ({company_sql})
              AND state IN ('sale', 'done')
              AND date_order >= :start_date
              AND date_order <= :end_date
            """,
            params,
        )

        revenue = float(rows[0]["revenue"] or 0) if rows else 0.0
        count = int(rows[0]["count"] or 0) if rows else 0

        average_order_value = revenue / count if count else 0.0

        is_summary_request = (
            "summary" in text
            or "sales summary" in text
            or "give me the sales" in text
        )

        if is_summary_request:
            return (
                f"## Sales Summary — {period_label}\n\n"
                f"For tenant `{tenant_id}`, across companies `{company_ids}`, here is the sales summary:\n\n"
                f"- **Total Sales Revenue:** {revenue:,.2f}\n"
                f"- **Confirmed Orders:** {count}\n"
                f"- **Average Order Value:** {average_order_value:,.2f}\n"
                f"- **Period:** `{start_date}` to `{end_date}`\n"
                f"- **Source:** `fact_sales_orders`\n"
                f"- **Included states:** `sale`, `done`"
            )

        return (
            f"## Sales Revenue — {period_label}\n\n"
            f"For tenant `{tenant_id}`, across companies `{company_ids}`, "
            f"the sales revenue was **{revenue:,.2f}**.\n\n"
            f"- Period: `{start_date}` to `{end_date}`\n"
            f"- Source: `fact_sales_orders`\n"
            f"- Included states: `sale`, `done`\n"
            f"- Orders counted: `{count}`"
        )
    rows = run_query(
        f"""
        SELECT
            COALESCE(SUM(amount_total), 0) AS revenue,
            COUNT(*) AS count
        FROM fact_account_moves
        WHERE tenant_id = :tenant_id
          AND company_id IN ({company_sql})
          AND invoice_date >= :start_date
          AND invoice_date <= :end_date
          AND move_type = 'out_invoice'
          AND state = 'posted'
        """,
        params,
    )

    revenue = float(rows[0]["revenue"] or 0) if rows else 0.0
    count = int(rows[0]["count"] or 0) if rows else 0

    return (
        f"## Accounting Revenue — {period_label}\n\n"
        f"For tenant `{tenant_id}`, across companies `{company_ids}`, "
        f"the accounting revenue was **{revenue:,.2f}**.\n\n"
        f"- Period: `{start_date}` to `{end_date}`\n"
        f"- Source: `fact_account_moves`\n"
        f"- Included records: posted customer invoices only\n"
        f"- Invoices counted: `{count}`"
    )


def _extract_month_year_pairs_for_reasoning(message: str) -> list[tuple[int, int, str]]:
    import re

    month_map = {
        "jan": 1, "january": 1,
        "feb": 2, "february": 2,
        "mar": 3, "march": 3,
        "apr": 4, "april": 4,
        "may": 5,
        "jun": 6, "june": 6,
        "jul": 7, "july": 7,
        "aug": 8, "august": 8,
        "sep": 9, "sept": 9, "september": 9,
        "oct": 10, "october": 10,
        "nov": 11, "november": 11,
        "dec": 12, "december": 12,
    }

    label_map = {
        1: "January", 2: "February", 3: "March", 4: "April",
        5: "May", 6: "June", 7: "July", 8: "August",
        9: "September", 10: "October", 11: "November", 12: "December",
    }

    pattern = r"\b(january|jan|february|feb|march|mar|april|apr|may|june|jun|july|jul|august|aug|september|sept|sep|october|oct|november|nov|december|dec)\s+(\d{4})\b"
    matches = re.findall(pattern, (message or "").lower())

    result = []
    for month_text, year_text in matches:
        month_number = month_map.get(month_text)
        if month_number:
            year_number = int(year_text)
            label = f"{label_map[month_number]} {year_number}"
            result.append((month_number, year_number, label))

    return result


def _month_bounds_from_number(year: int, month: int) -> tuple[str, str]:
    import calendar

    last_day = calendar.monthrange(year, month)[1]
    return f"{year:04d}-{month:02d}-01", f"{year:04d}-{month:02d}-{last_day:02d}"


def _sales_month_metrics(
    tenant_id: str,
    company_ids: list[int],
    start_date: str,
    end_date: str,
) -> dict:
    params = {
        "tenant_id": tenant_id,
        "start_date": start_date,
        "end_date": end_date,
    }

    placeholders = []
    for index, cid in enumerate(company_ids):
        key = f"company_{index}"
        placeholders.append(f":{key}")
        params[key] = cid

    rows = run_query(
        f"""
        SELECT
            COALESCE(SUM(amount_total), 0) AS revenue,
            COUNT(*) AS order_count,
            COALESCE(AVG(amount_total), 0) AS average_order_value
        FROM fact_sales_orders
        WHERE tenant_id = :tenant_id
          AND company_id IN ({", ".join(placeholders)})
          AND state IN ('sale', 'done')
          AND date_order >= :start_date
          AND date_order <= :end_date
        """,
        params,
    )

    row = rows[0] if rows else {}

    return {
        "revenue": float(row.get("revenue") or 0),
        "order_count": int(row.get("order_count") or 0),
        "average_order_value": float(row.get("average_order_value") or 0),
    }


def _accounting_revenue_metrics(
    tenant_id: str,
    company_ids: list[int],
    start_date: str,
    end_date: str,
) -> dict:
    params = {
        "tenant_id": tenant_id,
        "start_date": start_date,
        "end_date": end_date,
    }

    placeholders = []
    for index, cid in enumerate(company_ids):
        key = f"company_{index}"
        placeholders.append(f":{key}")
        params[key] = cid

    rows = run_query(
        f"""
        SELECT
            COALESCE(SUM(amount_total), 0) AS revenue,
            COUNT(*) AS invoice_count
        FROM fact_account_moves
        WHERE tenant_id = :tenant_id
          AND company_id IN ({", ".join(placeholders)})
          AND invoice_date >= :start_date
          AND invoice_date <= :end_date
          AND move_type = 'out_invoice'
          AND state = 'posted'
        """,
        params,
    )

    row = rows[0] if rows else {}

    return {
        "revenue": float(row.get("revenue") or 0),
        "invoice_count": int(row.get("invoice_count") or 0),
    }



def _agent_direct_reasoning_answer(
    tenant_id: str,
    message: str,
    context: str | None,
    company_id: int | None = None,
    companies: list[int] | None = None,
) -> str | None:
    """
    Deterministic reasoning answers for common business analysis questions.
    Uses direct SQL so we avoid generic Claude answers when the analysis is simple.
    """

    text = normalize_business_text_for_intent(message)
    company_ids = parse_company_ids_for_agent(company_id=company_id, companies=companies)

    # ─────────────────────────────
    # DIRECT SALES MONTH-TO-MONTH REASONING
    # Example:
    # "Why did sales drop from November 2025 to December 2025?"
    # "Compare October 2025 and November 2025 sales and explain"
    # ─────────────────────────────
    periods_for_sales_compare = _extract_month_year_pairs_for_reasoning(message)

    if (
        len(periods_for_sales_compare) >= 2
        and ("sales" in text or "revenue" in text or "sell" in text or "sold" in text)
        and any(word in text for word in [
            "why",
            "drop",
            "dropped",
            "decrease",
            "decreased",
            "increase",
            "increased",
            "compare",
            "comparison",
            "difference",
            "explain",
            "higher",
            "lower",
            "change",
            "changed",
        ])
    ):
        month1, year1, label1 = periods_for_sales_compare[0]
        month2, year2, label2 = periods_for_sales_compare[1]

        start1, end1 = _month_bounds_from_number(year1, month1)
        start2, end2 = _month_bounds_from_number(year2, month2)

        m1 = _sales_month_metrics(
            tenant_id=tenant_id,
            company_ids=company_ids,
            start_date=start1,
            end_date=end1,
        )

        m2 = _sales_month_metrics(
            tenant_id=tenant_id,
            company_ids=company_ids,
            start_date=start2,
            end_date=end2,
        )

        revenue_change = m2["revenue"] - m1["revenue"]
        order_change = m2["order_count"] - m1["order_count"]
        aov_change = m2["average_order_value"] - m1["average_order_value"]

        revenue_change_pct = (revenue_change / m1["revenue"] * 100) if m1["revenue"] else 0.0
        order_change_pct = (order_change / m1["order_count"] * 100) if m1["order_count"] else 0.0

        if revenue_change < 0:
            direction = "dropped"
        elif revenue_change > 0:
            direction = "increased"
        else:
            direction = "stayed flat"

        if m2["order_count"] < m1["order_count"]:
            main_driver = "lower confirmed order volume"
        elif m2["average_order_value"] < m1["average_order_value"]:
            main_driver = "lower average order value / product mix"
        else:
            main_driver = "a combination of order value and product mix"

        return (
            f"## Sales Change Analysis — {label1} vs {label2}\n\n"
            f"For tenant `{tenant_id}`, across companies `{company_ids}`:\n\n"
            f"| Metric | {label1} | {label2} | Change |\n"
            f"|---|---:|---:|---:|\n"
            f"| Sales revenue | {m1['revenue']:,.2f} | {m2['revenue']:,.2f} | {revenue_change:,.2f} ({revenue_change_pct:,.2f}%) |\n"
            f"| Confirmed orders | {m1['order_count']} | {m2['order_count']} | {order_change} ({order_change_pct:,.2f}%) |\n"
            f"| Average order value | {m1['average_order_value']:,.2f} | {m2['average_order_value']:,.2f} | {aov_change:,.2f} |\n\n"
            f"### Why it happened\n\n"
            f"Sales **{direction}** from {label1} to {label2}. "
            f"The main visible driver is **{main_driver}**. "
            f"{label2} had **{m2['order_count']} confirmed orders** compared with "
            f"**{m1['order_count']} confirmed orders** in {label1}.\n\n"
            f"### Interpretation\n\n"
            f"- If confirmed orders dropped, the decline is mostly demand/order-volume related.\n"
            f"- If order count stayed close but average order value dropped, the issue is likely product mix or fewer high-ticket deals.\n"
            f"- If both dropped, then both customer activity and deal size weakened.\n\n"
            f"### Recommended next action\n\n"
            f"Compare the top products and top customers for {label1} and {label2}. "
            f"That will show whether the drop came from lost high-ticket products, fewer customers, or lower order volume."
        )

    # Build company filter
    params = {"tenant_id": tenant_id}
    company_placeholders = []
    for index, cid in enumerate(company_ids):
        key = f"company_{index}"
        company_placeholders.append(f":{key}")
        params[key] = cid
    company_sql = ", ".join(company_placeholders)

    # ─────────────────────────────
    # Accounting revenue vs sales revenue
    # ─────────────────────────────
    is_revenue_gap_question = (
        "accounting revenue" in text
        and "sales revenue" in text
        and (
            "why" in text
            or "higher than" in text
            or "lower than" in text
            or "difference" in text
            or "compare" in text
            or "explain" in text
        )
    )

    if is_revenue_gap_question:
        start_date, end_date, period_label = _month_range_from_message(message)

        if not start_date or not end_date:
            return "Which date or period should I use to compare accounting revenue and sales revenue?"

        params.update({
            "start_date": start_date,
            "end_date": end_date,
        })

        sales_rows = run_query(
            f"""
            SELECT
                COALESCE(SUM(amount_total), 0) AS sales_revenue,
                COUNT(*) AS sales_order_count
            FROM fact_sales_orders
            WHERE tenant_id = :tenant_id
              AND company_id IN ({company_sql})
              AND state IN ('sale', 'done')
              AND date_order >= :start_date
              AND date_order <= :end_date
            """,
            params,
        )

        accounting_rows = run_query(
            f"""
            SELECT
                COALESCE(SUM(amount_total), 0) AS accounting_revenue,
                COUNT(*) AS invoice_count
            FROM fact_account_moves
            WHERE tenant_id = :tenant_id
              AND company_id IN ({company_sql})
              AND move_type = 'out_invoice'
              AND state = 'posted'
              AND invoice_date >= :start_date
              AND invoice_date <= :end_date
            """,
            params,
        )

        sales_revenue = float(sales_rows[0]["sales_revenue"] or 0) if sales_rows else 0.0
        sales_order_count = int(sales_rows[0]["sales_order_count"] or 0) if sales_rows else 0

        accounting_revenue = float(accounting_rows[0]["accounting_revenue"] or 0) if accounting_rows else 0.0
        invoice_count = int(accounting_rows[0]["invoice_count"] or 0) if accounting_rows else 0

        difference = accounting_revenue - sales_revenue

        if sales_revenue:
            difference_pct = (difference / sales_revenue) * 100
            difference_pct_text = f"{difference_pct:,.2f}%"
        else:
            difference_pct_text = "N/A"

        if difference > 0:
            direction = "higher"
        elif difference < 0:
            direction = "lower"
        else:
            direction = "equal"

        return (
            f"## Accounting Revenue vs Sales Revenue — {period_label}\n\n"
            f"For tenant `{tenant_id}`, across companies `{company_ids}`:\n\n"
            f"| Metric | Value |\n"
            f"|---|---:|\n"
            f"| Accounting Revenue | {accounting_revenue:,.2f} |\n"
            f"| Sales Revenue | {sales_revenue:,.2f} |\n"
            f"| Difference | {difference:,.2f} |\n"
            f"| Difference vs Sales | {difference_pct_text} |\n"
            f"| Posted Invoices Count | {invoice_count} |\n"
            f"| Confirmed Sales Orders Count | {sales_order_count} |\n\n"
            f"### Explanation\n\n"
            f"Accounting revenue is **{direction}** than sales revenue for this period because the two sources measure different business events:\n\n"
            f"- `fact_sales_orders` counts confirmed sales orders with state `sale` or `done`.\n"
            f"- `fact_account_moves` counts posted customer invoices with `move_type = out_invoice` and `state = posted`.\n\n"
            f"So the values can differ when:\n\n"
            f"1. Some invoices were posted in October for sales orders created in another month.\n"
            f"2. Some October sales orders were not invoiced yet.\n"
            f"3. Invoices may include adjustments, services, delivery fees, taxes, or accounting entries not matching the sales-order total exactly.\n"
            f"4. Cancellations/returns/credit notes may affect one table differently depending on sync logic.\n\n"
            f"### Conclusion\n\n"
            f"The gap is not automatically an error. It means **sales orders and posted invoices are not the same accounting event**. "
            f"To fully reconcile it, the next check should match October invoices back to their related sales orders."
        )

    return None



def format_execution_plan_message(plan: dict) -> str:
    """
    Convert a structured Financial Execution Plan into markdown text
    so the frontend can display it even if it ignores the `plan` JSON field.
    """
    if not plan:
        return "I prepared a financial execution plan. Please approve it before I continue with the final analysis."

    lines = []
    lines.append("## Financial Execution Plan")
    lines.append("")
    lines.append("I prepared a financial execution plan. Please approve it before I continue with the final analysis.")
    lines.append("")

    question_summary = plan.get("question_summary")
    if question_summary:
        lines.append("### Question Summary")
        lines.append(question_summary)
        lines.append("")

    data_sources = plan.get("data_sources_used") or []
    if data_sources:
        lines.append("### Data Sources / Tools to Use")
        for source in data_sources:
            lines.append(f"- `{source}`")
        lines.append("")

    key_findings = plan.get("key_findings") or []
    if key_findings:
        lines.append("### Initial Findings / Assumptions")
        for finding in key_findings:
            lines.append(f"- {finding}")
        lines.append("")

    steps = plan.get("proposed_analysis_steps") or []
    if steps:
        lines.append("### Proposed Analysis Steps")
        for step in steps:
            step_no = step.get("step", "")
            action = step.get("action", "")
            rationale = step.get("rationale", "")
            lines.append(f"**Step {step_no}:** {action}")
            if rationale:
                lines.append(f"- Rationale: {rationale}")
            lines.append("")

    estimated_depth = plan.get("estimated_depth")
    status = plan.get("status")

    lines.append("### Plan Status")
    if estimated_depth:
        lines.append(f"- Estimated depth: **{estimated_depth}**")
    if status:
        lines.append(f"- Status: **{status}**")
    lines.append("")

    lines.append("Reply with **approve** to continue, **edit** to change the plan, or **cancel** to stop.")

    return "\n".join(lines)


def get_public_base_url() -> str:
    """
    For ngrok/frontend downloads, set in .env:
    PUBLIC_BASE_URL=https://your-ngrok-url.ngrok-free.dev
    """
    return os.getenv("PUBLIC_BASE_URL", "").rstrip("/")


def make_report_url(report_path_or_filename: str | None) -> str | None:
    if not report_path_or_filename:
        return None

    filename = Path(report_path_or_filename).name
    public_base_url = get_public_base_url()

    if public_base_url:
        # router is usually mounted under /api/v1
        return f"{public_base_url}/api/v1/reports/{filename}"

    # fallback for local testing
    return f"/api/v1/reports/{filename}"


def normalize_graph_for_frontend(graph_data):
    """
    Frontend CustomChart expects:
    [
      {"name": "Jan", "value": 100},
      {"name": "Feb", "value": 200}
    ]
    """

    if not graph_data:
        return None

    # Already correct frontend shape
    if isinstance(graph_data, list):
        normalized = []
        for item in graph_data:
            if not isinstance(item, dict):
                continue

            if "name" in item and "value" in item:
                normalized.append(item)
            elif "x" in item and "y" in item:
                normalized.append(
                    {
                        "name": str(item.get("x")),
                        "value": float(item.get("y") or 0),
                    }
                )
            elif "month" in item and "revenue" in item:
                normalized.append(
                    {
                        "name": str(item.get("month")),
                        "value": float(item.get("revenue") or 0),
                    }
                )
            elif "date" in item and "value" in item:
                normalized.append(
                    {
                        "name": str(item.get("date")),
                        "value": float(item.get("value") or 0),
                    }
                )

        return normalized if normalized else None

    if isinstance(graph_data, dict):
        # Shape: {"x": [...], "y": [...]}
        if isinstance(graph_data.get("x"), list) and isinstance(graph_data.get("y"), list):
            return [
                {
                    "name": str(x_value),
                    "value": float(graph_data["y"][index] or 0),
                }
                for index, x_value in enumerate(graph_data["x"])
                if index < len(graph_data["y"])
            ]

        # Shape: {"labels": [...], "values": [...]}
        if isinstance(graph_data.get("labels"), list) and isinstance(graph_data.get("values"), list):
            return [
                {
                    "name": str(label),
                    "value": float(graph_data["values"][index] or 0),
                }
                for index, label in enumerate(graph_data["labels"])
                if index < len(graph_data["values"])
            ]

        # Shape: {"points": [{"x":..., "y":...}]}
        if isinstance(graph_data.get("points"), list):
            return normalize_graph_for_frontend(graph_data["points"])

        # Shape: {"data": [...]}
        if isinstance(graph_data.get("data"), list):
            return normalize_graph_for_frontend(graph_data["data"])

    return None


def create_svg_chart_file(graph_data, title: str = "Generated Chart") -> str | None:
    """
    Backend-only graph workaround.

    Creates a simple SVG line chart file in reports/.
    The frontend already displays message text, so we return a clickable graph URL
    inside the assistant message.
    """

    points = normalize_graph_for_frontend(graph_data)

    if not points:
        return None

    width = 760
    height = 420
    padding_left = 70
    padding_right = 30
    padding_top = 60
    padding_bottom = 70

    chart_width = width - padding_left - padding_right
    chart_height = height - padding_top - padding_bottom

    values = [float(point.get("value") or 0) for point in points]
    labels = [str(point.get("name") or "") for point in points]

    min_value = min(values)
    max_value = max(values)

    if max_value == min_value:
        max_value = min_value + 1

    def x_pos(index: int) -> float:
        if len(points) == 1:
            return padding_left + chart_width / 2
        return padding_left + (index / (len(points) - 1)) * chart_width

    def y_pos(value: float) -> float:
        ratio = (value - min_value) / (max_value - min_value)
        return padding_top + chart_height - (ratio * chart_height)

    svg_points = []
    circles = []
    x_labels = []

    for index, point in enumerate(points):
        x = x_pos(index)
        y = y_pos(float(point.get("value") or 0))
        svg_points.append(f"{x:.2f},{y:.2f}")

        circles.append(
            f"""
            <circle cx="{x:.2f}" cy="{y:.2f}" r="5" fill="#2563eb" />
            <text x="{x:.2f}" y="{y - 12:.2f}" text-anchor="middle" font-size="12" fill="#111827">
                {escape(str(round(float(point.get("value") or 0), 2)))}
            </text>
            """
        )

        label = labels[index]
        if len(label) > 14:
            label = label[:14] + "..."

        x_labels.append(
            f"""
            <text x="{x:.2f}" y="{height - 30}" text-anchor="middle" font-size="12" fill="#374151">
                {escape(label)}
            </text>
            """
        )

    y_axis_labels = f"""
        <text x="20" y="{padding_top}" font-size="12" fill="#374151">{escape(str(round(max_value, 2)))}</text>
        <text x="20" y="{padding_top + chart_height}" font-size="12" fill="#374151">{escape(str(round(min_value, 2)))}</text>
    """

    svg = f"""<?xml version="1.0" encoding="UTF-8"?>
<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">
    <rect width="100%" height="100%" fill="#ffffff"/>

    <text x="{width / 2}" y="30" text-anchor="middle" font-size="22" font-weight="bold" fill="#111827">
        {escape(title)}
    </text>

    <line x1="{padding_left}" y1="{padding_top}" x2="{padding_left}" y2="{padding_top + chart_height}" stroke="#9ca3af" stroke-width="1"/>
    <line x1="{padding_left}" y1="{padding_top + chart_height}" x2="{padding_left + chart_width}" y2="{padding_top + chart_height}" stroke="#9ca3af" stroke-width="1"/>

    <line x1="{padding_left}" y1="{padding_top}" x2="{padding_left + chart_width}" y2="{padding_top}" stroke="#e5e7eb" stroke-width="1"/>
    <line x1="{padding_left}" y1="{padding_top + chart_height / 2}" x2="{padding_left + chart_width}" y2="{padding_top + chart_height / 2}" stroke="#e5e7eb" stroke-width="1"/>

    {y_axis_labels}

    <polyline points="{' '.join(svg_points)}" fill="none" stroke="#2563eb" stroke-width="3"/>

    {''.join(circles)}
    {''.join(x_labels)}

    <text x="{width / 2}" y="{height - 8}" text-anchor="middle" font-size="11" fill="#6b7280">
        Generated by Doova AI backend
    </text>
</svg>
"""

    filename = f"graph_{uuid4().hex}.svg"
    file_path = REPORTS_DIR / filename

    with file_path.open("w", encoding="utf-8") as file:
        file.write(svg)

    return filename


def extract_uploaded_file_text(file_id: str) -> str:
    """
    Extract readable text from uploaded files.

    Supports:
    - .txt
    - .csv
    - .md
    - .json
    - .pdf using pypdf

    Images are acknowledged but not OCR-read yet.
    """

    file_info = uploaded_files.get(file_id)

    if not file_info:
        return (
            f"File reference received: fileId={file_id}, "
            "but file metadata was not found. The server may have restarted after upload."
        )

    file_path = Path(file_info.get("path", ""))
    filename = file_info.get("filename", "uploaded file")
    suffix = file_path.suffix.lower()

    if not file_path.exists():
        return f"File '{filename}' was uploaded, but the stored file path no longer exists."

    try:
        if suffix in [".txt", ".csv", ".md", ".json"]:
            text = file_path.read_text(encoding="utf-8", errors="ignore")
            return text[:8000]

        if suffix == ".pdf":
            try:
                from pypdf import PdfReader

                reader = PdfReader(str(file_path))
                pages_text = []

                for page in reader.pages[:5]:
                    pages_text.append(page.extract_text() or "")

                extracted = "\n".join(pages_text).strip()

                if not extracted:
                    return (
                        f"The PDF '{filename}' was uploaded, but no readable text was extracted. "
                        "It may be scanned/image-based and would need OCR."
                    )

                return extracted[:8000]

            except Exception as pdf_error:
                return (
                    f"The PDF '{filename}' was uploaded, but PDF text extraction failed: {pdf_error}"
                )

        if suffix in [".png", ".jpg", ".jpeg", ".webp", ".bmp"]:
            return (
                f"Image '{filename}' was uploaded successfully. "
                "Image OCR/vision analysis is not connected yet, so I can confirm receipt of the image, "
                "but I cannot read visual content from it in this backend version."
            )

        return (
            f"File '{filename}' was uploaded successfully, but this file type '{suffix}' "
            "is not supported for text extraction yet."
        )

    except Exception as error:
        return f"File '{filename}' was uploaded, but extraction failed: {error}"


def frontend_response(
    *,
    message: str,
    session_id: str,
    route: str = "FAST",
    graph_data=None,
    report_ready: bool = False,
    report_path: str | None = None,
    plan=None,
):
    """
    Frontend-compatible response.

    The frontend AI response component already supports graph/chart rendering if:
    - response.type is "graph" or "chart"
    - response.chart exists
    - response.graphData.chart exists
    - response.chartData.chart exists
    - response.payload.chart exists
    """

    is_chart_response = (
        isinstance(graph_data, dict)
        and (
            graph_data.get("type") in ["chart", "graph"]
            or graph_data.get("response_type") in ["chart", "graph"]
            or isinstance(graph_data.get("chart"), dict)
        )
    )

    if is_chart_response:
        chart_payload = graph_data.get("chart")
        chart_rows = graph_data.get("data") or (
            chart_payload.get("data", []) if isinstance(chart_payload, dict) else []
        )


        frontend_graph = {
            "type": "chart",
            "response_type": "chart",
            "chart": chart_payload,
            "data": chart_rows,
        }



        response_type = "chart"

        # Keep answer/message as readable text.
        # The actual graph object is sent separately in chart/graphData/payload.
        answer_text = message

    else:
        frontend_graph = normalize_graph_for_frontend(graph_data)
        chart_payload = None
        chart_rows = []
        response_type = "text"
        answer_text = message

    # Build download_url from report_path if present
    download_url = None
    if report_ready and report_path:
        download_url = report_path

    return {
        "success": True,

        # common answer field names
        "response": answer_text,
        "message": answer_text,
        "answer": answer_text,
        "reply": answer_text,
        "content": answer_text,
        "text": answer_text,

        # session fields
        "session_id": session_id,
        "sessionId": session_id,

        # agent fields
        "route": route,
        "plan": plan,

        # IMPORTANT for frontend graph rendering
        "type": response_type,
        "response_type": response_type,

        # direct chart fields
        "chart": chart_payload,
        "chartType": chart_payload.get("chartType") if isinstance(chart_payload, dict) else None,
        "data": chart_rows,

        # graph/chart fields
        "graph_data": frontend_graph,
        "graphData": frontend_graph,
        "chart_data": frontend_graph,
        "chartData": frontend_graph,
        "visualization": frontend_graph,

        # payload field because aiScreen.jsx passes response.payload into AIRESPONSE
        "payload": {
            "type": response_type,
            "chart": chart_payload,
            "data": chart_rows,
            "graphData": frontend_graph,
            "chartData": frontend_graph,
        },

        # report fields
        "report_ready": report_ready,
        "reportReady": report_ready,
        "report_path": report_path,
        "reportPath": report_path,
        "download_url": download_url,
        "downloadUrl": download_url,
    }

# ─────────────────────────────
# Helper: infer approval from natural language
# ─────────────────────────────
def infer_plan_action(message: str, explicit_action: str | None) -> str | None:
    if explicit_action:
        return explicit_action.lower().strip()

    text = message.lower().strip()

    approve_words = [
        "yes",
        "yes proceed",
        "proceed",
        "go ahead",
        "approved",
        "approve",
        "continue",
        "do it",
        "ok proceed",
    ]

    cancel_words = [
        "cancel",
        "stop",
        "never mind",
        "nevermind",
        "don't continue",
        "do not continue",
    ]

    edit_words = [
        "edit",
        "change",
        "modify",
        "focus on",
        "instead",
    ]

    if text in approve_words:
        return "approve"

    if any(word in text for word in cancel_words):
        return "cancel"

    if any(word in text for word in edit_words):
        return "edit"

    return None


# ─────────────────────────────
# Core agent function
# Shared by all endpoints
# ─────────────────────────────

# ─────────────────────────────
# Pending follow-up handling
# Example:
# User: "sales summary"
# Bot:  "Which date or period?"
# User: "March 2025"
# Bot:  "Sales Summary — March 2025"
# ─────────────────────────────

PENDING_AGENT_FOLLOWUPS: dict[str, dict[str, Any]] = {}


def _agent_message_has_business_keyword(message: str) -> bool:
    text = (message or "").lower()

    keywords = [
        "revenue",
        "sales",
        "sell",
        "sold",
        "orders",
        "customers",
        "products",
        "inventory",
        "stock",
        "low stock",
        "cash flow",
        "receivables",
        "payables",
        "profit",
        "margin",
        "forecast",
        "trend",
        "graph",
        "chart",
        "report",
        "business health",
        "database",
    ]

    return any(keyword in text for keyword in keywords)


def _infer_pending_followup_intent(message: str, context: str | None = None) -> str:
    text = (message or "").lower()
    context_text = (context or "").lower()

    if (
        "sales summary" in text
        or "how much did we sell" in text
        or "how much we sold" in text
        or "sold" in text
        or "sell" in text
    ):
        return "sales summary"

    if (
        "sales revenue" in text
        or "revenue sales" in text
        or "total sales" in text
        or "sales" in context_text
    ):
        return "sales revenue"

    if "revenue" in text or "income" in text or "how much did we make" in text:
        return "revenue"

    return "business question"


def _maybe_rewrite_pending_followup(
    session_id: str,
    message: str,
    context: str | None,
    company_id: int | None,
    companies: list[int] | None,
) -> tuple[str, str | None, int | None, list[int] | None]:
    pending = PENDING_AGENT_FOLLOWUPS.get(session_id)

    if not pending:
        return message, context, company_id, companies

    start_date, end_date, period_label = _month_range_from_message(message)

    # If user replied only with a date/period, attach it to the pending intent.
    if start_date and end_date and not _agent_message_has_business_keyword(message):
        intent = pending.get("intent") or "revenue"

        rewritten_message = f"{intent} {message}"

        rewritten_context = context or pending.get("context")
        rewritten_company_id = company_id if company_id is not None else pending.get("company_id")
        rewritten_companies = companies or pending.get("companies")

        PENDING_AGENT_FOLLOWUPS.pop(session_id, None)

        return rewritten_message, rewritten_context, rewritten_company_id, rewritten_companies

    # If user asked a new business question, clear the old pending follow-up.
    if _agent_message_has_business_keyword(message):
        PENDING_AGENT_FOLLOWUPS.pop(session_id, None)

    return message, context, company_id, companies

async def run_agent_chat(
    tenant_id: str,
    session_id: str,
    message: str,
    company_id: int | None = None,
    companies: list[int] | None = None,
    context: str | None = None,
    plan_action: str | None = None,
) -> AgentChatResponse:
    memory_summary = memory.get_summary(session_id)


    month_only = _month_name_without_year(message)
    if month_only and not _agent_message_has_business_keyword(message):
        return AgentChatResponse(
            session_id=session_id,
            route="FAST",
            message=f"Which year should I use for {month_only}?",
            plan=None,
            graph_data=None,
            report_ready=False,
            report_path=None,
        )

    # Direct handling for date-only follow-ups.
    # Example:
    # User: "sales summary"
    # Assistant: "Which date or period should I use?"
    # User: "March 2025"
    # Assistant: "Sales Summary — March 2025"
    followup_start, followup_end, followup_label = _month_range_from_message(message)
    if followup_start and followup_end and not _agent_message_has_business_keyword(message):
        context_text = (context or "").lower()
        pending = PENDING_AGENT_FOLLOWUPS.get(session_id, {})
        pending_intent = (pending.get("intent") or "").lower()
        pending_context = (pending.get("context") or "").lower()

        if (
            "sales summary" in pending_intent
            or "sales" in pending_context
            or "sales" in context_text
        ):
            rewritten_message = f"sales summary {message}"
        elif (
            "sales revenue" in pending_intent
            or "sales revenue" in context_text
        ):
            rewritten_message = f"sales revenue {message}"
        elif (
            "revenue" in pending_intent
            or "accounting" in pending_context
            or "accounting" in context_text
        ):
            rewritten_message = f"revenue {message}"
        else:
            rewritten_message = None






        if rewritten_message:
            direct_followup_answer = _agent_revenue_answer(
                tenant_id=tenant_id,
                message=rewritten_message,
                context=context,
                company_id=company_id,
                companies=companies,
            )

            if direct_followup_answer is not None:
                PENDING_AGENT_FOLLOWUPS.pop(session_id, None)

                memory.add_turn(
                    session_id=session_id,
                    user_message=message,
                    assistant_message=direct_followup_answer,
                )

                return AgentChatResponse(                    
                    session_id=session_id,
                    route="FAST",
                    message=direct_followup_answer,
                    plan=None,
                    graph_data=None,
                    report_ready=False,
                    report_path=None,
                )


    direct_reasoning_answer = _agent_direct_reasoning_answer(
        tenant_id=tenant_id,
        message=message,
        context=context,
        company_id=company_id,
        companies=companies,
    )

    if direct_reasoning_answer is not None:
        memory.add_turn(
            session_id=session_id,
            user_message=message,
            assistant_message=direct_reasoning_answer,
        )

        return AgentChatResponse(
            session_id=session_id,
            route="REASONING",
            message=direct_reasoning_answer,
            plan=None,
            graph_data=None,
            report_ready=False,
            report_path=None,
        )

    # ─────────────────────────────
    # CUSTOM SQL QUESTION FALLBACK BEFORE SIMPLE REVENUE HANDLER
    # Some questions contain words like "sales revenue" but need grouping/ranking,
    # not a single date-based revenue metric.
    # ─────────────────────────────
    custom_sql_phrases = [
        "which company",
        "which companies",
        "company that have",
        "companies that have",
        "list of the company",
        "list of companies",
        "company list",
        "companies list",
        "by company",
        "each company",
        "per company",
        "highest",
        "highest sales",
        "highest revenue",
        "highest total sales",
        "highest sales revenue",
        "lowest",
        "top 10",
        "top ten",
        "top 5",
        "top five",
        "rank",
        "ranking",
        "group by",
        "which customers",
        "which customer",
        "which products",
        "which product",
        "bought in",
        "but not",
        "have stock but no sales",
        "sales but no stock",
    ]

    normalized_for_sql = normalize_business_text_for_intent(message)

    if any(phrase in normalized_for_sql for phrase in custom_sql_phrases):
        sql_result = run_sql_agent(
            user_question=message,
            chat_history=memory_summary or "",
            tenant_id=tenant_id,
        )

        if sql_result.get("success"):
            answer = sql_result.get("message") or "SQL agent completed the analysis."

            memory.add_turn(
                session_id=session_id,
                user_message=message,
                assistant_message=answer,
            )

            return AgentChatResponse(
                session_id=session_id,
                route="SQL_AGENT",
                message=answer,
                plan=None,
                graph_data=None,
                report_ready=False,
                report_path=None,
            )

    direct_revenue_answer = _agent_revenue_answer(
        tenant_id=tenant_id,
        message=message,
        context=context,
        company_id=company_id,
        companies=companies,
    )

    if direct_revenue_answer is not None:
        if direct_revenue_answer.startswith("Which date or period"):
            PENDING_AGENT_FOLLOWUPS[session_id] = {
                "intent": _infer_pending_followup_intent(message, context),
                "context": context,
                "company_id": company_id,
                "companies": companies,
            }
        else:
            PENDING_AGENT_FOLLOWUPS.pop(session_id, None)

        memory.add_turn(
            session_id=session_id,
            user_message=message,
            assistant_message=direct_revenue_answer,
        )

        return AgentChatResponse(
            session_id=session_id,
            route="FAST",
            message=direct_revenue_answer,
            plan=None,
            graph_data=None,
            report_ready=False,
            report_path=None,
        )

    

















    # Force simple inventory efficiency questions to FAST path.
    # These should not create a reasoning execution plan.
    inventory_efficiency_phrases = [
        "inventory efficiency",
        "inventory turnover",
        "turnover ratio",
        "days inventory",
        "days inventory on hand",
        "stock efficiency",
        "inventory performance",
        "inventory value",
        "stock value",
        "movement summary",
        "inventory movement",
        "stock movement",
        "how efficient is inventory",
        "how efficient is our inventory",
    ]

    if any(phrase in (message or "").lower() for phrase in inventory_efficiency_phrases):
        answer = fast_node.run(
            message=message,
            tenant_id=tenant_id,
            company_id=company_id,
            companies=companies,
            context=context,
            memory_summary=memory_summary,
        )

        memory.add_turn(
            session_id=session_id,
            user_message=message,
            assistant_message=answer,
        )

        return AgentChatResponse(
            session_id=session_id,
            route="FAST",
            message=answer,
            plan=None,
            graph_data=None,
            report_ready=False,
            report_path=None,
        )

    pending_plan = memory.get_plan(session_id)
    action = infer_plan_action(message, plan_action)

    # ─────────────────────────────
    # 0. HANDLE PENDING REASONING PLAN
    # ─────────────────────────────
    if pending_plan is not None:
        if action == "approve":
            answer = reasoning_node.execute_plan(
                message=message,
                plan=pending_plan,
                tenant_id=tenant_id,
                company_id=company_id,
                memory_summary=memory_summary,
            )

            memory.clear_plan(session_id)

            report_ready = False
            report_path = None

            if is_pdf_request(message):
                local_report_path = generate_pdf(answer)
                report_path = make_report_url(local_report_path)
                report_ready = True
                answer = answer + f"\n\nPDF report generated: {report_path}"

            memory.add_turn(
                session_id=session_id,
                user_message=message,
                assistant_message=answer,
            )

            return AgentChatResponse(
                session_id=session_id,
                route="REASONING",
                message=answer,
                plan=None,
                graph_data=None,
                report_ready=report_ready,
                report_path=report_path,
            )

        if action == "cancel":
            memory.clear_plan(session_id)

            response_message = "Canceled the pending financial analysis plan."

            memory.add_turn(
                session_id=session_id,
                user_message=message,
                assistant_message=response_message,
            )

            return AgentChatResponse(
                session_id=session_id,
                route="REASONING",
                message=response_message,
                plan=None,
                graph_data=None,
                report_ready=False,
                report_path=None,
            )

        if action == "edit":
            new_plan = reasoning_node.create_plan(
                message=message,
                tenant_id=tenant_id,
                company_id=company_id,
                memory_summary=memory_summary,
            )

            memory.set_plan(session_id, new_plan)

            response_message = (
                "I updated the financial execution plan. "
                "Please approve it if you want me to continue."
            )

            memory.add_turn(
                session_id=session_id,
                user_message=message,
                assistant_message=response_message,
            )

            return AgentChatResponse(
                session_id=session_id,
                route="REASONING",
                message=response_message,
                plan=new_plan,
                graph_data=None,
                report_ready=False,
                report_path=None,
            )

        response_message = (
            "There is a pending financial execution plan. "
            "Please reply with 'approve', 'cancel', or tell me what to edit."
        )

        return AgentChatResponse(
            session_id=session_id,
            route="REASONING",
            message=response_message,
            plan=pending_plan,
            graph_data=None,
            report_ready=False,
            report_path=None,
        )

    # ─────────────────────────────
    # 0. BUSINESS REPORT REQUEST
    # Generate report and return reportReady/reportPath to frontend
    # ─────────────────────────────
    text_lower = normalize_business_text_for_intent(message)

    report_keywords = [
        "generate report",
        "business report",
        "financial report",
        "pdf report",
        "create report",
        "download report",
        "report pdf",
        "create pdf",
        "generate pdf",
        "download pdf",
        "export pdf",
        "pdf for",
        "as pdf",
        "in pdf",
        "pdf version",
        "report for",
        "download",
        "export",
        "document",
    ]

    sales_domain_keywords = [
        "sales",
        "sell",
        "sold",
        "sales summary",
        "sales revenue",
    ]

    inventory_domain_keywords = [
        "inventory",
        "stock",
        "low stock",
        "expiring",
        "lots",
        "lot",
        "reorder",
        "expiry",
        "expiration",
        "inventory alerts",
        "inventory problems",
        "stock problems",
    ]

    customer_domain_keywords = [
        "customer",
        "customers",
        "client",
        "clients",
        "receivable",
        "receivables",
    ]

    product_domain_keywords = [
        "product",
        "products",
        "items",
        "top products",
    ]

    is_report_request = any(keyword in text_lower for keyword in report_keywords)

    # ─────────────────────────────
    # 0b. HANDLE REPORT / PDF REQUEST
    # Calls generate_report_tool, returns download link.
    # ─────────────────────────────
    if is_report_request:
        try:
            company_ids_for_report = parse_company_ids_for_agent(
                company_id=company_id, companies=companies
            )
            first_company = company_ids_for_report[0] if company_ids_for_report else company_id

            report_result = generate_report_tool(
                tenant_id=tenant_id,
                company_id=first_company,
                report_type="business_summary",
            )

            report_filename = report_result.get("report_filename", "")
            download_url = make_report_url(report_filename)

            summary = report_result.get("summary", {})
            total_revenue = summary.get("total_revenue", "N/A")
            health_status = summary.get("health_status", "N/A")
            health_score = summary.get("business_health_score", "N/A")
            liquidity = summary.get("liquidity_status", "N/A")
            receivables_risk = summary.get("receivables_risk", "N/A")
            inventory_eff = summary.get("inventory_efficiency", "N/A")
            low_stock_count = summary.get("low_stock_count", 0)

            if isinstance(total_revenue, (int, float)):
                total_revenue_fmt = f"{total_revenue:,.2f}"
            else:
                total_revenue_fmt = str(total_revenue)

            report_message = (
                f"## 📊 Business Report Generated\n\n"
                f"Your PDF report is ready for download.\n\n"
                f"### 📥 Download Link\n\n"
                f"**[⬇️ Download Business Report (PDF)]({download_url})**\n\n"
                f"---\n\n"
                f"### Report Highlights\n\n"
                f"| Metric | Value |\n"
                f"|---|---|\n"
                f"| Total Revenue | {total_revenue_fmt} |\n"
                f"| Business Health Score | {health_score} |\n"
                f"| Health Status | {health_status} |\n"
                f"| Liquidity Status | {liquidity} |\n"
                f"| Receivables Risk | {receivables_risk} |\n"
                f"| Inventory Efficiency | {inventory_eff} |\n"
                f"| Low Stock Items | {low_stock_count} |\n\n"
                f"> ✅ Report generated from real PostgreSQL data synced from Odoo.\n\n"
                f"📥 **Direct link:** {download_url}"
            )

            memory.add_turn(
                session_id=session_id,
                user_message=message,
                assistant_message=report_message,
            )

            return AgentChatResponse(
                session_id=session_id,
                route="FAST",
                message=report_message,
                plan=None,
                graph_data=None,
                report_ready=True,
                report_path=download_url,
            )

        except Exception as report_error:
            error_message = (
                f"I tried to generate a business report but encountered an error: {report_error}\n\n"
                "Please try again or contact your Doova OneView administrator."
            )

            return AgentChatResponse(
                session_id=session_id,
                route="FAST",
                message=error_message,
                plan=None,
                graph_data=None,
                report_ready=False,
                report_path=None,
            )

    # ─────────────────────────────
    # 1. GRAPH / CHART REQUEST
    # Return structured chart payload for frontend rendering.
    # ─────────────────────────────
    if is_graph_request(message):
        fast_result = run_fast_tool(
            message=message,
            tenant_id=tenant_id,
            company_id=company_id,
            companies=companies,
        )

        if fast_result and fast_result.get("response_type") == "chart":
            response_message = fast_result.get(
                "message",
                "Here is the chart based on available business data."
            )

            graph_payload = {
                "type": "chart",
                "response_type": "chart",
                "chart": fast_result.get("chart"),
                "data": fast_result.get("data", []),
            }

            memory.add_turn(
                session_id=session_id,
                user_message=message,
                assistant_message=response_message,
                assistant_type="chart",
                assistant_payload=graph_payload,
            )

            return AgentChatResponse(
                session_id=session_id,
                route="FAST",
                message=response_message,
                plan=None,
                graph_data=graph_payload,
                report_ready=False,
                report_path=None,
            )

        response_message = (
            "I detected a graph request, but I could not prepare chart data "
            "from the available business data."
        )

        memory.add_turn(
            session_id=session_id,
            user_message=message,
            assistant_message=response_message,
        )

        return AgentChatResponse(
            session_id=session_id,
            route="FAST",
            message=response_message,
            plan=None,
            graph_data=None,
            report_ready=False,
            report_path=None,
        )

    # ─────────────────────────────
    # 2. ROUTER
    # ─────────────────────────────
    route = router_node.classify(message)

    # ─────────────────────────────
    # 3. REJECT
    # ─────────────────────────────
    if route == "REJECT":
        # ─────────────────────────────
        # SQL AGENT FALLBACK
        # If no deterministic tool matched, try a safe read-only SQL agent.
        # This handles custom database questions.
        # ─────────────────────────────
        sql_result = run_sql_agent(
            user_question=message,
            chat_history=memory_summary or "",
            tenant_id=tenant_id,
        )

        if sql_result.get("success"):
            answer = sql_result.get("message") or "SQL agent completed the analysis."

            memory.add_turn(
                session_id=session_id,
                user_message=message,
                assistant_message=answer,
            )

            return AgentChatResponse(
                session_id=session_id,
                route="SQL_AGENT",
                message=answer,
                plan=None,
                graph_data=None,
                report_ready=False,
                report_path=None,
            )

        response_message = (
            sql_result.get("message")
            or "I can only answer questions related to this business's own financial or operational data."
        )

        memory.add_turn(
            session_id=session_id,
            user_message=message,
            assistant_message=response_message,
        )

        return AgentChatResponse(
            session_id=session_id,
            route="REJECT",
            message=response_message,
            plan=None,
            graph_data=None,
            report_ready=False,
            report_path=None,
        )

    # ─────────────────────────────
    # 4. FAST PATH
    # ─────────────────────────────
    if route == "FAST":
        answer = fast_node.run(
            message=message,
            tenant_id=tenant_id,
            company_id=company_id,
            companies=companies,
            context=context,
            memory_summary=memory_summary,
        )

        report_ready = False
        report_path = None

        memory.add_turn(
            session_id=session_id,
            user_message=message,
            assistant_message=answer,
        )

        return AgentChatResponse(
            session_id=session_id,
            route=route,
            message=answer,
            plan=None,
            graph_data=None,
            report_ready=report_ready,
            report_path=report_path,
        )

    # ─────────────────────────────
    # 5. REASONING PATH
    # ─────────────────────────────
    if route == "REASONING":
        plan = reasoning_node.create_plan(
            message=message,
            tenant_id=tenant_id,
            company_id=company_id,
            memory_summary=memory_summary,
        )

        memory.set_plan(session_id, plan)

        response_message = format_execution_plan_message(plan)

        memory.add_turn(
            session_id=session_id,
            user_message=message,
            assistant_message=response_message,
        )

        return AgentChatResponse(
            session_id=session_id,
            route="REASONING",
            message=response_message,
            plan=plan,
            graph_data=None,
            report_ready=False,
            report_path=None,
        )

    fallback_message = "I could not classify the request, so I handled it as a simple question."

    return AgentChatResponse(
        session_id=session_id,
        route="FAST",
        message=fallback_message,
        plan=None,
        graph_data=None,
        report_ready=False,
        report_path=None,
    )


# ─────────────────────────────
# Flexible frontend body parser
# Accepts:
# tenantId / tenant_id
# sessionId / session_id
# fileId / file_id
# ─────────────────────────────
async def parse_frontend_body(body: Dict[str, Any]) -> Dict[str, Any]:
    if not isinstance(body, dict):
        body = {}

    query = (
        body.get("query")
        or body.get("message")
        or body.get("prompt")
        or body.get("input")
        or body.get("text")
    )

    # Some chat frontends send:
    # {"messages": [{"role": "user", "content": "..."}]}
    if not query and isinstance(body.get("messages"), list) and body["messages"]:
        last_message = body["messages"][-1]
        if isinstance(last_message, dict):
            query = (
                last_message.get("content")
                or last_message.get("message")
                or last_message.get("text")
            )

    tenant_id = (
        body.get("tenant_id")
        or body.get("tenantId")
        or body.get("tenant")
        or "test-tenant"
    )

    session_id = (
        body.get("session_id")
        or body.get("sessionId")
        or body.get("conversation_id")
        or body.get("conversationId")
        or str(uuid4())
    )

    company_id = parse_optional_int(
        body.get("company_id") or body.get("companyId")
    )

    plan_action = body.get("plan_action") or body.get("planAction")

    file_id = (
        body.get("file_id")
        or body.get("fileId")
        or body.get("attachment_id")
        or body.get("attachmentId")
    )

    context = (
        body.get("context")
        or body.get("selectedContext")
        or body.get("module")
        or body.get("activeModule")
    )

    return {
        "query": query,
        "tenant_id": tenant_id,
        "session_id": session_id,
        "company_id": company_id,
        "plan_action": plan_action,
        "file_id": file_id,
        "context": context,
        "raw_body": body,
    }


async def run_frontend_chat(body: Dict[str, Any]):
    parsed = await parse_frontend_body(body)

    query = parsed["query"]

    if not query:
        error_message = "Missing query/message in request body."

        return frontend_response(
            message=error_message,
            session_id=parsed["session_id"],
            route="ERROR",
            graph_data=None,
            report_ready=False,
            report_path=None,
            plan=None,
        )

    # If frontend later sends context, backend can use it.
    context = parsed.get("context")
    if context and str(context).lower() not in ["all context", "all", "none", "null"]:
        query = f"[Selected context: {context}]\n{query}"

    # If frontend sends fileId, read the uploaded file and add its content to the query.
    file_id = parsed.get("file_id")
    if file_id:
        extracted_file_text = extract_uploaded_file_text(file_id)

        query = (
            f"{query}\n\n"
            "The user attached a file. Use the extracted file content below when answering.\n\n"
            "----- BEGIN ATTACHED FILE CONTENT -----\n"
            f"{extracted_file_text}\n"
            "----- END ATTACHED FILE CONTENT -----"
        )
    print("DEBUG FRONTEND CHAT parsed =", parsed)

    # Frontend sometimes sends tenant_id as None.
    # Our synced PostgreSQL data is under demo-tenant, so use it as fallback.
    if parsed.get("tenant_id") in [None, "", "test-tenant"]:
        parsed["tenant_id"] = "demo-tenant"

    result = await run_agent_chat(
        tenant_id=parsed["tenant_id"],
        session_id=parsed["session_id"],
        message=query,
        company_id=parsed.get("company_id"),
        companies=parsed.get("companies") or parsed.get("company_ids") or parsed.get("companyIds"),
        context=parsed.get("context"),
        plan_action=parsed["plan_action"],
    )

    return frontend_response(
        message=result.message,
        session_id=result.session_id,
        route=result.route,
        graph_data=result.graph_data,
        report_ready=result.report_ready,
        report_path=result.report_path,
        plan=result.plan,
    )


# ─────────────────────────────
# Internal strict endpoint
# POST /api/v1/agent/{tenant_id}/chat
# ─────────────────────────────
@router.post("/agent/{tenant_id}/chat", response_model=AgentChatResponse)
async def chat(
    tenant_id: str,
    body: AgentChatRequest,
):
    return await run_agent_chat(
        tenant_id=tenant_id,
        session_id=body.session_id,
        message=body.message,
        company_id=body.company_id,
        companies=body.companies,
        context=body.context,
        plan_action=body.plan_action,
    )

# ─────────────────────────────
# Frontend-compatible chat aliases
# These support:
# POST /api/v1/financial-advisor/chat
# POST /api/v1/chat
# POST /api/v1/agent/chat
# ─────────────────────────────
@router.post("/financial-advisor/chat")
async def financial_advisor_chat(body: Dict[str, Any] = Body(...)):
    return await run_frontend_chat(body)


@router.post("/chat")
async def frontend_chat(body: Dict[str, Any] = Body(...)):
    return await run_frontend_chat(body)


@router.post("/agent/chat")
async def agent_chat_alias(body: Dict[str, Any] = Body(...)):
    return await run_frontend_chat(body)


# ─────────────────────────────
# File upload compatibility
# Frontend currently calls:
# POST /api/v1/files/upload
# ─────────────────────────────
@router.post("/files/upload")
async def upload_file_alias(file: UploadFile = File(...)):
    file_id = str(uuid4())
    safe_original_name = Path(file.filename or "uploaded_file").name
    stored_filename = f"{file_id}_{safe_original_name}"
    file_path = UPLOAD_DIR / stored_filename

    with file_path.open("wb") as buffer:
        shutil.copyfileobj(file.file, buffer)

    uploaded_files[file_id] = {
        "file_id": file_id,
        "fileId": file_id,
        "filename": safe_original_name,
        "stored_filename": stored_filename,
        "path": str(file_path),
        "content_type": file.content_type,
    }

    return {
        "success": True,
        "file_id": file_id,
        "fileId": file_id,
        "filename": safe_original_name,
        "path": str(file_path),
        "message": "File uploaded successfully.",
    }



# GET /api/v1/files/{tenant_id}
# Frontend uses this for Storage / Notifications list.
@router.get("/files/{tenant_id}")
def list_files_for_tenant(tenant_id: str):
    return []



# Official-style file upload alias:
# POST /api/v1/files/{tenant_id}
@router.post("/files/{tenant_id}")
async def upload_file_for_tenant(
    tenant_id: str,
    file: UploadFile = File(...),
    description: str | None = None,
):
    result = await upload_file_alias(file)

    result["tenant_id"] = tenant_id
    result["tenantId"] = tenant_id
    result["description"] = description

    return result


# ─────────────────────────────
# Report download endpoint
# Frontend expects reportPath to be a downloadable URL.
# Example:
# /api/v1/reports/business_report_test-tenant_20260508_013137.pdf
# ─────────────────────────────
@router.get("/reports/{filename}")
async def download_report(filename: str):
    safe_filename = Path(filename).name
    report_path = REPORTS_DIR / safe_filename

    if not report_path.exists():
        raise HTTPException(status_code=404, detail="Report not found")

    if safe_filename.lower().endswith(".svg"):
        media_type = "image/svg+xml"
    elif safe_filename.lower().endswith(".pdf"):
        media_type = "application/pdf"
    else:
        media_type = "application/octet-stream"

    return FileResponse(
        path=str(report_path),
        media_type=media_type,
        filename=safe_filename,
    )


# ─────────────────────────────
# Sessions
# Supports:
# GET /api/v1/financial-advisor/sessions
# GET /api/v1/financial-advisor/sessions/{session_id}
# DELETE /api/v1/financial-advisor/sessions/{session_id}
# ─────────────────────────────
@router.get("/financial-advisor/sessions")
async def list_financial_advisor_sessions():
    sessions = memory.list_sessions()

    return {
        "sessions": sessions,
        "count": len(sessions),
        "success": True,
    }

@router.get("/financial-advisor/sessions/{session_id}")
async def get_financial_advisor_session(session_id: str):
    session = memory.get_session(session_id)

    if session is None:
        return {
            "session_id": session_id,
            "sessionId": session_id,
            "title": "New Chat",
            "summary": "",
            "raw_turns": [],
            "history": [],
            "plan_state": None,
            "turn_count": 0,
            "last_message": "",
            "created_at": None,
            "updated_at": None,
        }

    return session

@router.delete("/financial-advisor/sessions/{session_id}")
async def delete_financial_advisor_session(session_id: str):
    deleted = memory.delete_session(session_id)

    return {
        "session_id": session_id,
        "sessionId": session_id,
        "deleted": deleted,
        "message": "Session deleted" if deleted else "Session not found",
    }


# ─────────────────────────────
# Temporary tenants endpoint for frontend compatibility
# Supports:
# GET /api/v1/tenants/?limit=10&offset=0
# ─────────────────────────────
@router.get("/tenants/")
async def tenants_alias(limit: int = 10, offset: int = 0):
    tenants = [
        {
            "id": "demo-tenant",
            "tenant_id": "demo-tenant",
            "tenantId": "demo-tenant",
            "name": "Demo Tenant",
            "display_name": "Demo Tenant",
            "is_active": True,
        }
    ]

    return tenants[offset: offset + limit]