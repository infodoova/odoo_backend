"""
Standard API response models
"""

from pydantic import BaseModel
from typing import Optional, Generic, TypeVar, List

T = TypeVar('T')


class SuccessResponse(BaseModel, Generic[T]):
    """Standard success response"""
    success: bool = True
    message: str
    data: Optional[T] = None
    message_type: str = "success"


class ErrorResponse(BaseModel):
    """Standard error response"""
    success: bool = False
    error: str
    details: Optional[dict] = None
    message_type: str = "error"


class PaginatedResponse(BaseModel, Generic[T]):
    """Paginated response"""
    items: List[T]
    total: int
    page: int
    page_size: int
    pages: int
