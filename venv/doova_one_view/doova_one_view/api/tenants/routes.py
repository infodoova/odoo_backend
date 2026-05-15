"""
Tenant routes - HTTP request handlers
"""

from fastapi import APIRouter, Depends, HTTPException, status, Query
from typing import List

from doova_one_view.api.tenants.schemas import (
    TenantCreate,
    TenantUpdate,
    TenantRead,
    SyncResponse,
    SyncStatusResponse
)
from doova_one_view.api.tenants.service import TenantService
from doova_one_view.api.dependencies import get_current_user
from doova_one_view.api.common.exceptions import NotFoundError, PermissionError
from odoo_app.models import AppUser

router = APIRouter(prefix="/tenants", tags=["Tenants"])


@router.post(
    "/",
    response_model=TenantRead,
    status_code=status.HTTP_201_CREATED,
    summary="Create a new tenant"
)
async def create_tenant(
    payload: TenantCreate,
    user: AppUser = Depends(get_current_user)
):
    """
    Create a new tenant
    
    - **name**: Tenant name
    - **odoo_url**: Odoo instance URL
    - **odoo_database**: Odoo database name
    - **odoo_api_key**: Odoo API key (will be encrypted)
    - **is_active**: Whether tenant is active
    """
    try:
        return await TenantService.create_tenant(payload, str(user.id))
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )


@router.get(
    "/",
    response_model=List[TenantRead],
    summary="List tenants"
)
async def list_tenants(
    limit: int = Query(10, ge=1, le=100, description="Number of results per page"),
    offset: int = Query(0, ge=0, description="Number of results to skip"),
    user: AppUser = Depends(get_current_user)
):
    """
    List tenants accessible by current user
    
    - **limit**: Maximum number of results (1-100)
    - **offset**: Number of results to skip
    """
    try:
        return await TenantService.list_tenants(str(user.id), limit=limit, offset=offset)
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to list tenants"
        )


@router.get(
    "/{tenant_id}",
    response_model=TenantRead,
    summary="Get tenant details"
)
async def get_tenant(
    tenant_id: str,
    user: AppUser = Depends(get_current_user)
):
    """
    Get tenant details by ID
    """
    try:
        return await TenantService.get_tenant(tenant_id, str(user.id))
    except NotFoundError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(e)
        )
    except PermissionError as e:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=str(e)
        )


@router.put(
    "/{tenant_id}",
    response_model=TenantRead,
    summary="Update tenant (full update)"
)
@router.patch(
    "/{tenant_id}",
    response_model=TenantRead,
    summary="Update tenant (partial update)"
)
async def update_tenant(
    tenant_id: str,
    payload: TenantUpdate,
    user: AppUser = Depends(get_current_user)
):
    """
    Update tenant information
    
    - **name**: Optional new name
    - **odoo_url**: Optional new Odoo URL
    - **odoo_database**: Optional new database name
    - **odoo_api_key**: Optional new API key
    - **is_active**: Optional active status
    """
    try:
        return await TenantService.update_tenant(tenant_id, payload, str(user.id))
    except NotFoundError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(e)
        )
    except PermissionError as e:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=str(e)
        )


@router.delete(
    "/{tenant_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete tenant"
)
async def delete_tenant(
    tenant_id: str,
    user: AppUser = Depends(get_current_user)
):
    """
    Delete a tenant
    """
    try:
        await TenantService.delete_tenant(tenant_id, str(user.id))
        return None
    except NotFoundError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(e)
        )
    except PermissionError as e:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=str(e)
        )


@router.post(
    "/{tenant_id}/sync",
    response_model=SyncResponse,
    summary="Trigger Smart/Incremental sync"
)
async def sync_tenant(
    tenant_id: str,
    force_full: bool = Query(False, description="If true, ignores history and performs a full sync"),
    user: AppUser = Depends(get_current_user)
):
    """
    Trigger a synchronization for the tenant.
    
    By default (smart mode), it will only sync data that has changed since the last successful sync.
    If no previous sync exists, it will perform a full load.
    
    - **force_full**: Set to true to bypass history and re-sync everything.
    """
    try:
        # Check access first
        await TenantService.get_tenant(tenant_id, str(user.id))
        
        if force_full:
            return await TenantService.run_full_sync(tenant_id)
        else:
            return await TenantService.run_smart_sync(tenant_id)
    except NotFoundError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(e)
        )
    except PermissionError as e:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=str(e)
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Sync failed: {str(e)}"
        )


@router.post(
    "/{tenant_id}/delta-sync",
    response_model=SyncResponse,
    summary="Trigger incremental delta sync"
)
async def delta_sync_tenant(
    tenant_id: str,
    user: AppUser = Depends(get_current_user)
):
    """
    Trigger an incremental delta sync for the tenant
    
    This will only sync data that has changed since the last sync.
    """
    try:
        # Check access first
        await TenantService.get_tenant(tenant_id, str(user.id))
        return await TenantService.run_delta_sync(tenant_id)
    except NotFoundError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(e)
        )
    except PermissionError as e:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=str(e)
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Delta sync failed: {str(e)}"
        )


@router.get(
    "/{tenant_id}/status",
    response_model=SyncStatusResponse,
    summary="Get sync status"
)
async def get_sync_status(
    tenant_id: str,
    user: AppUser = Depends(get_current_user)
):
    """
    Get the current sync status for a tenant
    """
    try:
        # Check access first
        await TenantService.get_tenant(tenant_id, str(user.id))
        return await TenantService.get_sync_status(tenant_id)
    except NotFoundError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(e)
        )
    except PermissionError as e:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=str(e)
        )
