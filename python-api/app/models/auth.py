"""Authentication and authorization related models."""

from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, Field, validator

from .common import BaseResponse


class UserInfo(BaseModel):
    """User information."""
    
    user_id: str = Field(..., description="User identifier")
    username: str = Field(..., description="Username")
    email: Optional[str] = Field(None, description="Email address")
    full_name: Optional[str] = Field(None, description="Full name")
    is_active: bool = Field(True, description="Whether user is active")
    created_at: datetime = Field(..., description="Account creation time")
    last_login: Optional[datetime] = Field(None, description="Last login time")
    permissions: List[str] = Field(
        default_factory=list,
        description="User permissions"
    )
    
    class Config:
        """Pydantic configuration."""
        schema_extra = {
            "example": {
                "user_id": "user_123",
                "username": "john_doe",
                "email": "john@example.com",
                "full_name": "John Doe",
                "is_active": True,
                "created_at": "2024-01-01T00:00:00Z",
                "last_login": "2024-01-15T10:30:00Z",
                "permissions": ["read", "write", "admin"]
            }
        }


class APIKeyInfo(BaseModel):
    """API key information."""
    
    key_id: str = Field(..., description="API key identifier")
    name: str = Field(..., description="API key name")
    prefix: str = Field(..., description="API key prefix (first 8 characters)")
    created_at: datetime = Field(..., description="Creation time")
    expires_at: Optional[datetime] = Field(None, description="Expiration time")
    last_used: Optional[datetime] = Field(None, description="Last usage time")
    is_active: bool = Field(True, description="Whether key is active")
    permissions: List[str] = Field(
        default_factory=list,
        description="API key permissions"
    )
    usage_count: int = Field(0, ge=0, description="Total usage count")
    
    @property
    def is_expired(self) -> bool:
        """Check if API key is expired."""
        if self.expires_at is None:
            return False
        return datetime.utcnow() > self.expires_at
    
    class Config:
        """Pydantic configuration."""
        schema_extra = {
            "example": {
                "key_id": "key_abc123",
                "name": "Production API Key",
                "prefix": "rag_1234",
                "created_at": "2024-01-01T00:00:00Z",
                "expires_at": "2024-12-31T23:59:59Z",
                "last_used": "2024-01-15T10:30:00Z",
                "is_active": True,
                "permissions": ["read", "write"],
                "usage_count": 1543
            }
        }


class JWTToken(BaseResponse):
    """JWT token response."""
    
    access_token: str = Field(..., description="JWT access token")
    token_type: str = Field("bearer", description="Token type")
    expires_in: int = Field(..., description="Token expiration in seconds")
    expires_at: datetime = Field(..., description="Token expiration timestamp")
    scope: Optional[str] = Field(None, description="Token scope")
    
    class Config:
        """Pydantic configuration."""
        schema_extra = {
            "example": {
                "access_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
                "token_type": "bearer",
                "expires_in": 3600,
                "expires_at": "2024-01-15T11:30:00Z",
                "scope": "read write",
                "timestamp": "2024-01-15T10:30:00Z"
            }
        }


class LoginRequest(BaseModel):
    """User login request."""
    
    username: str = Field(..., min_length=3, description="Username")
    password: str = Field(..., min_length=8, description="Password")
    remember_me: bool = Field(False, description="Extend session duration")
    
    class Config:
        """Pydantic configuration."""
        schema_extra = {
            "example": {
                "username": "john_doe",
                "password": "SecurePassword123!",
                "remember_me": False
            }
        }


class APIKeyCreateRequest(BaseModel):
    """API key creation request."""
    
    name: str = Field(..., min_length=3, max_length=100, description="API key name")
    expires_in_days: Optional[int] = Field(
        None,
        ge=1,
        le=365,
        description="Expiration in days (None for no expiration)"
    )
    permissions: List[str] = Field(
        default_factory=list,
        description="API key permissions"
    )
    description: Optional[str] = Field(None, description="API key description")
    
    @validator("permissions")
    def validate_permissions(cls, v):
        """Validate permissions."""
        allowed_permissions = {
            "read", "write", "delete", "admin", 
            "documents", "queries", "files", "kb_manage"
        }
        for permission in v:
            if permission not in allowed_permissions:
                raise ValueError(f"Invalid permission: {permission}")
        return v
    
    class Config:
        """Pydantic configuration."""
        schema_extra = {
            "example": {
                "name": "Production API Key",
                "expires_in_days": 365,
                "permissions": ["read", "write", "documents"],
                "description": "API key for production application"
            }
        }


# Alias for backward compatibility
TokenResponse = JWTToken
APIKeyResponse = APIKeyInfo


class RefreshTokenRequest(BaseModel):
    """Refresh token request."""
    
    refresh_token: str = Field(..., description="Refresh token")
    
    class Config:
        """Pydantic configuration."""
        schema_extra = {
            "example": {
                "refresh_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9..."
            }
        }


class APIKeyCreateResult(BaseResponse):
    """API key creation result."""
    
    key_id: str = Field(..., description="API key identifier")
    api_key: str = Field(..., description="Generated API key (shown once)")
    name: str = Field(..., description="API key name")
    expires_at: Optional[datetime] = Field(None, description="Expiration time")
    permissions: List[str] = Field(
        default_factory=list,
        description="API key permissions"
    )
    
    class Config:
        """Pydantic configuration."""
        schema_extra = {
            "example": {
                "key_id": "key_abc123",
                "api_key": "rag_12345678901234567890123456789012",
                "name": "Production API Key",
                "expires_at": "2024-12-31T23:59:59Z",
                "permissions": ["read", "write", "documents"],
                "timestamp": "2024-01-15T10:30:00Z"
            }
        }


class PasswordChangeRequest(BaseModel):
    """Password change request."""
    
    current_password: str = Field(..., description="Current password")
    new_password: str = Field(
        ...,
        min_length=8,
        description="New password"
    )
    confirm_password: str = Field(..., description="Confirm new password")
    
    @validator("confirm_password")
    def passwords_match(cls, v, values):
        """Validate password confirmation."""
        if "new_password" in values and v != values["new_password"]:
            raise ValueError("Passwords do not match")
        return v
    
    @validator("new_password")
    def validate_password_strength(cls, v):
        """Validate password strength."""
        if len(v) < 8:
            raise ValueError("Password must be at least 8 characters long")
        
        has_upper = any(c.isupper() for c in v)
        has_lower = any(c.islower() for c in v)
        has_digit = any(c.isdigit() for c in v)
        has_special = any(c in "!@#$%^&*()_+-=[]{}|;:,.<>?" for c in v)
        
        if not all([has_upper, has_lower, has_digit, has_special]):
            raise ValueError(
                "Password must contain uppercase, lowercase, digit, and special character"
            )
        
        return v


class RateLimitInfo(BaseModel):
    """Rate limiting information."""
    
    limit: int = Field(..., description="Request limit per window")
    remaining: int = Field(..., description="Remaining requests")
    reset_time: datetime = Field(..., description="Rate limit reset time")
    window_seconds: int = Field(..., description="Rate limit window in seconds")
    
    @property
    def reset_in_seconds(self) -> int:
        """Seconds until rate limit reset."""
        return max(0, int((self.reset_time - datetime.utcnow()).total_seconds()))
    
    class Config:
        """Pydantic configuration."""
        schema_extra = {
            "example": {
                "limit": 100,
                "remaining": 87,
                "reset_time": "2024-01-15T11:00:00Z",
                "window_seconds": 3600
            }
        }