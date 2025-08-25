"""Configuration management for RAG-Anything API."""

import os
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field, validator
from pydantic_settings import BaseSettings


class RedisSettings(BaseModel):
    """Redis configuration."""
    
    url: str = Field(default="redis://localhost:6379", description="Redis connection URL")
    max_connections: int = Field(default=20, description="Maximum Redis connections")
    retry_on_timeout: bool = Field(default=True, description="Retry on timeout")
    health_check_interval: int = Field(default=30, description="Health check interval in seconds")
    
    # Cache settings
    default_ttl: int = Field(default=3600, description="Default cache TTL in seconds")
    query_cache_ttl: int = Field(default=1800, description="Query cache TTL in seconds")


class AuthSettings(BaseModel):
    """Authentication configuration."""
    
    secret_key: str = Field(..., description="Secret key for JWT signing")
    algorithm: str = Field(default="HS256", description="JWT algorithm")
    access_token_expire_minutes: int = Field(default=60, description="Access token expiration")
    
    # Rate limiting
    rate_limit_requests: int = Field(default=100, description="Requests per window")
    rate_limit_window: int = Field(default=3600, description="Rate limit window in seconds")


class RAGAnythingSettings(BaseModel):
    """RAG-Anything integration settings."""
    
    working_dir: str = Field(default="./storage", description="Working directory")
    enable_image_processing: bool = Field(default=True, description="Enable image processing")
    chunk_size: int = Field(default=1000, ge=100, le=4000, description="Text chunk size")
    chunk_overlap: int = Field(default=200, ge=0, le=1000, description="Chunk overlap")
    
    # Parser settings
    default_parser: str = Field(default="auto", description="Default parser type")
    default_parse_method: str = Field(default="auto", description="Default parse method")
    default_lang: str = Field(default="en", description="Default language")
    default_device: str = Field(default="cpu", description="Default processing device")
    
    # LightRAG settings
    lightrag_storage_dir: str = Field(default="./lightrag_storage", description="LightRAG storage directory")


class FileSettings(BaseModel):
    """File upload and management settings."""
    
    upload_dir: str = Field(default="./uploads", description="Upload directory")
    temp_dir: str = Field(default="./temp", description="Temporary directory")
    max_file_size_mb: int = Field(default=100, description="Maximum file size in MB")
    max_files_per_batch: int = Field(default=50, description="Maximum files per batch")
    chunk_size_bytes: int = Field(default=1024*1024, description="Chunk size for streaming uploads")
    cleanup_interval_hours: int = Field(default=24, description="File cleanup interval in hours")
    
    # Allowed file types
    allowed_extensions: List[str] = Field(
        default=[".pdf", ".docx", ".pptx", ".jpg", ".jpeg", ".png", ".txt", ".md"],
        description="Allowed file extensions"
    )


class MonitoringSettings(BaseModel):
    """Monitoring and observability settings."""
    
    enable_metrics: bool = Field(default=True, description="Enable Prometheus metrics")
    metrics_port: int = Field(default=9090, description="Metrics server port")
    
    # Logging
    log_level: str = Field(default="INFO", description="Logging level")
    log_format: str = Field(default="json", description="Log format (json|text)")
    log_file: Optional[str] = Field(default=None, description="Log file path")
    
    # Health checks
    health_check_timeout: int = Field(default=30, description="Health check timeout")


class CelerySettings(BaseModel):
    """Celery configuration for background tasks."""
    
    broker_url: str = Field(default="redis://localhost:6379/0", description="Celery broker URL")
    result_backend: str = Field(default="redis://localhost:6379/0", description="Celery result backend")
    
    # Worker settings
    worker_prefetch_multiplier: int = Field(default=1, description="Worker prefetch multiplier")
    task_acks_late: bool = Field(default=True, description="Acknowledge tasks late")
    worker_max_tasks_per_child: int = Field(default=1000, description="Max tasks per worker child")
    
    # Task routing
    task_routes: Dict[str, str] = Field(
        default={
            "app.tasks.document_processing.*": "document_queue",
            "app.tasks.batch_processing.*": "batch_queue",
        },
        description="Task routing configuration"
    )


class Settings(BaseSettings):
    """Main application settings."""
    
    # Basic app settings
    app_name: str = Field(default="RAG-Anything API", description="Application name")
    app_version: str = Field(default="1.0.0", description="Application version")
    debug: bool = Field(default=False, description="Debug mode")
    environment: str = Field(default="development", description="Environment")
    
    # API settings
    api_prefix: str = Field(default="/api/v1", description="API prefix")
    docs_url: str = Field(default="/docs", description="OpenAPI docs URL")
    redoc_url: str = Field(default="/redoc", description="ReDoc URL")
    openapi_url: str = Field(default="/openapi.json", description="OpenAPI spec URL")
    
    # Server settings
    host: str = Field(default="0.0.0.0", description="Server host")
    port: int = Field(default=8000, description="Server port")
    workers: int = Field(default=4, description="Number of worker processes")
    
    # CORS settings
    cors_origins: List[str] = Field(
        default=["http://localhost:3000", "http://localhost:8080", "https://*.example.com"], 
        description="CORS allowed origins"
    )
    cors_methods: List[str] = Field(
        default=["GET", "POST", "PUT", "DELETE", "OPTIONS"], 
        description="CORS allowed methods"
    )
    cors_headers: List[str] = Field(
        default=[
            "Authorization", 
            "Content-Type", 
            "X-API-Key",
            "X-Requested-With",
            "Accept",
            "Origin"
        ], 
        description="CORS allowed headers"
    )
    
    # Component settings
    redis: RedisSettings = Field(default_factory=RedisSettings)
    auth: AuthSettings = Field(default_factory=lambda: AuthSettings(secret_key=os.urandom(32).hex()))
    raganything: RAGAnythingSettings = Field(default_factory=RAGAnythingSettings)
    files: FileSettings = Field(default_factory=FileSettings)
    monitoring: MonitoringSettings = Field(default_factory=MonitoringSettings)
    celery: CelerySettings = Field(default_factory=CelerySettings)
    
    # Convenience properties for backward compatibility
    @property
    def jwt_secret_key(self) -> str:
        """Get JWT secret key."""
        return self.auth.secret_key
    
    @property
    def jwt_algorithm(self) -> str:
        """Get JWT algorithm."""
        return self.auth.algorithm
    
    @property
    def access_token_expire_minutes(self) -> int:
        """Get access token expiration minutes."""
        return self.auth.access_token_expire_minutes
    
    class Config:
        """Pydantic config."""
        env_file = ".env"
        env_nested_delimiter = "__"
        case_sensitive = False
        extra = "allow"
        
    @validator("cors_origins", pre=True)
    def parse_cors_origins(cls, value: Any) -> List[str]:
        """Parse CORS origins from environment variable."""
        if isinstance(value, str):
            return [origin.strip() for origin in value.split(",")]
        return value
    
    @validator("environment")
    def validate_environment(cls, value: str) -> str:
        """Validate environment setting."""
        allowed = {"development", "staging", "production"}
        if value not in allowed:
            raise ValueError(f"Environment must be one of {allowed}")
        return value
    
    def create_directories(self) -> None:
        """Create necessary directories."""
        directories = [
            self.raganything.working_dir,
            self.raganything.lightrag_storage_dir,
            self.files.upload_dir,
            self.files.temp_dir,
        ]
        
        for directory in directories:
            os.makedirs(directory, exist_ok=True)


# Global settings instance
settings = Settings()

# Create directories on import
settings.create_directories()