"""
Files API routes.
"""

import asyncio
from typing import Any, Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, Response

from odoo_app.models import AppUser
from doova_one_view.api.dependencies import get_current_user
from doova_one_view.api.files.service import MAX_FILE_BYTES, FilesService
from doova_one_view.api.tenants.service import TenantService

router = APIRouter(prefix="/files", tags=["Files"])


def _base_url(request: Request) -> str:
    return str(request.base_url).rstrip("/")


@router.get("/{tenant_id}/{company_id}")
async def list_files(
    tenant_id: str,
    company_id: int,
    request: Request,
    user: AppUser = Depends(get_current_user),
) -> list[dict[str, Any]]:
    await TenantService.get_tenant(tenant_id, str(user.id))
    return await asyncio.to_thread(FilesService.list_files, tenant_id, company_id, _base_url(request))


@router.post("/{tenant_id}/{company_id}", status_code=201)
async def upload_file(
    tenant_id: str,
    company_id: int,
    request: Request,
    file: UploadFile = File(...),
    description: Optional[str] = Form(None),
    user: AppUser = Depends(get_current_user),
) -> dict[str, Any]:
    await TenantService.get_tenant(tenant_id, str(user.id))

    content_length = request.headers.get("content-length")
    if content_length:
        try:
            if int(content_length) > MAX_FILE_BYTES + 1024 * 1024:
                raise HTTPException(status_code=413, detail="File size exceeds 10 MB limit.")
        except ValueError:
            pass

    data = await file.read()
    if not data:
        raise HTTPException(status_code=400, detail="Uploaded file is empty.")

    return await asyncio.to_thread(
        FilesService.save_file,
        tenant_id,
        company_id,
        file.filename or "upload",
        file.content_type,
        data,
        description,
        _base_url(request),
    )


@router.delete("/{tenant_id}/{company_id}/{file_id}", status_code=204)
async def delete_file(
    tenant_id: str,
    company_id: int,
    file_id: int,
    user: AppUser = Depends(get_current_user),
) -> Response:
    await TenantService.get_tenant(tenant_id, str(user.id))
    await asyncio.to_thread(FilesService.delete_file, tenant_id, company_id, file_id)
    return Response(status_code=204)


@router.get("/{tenant_id}/{company_id}/{file_id}/content")
async def download_file(
    tenant_id: str,
    company_id: int,
    file_id: int,
    user: AppUser = Depends(get_current_user),
) -> FileResponse:
    await TenantService.get_tenant(tenant_id, str(user.id))
    storage_path, file_name = await asyncio.to_thread(
        FilesService.get_file_path, tenant_id, company_id, file_id
    )
    return FileResponse(
        path=storage_path,
        filename=file_name,
        headers={"Content-Disposition": f'inline; filename="{file_name}"'},
    )
