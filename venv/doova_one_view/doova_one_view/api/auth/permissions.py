from fastapi import Depends, HTTPException, status
from doova_one_view.api.dependencies import get_current_user
from doova_one_view.api.auth.permission_service import PermissionService
from odoo_app.models import AppUser


def require_permissions(*codenames: str):
    """
    FastAPI dependency that enforces ALL listed permission codenames.
    Superusers bypass all checks.
    Permissions are always fetched from the DB — never from the token.
    """
    async def _checker(user: AppUser = Depends(get_current_user)):
        if getattr(user, 'is_superuser', False):
            return user

        user_perms = await PermissionService.get_user_permissions(user.id)
        missing = [c for c in codenames if c not in user_perms]
        if missing:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Missing permissions: {', '.join(missing)}"
            )
        return user

    return _checker


def require_any_permission(*codenames: str):
    """
    FastAPI dependency that enforces AT LEAST ONE of the listed permission codenames.
    Superusers bypass all checks.
    """
    async def _checker(user: AppUser = Depends(get_current_user)):
        if getattr(user, 'is_superuser', False):
            return user

        user_perms = await PermissionService.get_user_permissions(user.id)
        if not any(c in user_perms for c in codenames):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Missing required permission. Requires one of: {', '.join(codenames)}"
            )
        return user

    return _checker
