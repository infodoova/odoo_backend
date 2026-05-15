# api/agent/session_manager.py

from langchain_anthropic import ChatAnthropic
from .config import AgentConfig
from .prompts import SESSION_TITLE_PROMPT
from odoo_app.models.agent import ChatSession, ChatMessage
from django.db import transaction

class SessionManager:
    def __init__(self):
        self.llm = ChatAnthropic(
            model=AgentConfig.ROUTER_MODEL,
            anthropic_api_key=AgentConfig.ANTHROPIC_API_KEY
        )
        self.title_prompt = SESSION_TITLE_PROMPT

    def generate_title(self, first_message: str) -> str:
        chain = self.title_prompt | self.llm
        response = chain.invoke({"message": first_message})
        return response.content.strip().strip('"')

    def get_or_create_session(self, session_id: str, tenant_id: str, first_message: str = None) -> ChatSession:
        session, created = ChatSession.objects.get_or_create(session_id=session_id)
        if created:
            session.tenant_id = tenant_id
            if first_message:
                session.title = self.generate_title(first_message)
            session.save()
        return session

    def save_message(self, session_id: str, role: str, content: str, message_type: str = "text", payload: dict = None):
        session = ChatSession.objects.get(session_id=session_id)
        ChatMessage.objects.create(
            session=session,
            role=role,
            content=content,
            message_type=message_type,
            payload=payload
        )
        session.last_message = content
        session.turn_count += 1
        session.save()

    def save_summary(self, session_id: str, summary_text: str):
        """Persist a generated memory summary to the session record."""
        ChatSession.objects.filter(session_id=session_id).update(summary=summary_text)

    def get_sessions(self, tenant_id: str = None):
        if tenant_id:
            return ChatSession.objects.filter(tenant_id=tenant_id)
        return ChatSession.objects.all()

    def get_messages(self, session_id: str):
        return ChatMessage.objects.filter(session_id=session_id)

    def delete_session(self, session_id: str):
        ChatSession.objects.filter(session_id=session_id).delete()
