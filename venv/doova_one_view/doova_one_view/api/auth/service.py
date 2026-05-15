"""
Authentication service - Business logic layer
"""

import asyncio
import logging
from typing import Optional
from datetime import datetime

from odoo_app.models import AppUser
from django.contrib.auth.hashers import make_password
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework_simplejwt.exceptions import TokenError

from doova_one_view.api.common.exceptions import (
    ValidationError,
    AuthenticationError,
    NotFoundError
)
from doova_one_view.api.auth.schemas import (
    RegisterRequest,
    LoginRequest,
    UserResponse,
    TokenResponse,
    ProfileUpdateRequest,
    ChangePasswordRequest
)

logger = logging.getLogger(__name__)


class AuthService:
    """Service for authentication operations"""
    
    @staticmethod
    async def register_user(request: RegisterRequest) -> UserResponse:
        """
        Register a new user
        
        Args:
            request: Registration request data
            
        Returns:
            UserResponse: Created user data
            
        Raises:
            ValidationError: If validation fails
        """
        # Validate password confirmation
        if request.password != request.password_confirm:
            raise ValidationError("Passwords do not match")
        
        def _create_user():
            # Check if user already exists
            if AppUser.objects.filter(email=request.email).exists():
                raise ValidationError("User with this email already exists")
            
            # Create user
            user = AppUser(
                email=request.email,
                password_hash=make_password(request.password),
                full_name=request.full_name,
                role=request.role,
                is_active=True
            )
            user.save()
            return user
        
        try:
            user = await asyncio.to_thread(_create_user)
            logger.info(f"New user registered: {user.email}")
            
            return UserResponse(
                id=str(user.id),
                email=user.email,
                full_name=user.full_name,
                role=user.role,
                is_active=user.is_active,
                created_at=user.created_at,
                last_login_at=user.last_login_at
            )
        except ValidationError:
            raise
        except Exception as e:
            logger.error(f"Registration error: {str(e)}")
            raise ValidationError("Registration failed")
    
    @staticmethod
    async def authenticate_user(request: LoginRequest) -> TokenResponse:
        """
        Authenticate user and generate JWT tokens
        
        Args:
            request: Login request data
            
        Returns:
            TokenResponse: JWT access and refresh tokens
            
        Raises:
            AuthenticationError: If authentication fails
        """
        def _authenticate():
            try:
                user = AppUser.objects.get(email=request.email)
                if not user.is_active:
                    raise AuthenticationError("User account is inactive")
                
                # Check password
                if not user.check_password(request.password):
                    raise AuthenticationError("Invalid credentials")
                
                # Update last login with timezone-aware datetime
                from django.utils import timezone
                user.last_login_at = timezone.now()
                user.save(update_fields=['last_login_at'])
                
                return user
            except AppUser.DoesNotExist:
                raise AuthenticationError("Invalid credentials")
        
        try:
            user = await asyncio.to_thread(_authenticate)
            
            # Generate tokens
            refresh = RefreshToken.for_user(user)
            
            # Add custom claims
            refresh['email'] = user.email
            refresh['full_name'] = user.full_name or ""
            refresh['role'] = user.role
            
            return TokenResponse(
                access=str(refresh.access_token),
                refresh=str(refresh)
            )
        except AuthenticationError:
            raise
        except Exception as e:
            logger.error(f"Login error: {str(e)}")
            raise AuthenticationError("Login failed")
    
    @staticmethod
    async def refresh_access_token(refresh_token_str: str) -> dict:
        """
        Refresh access token using refresh token
        
        Args:
            refresh_token_str: Refresh token string
            
        Returns:
            dict: New access token
            
        Raises:
            AuthenticationError: If token is invalid
        """
        if not refresh_token_str:
            raise ValidationError("Refresh token required")
        
        try:
            refresh = RefreshToken(refresh_token_str)
            access = str(refresh.access_token)
            return {
                "access": access,
                "message": "Token refreshed successfully",
                "message_type": "success"
            }
        except TokenError:
            raise AuthenticationError("Invalid or expired refresh token")
        except Exception as e:
            logger.error(f"Token refresh error: {str(e)}")
            raise AuthenticationError("Token refresh failed")
    
    @staticmethod
    async def get_user_profile(user: AppUser) -> UserResponse:
        """
        Get user profile
        
        Args:
            user: Authenticated user instance
            
        Returns:
            UserResponse: User profile data
        """
        return UserResponse(
            id=str(user.id),
            email=user.email,
            full_name=user.full_name,
            role=user.role,
            is_active=user.is_active,
            created_at=user.created_at,
            last_login_at=user.last_login_at
        )
    
    @staticmethod
    async def update_user_profile(
        user: AppUser,
        request: ProfileUpdateRequest
    ) -> UserResponse:
        """
        Update user profile
        
        Args:
            user: Authenticated user instance
            request: Profile update data
            
        Returns:
            UserResponse: Updated user data
        """
        def _update():
            if request.full_name is not None:
                user.full_name = request.full_name
            if request.role is not None:
                user.role = request.role
            user.save()
            return user
        
        updated_user = await asyncio.to_thread(_update)
        logger.info(f"User profile updated: {user.email}")
        
        return UserResponse(
            id=str(updated_user.id),
            email=updated_user.email,
            full_name=updated_user.full_name,
            role=updated_user.role,
            is_active=updated_user.is_active,
            created_at=updated_user.created_at,
            last_login_at=updated_user.last_login_at
        )
    
    @staticmethod
    async def change_user_password(
        user: AppUser,
        request: ChangePasswordRequest
    ) -> dict:
        """
        Change user password
        
        Args:
            user: Authenticated user instance
            request: Password change data
            
        Returns:
            dict: Success message
            
        Raises:
            ValidationError: If validation fails
        """
        # Validate password confirmation
        if request.new_password != request.new_password_confirm:
            raise ValidationError("Passwords do not match")
        
        def _change_password():
            # Check old password
            if not user.check_password(request.old_password):
                raise ValidationError("Old password is incorrect")
            
            # Update password
            user.set_password(request.new_password)
            user.save()
            return True
        
        try:
            await asyncio.to_thread(_change_password)
            logger.info(f"Password changed for user: {user.email}")
            return {
                "message": "Password changed successfully",
                "message_type": "success"
            }
        except ValidationError:
            raise
        except Exception as e:
            logger.error(f"Password change error: {str(e)}")
            raise ValidationError("Password change failed")
