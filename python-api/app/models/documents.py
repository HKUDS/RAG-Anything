"""Document processing related Pydantic models."""

from datetime import datetime
from typing import Any, Dict, List, Optional, Union

from pydantic import BaseModel, Field, validator

from .common import (
    BaseResponse,
    ContentTypeEnum,
    DeviceEnum,
    ParseMethodEnum,
    ParserTypeEnum,
    ProcessingStats,
    StatusEnum,
    TaskProgress,
)


class ProcessingConfig(BaseModel):
    """Document processing configuration."""
    
    parser: ParserTypeEnum = Field(
        ParserTypeEnum.AUTO,
        description="Parser to use for document processing"
    )
    parse_method: ParseMethodEnum = Field(
        ParseMethodEnum.AUTO,
        description="Parsing method selection"
    )
    working_dir: str = Field(
        "./storage",
        description="Working directory for processing"
    )
    config: Dict[str, Any] = Field(
        default_factory=dict,
        description="Parser-specific configuration"
    )
    
    # Processing options
    chunk_size: int = Field(
        1000,
        ge=100,
        le=4000,
        description="Text chunk size"
    )
    chunk_overlap: int = Field(
        200,
        ge=0,
        le=1000,
        description="Chunk overlap size"
    )
    enable_multimodal: bool = Field(
        True,
        description="Enable multimodal content processing"
    )
    
    # MinerU specific options
    lang: Optional[str] = Field(
        "en",
        description="Language for OCR processing"
    )
    device: DeviceEnum = Field(
        DeviceEnum.CPU,
        description="Processing device"
    )
    start_page: Optional[int] = Field(
        None,
        ge=1,
        description="Starting page for processing"
    )
    end_page: Optional[int] = Field(
        None,
        ge=1,
        description="Ending page for processing"
    )
    enable_image_processing: bool = Field(
        True,
        description="Enable image extraction and processing"
    )
    
    @validator("end_page")
    def validate_page_range(cls, v, values):
        """Validate page range."""
        if v is not None and values.get("start_page") is not None:
            if v < values["start_page"]:
                raise ValueError("end_page must be greater than or equal to start_page")
        return v
    
    class Config:
        """Pydantic configuration."""
        schema_extra = {
            "example": {
                "parser": "mineru",
                "parse_method": "auto",
                "working_dir": "./storage",
                "lang": "en",
                "device": "cpu",
                "enable_image_processing": True,
                "chunk_size": 1000,
                "chunk_overlap": 200,
                "config": {
                    "custom_option": "value"
                }
            }
        }


class DocumentProcessResult(BaseResponse):
    """Document processing result."""
    
    document_id: str = Field(..., description="Generated document identifier")
    status: StatusEnum = Field(..., description="Processing status")
    processing_time: float = Field(..., ge=0, description="Processing time in seconds")
    content_stats: ProcessingStats = Field(..., description="Content statistics")
    metadata: Dict[str, Any] = Field(
        default_factory=dict,
        description="Additional metadata"
    )
    errors: List[Dict[str, Any]] = Field(
        default_factory=list,
        description="Processing errors"
    )
    
    class Config:
        """Pydantic configuration."""
        schema_extra = {
            "example": {
                "document_id": "doc_123456",
                "status": "completed",
                "processing_time": 12.45,
                "content_stats": {
                    "total_pages": 10,
                    "text_blocks": 45,
                    "images": 3,
                    "tables": 2,
                    "equations": 1
                },
                "metadata": {
                    "filename": "research_paper.pdf",
                    "file_size": 2048576,
                    "parser_used": "mineru"
                },
                "errors": [],
                "timestamp": "2024-01-15T10:30:00Z"
            }
        }


class BatchProcessRequest(BaseModel):
    """Batch processing request."""
    
    file_ids: List[str] = Field(
        ...,
        min_items=1,
        max_items=50,
        description="List of uploaded file IDs to process"
    )
    config: ProcessingConfig = Field(
        default_factory=ProcessingConfig,
        description="Processing configuration"
    )
    max_concurrent: int = Field(
        4,
        ge=1,
        le=10,
        description="Maximum concurrent processing jobs"
    )
    kb_id: str = Field(
        "default",
        description="Target knowledge base ID"
    )
    
    class Config:
        """Pydantic configuration."""
        schema_extra = {
            "example": {
                "file_ids": ["file_001", "file_002", "file_003"],
                "config": {
                    "parser": "mineru",
                    "lang": "en",
                    "device": "cpu"
                },
                "max_concurrent": 4,
                "kb_id": "default"
            }
        }


class BatchProcessResult(BaseResponse):
    """Batch processing creation result."""
    
    job_id: str = Field(..., description="Batch job identifier")
    status: StatusEnum = Field(..., description="Job status")
    estimated_completion: Optional[datetime] = Field(
        None,
        description="Estimated completion time"
    )
    files_count: int = Field(..., ge=0, description="Number of files in batch")
    
    class Config:
        """Pydantic configuration."""
        schema_extra = {
            "example": {
                "job_id": "batch_789012",
                "status": "queued",
                "estimated_completion": "2024-01-15T10:45:00Z",
                "files_count": 3,
                "timestamp": "2024-01-15T10:30:00Z"
            }
        }


class JobFileResult(BaseModel):
    """Individual file result within a batch job."""
    
    file_id: str = Field(..., description="File identifier")
    document_id: Optional[str] = Field(None, description="Generated document ID")
    status: StatusEnum = Field(..., description="Processing status")
    error: Optional[str] = Field(None, description="Error message if failed")
    processing_time: Optional[float] = Field(None, ge=0, description="Processing time")
    content_stats: Optional[ProcessingStats] = Field(None, description="Content statistics")


class JobStatus(BaseResponse):
    """Batch job status."""
    
    job_id: str = Field(..., description="Job identifier")
    status: StatusEnum = Field(..., description="Job status")
    progress: TaskProgress = Field(..., description="Job progress")
    completed_files: int = Field(0, ge=0, description="Number of completed files")
    failed_files: int = Field(0, ge=0, description="Number of failed files")
    total_files: int = Field(..., ge=1, description="Total number of files in job")
    results: List[JobFileResult] = Field(
        default_factory=list,
        description="Individual file results"
    )
    created_at: datetime = Field(..., description="Job creation time")
    updated_at: datetime = Field(..., description="Last update time")
    estimated_completion: Optional[datetime] = Field(
        None,
        description="Estimated completion time"
    )
    error: Optional[str] = Field(None, description="Job-level error message")
    
    @property
    def success_rate(self) -> float:
        """Calculate success rate."""
        if self.total_files == 0:
            return 0.0
        return (self.completed_files / self.total_files) * 100
    
    class Config:
        """Pydantic configuration."""
        schema_extra = {
            "example": {
                "job_id": "batch_789012",
                "status": "processing",
                "progress": {
                    "current": 2,
                    "total": 3,
                    "percentage": 66.7,
                    "message": "Processing file 2 of 3"
                },
                "completed_files": 2,
                "failed_files": 0,
                "total_files": 3,
                "results": [
                    {
                        "file_id": "file_001",
                        "document_id": "doc_001",
                        "status": "completed"
                    },
                    {
                        "file_id": "file_002",
                        "document_id": "doc_002", 
                        "status": "completed"
                    },
                    {
                        "file_id": "file_003",
                        "status": "processing"
                    }
                ],
                "created_at": "2024-01-15T10:30:00Z",
                "updated_at": "2024-01-15T10:32:30Z",
                "timestamp": "2024-01-15T10:33:00Z"
            }
        }


class DocumentInfo(BaseModel):
    """Document information."""
    
    document_id: str = Field(..., description="Document identifier")
    filename: str = Field(..., description="Original filename")
    file_size: int = Field(..., ge=0, description="File size in bytes")
    content_count: int = Field(..., ge=0, description="Number of content items")
    created_at: datetime = Field(..., description="Creation timestamp")
    updated_at: datetime = Field(..., description="Last update timestamp")
    status: StatusEnum = Field(..., description="Document status")
    metadata: Dict[str, Any] = Field(
        default_factory=dict,
        description="Additional metadata"
    )
    
    class Config:
        """Pydantic configuration."""
        schema_extra = {
            "example": {
                "document_id": "doc_123456",
                "filename": "research_paper.pdf",
                "file_size": 2048576,
                "content_count": 45,
                "created_at": "2024-01-15T10:30:00Z",
                "updated_at": "2024-01-15T10:30:00Z",
                "status": "indexed",
                "metadata": {
                    "parser_used": "mineru",
                    "processing_time": 12.45,
                    "pages": 10
                }
            }
        }