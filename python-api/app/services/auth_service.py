"""Authentication service for JWT and API key management."""

import hashlib
import secrets
from datetime import datetime, timedelta
from typing import Dict, Any, Optional, Tuple, List

import redis
from jose import jwt
from loguru import logger
from passlib.context import CryptContext

from app.config import settings

# Password hashing context
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


class AuthService:
    """Authentication service for managing JWT tokens and API keys."""
    
    def __init__(self, redis_client: redis.Redis):
        """Initialize authentication service.
        
        Args:
            redis_client: Redis client for token/key storage
        """
        self.redis = redis_client
        self.secret_key = settings.jwt_secret_key
        self.algorithm = settings.jwt_algorithm
        self.access_token_expire_minutes = settings.access_token_expire_minutes
        
    def create_access_token(
        self,
        user_id: str,
        expires_delta: Optional[timedelta] = None,
        additional_claims: Optional[Dict[str, Any]] = None
    ) -> str:
        """Create JWT access token.
        
        Args:
            user_id: User identifier
            expires_delta: Token expiration time
            additional_claims: Additional JWT claims
            
        Returns:
            JWT token string
        """
        try:
            # Set expiration time
            if expires_delta:
                expire = datetime.utcnow() + expires_delta
            else:
                expire = datetime.utcnow() + timedelta(
                    minutes=self.access_token_expire_minutes
                )
            
            # Create token payload
            payload = {
                "sub": user_id,
                "exp": expire,
                "iat": datetime.utcnow(),
                "type": "access"
            }
            
            # Add additional claims if provided
            if additional_claims:
                payload.update(additional_claims)
            
            # Create and return JWT token
            token = jwt.encode(payload, self.secret_key, algorithm=self.algorithm)
            
            logger.info(f"Created access token for user {user_id}")
            return token
            
        except Exception as e:
            logger.error(f"Failed to create access token: {e}")
            raise RuntimeError(f"Token creation failed: {e}")
    
    def create_refresh_token(self, user_id: str) -> str:
        """Create JWT refresh token.
        
        Args:
            user_id: User identifier
            
        Returns:
            JWT refresh token string
        """
        try:
            expire = datetime.utcnow() + timedelta(days=30)  # 30 days for refresh
            
            payload = {
                "sub": user_id,
                "exp": expire,
                "iat": datetime.utcnow(),
                "type": "refresh"
            }
            
            token = jwt.encode(payload, self.secret_key, algorithm=self.algorithm)
            
            logger.info(f"Created refresh token for user {user_id}")
            return token
            
        except Exception as e:
            logger.error(f"Failed to create refresh token: {e}")
            raise RuntimeError(f"Refresh token creation failed: {e}")
    
    def verify_token(self, token: str) -> Dict[str, Any]:
        """Verify and decode JWT token.
        
        Args:
            token: JWT token string
            
        Returns:
            Token payload
            
        Raises:
            ValueError: If token is invalid or expired
        """
        try:
            payload = jwt.decode(token, self.secret_key, algorithms=[self.algorithm])
            
            # Check if token is expired
            exp_timestamp = payload.get("exp", 0)
            if datetime.fromtimestamp(exp_timestamp) < datetime.utcnow():
                raise ValueError("Token expired")
            
            return payload
            
        except jwt.ExpiredSignatureError:
            raise ValueError("Token expired")
        except jwt.InvalidTokenError as e:
            raise ValueError(f"Invalid token: {e}")
    
    async def revoke_token(self, token: str) -> bool:
        """Add token to blacklist (revoke token).
        
        Args:
            token: JWT token to revoke
            
        Returns:
            True if token was successfully revoked
        """
        try:
            # Extract token info for blacklist duration
            payload = self.verify_token(token)
            exp_timestamp = payload.get("exp", 0)
            
            # Calculate TTL (time until token would expire anyway)
            exp_datetime = datetime.fromtimestamp(exp_timestamp)
            now = datetime.utcnow()
            
            if exp_datetime <= now:
                # Token already expired, no need to blacklist
                return True
            
            ttl_seconds = int((exp_datetime - now).total_seconds())
            
            # Add to blacklist with TTL
            blacklist_key = f"blacklist:{token[-16:]}"  # Use last 16 chars as key
            await self.redis.setex(blacklist_key, ttl_seconds, "revoked")
            
            logger.info(f"Token revoked: {token[-16:]}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to revoke token: {e}")
            return False
    
    async def generate_api_key(
        self,
        user_id: str,
        name: str,
        rate_limit: int = 60,
        expires_in_days: Optional[int] = None
    ) -> Tuple[str, str]:
        """Generate new API key.
        
        Args:
            user_id: User identifier
            name: Human-readable name for the key
            rate_limit: Requests per minute limit
            expires_in_days: Expiration in days (None for no expiration)
            
        Returns:
            Tuple of (api_key, key_id)
        """
        try:
            # Generate API key
            key_id = secrets.token_hex(16)
            api_key = f"rag_api_{secrets.token_urlsafe(32)}"
            key_hash = hashlib.sha256(api_key.encode()).hexdigest()
            
            # Calculate expiration
            expires_at = None
            if expires_in_days:
                expires_at = datetime.utcnow() + timedelta(days=expires_in_days)
            
            # Store API key metadata in Redis
            key_data = {
                "key_id": key_id,
                "name": name,
                "user_id": user_id,
                "rate_limit_per_minute": str(rate_limit),
                "is_active": "true",
                "created_at": datetime.utcnow().isoformat(),
                "last_used_at": "",
            }
            
            if expires_at:
                key_data["expires_at"] = expires_at.isoformat()
            
            # Store in Redis
            redis_key = f"api_key:{key_hash}"
            await self.redis.hset(redis_key, mapping=key_data)
            
            # Set expiration on Redis key if API key expires
            if expires_at:
                expire_seconds = int((expires_at - datetime.utcnow()).total_seconds())
                await self.redis.expire(redis_key, expire_seconds)
            
            # Store key_id to hash mapping for lookups
            await self.redis.set(f"api_key_id:{key_id}", key_hash, ex=86400 * 365)  # 1 year
            
            logger.info(f"Generated API key {key_id} for user {user_id}")
            return api_key, key_id
            
        except Exception as e:
            logger.error(f"Failed to generate API key: {e}")
            raise RuntimeError(f"API key generation failed: {e}")
    
    async def get_api_key_info(self, key_id: str, user_id: str) -> Dict[str, Any]:
        """Get API key information.
        
        Args:
            key_id: API key identifier
            user_id: User identifier (for authorization)
            
        Returns:
            API key metadata
            
        Raises:
            ValueError: If key not found or access denied
        """
        try:
            # Get key hash from key_id
            key_hash = await self.redis.get(f"api_key_id:{key_id}")
            if not key_hash:
                raise ValueError("API key not found")
            
            key_hash = key_hash.decode()
            
            # Get key metadata
            key_data = await self.redis.hgetall(f"api_key:{key_hash}")
            if not key_data:
                raise ValueError("API key not found")
            
            # Convert bytes to strings
            key_data = {k.decode(): v.decode() for k, v in key_data.items()}
            
            # Check authorization
            if key_data.get("user_id") != user_id:
                raise ValueError("Access denied")
            
            # Remove sensitive information
            safe_data = {
                "key_id": key_data.get("key_id"),
                "name": key_data.get("name"),
                "rate_limit_per_minute": int(key_data.get("rate_limit_per_minute", 60)),
                "is_active": key_data.get("is_active") == "true",
                "created_at": key_data.get("created_at"),
                "last_used_at": key_data.get("last_used_at") or None,
                "expires_at": key_data.get("expires_at") or None
            }
            
            return safe_data
            
        except ValueError:
            raise
        except Exception as e:
            logger.error(f"Failed to get API key info: {e}")
            raise RuntimeError(f"API key info retrieval failed: {e}")
    
    async def list_api_keys(self, user_id: str) -> List[Dict[str, Any]]:
        """List all API keys for a user.
        
        Args:
            user_id: User identifier
            
        Returns:
            List of API key metadata
        """
        try:
            # Get all API key patterns
            pattern = "api_key:*"
            keys = []
            
            async for redis_key in self.redis.scan_iter(match=pattern):
                key_data = await self.redis.hgetall(redis_key)
                if not key_data:
                    continue
                
                # Convert bytes to strings
                key_data = {k.decode(): v.decode() for k, v in key_data.items()}
                
                # Filter by user_id
                if key_data.get("user_id") == user_id:
                    safe_data = {
                        "key_id": key_data.get("key_id"),
                        "name": key_data.get("name"),
                        "rate_limit_per_minute": int(key_data.get("rate_limit_per_minute", 60)),
                        "is_active": key_data.get("is_active") == "true",
                        "created_at": key_data.get("created_at"),
                        "last_used_at": key_data.get("last_used_at") or None,
                        "expires_at": key_data.get("expires_at") or None
                    }
                    keys.append(safe_data)
            
            return keys
            
        except Exception as e:
            logger.error(f"Failed to list API keys: {e}")
            raise RuntimeError(f"API key listing failed: {e}")
    
    async def revoke_api_key(self, key_id: str, user_id: str) -> bool:
        """Revoke (deactivate) API key.
        
        Args:
            key_id: API key identifier
            user_id: User identifier (for authorization)
            
        Returns:
            True if key was successfully revoked
        """
        try:
            # Get key hash from key_id
            key_hash = await self.redis.get(f"api_key_id:{key_id}")
            if not key_hash:
                raise ValueError("API key not found")
            
            key_hash = key_hash.decode()
            
            # Get key metadata to check ownership
            key_data = await self.redis.hgetall(f"api_key:{key_hash}")
            if not key_data:
                raise ValueError("API key not found")
            
            key_data = {k.decode(): v.decode() for k, v in key_data.items()}
            
            # Check authorization
            if key_data.get("user_id") != user_id:
                raise ValueError("Access denied")
            
            # Deactivate the key
            await self.redis.hset(f"api_key:{key_hash}", "is_active", "false")
            
            logger.info(f"API key {key_id} revoked by user {user_id}")
            return True
            
        except ValueError:
            raise
        except Exception as e:
            logger.error(f"Failed to revoke API key: {e}")
            return False
    
    def hash_password(self, password: str) -> str:
        """Hash password using bcrypt.
        
        Args:
            password: Plain text password
            
        Returns:
            Hashed password
        """
        return pwd_context.hash(password)
    
    def verify_password(self, plain_password: str, hashed_password: str) -> bool:
        """Verify password against hash.
        
        Args:
            plain_password: Plain text password
            hashed_password: Hashed password to verify against
            
        Returns:
            True if password matches
        """
        return pwd_context.verify(plain_password, hashed_password)
    
    async def cleanup_expired_tokens(self) -> int:
        """Clean up expired blacklisted tokens.
        
        Returns:
            Number of expired tokens cleaned up
        """
        try:
            pattern = "blacklist:*"
            cleaned_count = 0
            
            async for key in self.redis.scan_iter(match=pattern):
                # Redis will automatically expire these keys, but we can check TTL
                ttl = await self.redis.ttl(key)
                if ttl == -2:  # Key doesn't exist (expired)
                    cleaned_count += 1
            
            if cleaned_count > 0:
                logger.info(f"Cleaned up {cleaned_count} expired blacklist entries")
            
            return cleaned_count
            
        except Exception as e:
            logger.error(f"Failed to cleanup expired tokens: {e}")
            return 0