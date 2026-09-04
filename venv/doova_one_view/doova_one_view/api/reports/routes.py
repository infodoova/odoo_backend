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
from doova_one_view.api.auth.permissions import require_permissions, require_any_permission
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

_view   = Depends(require_any_permission("view_reports"))
_manage = Depends(require_permissions("manage_reports"))


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _serialize_schedule(s, tenant_map: dict = None, company_map: dict = None) -> dict:
    from django.db import models
    t_ids = getattr(s, "tenants", []) or ([str(s.tenant_id)] if s.tenant_id else [])
    c_ids = getattr(s, "companies", []) or []

    # 1. Resolve Tenant Names
    if tenant_map is None:
        from odoo_app.models.tenant import Tenant
        query_ids = list(set([str(tid) for tid in t_ids if tid] + ([str(s.tenant_id)] if s.tenant_id else [])))
        t_objs = Tenant.objects.filter(id__in=query_ids)
        tenant_map = {str(t.id): t.name for t in t_objs}
    
    t_names = [tenant_map[str(tid)] for tid in t_ids if str(tid) in tenant_map]
    if not t_names and s.tenant_id and str(s.tenant_id) in tenant_map:
        t_names = [tenant_map[str(s.tenant_id)]]
    if not t_names and getattr(s, 'tenant', None) and s.tenant:
        try:
            t_names = [s.tenant.name]
        except Exception:
            pass
    
    tenant_name_str = ", ".join(t_names) if t_names else (s.tenant.name if getattr(s, 'tenant', None) and s.tenant else None)

    # 2. Resolve Company Names
    if company_map is None and c_ids:
        from odoo_app.models.company import Company
        c_objs = Company.objects.filter(models.Q(id__in=c_ids) | models.Q(odoo_id__in=c_ids))
        company_map = {}
        for c in c_objs:
            company_map[c.id] = c.name
            company_map[c.odoo_id] = c.name
            company_map[str(c.id)] = c.name
            company_map[str(c.odoo_id)] = c.name
    elif company_map is None:
        company_map = {}

    c_names = []
    for cid in c_ids:
        c_name = company_map.get(cid) or company_map.get(str(cid))
        if c_name and c_name not in c_names:
            c_names.append(c_name)

    company_name_str = ", ".join(c_names) if c_names else ("All Companies" if not c_ids else None)

    return {
        "id":               str(s.id),
        "report_name":      s.report_name or '',
        "tenant_id":        str(s.tenant_id) if s.tenant_id else None,
        "tenant_name":      tenant_name_str,
        "tenantName":       tenant_name_str,
        "tenantIds":        t_ids,
        "tenant_names":     t_names,
        "tenantNames":      t_names,
        "recipients":       s.recipients,
        "frequency":        s.frequency,
        "timezone":         s.timezone,
        "companyIds":       c_ids,
        "company_name":     company_name_str,
        "companyName":      company_name_str,
        "company_names":    c_names,
        "companyNames":     c_names,
        "report_type":      s.report_type,
        "date_range_start": s.date_range_start,
        "date_range_end":   s.date_range_end,
        "comparison_label": getattr(s, "comparison_label", None),
        "prompt":           s.prompt,
        "is_enabled":       s.is_enabled,
        "next_send_at":     s.next_send_at,
        "last_sent_at":     s.last_sent_at,
        "created_at":       s.created_at,
    }


def _serialize_log(lg) -> dict:
    return {
        "id":               lg.id,
        "schedule_id":      str(lg.schedule_id),
        "status":           lg.status,
        "filename":         lg.filename,
        "error_message":    lg.error_message,
        "error_category":   getattr(lg, 'error_category', None),
        "duration_seconds": getattr(lg, 'duration_seconds', None),
        "pdf_size_bytes":   getattr(lg, 'pdf_size_bytes', None),
        "sent_at":          lg.sent_at,
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
            report_name=payload.report_name,
            recipients=payload.recipients,
            frequency=payload.frequency,
            timezone=payload.timezone,
            companies=payload.companyIds,
            report_type=payload.report_type,
            date_range_start=payload.date_range_start,
            date_range_end=payload.date_range_end,
            comparison_label=payload.comparison_label,
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
        from odoo_app.models.tenant import Tenant
        from odoo_app.models.company import Company
        from django.db.models import Q
        qs = ReportSchedule.objects.filter(
            Q(tenant_id=tenant_id) | Q(tenants__contains=tenant_id)
        ).select_related('tenant').order_by('-created_at')
        schedules = list(qs[offset: offset + limit])

        all_tenant_ids = set()
        all_company_ids = set()
        for s in schedules:
            if s.tenant_id:
                all_tenant_ids.add(str(s.tenant_id))
            for tid in (getattr(s, "tenants", []) or []):
                all_tenant_ids.add(str(tid))
            for cid in (getattr(s, "companies", []) or []):
                all_company_ids.add(cid)

        tenant_map = {str(t.id): t.name for t in Tenant.objects.filter(id__in=all_tenant_ids)}
        company_map = {}
        if all_company_ids:
            for c in Company.objects.filter(Q(id__in=all_company_ids) | Q(odoo_id__in=all_company_ids)):
                company_map[c.id] = c.name
                company_map[c.odoo_id] = c.name
                company_map[str(c.id)] = c.name
                company_map[str(c.odoo_id)] = c.name

        return [_serialize_schedule(s, tenant_map=tenant_map, company_map=company_map) for s in schedules]

    schedules = await asyncio.to_thread(_fetch)
    return schedules


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
        for field in (
            'report_name', 'recipients', 'frequency', 'timezone', 'report_type',
            'date_range_start', 'date_range_end', 'comparison_label', 'prompt',
            'is_enabled', 'next_send_at'
        ):
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


# ---------------------------------------------------------------------------
# GET /reports/download/{filename}
# ---------------------------------------------------------------------------

@router.get(
    "/download/{filename}",
    summary="Securely download a generated report PDF file",
    dependencies=[_view],
)
async def download_report_pdf(
    filename: str,
    user: AppUser = Depends(get_current_user),
):
    from fastapi.responses import FileResponse
    from pathlib import Path

    # Security check 1: Sanitize filename to prevent directory traversal
    if ".." in filename or "/" in filename or "\\" in filename:
        raise HTTPException(status_code=400, detail="Invalid filename format")

    if not filename.endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only PDF files can be downloaded")

    # Security check 2: Verify file exists in reports directory
    from django.conf import settings
    reports_dir = Path(getattr(settings, "REPORTS_DIR", Path("reports")))
    file_path = reports_dir / filename
    if not file_path.exists() or not file_path.is_file():
        raise HTTPException(status_code=400 if not file_path.exists() else 404, detail="Report file not found or expired")


    # Security check 3: Verify tenant ownership of the report
    tenant_id = await _get_tenant_id_for_user(user)

    def _verify_tenant():
        from odoo_app.models.report_schedule import ReportLog
        return ReportLog.objects.filter(
            schedule__tenant_id=tenant_id,
            filename=filename,
        ).exists()

    is_owner = await asyncio.to_thread(_verify_tenant)
    if not is_owner:
        raise HTTPException(status_code=403, detail="Access denied: report does not belong to your tenant")

    return FileResponse(
        path=str(file_path),
        media_type="application/pdf",
        filename=filename,
        headers={
            "Content-Disposition": f'inline; filename="{filename}"',
            "Cache-Control": "private, max-age=3600",
            "X-Content-Type-Options": "nosniff",
        },
    )

