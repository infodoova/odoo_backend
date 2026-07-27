"""
Alert schedule management routes.

POST   /alerts/schedules                      — create alert schedule
GET    /alerts/schedules                      — list schedules for current tenant
PATCH  /alerts/schedules/{id}                 — update schedule
DELETE /alerts/schedules/{id}                 — delete schedule
POST   /alerts/schedules/{id}/run-now         — instant check (returns AI result, optional email)
GET    /alerts/history                        — list AlertLog entries for current tenant
"""

import asyncio
import logging
from datetime import datetime, timezone as tz
from datetime import timedelta
from typing import List
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status

from doova_one_view.api.dependencies import get_current_user
from doova_one_view.api.auth.permissions import require_permissions
from doova_one_view.api.alerts.schemas import (
    AlertScheduleCreate,
    AlertScheduleUpdate,
    AlertScheduleResponse,
    AlertLogResponse,
    RunAlertRequest,
    RunAlertResponse,
)
from odoo_app.models import AppUser

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/alerts", tags=["Alerts"])

_view   = Depends(require_permissions("view_kpi"))
_manage = Depends(require_permissions("view_kpi"))


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _serialize_schedule(s) -> dict:
    return {
        "id":               str(s.id),
        "tenant_id":        str(s.tenant_id) if s.tenant_id else None,
        "tenantIds":        getattr(s, "tenants", []) or ([str(s.tenant_id)] if s.tenant_id else []),
        "name":             s.name,
        "prompt":           s.prompt,
        "recipients":       s.recipients,
        "companyIds":       getattr(s, "companies", []),
        "timezone":         s.timezone,
        "is_enabled":       s.is_enabled,
        "is_system_default": s.is_system_default,
        "next_check_at":    s.next_check_at,
        "last_checked_at":  s.last_checked_at,
        "created_at":       s.created_at,
    }


def _serialize_log(lg) -> dict:
    return {
        "id":            lg.id,
        "schedule_id":   str(lg.schedule_id) if lg.schedule_id else None,
        "tenant_id":     str(lg.tenant_id) if lg.tenant_id else None,
        "status":        lg.status,
        "has_anomalies": lg.has_anomalies,
        "summary":       lg.summary,
        "alert_sent":    lg.alert_sent,
        "error_message": lg.error_message,
        "checked_at":    lg.checked_at,
    }


async def _get_tenant_id_for_user(user: AppUser) -> str:
    def _fetch():
        from odoo_app.models.user_tenant_access import UserTenantAccess
        access = UserTenantAccess.objects.filter(user=user).select_related('tenant').first()
        return str(access.tenant_id) if access else None

    tenant_id = await asyncio.to_thread(_fetch)
    if not tenant_id:
        raise HTTPException(status_code=400, detail="No tenant associated with this user")
    return tenant_id


# ---------------------------------------------------------------------------
# POST /alerts/schedules
# ---------------------------------------------------------------------------

@router.post(
    "/schedules",
    response_model=AlertScheduleResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create an alert schedule",
    dependencies=[_manage],
)
async def create_alert_schedule(
    payload: AlertScheduleCreate,
    user: AppUser = Depends(get_current_user),
):
    tenant_id = await _get_tenant_id_for_user(user)

    start_at = payload.start_at
    if start_at.tzinfo is None:
        start_at = start_at.replace(tzinfo=tz.utc)

    def _create():
        from odoo_app.models.alert_schedule import AlertSchedule
        from odoo_app.models.tenant import Tenant
        tenant = Tenant.objects.filter(id=tenant_id).first()
        tenant_ids = payload.tenantIds if payload.tenantIds else ([tenant_id] if tenant_id else [])
        return AlertSchedule.objects.create(
            tenant=tenant,
            tenants=tenant_ids,
            name=payload.name,
            prompt=payload.prompt,
            recipients=payload.recipients,
            companies=payload.companyIds,
            timezone=payload.timezone,
            is_enabled=payload.is_enabled,
            is_system_default=payload.is_system_default,
            next_check_at=start_at,
        )

    schedule = await asyncio.to_thread(_create)
    return _serialize_schedule(schedule)


# ---------------------------------------------------------------------------
# GET /alerts/schedules
# ---------------------------------------------------------------------------

@router.get(
    "/schedules",
    response_model=List[AlertScheduleResponse],
    summary="List alert schedules for the current tenant",
    dependencies=[_view],
)
async def list_alert_schedules(
    user: AppUser = Depends(get_current_user),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
):
    tenant_id = await _get_tenant_id_for_user(user)

    def _fetch():
        from odoo_app.models.alert_schedule import AlertSchedule
        # Return this tenant's schedules AND system-wide ones AND multi-tenant matching ones
        from django.db.models import Q
        qs = AlertSchedule.objects.filter(
            Q(tenant_id=tenant_id) | Q(tenants__contains=tenant_id) | Q(is_system_default=True)
        ).order_by('-created_at')
        return list(qs[offset: offset + limit])

    schedules = await asyncio.to_thread(_fetch)
    return [_serialize_schedule(s) for s in schedules]


# ---------------------------------------------------------------------------
# PATCH /alerts/schedules/{id}
# ---------------------------------------------------------------------------

@router.patch(
    "/schedules/{schedule_id}",
    response_model=AlertScheduleResponse,
    summary="Update an alert schedule",
    dependencies=[_manage],
)
async def update_alert_schedule(
    schedule_id: UUID,
    payload: AlertScheduleUpdate,
    user: AppUser = Depends(get_current_user),
):
    tenant_id = await _get_tenant_id_for_user(user)

    def _update():
        from odoo_app.models.alert_schedule import AlertSchedule
        from django.db.models import Q
        try:
            s = AlertSchedule.objects.get(
                Q(tenant_id=tenant_id) | Q(is_system_default=True),
                id=schedule_id,
            )
        except AlertSchedule.DoesNotExist:
            return None

        update_fields = []
        for field in ('name', 'prompt', 'recipients', 'timezone',
                       'is_enabled', 'is_system_default', 'next_check_at'):
            val = getattr(payload, field, None)
            if val is not None:
                setattr(s, field, val)
                update_fields.append(field)

        if payload.companyIds is not None:
            s.companies = payload.companyIds
            update_fields.append('companies')

        if payload.tenantIds is not None:
            s.tenants = payload.tenantIds
            update_fields.append('tenants')

        if update_fields:
            update_fields.append('updated_at')
            s.save(update_fields=update_fields)
        return s

    schedule = await asyncio.to_thread(_update)
    if schedule is None:
        raise HTTPException(status_code=404, detail="Alert schedule not found")
    return _serialize_schedule(schedule)


# ---------------------------------------------------------------------------
# DELETE /alerts/schedules/{id}
# ---------------------------------------------------------------------------

@router.delete(
    "/schedules/{schedule_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete an alert schedule",
    dependencies=[_manage],
)
async def delete_alert_schedule(
    schedule_id: UUID,
    user: AppUser = Depends(get_current_user),
):
    tenant_id = await _get_tenant_id_for_user(user)

    def _delete():
        from odoo_app.models.alert_schedule import AlertSchedule
        from django.db.models import Q
        deleted, _ = AlertSchedule.objects.filter(
            Q(tenant_id=tenant_id) | Q(is_system_default=True),
            id=schedule_id,
        ).delete()
        return deleted

    deleted = await asyncio.to_thread(_delete)
    if not deleted:
        raise HTTPException(status_code=404, detail="Alert schedule not found")
    return None


# ---------------------------------------------------------------------------
# POST /alerts/schedules/{id}/run-now
# ---------------------------------------------------------------------------

@router.post(
    "/schedules/{schedule_id}/run-now",
    response_model=RunAlertResponse,
    summary="Instantly run an alert check and return results (optionally send email)",
    dependencies=[_manage],
)
async def run_alert_now(
    schedule_id: UUID,
    payload: RunAlertRequest,
    user: AppUser = Depends(get_current_user),
):
    tenant_id = await _get_tenant_id_for_user(user)

    def _get():
        from odoo_app.models.alert_schedule import AlertSchedule
        from django.db.models import Q
        try:
            return AlertSchedule.objects.select_related('tenant').get(
                Q(tenant_id=tenant_id) | Q(is_system_default=True),
                id=schedule_id,
            )
        except AlertSchedule.DoesNotExist:
            return None

    schedule = await asyncio.to_thread(_get)
    if schedule is None:
        raise HTTPException(status_code=404, detail="Alert schedule not found")

    from doova_one_view.api.jobs.alert_job import AlertJobManager
    try:
        result = await AlertJobManager.run_check(
            schedule=schedule,
            tenant_id=tenant_id,
            send_email=payload.send_email,
            is_instant=True,
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))
    return result


# ---------------------------------------------------------------------------
# GET /alerts/history
# ---------------------------------------------------------------------------

@router.get(
    "/history",
    response_model=List[AlertLogResponse],
    summary="List alert check history for the current tenant",
    dependencies=[_view],
)
async def list_alert_history(
    user: AppUser = Depends(get_current_user),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
):
    tenant_id = await _get_tenant_id_for_user(user)

    def _fetch():
        from odoo_app.models.alert_schedule import AlertLog
        from django.db.models import Q
        qs = (
            AlertLog.objects
            .filter(
                Q(tenant_id=tenant_id) |
                Q(schedule__is_system_default=True)
            )
            .select_related('schedule')
            .order_by('-checked_at')
        )
        return list(qs[offset: offset + limit])

    logs = await asyncio.to_thread(_fetch)
    return [_serialize_log(lg) for lg in logs]
