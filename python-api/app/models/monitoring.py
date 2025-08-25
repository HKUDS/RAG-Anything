"""Monitoring and health check related models."""

from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

from .common import BaseResponse


class ComponentStatus(BaseModel):
    """Individual component health status."""
    
    name: str = Field(..., description="Component name")
    status: str = Field(..., description="Component status")
    response_time_ms: Optional[float] = Field(None, description="Response time in milliseconds")
    message: Optional[str] = Field(None, description="Status message")
    metadata: Dict[str, Any] = Field(
        default_factory=dict,
        description="Additional component metadata"
    )
    last_checked: datetime = Field(..., description="Last health check time")
    
    class Config:
        """Pydantic configuration."""
        schema_extra = {
            "example": {
                "name": "lightrag",
                "status": "healthy",
                "response_time_ms": 12.5,
                "message": "LightRAG storage is accessible",
                "metadata": {
                    "version": "0.1.0",
                    "storage_size_mb": 256.7
                },
                "last_checked": "2024-01-15T10:30:00Z"
            }
        }


class HealthStatus(BaseResponse):
    """Basic health check response."""
    
    status: str = Field(..., description="Overall health status")
    version: str = Field(..., description="Application version")
    
    class Config:
        """Pydantic configuration."""
        schema_extra = {
            "example": {
                "status": "healthy",
                "version": "1.0.0",
                "timestamp": "2024-01-15T10:30:00Z"
            }
        }


class SystemMetrics(BaseModel):
    """System performance metrics."""
    
    uptime_seconds: int = Field(..., ge=0, description="System uptime in seconds")
    total_requests: int = Field(..., ge=0, description="Total requests processed")
    active_connections: int = Field(..., ge=0, description="Current active connections")
    memory_usage_mb: float = Field(..., ge=0, description="Memory usage in MB")
    memory_usage_percent: float = Field(..., ge=0, le=100, description="Memory usage percentage")
    cpu_usage_percent: float = Field(..., ge=0, le=100, description="CPU usage percentage")
    disk_usage_percent: float = Field(..., ge=0, le=100, description="Disk usage percentage")
    disk_free_gb: float = Field(..., ge=0, description="Free disk space in GB")
    
    # Performance metrics
    avg_response_time_ms: float = Field(..., ge=0, description="Average response time")
    p95_response_time_ms: float = Field(..., ge=0, description="95th percentile response time")
    p99_response_time_ms: float = Field(..., ge=0, description="99th percentile response time")
    
    # Cache metrics
    cache_hit_rate: float = Field(..., ge=0, le=100, description="Cache hit rate percentage")
    cache_size_mb: float = Field(..., ge=0, description="Cache size in MB")
    
    # Task queue metrics
    queued_tasks: int = Field(..., ge=0, description="Number of queued background tasks")
    active_tasks: int = Field(..., ge=0, description="Number of active background tasks")
    failed_tasks: int = Field(..., ge=0, description="Number of failed tasks")
    
    class Config:
        """Pydantic configuration."""
        schema_extra = {
            "example": {
                "uptime_seconds": 86400,
                "total_requests": 15420,
                "active_connections": 12,
                "memory_usage_mb": 2048.5,
                "memory_usage_percent": 45.2,
                "cpu_usage_percent": 23.7,
                "disk_usage_percent": 67.8,
                "disk_free_gb": 125.4,
                "avg_response_time_ms": 156.7,
                "p95_response_time_ms": 892.3,
                "p99_response_time_ms": 1534.2,
                "cache_hit_rate": 87.3,
                "cache_size_mb": 512.8,
                "queued_tasks": 5,
                "active_tasks": 2,
                "failed_tasks": 1
            }
        }


class SystemStatus(BaseResponse):
    """Comprehensive system status."""
    
    status: str = Field(..., description="Overall system status")
    components: List[ComponentStatus] = Field(
        ...,
        description="Individual component statuses"
    )
    metrics: SystemMetrics = Field(..., description="System performance metrics")
    
    @property
    def is_healthy(self) -> bool:
        """Check if all components are healthy."""
        return all(
            comp.status == "healthy" 
            for comp in self.components
        )
    
    @property
    def degraded_components(self) -> List[str]:
        """Get list of degraded component names."""
        return [
            comp.name 
            for comp in self.components 
            if comp.status == "degraded"
        ]
    
    @property
    def failed_components(self) -> List[str]:
        """Get list of failed component names."""
        return [
            comp.name 
            for comp in self.components 
            if comp.status == "unhealthy"
        ]
    
    class Config:
        """Pydantic configuration."""
        schema_extra = {
            "example": {
                "status": "healthy",
                "components": [
                    {
                        "name": "lightrag",
                        "status": "healthy",
                        "response_time_ms": 12.5,
                        "last_checked": "2024-01-15T10:30:00Z"
                    },
                    {
                        "name": "redis",
                        "status": "healthy",
                        "response_time_ms": 3.2,
                        "last_checked": "2024-01-15T10:30:00Z"
                    }
                ],
                "metrics": {
                    "uptime_seconds": 86400,
                    "total_requests": 15420,
                    "active_connections": 12,
                    "memory_usage_mb": 2048.5,
                    "cpu_usage_percent": 23.7
                },
                "timestamp": "2024-01-15T10:30:00Z"
            }
        }


class MetricPoint(BaseModel):
    """Time-series metric data point."""
    
    timestamp: datetime = Field(..., description="Metric timestamp")
    value: float = Field(..., description="Metric value")
    labels: Dict[str, str] = Field(
        default_factory=dict,
        description="Metric labels"
    )


class MetricsData(BaseResponse):
    """Metrics data response."""
    
    metrics: Dict[str, List[MetricPoint]] = Field(
        ...,
        description="Metrics data by metric name"
    )
    time_range: Dict[str, datetime] = Field(
        ...,
        description="Time range of metrics"
    )
    
    class Config:
        """Pydantic configuration."""
        schema_extra = {
            "example": {
                "metrics": {
                    "request_duration_seconds": [
                        {
                            "timestamp": "2024-01-15T10:30:00Z",
                            "value": 0.156,
                            "labels": {"endpoint": "/api/v1/query/text"}
                        }
                    ]
                },
                "time_range": {
                    "start": "2024-01-15T10:00:00Z",
                    "end": "2024-01-15T10:30:00Z"
                },
                "timestamp": "2024-01-15T10:30:00Z"
            }
        }


class AlertRule(BaseModel):
    """Monitoring alert rule."""
    
    rule_id: str = Field(..., description="Alert rule identifier")
    name: str = Field(..., description="Alert rule name")
    condition: str = Field(..., description="Alert condition")
    threshold: float = Field(..., description="Alert threshold")
    severity: str = Field(..., description="Alert severity level")
    enabled: bool = Field(True, description="Whether rule is enabled")
    
    class Config:
        """Pydantic configuration."""
        schema_extra = {
            "example": {
                "rule_id": "alert_001",
                "name": "High Response Time",
                "condition": "avg_response_time_ms > threshold",
                "threshold": 1000.0,
                "severity": "warning",
                "enabled": True
            }
        }


class Alert(BaseModel):
    """Active alert."""
    
    alert_id: str = Field(..., description="Alert identifier")
    rule_id: str = Field(..., description="Associated rule ID")
    severity: str = Field(..., description="Alert severity")
    message: str = Field(..., description="Alert message")
    triggered_at: datetime = Field(..., description="When alert was triggered")
    resolved_at: Optional[datetime] = Field(None, description="When alert was resolved")
    metadata: Dict[str, Any] = Field(
        default_factory=dict,
        description="Additional alert metadata"
    )
    
    @property
    def is_resolved(self) -> bool:
        """Check if alert is resolved."""
        return self.resolved_at is not None
    
    @property
    def duration_minutes(self) -> float:
        """Get alert duration in minutes."""
        end_time = self.resolved_at or datetime.utcnow()
        return (end_time - self.triggered_at).total_seconds() / 60
    
    class Config:
        """Pydantic configuration."""
        schema_extra = {
            "example": {
                "alert_id": "alert_123",
                "rule_id": "alert_001",
                "severity": "warning",
                "message": "Average response time exceeded 1000ms",
                "triggered_at": "2024-01-15T10:15:00Z",
                "resolved_at": None,
                "metadata": {
                    "current_value": 1234.5,
                    "threshold": 1000.0
                }
            }
        }