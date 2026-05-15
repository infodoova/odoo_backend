# api/agent/routes.py

import json
import time
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
    db_messages = await sync_to_async(list)(session_manager.get_messages(current_session_id))
    
    chat_history_from_db = [
        {"role": m.role, "content": m.content}
        for m in db_messages
        if m.role in ("user", "assistant")
    ]
    
    # Now save the new user message to DB
    await sync_to_async(session_manager.save_message)(current_session_id, "user", user_message or "[Empty Message]")
    log_session_event("MESSAGE_SAVED", current_session_id, "user message")

    # Handle empty messages / simple greetings
    if not user_message or not user_message.strip() or user_message.lower() in ["hi", "hello", "hey"]:
        answer = "Hello! I am your Doova Finance Brain. How can I assist you with your business data today?"
        await sync_to_async(session_manager.save_message)(current_session_id, "assistant", answer)
        return {
            "answer": answer,
            "mode": "EXECUTE",
            "session_id": current_session_id,
            "session_title": session.title
        }

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
            return {
                "answer": answer,
                "mode": "EXECUTE_PLAN",
                "session_id": current_session_id,
                "session_title": session.title
            }
        except Exception as e:
            log_error("chat_endpoint.CONFIRM_EXECUTE", e)
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
            answer = fast_path_node.run(
                message=user_message,
                tenant_id=req_data.tenant_id,
                company_id=req_data.company_id,
                chat_history=chat_history_from_db
            )
            await sync_to_async(session_manager.save_message)(current_session_id, "assistant", answer)
            duration = (time.time() - request_start) * 1000
            logger.info(f"EXECUTE COMPLETE in {duration:.0f}ms | Response: \"{answer[:80]}...\"")
            return {
                "answer": answer,
                "mode": "EXECUTE",
                "session_id": current_session_id,
                "session_title": session.title
            }
        except Exception as e:
            log_error("chat_endpoint.EXECUTE", e)
            
            # Friendly message for API quota/limit issues
            error_msg = str(e).lower()
            if "usage limits" in error_msg or "quota" in error_msg or "429" in error_msg:
                answer = "I'm currently experiencing high demand and have reached my processing limit for the moment. Please try again in a short while or contact support if the issue persists."
                await sync_to_async(session_manager.save_message)(current_session_id, "assistant", answer)
                return {"answer": answer, "mode": "ERROR", "session_id": current_session_id}
                
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
        
        return {
            "answer": answer,
            "plan": plan,
            "mode": "PLAN",
            "session_id": current_session_id,
            "status": "AWAITING_APPROVAL",
            "session_title": session.title
        }
    except Exception as e:
        log_error("chat_endpoint.PLAN", e)
        # Friendly message for API quota/limit issues
        error_msg = str(e).lower()
        if "usage limits" in error_msg or "quota" in error_msg or "429" in error_msg:
            answer = "I'm currently experiencing high demand and have reached my processing limit for the moment. Please try again in a short while."
            await sync_to_async(session_manager.save_message)(current_session_id, "assistant", answer)
            return {"answer": answer, "mode": "ERROR", "session_id": current_session_id}
            
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
        return {
            "answer": answer, 
            "mode": "PLAN", 
            "status": "DONE",
            "session_id": request.session_id
        }
    except Exception as e:
        log_error("approve_plan", e)
        raise HTTPException(status_code=500, detail=str(e))