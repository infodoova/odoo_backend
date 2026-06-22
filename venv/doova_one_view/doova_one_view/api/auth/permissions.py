from fastapi import Depends, HTTPException, status
from doova_one_view.api.dependencies import get_current_user
from doova_one_view.api.auth.permission_service import PermissionService
from odoo_app.models import AppUser


def require_permissions(*codenames: str):
    """
    FastAPI dependency that enforces all listed permission codenames.
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
