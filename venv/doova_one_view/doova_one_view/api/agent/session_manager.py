# api/agent/session_manager.py

from typing import Optional, Dict, Any, List
from langchain_anthropic import ChatAnthropic
from .config import AgentConfig
from .prompts import SESSION_TITLE_PROMPT
from .logger import logger
from odoo_app.models.agent import ChatSession, ChatMessage
from django.db import transaction

class SessionManager:
    def __init__(self):
        self.llm = ChatAnthropic(
            model=AgentConfig.ROUTER_MODEL,
            anthropic_api_key=AgentConfig.ANTHROPIC_API_KEY,
            model_kwargs={
                "extra_headers": {"anthropic-beta": "prompt-caching-2024-07-31"}
            }
        )
        self.title_prompt = SESSION_TITLE_PROMPT

    def generate_title(self, first_message: str) -> str:
        clean_message = (first_message or "").strip()
        if not clean_message:
            return "New Conversation"

        # Fast-path: Common short greetings don't need an LLM call
        common_greetings = {"hello", "hi", "hey", "good morning", "good afternoon", "good evening", "greetings", "test", "help"}
        if clean_message.lower().strip("!.,? ") in common_greetings or len(clean_message) <= 3:
            return "New Conversation"

        try:
            chain = self.title_prompt | self.llm
            response = chain.invoke({"message": clean_message})
            raw = str(response.content).strip().strip('"').strip("'")
            # If the model output multiple lines, take only the first line
            first_line = raw.split("\n")[0].strip().strip('"').strip("'")
            if first_line.lower().startswith("title:"):
                first_line = first_line[6:].strip()
            
            # If the model still returned a chatty explanation instead of a title
            if len(first_line) > 60 or "provide" in first_line.lower() or "ready to" in first_line.lower():
                if len(clean_message) <= 40:
                    return clean_message
                return clean_message[:37] + "..."
                
            return first_line or "New Conversation"
        except Exception as e:
            from .logger import log_error
            log_error("SessionManager.generate_title", e)
            if len(clean_message) > 40:
                return clean_message[:37] + "..."
            return clean_message or "New Conversation"

    def get_or_create_session(self, session_id: str, tenant_id: str, first_message: str = None) -> ChatSession:
        session, created = ChatSession.objects.get_or_create(session_id=session_id)
        if created:
            session.tenant_id = str(tenant_id)[:255] if tenant_id else None
            if first_message:
                raw_title = self.generate_title(first_message)
                session.title = (raw_title or "New Chat")[:250]
            session.save()
        return session

    def save_message(
        self,
        session_id: str,
        role: str,
        content: str,
        message_type: str = "text",
        payload: dict = None,
        token_usage: dict = None
    ) -> ChatMessage:
        session = ChatSession.objects.get(session_id=session_id)
        final_payload = dict(payload) if isinstance(payload, dict) else ({} if payload is None else payload)
        if token_usage:
            if isinstance(final_payload, dict):
                final_payload["token_usage"] = token_usage
            else:
                final_payload = {"raw_payload": final_payload, "token_usage": token_usage}

        msg = ChatMessage.objects.create(
            session=session,
            role=role,
            content=content,
            message_type=message_type,
            payload=final_payload if final_payload else None
        )
        session.last_message = content
        session.turn_count += 1
        session.save()
        return msg

    def save_summary(self, session_id: str, summary_text: str):
        """Persist a generated memory summary to the session record."""
        ChatSession.objects.filter(session_id=session_id).update(summary=summary_text)

    def save_active_date_window(self, session_id: str, date_window: dict):
        """Persist the active date window (start_date, end_date, label) to the session record."""
        ChatSession.objects.filter(session_id=session_id).update(active_date_window=date_window)

    def get_active_date_window(self, session_id: str) -> Optional[dict]:
        """Retrieve the active date window from the session record."""
        session = ChatSession.objects.filter(session_id=session_id).first()
        return session.active_date_window if session else None

    def get_sessions(self, tenant_id: str = None):
        if tenant_id:
            return ChatSession.objects.filter(tenant_id=tenant_id)
        return ChatSession.objects.all()

    def get_messages(self, session_id: str):
        return ChatMessage.objects.filter(session_id=session_id)

    def delete_session(self, session_id: str):
        # 1. Clean up uploaded attachments on disk and metadata in stored_files table
        try:
            from .attachment_processor import cleanup_session_attachments
            cleanup_session_attachments(session_id)
        except Exception as e:
            logger.warning(f"Error cleaning up session attachments for {session_id}: {e}")

        # 2. Delete ChatMessages and ChatSession database records
        ChatSession.objects.filter(session_id=session_id).delete()

    def reset_session_memory(self, session_id: str):
        """Reset a session's turn count, memory summary, and messages while keeping session record."""
        ChatMessage.objects.filter(session__session_id=session_id).delete()
        ChatSession.objects.filter(session_id=session_id).update(
            turn_count=0,
            summary="",
            plan_state=None,
            plan_created_at=None,
            last_message=""
        )
