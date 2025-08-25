"""Common Pydantic models used across the API."""

from datetime import datetime
from typing import Any, Dict, Generic, List, Optional, TypeVar, Union
from enum import Enum

from pydantic import BaseModel, Field

T = TypeVar('T')


class BaseResponse(BaseModel):
    """Base response model."""
    
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    request_id: Optional[str] = Field(None, description="Request ID for tracing")

    class Config:
        """Pydantic configuration."""
        json_encoders = {
            datetime: lambda v: v.isoformat()
        }


class ErrorResponse(BaseResponse):
    """Error response model."""
    
    error: str = Field(..., description="Error code")
    message: str = Field(..., description="Human-readable error message")
    details: Optional[Dict[str, Any]] = Field(None, description="Additional error details")
    
    class Config:
        """Pydantic configuration."""
        schema_extra = {
            "example": {
                "error": "INVALID_REQUEST",
                "message": "The request body is invalid",
                "details": {
                    "field": "query",
                    "provided": None,
                    "expected": "string"
                },
                "request_id": "req_abc123",
                "timestamp": "2024-01-15T10:30:00Z"
            }
        }


class SuccessResponse(BaseResponse):
    """Success response model."""
    
    success: bool = Field(True, description="Success indicator")
    message: Optional[str] = Field(None, description="Success message")


class Pagination(BaseModel):
    """Pagination information."""
    
    page: int = Field(..., ge=1, description="Current page number")
    limit: int = Field(..., ge=1, le=100, description="Items per page")
    total: int = Field(..., ge=0, description="Total number of items")
    pages: int = Field(..., ge=0, description="Total number of pages")
    has_next: bool = Field(..., description="Whether there is a next page")
    has_prev: bool = Field(..., description="Whether there is a previous page")


class PaginatedResponse(BaseResponse, Generic[T]):
    """Generic paginated response."""
    
    items: List[T] = Field(..., description="Page items")
    pagination: Pagination = Field(..., description="Pagination information")


class StatusEnum(str, Enum):
    """Common status enumeration."""
    
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class ContentTypeEnum(str, Enum):
    """Content type enumeration."""
    
    TEXT = "text"
    IMAGE = "image"
    TABLE = "table"
    EQUATION = "equation"


class QueryModeEnum(str, Enum):
    """Query mode enumeration."""
    
    HYBRID = "hybrid"
    LOCAL = "local"
    GLOBAL = "global"
    NAIVE = "naive"


class ParserTypeEnum(str, Enum):
    """Parser type enumeration."""
    
    AUTO = "auto"
    MINERU = "mineru"
    DOCLING = "docling"


class ParseMethodEnum(str, Enum):
    """Parse method enumeration."""
    
    AUTO = "auto"
    OCR = "ocr"
    TXT = "txt"
    HYBRID = "hybrid"


class DeviceEnum(str, Enum):
    """Processing device enumeration."""
    
    CPU = "cpu"
    CUDA = "cuda"
    AUTO = "auto"


class BoundingBox(BaseModel):
    """Bounding box coordinates."""
    
    x1: float = Field(..., description="Left coordinate")
    y1: float = Field(..., description="Top coordinate")
    x2: float = Field(..., description="Right coordinate")
    y2: float = Field(..., description="Bottom coordinate")
    
    @property
    def width(self) -> float:
        """Calculate width."""
        return self.x2 - self.x1
    
    @property
    def height(self) -> float:
        """Calculate height."""
        return self.y2 - self.y1
    
    @property
    def area(self) -> float:
        """Calculate area."""
        return self.width * self.height


class SourceInfo(BaseModel):
    """Source information for content items."""
    
    document_id: str = Field(..., description="Document identifier")
    page: Optional[int] = Field(None, ge=1, description="Page number")
    bbox: Optional[BoundingBox] = Field(None, description="Bounding box coordinates")
    chunk_id: Optional[str] = Field(None, description="Chunk identifier")
    section: Optional[str] = Field(None, description="Document section")
    filename: Optional[str] = Field(None, description="Original filename")


class ProcessingStats(BaseModel):
    """Processing statistics."""
    
    total_pages: int = Field(0, ge=0, description="Total pages processed")
    text_blocks: int = Field(0, ge=0, description="Number of text blocks")
    images: int = Field(0, ge=0, description="Number of images")
    tables: int = Field(0, ge=0, description="Number of tables")
    equations: int = Field(0, ge=0, description="Number of equations")
    processing_time: float = Field(0, ge=0, description="Processing time in seconds")
    file_size: Optional[int] = Field(None, ge=0, description="File size in bytes")


class ValidationError(BaseModel):
    """Validation error details."""
    
    field: str = Field(..., description="Field name")
    message: str = Field(..., description="Error message")
    invalid_value: Any = Field(None, description="Invalid value provided")
    expected_type: Optional[str] = Field(None, description="Expected type or format")


class TaskProgress(BaseModel):
    """Task progress information."""
    
    current: int = Field(0, ge=0, description="Current progress value")
    total: int = Field(1, ge=1, description="Total progress value")
    percentage: float = Field(0, ge=0, le=100, description="Progress percentage")
    message: Optional[str] = Field(None, description="Progress message")
    
    @property
    def is_complete(self) -> bool:
        """Check if task is complete."""
        return self.current >= self.total