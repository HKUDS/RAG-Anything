"""Authentication endpoints for JWT tokens and API key management."""

from datetime import timedelta
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, validator
from loguru import logger

from app.middleware.auth import require_auth
from app.services.auth_service import AuthService
from app.models.auth import (
    TokenResponse,
    APIKeyCreateRequest,
    APIKeyResponse,
    LoginRequest,
    RefreshTokenRequest
)

router = APIRouter(prefix="/api/v1/auth", tags=["Authentication"])


class CreateAPIKeyRequest(BaseModel):
    """Request model for API key creation."""
    name: str
    rate_limit: int = 60
    expires_in_days: Optional[int] = None
    
    @validator('name')
    def validate_name(cls, v):
        if not v or len(v.strip()) < 3:
            raise ValueError("Name must be at least 3 characters")
        if len(v) > 100:
            raise ValueError("Name must be less than 100 characters")
        return v.strip()
    
    @validator('rate_limit')
    def validate_rate_limit(cls, v):
        if v < 1 or v > 10000:
            raise ValueError("Rate limit must be between 1 and 10000")
        return v
    
    @validator('expires_in_days')
    def validate_expires_in_days(cls, v):
        if v is not None and (v < 1 or v > 365):
            raise ValueError("Expiration must be between 1 and 365 days")
        return v


class TokenCreateRequest(BaseModel):
    """Request model for token creation (for testing/admin)."""
    user_id: str
    expires_in_minutes: int = 60
    
    @validator('user_id')
    def validate_user_id(cls, v):
        if not v or len(v.strip()) < 3:
            raise ValueError("User ID must be at least 3 characters")
        return v.strip()


# Mock user authentication (replace with real user service)
async def authenticate_user(username: str, password: str) -> Optional[str]:
    """Mock user authentication.
    
    In production, this should integrate with your user management system.
    """
    # Mock users for testing
    mock_users = {
        "testuser": {"password": "testpass123", "user_id": "user_12345"},
        "admin": {"password": "admin123", "user_id": "admin_67890"}
    }
    
    user = mock_users.get(username)
    if user and user["password"] == password:
        return user["user_id"]
    
    return None


def get_auth_service() -> AuthService:
    """Get auth service dependency."""
    from app.main import redis_client  # Import here to avoid circular imports
    return AuthService(redis_client)


@router.post("/login", response_model=TokenResponse)
async def login(
    request: LoginRequest,
    auth_service: AuthService = Depends(get_auth_service)
):
    """Login with username/password and get JWT tokens.
    
    This is a mock endpoint for testing. In production, integrate with
    your user management system.
    """
    try:
        # Authenticate user
        user_id = await authenticate_user(request.username, request.password)
        if not user_id:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid username or password"
            )
        
        # Create tokens
        access_token = auth_service.create_access_token(user_id)
        refresh_token = auth_service.create_refresh_token(user_id)
        
        logger.info(f"User {user_id} logged in successfully")
        
        return TokenResponse(
            access_token=access_token,
            refresh_token=refresh_token,
            token_type="bearer",
            expires_in=auth_service.access_token_expire_minutes * 60
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Login failed: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Login failed"
        )


@router.post("/refresh", response_model=TokenResponse)
async def refresh_token(
    request: RefreshTokenRequest,
    auth_service: AuthService = Depends(get_auth_service)
):
    """Refresh access token using refresh token."""
    try:
        # Verify refresh token
        payload = auth_service.verify_token(request.refresh_token)
        
        if payload.get("type") != "refresh":
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid refresh token"
            )
        
        user_id = payload.get("sub")
        if not user_id:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid refresh token"
            )
        
        # Create new access token
        access_token = auth_service.create_access_token(user_id)
        
        return TokenResponse(
            access_token=access_token,
            refresh_token=request.refresh_token,  # Keep same refresh token
            token_type="bearer",
            expires_in=auth_service.access_token_expire_minutes * 60
        )
        
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(e)
        )
    except Exception as e:
        logger.error(f"Token refresh failed: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Token refresh failed"
        )


@router.post("/logout")
async def logout(
    request: Request,
    user_id: str = Depends(require_auth),
    auth_service: AuthService = Depends(get_auth_service)
):
    """Logout and revoke current token."""
    try:
        # Get token from request
        auth_header = request.headers.get("Authorization")
        if auth_header and auth_header.startswith("Bearer "):
            token = auth_header.split(" ", 1)[1]
            await auth_service.revoke_token(token)
        
        logger.info(f"User {user_id} logged out")
        
        return {"message": "Logged out successfully"}
        
    except Exception as e:
        logger.error(f"Logout failed: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Logout failed"
        )


@router.post("/api-keys", response_model=APIKeyResponse)
async def create_api_key(
    request: CreateAPIKeyRequest,
    user_id: str = Depends(require_auth),
    auth_service: AuthService = Depends(get_auth_service)
):
    """Create new API key."""
    try:
        api_key, key_id = await auth_service.generate_api_key(
            user_id=user_id,
            name=request.name,
            rate_limit=request.rate_limit,
            expires_in_days=request.expires_in_days
        )
        
        return APIKeyResponse(
            key_id=key_id,
            api_key=api_key,  # Only returned once during creation
            name=request.name,
            rate_limit_per_minute=request.rate_limit,
            expires_in_days=request.expires_in_days
        )
        
    except Exception as e:
        logger.error(f"API key creation failed: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="API key creation failed"
        )


@router.get("/api-keys", response_model=List[dict])
async def list_api_keys(
    user_id: str = Depends(require_auth),
    auth_service: AuthService = Depends(get_auth_service)
):
    """List all API keys for the authenticated user."""
    try:
        keys = await auth_service.list_api_keys(user_id)
        return keys
        
    except Exception as e:
        logger.error(f"API key listing failed: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to list API keys"
        )


@router.get("/api-keys/{key_id}")
async def get_api_key(
    key_id: str,
    user_id: str = Depends(require_auth),
    auth_service: AuthService = Depends(get_auth_service)
):
    """Get API key information."""
    try:
        key_info = await auth_service.get_api_key_info(key_id, user_id)
        return key_info
        
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(e)
        )
    except Exception as e:
        logger.error(f"API key info retrieval failed: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to get API key info"
        )


@router.delete("/api-keys/{key_id}")
async def revoke_api_key(
    key_id: str,
    user_id: str = Depends(require_auth),
    auth_service: AuthService = Depends(get_auth_service)
):
    """Revoke (deactivate) API key."""
    try:
        success = await auth_service.revoke_api_key(key_id, user_id)
        
        if not success:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Failed to revoke API key"
            )
        
        return {"message": f"API key {key_id} revoked successfully"}
        
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(e)
        )
    except Exception as e:
        logger.error(f"API key revocation failed: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to revoke API key"
        )


@router.post("/tokens", response_model=TokenResponse)
async def create_test_token(
    request: TokenCreateRequest,
    user_id: str = Depends(require_auth),  # Only authenticated users can create test tokens
    auth_service: AuthService = Depends(get_auth_service)
):
    """Create test token (for development/testing).
    
    This endpoint allows creating tokens for testing purposes.
    In production, restrict access or remove entirely.
    """
    try:
        expires_delta = timedelta(minutes=request.expires_in_minutes)
        access_token = auth_service.create_access_token(
            request.user_id,
            expires_delta=expires_delta
        )
        
        refresh_token = auth_service.create_refresh_token(request.user_id)
        
        logger.info(f"Test token created for user {request.user_id} by {user_id}")
        
        return TokenResponse(
            access_token=access_token,
            refresh_token=refresh_token,
            token_type="bearer",
            expires_in=request.expires_in_minutes * 60
        )
        
    except Exception as e:
        logger.error(f"Test token creation failed: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Test token creation failed"
        )


@router.get("/me")
async def get_current_user(
    user_id: str = Depends(require_auth)
):
    """Get current authenticated user information."""
    return {
        "user_id": user_id,
        "authenticated": True,
        "auth_method": "jwt_or_api_key"
    }


@router.post("/verify-token")
async def verify_token(
    request: Request,
    auth_service: AuthService = Depends(get_auth_service)
):
    """Verify if a token is valid."""
    try:
        # Try to get token from Authorization header
        auth_header = request.headers.get("Authorization")
        if not auth_header or not auth_header.startswith("Bearer "):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Bearer token required"
            )
        
        token = auth_header.split(" ", 1)[1]
        payload = auth_service.verify_token(token)
        
        return {
            "valid": True,
            "user_id": payload.get("sub"),
            "token_type": payload.get("type", "access"),
            "expires_at": payload.get("exp")
        }
        
    except ValueError as e:
        return {
            "valid": False,
            "error": str(e)
        }
    except Exception as e:
        logger.error(f"Token verification failed: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Token verification failed"
        )