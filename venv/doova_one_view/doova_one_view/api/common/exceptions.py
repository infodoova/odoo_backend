"""
Custom API exceptions
"""

from fastapi import HTTPException, status
from typing import Optional, Dict, Any


class APIException(HTTPException):
    """Base API exception with message_type support"""
    
    def __init__(
        self,
        status_code: int,
        detail: str,
        message_type: str = "error",
        headers: Optional[Dict[str, Any]] = None
    ):
        super().__init__(status_code=status_code, detail=detail, headers=headers)
        self.message = detail
        self.message_type = message_type


class NotFoundError(APIException):
    """Resource not found exception"""
    
    def __init__(self, resource: str, identifier: Optional[str] = None):
        message = f"{resource} not found"
        if identifier:
            message += f": {identifier}"
        super().__init__(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=message
        )


class ValidationError(APIException):
    """Validation error exception"""
    
    def __init__(self, detail: str):
        super().__init__(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=detail
        )


class AuthenticationError(APIException):
    """Authentication error exception"""
    
    def __init__(self, detail: str = "Authentication failed"):
        super().__init__(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=detail
        )


class PermissionError(APIException):
    """Permission denied exception"""
    
    def __init__(self, detail: str = "Permission denied"):
        super().__init__(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=detail
        )
