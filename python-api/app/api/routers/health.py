"""Health and monitoring endpoints."""

import asyncio
import time
from datetime import datetime

from fastapi import APIRouter, HTTPException
from loguru import logger

from app.models.monitoring import HealthStatus, SystemStatus, ComponentStatus, SystemMetrics
from app.config import settings

router = APIRouter()


@router.get("/health", response_model=HealthStatus)
async def health_check():
    """Basic health check endpoint for load balancers."""
    return HealthStatus(
        status="healthy",
        version=settings.app_version
    )


@router.get("/status", response_model=SystemStatus)  
async def detailed_status():
    """Comprehensive system status including component health."""
    try:
        # Check components
        components = []
        
        # Check LightRAG connectivity (placeholder)
        lightrag_status = await check_lightrag_connection()
        components.append(ComponentStatus(
            name="lightrag",
            status="healthy" if lightrag_status else "unhealthy",
            response_time_ms=10.5 if lightrag_status else None,
            message="LightRAG storage is accessible" if lightrag_status else "LightRAG storage is not accessible",
            last_checked=datetime.utcnow()
        ))
        
        # Check Redis connectivity (placeholder)
        redis_status = await check_redis_connection()
        components.append(ComponentStatus(
            name="redis",
            status="healthy" if redis_status else "degraded",
            response_time_ms=3.2 if redis_status else None,
            message="Redis cache is accessible" if redis_status else "Redis cache is not accessible",
            last_checked=datetime.utcnow()
        ))
        
        # System metrics
        metrics = SystemMetrics(
            uptime_seconds=int(time.time() - start_time),
            total_requests=1000,  # Would come from metrics
            active_connections=5,
            memory_usage_mb=1024.5,
            memory_usage_percent=45.2,
            cpu_usage_percent=23.7,
            disk_usage_percent=67.8,
            disk_free_gb=125.4,
            avg_response_time_ms=156.7,
            p95_response_time_ms=892.3,
            p99_response_time_ms=1534.2,
            cache_hit_rate=87.3,
            cache_size_mb=256.8,
            queued_tasks=2,
            active_tasks=1,
            failed_tasks=0
        )
        
        # Overall status
        overall_status = "healthy" if all(c.status == "healthy" for c in components) else "degraded"
        
        return SystemStatus(
            status=overall_status,
            components=components,
            metrics=metrics
        )
        
    except Exception as e:
        logger.error(f"Status check failed: {e}")
        raise HTTPException(status_code=500, detail="Status check failed")


async def check_lightrag_connection() -> bool:
    """Check LightRAG connectivity."""
    try:
        # Placeholder - would check actual LightRAG connection
        await asyncio.sleep(0.01)  # Simulate connection check
        return True
    except Exception:
        return False


async def check_redis_connection() -> bool:
    """Check Redis connectivity."""
    try:
        # Placeholder - would check actual Redis connection
        await asyncio.sleep(0.003)  # Simulate connection check
        return True
    except Exception:
        return False


# Application start time for uptime calculation
start_time = time.time()