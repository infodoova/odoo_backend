"""
Persistent session memory for the chatbot.
Stores sessions in PostgreSQL via Django models.
"""

from typing import Dict, Any, List, Optional
from datetime import datetime

from .config import AgentConfig
from .summarizer import MemorySummarizer
from odoo_app.models.agent import ChatSession, ChatMessage


class SessionMemory:
    """
    Persistent session memory for the chatbot using PostgreSQL.
    Stores chat history, auto-generates titles, and handles state.
    """

    def __init__(self):
        self.summarizer = MemorySummarizer()

    # ─────────────────────────────
    # TIME / TITLE HELPERS
    # ─────────────────────────────
    def _generate_title_from_first_prompt(self, user_message: str) -> str:
        if not user_message:
            return "New Chat"

        cleaned = " ".join(str(user_message).strip().split())
        if "----- BEGIN ATTACHED FILE CONTENT -----" in cleaned:
            cleaned = cleaned.split("----- BEGIN ATTACHED FILE CONTENT -----")[0].strip()
        if "[Selected context:" in cleaned:
            parts = cleaned.split("\n", 1)
            if len(parts) > 1: cleaned = parts[1].strip()

        cleaned = cleaned.strip(" ?!.,;:")
        lowered = cleaned.lower()

        # Business-intent titles (same logic as before)
        if any(x in lowered for x in ["highest sales revenue", "highest revenue company"]): return "Top Revenue Company"
        if any(x in lowered for x in ["orders by company", "sales orders by company"]): return "Sales Orders by Company"
        if any(x in lowered for x in ["top customers by total sales", "highest sales customers"]): return "Top Customers by Sales"
        if any(x in lowered for x in ["products sold in", "sold products in"]): return "Products Sold"
        if any(x in lowered for x in ["stock but no sales", "stock without sales"]): return "Stock Without Sales"
        if any(x in lowered for x in ["why did sales drop", "sales decline"]): return "Sales Drop Analysis"
        if any(x in lowered for x in ["compare sales", "compare revenue"]): return "Sales Comparison"
        if any(x in lowered for x in ["revenue graph", "sales chart", "monthly sales trend"]): return "Revenue Graph"
        if any(x in lowered for x in ["business report", "financial report", "pdf report"]): return "Business Report"
        if any(x in lowered for x in ["inventory report", "pdf for inventory"]): return "Inventory Report"
        if any(x in lowered for x in ["sales report", "pdf for sales"]): return "Sales Report"
        if any(x in lowered for x in ["reorder recommendation", "what should we reorder"]): return "Reorder Recommendations"
        if any(x in lowered for x in ["lots will expire", "expiring lots", "near expiry"]): return "Expiring Lots"
        if any(x in lowered for x in ["low stock", "inventory alerts"]): return "Inventory Alerts"
        if any(x in lowered for x in ["inventory efficiency", "inventory turnover"]): return "Inventory Efficiency"
        if any(x in lowered for x in ["top products", "best selling products"]): return "Top Products"
        if any(x in lowered for x in ["top customers", "best customers"]): return "Top Customers"
        if any(x in lowered for x in ["sales summary", "total sales"]): return "Sales Summary"
        if "revenue" in lowered: return "Revenue"
        if "receivable" in lowered: return "Receivables Analysis"
        if "purchase" in lowered: return "Purchase Summary"

        prefixes = ["can you please ", "can you ", "could you ", "please ", "i want ", "i need ", "show me ", "tell me ", "give me ", "what is ", "what are "]
        fallback = cleaned
        for prefix in prefixes:
            if fallback.lower().startswith(prefix):
                fallback = fallback[len(prefix):].strip()
                break

        fallback = fallback.strip(" ?!.,;:")
        if not fallback or fallback.lower() in ["what is", "what are", "show me"]: return "New Chat"
        
        words = fallback.split()
        title = " ".join(words[:8]).strip()
        if not title: return "New Chat"
        title = title[0].upper() + title[1:]
        return title[:60] + "..." if len(title) > 60 else title

    def _make_preview(self, text: str, max_len: int = 120) -> str:
        if not text: return ""
        preview = " ".join(str(text).strip().split())
        return preview[: max_len - 3].rstrip() + "..." if len(preview) > max_len else preview

    # ─────────────────────────────
    # SESSION MANAGEMENT
    # ─────────────────────────────
    def get_or_create(self, session_id: str) -> ChatSession:
        session, created = ChatSession.objects.get_or_create(session_id=session_id)
        return session

    def get_summary(self, session_id: str) -> str:
        session = self.get_or_create(session_id)
        return session.summary

    def add_turn(self, session_id: str, user_message: str, assistant_message: str, assistant_type: str = "text", assistant_payload: Optional[Dict[str, Any]] = None):
        session = self.get_or_create(session_id)
        
        # Auto-title for new chats
        if session.turn_count == 0 or session.title in ["", "New Chat", None]:
            session.title = self._generate_title_from_first_prompt(user_message)
        
        # Save user message
        ChatMessage.objects.create(
            session=session,
            role="user",
            content=user_message,
            message_type="text"
        )
        
        # Save assistant message
        ChatMessage.objects.create(
            session=session,
            role="assistant",
            content=assistant_message,
            message_type=assistant_type or "text",
            payload=assistant_payload
        )
        
        # Update session metadata
        session.turn_count += 1
        session.last_message = self._make_preview(user_message)
        session.save()
        
        # Summarize periodically
        if session.turn_count % AgentConfig.SUMMARIZE_EVERY_N == 0:
            self._summarize_session(session_id)

    def _summarize_session(self, session_id: str):
        session = self.get_or_create(session_id)
        messages = session.messages.all().order_by('created_at')
        if not messages.exists(): return
        
        # Map DB messages to the format summarizer expects
        recent_turns = []
        user_msg = ""
        for msg in messages:
            if msg.role == "user":
                user_msg = msg.content
            elif msg.role == "assistant":
                recent_turns.append({"user": user_msg, "assistant": msg.content})
                user_msg = ""

        try:
            session.summary = self.summarizer.summarize(
                current_summary=session.summary, 
                recent_turns=recent_turns
            )
            session.save()
        except Exception as e:
            print(f"Memory summarization failed: {e}")

    def set_plan(self, session_id: str, plan: Dict[str, Any]):
        session = self.get_or_create(session_id)
        session.plan_state = plan
        session.save()

    def get_plan(self, session_id: str) -> Optional[Dict[str, Any]]:
        session = self.get_or_create(session_id)
        return session.plan_state

    def clear_plan(self, session_id: str):
        session = self.get_or_create(session_id)
        session.plan_state = None
        session.save()

    def list_sessions(self) -> List[Dict[str, Any]]:
        sessions = ChatSession.objects.all().order_by('-updated_at')
        results = []
        for s in sessions:
            results.append({
                "id": s.session_id, 
                "session_id": s.session_id, 
                "sessionId": s.session_id, 
                "title": s.title,
                "turn_count": s.turn_count, 
                "summary": s.summary,
                "last_message": s.last_message, 
                "created_at": s.created_at.isoformat(),
                "updated_at": s.updated_at.isoformat(), 
                "has_pending_plan": s.plan_state is not None,
            })
        return results

    def get_session(self, session_id: str) -> Optional[Dict[str, Any]]:
        try:
            session = ChatSession.objects.get(session_id=session_id)
        except ChatSession.DoesNotExist:
            return None
            
        messages = []
        for msg in session.messages.all().order_by('created_at'):
            m = {
                "id": msg.id, 
                "content": msg.content, 
                "role": msg.role, 
                "created_at": msg.created_at.isoformat(), 
                "type": msg.message_type, 
                "payload": msg.payload
            }
            # Add extra fields for charts if present in payload
            if msg.payload and isinstance(msg.payload, dict):
                m["chart"] = msg.payload.get("chart")
                m["data"] = msg.payload.get("data", [])
                m["graphData"] = msg.payload
                m["chartData"] = msg.payload
            messages.append(m)
            
        if not messages and session.summary:
            messages.append({
                "id": 0, 
                "content": session.summary, 
                "role": "assistant", 
                "created_at": session.updated_at.isoformat(), 
                "type": "text", 
                "payload": None
            })
            
        return {
            "session_id": session_id, 
            "sessionId": session_id, 
            "title": session.title,
            "summary": session.summary, 
            "messages": messages,
            "plan_state": session.plan_state, 
            "turn_count": session.turn_count,
            "last_message": session.last_message, 
            "created_at": session.created_at.isoformat(),
            "updated_at": session.updated_at.isoformat(),
        }

    def delete_session(self, session_id: str) -> bool:
        try:
            session = ChatSession.objects.get(session_id=session_id)
            session.delete()
            return True
        except ChatSession.DoesNotExist:
            return False
