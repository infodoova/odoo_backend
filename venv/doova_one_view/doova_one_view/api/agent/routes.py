# api/agent/routes.py

import re as _re
import json
import time
import asyncio
from asgiref.sync import sync_to_async
from fastapi import APIRouter, HTTPException, Depends, Request
from pydantic import BaseModel, Field, ConfigDict, model_validator
from typing import List, Optional, Union, Any

from .router import RouterNode
from .fast_path import FastPathNode
from .reasoning import ReasoningNode
from .utils import make_report_url
from .logger import log_session_event, log_error, logger

from .session_manager import SessionManager
from .query_context import resolve_tenant_id, normalize_tenant_ids, normalize_company_ids
from .config import AgentConfig
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

    tenant_ids: Optional[Union[List[str], str]] = Field(alias="tenantIds", default=None)
    tenant_id: Optional[str] = Field(alias="tenantId", default=None)
    session_id: str = Field(alias="sessionId", default="default_session")
    company_ids: Optional[Union[List[Union[int, str]], Union[int, str]]] = Field(alias="companyIds", default=None)
    company_id: Optional[Union[int, str]] = Field(alias="companyId", default=None)

    chat_history: Optional[List[dict]] = Field(default=[])
    web_search: Optional[bool] = Field(alias="webSearch", default=False)
    attachments: Optional[List[dict]] = Field(default=None)
    is_voice: Optional[bool] = Field(alias="isVoice", default=False)
    language: Optional[str] = Field(default=None)

    @model_validator(mode="before")
    @classmethod
    def normalize_aliases(cls, data: Any) -> Any:
        if isinstance(data, dict):
            t_id = data.get("tenant_id") or data.get("tenantId")
            t_ids = data.get("tenant_ids") or data.get("tenantIds")
            if t_id and not data.get("tenant_id"):
                data["tenant_id"] = t_id
            if t_id and t_ids:
                if isinstance(t_ids, list):
                    data["tenant_ids"] = [t_id] + [x for x in t_ids if x != t_id]
                else:
                    data["tenant_ids"] = [t_id, t_ids]
            elif t_id and not t_ids:
                data["tenant_ids"] = t_id

            c_id = data.get("company_id") or data.get("companyId")
            c_ids = data.get("company_ids") or data.get("companyIds")
            if c_id is not None and not data.get("company_id"):
                data["company_id"] = c_id
            if c_id is not None and c_ids is not None:
                if isinstance(c_ids, list):
                    data["company_ids"] = [c_id] + [x for x in c_ids if x != c_id]
                else:
                    data["company_ids"] = [c_id, c_ids]
            elif c_id is not None and c_ids is None:
                data["company_ids"] = c_id
        return data

    # Fallback for 'message' vs 'text'
    @property
    def query(self) -> str:
        return self.message

def extract_context_ids(req_data: Union[ChatRequest, dict]):
    """
    Extracts and normalizes tenant and company parameters from a ChatRequest or dict.
    Returns: (primary_tenant_id, resolved_tenant_ids, primary_company_id, resolved_company_ids)
    """
    if isinstance(req_data, ChatRequest):
        t_single = getattr(req_data, "tenant_id", None)
        t_multi = getattr(req_data, "tenant_ids", None)
        c_single = getattr(req_data, "company_id", None)
        c_multi = getattr(req_data, "company_ids", None)
    else:
        t_single = req_data.get("tenant_id") or req_data.get("tenantId")
        t_multi = req_data.get("tenant_ids") or req_data.get("tenantIds")
        c_single = req_data.get("company_id") or req_data.get("companyId")
        c_multi = req_data.get("company_ids") or req_data.get("companyIds")

    raw_tenants = []
    if t_single:
        raw_tenants.append(t_single)
    if t_multi:
        if isinstance(t_multi, list):
            raw_tenants.extend(t_multi)
        else:
            raw_tenants.append(t_multi)

    raw_companies = []
    if c_single is not None:
        raw_companies.append(c_single)
    if c_multi is not None:
        if isinstance(c_multi, list):
            raw_companies.extend(c_multi)
        else:
            raw_companies.append(c_multi)

    resolved_tenant_ids = normalize_tenant_ids(raw_tenants)
    resolved_company_ids = normalize_company_ids(raw_companies)

    clean_single_t = normalize_tenant_ids([t_single])[0] if t_single and normalize_tenant_ids([t_single]) else None
    primary_tenant_id = clean_single_t or (resolved_tenant_ids[0] if resolved_tenant_ids else None)

    clean_single_c = normalize_company_ids([c_single])[0] if c_single is not None and normalize_company_ids([c_single]) else None
    primary_company_id = clean_single_c if clean_single_c is not None else (resolved_company_ids[0] if len(resolved_company_ids) == 1 else None)

    return primary_tenant_id, resolved_tenant_ids, primary_company_id, resolved_company_ids

def format_pdf_links_as_clickable_markdown(text: str) -> tuple[str, Optional[str]]:
    """
    Ensures any generated PDF report URLs are formatted as standard clickable Markdown links.
    Converts raw strings or backtick-wrapped paths like `/reports/x.pdf` into `[📥 **Download PDF Report**](/reports/x.pdf)`.
    """
    if not text:
        return text, None

    download_url = None
    pdf_pattern = r'(?:https?://[^\s`()]+)?/(?:api/v1/)?(?:financial-advisor/)?reports/[^\s`()]+\.pdf'
    match = _re.search(pdf_pattern, text)
    if match:
        download_url = match.group(0)

    # 1. Replace backticked PDF links `.../reports/xyz.pdf` with [📥 **Download PDF Report**](url)
    text = _re.sub(
        r'`\s*((?:https?://[^\s`()]+)?/(?:api/v1/)?(?:financial-advisor/)?reports/[^`\s()]+\.pdf)\s*`',
        r'[📥 **Download PDF Report**](\1)',
        text
    )

    # 2. Replace raw unlinked URLs (not preceded by `](` or `(`) with clickable markdown links
    text = _re.sub(
        r'(?<!\]\()(?<!\()(?<!`)\b((?:https?://[^\s`()]+)?/(?:api/v1/)?(?:financial-advisor/)?reports/[^\s`()]+\.pdf)\b(?!\))',
        r'[📥 **Download PDF Report**](\1)',
        text
    )

    return text, download_url


def make_chat_response(
    answer: str,
    mode: str,
    session_id: str,
    session_title: str,
    user_message: str,
    plan: Optional[dict] = None,
    status: Optional[str] = None,
    citations: Optional[List[dict]] = None,
) -> dict:
    from .utils import parse_json_chart_from_text, strip_json_chart_from_text, replace_tenant_ids_with_names

    chart_payload = parse_json_chart_from_text(answer)

    if chart_payload:
        final_answer = strip_json_chart_from_text(answer)
        if not final_answer:
            final_answer = chart_payload.get("message", "")
        res_type = "graph"
    else:
        final_answer = answer
        res_type = "text"

    final_answer = replace_tenant_ids_with_names(final_answer)
    final_answer, pdf_download_url = format_pdf_links_as_clickable_markdown(final_answer)

    res = {
        "answer": final_answer,
        "mode": mode,
        "session_id": session_id,
        "session_title": session_title,
        "type": res_type,
    }

    if pdf_download_url:
        res["download_url"] = pdf_download_url

    if chart_payload:
        res["payload"] = chart_payload

    if plan is not None:
        try:
            cleaned_plan_str = replace_tenant_ids_with_names(json.dumps(plan))
            res["plan"] = json.loads(cleaned_plan_str)
        except Exception:
            res["plan"] = plan
    if status is not None:
        res["status"] = status
    if citations:
        res["citations"] = citations
    return res


def _is_credit_balance_error(e: Exception) -> bool:
    error_msg = str(e).lower()
    return any(k in error_msg for k in ["credit balance", "insufficient credits", "billing", "plans & billing", "balance is too low", "purchase credits"])

def get_user_facing_error_message(e: Exception | None = None) -> str:
    """Standardized user-facing error message for all agent errors."""
    return "⚠️ An error occurred while processing your request. Please try again later or contact support if the problem persists."

async def background_retry_executor(
    session_id: str,
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
            from .session_context import set_session_context
            set_session_context(session_id)
            
            if mode == "EXECUTE":
                def save_summary_to_db(summary_text: str):
                    session_manager.save_summary(session_id, summary_text)
                    logger.info(f"BACKGROUND SUMMARY SAVED | Session: {session_id}")
                
                answer = await asyncio.to_thread(fast_path_node.run, 
                    message=user_message,
                    tenant_ids=tenant_ids,
                    company_ids=company_ids,
                    chat_history=chat_history,
                    memory_summary=db_summary,
                    on_summary=save_summary_to_db
                )
            elif mode == "PLAN":
                plan_result = await asyncio.to_thread(reasoning_node.create_plan, 
                    message=user_message,
                    tenant_ids=tenant_ids,
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
                    primary_tid = tenant_ids[0] if tenant_ids else "default"
                    s = session_manager.get_or_create_session(session_id, primary_tid)
                    s.plan_state = plan_result
                    s.save()
                await sync_to_async(_update_session_plan)()
            elif mode == "EXECUTE_PLAN":
                answer = await asyncio.to_thread(reasoning_node.execute_plan, 
                    message=user_message,
                    plan=plan,
                    tenant_ids=tenant_ids,
                    company_ids=company_ids
                )
            
            token_usage = (fast_path_node.get_last_token_usage() if mode == "EXECUTE" else reasoning_node.get_last_token_usage())
            bg_payload = {"token_usage": token_usage} if (token_usage and token_usage.get("total_tokens", 0) > 0) else None
            await sync_to_async(session_manager.save_message)(session_id, "assistant", answer, payload=bg_payload)
            logger.info(f"BACKGROUND RETRY SUCCESS | Session: {session_id} on attempt {attempt}")
            return
            
        except Exception as e:
            if _is_credit_balance_error(e):
                err_text = get_user_facing_error_message(e)
                await sync_to_async(session_manager.save_message)(session_id, "assistant", err_text)
                return

            error_msg = str(e).lower()
            is_temporary = any(k in error_msg for k in ["usage limits", "quota", "429", "overloaded", "529", "service unavailable", "temp"])
            if is_temporary and attempt < max_retries:
                logger.warning(f"BACKGROUND RETRY FAILED (temp error) | Session: {session_id} | Waiting {delay}s...")
                await asyncio.sleep(delay)
                delay *= 2.0  # exponential backoff
            else:
                logger.error(f"BACKGROUND RETRY FAILED PERMANENTLY | Session: {session_id} | Error: {e}")
                err_text = get_user_facing_error_message(e)
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
    
    # Clean voice mode tags, reply-to metadata, and unicode directional/control marks immediately
    clean_user_message = user_message
    is_voice_mode = bool(req_data.is_voice) or ("[VOICE MODE:" in user_message)
    user_language = req_data.language or None
    if "[VOICE MODE:" in user_message:
        clean_user_message = _re.sub(r'\[VOICE MODE:[^\]]*\]', '', user_message).strip()
    clean_user_message = _re.sub(r'>\s*\[REPLY_TO:[^\]]*\]', '', clean_user_message).strip()
    clean_user_message = _re.sub(r'[\u200e\u200f\u202a-\u202e\u2066-\u2069\ufeff\u200b\u200c\u200d]', '', clean_user_message).strip()

    enable_web_search = bool(
        (getattr(req_data, "web_search", False) or (isinstance(body, dict) and (body.get("web_search") or body.get("webSearch"))))
        and getattr(AgentConfig, "ENABLE_WEB_SEARCH", False)
    )

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
    session = await sync_to_async(session_manager.get_or_create_session)(current_session_id, session_tenant_id, user_message)
    
    # Initialize thread-safe session context with active date window + scope IDs
    from .session_context import set_session_context, get_active_tenant_ids, get_active_company_ids
    set_session_context(
        current_session_id,
        session.active_date_window,
        tenant_ids=resolved_tenant_ids or None,
        company_ids=resolved_company_ids or None,
    )

    # If the request did not supply tenant/company scope (e.g. voice mode sends bare query),
    # inherit the active scope from the persisted session context.
    if not resolved_tenant_ids:
        inherited_tids = get_active_tenant_ids(current_session_id)
        if inherited_tids:
            resolved_tenant_ids = inherited_tids
            primary_tenant_id = inherited_tids[0]
            logger.info(f"SCOPE INHERIT | Session {current_session_id}: tenant_ids inherited from session -> {inherited_tids}")
    if not resolved_company_ids:
        inherited_cids = get_active_company_ids(current_session_id)
        if inherited_cids:
            resolved_company_ids = inherited_cids
            logger.info(f"SCOPE INHERIT | Session {current_session_id}: company_ids inherited from session -> {inherited_cids}")

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
    
    # Save the new user message to DB (persisting attachments in payload if present)
    user_payload = {"attachments": req_data.attachments} if req_data.attachments else {}
    await sync_to_async(session_manager.save_message)(
        current_session_id, "user", user_message or "[Empty Message]", payload=user_payload
    )
    log_session_event("MESSAGE_SAVED", current_session_id, "user message")

    ARABIC_GREETINGS = {
        "هلا", "مرحبا", "مرحب", "سلام", "السلام", "أهلا", "أهلاً", "أهلين", "اهلين",
        "صباح الخير", "مساء الخير", "حياك الله", "حياك", "حياكم", "يا هلا", "مرحبا بك",
        "أهلا وسهلا", "اهلا وسهلا", "يعطيك العافية", "شكرا", "شكراً", "تسلم", "مشكور",
        "السلام عليكم", "سلام عليكم", "هاي", "هلو", "كيف الحال", "كيفك", "شخبارك", "هلا وغلا"
    }
    FRENCH_GREETINGS = {
        "bonjour", "salut", "coucou", "bonsoir", "merci", "au revoir", "comment ca va", "comment allez-vous"
    }
    SPANISH_GREETINGS = {
        "hola", "buenos dias", "buenas tardes", "buenas noches", "gracias", "adios", "que tal", "como estas"
    }
    ENGLISH_GREETINGS = {
        "hi", "hello", "hey", "how are you", "how are you?",
        "good morning", "good afternoon", "good evening",
        "thanks", "thank you", "bye", "goodbye", "ok", "okay",
        "greetings", "whats up", "what's up", "yo"
    }

    # Helper: Check if message is a short greeting / pleasantry
    msg_clean_lower = clean_user_message.lower().strip("!.? \t\n\r,;")
    msg_words = msg_clean_lower.split()
    
    is_arabic_greeting = (
        msg_clean_lower in ARABIC_GREETINGS
        or (any(w in ARABIC_GREETINGS for w in msg_words) and len(msg_words) <= 4)
        or (any(clean_user_message.startswith(g) for g in ["هلا", "مرحبا", "السلام عليكم", "أهلا", "اهلا", "صباح الخير", "مساء الخير"]) and len(msg_words) <= 5)
    )
    is_french_greeting = (
        msg_clean_lower in FRENCH_GREETINGS
        or (any(w in FRENCH_GREETINGS for w in msg_words) and len(msg_words) <= 3)
    )
    is_spanish_greeting = (
        msg_clean_lower in SPANISH_GREETINGS
        or (any(w in SPANISH_GREETINGS for w in msg_words) and len(msg_words) <= 3)
    )
    is_english_greeting = (
        msg_clean_lower in ENGLISH_GREETINGS
        or (any(w in ENGLISH_GREETINGS for w in msg_words) and len(msg_words) <= 3)
    )

    # Handle empty messages / simple social phrases before hitting the router (only if no attachments)
    if not req_data.attachments and (not user_message or not user_message.strip() or is_arabic_greeting or is_french_greeting or is_spanish_greeting or is_english_greeting):
        if is_arabic_greeting:
            answer = "أهلاً وسهلاً بك! أنا Nexus. كيف يمكنني مساعدتك في بيانات أعمالك اليوم؟"
        elif is_french_greeting:
            answer = "Bonjour ! Je suis Nexus. Comment puis-je vous aider avec vos données d'entreprise aujourd'hui ?"
        elif is_spanish_greeting:
            answer = "¡Hola! Soy Nexus. ¿Cómo puedo ayudarte con los datos de tu empresa hoy?"
        else:
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
        f"   Attachments: {len(req_data.attachments) if req_data.attachments else 0}\n"
        f"   Voice Mode: {is_voice_mode}\n"
        f"   Language: {user_language}\n"
        f"   History Context: {len(chat_history_from_db)} messages"
    )

    # If user provided attachments, always route to EXECUTE directly
    if req_data.attachments:
        decision = "EXECUTE"

    # ── Defense 1: Pre-Router Deterministic Fast Path ──────────────────────
    # Short affirmations MUST NOT go through the LLM router. The router is
    # unreliable for 1-3 word messages and may misclassify "yes" as PLAN.
    # Instead, we deterministically resolve them here.
    _HARD_AFFIRMATIVE_TOKENS = {
        # English
        "yes", "ye", "yeah", "yep", "yup", "ya", "yaa", "yess", "yesss",
        "sure", "ok", "okay", "proceed", "go", "ahead", "confirm", "approve",
        "right", "fine", "alright", "perfect", "great", "cool", "do",
        # French
        "oui", "ouais", "bien", "entendu", "d'accord", "daccord",
        # Spanish
        "si", "sí", "claro", "vale", "dale", "bueno",
        # Arabic
        "\u0646\u0639\u0645", "\u0623\u064a\u0648\u0629", "\u0627\u064a\u0648\u0629", "\u062a\u0645\u0627\u0645", "\u0645\u0627\u0634\u064a", "\u064a\u0644\u0627", "\u0627\u062a\u0643\u0644",
        "\u062e\u0644\u0627\u0635", "\u0623\u0643\u064a\u062f", "\u0627\u0643\u064a\u062f", "\u0637\u0628\u0639\u0627\u064b", "\u0637\u0628\u0639\u0627", "\u0645\u0648\u0627\u0641\u0642", "\u064a\u0627\u0644\u0644\u0647",
        "\u0627\u0645\u0634\u064a", "\u0627\u0639\u0645\u0644", "\u0627\u0628\u062f\u0623",
    }
    _SHORT_MSG_THRESHOLD = 8  # words
    _pre_router_words = clean_user_message.strip().split()
    _pre_router_word_set = {w.lower().strip("!?.,;:'\"") for w in _pre_router_words}

    if (len(_pre_router_words) <= _SHORT_MSG_THRESHOLD
            and _pre_router_word_set.intersection(_HARD_AFFIRMATIVE_TOKENS)):
        # Short affirmative detected — skip the LLM router entirely
        if session.plan_state:
            decision = "CONFIRM"
            logger.info(f"PRE-ROUTER FAST PATH | Short affirmative with pending plan → CONFIRM | msg='{clean_user_message}'")
        else:
            decision = "EXECUTE"
            logger.info(f"PRE-ROUTER FAST PATH | Short affirmative, no plan → EXECUTE | msg='{clean_user_message}'")
    else:
        # 2. Routing (pass recent chat history for context-aware intent resolution)
        try:
            decision = await asyncio.to_thread(router_node.classify, clean_user_message or user_message, chat_history_from_db)
        except Exception as e:
            log_error("router_node.classify", e)
            decision = "EXECUTE"

    # 2.1 Handle Plan Approval (CONFIRM path with deterministic affirmative matching)
    REJECTION_KEYWORDS = {"no", "nope", "nah", "cancel", "stop", "abort", "dont", "don't", "refuse", "reject", "nevermind", "nvm"}
    AFFIRMATIVE_KEYWORDS = {
        "yes", "ye", "yeah", "yep", "yup", "ya", "yaa", "yess", "yesss", "sure", "ok", "okay", "k", "kk",
        "proceed", "go", "ahead", "do", "it", "confirm", "approve", "accepted", "agreed", "correct",
        "right", "fine", "alright", "please", "pls", "plsn", "execute", "run", "start", "plan", "show",
        "give", "perfect", "awesome", "great", "nice", "good", "super", "cool", "thx", "thanks", "thank",
        "si", "oui", "claro", "vale", "sy", "sim", "create", "generate", "build", "make", "fetch", "pull",
        # Arabic affirmations
        "\u0646\u0639\u0645", "\u0623\u064a\u0648\u0629", "\u0627\u064a\u0648\u0629", "\u062a\u0645\u0627\u0645", "\u0645\u0627\u0634\u064a", "\u064a\u0644\u0627", "\u0627\u062a\u0643\u0644", "\u062e\u0644\u0627\u0635",
        "\u0623\u0643\u064a\u062f", "\u0627\u0643\u064a\u062f", "\u0637\u0628\u0639\u0627\u064b", "\u0637\u0628\u0639\u0627", "\u0645\u0648\u0627\u0641\u0642", "\u064a\u0627\u0644\u0644\u0647", "\u0627\u0645\u0634\u064a", "\u0627\u0639\u0645\u0644", "\u0627\u0628\u062f\u0623",
    }
    AFFIRMATIVE_PHRASES = [
        "give me", "sounds good", "looks good", "let's do", "lets do", "go ahead", "do it",
        "run it", "give it", "show me", "why not", "of course", "do that", "do this", "all right",
        # Arabic affirmative phrases
        "\u0627\u062a\u0643\u0644 \u0639\u0644\u0649 \u0627\u0644\u0644\u0647", "\u0639\u0644\u0649 \u0628\u0631\u0643\u0629 \u0627\u0644\u0644\u0647", "\u064a\u0644\u0627 \u0627\u0645\u0634\u064a", "\u0627\u0639\u0645\u0644 \u0644\u0646\u0627", "\u0627\u0639\u0645\u0644\u0647\u0627",
    ]

    lower_msg = clean_user_message.lower()
    user_words = set(_re.findall(r'\b\w+\b', lower_msg))
    is_explicit_rejection = bool(user_words.intersection(REJECTION_KEYWORDS))

    # If plan is pending and message is NOT an explicit rejection:
    # treat explicit positive token or phrase as an approval
    is_affirmative = not is_explicit_rejection and (
        bool(user_words.intersection(AFFIRMATIVE_KEYWORDS)) or
        any(phrase in lower_msg for phrase in AFFIRMATIVE_PHRASES)
    )

    if session.plan_state and (decision == "CONFIRM" or is_affirmative):
        from django.utils import timezone
        import datetime
        # Enforce plan expiry: stale plans are discarded to prevent accidental re-execution
        plan_age_ok = True
        if session.plan_created_at:
            age_minutes = (timezone.now() - session.plan_created_at).total_seconds() / 60
            if age_minutes > AgentConfig.PLAN_EXPIRY_MINUTES:
                plan_age_ok = False
                logger.warning(
                    f"PLAN EXPIRED | Session: {current_session_id} | "
                    f"Age: {age_minutes:.1f} min > {AgentConfig.PLAN_EXPIRY_MINUTES} min limit. "
                    "Clearing plan state and routing to EXECUTE."
                )
                session.plan_state = None
                session.plan_created_at = None
                await sync_to_async(session.save)()

    if session.plan_state and (decision == "CONFIRM" or is_affirmative):
        try:
            logger.info(f"PLAN APPROVED: Executing strategic architecture for session {current_session_id}")
            answer = await asyncio.to_thread(
                reasoning_node.execute_plan,
                message=user_message,
                plan=session.plan_state,
                tenant_ids=resolved_tenant_ids,
                company_ids=resolved_company_ids
            )
            
            # Reset plan state after successful execution
            session.plan_state = None
            await sync_to_async(session.save)()
            
            plan_token_usage = reasoning_node.get_last_token_usage()
            exec_payload = {"token_usage": plan_token_usage} if (plan_token_usage and plan_token_usage.get("total_tokens", 0) > 0) else None
            await sync_to_async(session_manager.save_message)(current_session_id, "assistant", answer, payload=exec_payload)
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
            if _is_credit_balance_error(e):
                answer = get_user_facing_error_message(e)
                await sync_to_async(session_manager.save_message)(current_session_id, "assistant", answer)
                return make_chat_response(
                    answer,
                    "ERROR",
                    current_session_id,
                    session.title if session else "New Chat",
                    user_message
                )
            error_msg = str(e).lower()
            if any(k in error_msg for k in ["usage limits", "quota", "429", "overloaded", "529", "service unavailable", "temp"]):
                asyncio.create_task(
                    background_retry_executor(
                        session_id=current_session_id,
                        user_message=user_message,
                        chat_history=chat_history_from_db,
                        db_summary=db_summary,
                        mode="EXECUTE_PLAN",
                        plan=session.plan_state,
                        tenant_ids=resolved_tenant_ids,
                        company_ids=resolved_company_ids
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
            answer = get_user_facing_error_message(e)
            await sync_to_async(session_manager.save_message)(current_session_id, "assistant", answer)
            return make_chat_response(
                answer,
                "ERROR",
                current_session_id,
                session.title if session else "New Chat",
                user_message
            )

    # 2.2 Conversational Continuation Handling:
    # If the user gives an affirmative reply ("yes", "ok", "sure", "proceed") or router returned CONFIRM,
    # but there is NO pending plan in session: treat as a conversational follow-up/execution.
    if not session.plan_state and (decision == "CONFIRM" or is_affirmative):
        logger.info(f"ROUTER OVERRIDE | No active plan in session {current_session_id}. Converting CONFIRM/affirmative to EXECUTE for conversational continuation.")
        decision = "EXECUTE"

    # Fail-safe guard against accidental rejections on follow-up phrases, market research, or active sessions
    clean_words = (clean_user_message or user_message).strip().split()
    if decision == "REJECT":
        business_keywords = {
            # English
            "today", "yesterday", "year", "month", "quarter", "ytd", "week", "now", "company",
            "sales", "revenue", "profit", "margin", "cost", "cogs", "inventory", "stock", "customers",
            "clients", "partners", "receivables", "payables", "invoices", "orders", "top", "best", "total",
            "competitor", "competitors", "competition", "market", "industry", "area", "region", "benchmarks", "pricing", "share",
            # French
            "aujourd'hui", "hier", "annee", "année", "mois", "trimestre", "semaine", "acteurs", "detaille",
            "produit", "produits", "ventes", "recettes", "benefice", "bénéfice", "marge", "client", "deux",
            "clients", "fournisseurs", "factures", "commandes", "achats", "stock", "chiffre", "affaires",
            "concurrents", "concurrence", "marché",
            # Spanish
            "hoy", "ayer", "año", "mes", "trimestre", "semana", "ventas", "ingresos", "ganancias", "ambos",
            "clientes", "proveedores", "facturas", "pedidos", "compras", "inventario", "productos", "detalle",
            "competidores", "competencia", "mercado",
            # Arabic & Transliterated (including inflected pronouns attached to stems)
            "مبيعات", "مبيعاتها", "مبيعاتهم", "مبيعاتنا",
            "ارباح", "أرباح", "أرباحها", "أرباحهم",
            "ايراد", "إيراد", "ايراداتها",
            "عملاء", "عملائها",
            "موردين", "موردينها",
            "مخزون", "مخزونها",
            "فواتير", "فواتيرها",
            "منتجات", "منتجاتها",
            "تكاليف", "تكاليفها",
            "منافسين", "المنافسين", "السوق",
            "مشتريات", "مشترياتها",
            "مصروفات", "مصروفاتها",
            "mabi3at", "arba7", "omala"
        }
        clean_word_set = {w.lower().strip("!?.,;:'\"") for w in clean_words}
        # Override REJECT if the utterance contains explicit business keywords, timeframe adjustments, or web search is requested
        if bool(clean_word_set.intersection(business_keywords)) or (enable_web_search and len(clean_words) >= 2):
            logger.info(f"ROUTER OVERRIDE | Converting REJECT to EXECUTE for business/market prompt: '{clean_user_message}'")
            decision = "EXECUTE"

    if decision == "REJECT":
        french_words = {"les", "des", "est", "que", "pourquoi", "comment", "bonjour", "salut", "qui", "combien", "quels", "quelles", "quel", "quelle", "dans", "avec", "par", "pour", "sur", "donne", "moi", "affiche", "montre", "acteurs", "détaille"}
        spanish_words = {"hola", "que", "quien", "cuanto", "cuantos", "cual", "cuales", "como", "donde", "por", "para", "muestra", "dame", "ventas", "gracias", "ambos"}
        arabic_words = {"مرحبا", "سلام", "شكرا", "كيف", "ماذا", "من", "كم", "هل"}

        user_words_lower = set(_re.findall(r'\b\w+\b', clean_user_message.lower()))
        is_arabic_text = bool(_re.search(r'[\u0600-\u06FF]', clean_user_message))
        if user_words_lower.intersection(french_words) or (user_language and user_language.startswith("fr")):
            answer = "Désolé, je ne peux répondre qu'aux questions financières et commerciales liées à vos données Odoo."
        elif user_words_lower.intersection(spanish_words) or (user_language and user_language.startswith("es")):
            answer = "Lo siento, solo puedo responder a preguntas financieras y comerciales sobre sus datos de Odoo."
        elif user_words_lower.intersection(arabic_words) or is_arabic_text or (user_language and user_language.startswith("ar")):
            answer = "عذراً، يمكنني المساعدة فقط في الأسئلة المالية والتجارية المتعلقة ببيانات Odoo الخاصة بك."
        else:
            answer = "I'm sorry, I can only assist with business and financial questions related to your Odoo data."
        await sync_to_async(session_manager.save_message)(current_session_id, "assistant", answer, payload={"is_rejected": True})
        duration = (time.time() - request_start) * 1000
        logger.info(f"REQUEST REJECTED in {duration:.0f}ms")
        return {"answer": answer}
    
    # 2.3 Strict Fallback: Any non-REJECT, non-PLAN decision defaults to EXECUTE
    if decision != "PLAN":
        decision = "EXECUTE"

    # ── Defense 2: PLAN Gate ──────────────────────────────────────────────
    # Even if the router returned PLAN, only allow it if the user's message
    # contains explicit strategic planning language. Without this, a simple
    # "yes" that slips past Defense 1 would still reach create_plan().
    if decision == "PLAN":
        _PLAN_TRIGGER_KEYWORDS = {
            "roadmap", "strategic plan", "transformation", "multi-phase",
            "multi phase", "enterprise audit", "5 year", "five year",
            "long term", "long-term", "comprehensive audit", "full audit",
            "action plan", "implementation plan", "project plan",
            # Arabic
            "\u062e\u0637\u0629 \u0627\u0633\u062a\u0631\u0627\u062a\u064a\u062c\u064a\u0629", "\u062e\u0627\u0631\u0637\u0629 \u0637\u0631\u064a\u0642", "\u062e\u0637\u0629 \u0639\u0645\u0644",
            # French
            "feuille de route", "plan strategique", "plan strat\u00e9gique",
        }
        _plan_msg_lower = clean_user_message.lower()
        _has_plan_language = any(kw in _plan_msg_lower for kw in _PLAN_TRIGGER_KEYWORDS)
        if not _has_plan_language:
            logger.info(
                f"PLAN GATE | Router returned PLAN but no planning keywords found in message. "
                f"Converting to EXECUTE. | msg='{clean_user_message[:100]}'"
            )
            decision = "EXECUTE"

    # 3. Execution Path
    if decision == "EXECUTE":
        try:
            from datetime import date
            today_str = date.today().strftime("%Y-%m-%d")

            use_web_search = enable_web_search

            citations = None
            if use_web_search:
                from .web_search_agent import WebSearchAgent
                logger.info(f"WEB SEARCH ACTIVE for session {current_session_id}")

                def run_web_search():
                    agent = WebSearchAgent()
                    return agent.run(
                        message=user_message,
                        tenant_ids=resolved_tenant_ids,
                        company_ids=resolved_company_ids,
                        chat_history=chat_history_from_db,
                        memory_summary=db_summary,
                        language=user_language,
                    )

                try:
                    answer, citations = await asyncio.to_thread(run_web_search)
                except Exception as ws_err:
                    logger.warning(f"WebSearchAgent failed ({ws_err}). Falling back to standard business executor.")
                    def save_summary_to_db(summary_text: str):
                        session_manager.save_summary(current_session_id, summary_text)

                    def run_fast_path():
                        return fast_path_node.run(
                            message=clean_user_message or user_message,
                            tenant_ids=resolved_tenant_ids,
                            company_ids=resolved_company_ids,
                            chat_history=chat_history_from_db,
                            memory_summary=db_summary,
                            on_summary=save_summary_to_db,
                            session_id=current_session_id,
                            is_voice=is_voice_mode,
                            language=user_language,
                        )

                    answer = await asyncio.to_thread(run_fast_path)
            else:
                # Persist summary to DB when agent generates one
                def save_summary_to_db(summary_text: str):
                    session_manager.save_summary(current_session_id, summary_text)
                    logger.info(f"SUMMARY SAVED | Session: {current_session_id} | Length: {len(summary_text)} chars")

                def run_fast_path():
                    return fast_path_node.run(
                        message=clean_user_message or user_message,
                        tenant_ids=resolved_tenant_ids,
                        company_ids=resolved_company_ids,
                        chat_history=chat_history_from_db,
                        memory_summary=db_summary,
                        on_summary=save_summary_to_db,
                        attachments=req_data.attachments,
                        session_id=current_session_id,
                        is_voice=is_voice_mode,
                        language=user_language
                    )

                answer = await asyncio.to_thread(run_fast_path)

            message_payload = {"citations": citations} if citations else {}
            token_usage = fast_path_node.get_last_token_usage()
            if token_usage and token_usage.get("total_tokens", 0) > 0:
                message_payload["token_usage"] = token_usage
            await sync_to_async(session_manager.save_message)(
                current_session_id, "assistant", answer, payload=message_payload or None
            )
            duration = (time.time() - request_start) * 1000
            logger.info(f"EXECUTE COMPLETE in {duration:.0f}ms | Response: \"{answer[:80]}...\"")
            return make_chat_response(
                answer,
                "EXECUTE",
                current_session_id,
                session.title,
                user_message,
                citations=citations if citations else None
            )
        except Exception as e:
            log_error("chat_endpoint.EXECUTE", e)
            if _is_credit_balance_error(e):
                answer = get_user_facing_error_message(e)
                await sync_to_async(session_manager.save_message)(current_session_id, "assistant", answer)
                return make_chat_response(
                    answer,
                    "ERROR",
                    current_session_id,
                    session.title if session else "New Chat",
                    user_message
                )
            
            # Friendly message for API quota/limit/overloaded issues
            error_msg = str(e).lower()
            if any(k in error_msg for k in ["usage limits", "quota", "429", "overloaded", "529", "service unavailable", "temp"]):
                asyncio.create_task(
                    background_retry_executor(
                        session_id=current_session_id,
                        user_message=user_message,
                        chat_history=chat_history_from_db,
                        db_summary=db_summary,
                        mode="EXECUTE",
                        tenant_ids=resolved_tenant_ids,
                        company_ids=resolved_company_ids
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
                
            answer = get_user_facing_error_message(e)
            await sync_to_async(session_manager.save_message)(current_session_id, "assistant", answer)
            return make_chat_response(
                answer,
                "ERROR",
                current_session_id,
                session.title if session else "New Chat",
                user_message
            )
    
    # 4. Planning Path (High-Stakes Architecture)
    try:
        plan = await asyncio.to_thread(
            reasoning_node.create_plan,
            message=user_message,
            tenant_ids=resolved_tenant_ids,
            company_ids=resolved_company_ids
        )
        # Format the plan into a readable answer for the UI
        plan_objective = plan.get('strategic_objective') or plan.get('objective') or 'Strategic Analysis'
        plan_summary = f"### Strategic Architecture Plan\n\n"
        plan_summary += f"**Objective:** {plan_objective}\n\n"

        steps = plan.get('steps', [])
        phases = plan.get('phases', [])

        if steps:
            plan_summary += "**Execution Plan Steps:**\n"
            for s in steps:
                step_num = s.get('step', '')
                desc = s.get('description', '')
                tools = s.get('tools', [])
                tools_str = f" *(Tools: {', '.join(tools)})*" if tools else ""
                plan_summary += f"{step_num}. **Step {step_num}**: {desc}{tools_str}\n"
            plan_summary += "\n"
        elif phases:
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
        plan_token_usage = reasoning_node.get_last_token_usage()
        if plan_token_usage and plan_token_usage.get("total_tokens", 0) > 0:
            plan["token_usage"] = plan_token_usage
        await sync_to_async(session_manager.save_message)(current_session_id, "assistant", answer, message_type="plan", payload=plan)
        from django.utils import timezone
        session.plan_state = plan
        session.plan_created_at = timezone.now()
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
        if _is_credit_balance_error(e):
            answer = get_user_facing_error_message(e)
            await sync_to_async(session_manager.save_message)(current_session_id, "assistant", answer)
            return make_chat_response(
                answer,
                "ERROR",
                current_session_id,
                session.title if session else "New Chat",
                user_message
            )
        # Friendly message for API quota/limit/overloaded issues
        error_msg = str(e).lower()
        if any(k in error_msg for k in ["usage limits", "quota", "429", "overloaded", "529", "service unavailable", "temp"]):
            asyncio.create_task(
                background_retry_executor(
                    session_id=current_session_id,
                    user_message=user_message,
                    chat_history=chat_history_from_db,
                    db_summary=db_summary,
                    mode="PLAN",
                    tenant_ids=resolved_tenant_ids,
                    company_ids=resolved_company_ids
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
            
        answer = get_user_facing_error_message(e)
        await sync_to_async(session_manager.save_message)(current_session_id, "assistant", answer)
        return make_chat_response(
            answer,
            "ERROR",
            current_session_id,
            session.title if session else "New Chat",
            user_message
        )


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
    from .report_classifier import ReportTypeClassifier
    raw_type = body.get("report_type") or body.get("type")
    prompt_text = body.get("prompt") or body.get("message") or ""
    report_type = ReportTypeClassifier.classify(
        prompt=prompt_text,
        custom_content=body.get("custom_content") or "",
        raw_type=raw_type,
    )
    report_data = body.get("report_data")
    data = body.get("data", {})

    lines = []
    if body.get("custom_content"):
        custom_content = body["custom_content"]
    else:
        if report_type in ("analysis", "health", "executive", "general"):
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

        elif report_type in ("forecast", "proforma"):
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

        elif report_type in ("audit", "accounting"):
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
        else:
            if data.get("title"):
                lines.append(f"## {data['title']}\n")
            if data.get("summary"):
                lines.append(f"### Summary\n{data['summary']}\n")

        custom_content = "\n".join(lines)
    logo_path = body.get("logo_path")

    try:
        from .tools_refactored.reporting_v2 import generate_report_tool
        result = await sync_to_async(generate_report_tool)(
            tenant_ids=resolved_tenant_ids,
            company_ids=resolved_company_ids,
            custom_content=custom_content,
            report_type=report_type,
            report_data=report_data,
            logo_path=logo_path,
            base_currency=body.get("base_currency"),
            start_date=body.get("start_date") or body.get("from_date"),
            end_date=body.get("end_date") or body.get("to_date"),
            reporting_period=body.get("reporting_period"),
            comparison_label=body.get("comparison_label"),
            prompt=body.get("prompt") or body.get("message") or "",
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
        "Inventory Velocity": "inventory_dashboard_alerts, inventory_efficiency",
        "Operational Costs": "calculate_pnl, expense_breakdown",
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
            tenant_ids=resolved_tenant_ids,
            company_ids=resolved_company_ids,
            chat_history=[],
            memory_summary=""
        )
        structured = _extract_json_block(answer)
        if not structured:
            raise HTTPException(status_code=422, detail="AI did not return structured data. Please retry.")
        analysis_token_usage = fast_path_node.get_last_token_usage()
        if analysis_token_usage and analysis_token_usage.get("total_tokens", 0) > 0:
            structured["token_usage"] = analysis_token_usage
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
        answer = await asyncio.to_thread(
            fast_path_node.run,
            message=prompt,
            tenant_ids=resolved_tenant_ids,
            company_ids=resolved_company_ids,
            chat_history=[],
            memory_summary=""
        )
        structured = _extract_json_block(answer)
        if not structured:
            raise HTTPException(status_code=422, detail="AI did not return structured data. Please retry.")
        forecast_token_usage = fast_path_node.get_last_token_usage()
        if forecast_token_usage and forecast_token_usage.get("total_tokens", 0) > 0:
            structured["token_usage"] = forecast_token_usage
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
        answer = await asyncio.to_thread(
            fast_path_node.run,
            message=prompt,
            tenant_ids=resolved_tenant_ids,
            company_ids=resolved_company_ids,
            chat_history=[],
            memory_summary=""
        )
        structured = _extract_json_block(answer)
        if not structured:
            raise HTTPException(status_code=422, detail="AI did not return structured data. Please retry.")
        audit_token_usage = fast_path_node.get_last_token_usage()
        if audit_token_usage and audit_token_usage.get("total_tokens", 0) > 0:
            structured["token_usage"] = audit_token_usage
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
    from asgiref.sync import sync_to_async
    def _fetch():
        return list(session_manager.get_messages(session_id))
    messages = await sync_to_async(_fetch)()
    return {
        "messages": [
            {
                "role": m.role,
                "content": m.content,
                "message_type": m.message_type,
                "payload": m.payload,
                "attachments": (m.payload.get("attachments") if m.payload and isinstance(m.payload, dict) else []) or [],
                "citations": (m.payload.get("citations") if m.payload and isinstance(m.payload, dict) else None),
                "created_at": m.created_at
            }
            for m in messages
        ]
    }

@router.get("/sessions/{session_id}", dependencies=[_use_agent])
async def get_session_details(session_id: str):
    """Retrieve details and messages for a specific session."""
    from asgiref.sync import sync_to_async
    def _fetch():
        sess = session_manager.get_or_create_session(session_id, "default")
        msgs = list(session_manager.get_messages(session_id))
        return sess, msgs
    session, messages = await sync_to_async(_fetch)()
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
                "attachments": (m.payload.get("attachments") if m.payload and isinstance(m.payload, dict) else []) or [],
                "citations": (m.payload.get("citations") if m.payload and isinstance(m.payload, dict) else None),
                "created_at": m.created_at
            }
            for m in messages
        ]
    }

@router.delete("/sessions/{session_id}", dependencies=[_use_agent])
async def delete_session(session_id: str):
    """Delete a chat session."""
    from asgiref.sync import sync_to_async
    await sync_to_async(session_manager.delete_session)(session_id)
    log_session_event("DELETED", session_id, "User requested deletion")
    return {"status": "deleted"}

@router.post("/approve_plan", dependencies=[_use_agent])
async def approve_plan(request: ChatRequest, plan: dict):
    user_message = request.message or request.content or request.prompt or "Plan execution"
    logger.info(f"PLAN APPROVED | Session: {request.session_id}")
    primary_tenant_id, resolved_tenant_ids, primary_company_id, resolved_company_ids = extract_context_ids(request)
    try:
        answer = await asyncio.to_thread(
            reasoning_node.execute_plan,
            message=user_message,
            plan=plan,
            tenant_ids=resolved_tenant_ids,
            company_ids=resolved_company_ids
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
                    user_message=user_message,
                    chat_history=[],
                    db_summary="",
                    mode="EXECUTE_PLAN",
                    plan=plan,
                    tenant_ids=resolved_tenant_ids,
                    company_ids=resolved_company_ids
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
        answer = get_user_facing_error_message(e)
        session_manager.save_message(request.session_id, "assistant", answer)
        return make_chat_response(
            answer,
            "ERROR",
            request.session_id,
            "Plan Approved",
            user_message,
            status="ERROR"
        )


@router.get("/reports/{filename}", tags=["Agent Reports"])
async def download_ai_report(filename: str):
    """Download an AI-generated PDF report with browser preview support."""
    from fastapi.responses import FileResponse
    from django.conf import settings
    import os
    import urllib.parse

    # 1. Decode URL encoding (e.g. %60 for backtick) and clean up filename
    cleaned_filename = urllib.parse.unquote(filename).strip("`'\" \t\n\r")
    
    # 2. Prevent path traversal attacks
    if "/" in cleaned_filename or "\\" in cleaned_filename or ".." in cleaned_filename:
        raise HTTPException(status_code=400, detail="Invalid report filename")

    # 3. Check reports directory from Django settings or fallback
    reports_dir = getattr(settings, "REPORTS_DIR", "reports")
    report_path = os.path.join(reports_dir, cleaned_filename)

    if not os.path.exists(report_path):
        # Fallback to local reports/ directory
        report_path = os.path.join("reports", cleaned_filename)
        if not os.path.exists(report_path):
            raise HTTPException(status_code=404, detail="Report not found")

    return FileResponse(
        path=report_path,
        filename=cleaned_filename,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'inline; filename="{cleaned_filename}"',
            "Cache-Control": "private, max-age=3600",
        }
    )