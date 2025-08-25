"""File management related Pydantic models."""

from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field, validator

from .common import (
    BaseResponse,
    StatusEnum,
)


class FileUploadResult(BaseResponse):
    """File upload result."""
    
    file_id: str = Field(..., description="Unique file identifier")
    filename: str = Field(..., description="Original filename")
    file_size: int = Field(..., ge=0, description="File size in bytes")
    content_type: str = Field(..., description="MIME type")
    expires_at: datetime = Field(..., description="File expiration timestamp")
    upload_url: Optional[str] = Field(None, description="Upload URL for chunked uploads")
    
    class Config:
        """Pydantic configuration."""
        json_encoders = {
            datetime: lambda v: v.isoformat()
        }
        schema_extra = {
            "example": {
                "file_id": "file_abc123",
                "filename": "document.pdf",
                "file_size": 2048576,
                "content_type": "application/pdf",
                "expires_at": "2024-01-15T11:30:00Z",
                "timestamp": "2024-01-15T10:30:00Z"
            }
        }


class FileMetadata(BaseModel):
    """File metadata information."""
    
    file_id: str = Field(..., description="File identifier")
    filename: str = Field(..., description="Original filename")
    file_size: int = Field(..., ge=0, description="File size in bytes")
    content_type: str = Field(..., description="MIME type")
    created_at: datetime = Field(..., description="Upload timestamp")
    expires_at: datetime = Field(..., description="File expiration timestamp")
    status: StatusEnum = Field(..., description="File status")
    metadata: Dict[str, Any] = Field(
        default_factory=dict,
        description="Additional metadata"
    )
    
    # Processing information
    processed: bool = Field(False, description="Whether file has been processed")
    document_id: Optional[str] = Field(None, description="Associated document ID")
    
    @property
    def is_expired(self) -> bool:
        """Check if file is expired."""
        return datetime.utcnow() > self.expires_at
    
    @property
    def size_mb(self) -> float:
        """Get file size in MB."""
        return self.file_size / (1024 * 1024)
    
    class Config:
        """Pydantic configuration."""
        schema_extra = {
            "example": {
                "file_id": "file_abc123",
                "filename": "document.pdf",
                "file_size": 2048576,
                "content_type": "application/pdf",
                "created_at": "2024-01-15T10:30:00Z",
                "expires_at": "2024-01-15T11:30:00Z",
                "status": "uploaded",
                "processed": False,
                "metadata": {
                    "upload_method": "direct",
                    "client_ip": "192.168.1.100"
                }
            }
        }


class ChunkUploadRequest(BaseModel):
    """Chunked upload request."""
    
    upload_id: str = Field(..., description="Upload session identifier")
    chunk_index: int = Field(..., ge=0, description="Zero-based chunk index")
    total_chunks: int = Field(..., ge=1, description="Total number of chunks")
    chunk_size: int = Field(..., ge=1, description="Size of this chunk in bytes")
    filename: Optional[str] = Field(
        None,
        description="Original filename (required for first chunk)"
    )
    
    @validator("chunk_index")
    def validate_chunk_index(cls, v, values):
        """Validate chunk index."""
        total_chunks = values.get("total_chunks")
        if total_chunks is not None and v >= total_chunks:
            raise ValueError("chunk_index must be less than total_chunks")
        return v
    
    class Config:
        """Pydantic configuration."""
        schema_extra = {
            "example": {
                "upload_id": "upload_xyz789",
                "chunk_index": 0,
                "total_chunks": 10,
                "chunk_size": 1048576,
                "filename": "large_document.pdf"
            }
        }


class ChunkUploadResult(BaseResponse):
    """Chunked upload result."""
    
    upload_id: str = Field(..., description="Upload session identifier")
    chunk_index: int = Field(..., description="Uploaded chunk index")
    status: str = Field(..., description="Upload status")
    
    # For completed uploads
    file_id: Optional[str] = Field(None, description="Final file ID (when complete)")
    file_size: Optional[int] = Field(None, description="Total file size (when complete)")
    
    # Progress information
    chunks_received: int = Field(..., ge=0, description="Number of chunks received")
    total_chunks: int = Field(..., ge=1, description="Total expected chunks")
    bytes_received: int = Field(..., ge=0, description="Total bytes received")
    
    @property
    def progress_percentage(self) -> float:
        """Calculate upload progress percentage."""
        return (self.chunks_received / self.total_chunks) * 100
    
    @property
    def is_complete(self) -> bool:
        """Check if upload is complete."""
        return self.chunks_received >= self.total_chunks
    
    class Config:
        """Pydantic configuration."""
        schema_extra = {
            "example": {
                "upload_id": "upload_xyz789",
                "chunk_index": 5,
                "status": "chunk_received",
                "chunks_received": 6,
                "total_chunks": 10,
                "bytes_received": 6291456,
                "timestamp": "2024-01-15T10:30:00Z"
            }
        }