"""
Server-side access decisions for the AI agent.

The agent endpoints used to take ``tenant_ids`` and ``session_id`` straight from the request
body, so any user with the ``use_agent`` permission could read another tenant's data (the
tools and the SQL agent query whatever tenants they are given) and read, continue or delete
another user's conversations. This module decides what the *authenticated user* may see:

* ``resolve_request_scope`` turns the tenants named in a request into the tenants the user
  may actually read, rejects anything else, and fixes that set for the rest of the request
  (see ``session_context.set_authorized_tenant_ids``).
* ``user_can_access_session`` / ``sessions_visible_to`` apply session ownership.
"""

from __future__ import annotations

import asyncio
from contextvars import ContextVar
from typing import Any, Iterable, Optional

from fastapi import HTTPException, status

from .session_context import set_authorized_tenant_ids


def accessible_tenant_ids(user) -> set[str]:
    """Tenant ids ``user`` may read: all tenants for a superuser, else their access rows."""
    from odoo_app.models.tenant import Tenant
    from odoo_app.models.user_tenant_access import UserTenantAccess

    if getattr(user, "is_superuser", False):
        return {str(t) for t in Tenant.objects.values_list("id", flat=True)}
    return {
        str(t)
        for t in UserTenantAccess.objects.filter(user_id=user.id).values_list("tenant_id", flat=True)
    }


def _normalize_without_scope(raw: Any) -> list[str]:
    """Normalize requested tenant ids with no earlier scope applied."""
    from .query_context import normalize_tenant_ids

    set_authorized_tenant_ids(None)
    return normalize_tenant_ids(raw)


def resolve_scope_sync(user, requested: Any, session_id: Optional[str] = None) -> tuple[list[str], set[str]]:
    """Return ``(scope, accessible)`` and fix ``scope`` as the request's authorized tenants.

    * Tenants requested that the user cannot access -> HTTP 403 (nothing is queried).
    * No tenant requested -> all of the user's accessible tenants (never "every tenant").
    * A user with no accessible tenant -> HTTP 403.
    """
    accessible = accessible_tenant_ids(user)
    if not accessible:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Your account has no tenant access.",
        )

    wanted = _normalize_without_scope(requested)
    denied = [t for t in wanted if t not in accessible]
    if denied:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not have access to one or more of the requested tenants.",
        )

    scope = wanted or sorted(accessible)
    set_authorized_tenant_ids(scope, session_id)
    return scope, accessible


_principal: ContextVar[Optional[tuple]] = ContextVar("agent_request_principal", default=None)


def get_principal() -> tuple[Any, set[str]]:
    """``(user, accessible_tenant_ids)`` of the request being served, or ``(None, set())``."""
    return _principal.get() or (None, set())


async def resolve_request_scope(user, requested: Any, session_id: Optional[str] = None) -> tuple[list[str], set[str]]:
    """Async wrapper for ``resolve_scope_sync``; also remembers the caller for this request."""
    scope, accessible = await asyncio.to_thread(resolve_scope_sync, user, requested, session_id)
    # asyncio.to_thread runs in a copied context, so fix the scope in this task as well.
    set_authorized_tenant_ids(scope, session_id)
    _principal.set((user, accessible))
    return scope, accessible


def narrow_scope(accessible: Iterable[str], tenants: Optional[list[str]], session_id: Optional[str] = None) -> list[str]:
    """Final scope for a request whose tenants may come from the stored session.

    Tenants the user can no longer access are dropped (not an error: the session may be old);
    an empty result means all of the user's tenants.
    """
    allowed = set(accessible)
    scope = [t for t in (tenants or []) if t in allowed] or sorted(allowed)
    set_authorized_tenant_ids(scope, session_id)
    return scope


# ── Sessions ──────────────────────────────────────────────────────────────────


def user_can_access_session(session, user, accessible: Iterable[str]) -> bool:
    """A session belongs to its owner. A legacy session (no owner) is open to users with
    access to its tenant, and to superusers."""
    owner = getattr(session, "user_id", None)
    if owner is not None:
        return str(owner) == str(user.id)
    tenant = getattr(session, "tenant_id", None)
    if tenant and str(tenant) in set(accessible):
        return True
    return bool(getattr(user, "is_superuser", False))


def sessions_visible_to(queryset, user, accessible: Iterable[str]):
    """Restrict a ChatSession queryset to what ``user`` may see."""
    from django.db.models import Q

    return queryset.filter(
        Q(user_id=user.id) | Q(user_id__isnull=True, tenant_id__in=[str(t) for t in accessible])
    )
