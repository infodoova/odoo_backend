from pydantic import BaseModel
from typing import Optional
from datetime import datetime


class PermissionOut(BaseModel):
    id: str
    codename: str
    description: str
    created_at: str


class UserListItem(BaseModel):
    id: str
    email: str
    full_name: Optional[str] = None
    is_active: bool
    created_at: str
    last_login_at: Optional[str] = None
    roles: list[str] = []


class CreatePermissionRequest(BaseModel):
    codename: str
    description: Optional[str] = ""


class RoleOut(BaseModel):
    id: str
    name: str
    description: str
    created_at: str
    permissions: list[str] = []


class CreateRoleRequest(BaseModel):
    name: str
    description: Optional[str] = ""


class AssignPermissionsRequest(BaseModel):
    permission_codenames: list[str]


class AssignRoleRequest(BaseModel):
    role_id: str


class UserRoleOut(BaseModel):
    user_id: str
    role_id: str
    role_name: str


class TenantAccessItem(BaseModel):
    tenant_id: str
    tenant_name: str
    tenant_is_active: bool
    can_view_all_companies: bool
    granted_at: str


class TenantSimple(BaseModel):
    id: str
    name: str
    is_active: bool


class GrantTenantAccessRequest(BaseModel):
    tenant_id: str
