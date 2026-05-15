"""
Authentication module
"""

from doova_one_view.api.auth.routes import router
from doova_one_view.api.auth.schemas import (
    LoginRequest,
    RegisterRequest,
    TokenResponse,
    UserResponse,
    ProfileUpdateRequest,
    ChangePasswordRequest
)
from doova_one_view.api.auth.service import AuthService
from doova_one_view.api.dependencies import get_current_user

__all__ = [
    "router",
    "LoginRequest",
    "RegisterRequest",
    "TokenResponse",
    "UserResponse",
    "ProfileUpdateRequest",
    "ChangePasswordRequest",
    "AuthService",
    "get_current_user",
]
