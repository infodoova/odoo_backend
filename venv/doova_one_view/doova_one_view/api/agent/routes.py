# api/agent/routes.py

import time
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from typing import List, Optional

from .router import RouterNode
from .fast_path import FastPathNode
from .reasoning import ReasoningNode
from .utils import make_report_url
from .logger import log_session_event, log_error, logger

router = APIRouter()

from .session_manager import SessionManager

# Initialize Nodes
router_node = RouterNode()
fast_path_node = FastPathNode()
reasoning_node = ReasoningNode()
session_manager = SessionManager()

class ChatRequest(BaseModel):
    message: str
    tenant_id: str
    session_id: str
    company_id: Optional[int] = None
    chat_history: Optional[List[dict]] = []

@router.post("/chat")
async def chat_endpoint(request: ChatRequest):
    request_start = time.time()
    logger.info(
        f"📨 INCOMING REQUEST\n"
        f"   Session: {request.session_id}\n"
        f"   Tenant: {request.tenant_id}\n"
        f"   Company: {request.company_id or 'ALL'}\n"
        f"   Message: \"{request.message[:100]}\""
    )

    # 1. Session Handling
    session = session_manager.get_or_create_session(request.session_id, request.message)
    session_manager.save_message(request.session_id, "user", request.message)
    log_session_event("MESSAGE_SAVED", request.session_id, "user message")

    # 2. Routing
    decision = router_node.classify(request.message)
    
    if decision == "REJECT":
        answer = "I'm sorry, I can only assist with business and financial questions related to your Odoo data."
        session_manager.save_message(request.session_id, "assistant", answer)
        duration = (time.time() - request_start) * 1000
        logger.info(f"🚫 REQUEST REJECTED in {duration:.0f}ms")
        return {"answer": answer}
    
    # 3. Execution
    if decision == "EXECUTE":
        try:
            answer = fast_path_node.run(
                message=request.message,
                tenant_id=request.tenant_id,
                company_id=request.company_id,
                chat_history=request.chat_history
            )
            session_manager.save_message(request.session_id, "assistant", answer)
            duration = (time.time() - request_start) * 1000
            logger.info(f"⚡ EXECUTE COMPLETE in {duration:.0f}ms | Response: \"{answer[:80]}...\"")
            return {"answer": answer, "mode": "EXECUTE", "session_title": session.title}
        except Exception as e:
            log_error("chat_endpoint.EXECUTE", e)
            raise HTTPException(status_code=500, detail=str(e))
    
    # 4. Planning (High-Stakes Architecture Phase)
    try:
        plan = reasoning_node.create_plan(
            message=request.message,
            tenant_id=request.tenant_id,
            company_id=request.company_id
        )
        duration = (time.time() - request_start) * 1000
        logger.info(f"📋 PLAN GENERATED in {duration:.0f}ms | Awaiting approval")
        
        return {
            "answer": "This is a high-stakes request. I have prepared a strategic architecture plan. Shall I proceed?",
            "plan": plan,
            "mode": "PLAN",
            "status": "AWAITING_APPROVAL",
            "session_title": session.title
        }
    except Exception as e:
        log_error("chat_endpoint.PLAN", e)
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/sessions")
async def list_sessions():
    sessions = session_manager.get_sessions()
    return [{"id": s.session_id, "title": s.title, "updated_at": s.updated_at, "turn_count": s.turn_count} for s in sessions]

@router.get("/sessions/{session_id}/messages")
async def get_session_messages(session_id: str):
    messages = session_manager.get_messages(session_id)
    return [{"role": m.role, "content": m.content, "created_at": m.created_at} for m in messages]

@router.delete("/sessions/{session_id}")
async def delete_session(session_id: str):
    session_manager.delete_session(session_id)
    log_session_event("DELETED", session_id)
    return {"status": "deleted"}

@router.post("/approve_plan")
async def approve_plan(request: ChatRequest, plan: dict):
    logger.info(f"✅ PLAN APPROVED | Session: {request.session_id}")
    try:
        answer = reasoning_node.execute_plan(
            message=request.message,
            plan=plan,
            tenant_id=request.tenant_id,
            company_id=request.company_id
        )
        session_manager.save_message(request.session_id, "assistant", answer)
        return {"answer": answer, "mode": "PLAN", "status": "DONE"}
    except Exception as e:
        log_error("approve_plan", e)
        raise HTTPException(status_code=500, detail=str(e))