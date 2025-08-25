"""Rate limiting middleware using token bucket algorithm."""

import hashlib
import json
import time
from typing import Dict, Tuple, Optional

import redis
from fastapi import HTTPException, Request
from loguru import logger
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response


class TokenBucketRateLimit:
    """Token bucket rate limiting implementation."""
    
    def __init__(self, redis_client: redis.Redis):
        """Initialize rate limiter.
        
        Args:
            redis_client: Redis client for storing rate limit state
        """
        self.redis = redis_client
    
    async def is_allowed(
        self,
        key: str,
        max_requests: int,
        window_seconds: int = 60
    ) -> Tuple[bool, Dict[str, str]]:
        """Check if request is allowed using token bucket algorithm.
        
        Args:
            key: Unique identifier for the client/endpoint
            max_requests: Maximum requests allowed in the window
            window_seconds: Time window in seconds
            
        Returns:
            Tuple of (is_allowed, rate_limit_headers)
        """
        try:
            now = time.time()
            bucket_key = f"rate_limit:{key}"
            
            # Get current bucket state
            bucket_data = await self.redis.get(bucket_key)
            
            if bucket_data:
                bucket = json.loads(bucket_data.decode())
                tokens = bucket["tokens"]
                last_update = bucket["last_update"]
            else:
                # Initialize new bucket
                tokens = max_requests
                last_update = now
            
            # Add tokens based on time passed (token refill)
            time_passed = now - last_update
            tokens = min(
                max_requests,
                tokens + (time_passed * max_requests / window_seconds)
            )
            
            # Check if request is allowed
            if tokens >= 1:
                tokens -= 1
                allowed = True
            else:
                allowed = False
            
            # Save bucket state
            bucket_data = {
                "tokens": tokens,
                "last_update": now,
                "max_requests": max_requests,
                "window_seconds": window_seconds
            }
            
            # Store with TTL (2x window to handle edge cases)
            await self.redis.setex(
                bucket_key,
                window_seconds * 2,
                json.dumps(bucket_data)
            )
            
            # Calculate rate limit headers
            remaining = int(max(0, tokens))
            reset_time = int(now + window_seconds)
            
            headers = {
                "X-RateLimit-Limit": str(max_requests),
                "X-RateLimit-Remaining": str(remaining),
                "X-RateLimit-Reset": str(reset_time),
                "X-RateLimit-Window": str(window_seconds)
            }
            
            if not allowed:
                # Add retry-after header when rate limited
                retry_after = max(1, int((1 - tokens) * window_seconds / max_requests))
                headers["Retry-After"] = str(retry_after)
            
            return allowed, headers
            
        except Exception as e:
            logger.error(f"Rate limit check failed for {key}: {e}")
            # On error, allow the request but log the issue
            return True, {
                "X-RateLimit-Limit": str(max_requests),
                "X-RateLimit-Remaining": "0",
                "X-RateLimit-Reset": str(int(time.time() + window_seconds))
            }


class RateLimitMiddleware(BaseHTTPMiddleware):
    """HTTP middleware for rate limiting requests."""
    
    def __init__(self, app, redis_client: redis.Redis, default_limits: Dict[str, int] = None):
        """Initialize rate limit middleware.
        
        Args:
            app: FastAPI application
            redis_client: Redis client for rate limit storage
            default_limits: Default rate limits for different endpoint patterns
        """
        super().__init__(app)
        self.rate_limiter = TokenBucketRateLimit(redis_client)
        
        # Default rate limits (requests per minute)
        self.default_limits = default_limits or {
            "/api/v1/query/": 10,      # Query endpoints - 10 req/min
            "/api/v1/documents/": 5,   # Document processing - 5 req/min
            "/api/v1/files/": 20,      # File operations - 20 req/min
            "/api/v1/kb/": 15,         # Knowledge base ops - 15 req/min
            "/api/v1/auth/": 30,       # Auth endpoints - 30 req/min
            "default": 60              # Other endpoints - 60 req/min
        }
    
    async def dispatch(self, request: Request, call_next) -> Response:
        """Process request with rate limiting.
        
        Args:
            request: HTTP request
            call_next: Next middleware/handler
            
        Returns:
            HTTP response
        """
        try:
            # Skip rate limiting for health checks and metrics
            if request.url.path in ["/health", "/metrics", "/", "/docs", "/redoc", "/openapi.json"]:
                return await call_next(request)
            
            # Get client identifier
            client_id = self._get_client_id(request)
            
            # Get rate limit for this endpoint
            rate_limit = self._get_rate_limit_for_endpoint(request.url.path)
            
            # Create unique key for this client + endpoint combination
            rate_limit_key = f"{client_id}:{self._normalize_path(request.url.path)}"
            
            # Check rate limit
            allowed, headers = await self.rate_limiter.is_allowed(
                rate_limit_key,
                rate_limit,
                60  # 1 minute window
            )
            
            if not allowed:
                logger.warning(f"Rate limit exceeded for {client_id} on {request.url.path}")
                raise HTTPException(
                    status_code=429,
                    detail="Rate limit exceeded. Please try again later.",
                    headers=headers
                )
            
            # Process request
            response = await call_next(request)
            
            # Add rate limit headers to response
            for key, value in headers.items():
                response.headers[key] = value
            
            return response
            
        except HTTPException:
            # Re-raise HTTP exceptions (including rate limit errors)
            raise
        except Exception as e:
            logger.error(f"Rate limiting middleware error: {e}")
            # On middleware error, allow request to proceed
            return await call_next(request)
    
    def _get_client_id(self, request: Request) -> str:
        """Get unique client identifier for rate limiting.
        
        Args:
            request: HTTP request
            
        Returns:
            Unique client identifier
        """
        # Try to get from API key first (more specific)
        api_key = request.headers.get("X-API-Key")
        if api_key:
            # Use hash of API key for privacy
            return f"api_key:{hashlib.sha256(api_key.encode()).hexdigest()[:16]}"
        
        # Try JWT token
        auth_header = request.headers.get("Authorization")
        if auth_header and auth_header.startswith("Bearer "):
            token = auth_header.split(" ", 1)[1]
            # Use hash of token for privacy
            return f"jwt:{hashlib.sha256(token.encode()).hexdigest()[:16]}"
        
        # Fall back to IP address with User-Agent for better uniqueness
        client_ip = self._get_client_ip(request)
        user_agent = request.headers.get("User-Agent", "unknown")
        ua_hash = hashlib.md5(user_agent.encode()).hexdigest()[:8]
        
        return f"ip:{client_ip}:{ua_hash}"
    
    def _get_client_ip(self, request: Request) -> str:
        """Get client IP address, considering proxies.
        
        Args:
            request: HTTP request
            
        Returns:
            Client IP address
        """
        # Check for forwarded headers (common in proxy setups)
        forwarded_for = request.headers.get("X-Forwarded-For")
        if forwarded_for:
            # Take the first IP in the chain
            return forwarded_for.split(",")[0].strip()
        
        real_ip = request.headers.get("X-Real-IP")
        if real_ip:
            return real_ip
        
        # Fall back to direct client IP
        return request.client.host if request.client else "unknown"
    
    def _get_rate_limit_for_endpoint(self, path: str) -> int:
        """Get rate limit for specific endpoint.
        
        Args:
            path: Request path
            
        Returns:
            Rate limit (requests per minute)
        """
        # Check for specific path matches
        for pattern, limit in self.default_limits.items():
            if pattern != "default" and pattern in path:
                return limit
        
        # Return default limit
        return self.default_limits["default"]
    
    def _normalize_path(self, path: str) -> str:
        """Normalize path for rate limiting grouping.
        
        Args:
            path: Original request path
            
        Returns:
            Normalized path for grouping
        """
        # Group similar paths together for rate limiting
        # e.g., /api/v1/documents/123 -> /api/v1/documents/
        
        # Remove query parameters
        path = path.split("?")[0]
        
        # Group by API prefix
        if path.startswith("/api/v1/"):
            parts = path.split("/")
            if len(parts) >= 4:
                # Keep /api/v1/resource/ pattern
                return "/".join(parts[:4]) + "/"
        
        return path


class IPRateLimitMiddleware(BaseHTTPMiddleware):
    """Simple IP-based rate limiting middleware."""
    
    def __init__(self, app, redis_client: redis.Redis, max_requests: int = 100):
        """Initialize IP rate limit middleware.
        
        Args:
            app: FastAPI application
            redis_client: Redis client
            max_requests: Maximum requests per minute per IP
        """
        super().__init__(app)
        self.rate_limiter = TokenBucketRateLimit(redis_client)
        self.max_requests = max_requests
    
    async def dispatch(self, request: Request, call_next) -> Response:
        """Process request with IP-based rate limiting.
        
        Args:
            request: HTTP request
            call_next: Next middleware/handler
            
        Returns:
            HTTP response
        """
        try:
            # Skip for health endpoints
            if request.url.path in ["/health", "/metrics", "/"]:
                return await call_next(request)
            
            # Get client IP
            client_ip = self._get_client_ip(request)
            
            # Check rate limit
            allowed, headers = await self.rate_limiter.is_allowed(
                f"ip_global:{client_ip}",
                self.max_requests,
                60
            )
            
            if not allowed:
                logger.warning(f"Global IP rate limit exceeded for {client_ip}")
                raise HTTPException(
                    status_code=429,
                    detail=f"Too many requests from IP {client_ip}. Limit: {self.max_requests}/minute",
                    headers=headers
                )
            
            response = await call_next(request)
            
            # Add global rate limit headers
            for key, value in headers.items():
                response.headers[f"X-Global-{key}"] = value
            
            return response
            
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"IP rate limiting error: {e}")
            return await call_next(request)
    
    def _get_client_ip(self, request: Request) -> str:
        """Get client IP address."""
        forwarded_for = request.headers.get("X-Forwarded-For")
        if forwarded_for:
            return forwarded_for.split(",")[0].strip()
        
        real_ip = request.headers.get("X-Real-IP")
        if real_ip:
            return real_ip
        
        return request.client.host if request.client else "unknown"