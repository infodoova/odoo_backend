# api/agent/routes.py

import json
import time
import asyncio
from asgiref.sync import sync_to_async
from fastapi import APIRouter, HTTPException, Depends, Request
from pydantic import BaseModel, Field, ConfigDict
from typing import List, Optional

from .router import RouterNode
from .fast_path import FastPathNode
from .reasoning import ReasoningNode
from .utils import make_report_url
from .logger import log_session_event, log_error, logger

from .session_manager import SessionManager

# Initialize Nodes
router_node = RouterNode()
fast_path_node = FastPathNode()
reasoning_node = ReasoningNode()
router = APIRouter(prefix="/financial-advisor", tags=["Agent"])
session_manager = SessionManager()

class ChatRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    message: str = Field(alias="text", default="")
    query_alt: Optional[str] = Field(alias="query", default=None)
    content: Optional[str] = Field(alias="userInput", default=None)
    prompt: Optional[str] = Field(default=None)
    tenant_id: str = Field(alias="tenantId", default="default")
    session_id: str = Field(alias="sessionId", default="default_session")
    company_id: Optional[int] = Field(alias="companyId", default=None)
    chat_history: Optional[List[dict]] = Field(default=[])

    # Fallback for 'message' vs 'text'
    @property
    def query(self) -> str:
        return self.message

def make_chat_response(
    answer: str,
    mode: str,
    session_id: str,
    session_title: str,
    user_message: str,
    plan: Optional[dict] = None,
    status: Optional[str] = None
) -> dict:
    from .utils import parse_graph_data_from_text, strip_visual_charts_from_text
    
    graph_data = parse_graph_data_from_text(answer)
    has_parsed_graph = bool(graph_data)
    
    final_answer = answer
    if has_parsed_graph:
        final_answer = strip_visual_charts_from_text(answer)
        
    res = {
        "answer": final_answer,
        "mode": mode,
        "session_id": session_id,
        "session_title": session_title,
        "type": "graph" if has_parsed_graph else "text",
        "graph_data": graph_data
    }
    if plan is not None:
        res["plan"] = plan
    if status is not None:
        res["status"] = status
    return res


async def background_retry_executor(
    session_id: str,
    tenant_id: str,
    company_id: int | None,
    user_message: str,
    chat_history: list,
    db_summary: str,
    mode: str = "EXECUTE",
    plan: dict = None
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
                
                answer = await sync_to_async(fast_path_node.run)(
                    message=user_message,
                    tenant_id=tenant_id,
                    company_id=company_id,
                    chat_history=chat_history,
                    memory_summary=db_summary,
                    on_summary=save_summary_to_db
                )
            elif mode == "PLAN":
                plan_result = await sync_to_async(reasoning_node.create_plan)(
                    message=user_message,
                    tenant_id=tenant_id,
                    company_id=company_id
                )
                
                plan_summary = f"### 🗺️ Strategic Architecture Plan (Completed in Background)\n\n"
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
                    s = session_manager.get_or_create_session(session_id, tenant_id)
                    s.plan_state = plan_result
                    s.save()
                await sync_to_async(_update_session_plan)()
            elif mode == "EXECUTE_PLAN":
                answer = await sync_to_async(reasoning_node.execute_plan)(
                    message=user_message,
                    plan=plan,
                    tenant_id=tenant_id,
                    company_id=company_id
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
                err_text = "❌ I attempted to process your request in the background but ran into persistent issues with the AI provider. Please try sending your message again shortly."
                await sync_to_async(session_manager.save_message)(session_id, "assistant", err_text)
                return

@router.post("/chat")
async def chat_endpoint(request: Request):
    # Get raw body for debugging
    body = await request.json()
    logger.info(f"RAW REQUEST BODY: {json.dumps(body)}")
    
    # Parse into ChatRequest manually to keep flexibility
    try:
        req_data = ChatRequest(**body)
    except Exception as e:
        logger.error(f"Failed to parse ChatRequest: {e}")
        req_data = ChatRequest(message=body.get("message", body.get("text", "")))

    request_start = time.time()
    
    # Extract message from multiple potential sources
    user_message = req_data.query_alt or req_data.message or req_data.content or req_data.prompt or ""
    
    # 1. Immediate Session Handling
    import uuid
    from asgiref.sync import sync_to_async
    
    current_session_id = req_data.session_id
    if not current_session_id or current_session_id == "new" or current_session_id == "default_session":
        current_session_id = str(uuid.uuid4())
        logger.info(f"Generated new session ID: {current_session_id}")

    # Load session and history BEFORE saving new message
    session = await sync_to_async(session_manager.get_or_create_session)(current_session_id, req_data.tenant_id, user_message)
    
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

    # Handle empty messages / simple greetings
    if not user_message or not user_message.strip() or user_message.lower() in ["hi", "hello", "hey"]:
        answer = "Hello! I am your Doova Finance Brain. How can I assist you with your business data today?"
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
        f"   Tenant: {req_data.tenant_id}\n"
        f"   Company: {req_data.company_id or 'ALL'}\n"
        f"   Message: \"{user_message[:100]}\"\n"
        f"   History Context: {len(chat_history_from_db)} messages"
    )

    # 2. Routing
    decision = router_node.classify(user_message)
    
    # 2.1 Handle Plan Approval (CONFIRM path)
    if decision == "CONFIRM" and session.plan_state:
        try:
            logger.info(f"PLAN APPROVED: Executing strategic architecture for session {current_session_id}")
            answer = reasoning_node.execute_plan(
                message=user_message,
                plan=session.plan_state,
                tenant_id=req_data.tenant_id,
                company_id=req_data.company_id
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
                        tenant_id=req_data.tenant_id,
                        company_id=req_data.company_id,
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
            
            answer = fast_path_node.run(
                message=user_message,
                tenant_id=req_data.tenant_id,
                company_id=req_data.company_id,
                chat_history=chat_history_from_db,
                memory_summary=db_summary,
                on_summary=save_summary_to_db
            )
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
                        tenant_id=req_data.tenant_id,
                        company_id=req_data.company_id,
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
        # For planning, we also want to pass context if possible
        # Since create_plan doesn't take full history yet, we'll pass it via reasoning_node if updated, 
        # or just ensure the session title is used as context.
        plan = reasoning_node.create_plan(
            message=user_message,
            tenant_id=req_data.tenant_id,
            company_id=req_data.company_id
        )
        # Format the plan into a readable answer for the UI
        plan_summary = f"### 🗺️ Strategic Architecture Plan\n\n"
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
                    tenant_id=req_data.tenant_id,
                    company_id=req_data.company_id,
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


# ── Session Management Endpoints ────────────────

@router.get("/sessions")
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

@router.get("/sessions/{session_id}/messages")
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

@router.get("/sessions/{session_id}")
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
                "created_at": m.created_at
            }
            for m in messages
        ]
    }

@router.delete("/sessions/{session_id}")
async def delete_session(session_id: str):
    """Delete a chat session."""
    session_manager.delete_session(session_id)
    log_session_event("DELETED", session_id, "User requested deletion")
    return {"status": "deleted"}

@router.post("/approve_plan")
async def approve_plan(request: ChatRequest, plan: dict):
    user_message = request.message or request.content or request.prompt or "Plan execution"
    logger.info(f"PLAN APPROVED | Session: {request.session_id}")
    try:
        answer = reasoning_node.execute_plan(
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