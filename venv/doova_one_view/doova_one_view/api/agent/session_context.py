# doova_one_view/api/agent/session_context.py
"""
Thread-safe session context tracking for active reporting date windows,
tenant IDs, and company IDs.

Allows tool executions and agent prompts to seamlessly share and inherit
the active scope (date, tenant, company) across multi-turn conversational
follow-ups.
"""

from collections import OrderedDict
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


# ── Authorized tenants (server-side access decision) ──────────────────
# The set of tenants the authenticated caller may read. It is established by the
# endpoint (or background job) from the user's access rights, never from request text
# or model output. normalize_tenant_ids() clips every tenant list to this set, so tools
# and the SQL agent cannot be pointed at another tenant by a prompt or a tool argument.
_current_authorized_tenant_ids: ContextVar[Optional[frozenset]] = ContextVar(
    "current_authorized_tenant_ids", default=None
)
_session_authorized: "OrderedDict[str, frozenset]" = OrderedDict()
_MAX_TRACKED_SESSIONS = 5000


def set_authorized_tenant_ids(tenant_ids: Optional[List[str]], session_id: Optional[str] = None) -> None:
    """Fix the tenants the current request/job may read. ``None`` removes the restriction."""
    if tenant_ids is None:
        _current_authorized_tenant_ids.set(None)
        if session_id:
            _session_authorized.pop(session_id, None)
        return
    allowed = frozenset(str(t) for t in tenant_ids)
    _current_authorized_tenant_ids.set(allowed)
    sid = session_id or _current_session_id.get()
    if sid:
        _session_authorized[sid] = allowed
        _session_authorized.move_to_end(sid)
        while len(_session_authorized) > _MAX_TRACKED_SESSIONS:
            _session_authorized.popitem(last=False)


def run_in_scope(tenant_ids: Optional[List[str]], fn, /, *args, **kwargs):
    # Positional-only: the wrapped call (agent.run) takes its own tenant_ids keyword.
    """Run ``fn`` with its tenant access limited to ``tenant_ids`` (a scheduled job's own tenants).

    Meant to be the target of ``asyncio.to_thread`` so the restriction stays inside that
    worker thread. An empty list leaves the call unrestricted, as before.
    """
    if tenant_ids:
        from .query_context import normalize_tenant_ids
        set_authorized_tenant_ids(None)
        scoped = normalize_tenant_ids(tenant_ids)
        if scoped:
            set_authorized_tenant_ids(scoped)
    return fn(*args, **kwargs)


def get_authorized_tenant_ids() -> Optional[frozenset]:
    """The authorized tenant set for this request, or ``None`` when no scope was set."""
    allowed = _current_authorized_tenant_ids.get()
    if allowed is not None:
        return allowed
    sid = _current_session_id.get()
    if sid:
        return _session_authorized.get(sid)
    return None


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
                    # Seed from legacy tenant_id field if nothing else. "default" is only the
                    # placeholder stored for a chat started without a tenant; resolving it would
                    # pick an arbitrary tenant ("the first one in the table"), so it is skipped and
                    # the request falls back to all of the caller's tenants.
                    if tenant_ids is None and sess.tenant_id and sess.tenant_id.strip().lower() != "default":
                        tenant_ids = [sess.tenant_id]
            except Exception:
                pass

    _current_active_date_window.set(resolved_window)

    # ── Tenant IDs ────────────────────────────────────────────────────
    if session_id and tenant_ids is not None:
        from .query_context import normalize_tenant_ids
        clean_tids = normalize_tenant_ids(tenant_ids)
        if clean_tids:
            _session_tenants[session_id] = clean_tids
            # Persist explicit scope to DB immediately so follow-up requests
            # (including voice mode bare payloads) can inherit it.
            try:
                from odoo_app.models.agent import ChatSession
                ChatSession.objects.filter(session_id=session_id).update(active_tenant_ids=clean_tids)
            except Exception:
                pass
            tenant_ids = clean_tids
    elif session_id and session_id in _session_tenants:
        tenant_ids = _session_tenants[session_id]
    _current_active_tenant_ids.set(tenant_ids)

    # ── Company IDs ───────────────────────────────────────────────────
    if session_id and company_ids is not None:
        from .query_context import normalize_company_ids
        clean_cids = normalize_company_ids(company_ids)
        if clean_cids:
            _session_companies[session_id] = clean_cids
            # Persist explicit scope to DB immediately.
            try:
                from odoo_app.models.agent import ChatSession
                ChatSession.objects.filter(session_id=session_id).update(active_company_ids=clean_cids)
            except Exception:
                pass
            company_ids = clean_cids
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


def update_active_tenant_ids(tenant_ids: Any, session_id: Optional[str] = None):
    """
    Persists tenant_ids in ContextVar, process store, and PostgreSQL ChatSession.
    No-op if tenant_ids is empty/None.
    """
    if not tenant_ids:
        return

    from .query_context import normalize_tenant_ids
    tids = normalize_tenant_ids(tenant_ids)
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


def update_active_company_ids(company_ids: Any, session_id: Optional[str] = None):
    """
    Persists company_ids in ContextVar, process store, and PostgreSQL ChatSession.
    No-op if company_ids is empty/None.
    """
    if not company_ids:
        return

    from .query_context import normalize_company_ids
    cids = normalize_company_ids(company_ids)
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

