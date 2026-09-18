# doova_one_view/api/agent/session_context.py
"""
Thread-safe session context tracking for active reporting date windows,
tenant IDs, and company IDs.

Allows tool executions and agent prompts to seamlessly share and inherit
the active scope (date, tenant, company) across multi-turn conversational
follow-ups.
"""

from contextvars import ContextVar
from datetime import datetime
from typing import Optional, Dict, Any, List

# ── ContextVar storage for current thread/async task ─────────────────
_current_session_id: ContextVar[Optional[str]] = ContextVar("current_session_id", default=None)
_current_active_date_window: ContextVar[Optional[Dict[str, Any]]] = ContextVar("current_active_date_window", default=None)
_current_active_tenant_ids: ContextVar[Optional[List[str]]] = ContextVar("current_active_tenant_ids", default=None)
_current_active_company_ids: ContextVar[Optional[List[int]]] = ContextVar("current_active_company_ids", default=None)

# ── Process-level session store for cross-thread sync ─────────────────
# (LangChain ThreadPoolExecutor threads cannot share ContextVars)
_session_windows: Dict[str, Dict[str, Any]] = {}
_session_tenants: Dict[str, List[str]] = {}
_session_companies: Dict[str, List[int]] = {}


def set_session_context(
    session_id: Optional[str],
    date_window: Optional[Dict[str, Any]] = None,
    tenant_ids: Optional[List[str]] = None,
    company_ids: Optional[List[int]] = None,
):
    """
    Initializes the session context for the current async/sync task execution.
    Loads persisted active scope from DB when not explicitly provided.
    """
    _current_session_id.set(session_id)

    # ── Date window ───────────────────────────────────────────────────
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
                if sess:
                    if sess.active_date_window:
                        resolved_window = sess.active_date_window
                        _session_windows[session_id] = resolved_window
                    # ── Tenant IDs ────────────────────────────────────
                    if tenant_ids is None and sess.active_tenant_ids:
                        tenant_ids = sess.active_tenant_ids
                    # ── Company IDs ───────────────────────────────────
                    if company_ids is None and sess.active_company_ids:
                        company_ids = sess.active_company_ids
                    # Seed from legacy tenant_id field if nothing else
                    if tenant_ids is None and sess.tenant_id:
                        tenant_ids = [sess.tenant_id]
            except Exception:
                pass

    _current_active_date_window.set(resolved_window)

    # ── Tenant IDs ────────────────────────────────────────────────────
    if session_id and tenant_ids is not None:
        _session_tenants[session_id] = tenant_ids
    elif session_id and session_id in _session_tenants:
        tenant_ids = _session_tenants[session_id]
    _current_active_tenant_ids.set(tenant_ids)

    # ── Company IDs ───────────────────────────────────────────────────
    if session_id and company_ids is not None:
        _session_companies[session_id] = company_ids
    elif session_id and session_id in _session_companies:
        company_ids = _session_companies[session_id]
    _current_active_company_ids.set(company_ids)


def get_current_session_id() -> Optional[str]:
    """Returns the session_id for the active request execution."""
    return _current_session_id.get()


# ── Date window accessors ─────────────────────────────────────────────

def get_active_date_window(session_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """
    Returns the active date window dictionary e.g.:
    {"start_date": "2026-07-01", "end_date": "2026-09-30", "label": "..."}
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


# ── Tenant IDs accessors ──────────────────────────────────────────────

def get_active_tenant_ids(session_id: Optional[str] = None) -> Optional[List[str]]:
    """
    Returns the active tenant_ids list for the current session, e.g. ['f9ce5883-...'].
    Returns None if no active tenant has been established.
    """
    sid = session_id or _current_session_id.get()
    if sid and sid in _session_tenants:
        return _session_tenants[sid]
    return _current_active_tenant_ids.get()


def update_active_tenant_ids(tenant_ids: List[str], session_id: Optional[str] = None):
    """
    Persists tenant_ids in ContextVar, process store, and PostgreSQL ChatSession.
    No-op if tenant_ids is empty/None.
    """
    if not tenant_ids:
        return

    tids = [str(t).strip() for t in tenant_ids if t]
    if not tids:
        return

    _current_active_tenant_ids.set(tids)
    sid = session_id or _current_session_id.get()
    if sid:
        _session_tenants[sid] = tids
        try:
            from odoo_app.models.agent import ChatSession
            ChatSession.objects.filter(session_id=sid).update(active_tenant_ids=tids)
        except Exception:
            pass


# ── Company IDs accessors ─────────────────────────────────────────────

def get_active_company_ids(session_id: Optional[str] = None) -> Optional[List[int]]:
    """
    Returns the active company_ids list for the current session, e.g. [1].
    Returns None if no active company has been established.
    """
    sid = session_id or _current_session_id.get()
    if sid and sid in _session_companies:
        return _session_companies[sid]
    return _current_active_company_ids.get()


def update_active_company_ids(company_ids: List[int], session_id: Optional[str] = None):
    """
    Persists company_ids in ContextVar, process store, and PostgreSQL ChatSession.
    No-op if company_ids is empty/None.
    """
    if not company_ids:
        return

    try:
        cids = [int(c) for c in company_ids if c is not None]
    except (TypeError, ValueError):
        return
    if not cids:
        return

    _current_active_company_ids.set(cids)
    sid = session_id or _current_session_id.get()
    if sid:
        _session_companies[sid] = cids
        try:
            from odoo_app.models.agent import ChatSession
            ChatSession.objects.filter(session_id=sid).update(active_company_ids=cids)
        except Exception:
            pass

