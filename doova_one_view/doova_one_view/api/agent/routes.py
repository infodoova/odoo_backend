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
    is_pdf_request,
    generate_pdf,
    generate_report_tool,
    normalize_business_text_for_intent,
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
    if value is None or value == "" or value == "null": return None
    try: return int(value)
    except: return None

def parse_company_ids_for_agent(company_id: int | None = None, companies: list[int] | None = None) -> list[int]:
    ids: list[int] = []
    if companies:
        for v in companies:
            try: ids.append(int(v))
            except: pass
    if company_id is not None:
        try: ids.append(int(company_id))
        except: pass
    if not ids: ids = [2, 3, 4, 5, 11]
    return list(dict.fromkeys(ids))

def _month_range_from_message(message: str) -> tuple[str | None, str | None, str | None]:
    text = (message or "").lower().strip()
    month_map = {
        "january": 1, "jan": 1, "february": 2, "feb": 2, "march": 3, "mar": 3, "april": 4, "apr": 4, "may": 5,
        "june": 6, "jun": 6, "july": 7, "jul": 7, "august": 8, "aug": 8, "september": 9, "sep": 9, "sept": 9,
        "october": 10, "oct": 10, "november": 11, "nov": 11, "december": 12, "dec": 12,
    }
    month_pattern = r"january|jan|february|feb|march|mar|april|apr|may|june|jun|july|jul|august|aug|september|sep|sept|october|oct|november|nov|december|dec"
    
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
        start = last_prev_month.replace(day=1); end = last_prev_month
        return start.isoformat(), end.isoformat(), start.strftime("%B %Y")
    
    match = re.search(rf"\b({month_pattern})\s+(\d{{4}})\b", text)
    if match:
        month_name = match.group(1); year = int(match.group(2)); month = month_map[month_name]
        start = date(year, month, 1)
        if month == 12: end = date(year, 12, 31)
        else: end = date(year, month + 1, 1) - timedelta(days=1)
        return start.isoformat(), end.isoformat(), start.strftime("%B %Y")
    
    match = re.search(rf"\b(\d{{1,2}})\s+({month_pattern})\s+(\d{{4}})\b", text)
    if match:
        day = int(match.group(1)); month_name = match.group(2); year = int(match.group(3)); month = month_map[month_name]
        try:
            d = date(year, month, day)
            return d.isoformat(), d.isoformat(), d.strftime("%B %d, %Y")
        except: return None, None, None

    match = re.search(r"\b(\d{1,2})[-/](\d{1,2})[-/](\d{4})\b", text)
    if match:
        day = int(match.group(1)); month = int(match.group(2)); year = int(match.group(3))
        try:
            d = date(year, month, day)
            return d.isoformat(), d.isoformat(), d.strftime("%B %d, %Y")
        except: return None, None, None
    return None, None, None

def _is_reasoning_question(message: str | None) -> bool:
    text = normalize_business_text_for_intent(message or "")
    reasoning_phrases = ["why", "what should", "recommend", "analyze", "compare", "explain", "reason", "cause", "drop", "decrease", "increase", "improve", "prioritize"]
    return any(phrase in text for phrase in reasoning_phrases)

def _agent_revenue_answer(tenant_id: str, message: str, context: str | None, company_id: int | None = None, companies: list[int] | None = None) -> str | None:
    text = normalize_business_text_for_intent(message)
    context_text = normalize_business_text_for_intent(context or "")
    if _is_reasoning_question(message): return None

    blocked_tool_phrases = ["top products", "best-selling", "low stock", "cash flow", "receivables", "forecast", "health", "profit", "report", "graph", "trend", "why", "explain", "compare", "analyze", "recommend"]
    if any(phrase in text for phrase in blocked_tool_phrases): return None

    is_sales_revenue = any(kw in text for kw in ["sales revenue", "total sales", "sales summary", "how much did we sell"]) or "sales" in context_text
    is_revenue_question = any(kw in text for kw in ["revenue", "total sales", "income"]) or is_sales_revenue

    if not is_revenue_question: return None
    start, end, label = _month_range_from_message(message)
    if not start or not end: return "Which date or period should I use for the revenue calculation?"

    company_ids = parse_company_ids_for_agent(company_id=company_id, companies=companies)
    params = {"tenant_id": tenant_id, "start_date": start, "end_date": end}
    company_placeholders = []
    for index, cid in enumerate(company_ids):
        key = f"company_{index}"; company_placeholders.append(f":{key}"); params[key] = cid
    company_sql = ", ".join(company_placeholders)

    use_sales = any(kw in text for kw in ["sales", "total sales"]) or "sales" in context_text
    if use_sales:
        rows = run_query(f"SELECT COALESCE(SUM(amount_total), 0) AS revenue, COUNT(*) AS count FROM fact_sales_orders WHERE tenant_id = :tenant_id AND company_id IN ({company_sql}) AND state IN ('sale', 'done') AND date_order >= :start_date AND date_order <= :end_date", params)
        rev = float(rows[0]["revenue"] or 0); count = int(rows[0]["count"] or 0)
        return f"## Sales Summary — {label}\n\nFor tenant `{tenant_id}`, total sales were **{rev:,.2f}** over {count} orders."

    rows = run_query(f"SELECT COALESCE(SUM(amount_total), 0) AS revenue, COUNT(*) AS count FROM fact_account_moves WHERE tenant_id = :tenant_id AND company_id IN ({company_sql}) AND invoice_date >= :start_date AND invoice_date <= :end_date AND move_type = 'out_invoice' AND state = 'posted'", params)
    rev = float(rows[0]["revenue"] or 0); count = int(rows[0]["count"] or 0)
    return f"## Accounting Revenue — {label}\n\nFor tenant `{tenant_id}`, total accounting revenue was **{rev:,.2f}** from {count} invoices."

def format_execution_plan_message(plan: dict) -> str:
    if not plan: return "I prepared a financial execution plan. Please approve it before I continue."
    lines = ["## Financial Execution Plan", "", "I prepared a financial execution plan. Please approve it before I continue.", ""]
    if plan.get("question_summary"): lines.extend(["### Question Summary", plan["question_summary"], ""])
    if plan.get("data_sources_used"): lines.append("### Tools to Use"); lines.extend([f"- `{s}`" for s in plan["data_sources_used"]]); lines.append("")
    if plan.get("proposed_analysis_steps"):
        lines.append("### Proposed Steps")
        for s in plan["proposed_analysis_steps"]: lines.append(f"**Step {s.get('step')}:** {s.get('action')}"); lines.append(f"- Rationale: {s.get('rationale')}")
    lines.append("\nReply with **approve** to continue, **edit** to change, or **cancel** to stop.")
    return "\n".join(lines)

def make_report_url(path: str | None) -> str | None:
    if not path: return None
    public_url = os.getenv("PUBLIC_BASE_URL", "").rstrip("/")
    return f"{public_url}/api/v1/reports/{Path(path).name}" if public_url else f"/api/v1/reports/{Path(path).name}"

def normalize_graph_for_frontend(graph_data):
    if not graph_data: return None
    if isinstance(graph_data, list): return [{"name": str(item.get("name", item.get("x"))), "value": float(item.get("value", item.get("y", 0)))} for item in graph_data if isinstance(item, dict)]
    if isinstance(graph_data, dict):
        if "x" in graph_data and "y" in graph_data: return [{"name": str(x), "value": float(y)} for x, y in zip(graph_data["x"], graph_data["y"])]
        if "data" in graph_data: return normalize_graph_for_frontend(graph_data["data"])
    return None

def extract_uploaded_file_text(file_id: str) -> str:
    info = uploaded_files.get(file_id)
    if not info: return "File not found."
    path = Path(info["path"])
    if not path.exists(): return "File path does not exist."
    try:
        if path.suffix.lower() in [".txt", ".csv", ".md", ".json"]: return path.read_text(encoding="utf-8", errors="ignore")[:8000]
        if path.suffix.lower() == ".pdf":
            from pypdf import PdfReader
            reader = PdfReader(str(path))
            return "\n".join([p.extract_text() or "" for p in reader.pages[:5]])[:8000]
    except Exception as e: return f"Extraction failed: {e}"
    return "Unsupported file type."

def frontend_response(*, message: str, session_id: str, route: str = "FAST", graph_data=None, report_ready: bool = False, report_path: str | None = None, plan=None):
    norm_graph = normalize_graph_for_frontend(graph_data)
    return {
        "success": True, "message": message, "session_id": session_id, "route": route, "plan": plan,
        "graphData": norm_graph, "chartData": norm_graph, "report_ready": report_ready, "report_path": report_path,
        "payload": {"graphData": norm_graph, "report_ready": report_ready}
    }

def infer_plan_action(message: str, explicit: str | None) -> str | None:
    if explicit: return explicit.lower().strip()
    text = message.lower().strip()
    if text in ["yes", "proceed", "go ahead", "approve"]: return "approve"
    if text in ["cancel", "stop"]: return "cancel"
    if "edit" in text or "change" in text: return "edit"
    return None

PENDING_AGENT_FOLLOWUPS: dict[str, dict[str, Any]] = {}

async def run_agent_chat(tenant_id: str, session_id: str, message: str, company_id: int | None = None, companies: list[int] | None = None, context: str | None = None, plan_action: str | None = None) -> AgentChatResponse:
    memory_summary = memory.get_summary(session_id)
    
    # Check for simple direct revenue lookup
    direct_rev = _agent_revenue_answer(tenant_id, message, context, company_id, companies)
    if direct_rev:
        memory.add_turn(session_id, message, direct_rev)
        return AgentChatResponse(session_id=session_id, route="FAST", message=direct_rev)

    # Check for pending plan actions
    pending_plan = memory.get_plan(session_id)
    action = infer_plan_action(message, plan_action)
    if pending_plan:
        if action == "approve":
            answer = reasoning_node.execute_plan(message, pending_plan, tenant_id, company_id, memory_summary)
            memory.clear_plan(session_id)
            memory.add_turn(session_id, message, answer)
            return AgentChatResponse(session_id=session_id, route="REASONING", message=answer)
        if action == "cancel":
            memory.clear_plan(session_id); memory.add_turn(session_id, message, "Canceled.")
            return AgentChatResponse(session_id=session_id, route="REASONING", message="Canceled.")

    # Core routing
    route = router_node.classify(message)
    if route == "REJECT":
        sql_res = run_sql_agent(message, memory_summary, tenant_id)
        ans = sql_res.get("message", "I can only help with business data.")
        memory.add_turn(session_id, message, ans)
        return AgentChatResponse(session_id=session_id, route="SQL_AGENT", message=ans)
    
    if route == "FAST":
        answer = fast_node.run(message, tenant_id, company_id, companies, context, memory_summary)
        memory.add_turn(session_id, message, answer)
        return AgentChatResponse(session_id=session_id, route="FAST", message=answer)
        
    if route == "REASONING":
        plan = reasoning_node.create_plan(message, tenant_id, company_id, memory_summary)
        memory.set_plan(session_id, plan)
        msg = format_execution_plan_message(plan)
        memory.add_turn(session_id, message, msg)
        return AgentChatResponse(session_id=session_id, route="REASONING", message=msg, plan=plan)

    return AgentChatResponse(session_id=session_id, route="FAST", message="I'm here to help.")

async def run_frontend_chat(body: Dict[str, Any]):
    q = body.get("query") or body.get("message")
    t = body.get("tenant_id") or "demo-tenant"
    s = body.get("session_id") or str(uuid4())
    res = await run_agent_chat(t, s, q, body.get("company_id"), body.get("companies"), body.get("context"), body.get("plan_action"))
    return frontend_response(message=res.message, session_id=res.session_id, route=res.route, plan=res.plan)

@router.post("/agent/{tenant_id}/chat", response_model=AgentChatResponse)
async def chat_endpoint(tenant_id: str, body: AgentChatRequest):
    return await run_agent_chat(tenant_id, body.session_id, body.message, body.company_id, body.companies, body.context, body.plan_action)

@router.post("/financial-advisor/chat")
async def fa_chat_endpoint(body: Dict[str, Any] = Body(...)):
    return await run_frontend_chat(body)

@router.get("/reports/{filename}")
async def download_report(filename: str):
    path = REPORTS_DIR / filename
    if not path.exists(): raise HTTPException(404, "Report not found")
    return FileResponse(str(path))

@router.get("/financial-advisor/sessions")
async def list_sessions():
    return {"sessions": memory.list_sessions(), "success": True}

@router.get("/financial-advisor/sessions/{session_id}")
async def get_session(session_id: str):
    return memory.get_session(session_id) or {"session_id": session_id, "messages": []}

@router.delete("/financial-advisor/sessions/{session_id}")
async def delete_session(session_id: str):
    return {"deleted": memory.delete_session(session_id)}
