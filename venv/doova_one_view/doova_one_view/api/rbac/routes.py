from fastapi import APIRouter, Depends, HTTPException, status
from odoo_app.models import AppUser
from doova_one_view.api.auth.permissions import require_permissions
from doova_one_view.api.auth.permission_service import PermissionService
from doova_one_view.api.tenants.service import TenantService as TenantSvc
from doova_one_view.api.rbac.schemas import (
    PermissionOut,
    CreatePermissionRequest,
    RoleOut,
    CreateRoleRequest,
    AssignPermissionsRequest,
    AssignRoleRequest,
    UserRoleOut,
    UserListItem,
    TenantAccessItem,
    TenantSimple,
    GrantTenantAccessRequest,
)

router = APIRouter(prefix="/rbac", tags=["RBAC"])

_manage = Depends(require_permissions("manage_roles"))


# ── Permissions ────────────────────────────────────────────────────────────────

@router.get("/permissions", response_model=list[PermissionOut], dependencies=[_manage])
async def list_permissions():
    return await PermissionService.list_permissions()


@router.post("/permissions", response_model=PermissionOut, status_code=201, dependencies=[_manage])
async def create_permission(payload: CreatePermissionRequest):
    try:
        return await PermissionService.create_permission(payload.codename, payload.description or "")
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


# ── Roles ──────────────────────────────────────────────────────────────────────

@router.get("/roles", response_model=list[RoleOut], dependencies=[_manage])
async def list_roles():
    return await PermissionService.list_roles()


@router.post("/roles", response_model=RoleOut, status_code=201, dependencies=[_manage])
async def create_role(payload: CreateRoleRequest):
    try:
        return await PermissionService.create_role(payload.name, payload.description or "")
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/roles/{role_id}/permissions", response_model=RoleOut, dependencies=[_manage])
async def assign_permissions_to_role(role_id: str, payload: AssignPermissionsRequest):
    try:
        return await PermissionService.assign_permissions_to_role(role_id, payload.permission_codenames)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.delete("/roles/{role_id}/permissions/{permission_id}", status_code=204, dependencies=[_manage])
async def remove_permission_from_role(role_id: str, permission_id: str):
    try:
        await PermissionService.remove_permission_from_role(role_id, permission_id)
    except Exception as e:
        raise HTTPException(status_code=404, detail=str(e))


# ── User ↔ Role ────────────────────────────────────────────────────────────────

@router.get("/users", response_model=list[UserListItem], dependencies=[_manage])
async def list_users():
    return await PermissionService.list_users_with_roles()


@router.get("/users/{user_id}/roles", response_model=list[dict], dependencies=[_manage])
async def get_user_roles(user_id: str):
    return await PermissionService.get_user_roles(user_id)


@router.post("/users/{user_id}/roles", response_model=UserRoleOut, status_code=201)
async def assign_role_to_user(
    user_id: str,
    payload: AssignRoleRequest,
    current_user: AppUser = Depends(require_permissions("manage_roles")),
):
    try:
        return await PermissionService.assign_role_to_user(user_id, payload.role_id, current_user.id)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.delete("/users/{user_id}/roles/{role_id}", status_code=204, dependencies=[_manage])
async def remove_role_from_user(user_id: str, role_id: str):
    try:
        await PermissionService.remove_role_from_user(user_id, role_id)
    except Exception as e:
        raise HTTPException(status_code=404, detail=str(e))


# ── Tenant Access ──────────────────────────────────────────────────────────────

@router.get("/tenants", response_model=list[TenantSimple], dependencies=[_manage])
async def list_all_tenants():
    return await TenantSvc.list_all_tenants_simple()


@router.get("/users/{user_id}/tenants", response_model=list[TenantAccessItem], dependencies=[_manage])
async def get_user_tenant_accesses(user_id: str):
    return await TenantSvc.get_user_tenant_accesses(user_id)


@router.post("/users/{user_id}/tenants", response_model=TenantAccessItem, status_code=201, dependencies=[_manage])
async def grant_tenant_access(user_id: str, payload: GrantTenantAccessRequest):
    try:
        return await TenantSvc.grant_tenant_access(user_id, payload.tenant_id)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.delete("/users/{user_id}/tenants/{tenant_id}", status_code=204, dependencies=[_manage])
async def revoke_tenant_access(user_id: str, tenant_id: str):
    try:
        await TenantSvc.revoke_tenant_access(user_id, tenant_id)
    except Exception as e:
        raise HTTPException(status_code=404, detail=str(e))
