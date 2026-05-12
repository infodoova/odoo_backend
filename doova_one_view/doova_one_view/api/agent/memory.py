"""
Persistent session memory for the chatbot.
Stores sessions in data/sessions.json and handles title generation and frontend mapping.
"""

import json
from pathlib import Path
from typing import Dict, Any, List, Optional
from datetime import datetime

from .config import AgentConfig
from .summarizer import MemorySummarizer


class SessionMemory:
    """
    Persistent session memory for the chatbot.
    Stores chat history, auto-generates titles, and maps to frontend format.
    """

    def __init__(self, storage_path: str = "data/sessions.json"):
        self.storage_path = Path(storage_path)
        self.storage_path.parent.mkdir(parents=True, exist_ok=True)
        self.sessions: Dict[str, Dict[str, Any]] = self._load_sessions()
        self.summarizer = MemorySummarizer()
        self._upgrade_existing_sessions()

    # ─────────────────────────────
    # TIME / TITLE HELPERS
    # ─────────────────────────────
    def _now(self) -> str:
        return datetime.now().isoformat(timespec="seconds")

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

        replacements = {
            "revnue": "revenue", "revenu": "revenue", "revanue": "revenue",
            "sale summery": "sales summary", "sales summery": "sales summary",
            "inventry": "inventory", "inventroy": "inventory", "stok": "stock",
            "grph": "graph", "grahp": "graph", "custmer": "customer",
            "custmers": "customers", "costumer": "customer", "costumers": "customers",
            "prodcut": "product", "prodcuts": "products",
        }
        for wrong, correct in replacements.items():
            lowered = lowered.replace(wrong, correct)

        # Business-intent titles
        if any(x in lowered for x in ["highest sales revenue", "highest revenue company"]): return "Top Revenue Company"
        if any(x in lowered for x in ["orders does each company", "orders by company"]): return "Sales Orders by Company"
        if any(x in lowered for x in ["top customers by total sales", "customer sales ranking"]): return "Top Customers by Sales"
        if any(x in lowered for x in ["products were sold", "products sold in"]): return "Products Sold"
        if any(x in lowered for x in ["stock but no sales", "stock without sales"]): return "Stock Without Sales"
        if any(x in lowered for x in ["why did sales drop", "sales drop", "sales decline"]): return "Sales Drop Analysis"
        if "accounting revenue" in lowered and "sales revenue" in lowered: return "Revenue Reconciliation"
        if any(x in lowered for x in ["compare sales", "compare revenue"]): return "Sales Comparison"
        if any(x in lowered for x in ["revenue graph", "sales chart", "visualize sales"]): return "Revenue Graph"
        if any(x in lowered for x in ["business report", "financial report", "pdf report"]): return "Business Report"
        if any(x in lowered for x in ["inventory report", "pdf for inventory"]): return "Inventory Report"
        if any(x in lowered for x in ["sales report", "sales pdf"]): return "Sales Report"
        if any(x in lowered for x in ["reorder recommendation", "what should we reorder"]): return "Reorder Recommendations"
        if any(x in lowered for x in ["lots will expire", "expiring lots", "near expiry"]): return "Expiring Lots"
        if any(x in lowered for x in ["low stock", "inventory alerts", "below threshold"]): return "Inventory Alerts"
        if any(x in lowered for x in ["inventory efficiency", "inventory turnover", "days inventory"]): return "Inventory Efficiency"
        if any(x in lowered for x in ["top products", "best selling products"]): return "Top Products"
        if any(x in lowered for x in ["top customers", "best customers", "top clients"]): return "Top Customers"
        if any(x in lowered for x in ["sales summary", "how much did we sell", "total sales"]): return "Sales Summary"
        
        if "accounting revenue" in lowered: return "Accounting Revenue"
        if "revenue" in lowered: return "Revenue"
        if "receivable" in lowered: return "Receivables Analysis"
        if "purchase" in lowered: return "Purchase Summary"

        prefixes = ["can you please ", "can you ", "could you please ", "could you ", "please ", "i want ", "i need ", "show me ", "tell me ", "give me ", "what is ", "what are "]
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
    # FILE STORAGE
    # ─────────────────────────────
    def _load_sessions(self) -> Dict[str, Dict[str, Any]]:
        if not self.storage_path.exists(): return {}
        try:
            with open(self.storage_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            return data if isinstance(data, dict) else {}
        except: return {}

    def _save_sessions(self):
        with open(self.storage_path, "w", encoding="utf-8") as f:
            json.dump(self.sessions, f, indent=2, ensure_ascii=False)

    def _upgrade_existing_sessions(self):
        changed = False
        now = self._now()
        for session_id, session in self.sessions.items():
            if "title" not in session:
                raw = session.get("raw_turns", [])
                session["title"] = self._generate_title_from_first_prompt(raw[0].get("user", "") if raw else "")
                changed = True
            if "created_at" not in session: session["created_at"] = now; changed = True
            if "updated_at" not in session: session["updated_at"] = now; changed = True
            if "last_message" not in session:
                raw = session.get("raw_turns", [])
                session["last_message"] = self._make_preview(raw[-1].get("user", "") if raw else "")
                changed = True
            if "turn_count" not in session: session["turn_count"] = len(session.get("raw_turns", [])); changed = True
            if "summary" not in session: session["summary"] = ""; changed = True
            if "raw_turns" not in session: session["raw_turns"] = []; changed = True
            if "plan_state" not in session: session["plan_state"] = None; changed = True
        if changed: self._save_sessions()

    # ─────────────────────────────
    # SESSION MANAGEMENT
    # ─────────────────────────────
    def get_or_create(self, session_id: str) -> Dict[str, Any]:
        if session_id not in self.sessions:
            now = self._now()
            self.sessions[session_id] = {
                "title": "New Chat", "summary": "", "raw_turns": [], "plan_state": None,
                "turn_count": 0, "created_at": now, "updated_at": now, "last_message": "",
            }
            self._save_sessions()
        return self.sessions[session_id]

    def get_summary(self, session_id: str) -> str:
        return self.get_or_create(session_id).get("summary", "")

    def add_turn(self, session_id: str, user_message: str, assistant_message: str, assistant_type: str = "text", assistant_payload: Optional[Dict[str, Any]] = None):
        session = self.get_or_create(session_id)
        now = self._now()
        if session.get("turn_count", 0) == 0 or session.get("title") in ["", "New Chat", None]:
            session["title"] = self._generate_title_from_first_prompt(user_message)
        turn = {
            "user": user_message, "assistant": assistant_message, "created_at": now,
            "assistant_type": assistant_type or "text", "assistant_payload": assistant_payload,
        }
        session["raw_turns"].append(turn)
        session["turn_count"] = session.get("turn_count", 0) + 1
        session["updated_at"] = now
        session["last_message"] = self._make_preview(user_message)
        if session["turn_count"] % AgentConfig.SUMMARIZE_EVERY_N == 0:
            self._summarize_session(session_id)
        self._save_sessions()

    def _summarize_session(self, session_id: str):
        session = self.get_or_create(session_id)
        raw = session.get("raw_turns", [])
        if not raw: return
        try:
            session["summary"] = self.summarizer.summarize(current_summary=session.get("summary", ""), recent_turns=raw)
        except Exception as e: print(f"⚠️ Memory summarization failed: {e}")

    def set_plan(self, session_id: str, plan: Dict[str, Any]):
        session = self.get_or_create(session_id); session["plan_state"] = plan; session["updated_at"] = self._now(); self._save_sessions()

    def get_plan(self, session_id: str) -> Optional[Dict[str, Any]]:
        return self.get_or_create(session_id).get("plan_state")

    def clear_plan(self, session_id: str):
        session = self.get_or_create(session_id); session["plan_state"] = None; session["updated_at"] = self._now(); self._save_sessions()

    def list_sessions(self) -> List[Dict[str, Any]]:
        results = []
        for sid, s in self.sessions.items():
            results.append({
                "id": sid, "session_id": sid, "sessionId": sid, "title": s.get("title", "New Chat"),
                "turn_count": s.get("turn_count", 0), "summary": s.get("summary", ""),
                "last_message": s.get("last_message", ""), "created_at": s.get("created_at"),
                "updated_at": s.get("updated_at"), "has_pending_plan": s.get("plan_state") is not None,
            })
        results.sort(key=lambda x: x.get("updated_at") or "", reverse=True)
        return results

    def get_session(self, session_id: str) -> Optional[Dict[str, Any]]:
        session = self.sessions.get(session_id)
        if not session: return None
        messages = []
        msg_id = 1
        for turn in session.get("raw_turns", []):
            ts = turn.get("created_at")
            if turn.get("user"):
                messages.append({"id": msg_id, "content": turn["user"], "role": "user", "created_at": ts, "type": "text", "payload": None})
                msg_id += 1
            if turn.get("assistant"):
                p = turn.get("assistant_payload")
                messages.append({
                    "id": msg_id, "content": turn["assistant"], "role": "assistant", "created_at": ts,
                    "type": turn.get("assistant_type") or "text", "payload": p,
                    "chart": p.get("chart") if isinstance(p, dict) else None,
                    "data": p.get("data", []) if isinstance(p, dict) else [],
                    "graphData": p, "chartData": p,
                })
                msg_id += 1
        if not messages and session.get("summary"):
            messages.append({"id": 1, "content": session["summary"], "role": "assistant", "created_at": session["updated_at"], "type": "text", "payload": None})
        return {
            "session_id": session_id, "sessionId": session_id, "title": session.get("title", "New Chat"),
            "summary": session.get("summary", ""), "raw_turns": session.get("raw_turns", []),
            "history": session.get("raw_turns", []), "messages": messages,
            "plan_state": session.get("plan_state"), "turn_count": session.get("turn_count", 0),
            "last_message": session.get("last_message", ""), "created_at": session.get("created_at"),
            "updated_at": session.get("updated_at"),
        }

    def delete_session(self, session_id: str) -> bool:
        if session_id in self.sessions:
            del self.sessions[session_id]; self._save_sessions(); return True
        return False
