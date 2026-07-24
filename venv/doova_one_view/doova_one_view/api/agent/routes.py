# api/agent/routes.py

import re as _re
import json
import time
import asyncio
from asgiref.sync import sync_to_async
from fastapi import APIRouter, HTTPException, Depends, Request
from pydantic import BaseModel, Field, ConfigDict
from typing import List, Optional, Union

from .router import RouterNode
from .fast_path import FastPathNode
from .reasoning import ReasoningNode
from .utils import make_report_url
from .logger import log_session_event, log_error, logger

from .session_manager import SessionManager
from .query_context import resolve_tenant_id, normalize_tenant_ids, normalize_company_ids
from doova_one_view.api.auth.permissions import require_permissions

# Initialize Nodes
router_node = RouterNode()
fast_path_node = FastPathNode()
reasoning_node = ReasoningNode()
router = APIRouter(prefix="/financial-advisor", tags=["Agent"])
session_manager = SessionManager()

_use_agent = Depends(require_permissions("use_agent"))

class ChatRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    message: str = Field(alias="text", default="")
    query_alt: Optional[str] = Field(alias="query", default=None)
    content: Optional[str] = Field(alias="userInput", default=None)
    prompt: Optional[str] = Field(default=None)

    tenant_id: Optional[Union[str, List[str]]] = Field(alias="tenantId", default=None)
    tenant_ids: Optional[List[str]] = Field(alias="tenantIds", default=None)
    tenants: Optional[List[str]] = Field(default=None)

    session_id: str = Field(alias="sessionId", default="default_session")

    company_id: Optional[Union[int, str, List[Union[int, str]]]] = Field(alias="companyId", default=None)
    company_ids: Optional[List[Union[int, str]]] = Field(alias="companyIds", default=None)
    companies: Optional[List[Union[int, str]]] = Field(default=None)

    chat_history: Optional[List[dict]] = Field(default=[])

    # Fallback for 'message' vs 'text'
    @property
    def query(self) -> str:
        return self.message

def extract_context_ids(req_data: Union[ChatRequest, dict]):
    """
    Extracts and normalizes tenant and company parameters from a ChatRequest or dict.
    Returns: (primary_tenant_id, resolved_tenant_ids, primary_company_id, resolved_company_ids)
    """
    raw_tenants = []
    raw_companies = []

    if isinstance(req_data, ChatRequest):
        t_id = req_data.tenant_id
        t_ids = req_data.tenant_ids
        t_list = req_data.tenants

        c_id = req_data.company_id
        c_ids = req_data.company_ids
        c_list = req_data.companies
    else:
        t_id = req_data.get("tenant_id") or req_data.get("tenantId")
        t_ids = req_data.get("tenant_ids") or req_data.get("tenantIds")
        t_list = req_data.get("tenants")

        c_id = req_data.get("company_id") or req_data.get("companyId")
        c_ids = req_data.get("company_ids") or req_data.get("companyIds")
        c_list = req_data.get("companies")

    for val in (t_id, t_ids, t_list):
        if val is not None:
            if isinstance(val, list):
                raw_tenants.extend(val)
            else:
                raw_tenants.append(val)

    for val in (c_id, c_ids, c_list):
        if val is not None:
            if isinstance(val, list):
                raw_companies.extend(val)
            else:
                raw_companies.append(val)

    resolved_tenant_ids = normalize_tenant_ids(tenant_ids=raw_tenants)
    resolved_company_ids = normalize_company_ids(companies=raw_companies)

    primary_tenant_id = resolved_tenant_ids[0] if resolved_tenant_ids else None
    primary_company_id = resolved_company_ids[0] if len(resolved_company_ids) == 1 else None

    return primary_tenant_id, resolved_tenant_ids, primary_company_id, resolved_company_ids

def make_chat_response(
    answer: str,
    mode: str,
    session_id: str,
    session_title: str,
    user_message: str,
    plan: Optional[dict] = None,
    status: Optional[str] = None
) -> dict:
    from .utils import parse_json_chart_from_text, strip_json_chart_from_text

    chart_payload = parse_json_chart_from_text(answer)

    if chart_payload:
        final_answer = strip_json_chart_from_text(answer)
        if not final_answer:
            final_answer = chart_payload.get("message", "")
        res_type = "graph"
    else:
        final_answer = answer
        res_type = "text"

    res = {
        "answer": final_answer,
        "mode": mode,
        "session_id": session_id,
        "session_title": session_title,
        "type": res_type,
    }

    if chart_payload:
        res["payload"] = chart_payload

    if plan is not None:
        res["plan"] = plan
    if status is not None:
        res["status"] = status
    return res


async def background_retry_executor(
    session_id: str,
    tenant_id: str | None,
    company_id: int | None,
    user_message: str,
    chat_history: list,
    db_summary: str,
    mode: str = "EXECUTE",
    plan: dict = None,
    tenant_ids: list[str] | None = None,
    company_ids: list[int] | None = None,
):
    max_retries = 5
    delay = 1.0  # initial delay in seconds
    
    for attempt in range(1, max_retries + 1):
        try:
            logger.info(f"BACKGROUND RETRY | Session: {session_id} | Attempt {attempt}/{max_retries}")
            
            if mode == "EXECUTE":
                def save_summary_to_db(summary_text: str):
                    session_manager.save_summary(session_id, summary_text)
                    logger.info(f"BACKGROUND SUMMARY SAVED | Session: {session_id}")
                
                answer = await asyncio.to_thread(fast_path_node.run, 
                    message=user_message,
                    tenant_id=tenant_id,
                    tenant_ids=tenant_ids,
                    company_id=company_id,
                    company_ids=company_ids,
                    chat_history=chat_history,
                    memory_summary=db_summary,
                    on_summary=save_summary_to_db
                )
            elif mode == "PLAN":
                plan_result = await asyncio.to_thread(reasoning_node.create_plan, 
                    message=user_message,
                    tenant_id=tenant_id,
                    tenant_ids=tenant_ids,
                    company_id=company_id,
                    company_ids=company_ids
                )
                
                plan_summary = f"### Strategic Architecture Plan (Completed in Background)\n\n"
                plan_summary += f"**Objective:** {plan_result.get('objective', 'Strategic Audit')}\n\n"
                phases = plan_result.get('phases', [])
                if phases:
                    plan_summary += "**Phases:**\n"
                    for idx, p in enumerate(phases, 1):
                        title = p if isinstance(p, str) else p.get('title', 'Phase')
                        desc = "" if isinstance(p, str) else f": {p.get('description', '')}"
                        plan_summary += f"{idx}. **{title}**{desc}\n"
                    plan_summary += "\n"
                plan_summary += f"**Expected Outcome:** {plan_result.get('expected_outcome', 'Complete Analysis')}\n\n"
                plan_summary += "---\n*Plan execution is ready. Shall I proceed with this plan?*"
                answer = plan_summary
                
                def _update_session_plan():
                    s = session_manager.get_or_create_session(session_id, tenant_id or "default")
                    s.plan_state = plan_result
                    s.save()
                await sync_to_async(_update_session_plan)()
            elif mode == "EXECUTE_PLAN":
                answer = await asyncio.to_thread(reasoning_node.execute_plan, 
                    message=user_message,
                    plan=plan,
                    tenant_id=tenant_id,
                    tenant_ids=tenant_ids,
                    company_id=company_id,
                    company_ids=company_ids
                )
            
            await sync_to_async(session_manager.save_message)(session_id, "assistant", answer)
            logger.info(f"BACKGROUND RETRY SUCCESS | Session: {session_id} on attempt {attempt}")
            return
            
        except Exception as e:
            error_msg = str(e).lower()
            is_temporary = any(k in error_msg for k in ["usage limits", "quota", "429", "overloaded", "529", "service unavailable", "temp"])
            if is_temporary and attempt < max_retries:
                logger.warning(f"BACKGROUND RETRY FAILED (temp error) | Session: {session_id} | Waiting {delay}s...")
                await asyncio.sleep(delay)
                delay *= 2.0  # exponential backoff
            else:
                logger.error(f"BACKGROUND RETRY FAILED PERMANENTLY | Session: {session_id} | Error: {e}")
                err_text = "I attempted to process your request in the background but ran into persistent issues with the AI provider. Please try sending your message again shortly."
                await sync_to_async(session_manager.save_message)(session_id, "assistant", err_text)
                return

@router.post("/chat", dependencies=[_use_agent])
async def chat_endpoint(request: Request):
    # Get raw body for debugging
    body = await request.json()
    logger.info(f"RAW REQUEST BODY: {json.dumps(body)}")
    
    # Parse into ChatRequest manually to keep flexibility
    try:
        req_data = ChatRequest(**body)
    except Exception as e:
        logger.error(f"Failed to parse ChatRequest: {e}")
        raw_msg = (body.get("query") or body.get("message") or
                   body.get("text") or body.get("userInput") or
                   body.get("content") or body.get("prompt") or "")
        req_data = ChatRequest(message=raw_msg)

    request_start = time.time()
    
    # Extract message from multiple potential sources
    user_message = req_data.query_alt or req_data.message or req_data.content or req_data.prompt or ""
    
    # Extract & normalize all tenant and company ids
    from asgiref.sync import sync_to_async
    primary_tenant_id, resolved_tenant_ids, primary_company_id, resolved_company_ids = await sync_to_async(extract_context_ids)(req_data)

    # 1. Immediate Session Handling
    import uuid
    
    current_session_id = req_data.session_id
    if not current_session_id or current_session_id == "new" or current_session_id == "default_session":
        current_session_id = str(uuid.uuid4())
        logger.info(f"Generated new session ID: {current_session_id}")

    session_tenant_id = primary_tenant_id or "default"
    # Load session and history BEFORE saving new message
    session = await sync_to_async(session_manager.get_or_create_session)(current_session_id, session_tenant_id, user_message)
    
    # Retrieve persisted summary (from last summarization cycle)
    db_summary = session.summary or ""
    
    # Only load the most recent N messages to keep context lean
    RECENT_MSG_LIMIT = 10
    def _get_recent_messages():
        return list(
            session_manager.get_messages(current_session_id)
            .order_by('-created_at')[:RECENT_MSG_LIMIT]
        )
    all_db_messages = await sync_to_async(_get_recent_messages)()
    all_db_messages.reverse()  # restore chronological order
    
    chat_history_from_db = [
        {"role": m.role, "content": m.content}
        for m in all_db_messages
        if m.role in ("user", "assistant")
    ]
    
    # Now save the new user message to DB
    await sync_to_async(session_manager.save_message)(current_session_id, "user", user_message or "[Empty Message]")
    log_session_event("MESSAGE_SAVED", current_session_id, "user message")

    SOCIAL_PHRASES = {
        "hi", "hello", "hey", "how are you", "how are you?",
        "good morning", "good afternoon", "good evening",
        "thanks", "thank you", "bye", "goodbye", "ok", "okay",
    }
    # Handle empty messages / simple social phrases before hitting the router
    if not user_message or not user_message.strip() or user_message.lower().strip("!.?") in SOCIAL_PHRASES:
        answer = "Hello! I am Nexus. How can I assist you with your business data today?"
        await sync_to_async(session_manager.save_message)(current_session_id, "assistant", answer)
        return make_chat_response(
            answer,
            "EXECUTE",
            current_session_id,
            session.title,
            user_message
        )

    logger.info(
        f"INCOMING REQUEST\n"
        f"   Session: {current_session_id}\n"
        f"   Tenants: {resolved_tenant_ids or 'ALL'}\n"
        f"   Companies: {resolved_company_ids or 'ALL'}\n"
        f"   Message: \"{user_message[:100]}\"\n"
        f"   History Context: {len(chat_history_from_db)} messages"
    )

    # 2. Routing
    decision = await asyncio.to_thread(router_node.classify, user_message)
    
    # 2.1 Handle Plan Approval (CONFIRM path)
    if decision == "CONFIRM" and session.plan_state:
        try:
            logger.info(f"PLAN APPROVED: Executing strategic architecture for session {current_session_id}")
            answer = await asyncio.to_thread(
                reasoning_node.execute_plan,
                message=user_message,
                plan=session.plan_state,
                tenant_id=primary_tenant_id,
                tenant_ids=resolved_tenant_ids,
                company_id=primary_company_id,
                company_ids=resolved_company_ids
            )
            
            # Reset plan state after successful execution
            session.plan_state = None
            await sync_to_async(session.save)()
            
            await sync_to_async(session_manager.save_message)(current_session_id, "assistant", answer)
            duration = (time.time() - request_start) * 1000
            logger.info(f"PLAN EXECUTION COMPLETE in {duration:.0f}ms")
            return make_chat_response(
                answer,
                "EXECUTE_PLAN",
                current_session_id,
                session.title,
                user_message
            )
        except Exception as e:
            log_error("chat_endpoint.CONFIRM_EXECUTE", e)
            error_msg = str(e).lower()
            if any(k in error_msg for k in ["usage limits", "quota", "429", "overloaded", "529", "service unavailable", "temp"]):
                asyncio.create_task(
                    background_retry_executor(
                        session_id=current_session_id,
                        tenant_id=primary_tenant_id,
                        tenant_ids=resolved_tenant_ids,
                        company_id=primary_company_id,
                        company_ids=resolved_company_ids,
                        user_message=user_message,
                        chat_history=chat_history_from_db,
                        db_summary=db_summary,
                        mode="EXECUTE_PLAN",
                        plan=session.plan_state
                    )
                )
                session.plan_state = None
                await sync_to_async(session.save)()
                
                answer = "⏳ The AI provider is temporarily overloaded, but I am executing the approved plan in the background. Please wait a moment—your dashboard/chat will automatically update as soon as the results are ready."
                return make_chat_response(
                    answer,
                    "BACKGROUND_PROCESSING",
                    current_session_id,
                    session.title,
                    user_message
                )
            raise HTTPException(status_code=500, detail=str(e))

    if decision == "REJECT":
        answer = "I'm sorry, I can only assist with business and financial questions related to your Odoo data."
        await sync_to_async(session_manager.save_message)(current_session_id, "assistant", answer)
        duration = (time.time() - request_start) * 1000
        logger.info(f"REQUEST REJECTED in {duration:.0f}ms")
        return {"answer": answer}
    
    # 3. Execution Path
    if decision == "EXECUTE":
        try:
            from datetime import date
            today_str = date.today().strftime("%Y-%m-%d")
            
            # Persist summary to DB when agent generates one
            def save_summary_to_db(summary_text: str):
                session_manager.save_summary(current_session_id, summary_text)
                logger.info(f"SUMMARY SAVED | Session: {current_session_id} | Length: {len(summary_text)} chars")
            
            def run_fast_path():
                return fast_path_node.run(
                    message=user_message,
                    tenant_id=primary_tenant_id,
                    tenant_ids=resolved_tenant_ids,
                    company_id=primary_company_id,
                    company_ids=resolved_company_ids,
                    chat_history=chat_history_from_db,
                    memory_summary=db_summary,
                    on_summary=save_summary_to_db
                )
            
            answer = await asyncio.to_thread(run_fast_path)
            await sync_to_async(session_manager.save_message)(current_session_id, "assistant", answer)
            duration = (time.time() - request_start) * 1000
            logger.info(f"EXECUTE COMPLETE in {duration:.0f}ms | Response: \"{answer[:80]}...\"")
            return make_chat_response(
                answer,
                "EXECUTE",
                current_session_id,
                session.title,
                user_message
            )
        except Exception as e:
            log_error("chat_endpoint.EXECUTE", e)
            
            # Friendly message for API quota/limit/overloaded issues
            error_msg = str(e).lower()
            if any(k in error_msg for k in ["usage limits", "quota", "429", "overloaded", "529", "service unavailable", "temp"]):
                asyncio.create_task(
                    background_retry_executor(
                        session_id=current_session_id,
                        tenant_id=primary_tenant_id,
                        tenant_ids=resolved_tenant_ids,
                        company_id=primary_company_id,
                        company_ids=resolved_company_ids,
                        user_message=user_message,
                        chat_history=chat_history_from_db,
                        db_summary=db_summary,
                        mode="EXECUTE"
                    )
                )
                answer = "⏳ The AI provider is temporarily overloaded, but I have queued your request and am executing it in the background. Please wait a moment—your dashboard/chat will automatically update as soon as the results are ready."
                return make_chat_response(
                    answer,
                    "BACKGROUND_PROCESSING",
                    current_session_id,
                    session.title,
                    user_message
                )
                
            raise HTTPException(status_code=500, detail=str(e))
    
    # 4. Planning Path (High-Stakes Architecture)
    try:
        plan = await asyncio.to_thread(
            reasoning_node.create_plan,
            message=user_message,
            tenant_id=primary_tenant_id,
            tenant_ids=resolved_tenant_ids,
            company_id=primary_company_id,
            company_ids=resolved_company_ids
        )
        # Format the plan into a readable answer for the UI
        plan_summary = f"### Strategic Architecture Plan\n\n"
        plan_summary += f"**Objective:** {plan.get('objective', 'Strategic Audit')}\n\n"
        
        phases = plan.get('phases', [])
        if phases:
            plan_summary += "**Phases:**\n"
            for i, p in enumerate(phases, 1):
                title = p if isinstance(p, str) else p.get('title', 'Phase')
                desc = "" if isinstance(p, str) else f": {p.get('description', '')}"
                plan_summary += f"{i}. **{title}**{desc}\n"
            plan_summary += "\n"
        
        plan_summary += f"**Expected Outcome:** {plan.get('expected_outcome', 'Complete Analysis')}\n\n"
        plan_summary += "---\n*This is a high-stakes request. Shall I proceed with this plan?*"
        
        answer = plan_summary
        
        # Save assistant message and plan state
        await sync_to_async(session_manager.save_message)(current_session_id, "assistant", answer, message_type="plan", payload=plan)
        session.plan_state = plan
        await sync_to_async(session.save)()
        
        return make_chat_response(
            answer,
            "PLAN",
            current_session_id,
            session.title,
            user_message,
            plan=plan,
            status="AWAITING_APPROVAL"
        )
    except Exception as e:
        log_error("chat_endpoint.PLAN", e)
        # Friendly message for API quota/limit/overloaded issues
        error_msg = str(e).lower()
        if any(k in error_msg for k in ["usage limits", "quota", "429", "overloaded", "529", "service unavailable", "temp"]):
            asyncio.create_task(
                background_retry_executor(
                    session_id=current_session_id,
                    tenant_id=primary_tenant_id,
                    tenant_ids=resolved_tenant_ids,
                    company_id=primary_company_id,
                    company_ids=resolved_company_ids,
                    user_message=user_message,
                    chat_history=chat_history_from_db,
                    db_summary=db_summary,
                    mode="PLAN"
                )
            )
            answer = "⏳ The AI provider is temporarily overloaded, but I have queued your request to generate the strategic plan in the background. Please wait a moment—it will automatically appear as soon as it's ready."
            return make_chat_response(
                answer,
                "BACKGROUND_PROCESSING",
                current_session_id,
                session.title,
                user_message
            )
            
        raise HTTPException(status_code=500, detail=str(e))


# ── Structured AI Feature Endpoints ─────────────

def _extract_json_block(text: str) -> dict | None:
    """Extract the first ```json ... ``` block from agent text output."""
    match = _re.search(r'```json\s*([\s\S]*?)\s*```', text, _re.IGNORECASE)
    if match:
        try:
            return json.loads(match.group(1))
        except (json.JSONDecodeError, ValueError):
            return None
    return None


@router.post("/report", dependencies=[_use_agent])
async def generate_ai_report(request: Request):
    body = await request.json()
    primary_tenant_id, resolved_tenant_ids, primary_company_id, resolved_company_ids = extract_context_ids(body)
    report_type = body.get("type", "analysis")
    data = body.get("data", {})

    lines = []

    if report_type == "analysis":
        lines += [
            f"## {data.get('title', 'Financial Analysis')}",
            f"**Primary Metric:** {data.get('value', 'N/A')}  |  **Trend:** {data.get('trend', 'N/A')}",
            "",
        ]
        if data.get("summary"):
            lines += ["### Executive Summary", data["summary"], ""]
        if data.get("insights"):
            lines.append("### Key Insights")
            lines += [f"- {i}" for i in data["insights"]]
            lines.append("")
        if data.get("details"):
            lines.append("### Key Findings")
            for d in data["details"]:
                lines += [f"**{d['title']}**", d["description"], ""]
        if data.get("levers"):
            lines.append("### Optimization Levers")
            lines += [f"- {l}" for l in data["levers"]]

    elif report_type == "forecast":
        lines += [
            f"## {data.get('title', 'Sales Forecast')}",
            f"**Projected Value:** {data.get('value', 'N/A')}  |  "
            f"**Period:** {data.get('period', 'N/A')}  |  "
            f"**Confidence:** {data.get('confidence', 'N/A')}%",
            "",
        ]
        if data.get("insights"):
            lines.append("### Key Insights")
            lines += [f"- {i}" for i in data["insights"]]
            lines.append("")
        if data.get("steps"):
            lines.append("### Strategic Action Plan")
            for idx, s in enumerate(data["steps"], 1):
                lines += [f"**Phase {idx}: {s['title']}**", s["description"], ""]

    elif report_type == "audit":
        lines += [
            f"## {data.get('title', 'Integrity Audit')}",
            f"**Score:** {data.get('score', 'N/A')}/100  |  "
            f"**Status:** {data.get('status', 'N/A')}  |  "
            f"**Grade:** {data.get('grade', 'N/A')}",
            "",
        ]
        if data.get("findings"):
            lines.append("### Audit Findings")
            for f in data["findings"]:
                sev = f.get("severity", "info").upper()
                lines += [f"**[{sev}] {f['title']}**", f["description"], ""]

    custom_content = "\n".join(lines)
    logo_path = body.get("logo_path")

    try:
        from .tools_refactored.reporting_v2 import generate_report_tool
        result = await sync_to_async(generate_report_tool)(
            tenant_id=primary_tenant_id,
            tenant_ids=resolved_tenant_ids,
            company_id=primary_company_id,
            company_ids=resolved_company_ids,
            custom_content=custom_content,
            logo_path=logo_path,
        )
        return {"download_url": result.get("path", result["download_url"]), "filename": result["filename"]}
    except Exception as e:
        log_error("generate_ai_report", e)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/analysis", dependencies=[_use_agent])
async def run_analysis(request: Request):
    import uuid
    body = await request.json()
    primary_tenant_id, resolved_tenant_ids, primary_company_id, resolved_company_ids = extract_context_ids(body)
    focus_area = body.get("focus_area", "Sales & Revenue")
    dimension = body.get("dimension", "Overall Performance")
    session_id = body.get("session_id") or str(uuid.uuid4())

    tool_map = {
        "Sales & Revenue": "sales_summary, period_comparison, top_products",
        "Inventory Velocity": "inventory_alerts, inventory_efficiency",
        "Operational Costs": "calculate_pnl, expense_breakdown, profitability_analysis",
    }
    tool_hint = tool_map.get(focus_area, "sales_summary, period_comparison")

    prompt = (
        f"[STRUCTURED ANALYSIS REQUEST]\n\n"
        f"Perform a deep financial analysis on: {focus_area} | Dimension: {dimension}\n"
        f"Use these tools: {tool_hint}\n\n"
        f"After completing the analysis, output ONLY this JSON block at the very end of your response:\n\n"
        "```json\n"
        "{\n"
        '  "title": "<3-5 word analysis title>",\n'
        '  "value": "<primary headline KPI with currency>",\n'
        '  "trend": "<% change vs prior period, e.g. +12.4%>",\n'
        '  "isPositive": <true or false>,\n'
        '  "insights": ["<insight with real number>", "<insight with real number>", "<insight with real number>"],\n'
        '  "summary": "<2-sentence executive summary with real figures>",\n'
        '  "details": [\n'
        '    {"title": "<finding title>", "description": "<detailed finding with data>"},\n'
        '    {"title": "<finding title>", "description": "<detailed finding with data>"}\n'
        '  ],\n'
        '  "levers": ["<action recommendation 1>", "<action recommendation 2>"]\n'
        "}\n"
        "```"
    )

    user_label = f"Analysis: {focus_area} — {dimension}"
    session_tenant_id = primary_tenant_id or "default"
    await sync_to_async(session_manager.get_or_create_session)(session_id, session_tenant_id, user_label)
    await sync_to_async(session_manager.save_message)(session_id, "user", user_label)

    try:
        answer = await asyncio.to_thread(
            fast_path_node.run,
            message=prompt,
            tenant_id=primary_tenant_id,
            tenant_ids=resolved_tenant_ids,
            company_id=primary_company_id,
            company_ids=resolved_company_ids,
            chat_history=[],
            memory_summary=""
        )
        structured = _extract_json_block(answer)
        if not structured:
            raise HTTPException(status_code=422, detail="AI did not return structured data. Please retry.")
        await sync_to_async(session_manager.save_message)(
            session_id, "assistant",
            structured.get("summary", structured.get("title", "Analysis complete.")),
            message_type="analysis", payload=structured
        )
        return {**structured, "session_id": session_id}
    except HTTPException:
        raise
    except Exception as e:
        log_error("run_analysis", e)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/forecast", dependencies=[_use_agent])
async def run_forecast(request: Request):
    import uuid
    body = await request.json()
    primary_tenant_id, resolved_tenant_ids, primary_company_id, resolved_company_ids = extract_context_ids(body)
    scope = body.get("scope", "Next 30 Days")
    risk_profile = body.get("risk_profile", "Balanced (Standard)")
    session_id = body.get("session_id") or str(uuid.uuid4())

    scope_hint = {
        "Next 30 Days": "next 30 days",
        "Quarterly Growth": "next quarter",
        "Year-End Outlook": "remainder of the current year",
    }.get(scope, "next 30 days")

    risk_hint = {
        "Conservative (Safe)": "apply a conservative 15% downward buffer to projections",
        "Balanced (Standard)": "use base trend projections without adjustment",
        "Aggressive (High Growth)": "apply an aggressive 20% upward growth multiplier",
    }.get(risk_profile, "use base trend projections without adjustment")

    prompt = (
        f"[STRUCTURED FORECAST REQUEST]\n\n"
        f"Generate a financial sales forecast for: {scope} using {risk_profile} risk parameters.\n"
        f"Time horizon: {scope_hint}. Risk guidance: {risk_hint}.\n"
        f"Use these tools: sales_forecast, sales_summary, sales_trend, period_comparison\n\n"
        f"After completing the forecast, output ONLY this JSON block at the very end of your response:\n\n"
        "```json\n"
        "{\n"
        '  "title": "<3-5 word forecast title>",\n'
        '  "value": "<projected revenue/value with currency>",\n'
        '  "period": "<forecast period description>",\n'
        '  "confidence": <integer 0-100 confidence level>,\n'
        '  "insights": ["<data-driven insight 1>", "<data-driven insight 2>", "<data-driven insight 3>"],\n'
        '  "steps": [\n'
        '    {"title": "<action phase title>", "description": "<what to do and expected outcome>"},\n'
        '    {"title": "<action phase title>", "description": "<what to do and expected outcome>"},\n'
        '    {"title": "<action phase title>", "description": "<what to do and expected outcome>"}\n'
        '  ]\n'
        "}\n"
        "```"
    )

    user_label = f"Forecast: {scope} ({risk_profile})"
    session_tenant_id = primary_tenant_id or "default"
    await sync_to_async(session_manager.get_or_create_session)(session_id, session_tenant_id, user_label)
    await sync_to_async(session_manager.save_message)(session_id, "user", user_label)

    try:
        answer = fast_path_node.run(
            message=prompt,
            tenant_id=primary_tenant_id,
            tenant_ids=resolved_tenant_ids,
            company_id=primary_company_id,
            company_ids=resolved_company_ids,
            chat_history=[],
            memory_summary=""
        )
        structured = _extract_json_block(answer)
        if not structured:
            raise HTTPException(status_code=422, detail="AI did not return structured data. Please retry.")
        await sync_to_async(session_manager.save_message)(
            session_id, "assistant",
            structured.get("title", "Forecast complete."),
            message_type="forecast", payload=structured
        )
        return {**structured, "session_id": session_id}
    except HTTPException:
        raise
    except Exception as e:
        log_error("run_forecast", e)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/audit", dependencies=[_use_agent])
async def run_audit(request: Request):
    import uuid
    body = await request.json()
    primary_tenant_id, resolved_tenant_ids, primary_company_id, resolved_company_ids = extract_context_ids(body)
    priority = body.get("priority", "Duplicate Detection")
    depth = body.get("depth", "Full Depth (Last Quarter)")
    session_id = body.get("session_id") or str(uuid.uuid4())

    depth_hint = {
        "Quick Scan (Last 7 days)": "last 7 days",
        "Full Depth (Last Quarter)": "last quarter",
        "Comprehensive (Full Year)": "full year to date",
    }.get(depth, "last quarter")

    tool_map = {
        "Duplicate Detection": "detect_anomalies, trial_balance",
        "Tax Compliance": "tax_summary, detect_anomalies",
        "Incomplete Records": "aging_analysis, receivables_analysis, detect_anomalies",
    }
    tool_hint = tool_map.get(priority, "detect_anomalies, trial_balance")

    prompt = (
        f"[STRUCTURED AUDIT REQUEST]\n\n"
        f"Perform an integrity audit focused on: {priority} | Depth: {depth} ({depth_hint}).\n"
        f"Use these tools: {tool_hint}\n\n"
        f"Calculate an overall integrity score (0-100) based on findings:\n"
        f"- 90-100: No critical issues → status: Verified, grade: AA\n"
        f"- 70-89: Minor issues → status: Attention Needed, grade: A\n"
        f"- 50-69: Notable issues → status: Issues Found, grade: B\n"
        f"- Below 50: Critical issues → status: Critical, grade: C\n\n"
        f"After completing the audit, output ONLY this JSON block at the very end of your response:\n\n"
        "```json\n"
        "{\n"
        '  "title": "<audit result title>",\n'
        '  "score": <integer 0-100>,\n'
        '  "status": "<Verified | Attention Needed | Issues Found | Critical>",\n'
        '  "grade": "<AA | A | B | C>",\n'
        '  "alerts": [\n'
        '    {"text": "<short finding title>", "sub": "<one-line detail with real data>"}\n'
        '  ],\n'
        '  "findings": [\n'
        '    {"title": "<finding title>", "description": "<detailed finding with amounts or counts>", "severity": "<critical | urgent | review | info>"}\n'
        '  ]\n'
        "}\n"
        "```"
    )

    user_label = f"Audit: {priority} — {depth}"
    session_tenant_id = primary_tenant_id or "default"
    await sync_to_async(session_manager.get_or_create_session)(session_id, session_tenant_id, user_label)
    await sync_to_async(session_manager.save_message)(session_id, "user", user_label)

    try:
        answer = fast_path_node.run(
            message=prompt,
            tenant_id=primary_tenant_id,
            tenant_ids=resolved_tenant_ids,
            company_id=primary_company_id,
            company_ids=resolved_company_ids,
            chat_history=[],
            memory_summary=""
        )
        structured = _extract_json_block(answer)
        if not structured:
            raise HTTPException(status_code=422, detail="AI did not return structured data. Please retry.")
        await sync_to_async(session_manager.save_message)(
            session_id, "assistant",
            structured.get("title", "Audit complete."),
            message_type="audit", payload=structured
        )
        return {**structured, "session_id": session_id}
    except HTTPException:
        raise
    except Exception as e:
        log_error("run_audit", e)
        raise HTTPException(status_code=500, detail=str(e))


# ── Session Management Endpoints ────────────────

@router.get("/sessions", dependencies=[_use_agent])
async def list_sessions(tenant_id: str = None):
    """List all chat sessions."""
    sessions = session_manager.get_sessions(tenant_id)
    return {
        "sessions": [
            {
                "session_id": s.session_id,
                "title": s.title,
                "last_message": s.last_message,
                "turn_count": s.turn_count,
                "updated_at": s.updated_at
            }
            for s in sessions
        ]
    }

@router.get("/sessions/{session_id}/messages", dependencies=[_use_agent])
async def get_session_messages(session_id: str):
    """Retrieve all messages for a specific session."""
    messages = session_manager.get_messages(session_id)
    return {
        "messages": [
            {
                "role": m.role,
                "content": m.content,
                "message_type": m.message_type,
                "created_at": m.created_at
            }
            for m in messages
        ]
    }

@router.get("/sessions/{session_id}", dependencies=[_use_agent])
async def get_session_details(session_id: str):
    """Retrieve details and messages for a specific session."""
    session = session_manager.get_or_create_session(session_id, "default") # tenant_id is not strictly needed for retrieval here
    messages = session_manager.get_messages(session_id)
    return {
        "session_id": session.session_id,
        "title": session.title,
        "updated_at": session.updated_at,
        "messages": [
            {
                "role": m.role,
                "content": m.content,
                "message_type": m.message_type,
                "payload": m.payload,
                "created_at": m.created_at
            }
            for m in messages
        ]
    }

@router.delete("/sessions/{session_id}", dependencies=[_use_agent])
async def delete_session(session_id: str):
    """Delete a chat session."""
    session_manager.delete_session(session_id)
    log_session_event("DELETED", session_id, "User requested deletion")
    return {"status": "deleted"}

@router.post("/approve_plan", dependencies=[_use_agent])
async def approve_plan(request: ChatRequest, plan: dict):
    user_message = request.message or request.content or request.prompt or "Plan execution"
    logger.info(f"PLAN APPROVED | Session: {request.session_id}")
    try:
        answer = await asyncio.to_thread(
            reasoning_node.execute_plan,
            message=user_message,
            plan=plan,
            tenant_id=request.tenant_id,
            company_id=request.company_id
        )
        session_manager.save_message(request.session_id, "assistant", answer)
        return make_chat_response(
            answer,
            "PLAN",
            request.session_id,
            "Plan Approved",
            user_message,
            status="DONE"
        )
    except Exception as e:
        log_error("approve_plan", e)
        error_msg = str(e).lower()
        if any(k in error_msg for k in ["usage limits", "quota", "429", "overloaded", "529", "service unavailable", "temp"]):
            asyncio.create_task(
                background_retry_executor(
                    session_id=request.session_id,
                    tenant_id=request.tenant_id,
                    company_id=request.company_id,
                    user_message=user_message,
                    chat_history=[],
                    db_summary="",
                    mode="EXECUTE_PLAN",
                    plan=plan
                )
            )
            answer = "⏳ The AI provider is temporarily overloaded, but I am executing the approved plan in the background. Please wait a moment—your dashboard/chat will automatically update as soon as the results are ready."
            return make_chat_response(
                answer,
                "BACKGROUND_PROCESSING",
                request.session_id,
                "Plan Approved",
                user_message,
                status="BACKGROUND_PROCESSING"
            )
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/reports/{filename}", tags=["Agent Reports"])
async def download_ai_report(filename: str):
    """Download an AI-generated PDF report."""
    from fastapi.responses import FileResponse
    import os

    # Prevent path traversal attacks
    if "/" in filename or "\\" in filename or ".." in filename:
        raise HTTPException(status_code=400, detail="Invalid report filename")

    report_path = os.path.join("reports", filename)
    if not os.path.exists(report_path):
        raise HTTPException(status_code=404, detail="Report not found")

    return FileResponse(
        path=report_path,
        filename=filename,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'}
    )