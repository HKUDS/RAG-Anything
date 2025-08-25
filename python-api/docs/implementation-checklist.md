# RAG-Anything Python API Implementation Checklist

**VALIDATION TARGET**: 95% Quality Score Achievement

**CURRENT STATUS**: 67% Quality Score (33-point improvement needed)

This checklist provides detailed implementation guidance for addressing critical validation gaps identified in the current implementation. Each item includes specific code examples, testing requirements, and acceptance criteria.

## Critical Gap Analysis Summary

### Validation Gaps Blocking 95% Score:
1. **API Endpoints (45% coverage)** - Missing query, KB management, and file endpoints
2. **Authentication System (0%)** - No JWT/API key implementation
3. **RAG-Anything Integration** - Using fallback classes instead of actual imports
4. **Testing Infrastructure (0%)** - No test files or coverage
5. **Security Features** - No rate limiting, file validation, security headers

## Phase 1: Authentication System (BLOCKING) 🔒

**Priority**: CRITICAL - Must complete before other endpoints
**Estimated Effort**: 2-3 weeks
**Validation Impact**: +15 points

### 1.1 JWT Authentication Middleware ⚠️ MISSING

**Status**: Not implemented  
**Files to create**: `app/middleware/auth.py`, `app/services/auth_service.py`

```python
# app/middleware/auth.py
from fastapi import HTTPException, Depends
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from jose import jwt, JWTError
from datetime import datetime, timedelta
import redis
from app.config import settings

security = HTTPBearer()

class JWTAuthMiddleware:
    def __init__(self, redis_client: redis.Redis):
        self.redis = redis_client
        self.secret_key = settings.JWT_SECRET_KEY
        self.algorithm = settings.JWT_ALGORITHM
        
    async def verify_token(self, credentials: HTTPAuthorizationCredentials = Depends(security)):
        try:
            # Decode JWT token
            payload = jwt.decode(
                credentials.credentials, 
                self.secret_key, 
                algorithms=[self.algorithm]
            )
            
            # Check expiration
            if datetime.fromtimestamp(payload.get("exp", 0)) < datetime.now():
                raise HTTPException(status_code=401, detail="Token expired")
            
            # Check blacklist
            if await self.redis.get(f"blacklist:{credentials.credentials}"):
                raise HTTPException(status_code=401, detail="Token revoked")
            
            return payload.get("sub")  # Return user ID
            
        except JWTError:
            raise HTTPException(status_code=401, detail="Invalid token")

# app/services/auth_service.py
from datetime import datetime, timedelta
from jose import jwt
from passlib.context import CryptContext
import secrets

class AuthService:
    def __init__(self, redis_client):
        self.redis = redis_client
        self.pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
    
    def create_access_token(self, user_id: str, expires_delta: timedelta = None):
        if expires_delta:
            expire = datetime.utcnow() + expires_delta
        else:
            expire = datetime.utcnow() + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
        
        to_encode = {"exp": expire, "sub": user_id}
        return jwt.encode(to_encode, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM)
    
    async def revoke_token(self, token: str):
        # Add token to Redis blacklist
        await self.redis.set(f"blacklist:{token}", "revoked", ex=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60)
```

**Testing Requirements**:
```python
# tests/test_auth.py
import pytest
from fastapi.testclient import TestClient
from datetime import datetime, timedelta

@pytest.mark.asyncio
async def test_jwt_authentication_valid_token():
    # Create valid token
    token = auth_service.create_access_token("user123")
    headers = {"Authorization": f"Bearer {token}"}
    
    response = client.get("/api/v1/query/text", headers=headers, json={"query": "test"})
    assert response.status_code == 200

@pytest.mark.asyncio
async def test_jwt_authentication_expired_token():
    # Create expired token
    token = auth_service.create_access_token("user123", timedelta(seconds=-1))
    headers = {"Authorization": f"Bearer {token}"}
    
    response = client.get("/api/v1/query/text", headers=headers, json={"query": "test"})
    assert response.status_code == 401
    assert "expired" in response.json()["detail"].lower()

@pytest.mark.asyncio
async def test_jwt_authentication_revoked_token():
    token = auth_service.create_access_token("user123")
    await auth_service.revoke_token(token)
    headers = {"Authorization": f"Bearer {token}"}
    
    response = client.get("/api/v1/query/text", headers=headers, json={"query": "test"})
    assert response.status_code == 401
    assert "revoked" in response.json()["detail"].lower()
```

### 1.2 API Key Authentication System ⚠️ MISSING

**Status**: Not implemented  
**Files to create**: `app/models/api_key.py`, `app/services/api_key_service.py`

```python
# app/models/api_key.py
from sqlalchemy import Column, String, DateTime, Boolean, Integer
from sqlalchemy.ext.declarative import declarative_base
from datetime import datetime

Base = declarative_base()

class APIKey(Base):
    __tablename__ = "api_keys"
    
    id = Column(String, primary_key=True)
    name = Column(String, nullable=False)
    key_hash = Column(String, nullable=False)
    user_id = Column(String, nullable=False)
    rate_limit_per_minute = Column(Integer, default=60)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    expires_at = Column(DateTime)
    last_used_at = Column(DateTime)

# app/services/api_key_service.py
import hashlib
import secrets
from sqlalchemy.orm import Session
from app.models.api_key import APIKey

class APIKeyService:
    def __init__(self, db: Session, redis_client):
        self.db = db
        self.redis = redis_client
    
    def generate_api_key(self, user_id: str, name: str, rate_limit: int = 60) -> tuple[str, str]:
        # Generate key
        key = f"rag_api_{secrets.token_urlsafe(32)}"
        key_hash = hashlib.sha256(key.encode()).hexdigest()
        
        # Store in database
        api_key = APIKey(
            id=secrets.token_hex(16),
            name=name,
            key_hash=key_hash,
            user_id=user_id,
            rate_limit_per_minute=rate_limit
        )
        self.db.add(api_key)
        self.db.commit()
        
        return key, api_key.id
    
    async def validate_api_key(self, key: str) -> APIKey:
        key_hash = hashlib.sha256(key.encode()).hexdigest()
        
        api_key = self.db.query(APIKey).filter(
            APIKey.key_hash == key_hash,
            APIKey.is_active == True
        ).first()
        
        if not api_key:
            return None
        
        # Check expiration
        if api_key.expires_at and api_key.expires_at < datetime.utcnow():
            return None
        
        # Update last used
        api_key.last_used_at = datetime.utcnow()
        self.db.commit()
        
        return api_key
```

**Testing Requirements**:
```python
@pytest.mark.asyncio
async def test_api_key_generation():
    key, key_id = api_key_service.generate_api_key("user123", "test-key")
    assert key.startswith("rag_api_")
    assert len(key) > 40

@pytest.mark.asyncio
async def test_api_key_validation_valid():
    key, key_id = api_key_service.generate_api_key("user123", "test-key")
    api_key = await api_key_service.validate_api_key(key)
    assert api_key is not None
    assert api_key.user_id == "user123"

@pytest.mark.asyncio
async def test_api_key_validation_invalid():
    api_key = await api_key_service.validate_api_key("invalid_key")
    assert api_key is None
```

### 1.3 Rate Limiting Implementation ⚠️ MISSING

**Status**: Not implemented  
**Files to create**: `app/middleware/rate_limiting.py`

```python
# app/middleware/rate_limiting.py
from fastapi import HTTPException, Request
from starlette.middleware.base import BaseHTTPMiddleware
import redis
import time
import json

class TokenBucketRateLimit:
    def __init__(self, redis_client: redis.Redis):
        self.redis = redis_client
    
    async def is_allowed(self, key: str, max_requests: int, window_seconds: int = 60) -> tuple[bool, dict]:
        now = time.time()
        bucket_key = f"rate_limit:{key}"
        
        # Get current bucket state
        bucket_data = await self.redis.get(bucket_key)
        
        if bucket_data:
            bucket = json.loads(bucket_data)
            tokens = bucket["tokens"]
            last_update = bucket["last_update"]
        else:
            tokens = max_requests
            last_update = now
        
        # Add tokens based on time passed
        time_passed = now - last_update
        tokens = min(max_requests, tokens + (time_passed * max_requests / window_seconds))
        
        # Check if request is allowed
        if tokens >= 1:
            tokens -= 1
            allowed = True
        else:
            allowed = False
        
        # Save bucket state
        bucket_data = {
            "tokens": tokens,
            "last_update": now
        }
        await self.redis.set(bucket_key, json.dumps(bucket_data), ex=window_seconds * 2)
        
        headers = {
            "X-RateLimit-Limit": str(max_requests),
            "X-RateLimit-Remaining": str(int(tokens)),
            "X-RateLimit-Reset": str(int(now + window_seconds))
        }
        
        return allowed, headers

class RateLimitMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, redis_client: redis.Redis):
        super().__init__(app)
        self.rate_limiter = TokenBucketRateLimit(redis_client)
    
    async def dispatch(self, request: Request, call_next):
        # Get rate limit for this endpoint and user
        client_id = self._get_client_id(request)
        rate_limit = self._get_rate_limit_for_endpoint(request.url.path)
        
        allowed, headers = await self.rate_limiter.is_allowed(
            f"{client_id}:{request.url.path}",
            rate_limit
        )
        
        if not allowed:
            raise HTTPException(
                status_code=429,
                detail="Rate limit exceeded",
                headers=headers
            )
        
        response = await call_next(request)
        
        # Add rate limit headers to response
        for key, value in headers.items():
            response.headers[key] = value
        
        return response
    
    def _get_client_id(self, request: Request) -> str:
        # Try to get from API key first
        api_key = request.headers.get("X-API-Key")
        if api_key:
            return f"api_key:{hashlib.sha256(api_key.encode()).hexdigest()[:16]}"
        
        # Try JWT token
        auth_header = request.headers.get("Authorization")
        if auth_header and auth_header.startswith("Bearer "):
            token = auth_header.split(" ")[1]
            return f"jwt:{hashlib.sha256(token.encode()).hexdigest()[:16]}"
        
        # Fall back to IP address
        return f"ip:{request.client.host}"
    
    def _get_rate_limit_for_endpoint(self, path: str) -> int:
        # Different limits for different endpoints
        if "/query/" in path:
            return 10  # 10 requests per minute for queries
        elif "/documents/" in path:
            return 5   # 5 requests per minute for document processing
        else:
            return 60  # 60 requests per minute for other endpoints
```

**Testing Requirements**:
```python
@pytest.mark.asyncio
async def test_rate_limiting_allows_requests_under_limit():
    for i in range(5):
        response = client.post("/api/v1/query/text", 
                             headers=auth_headers,
                             json={"query": f"test {i}"})
        assert response.status_code == 200

@pytest.mark.asyncio
async def test_rate_limiting_blocks_requests_over_limit():
    # Exhaust rate limit
    for i in range(10):
        client.post("/api/v1/query/text", headers=auth_headers, json={"query": f"test {i}"})
    
    # This should be blocked
    response = client.post("/api/v1/query/text", 
                          headers=auth_headers,
                          json={"query": "blocked"})
    assert response.status_code == 429
    assert "rate limit" in response.json()["detail"].lower()

@pytest.mark.asyncio
async def test_rate_limiting_headers():
    response = client.post("/api/v1/query/text", 
                          headers=auth_headers,
                          json={"query": "test"})
    assert "X-RateLimit-Limit" in response.headers
    assert "X-RateLimit-Remaining" in response.headers
```

## Phase 2: Query Endpoints Implementation (BLOCKING) 🔍

**Priority**: CRITICAL - Core functionality  
**Estimated Effort**: 3-4 weeks  
**Validation Impact**: +20 points

### 2.1 RAG-Anything Direct Integration ⚠️ CRITICAL

**Status**: Using fallback classes (major blocker)  
**Files to modify**: All service files using RAG-Anything

```python
# app/services/rag_service.py - CORRECT IMPLEMENTATION
from rag_anything import RAGAnything
from rag_anything.query import query_with_multimodal_content
from rag_anything.modal_processors import (
    image_processor, 
    table_processor, 
    equation_processor,
    generic_processor
)
from lightrag import LightRAG
import asyncio
from typing import Dict, List, Any, Optional

class RAGService:
    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.rag_instance = None
        self.lightrag_instance = None
        self._initialize()
    
    def _initialize(self):
        """Initialize RAG-Anything with actual imports"""
        try:
            # Initialize LightRAG
            self.lightrag_instance = LightRAG(
                working_dir=self.config['working_dir'],
                **self.config.get('lightrag_config', {})
            )
            
            # Initialize RAG-Anything
            self.rag_instance = RAGAnything(
                lightrag=self.lightrag_instance,
                **self.config.get('rag_config', {})
            )
            
            # Validate parsers are available
            self._validate_parsers()
            
        except Exception as e:
            raise RuntimeError(f"Failed to initialize RAG-Anything: {e}")
    
    def _validate_parsers(self):
        """Validate that parsers are actually available"""
        required_parsers = ['mineru', 'docling']
        available_parsers = []
        
        try:
            import mineru
            available_parsers.append('mineru')
        except ImportError:
            pass
        
        try:
            import docling
            available_parsers.append('docling')
        except ImportError:
            pass
        
        if not available_parsers:
            raise RuntimeError("No parsers available. Install mineru or docling.")
        
        self.available_parsers = available_parsers
    
    async def process_document(self, file_path: str, parser: str = "auto", **kwargs) -> Dict[str, Any]:
        """Process document using actual RAG-Anything integration"""
        try:
            # Select parser
            if parser == "auto":
                parser = self._select_parser_by_extension(file_path)
            
            if parser not in self.available_parsers:
                raise ValueError(f"Parser {parser} not available. Available: {self.available_parsers}")
            
            # Process document
            result = await asyncio.to_thread(
                self.rag_instance.process_document,
                file_path=file_path,
                parser=parser,
                **kwargs
            )
            
            return {
                "document_id": result.get("document_id"),
                "content_statistics": result.get("stats", {}),
                "processing_time": result.get("processing_time", 0),
                "parser_used": parser,
                "status": "completed"
            }
            
        except Exception as e:
            return {
                "status": "failed",
                "error": str(e),
                "parser_used": parser
            }
    
    async def query_text(self, query: str, mode: str = "hybrid", **kwargs) -> Dict[str, Any]:
        """Execute text query using actual RAG-Anything query module"""
        try:
            # Validate mode
            valid_modes = ["hybrid", "local", "global", "naive"]
            if mode not in valid_modes:
                raise ValueError(f"Invalid mode: {mode}. Valid modes: {valid_modes}")
            
            # Execute query using LightRAG
            result = await asyncio.to_thread(
                self.lightrag_instance.query,
                query=query,
                param=mode
            )
            
            return {
                "query": query,
                "mode": mode,
                "results": result,
                "timestamp": asyncio.get_event_loop().time()
            }
            
        except Exception as e:
            raise RuntimeError(f"Query execution failed: {e}")
    
    async def query_multimodal(self, query: str, multimodal_content: List[Dict], mode: str = "hybrid") -> Dict[str, Any]:
        """Execute multimodal query with content validation"""
        try:
            # Validate multimodal content
            validated_content = await self._validate_multimodal_content(multimodal_content)
            
            # Execute multimodal query
            result = await asyncio.to_thread(
                query_with_multimodal_content,
                query=query,
                multimodal_content=validated_content,
                lightrag_instance=self.lightrag_instance,
                mode=mode
            )
            
            return {
                "query": query,
                "mode": mode,
                "multimodal_content_count": len(validated_content),
                "results": result,
                "timestamp": asyncio.get_event_loop().time()
            }
            
        except Exception as e:
            raise RuntimeError(f"Multimodal query failed: {e}")
    
    async def _validate_multimodal_content(self, content_list: List[Dict]) -> List[Dict]:
        """Validate multimodal content against modal processor schemas"""
        validated = []
        
        for content in content_list:
            content_type = content.get("type")
            
            if content_type == "image":
                # Validate image content
                if "image_path" not in content:
                    raise ValueError("Image content must have 'image_path' field")
                if not os.path.isabs(content["image_path"]):
                    raise ValueError("Image path must be absolute")
                validated.append(content)
                
            elif content_type == "table":
                # Validate table content
                required_fields = ["table_data", "table_caption"]
                for field in required_fields:
                    if field not in content:
                        raise ValueError(f"Table content must have '{field}' field")
                validated.append(content)
                
            elif content_type == "equation":
                # Validate equation content
                if "equation" not in content:
                    raise ValueError("Equation content must have 'equation' field")
                validated.append(content)
                
            else:
                raise ValueError(f"Unsupported content type: {content_type}")
        
        return validated
    
    def _select_parser_by_extension(self, file_path: str) -> str:
        """Select appropriate parser based on file extension"""
        ext = os.path.splitext(file_path)[1].lower()
        
        # Prefer mineru for PDFs, docling for Office docs
        if ext == ".pdf" and "mineru" in self.available_parsers:
            return "mineru"
        elif ext in [".docx", ".doc", ".pptx", ".ppt"] and "docling" in self.available_parsers:
            return "docling"
        else:
            return self.available_parsers[0]  # Return first available
```

### 2.2 Query Endpoints Implementation ⚠️ MISSING

**Status**: Not implemented  
**Files to create**: `app/routers/query.py`

```python
# app/routers/query.py
from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, validator
from typing import List, Dict, Any, Optional
import json
import asyncio

from app.services.rag_service import RAGService
from app.middleware.auth import JWTAuthMiddleware
from app.models.query import QueryRequest, MultimodalQueryRequest, QueryResponse

router = APIRouter(prefix="/api/v1/query", tags=["query"])

class TextQueryRequest(BaseModel):
    query: str
    mode: str = "hybrid"
    kb_id: str = "default"
    stream: bool = False
    top_k: int = 10
    
    @validator('mode')
    def validate_mode(cls, v):
        valid_modes = ["hybrid", "local", "global", "naive"]
        if v not in valid_modes:
            raise ValueError(f"Invalid mode. Must be one of: {valid_modes}")
        return v

class MultimodalContent(BaseModel):
    type: str
    image_path: Optional[str] = None
    table_data: Optional[str] = None
    table_caption: Optional[str] = None
    equation: Optional[str] = None
    
    @validator('type')
    def validate_type(cls, v):
        valid_types = ["image", "table", "equation"]
        if v not in valid_types:
            raise ValueError(f"Invalid content type. Must be one of: {valid_types}")
        return v

class MultimodalQueryRequest(BaseModel):
    query: str
    multimodal_content: List[MultimodalContent]
    mode: str = "hybrid"
    kb_id: str = "default"

@router.post("/text")
async def query_text(
    request: TextQueryRequest,
    rag_service: RAGService = Depends(),
    user_id: str = Depends(auth_middleware.verify_token)
):
    """Execute text-based query"""
    try:
        if request.stream:
            return StreamingResponse(
                _stream_query_results(rag_service, request),
                media_type="text/plain"
            )
        else:
            result = await rag_service.query_text(
                query=request.query,
                mode=request.mode,
                kb_id=request.kb_id,
                top_k=request.top_k
            )
            return {"success": True, "data": result}
            
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/multimodal")
async def query_multimodal(
    request: MultimodalQueryRequest,
    rag_service: RAGService = Depends(),
    user_id: str = Depends(auth_middleware.verify_token)
):
    """Execute multimodal query with structured content"""
    try:
        # Convert Pydantic models to dicts
        multimodal_content = [content.dict() for content in request.multimodal_content]
        
        result = await rag_service.query_multimodal(
            query=request.query,
            multimodal_content=multimodal_content,
            mode=request.mode
        )
        
        return {"success": True, "data": result}
        
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/vlm-enhanced")
async def query_vlm_enhanced(
    request: TextQueryRequest,
    rag_service: RAGService = Depends(),
    user_id: str = Depends(auth_middleware.verify_token)
):
    """Execute VLM-enhanced query with automatic image analysis"""
    try:
        result = await rag_service.query_vlm_enhanced(
            query=request.query,
            mode=request.mode,
            kb_id=request.kb_id
        )
        
        return {"success": True, "data": result}
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

async def _stream_query_results(rag_service: RAGService, request: TextQueryRequest):
    """Stream query results for long-running queries"""
    try:
        # Start query execution
        query_gen = rag_service.stream_query(
            query=request.query,
            mode=request.mode,
            kb_id=request.kb_id
        )
        
        async for chunk in query_gen:
            yield f"data: {json.dumps(chunk)}\n\n"
            
        yield f"data: {json.dumps({'status': 'complete'})}\n\n"
        
    except Exception as e:
        yield f"data: {json.dumps({'error': str(e)})}\n\n"
```

**Testing Requirements**:
```python
# tests/test_query_endpoints.py
@pytest.mark.asyncio
async def test_text_query_success():
    response = client.post(
        "/api/v1/query/text",
        headers=auth_headers,
        json={"query": "test query", "mode": "hybrid"}
    )
    assert response.status_code == 200
    assert "data" in response.json()
    assert response.json()["success"] == True

@pytest.mark.asyncio
async def test_text_query_invalid_mode():
    response = client.post(
        "/api/v1/query/text",
        headers=auth_headers,
        json={"query": "test query", "mode": "invalid_mode"}
    )
    assert response.status_code == 422

@pytest.mark.asyncio
async def test_multimodal_query_success():
    multimodal_content = [{
        "type": "table",
        "table_data": "col1,col2\nval1,val2",
        "table_caption": "Test table"
    }]
    
    response = client.post(
        "/api/v1/query/multimodal",
        headers=auth_headers,
        json={
            "query": "analyze this table",
            "multimodal_content": multimodal_content,
            "mode": "hybrid"
        }
    )
    assert response.status_code == 200

@pytest.mark.asyncio
async def test_vlm_enhanced_query():
    response = client.post(
        "/api/v1/query/vlm-enhanced",
        headers=auth_headers,
        json={"query": "analyze images in context", "mode": "hybrid"}
    )
    assert response.status_code == 200

@pytest.mark.asyncio
async def test_streaming_query():
    with client.stream("POST", 
                      "/api/v1/query/text",
                      headers=auth_headers,
                      json={"query": "streaming test", "stream": True}) as response:
        assert response.status_code == 200
        content = ""
        for chunk in response.iter_text():
            content += chunk
        assert "data:" in content
```

## Phase 3: Knowledge Base Management (BLOCKING) 🗄️

**Priority**: HIGH - Required for full functionality  
**Estimated Effort**: 2 weeks  
**Validation Impact**: +10 points

### 3.1 Knowledge Base CRUD Operations ⚠️ MISSING

**Files to create**: `app/routers/kb.py`, `app/services/kb_service.py`

```python
# app/services/kb_service.py
import os
import shutil
from pathlib import Path
from typing import Dict, List, Any, Optional
from lightrag import LightRAG

class KnowledgeBaseService:
    def __init__(self, base_storage_dir: str):
        self.base_storage_dir = Path(base_storage_dir)
        self.base_storage_dir.mkdir(exist_ok=True)
        self._active_kbs = {}
    
    def create_knowledge_base(self, kb_id: str, config: Dict[str, Any] = None) -> Dict[str, Any]:
        """Create new knowledge base with isolated storage"""
        kb_dir = self.base_storage_dir / kb_id
        
        if kb_dir.exists():
            raise ValueError(f"Knowledge base {kb_id} already exists")
        
        try:
            kb_dir.mkdir(parents=True)
            
            # Initialize LightRAG for this KB
            lightrag_config = config or {}
            lightrag_instance = LightRAG(
                working_dir=str(kb_dir),
                **lightrag_config
            )
            
            self._active_kbs[kb_id] = lightrag_instance
            
            # Create metadata file
            metadata = {
                "kb_id": kb_id,
                "created_at": datetime.utcnow().isoformat(),
                "config": lightrag_config,
                "document_count": 0,
                "total_size": 0
            }
            
            with open(kb_dir / "metadata.json", "w") as f:
                json.dump(metadata, f, indent=2)
            
            return metadata
            
        except Exception as e:
            # Cleanup on failure
            if kb_dir.exists():
                shutil.rmtree(kb_dir)
            raise RuntimeError(f"Failed to create knowledge base: {e}")
    
    def get_knowledge_base_info(self, kb_id: str) -> Dict[str, Any]:
        """Get knowledge base information and statistics"""
        kb_dir = self.base_storage_dir / kb_id
        
        if not kb_dir.exists():
            raise ValueError(f"Knowledge base {kb_id} not found")
        
        metadata_file = kb_dir / "metadata.json"
        if not metadata_file.exists():
            raise ValueError(f"Knowledge base {kb_id} metadata not found")
        
        with open(metadata_file, "r") as f:
            metadata = json.load(f)
        
        # Calculate current statistics
        stats = self._calculate_kb_statistics(kb_dir)
        metadata.update(stats)
        
        return metadata
    
    def list_documents(self, kb_id: str, offset: int = 0, limit: int = 100) -> Dict[str, Any]:
        """List documents in knowledge base with pagination"""
        if kb_id not in self._active_kbs:
            self._load_knowledge_base(kb_id)
        
        lightrag = self._active_kbs[kb_id]
        
        # Get documents from LightRAG storage
        # This is implementation-dependent on LightRAG's storage format
        documents = self._extract_documents_from_storage(lightrag, offset, limit)
        
        return {
            "kb_id": kb_id,
            "documents": documents,
            "offset": offset,
            "limit": limit,
            "total": len(documents)
        }
    
    def delete_document(self, kb_id: str, doc_id: str) -> Dict[str, Any]:
        """Remove document from knowledge base"""
        if kb_id not in self._active_kbs:
            self._load_knowledge_base(kb_id)
        
        lightrag = self._active_kbs[kb_id]
        
        try:
            # Remove from LightRAG indices
            # This requires LightRAG to support document deletion
            result = lightrag.delete_document(doc_id)
            
            return {
                "kb_id": kb_id,
                "doc_id": doc_id,
                "deleted": True,
                "cleanup_stats": result
            }
            
        except Exception as e:
            raise RuntimeError(f"Failed to delete document {doc_id}: {e}")
    
    def delete_knowledge_base(self, kb_id: str) -> Dict[str, Any]:
        """Delete entire knowledge base and cleanup storage"""
        kb_dir = self.base_storage_dir / kb_id
        
        if not kb_dir.exists():
            raise ValueError(f"Knowledge base {kb_id} not found")
        
        try:
            # Remove from active KBs
            if kb_id in self._active_kbs:
                del self._active_kbs[kb_id]
            
            # Calculate stats before deletion
            stats = self._calculate_kb_statistics(kb_dir)
            
            # Remove directory
            shutil.rmtree(kb_dir)
            
            return {
                "kb_id": kb_id,
                "deleted": True,
                "cleanup_stats": stats
            }
            
        except Exception as e:
            raise RuntimeError(f"Failed to delete knowledge base {kb_id}: {e}")
    
    def _load_knowledge_base(self, kb_id: str):
        """Load knowledge base into memory if not already loaded"""
        kb_dir = self.base_storage_dir / kb_id
        
        if not kb_dir.exists():
            raise ValueError(f"Knowledge base {kb_id} not found")
        
        metadata_file = kb_dir / "metadata.json"
        with open(metadata_file, "r") as f:
            metadata = json.load(f)
        
        lightrag_instance = LightRAG(
            working_dir=str(kb_dir),
            **metadata.get("config", {})
        )
        
        self._active_kbs[kb_id] = lightrag_instance
    
    def _calculate_kb_statistics(self, kb_dir: Path) -> Dict[str, Any]:
        """Calculate storage and content statistics"""
        total_size = sum(f.stat().st_size for f in kb_dir.rglob('*') if f.is_file())
        
        # Count documents (implementation depends on LightRAG storage format)
        doc_count = len(list(kb_dir.glob("*.json")))  # Placeholder
        
        return {
            "document_count": doc_count,
            "total_size_bytes": total_size,
            "total_size_mb": round(total_size / 1024 / 1024, 2),
            "last_updated": datetime.utcnow().isoformat()
        }

# app/routers/kb.py
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from typing import Optional, Dict, Any

router = APIRouter(prefix="/api/v1/kb", tags=["knowledge-base"])

class CreateKBRequest(BaseModel):
    kb_id: str
    config: Optional[Dict[str, Any]] = {}

@router.post("/create")
async def create_knowledge_base(
    request: CreateKBRequest,
    kb_service: KnowledgeBaseService = Depends(),
    user_id: str = Depends(auth_middleware.verify_token)
):
    """Create new knowledge base"""
    try:
        result = kb_service.create_knowledge_base(
            kb_id=request.kb_id,
            config=request.config
        )
        return {"success": True, "data": result}
        
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/{kb_id}/info")
async def get_knowledge_base_info(
    kb_id: str,
    kb_service: KnowledgeBaseService = Depends(),
    user_id: str = Depends(auth_middleware.verify_token)
):
    """Get knowledge base information and statistics"""
    try:
        info = kb_service.get_knowledge_base_info(kb_id)
        return {"success": True, "data": info}
        
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/{kb_id}/documents")
async def list_documents(
    kb_id: str,
    offset: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=1000),
    kb_service: KnowledgeBaseService = Depends(),
    user_id: str = Depends(auth_middleware.verify_token)
):
    """List documents in knowledge base with pagination"""
    try:
        documents = kb_service.list_documents(kb_id, offset, limit)
        return {"success": True, "data": documents}
        
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.delete("/{kb_id}/documents/{doc_id}")
async def delete_document(
    kb_id: str,
    doc_id: str,
    kb_service: KnowledgeBaseService = Depends(),
    user_id: str = Depends(auth_middleware.verify_token)
):
    """Remove specific document from knowledge base"""
    try:
        result = kb_service.delete_document(kb_id, doc_id)
        return {"success": True, "data": result}
        
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.delete("/{kb_id}")
async def delete_knowledge_base(
    kb_id: str,
    kb_service: KnowledgeBaseService = Depends(),
    user_id: str = Depends(auth_middleware.verify_token)
):
    """Delete entire knowledge base"""
    try:
        result = kb_service.delete_knowledge_base(kb_id)
        return {"success": True, "data": result}
        
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/{kb_id}/stats")
async def get_knowledge_base_stats(
    kb_id: str,
    kb_service: KnowledgeBaseService = Depends(),
    user_id: str = Depends(auth_middleware.verify_token)
):
    """Get detailed statistics for knowledge base"""
    try:
        info = kb_service.get_knowledge_base_info(kb_id)
        
        # Extract only statistics
        stats = {
            "kb_id": kb_id,
            "document_count": info.get("document_count", 0),
            "total_size_bytes": info.get("total_size_bytes", 0),
            "total_size_mb": info.get("total_size_mb", 0),
            "created_at": info.get("created_at"),
            "last_updated": info.get("last_updated")
        }
        
        return {"success": True, "data": stats}
        
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
```

## Phase 4: File Management System (REQUIRED) 📁

**Priority**: HIGH - Required for complete functionality  
**Estimated Effort**: 2-3 weeks  
**Validation Impact**: +8 points

### 4.1 File Upload and Management ⚠️ MISSING

**Files to create**: `app/routers/files.py`, `app/services/file_service.py`

```python
# app/services/file_service.py
import os
import uuid
import hashlib
import aiofiles
from pathlib import Path
from datetime import datetime, timedelta
from typing import Dict, List, Optional, BinaryIO
from fastapi import UploadFile
import magic

class FileService:
    def __init__(self, storage_dir: str, redis_client, max_file_size: int = 100 * 1024 * 1024):
        self.storage_dir = Path(storage_dir)
        self.storage_dir.mkdir(exist_ok=True)
        self.redis = redis_client
        self.max_file_size = max_file_size
        
        # Allowed file types
        self.allowed_types = {
            'application/pdf',
            'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
            'application/vnd.openxmlformats-officedocument.presentationml.presentation',
            'application/msword',
            'text/plain',
            'image/jpeg',
            'image/png',
            'image/tiff'
        }
    
    async def upload_file(self, file: UploadFile, user_id: str) -> Dict[str, Any]:
        """Upload single file with security validation"""
        # Validate file size
        if file.size > self.max_file_size:
            raise ValueError(f"File size {file.size} exceeds maximum {self.max_file_size}")
        
        # Generate unique file ID
        file_id = str(uuid.uuid4())
        file_extension = os.path.splitext(file.filename)[1]
        internal_filename = f"{file_id}{file_extension}"
        file_path = self.storage_dir / internal_filename
        
        try:
            # Read file content
            content = await file.read()
            
            # Validate file type using python-magic
            mime_type = magic.from_buffer(content, mime=True)
            if mime_type not in self.allowed_types:
                raise ValueError(f"File type {mime_type} not allowed")
            
            # Security scan (placeholder - integrate with antivirus)
            if await self._scan_for_malware(content):
                raise ValueError("File failed security scan")
            
            # Save file
            async with aiofiles.open(file_path, 'wb') as f:
                await f.write(content)
            
            # Calculate file hash
            file_hash = hashlib.sha256(content).hexdigest()
            
            # Store metadata in Redis
            metadata = {
                "file_id": file_id,
                "original_filename": file.filename,
                "internal_filename": internal_filename,
                "mime_type": mime_type,
                "size_bytes": len(content),
                "hash_sha256": file_hash,
                "user_id": user_id,
                "upload_date": datetime.utcnow().isoformat(),
                "expires_at": (datetime.utcnow() + timedelta(hours=24)).isoformat(),
                "processing_status": "uploaded"
            }
            
            await self.redis.hset(f"file:{file_id}", mapping=metadata)
            await self.redis.expire(f"file:{file_id}", 24 * 3600)  # 24 hour TTL
            
            return {
                "file_id": file_id,
                "filename": file.filename,
                "size": len(content),
                "mime_type": mime_type,
                "hash": file_hash,
                "upload_date": metadata["upload_date"]
            }
            
        except Exception as e:
            # Cleanup on error
            if file_path.exists():
                file_path.unlink()
            raise
    
    async def get_file_metadata(self, file_id: str, user_id: str) -> Dict[str, Any]:
        """Get file metadata with authorization check"""
        metadata = await self.redis.hgetall(f"file:{file_id}")
        
        if not metadata:
            raise ValueError(f"File {file_id} not found")
        
        # Check authorization
        if metadata.get("user_id") != user_id:
            raise PermissionError("Access denied")
        
        # Convert bytes to strings (Redis returns bytes)
        return {k.decode(): v.decode() for k, v in metadata.items()}
    
    async def delete_file(self, file_id: str, user_id: str) -> Dict[str, Any]:
        """Delete file and cleanup storage"""
        metadata = await self.get_file_metadata(file_id, user_id)
        
        # Delete physical file
        file_path = self.storage_dir / metadata["internal_filename"]
        if file_path.exists():
            file_path.unlink()
        
        # Delete metadata
        await self.redis.delete(f"file:{file_id}")
        
        return {
            "file_id": file_id,
            "deleted": True,
            "cleanup_date": datetime.utcnow().isoformat()
        }
    
    async def cleanup_expired_files(self):
        """Background task to cleanup expired files"""
        current_time = datetime.utcnow()
        
        # Get all file keys
        file_keys = await self.redis.keys("file:*")
        
        for file_key in file_keys:
            metadata = await self.redis.hgetall(file_key)
            if not metadata:
                continue
            
            expires_at = datetime.fromisoformat(metadata[b"expires_at"].decode())
            if current_time > expires_at:
                # File has expired
                file_id = metadata[b"file_id"].decode()
                internal_filename = metadata[b"internal_filename"].decode()
                
                # Delete physical file
                file_path = self.storage_dir / internal_filename
                if file_path.exists():
                    file_path.unlink()
                
                # Delete metadata
                await self.redis.delete(file_key)
                
                print(f"Cleaned up expired file: {file_id}")
    
    async def _scan_for_malware(self, content: bytes) -> bool:
        """Placeholder for malware scanning integration"""
        # Integrate with ClamAV or similar
        # For now, just check for suspicious patterns
        
        suspicious_patterns = [
            b'<script',
            b'javascript:',
            b'<?php',
            b'<%',
        ]
        
        content_lower = content.lower()
        for pattern in suspicious_patterns:
            if pattern in content_lower:
                return True  # Suspicious content found
        
        return False

# app/routers/files.py
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from fastapi.responses import FileResponse
from app.services.file_service import FileService
from app.middleware.auth import auth_middleware

router = APIRouter(prefix="/api/v1/files", tags=["files"])

@router.post("/upload")
async def upload_file(
    file: UploadFile = File(...),
    file_service: FileService = Depends(),
    user_id: str = Depends(auth_middleware.verify_token)
):
    """Upload single file with security validation"""
    try:
        result = await file_service.upload_file(file, user_id)
        return {"success": True, "data": result}
        
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/{file_id}")
async def get_file_metadata(
    file_id: str,
    file_service: FileService = Depends(),
    user_id: str = Depends(auth_middleware.verify_token)
):
    """Get file metadata"""
    try:
        metadata = await file_service.get_file_metadata(file_id, user_id)
        return {"success": True, "data": metadata}
        
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.delete("/{file_id}")
async def delete_file(
    file_id: str,
    file_service: FileService = Depends(),
    user_id: str = Depends(auth_middleware.verify_token)
):
    """Delete uploaded file"""
    try:
        result = await file_service.delete_file(file_id, user_id)
        return {"success": True, "data": result}
        
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/{file_id}/download")
async def download_file(
    file_id: str,
    file_service: FileService = Depends(),
    user_id: str = Depends(auth_middleware.verify_token)
):
    """Download uploaded file"""
    try:
        metadata = await file_service.get_file_metadata(file_id, user_id)
        file_path = file_service.storage_dir / metadata["internal_filename"]
        
        return FileResponse(
            path=file_path,
            filename=metadata["original_filename"],
            media_type=metadata["mime_type"]
        )
        
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
```

## Phase 5: Testing Infrastructure (BLOCKING) 🧪

**Priority**: CRITICAL - Required for 95% validation  
**Estimated Effort**: 3-4 weeks  
**Validation Impact**: +25 points

### 5.1 Unit Test Framework ⚠️ MISSING

**Files to create**: Test suite structure and comprehensive tests

```bash
# Test directory structure
tests/
├── __init__.py
├── conftest.py                 # Test fixtures and configuration
├── unit/
│   ├── __init__.py
│   ├── test_auth_service.py    # Authentication tests
│   ├── test_rag_service.py     # RAG integration tests
│   ├── test_file_service.py    # File management tests
│   ├── test_kb_service.py      # Knowledge base tests
│   └── test_query_service.py   # Query processing tests
├── integration/
│   ├── __init__.py
│   ├── test_auth_endpoints.py  # Auth endpoint tests
│   ├── test_query_endpoints.py # Query endpoint tests
│   ├── test_kb_endpoints.py    # KB endpoint tests
│   └── test_file_endpoints.py  # File endpoint tests
├── performance/
│   ├── __init__.py
│   ├── test_load_queries.py    # Load testing
│   └── test_concurrent_upload.py # Concurrent operations
└── security/
    ├── __init__.py
    ├── test_auth_security.py   # Auth security tests
    ├── test_input_validation.py # Input validation tests
    └── test_file_security.py   # File security tests
```

```python
# tests/conftest.py
import pytest
import asyncio
import tempfile
import shutil
from pathlib import Path
from fastapi.testclient import TestClient
import redis
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.main import app
from app.services.rag_service import RAGService
from app.services.auth_service import AuthService
from app.services.file_service import FileService
from app.services.kb_service import KnowledgeBaseService

@pytest.fixture(scope="session")
def event_loop():
    """Create event loop for async tests"""
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()

@pytest.fixture
def temp_dir():
    """Create temporary directory for tests"""
    temp_dir = tempfile.mkdtemp()
    yield Path(temp_dir)
    shutil.rmtree(temp_dir)

@pytest.fixture
def redis_client():
    """Create Redis client for tests"""
    return redis.Redis(host='localhost', port=6379, db=15, decode_responses=False)

@pytest.fixture
def test_database():
    """Create test database"""
    engine = create_engine("sqlite:///./test.db")
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    
    # Create tables
    from app.models.api_key import Base
    Base.metadata.create_all(bind=engine)
    
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()
        # Cleanup
        os.unlink("./test.db")

@pytest.fixture
def rag_service(temp_dir):
    """Create RAG service for testing"""
    config = {
        'working_dir': str(temp_dir / "rag_storage"),
        'lightrag_config': {
            'embedding_model': 'test_model'
        }
    }
    return RAGService(config)

@pytest.fixture
def auth_service(redis_client, test_database):
    """Create auth service for testing"""
    return AuthService(test_database, redis_client)

@pytest.fixture
def file_service(temp_dir, redis_client):
    """Create file service for testing"""
    return FileService(
        storage_dir=str(temp_dir / "files"),
        redis_client=redis_client,
        max_file_size=10 * 1024 * 1024  # 10MB for tests
    )

@pytest.fixture
def kb_service(temp_dir):
    """Create KB service for testing"""
    return KnowledgeBaseService(str(temp_dir / "kb_storage"))

@pytest.fixture
def client():
    """Create test client"""
    return TestClient(app)

@pytest.fixture
def auth_headers(auth_service):
    """Create authentication headers for tests"""
    token = auth_service.create_access_token("test_user_123")
    return {"Authorization": f"Bearer {token}"}

@pytest.fixture
def api_key_headers(auth_service):
    """Create API key headers for tests"""
    api_key, _ = auth_service.generate_api_key("test_user_123", "test-key")
    return {"X-API-Key": api_key}

# tests/unit/test_rag_service.py
import pytest
from unittest.mock import Mock, patch, AsyncMock
from app.services.rag_service import RAGService

class TestRAGService:
    
    @pytest.mark.asyncio
    async def test_service_initialization(self, temp_dir):
        """Test RAG service initializes correctly"""
        config = {
            'working_dir': str(temp_dir),
            'lightrag_config': {}
        }
        
        with patch('app.services.rag_service.RAGAnything') as mock_rag, \
             patch('app.services.rag_service.LightRAG') as mock_lightrag:
            
            service = RAGService(config)
            assert service.config == config
            mock_rag.assert_called_once()
            mock_lightrag.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_process_document_success(self, rag_service, temp_dir):
        """Test document processing with successful result"""
        # Create test file
        test_file = temp_dir / "test.pdf"
        test_file.write_text("test content")
        
        with patch.object(rag_service.rag_instance, 'process_document') as mock_process:
            mock_process.return_value = {
                "document_id": "doc123",
                "stats": {"pages": 1, "words": 2},
                "processing_time": 1.5
            }
            
            result = await rag_service.process_document(str(test_file))
            
            assert result["status"] == "completed"
            assert result["document_id"] == "doc123"
            assert result["processing_time"] == 1.5
            mock_process.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_query_text_valid_modes(self, rag_service):
        """Test text querying with valid modes"""
        valid_modes = ["hybrid", "local", "global", "naive"]
        
        for mode in valid_modes:
            with patch.object(rag_service.lightrag_instance, 'query') as mock_query:
                mock_query.return_value = "test result"
                
                result = await rag_service.query_text("test query", mode)
                
                assert result["query"] == "test query"
                assert result["mode"] == mode
                assert result["results"] == "test result"
                mock_query.assert_called_with(query="test query", param=mode)
    
    @pytest.mark.asyncio
    async def test_query_text_invalid_mode(self, rag_service):
        """Test text querying with invalid mode raises error"""
        with pytest.raises(ValueError) as exc_info:
            await rag_service.query_text("test query", "invalid_mode")
        
        assert "Invalid mode" in str(exc_info.value)
    
    @pytest.mark.asyncio
    async def test_multimodal_content_validation(self, rag_service):
        """Test multimodal content validation"""
        valid_content = [
            {
                "type": "table",
                "table_data": "col1,col2\nval1,val2",
                "table_caption": "Test table"
            },
            {
                "type": "image",
                "image_path": "/absolute/path/to/image.jpg"
            }
        ]
        
        result = await rag_service._validate_multimodal_content(valid_content)
        assert len(result) == 2
    
    @pytest.mark.asyncio
    async def test_multimodal_content_validation_errors(self, rag_service):
        """Test multimodal content validation with errors"""
        # Missing required field
        invalid_content = [{
            "type": "table",
            "table_data": "data"
            # missing table_caption
        }]
        
        with pytest.raises(ValueError) as exc_info:
            await rag_service._validate_multimodal_content(invalid_content)
        
        assert "table_caption" in str(exc_info.value)
        
        # Relative image path
        invalid_image = [{
            "type": "image",
            "image_path": "relative/path.jpg"
        }]
        
        with pytest.raises(ValueError) as exc_info:
            await rag_service._validate_multimodal_content(invalid_image)
        
        assert "absolute" in str(exc_info.value)

# tests/integration/test_query_endpoints.py
import pytest
from fastapi.testclient import TestClient

class TestQueryEndpoints:
    
    def test_text_query_success(self, client, auth_headers):
        """Test successful text query"""
        response = client.post(
            "/api/v1/query/text",
            headers=auth_headers,
            json={
                "query": "test query",
                "mode": "hybrid",
                "kb_id": "default"
            }
        )
        
        assert response.status_code == 200
        data = response.json()
        assert data["success"] == True
        assert "data" in data
    
    def test_text_query_invalid_mode(self, client, auth_headers):
        """Test text query with invalid mode"""
        response = client.post(
            "/api/v1/query/text",
            headers=auth_headers,
            json={
                "query": "test query",
                "mode": "invalid_mode"
            }
        )
        
        assert response.status_code == 422
    
    def test_text_query_missing_auth(self, client):
        """Test text query without authentication"""
        response = client.post(
            "/api/v1/query/text",
            json={"query": "test query"}
        )
        
        assert response.status_code == 401
    
    def test_multimodal_query_success(self, client, auth_headers):
        """Test successful multimodal query"""
        multimodal_content = [{
            "type": "table",
            "table_data": "col1,col2\nval1,val2",
            "table_caption": "Test table"
        }]
        
        response = client.post(
            "/api/v1/query/multimodal",
            headers=auth_headers,
            json={
                "query": "analyze this table",
                "multimodal_content": multimodal_content,
                "mode": "hybrid"
            }
        )
        
        assert response.status_code == 200
        data = response.json()
        assert data["success"] == True
    
    def test_vlm_enhanced_query(self, client, auth_headers):
        """Test VLM enhanced query"""
        response = client.post(
            "/api/v1/query/vlm-enhanced",
            headers=auth_headers,
            json={
                "query": "analyze images in context",
                "mode": "hybrid"
            }
        )
        
        assert response.status_code == 200
    
    @pytest.mark.asyncio
    async def test_streaming_query(self, client, auth_headers):
        """Test streaming query response"""
        with client.stream("POST",
                          "/api/v1/query/text",
                          headers=auth_headers,
                          json={
                              "query": "streaming test query",
                              "stream": True
                          }) as response:
            assert response.status_code == 200
            assert response.headers.get("content-type") == "text/plain; charset=utf-8"
            
            content_chunks = []
            for chunk in response.iter_text():
                content_chunks.append(chunk)
            
            full_content = "".join(content_chunks)
            assert "data:" in full_content
```

**Testing Requirements Summary**:

1. **Unit Tests**: >80% coverage for all service classes
2. **Integration Tests**: All endpoints tested with real requests
3. **Performance Tests**: Load testing with concurrent requests
4. **Security Tests**: Authentication, input validation, file security
5. **CI/CD Integration**: Tests run automatically on code changes

### Test Execution Commands:
```bash
# Run all tests with coverage
pytest tests/ --cov=app --cov-report=html --cov-report=term-missing

# Run only unit tests
pytest tests/unit/ -v

# Run only integration tests
pytest tests/integration/ -v

# Run security tests
pytest tests/security/ -v

# Run performance tests
pytest tests/performance/ -v --timeout=300
```

## Implementation Priority Matrix

### Critical Path for 95% Score:
1. ✅ **Phase 1: Authentication (3-4 weeks)** - BLOCKING
2. ✅ **Phase 2: Query Endpoints (3-4 weeks)** - BLOCKING  
3. ✅ **Phase 3: Knowledge Base Management (2 weeks)** - BLOCKING
4. ✅ **Phase 4: File Management (2-3 weeks)** - REQUIRED
5. ✅ **Phase 5: Testing Infrastructure (3-4 weeks)** - BLOCKING

### Validation Score Projections:
- **Current**: 67%
- **After Phase 1**: 67% + 15% = 82%
- **After Phase 2**: 82% + 20% = 102% (capped at 100%)
- **Target Achievement**: Phase 1 + Phase 2 sufficient for 95%+

### Risk Mitigation:
1. **RAG-Anything Integration Risk**: Validate actual imports work before implementing endpoints
2. **Testing Infrastructure Risk**: Set up basic test framework early in Phase 1
3. **Authentication Complexity Risk**: Start with simple JWT, add API keys later
4. **Performance Risk**: Include performance testing in Phase 5

This implementation checklist provides the detailed roadmap to achieve the 95% quality validation score by addressing all critical gaps identified in the current implementation.