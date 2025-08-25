"""Security utilities and validators."""

import hashlib
import hmac
import re
import secrets
from typing import Optional, List, Dict, Any
from datetime import datetime, timedelta


class SecurityValidator:
    """Security validation utilities."""
    
    @staticmethod
    def validate_password_strength(password: str) -> Dict[str, Any]:
        """Validate password strength.
        
        Args:
            password: Password to validate
            
        Returns:
            Validation result with score and recommendations
        """
        if not password:
            return {
                "valid": False,
                "score": 0,
                "issues": ["Password is required"],
                "recommendations": ["Provide a password"]
            }
        
        issues = []
        recommendations = []
        score = 0
        
        # Length check
        if len(password) < 8:
            issues.append("Password too short")
            recommendations.append("Use at least 8 characters")
        elif len(password) >= 12:
            score += 2
        else:
            score += 1
        
        # Character variety checks
        if not re.search(r'[a-z]', password):
            issues.append("Missing lowercase letter")
            recommendations.append("Include lowercase letters")
        else:
            score += 1
        
        if not re.search(r'[A-Z]', password):
            issues.append("Missing uppercase letter")
            recommendations.append("Include uppercase letters")
        else:
            score += 1
        
        if not re.search(r'\d', password):
            issues.append("Missing number")
            recommendations.append("Include numbers")
        else:
            score += 1
        
        if not re.search(r'[!@#$%^&*()_+\-=\[\]{};\':"\\|,.<>/?]', password):
            issues.append("Missing special character")
            recommendations.append("Include special characters")
        else:
            score += 2
        
        # Common patterns check
        common_patterns = [
            r'123456', r'password', r'qwerty', r'abc123',
            r'admin', r'root', r'test', r'user'
        ]
        
        for pattern in common_patterns:
            if re.search(pattern, password, re.IGNORECASE):
                issues.append("Contains common pattern")
                recommendations.append("Avoid common passwords and patterns")
                score -= 2
                break
        
        # Sequential characters
        if re.search(r'(.)\1{2,}', password):
            issues.append("Contains repeated characters")
            recommendations.append("Avoid repeated characters")
            score -= 1
        
        return {
            "valid": len(issues) == 0 and score >= 4,
            "score": max(0, score),
            "issues": issues,
            "recommendations": recommendations
        }
    
    @staticmethod
    def sanitize_filename(filename: str, max_length: int = 255) -> str:
        """Sanitize filename for safe storage.
        
        Args:
            filename: Original filename
            max_length: Maximum allowed length
            
        Returns:
            Sanitized filename
        """
        if not filename:
            return "unnamed_file"
        
        # Remove path components
        filename = filename.split('/')[-1].split('\\')[-1]
        
        # Remove dangerous characters
        dangerous_chars = '<>:"|?*\x00\r\n\t'
        for char in dangerous_chars:
            filename = filename.replace(char, '_')
        
        # Replace multiple underscores with single
        filename = re.sub(r'_{2,}', '_', filename)
        
        # Remove leading/trailing dots and spaces
        filename = filename.strip('. _')
        
        # Ensure not empty
        if not filename:
            filename = "unnamed_file"
        
        # Truncate if too long, preserving extension
        if len(filename) > max_length:
            name, ext = filename.rsplit('.', 1) if '.' in filename else (filename, '')
            if ext:
                name = name[:max_length - len(ext) - 1]
                filename = f"{name}.{ext}"
            else:
                filename = filename[:max_length]
        
        return filename
    
    @staticmethod
    def validate_api_key_format(api_key: str) -> bool:
        """Validate API key format.
        
        Args:
            api_key: API key to validate
            
        Returns:
            True if format is valid
        """
        if not api_key:
            return False
        
        # Expected format: rag_api_<base64url>
        pattern = r'^rag_api_[A-Za-z0-9_-]{32,}$'
        return bool(re.match(pattern, api_key))
    
    @staticmethod
    def generate_secure_token(length: int = 32) -> str:
        """Generate cryptographically secure token.
        
        Args:
            length: Token length in bytes
            
        Returns:
            URL-safe base64 encoded token
        """
        return secrets.token_urlsafe(length)
    
    @staticmethod
    def constant_time_compare(a: str, b: str) -> bool:
        """Compare strings in constant time to prevent timing attacks.
        
        Args:
            a: First string
            b: Second string
            
        Returns:
            True if strings are equal
        """
        return hmac.compare_digest(a.encode(), b.encode())
    
    @staticmethod
    def hash_sensitive_data(data: str, salt: Optional[str] = None) -> tuple[str, str]:
        """Hash sensitive data with salt.
        
        Args:
            data: Data to hash
            salt: Optional salt (generated if not provided)
            
        Returns:
            Tuple of (hash, salt)
        """
        if salt is None:
            salt = secrets.token_hex(32)
        
        # Use SHA-256 with salt
        hash_obj = hashlib.sha256()
        hash_obj.update(salt.encode())
        hash_obj.update(data.encode())
        
        return hash_obj.hexdigest(), salt
    
    @staticmethod
    def verify_hash(data: str, hash_value: str, salt: str) -> bool:
        """Verify hashed data.
        
        Args:
            data: Original data
            hash_value: Expected hash
            salt: Salt used in hashing
            
        Returns:
            True if hash matches
        """
        computed_hash, _ = SecurityValidator.hash_sensitive_data(data, salt)
        return SecurityValidator.constant_time_compare(computed_hash, hash_value)


class ContentValidator:
    """Content validation utilities."""
    
    MALICIOUS_PATTERNS = [
        # Script injection
        re.compile(r'<script[^>]*>.*?</script>', re.IGNORECASE | re.DOTALL),
        re.compile(r'javascript:', re.IGNORECASE),
        re.compile(r'on\w+\s*=', re.IGNORECASE),
        
        # SQL injection
        re.compile(r'union\s+select', re.IGNORECASE),
        re.compile(r'drop\s+table', re.IGNORECASE),
        re.compile(r'insert\s+into', re.IGNORECASE),
        re.compile(r'delete\s+from', re.IGNORECASE),
        re.compile(r'update\s+\w+\s+set', re.IGNORECASE),
        
        # Command injection
        re.compile(r'[;&|`$]\s*\w+', re.IGNORECASE),
        re.compile(r'\$\([^)]*\)', re.IGNORECASE),
        
        # Path traversal
        re.compile(r'\.\.[\\/]', re.IGNORECASE),
        re.compile(r'[\\/]etc[\\/]', re.IGNORECASE),
        re.compile(r'[\\/]proc[\\/]', re.IGNORECASE),
    ]
    
    @classmethod
    def scan_content(cls, content: str, max_length: int = 1000000) -> Dict[str, Any]:
        """Scan content for malicious patterns.
        
        Args:
            content: Content to scan
            max_length: Maximum allowed content length
            
        Returns:
            Scan result with threats found
        """
        if not content:
            return {"safe": True, "threats": [], "truncated": False}
        
        # Check length
        truncated = False
        if len(content) > max_length:
            content = content[:max_length]
            truncated = True
        
        threats = []
        
        # Check for malicious patterns
        for i, pattern in enumerate(cls.MALICIOUS_PATTERNS):
            if pattern.search(content):
                threat_types = [
                    "script_injection", "script_injection", "script_injection",  # 0-2
                    "sql_injection", "sql_injection", "sql_injection", "sql_injection", "sql_injection",  # 3-7
                    "command_injection", "command_injection",  # 8-9
                    "path_traversal", "path_traversal", "path_traversal"  # 10-12
                ]
                
                threat_type = threat_types[i] if i < len(threat_types) else "unknown"
                threats.append(threat_type)
        
        # Remove duplicates
        threats = list(set(threats))
        
        return {
            "safe": len(threats) == 0,
            "threats": threats,
            "truncated": truncated,
            "content_length": len(content)
        }
    
    @staticmethod
    def validate_json_structure(data: Any, max_depth: int = 10, current_depth: int = 0) -> bool:
        """Validate JSON structure to prevent DoS attacks.
        
        Args:
            data: JSON data to validate
            max_depth: Maximum nesting depth
            current_depth: Current nesting level
            
        Returns:
            True if structure is safe
        """
        if current_depth > max_depth:
            return False
        
        if isinstance(data, dict):
            if len(data) > 1000:  # Limit object size
                return False
            
            for key, value in data.items():
                if not isinstance(key, str) or len(key) > 256:  # Limit key length
                    return False
                
                if not ContentValidator.validate_json_structure(value, max_depth, current_depth + 1):
                    return False
        
        elif isinstance(data, list):
            if len(data) > 10000:  # Limit array size
                return False
            
            for item in data:
                if not ContentValidator.validate_json_structure(item, max_depth, current_depth + 1):
                    return False
        
        elif isinstance(data, str):
            if len(data) > 100000:  # Limit string length
                return False
        
        return True


class RateLimitTracker:
    """Rate limit tracking utilities."""
    
    def __init__(self):
        self.attempts: Dict[str, List[datetime]] = {}
        self.blocked: Dict[str, datetime] = {}
    
    def is_allowed(self, identifier: str, max_attempts: int, window_minutes: int, 
                   block_minutes: int = 15) -> bool:
        """Check if request is allowed based on rate limits.
        
        Args:
            identifier: Unique identifier (IP, user_id, etc.)
            max_attempts: Maximum attempts in window
            window_minutes: Time window in minutes
            block_minutes: Block duration after limit exceeded
            
        Returns:
            True if request is allowed
        """
        now = datetime.utcnow()
        
        # Check if currently blocked
        if identifier in self.blocked:
            if now < self.blocked[identifier]:
                return False
            else:
                # Block period expired
                del self.blocked[identifier]
        
        # Initialize attempt list
        if identifier not in self.attempts:
            self.attempts[identifier] = []
        
        # Clean old attempts
        window_start = now - timedelta(minutes=window_minutes)
        self.attempts[identifier] = [
            attempt for attempt in self.attempts[identifier]
            if attempt > window_start
        ]
        
        # Check if limit exceeded
        if len(self.attempts[identifier]) >= max_attempts:
            # Block for specified duration
            self.blocked[identifier] = now + timedelta(minutes=block_minutes)
            return False
        
        # Record this attempt
        self.attempts[identifier].append(now)
        return True
    
    def cleanup_old_data(self, hours: int = 24):
        """Clean up old tracking data.
        
        Args:
            hours: Age threshold in hours
        """
        cutoff = datetime.utcnow() - timedelta(hours=hours)
        
        # Clean attempts
        for identifier in list(self.attempts.keys()):
            self.attempts[identifier] = [
                attempt for attempt in self.attempts[identifier]
                if attempt > cutoff
            ]
            
            if not self.attempts[identifier]:
                del self.attempts[identifier]
        
        # Clean expired blocks
        now = datetime.utcnow()
        self.blocked = {
            identifier: expiry
            for identifier, expiry in self.blocked.items()
            if expiry > now
        }