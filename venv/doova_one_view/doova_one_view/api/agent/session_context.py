# doova_one_view/api/agent/session_context.py
"""
Thread-safe session context tracking for active reporting date windows.

Allows tool executions and agent prompts to seamlessly share and inherit
the active date window across multi-turn conversational follow-ups.
"""

from contextvars import ContextVar
from datetime import datetime
from typing import Optional, Dict, Any

# ContextVar storage for current thread/async task
_current_session_id: ContextVar[Optional[str]] = ContextVar("current_session_id", default=None)
_current_active_date_window: ContextVar[Optional[Dict[str, Any]]] = ContextVar("current_active_date_window", default=None)

# Process-level session store for cross-thread sync (e.g. LangChain ThreadPoolExecutor)
_session_windows: Dict[str, Dict[str, Any]] = {}


def set_session_context(session_id: Optional[str], date_window: Optional[Dict[str, Any]] = None):
    """
    Initializes the session context for the current async/sync task execution.
    """
    _current_session_id.set(session_id)
    resolved_window = date_window
    if session_id:
        if date_window is not None:
            _session_windows[session_id] = date_window
        elif session_id in _session_windows:
            resolved_window = _session_windows[session_id]
        else:
            try:
                from odoo_app.models.agent import ChatSession
                sess = ChatSession.objects.filter(session_id=session_id).first()
                if sess and sess.active_date_window:
                    resolved_window = sess.active_date_window
                    _session_windows[session_id] = resolved_window
            except Exception:
                pass

    _current_active_date_window.set(resolved_window)


def get_current_session_id() -> Optional[str]:
    """Returns the session_id for the active request execution."""
    return _current_session_id.get()


def get_active_date_window(session_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """
    Returns the active date window dictionary e.g.:
    {"start_date": "2026-07-01", "end_date": "2026-09-30", "label": "Jul 01, 2026 – Sep 30, 2026 (Q3 2026)"}
    """
    sid = session_id or _current_session_id.get()
    if sid and sid in _session_windows:
        return _session_windows[sid]
    return _current_active_date_window.get()


def update_active_date_window(start_date: str, end_date: str, label: Optional[str] = None):
    """
    Updates the active date window in both ContextVar and _session_windows store,
    and persists to ChatSession in PostgreSQL.
    """
    if not start_date or not end_date:
        return

    window = {
        "start_date": str(start_date).strip(),
        "end_date": str(end_date).strip(),
        "label": (label or f"{start_date} – {end_date}").strip(),
        "updated_at": datetime.now().isoformat(),
    }
    _current_active_date_window.set(window)

    sid = _current_session_id.get()
    if sid:
        _session_windows[sid] = window
        try:
            from odoo_app.models.agent import ChatSession
            ChatSession.objects.filter(session_id=sid).update(active_date_window=window)
        except Exception:
            pass
