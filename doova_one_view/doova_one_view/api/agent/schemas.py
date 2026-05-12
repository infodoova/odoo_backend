"""
Pydantic schemas for the AI agent module.
Defines request and response shapes for multi-tenant chat and session history.
"""

from pydantic import BaseModel
from typing import Optional, Dict, Any, List


# ─────────────────────────────
# REASONING PLAN SCHEMAS
# ─────────────────────────────
class PlanStep(BaseModel):
    step: int
    action: str
    rationale: str


class ExecutionPlan(BaseModel):
    plan_id: str
    question_summary: str
    data_sources_used: List[str]
    key_findings: List[str]
    proposed_analysis_steps: List[PlanStep]
    estimated_depth: str
    status: str


# ─────────────────────────────
# INTERNAL AGENT ENDPOINT SCHEMAS
# Used by: POST /api/v1/agent/{tenant_id}/chat
# ─────────────────────────────
class AgentChatRequest(BaseModel):
    session_id: str
    message: str
    company_id: Optional[int] = None
    companies: Optional[List[int]] = None
    context: Optional[str] = None
    plan_action: Optional[str] = None  # null | approve | cancel | edit

class AgentChatResponse(BaseModel):
    session_id: str
    route: str
    message: str
    plan: Optional[ExecutionPlan] = None
    graph_data: Optional[Dict[str, Any]] = None
    report_ready: bool = False
    report_path: Optional[str] = None


# ─────────────────────────────
# FRONTEND-COMPATIBLE CHAT SCHEMAS
# Used by: POST /financial-advisor/chat
# ─────────────────────────────
class FrontendChatRequest(BaseModel):
    query: str
    tenant_id: str
    session_id: Optional[str] = None
    company_id: Optional[int] = None
    companies: Optional[List[int]] = None
    context: Optional[str] = None
    plan_action: Optional[str] = None  # null | approve | cancel | edit


class FrontendChatResponse(BaseModel):
    # Some frontends read response, some read message.
    # We return both to be safe.
    response: str
    message: str
    session_id: str
    route: str
    plan: Optional[ExecutionPlan] = None
    graph_data: Optional[Dict[str, Any]] = None
    report_ready: bool = False
    report_path: Optional[str] = None


# ─────────────────────────────
# SESSION HISTORY SCHEMAS
# ─────────────────────────────
class SessionSummary(BaseModel):
    session_id: str
    turn_count: int
    summary: str


class SessionHistoryResponse(BaseModel):
    session_id: str
    summary: str
    raw_turns: List[Dict[str, Any]]
    plan_state: Optional[Dict[str, Any]] = None
    turn_count: int


class DeleteSessionResponse(BaseModel):
    session_id: str
    deleted: bool
    message: str
