"""
Shared dependencies for FastAPI routes
"""

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from rest_framework_simplejwt.tokens import UntypedToken
from rest_framework_simplejwt.exceptions import InvalidToken, TokenError
import asyncio
import logging

from doova_one_view.api.common.exceptions import AuthenticationError

logger = logging.getLogger(__name__)
security = HTTPBearer()


async def get_current_user(credentials: HTTPAuthorizationCredentials = Depends(security)):
    """
    Validate JWT token and return current user.
    Uses Django SimpleJWT for token validation.
    
    Returns:
        AppUser: Authenticated user instance
        
    Raises:
        AuthenticationError: If token is invalid or user not found
    """
    token = credentials.credentials
    
    try:
        # Validate token using SimpleJWT
        validated_token = await asyncio.to_thread(UntypedToken, token)
        
        # Get user_id from token payload
        user_id = validated_token.get('user_id')
        if not user_id:
            raise AuthenticationError("Invalid token payload")
        
        # Get user from Django ORM
        from odoo_app.models import AppUser
        
        def _get_user():
            try:
                return AppUser.objects.get(id=user_id)
            except AppUser.DoesNotExist:
                return None
        
        user = await asyncio.to_thread(_get_user)
        
        if not user:
            raise AuthenticationError("User not found")
        
        if not user.is_active:
            raise AuthenticationError("User account is inactive")
        
        return user
        
    except TokenError as e:
        logger.warning(f"Token validation error: {str(e)}")
        raise AuthenticationError("Invalid or expired token")
    except Exception as e:
        logger.error(f"Unexpected error in get_current_user: {str(e)}")
        raise AuthenticationError("Authentication failed")
