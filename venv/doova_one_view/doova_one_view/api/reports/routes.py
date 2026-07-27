"""
Report schedule management routes.

POST   /reports/schedules            — create schedule
GET    /reports/schedules            — list schedules for current tenant
PATCH  /reports/schedules/{id}       — update schedule
DELETE /reports/schedules/{id}       — delete schedule
POST   /reports/schedules/{id}/send-now — trigger immediate send
GET    /reports/history              — list ReportLog entries for current tenant
"""

import asyncio
import logging
from datetime import datetime, timezone as tz
from typing import List
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status

from doova_one_view.api.dependencies import get_current_user
from doova_one_view.api.auth.permissions import require_permissions
from doova_one_view.api.reports.schemas import (
    ReportScheduleCreate,
    ReportScheduleUpdate,
    ReportScheduleResponse,
    ReportLogResponse,
)
from doova_one_view.api.reports.utils import calculate_next_send
from odoo_app.models import AppUser

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/reports", tags=["Reports"])

_view   = Depends(require_permissions("view_kpi"))
_manage = Depends(require_permissions("view_kpi"))


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _serialize_schedule(s) -> dict:
    return {
        "id":           str(s.id),
        "tenant_id":    str(s.tenant_id) if s.tenant_id else None,
        "tenantIds":    getattr(s, "tenants", []) or ([str(s.tenant_id)] if s.tenant_id else []),
        "recipients":   s.recipients,
        "frequency":    s.frequency,
        "timezone":     s.timezone,
        "companyIds":   getattr(s, "companies", []),
        "report_type":  s.report_type,
        "prompt":       s.prompt,
        "is_enabled":   s.is_enabled,
        "next_send_at": s.next_send_at,
        "last_sent_at": s.last_sent_at,
        "created_at":   s.created_at,
    }


def _serialize_log(lg) -> dict:
    return {
        "id":            lg.id,
        "schedule_id":   str(lg.schedule_id),
        "status":        lg.status,
        "filename":      lg.filename,
        "error_message": lg.error_message,
        "sent_at":       lg.sent_at,
    }


async def _get_tenant_id_for_user(user: AppUser) -> str:
    """Return the first tenant the user has access to."""
    def _fetch():
        from odoo_app.models.user_tenant_access import UserTenantAccess
        access = UserTenantAccess.objects.filter(user=user).select_related('tenant').first()
        return str(access.tenant_id) if access else None

    tenant_id = await asyncio.to_thread(_fetch)
    if not tenant_id:
        raise HTTPException(status_code=400, detail="No tenant associated with this user")
    return tenant_id


# ---------------------------------------------------------------------------
# POST /reports/schedules
# ---------------------------------------------------------------------------

@router.post(
    "/schedules",
    response_model=ReportScheduleResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a report schedule",
    dependencies=[_manage],
)
async def create_schedule(
    payload: ReportScheduleCreate,
    user: AppUser = Depends(get_current_user),
):
    tenant_id = await _get_tenant_id_for_user(user)

    start_at = payload.start_at
    if start_at.tzinfo is None:
        start_at = start_at.replace(tzinfo=tz.utc)

    def _create():
        from odoo_app.models.report_schedule import ReportSchedule
        from odoo_app.models.tenant import Tenant
        tenant = Tenant.objects.filter(id=tenant_id).first()
        tenant_ids = payload.tenantIds if payload.tenantIds else ([tenant_id] if tenant_id else [])
        return ReportSchedule.objects.create(
            tenant=tenant,
            tenants=tenant_ids,
            recipients=payload.recipients,
            frequency=payload.frequency,
            timezone=payload.timezone,
            companies=payload.companyIds,
            report_type=payload.report_type,
            prompt=payload.prompt,
            is_enabled=payload.is_enabled,
            next_send_at=start_at,
        )

    schedule = await asyncio.to_thread(_create)
    return _serialize_schedule(schedule)


# ---------------------------------------------------------------------------
# GET /reports/schedules
# ---------------------------------------------------------------------------

@router.get(
    "/schedules",
    response_model=List[ReportScheduleResponse],
    summary="List report schedules for the current tenant",
    dependencies=[_view],
)
async def list_schedules(
    user: AppUser = Depends(get_current_user),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
):
    tenant_id = await _get_tenant_id_for_user(user)

    def _fetch():
        from odoo_app.models.report_schedule import ReportSchedule
        from django.db.models import Q
        qs = ReportSchedule.objects.filter(
            Q(tenant_id=tenant_id) | Q(tenants__contains=tenant_id)
        ).order_by('-created_at')
        return list(qs[offset: offset + limit])

    schedules = await asyncio.to_thread(_fetch)
    return [_serialize_schedule(s) for s in schedules]


# ---------------------------------------------------------------------------
# PATCH /reports/schedules/{id}
# ---------------------------------------------------------------------------

@router.patch(
    "/schedules/{schedule_id}",
    response_model=ReportScheduleResponse,
    summary="Update a report schedule",
    dependencies=[_manage],
)
async def update_schedule(
    schedule_id: UUID,
    payload: ReportScheduleUpdate,
    user: AppUser = Depends(get_current_user),
):
    tenant_id = await _get_tenant_id_for_user(user)

    def _update():
        from odoo_app.models.report_schedule import ReportSchedule
        try:
            s = ReportSchedule.objects.get(id=schedule_id, tenant_id=tenant_id)
        except ReportSchedule.DoesNotExist:
            return None

        update_fields = []
        for field in ('recipients', 'frequency', 'timezone', 'report_type', 'prompt', 'is_enabled', 'next_send_at'):
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
        raise HTTPException(status_code=404, detail="Schedule not found")
    return _serialize_schedule(schedule)


# ---------------------------------------------------------------------------
# DELETE /reports/schedules/{id}
# ---------------------------------------------------------------------------

@router.delete(
    "/schedules/{schedule_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a report schedule",
    dependencies=[_manage],
)
async def delete_schedule(
    schedule_id: UUID,
    user: AppUser = Depends(get_current_user),
):
    tenant_id = await _get_tenant_id_for_user(user)

    def _delete():
        from odoo_app.models.report_schedule import ReportSchedule
        deleted, _ = ReportSchedule.objects.filter(id=schedule_id, tenant_id=tenant_id).delete()
        return deleted

    deleted = await asyncio.to_thread(_delete)
    if not deleted:
        raise HTTPException(status_code=404, detail="Schedule not found")
    return None


# ---------------------------------------------------------------------------
# POST /reports/schedules/{id}/send-now
# ---------------------------------------------------------------------------

@router.post(
    "/schedules/{schedule_id}/send-now",
    summary="Trigger an immediate report send for a schedule",
    dependencies=[_manage],
)
async def send_now(
    schedule_id: UUID,
    user: AppUser = Depends(get_current_user),
):
    tenant_id = await _get_tenant_id_for_user(user)

    def _get():
        from odoo_app.models.report_schedule import ReportSchedule
        try:
            return ReportSchedule.objects.select_related('tenant').get(
                id=schedule_id, tenant_id=tenant_id
            )
        except ReportSchedule.DoesNotExist:
            return None

    schedule = await asyncio.to_thread(_get)
    if schedule is None:
        raise HTTPException(status_code=404, detail="Schedule not found")

    from doova_one_view.api.jobs.report_job import ReportJobManager
    now = datetime.now(tz.utc)
    asyncio.create_task(ReportJobManager._fire_schedule(schedule, now))

    return {"detail": "Report generation started. It will be emailed shortly."}


# ---------------------------------------------------------------------------
# GET /reports/history
# ---------------------------------------------------------------------------

@router.get(
    "/history",
    response_model=List[ReportLogResponse],
    summary="List sent report history for the current tenant",
    dependencies=[_view],
)
async def list_history(
    user: AppUser = Depends(get_current_user),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
):
    tenant_id = await _get_tenant_id_for_user(user)

    def _fetch():
        from odoo_app.models.report_schedule import ReportLog
        qs = (
            ReportLog.objects
            .filter(schedule__tenant_id=tenant_id)
            .select_related('schedule')
            .order_by('-sent_at')
        )
        return list(qs[offset: offset + limit])

    logs = await asyncio.to_thread(_fetch)
    return [_serialize_log(lg) for lg in logs]
