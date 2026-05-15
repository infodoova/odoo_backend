"""
Permission checks for authentication
"""

from fastapi import Depends, HTTPException, status
from typing import Iterable
from doova_one_view.api.dependencies import get_current_user
from odoo_app.models import AppUser


def _user_has_role(user: AppUser, roles: Iterable[str]) -> bool:
    """
    Check if user has one of the specified roles
    
    Args:
        user: User instance
        roles: Iterable of role names
        
    Returns:
        bool: True if user has one of the roles
    """
    # Superusers have all roles
    if getattr(user, 'is_superuser', False):
        return True
    
    # Check user role
    return user.role in roles


def require_roles(*roles: str):
    """
    Dependency to require user to have one of the specified roles
    
    Args:
        *roles: Role names to check
        
    Returns:
        Dependency function
    """
    async def _checker(user: AppUser = Depends(get_current_user)):
        if not _user_has_role(user, roles):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Insufficient privileges"
            )
        return user
    
    return _checker
