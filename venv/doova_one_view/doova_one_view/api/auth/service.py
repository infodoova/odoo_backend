import asyncio
import logging
import random
import string
from datetime import datetime, timedelta

from odoo_app.models import AppUser
from odoo_app.models.password_reset_otp import PasswordResetOTP
from django.contrib.auth.hashers import make_password, check_password as django_check_password
from django.utils import timezone
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework_simplejwt.exceptions import TokenError

from doova_one_view.api.common.exceptions import ValidationError, AuthenticationError
from doova_one_view.api.auth.schemas import (
    RegisterRequest,
    LoginRequest,
    UserResponse,
    TokenResponse,
    ProfileUpdateRequest,
    ChangePasswordRequest,
    ForgotPasswordRequest,
    ResetPasswordRequest,
)
from doova_one_view.api.auth.permission_service import PermissionService
from doova_one_view.api.email.service import EmailService, EmailServiceError

logger = logging.getLogger(__name__)


async def _build_user_response(user: AppUser) -> UserResponse:
    roles_data = await PermissionService.get_user_roles(user.id)
    permissions = await PermissionService.get_user_permissions(user.id)
    return UserResponse(
        id=str(user.id),
        email=user.email,
        full_name=user.full_name,
        is_active=user.is_active,
        is_superuser=user.is_superuser,
        created_at=user.created_at,
        last_login_at=user.last_login_at,
        roles=[r["name"] for r in roles_data],
        permissions=sorted(permissions),
    )


class AuthService:

    @staticmethod
    async def register_user(request: RegisterRequest) -> UserResponse:
        if request.password != request.password_confirm:
            raise ValidationError("Passwords do not match")

        def _create():
            if AppUser.objects.filter(email=request.email).exists():
                raise ValidationError("User with this email already exists")
            user = AppUser(
                email=request.email,
                password_hash=make_password(request.password),
                full_name=request.full_name,
                is_active=True,
            )
            user.save()
            return user

        try:
            user = await asyncio.to_thread(_create)
            logger.info(f"New user registered: {user.email}")
            return await _build_user_response(user)
        except ValidationError:
            raise
        except Exception as e:
            logger.error(f"Registration error: {e}")
            raise ValidationError("Registration failed")

    @staticmethod
    async def authenticate_user(request: LoginRequest) -> TokenResponse:
        def _authenticate():
            try:
                user = AppUser.objects.get(email=request.email)
            except AppUser.DoesNotExist:
                raise AuthenticationError("Invalid credentials")

            if not user.is_active:
                raise AuthenticationError("User account is inactive")

            if not user.check_password(request.password):
                logger.warning(f"Failed login attempt for: {request.email}")
                raise AuthenticationError("Invalid credentials")

            from django.utils import timezone
            user.last_login_at = timezone.now()
            user.save(update_fields=['last_login_at'])
            return user

        try:
            user = await asyncio.to_thread(_authenticate)

            refresh = RefreshToken.for_user(user)
            refresh['email'] = user.email
            refresh['full_name'] = user.full_name or ""

            return TokenResponse(
                access=str(refresh.access_token),
                refresh=str(refresh),
                is_superuser=user.is_superuser,
            )
        except AuthenticationError:
            raise
        except Exception as e:
            logger.error(f"Login error: {e}")
            raise AuthenticationError("Login failed")

    @staticmethod
    async def refresh_access_token(refresh_token_str: str) -> dict:
        if not refresh_token_str:
            raise ValidationError("Refresh token required")

        try:
            refresh = RefreshToken(refresh_token_str)
            return {
                "access": str(refresh.access_token),
                "message": "Token refreshed successfully",
                "message_type": "success",
            }
        except TokenError:
            raise AuthenticationError("Invalid or expired refresh token")
        except Exception as e:
            logger.error(f"Token refresh error: {e}")
            raise AuthenticationError("Token refresh failed")

    @staticmethod
    async def get_user_profile(user: AppUser) -> UserResponse:
        return await _build_user_response(user)

    @staticmethod
    async def update_user_profile(user: AppUser, request: ProfileUpdateRequest) -> UserResponse:
        def _update():
            if request.full_name is not None:
                user.full_name = request.full_name
            user.save()
            return user

        updated_user = await asyncio.to_thread(_update)
        logger.info(f"User profile updated: {user.email}")
        return await _build_user_response(updated_user)

    @staticmethod
    async def change_user_password(user: AppUser, request: ChangePasswordRequest) -> dict:
        if request.new_password != request.new_password_confirm:
            raise ValidationError("Passwords do not match")

        def _change():
            if not user.check_password(request.old_password):
                raise ValidationError("Old password is incorrect")
            user.set_password(request.new_password)
            user.save()

        try:
            await asyncio.to_thread(_change)
            logger.info(f"Password changed for user: {user.email}")
            return {"message": "Password changed successfully", "message_type": "success"}
        except ValidationError:
            raise
        except Exception as e:
            logger.error(f"Password change error: {e}")
            raise ValidationError("Password change failed")

    @staticmethod
    async def request_password_reset(request: ForgotPasswordRequest) -> dict:
        """
        Generate and email a 6-digit OTP.
        Always returns success to avoid revealing whether the email exists.
        """
        def _prepare():
            try:
                user = AppUser.objects.get(email=request.email)
            except AppUser.DoesNotExist:
                return None, None

            # Invalidate any previous unused OTPs for this user
            PasswordResetOTP.objects.filter(user=user, used=False).update(used=True)

            otp_code = ''.join(random.choices(string.digits, k=6))
            otp_hash = make_password(otp_code)
            expires_at = timezone.now() + timedelta(minutes=10)

            PasswordResetOTP.objects.create(
                user=user,
                otp_hash=otp_hash,
                expires_at=expires_at,
            )
            return user, otp_code

        try:
            user, otp_code = await asyncio.to_thread(_prepare)
            if user and otp_code:
                try:
                    await EmailService.send_otp_email(
                        to=user.email,
                        to_name=user.full_name,
                        otp_code=otp_code,
                    )
                    logger.info(f"Password reset OTP sent to: {user.email}")
                except EmailServiceError as e:
                    logger.error(f"Failed to send OTP email to {user.email}: {e}")
                    raise ValidationError("Failed to send reset email. Please try again later.")
        except ValidationError:
            raise
        except Exception as e:
            logger.error(f"Password reset request error: {e}")

        return {"message": "If that email exists, a reset code has been sent.", "message_type": "success"}

    @staticmethod
    async def reset_password_with_otp(request: ResetPasswordRequest) -> dict:
        if request.new_password != request.new_password_confirm:
            raise ValidationError("Passwords do not match")

        def _reset():
            try:
                user = AppUser.objects.get(email=request.email)
            except AppUser.DoesNotExist:
                raise ValidationError("Invalid or expired reset code")

            otp_record = (
                PasswordResetOTP.objects
                .filter(user=user, used=False)
                .order_by('-created_at')
                .first()
            )

            if not otp_record or not otp_record.is_valid():
                raise ValidationError("Invalid or expired reset code")

            if not django_check_password(request.otp, otp_record.otp_hash):
                raise ValidationError("Invalid or expired reset code")

            otp_record.used = True
            otp_record.save(update_fields=['used'])

            user.set_password(request.new_password)
            user.save()

        try:
            await asyncio.to_thread(_reset)
            logger.info(f"Password reset via OTP for: {request.email}")
            return {"message": "Password reset successfully", "message_type": "success"}
        except ValidationError:
            raise
        except Exception as e:
            logger.error(f"Password reset error: {e}")
            raise ValidationError("Password reset failed")
