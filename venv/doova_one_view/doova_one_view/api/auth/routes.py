"""
Authentication routes - HTTP request handlers
"""

from fastapi import APIRouter, Depends, HTTPException, status
from typing import Dict

from doova_one_view.api.auth.schemas import (
    LoginRequest,
    RegisterRequest,
    TokenResponse,
    UserResponse,
    ProfileUpdateRequest,
    UserStatusUpdateRequest,
    ChangePasswordRequest,
    ForgotPasswordRequest,
    ResetPasswordRequest,
)
from doova_one_view.api.auth.service import AuthService
from doova_one_view.api.auth.permissions import require_permissions
from doova_one_view.api.dependencies import get_current_user
from odoo_app.models import AppUser

router = APIRouter(prefix="/auth", tags=["Authentication"])


@router.post(
    "/register",
    response_model=UserResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Register a new user"
)
async def register(
    payload: RegisterRequest,
    _: AppUser = Depends(require_permissions("manage_users")),
):
    """
    Register a new user account

    - **email**: User email address (must be unique)
    - **password**: Password (minimum 8 characters)
    - **password_confirm**: Password confirmation
    - **full_name**: Optional full name
    """
    try:
        return await AuthService.register_user(payload)
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )


@router.post(
    "/login",
    response_model=TokenResponse,
    summary="Authenticate user and get JWT tokens"
)
async def login(payload: LoginRequest):
    """
    Authenticate user and receive JWT access and refresh tokens
    
    - **email**: User email address
    - **password**: User password
    
    Returns access token (1 hour) and refresh token (7 days)
    """
    try:
        return await AuthService.authenticate_user(payload)
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(e)
        )


@router.post(
    "/token/refresh",
    response_model=Dict[str, str],
    summary="Refresh access token"
)
async def refresh_token(payload: Dict[str, str]):
    """
    Exchange refresh token for a new access token
    
    - **refresh**: Refresh token string
    """
    refresh_token_str = payload.get('refresh', '')
    try:
        return await AuthService.refresh_access_token(refresh_token_str)
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(e)
        )


@router.get(
    "/profile",
    response_model=UserResponse,
    summary="Get current user profile"
)
async def get_profile(user: AppUser = Depends(get_current_user)):
    """
    Get the authenticated user's profile information
    """
    return await AuthService.get_user_profile(user)


@router.put(
    "/profile/update",
    response_model=UserResponse,
    summary="Update user profile (full update)"
)
@router.patch(
    "/profile/update",
    response_model=UserResponse,
    summary="Update user profile (partial update)"
)
async def update_profile(
    payload: ProfileUpdateRequest,
    user: AppUser = Depends(get_current_user)
):
    """
    Update the authenticated user's profile

    - **full_name**: Optional new full name
    """
    try:
        return await AuthService.update_user_profile(user, payload)
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )


@router.post(
    "/change-password",
    response_model=Dict[str, str],
    summary="Change user password"
)
async def change_password(
    payload: ChangePasswordRequest,
    user: AppUser = Depends(get_current_user)
):
    """
    Change the authenticated user's password

    - **old_password**: Current password
    - **new_password**: New password (minimum 8 characters)
    - **new_password_confirm**: New password confirmation
    """
    try:
        return await AuthService.change_user_password(user, payload)
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )


@router.post(
    "/forgot-password",
    response_model=Dict[str, str],
    summary="Request a password reset OTP"
)
async def forgot_password(payload: ForgotPasswordRequest):
    """
    Send a 6-digit OTP to the user's email address.

    Always returns a success message regardless of whether the email exists,
    to prevent account enumeration.

    - **email**: The account email address
    """
    try:
        return await AuthService.request_password_reset(payload)
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )


@router.post(
    "/reset-password",
    response_model=Dict[str, str],
    summary="Reset password using OTP"
)
async def reset_password(payload: ResetPasswordRequest):
    """
    Reset the user's password after verifying the OTP.

    - **email**: Account email address
    - **otp**: 6-digit code received by email
    - **new_password**: New password (minimum 8 characters)
    - **new_password_confirm**: New password confirmation
    """
    try:
        return await AuthService.reset_password_with_otp(payload)
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )


@router.patch(
    "/users/{user_id}/status",
    response_model=UserResponse,
    summary="Update user active status (activate/deactivate)"
)
async def update_user_status(
    user_id: str,
    payload: UserStatusUpdateRequest,
    _: AppUser = Depends(require_permissions("manage_users")),
):
    """
    Update active status for a specific user.

    - **is_active**: true to activate, false to deactivate
    """
    try:
        return await AuthService.update_user_status(user_id, payload.is_active)
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )


@router.post(
    "/users/{user_id}/deactivate",
    response_model=UserResponse,
    summary="Deactivate a user account"
)
async def deactivate_user(
    user_id: str,
    _: AppUser = Depends(require_permissions("manage_users")),
):
    """
    Deactivate a user account. Deactivated users cannot log in.
    """
    try:
        return await AuthService.update_user_status(user_id, is_active=False)
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )


@router.post(
    "/users/{user_id}/activate",
    response_model=UserResponse,
    summary="Activate a user account"
)
async def activate_user(
    user_id: str,
    _: AppUser = Depends(require_permissions("manage_users")),
):
    """
    Re-activate a user account.
    """
    try:
        return await AuthService.update_user_status(user_id, is_active=True)
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )
