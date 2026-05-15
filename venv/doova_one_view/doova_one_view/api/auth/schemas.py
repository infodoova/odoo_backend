"""
Authentication schemas (Pydantic models)
"""

from pydantic import BaseModel, EmailStr, Field
from typing import Optional
from datetime import datetime


class LoginRequest(BaseModel):
    """Login request schema"""
    email: EmailStr
    password: str


class RegisterRequest(BaseModel):
    """User registration request schema"""
    email: EmailStr
    password: str = Field(..., min_length=8, description="Password must be at least 8 characters")
    password_confirm: str = Field(..., min_length=8)
    full_name: Optional[str] = None
    role: str = Field(default="accountant", pattern="^(owner|manager|accountant)$")


class TokenResponse(BaseModel):
    """JWT token response schema"""
    access: str
    refresh: str
    token_type: str = "bearer"


class UserResponse(BaseModel):
    """User response schema"""
    id: str
    email: EmailStr
    full_name: Optional[str]
    role: str
    is_active: bool
    created_at: datetime
    last_login_at: Optional[datetime] = None


class ProfileUpdateRequest(BaseModel):
    """Profile update request schema"""
    full_name: Optional[str] = None
    role: Optional[str] = Field(None, pattern="^(owner|manager|accountant)$")


class ChangePasswordRequest(BaseModel):
    """Change password request schema"""
    old_password: str
    new_password: str = Field(..., min_length=8)
    new_password_confirm: str = Field(..., min_length=8)
