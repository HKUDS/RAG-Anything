"""Security middleware for input sanitization and additional protections."""

import json
import re
import time
from datetime import datetime
from typing import Dict, Any, List
from fastapi import Request, HTTPException
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response
from loguru import logger


class InputSanitizationMiddleware(BaseHTTPMiddleware):
    """Middleware for input sanitization and validation."""
    
    def __init__(self, app):
        super().__init__(app)
        
        # Patterns for potentially malicious input
        self.dangerous_patterns = [
            # SQL injection patterns
            re.compile(r"(union\s+select|drop\s+table|insert\s+into|delete\s+from)", re.IGNORECASE),
            re.compile(r"('[^']*';\s*(drop|insert|update|delete))", re.IGNORECASE),
            re.compile(r"(--|\#|/\*|\*/)", re.IGNORECASE),
            
            # XSS patterns
            re.compile(r"<script[^>]*>", re.IGNORECASE),
            re.compile(r"javascript:", re.IGNORECASE),
            re.compile(r"on\w+\s*=", re.IGNORECASE),  # onclick, onload, etc.
            re.compile(r"expression\s*\(", re.IGNORECASE),
            
            # Path traversal patterns
            re.compile(r"\.\./", re.IGNORECASE),
            re.compile(r"\.\.\\", re.IGNORECASE),
            
            # Command injection patterns
            re.compile(r"[;&|`]", re.IGNORECASE),
            re.compile(r"\$\([^)]*\)", re.IGNORECASE),
            re.compile(r"`[^`]*`", re.IGNORECASE),
        ]
        
        # Paths to exclude from sanitization (e.g., file content)
        self.excluded_paths = [
            "/api/v1/files/upload",  # File uploads need raw content
        ]
    
    async def dispatch(self, request: Request, call_next):
        """Process request with input sanitization."""
        try:
            # Skip sanitization for excluded paths
            if any(path in str(request.url.path) for path in self.excluded_paths):
                return await call_next(request)
            
            # Skip for non-JSON requests (including file uploads)
            content_type = request.headers.get("content-type", "")
            if "application/json" not in content_type:
                # File uploads and other non-JSON requests should pass through
                response = await call_next(request)
                return response
            
            # Read and sanitize request body
            body = await request.body()
            if body:
                try:
                    data = json.loads(body)
                    
                    # Sanitize the data
                    sanitized_data = self._sanitize_data(data, request.url.path)
                    
                    # Check for malicious content
                    if self._contains_malicious_content(sanitized_data):
                        logger.warning(f"Malicious content detected in request to {request.url.path}")
                        raise HTTPException(
                            status_code=400,
                            detail="Request contains potentially malicious content"
                        )
                    
                    # Replace request body with sanitized data
                    # Import here to avoid circular imports
                    from app.utils.json_utils import safe_json_dumps
                    sanitized_body = safe_json_dumps(sanitized_data).encode()
                    
                    # Create new request with sanitized body
                    scope = request.scope.copy()
                    receive = self._create_receive(sanitized_body)
                    
                    # Create new request
                    new_request = Request(scope, receive)
                    request._body = sanitized_body
                    
                except json.JSONDecodeError:
                    # Invalid JSON, let it pass through for proper error handling
                    pass
                except Exception as e:
                    logger.error(f"Error during input sanitization: {e}")
                    # On error, let request pass through
            
            response = await call_next(request)
            return response
            
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Input sanitization middleware error: {e}", exc_info=True)
            # Don't call call_next again, just raise the exception
            raise
    
    def _sanitize_data(self, data: Any, path: str) -> Any:
        """Recursively sanitize data structure."""
        if isinstance(data, dict):
            return {key: self._sanitize_data(value, path) for key, value in data.items()}
        elif isinstance(data, list):
            return [self._sanitize_data(item, path) for item in data]
        elif isinstance(data, str):
            return self._sanitize_string(data, path)
        else:
            return data
    
    def _sanitize_string(self, text: str, path: str) -> str:
        """Sanitize string content."""
        if not text:
            return text
        
        # For query endpoints, be more permissive with content
        if "/query/" in path and len(text) > 100:
            # Only basic sanitization for long query texts
            # Remove null bytes and control characters
            sanitized = text.replace('\x00', '').replace('\r', '').replace('\n', ' ')
            # Limit excessive whitespace
            sanitized = re.sub(r'\s+', ' ', sanitized)
            return sanitized.strip()
        
        # Standard sanitization for other content
        sanitized = text
        
        # Remove null bytes and control characters
        sanitized = re.sub(r'[\x00-\x08\x0B-\x0C\x0E-\x1F\x7F]', '', sanitized)
        
        # Basic HTML encoding for < and >
        sanitized = sanitized.replace('<', '&lt;').replace('>', '&gt;')
        
        # Remove or escape dangerous characters for non-query paths
        if "/query/" not in path:
            sanitized = sanitized.replace(';', '&#59;')
            sanitized = sanitized.replace('&', '&amp;')
            sanitized = sanitized.replace('"', '&quot;')
            sanitized = sanitized.replace("'", '&#39;')
        
        return sanitized
    
    def _contains_malicious_content(self, data: Any) -> bool:
        """Check if data contains malicious patterns."""
        if isinstance(data, dict):
            return any(self._contains_malicious_content(value) for value in data.values())
        elif isinstance(data, list):
            return any(self._contains_malicious_content(item) for item in data)
        elif isinstance(data, str):
            return self._is_malicious_string(data)
        else:
            return False
    
    def _is_malicious_string(self, text: str) -> bool:
        """Check if string contains malicious patterns."""
        if not text or len(text) < 5:  # Skip very short strings
            return False
        
        # Check against dangerous patterns
        for pattern in self.dangerous_patterns:
            if pattern.search(text):
                return True
        
        return False
    
    def _create_receive(self, body: bytes):
        """Create receive callable for new request."""
        async def receive():
            return {"type": "http.request", "body": body}
        return receive


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Middleware to add security headers to responses."""
    
    def __init__(self, app):
        super().__init__(app)
        
        # Security headers to add
        self.security_headers = {
            # Prevent clickjacking
            "X-Frame-Options": "DENY",
            
            # Prevent MIME type sniffing
            "X-Content-Type-Options": "nosniff",
            
            # XSS protection
            "X-XSS-Protection": "1; mode=block",
            
            # Referrer policy
            "Referrer-Policy": "strict-origin-when-cross-origin",
            
            # Content Security Policy
            "Content-Security-Policy": (
                "default-src 'self'; "
                "script-src 'self' 'unsafe-inline'; "
                "style-src 'self' 'unsafe-inline'; "
                "img-src 'self' data: https:; "
                "connect-src 'self'; "
                "frame-ancestors 'none'; "
                "base-uri 'self'; "
                "form-action 'self'"
            ),
            
            # Permissions policy
            "Permissions-Policy": (
                "geolocation=(), "
                "microphone=(), "
                "camera=(), "
                "magnetometer=(), "
                "gyroscope=(), "
                "speaker=(), "
                "payment=(), "
                "usb=()"
            ),
            
            # Strict Transport Security (for HTTPS)
            # Note: This should only be added if served over HTTPS
            # "Strict-Transport-Security": "max-age=31536000; includeSubDomains"
        }
    
    async def dispatch(self, request: Request, call_next):
        """Add security headers to response."""
        response = await call_next(request)
        
        # Add security headers
        for header_name, header_value in self.security_headers.items():
            # Skip HSTS for non-HTTPS requests
            if header_name == "Strict-Transport-Security" and not request.url.scheme == "https":
                continue
                
            response.headers[header_name] = header_value
        
        # Remove potentially sensitive server information
        if "server" in response.headers:
            response.headers["server"] = "RAG-Anything-API"
        
        return response


class IPWhitelistMiddleware(BaseHTTPMiddleware):
    """Middleware for IP-based access control."""
    
    def __init__(self, app, allowed_ips: List[str] = None, blocked_ips: List[str] = None):
        super().__init__(app)
        self.allowed_ips = set(allowed_ips or [])
        self.blocked_ips = set(blocked_ips or [])
        
        # Convert CIDR notation to IP ranges if needed
        self._process_ip_lists()
    
    def _process_ip_lists(self):
        """Process IP lists to handle CIDR notation."""
        # For now, just handle exact IP matches
        # In production, you might want to use ipaddress module for CIDR support
        pass
    
    async def dispatch(self, request: Request, call_next):
        """Check IP-based access control."""
        client_ip = self._get_client_ip(request)
        
        # Check if IP is blocked
        if client_ip in self.blocked_ips:
            logger.warning(f"Blocked IP {client_ip} attempted access")
            raise HTTPException(status_code=403, detail="Access denied")
        
        # Check if whitelist is configured and IP is not in it
        if self.allowed_ips and client_ip not in self.allowed_ips:
            logger.warning(f"Non-whitelisted IP {client_ip} attempted access")
            raise HTTPException(status_code=403, detail="Access denied")
        
        return await call_next(request)
    
    def _get_client_ip(self, request: Request) -> str:
        """Get client IP address, considering proxies."""
        # Check for forwarded headers
        forwarded_for = request.headers.get("X-Forwarded-For")
        if forwarded_for:
            return forwarded_for.split(",")[0].strip()
        
        real_ip = request.headers.get("X-Real-IP")
        if real_ip:
            return real_ip
        
        return request.client.host if request.client else "unknown"


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    """Middleware for security-focused request logging."""
    
    def __init__(self, app, log_level: str = "INFO"):
        super().__init__(app)
        self.log_level = log_level.upper()
    
    async def dispatch(self, request: Request, call_next):
        """Log security-relevant request information."""
        start_time = time.time()
        
        # Get client information
        client_ip = self._get_client_ip(request)
        user_agent = request.headers.get("User-Agent", "unknown")
        
        # Check for suspicious patterns
        suspicious_indicators = self._check_suspicious_request(request)
        
        # Log request info if suspicious or if debug logging is enabled
        if suspicious_indicators or self.log_level == "DEBUG":
            logger.warning if suspicious_indicators else logger.debug(
                f"Request: {request.method} {request.url.path} from {client_ip} "
                f"UA: {user_agent[:100]} "
                f"Suspicious: {suspicious_indicators}"
            )
        
        response = await call_next(request)
        
        # Log response time for potential DoS detection
        response_time = time.time() - start_time
        if response_time > 5.0:  # Log slow requests
            logger.warning(
                f"Slow request: {request.method} {request.url.path} "
                f"took {response_time:.2f}s from {client_ip}"
            )
        
        # Log error responses
        if response.status_code >= 400:
            logger.warning(
                f"Error response: {response.status_code} for "
                f"{request.method} {request.url.path} from {client_ip}"
            )
        
        return response
    
    def _get_client_ip(self, request: Request) -> str:
        """Get client IP address."""
        forwarded_for = request.headers.get("X-Forwarded-For")
        if forwarded_for:
            return forwarded_for.split(",")[0].strip()
        
        return request.client.host if request.client else "unknown"
    
    def _check_suspicious_request(self, request: Request) -> List[str]:
        """Check for suspicious request patterns."""
        suspicious = []
        
        # Check URL for suspicious patterns
        path = str(request.url.path).lower()
        query = str(request.url.query).lower() if request.url.query else ""
        
        # Common attack patterns
        attack_patterns = [
            "../", "..\\", "etc/passwd", "system32", "boot.ini",
            "union select", "drop table", "<script>", "javascript:",
            "php://", "file://", "ftp://", "data:"
        ]
        
        for pattern in attack_patterns:
            if pattern in path or pattern in query:
                suspicious.append(f"attack_pattern_{pattern.replace('/', '_')}")
        
        # Check for unusual headers
        suspicious_headers = [
            "x-forwarded-host", "x-originating-ip", "x-remote-ip"
        ]
        
        for header in suspicious_headers:
            if header in request.headers:
                suspicious.append(f"suspicious_header_{header}")
        
        # Check User-Agent for common attack tools
        user_agent = request.headers.get("User-Agent", "").lower()
        attack_tools = [
            "sqlmap", "nikto", "nmap", "masscan", "burpsuite", 
            "owasp", "metasploit", "nessus", "openvas"
        ]
        
        for tool in attack_tools:
            if tool in user_agent:
                suspicious.append(f"attack_tool_{tool}")
        
        # Check for missing common headers (potential bot)
        if not request.headers.get("User-Agent"):
            suspicious.append("no_user_agent")
        
        if not request.headers.get("Accept"):
            suspicious.append("no_accept_header")
        
        return suspicious


# Utility functions for input validation

def validate_filename(filename: str) -> str:
    """Validate and sanitize filename."""
    if not filename:
        raise ValueError("Filename cannot be empty")
    
    # Remove path components
    filename = os.path.basename(filename)
    
    # Remove or replace dangerous characters
    dangerous_chars = '<>:"|?*\x00'
    for char in dangerous_chars:
        filename = filename.replace(char, '_')
    
    # Remove leading/trailing dots and spaces
    filename = filename.strip('. ')
    
    # Ensure filename is not empty after sanitization
    if not filename:
        filename = "unnamed_file"
    
    # Limit filename length
    if len(filename) > 255:
        name, ext = os.path.splitext(filename)
        filename = name[:255-len(ext)] + ext
    
    return filename


def sanitize_json_input(data: Dict[str, Any]) -> Dict[str, Any]:
    """Sanitize JSON input data."""
    def sanitize_value(value):
        if isinstance(value, str):
            # Remove null bytes and control characters
            value = re.sub(r'[\x00-\x08\x0B-\x0C\x0E-\x1F\x7F]', '', value)
            # Basic HTML encoding
            value = value.replace('<', '&lt;').replace('>', '&gt;')
            return value
        elif isinstance(value, dict):
            return {k: sanitize_value(v) for k, v in value.items()}
        elif isinstance(value, list):
            return [sanitize_value(v) for v in value]
        else:
            return value
    
    return sanitize_value(data)


def validate_uuid(uuid_string: str) -> bool:
    """Validate UUID format."""
    import uuid
    try:
        uuid.UUID(uuid_string)
        return True
    except ValueError:
        return False


def validate_kb_id(kb_id: str) -> bool:
    """Validate knowledge base ID format."""
    if not kb_id:
        return False
    
    # Only alphanumeric, hyphens, and underscores allowed
    if not re.match(r'^[a-zA-Z0-9_-]+$', kb_id):
        return False
    
    # Length constraints
    if len(kb_id) < 3 or len(kb_id) > 64:
        return False
    
    # No reserved names
    reserved = ['system', 'admin', 'api', 'default', 'test', 'temp']
    if kb_id.lower() in reserved:
        return False
    
    return True