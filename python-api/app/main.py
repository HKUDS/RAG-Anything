"""Main FastAPI application."""

import json
import time
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Dict, Any

import redis.asyncio as aioredis
from fastapi import FastAPI, Request, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from loguru import logger
from prometheus_client import Counter, Histogram, generate_latest, CONTENT_TYPE_LATEST
from starlette.responses import Response

from app.config import settings
from app.models.common import ErrorResponse
from app.api.routers import documents, health, auth, query, kb, files
from app.utils.responses import SafeORJSONResponse
from app.middleware.auth import UnifiedAuthMiddleware
from app.middleware.rate_limiting import RateLimitMiddleware, IPRateLimitMiddleware
from app.middleware.security import (
    InputSanitizationMiddleware, 
    SecurityHeadersMiddleware, 
    RequestLoggingMiddleware
)
from app.services.rag_service import RAGService
from app.services.file_service import FileService

# Global Redis client
redis_client = None
auth_middleware = None
rag_service_instance = None
file_service_instance = None

# Prometheus metrics
REQUEST_COUNT = Counter(
    'raganything_requests_total',
    'Total HTTP requests',
    ['method', 'endpoint', 'status']
)

REQUEST_DURATION = Histogram(
    'raganything_request_duration_seconds',
    'HTTP request duration',
    ['endpoint']
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan manager."""
    global redis_client, auth_middleware, rag_service_instance, file_service_instance
    
    # Startup
    logger.info("Starting RAG-Anything API")
    logger.info(f"Environment: {settings.environment}")
    logger.info(f"Debug mode: {settings.debug}")
    
    try:
        # Initialize Redis connection
        redis_client = aioredis.from_url(
            settings.redis.url,
            max_connections=settings.redis.max_connections,
            retry_on_timeout=settings.redis.retry_on_timeout,
            decode_responses=True
        )
        
        # Test Redis connection
        await redis_client.ping()
        logger.info("Redis connection established")
        
        # Initialize authentication middleware
        auth_middleware = UnifiedAuthMiddleware(redis_client)
        logger.info("Authentication middleware initialized")
        
        # Set global middleware instance
        import app.middleware.auth
        app.middleware.auth.auth_middleware = auth_middleware
        
        # Initialize file service
        file_service_instance = FileService(redis_client=redis_client)
        logger.info("File service initialized")
        
        # Set global file service instance
        import app.services.file_service
        app.services.file_service.file_service = file_service_instance
        
        # Initialize RAG service
        rag_config = {
            'working_dir': settings.raganything.working_dir,
            'lightrag_dir': settings.raganything.lightrag_storage_dir,
            'chunk_size': settings.raganything.chunk_size,
            'chunk_overlap': settings.raganything.chunk_overlap
        }
        
        rag_service_instance = RAGService(config=rag_config)
        await rag_service_instance.initialize()
        logger.info("RAG service initialized")
        
        # Set global RAG service instance
        import app.services.rag_service
        app.services.rag_service.rag_service = rag_service_instance
        
    except Exception as e:
        logger.error(f"Failed to initialize services: {e}")
        raise
    
    yield
    
    # Shutdown
    logger.info("Shutting down RAG-Anything API")
    
    # Cleanup RAG service
    if rag_service_instance:
        await rag_service_instance.cleanup()
        logger.info("RAG service cleaned up")
    
    # Close Redis connection
    if redis_client:
        await redis_client.close()
        logger.info("Redis connection closed")


# Create FastAPI application with custom response class
app = FastAPI(
    title="RAG-Anything Native Python API",
    version=settings.app_version,
    default_response_class=SafeORJSONResponse,  # Use custom response for better datetime handling
    description="""
    Native Python REST API for RAG-Anything multimodal document processing and querying.
    
    This API provides direct integration with RAG-Anything Python modules, eliminating
    subprocess overhead while maintaining full feature compatibility.
    
    ## Features
    - Document processing (PDF, Office, images, text)
    - Multimodal content querying
    - VLM-enhanced visual analysis
    - Batch processing capabilities
    - Knowledge base management
    - Real-time streaming responses
    
    ## Authentication
    - API Key authentication (preferred)
    - JWT token authentication
    - Rate limiting per client
    """,
    openapi_url=settings.openapi_url if not settings.environment == "production" else None,
    docs_url=settings.docs_url if not settings.environment == "production" else None,
    redoc_url=settings.redoc_url if not settings.environment == "production" else None,
    lifespan=lifespan
)

# Security middleware (add in order of execution - last added is first executed)

# Request logging (outermost layer)
app.add_middleware(
    RequestLoggingMiddleware,
    log_level=settings.monitoring.log_level
)

# Security headers
app.add_middleware(SecurityHeadersMiddleware)

# Input sanitization (before business logic)
app.add_middleware(InputSanitizationMiddleware)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=settings.cors_methods,
    allow_headers=settings.cors_headers,
)

# Rate limiting middleware (add after Redis initialization)
@app.on_event("startup")
async def add_rate_limiting():
    """Add rate limiting middleware after Redis is initialized."""
    if redis_client:
        # Add IP-based global rate limiting
        app.add_middleware(
            IPRateLimitMiddleware,
            redis_client=redis_client,
            max_requests=1000  # 1000 requests per minute per IP
        )
        
        # Add endpoint-specific rate limiting
        app.add_middleware(
            RateLimitMiddleware,
            redis_client=redis_client
        )


@app.middleware("http")
async def metrics_middleware(request: Request, call_next):
    """Collect Prometheus metrics for requests."""
    start_time = time.time()
    
    # Call next middleware/endpoint
    response = await call_next(request)
    
    # Record metrics
    duration = time.time() - start_time
    REQUEST_COUNT.labels(
        method=request.method,
        endpoint=request.url.path,
        status=response.status_code
    ).inc()
    
    REQUEST_DURATION.labels(endpoint=request.url.path).observe(duration)
    
    return response


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    """Handle HTTP exceptions."""
    error_response = ErrorResponse(
        error=f"HTTP_{exc.status_code}",
        message=exc.detail,
        details=getattr(exc, 'details', None)
    )
    
    return SafeORJSONResponse(
        status_code=exc.status_code,
        content=error_response.dict()
    )


@app.exception_handler(Exception)
async def general_exception_handler(request: Request, exc: Exception):
    """Handle general exceptions."""
    logger.error(f"Unhandled exception: {exc}", exc_info=True)
    
    error_response = ErrorResponse(
        error="INTERNAL_SERVER_ERROR",
        message="An unexpected error occurred"
    )
    
    return SafeORJSONResponse(
        status_code=500,
        content=error_response.model_dump(mode='json')
    )


# Prometheus metrics endpoint
@app.get("/metrics", include_in_schema=False)
async def metrics():
    """Prometheus metrics endpoint."""
    return Response(
        content=generate_latest(),
        media_type=CONTENT_TYPE_LATEST
    )


# Include routers
app.include_router(health.router, prefix=settings.api_prefix, tags=["Health & Monitoring"])
app.include_router(documents.router, prefix=settings.api_prefix, tags=["Document Processing"])
app.include_router(query.router, tags=["Query Processing"])
app.include_router(kb.router, tags=["Knowledge Base Management"])
app.include_router(files.router, tags=["File Management"])
app.include_router(auth.router, tags=["Authentication"])


# Root endpoint
@app.get("/", include_in_schema=False)
async def root():
    """Root endpoint."""
    return {
        "name": settings.app_name,
        "version": settings.app_version,
        "environment": settings.environment,
        "docs_url": settings.docs_url if settings.environment != "production" else None
    }


if __name__ == "__main__":
    import uvicorn
    
    uvicorn.run(
        "app.main:app",
        host=settings.host,
        port=settings.port,
        workers=1 if settings.debug else settings.workers,
        reload=settings.debug,
        log_level=settings.monitoring.log_level.lower()
    )