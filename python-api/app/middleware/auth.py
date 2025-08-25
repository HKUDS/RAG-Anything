"""JWT Authentication Middleware."""

import hashlib
from datetime import datetime, timedelta
from typing import Optional

import redis
from fastapi import HTTPException, Depends, Request
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from jose import jwt, JWTError
from loguru import logger

from app.config import settings

security = HTTPBearer()


class JWTAuthMiddleware:
    """JWT Authentication middleware."""
    
    def __init__(self, redis_client: redis.Redis):
        """Initialize JWT auth middleware.
        
        Args:
            redis_client: Redis client for token blacklisting
        """
        self.redis = redis_client
        self.secret_key = settings.jwt_secret_key
        self.algorithm = settings.jwt_algorithm
        
    async def verify_token(
        self, 
        credentials: HTTPAuthorizationCredentials = Depends(security)
    ) -> str:
        """Verify JWT token and return user ID.
        
        Args:
            credentials: HTTP authorization credentials
            
        Returns:
            User ID from token
            
        Raises:
            HTTPException: If token is invalid, expired, or revoked
        """
        try:
            # Decode JWT token
            payload = jwt.decode(
                credentials.credentials,
                self.secret_key,
                algorithms=[self.algorithm]
            )
            
            # Check expiration
            exp_timestamp = payload.get("exp", 0)
            if datetime.fromtimestamp(exp_timestamp) < datetime.utcnow():
                raise HTTPException(status_code=401, detail="Token expired")
            
            # Check blacklist (token revocation)
            blacklist_key = f"blacklist:{credentials.credentials[-16:]}"  # Use last 16 chars as key
            if await self.redis.get(blacklist_key):
                raise HTTPException(status_code=401, detail="Token revoked")
            
            user_id = payload.get("sub")
            if not user_id:
                raise HTTPException(status_code=401, detail="Invalid token: missing subject")
                
            return user_id
            
        except JWTError as e:
            logger.warning(f"JWT validation failed: {e}")
            raise HTTPException(status_code=401, detail="Invalid token")
        except Exception as e:
            logger.error(f"Token verification error: {e}")
            raise HTTPException(status_code=500, detail="Authentication error")


class APIKeyAuthMiddleware:
    """API Key Authentication middleware."""
    
    def __init__(self, redis_client: redis.Redis):
        """Initialize API key auth middleware.
        
        Args:
            redis_client: Redis client for key validation
        """
        self.redis = redis_client
        
    async def verify_api_key(self, request: Request) -> str:
        """Verify API key and return user ID.
        
        Args:
            request: FastAPI request object
            
        Returns:
            User ID associated with API key
            
        Raises:
            HTTPException: If API key is invalid or expired
        """
        api_key = request.headers.get("X-API-Key")
        if not api_key:
            raise HTTPException(status_code=401, detail="API key required")
        
        try:
            # Hash the API key for lookup
            key_hash = hashlib.sha256(api_key.encode()).hexdigest()
            
            # Get API key metadata from Redis
            key_data = await self.redis.hgetall(f"api_key:{key_hash}")
            if not key_data:
                raise HTTPException(status_code=401, detail="Invalid API key")
            
            # Convert bytes to strings
            key_data = {k.decode(): v.decode() for k, v in key_data.items()}
            
            # Check if key is active
            if not key_data.get("is_active", "true").lower() == "true":
                raise HTTPException(status_code=401, detail="API key deactivated")
            
            # Check expiration
            expires_at = key_data.get("expires_at")
            if expires_at:
                exp_date = datetime.fromisoformat(expires_at)
                if exp_date < datetime.utcnow():
                    raise HTTPException(status_code=401, detail="API key expired")
            
            # Update last used timestamp
            await self.redis.hset(
                f"api_key:{key_hash}",
                "last_used_at",
                datetime.utcnow().isoformat()
            )
            
            return key_data.get("user_id")
            
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"API key verification error: {e}")
            raise HTTPException(status_code=500, detail="Authentication error")


class UnifiedAuthMiddleware:
    """Unified authentication middleware supporting both JWT and API key."""
    
    def __init__(self, redis_client: redis.Redis):
        """Initialize unified auth middleware.
        
        Args:
            redis_client: Redis client instance
        """
        self.jwt_auth = JWTAuthMiddleware(redis_client)
        self.api_key_auth = APIKeyAuthMiddleware(redis_client)
        
    async def authenticate(self, request: Request) -> str:
        """Authenticate request using JWT or API key.
        
        Args:
            request: FastAPI request object
            
        Returns:
            User ID
            
        Raises:
            HTTPException: If authentication fails
        """
        # Development mode bypass
        if request.headers.get("X-Development-Mode") == "true":
            # In development mode, use X-User-ID header or default
            user_id = request.headers.get("X-User-ID", "dev-user")
            logger.info(f"Development mode authentication for user: {user_id}")
            return user_id
        
        # Try API key first
        api_key = request.headers.get("X-API-Key")
        if api_key:
            return await self.api_key_auth.verify_api_key(request)
        
        # Try JWT token
        auth_header = request.headers.get("Authorization")
        if auth_header and auth_header.startswith("Bearer "):
            token = auth_header.split(" ", 1)[1]
            credentials = HTTPAuthorizationCredentials(
                scheme="Bearer",
                credentials=token
            )
            return await self.jwt_auth.verify_token(credentials)
        
        raise HTTPException(
            status_code=401,
            detail="Authentication required: provide API key or JWT token"
        )


# Global auth middleware instance (initialized in main.py)
auth_middleware: Optional[UnifiedAuthMiddleware] = None


def get_auth_middleware() -> UnifiedAuthMiddleware:
    """Get global auth middleware instance."""
    if auth_middleware is None:
        raise RuntimeError("Auth middleware not initialized")
    return auth_middleware


async def require_auth(request: Request) -> str:
    """Dependency to require authentication.
    
    Args:
        request: FastAPI request object
        
    Returns:
        User ID
    """
    middleware = get_auth_middleware()
    return await middleware.authenticate(request)