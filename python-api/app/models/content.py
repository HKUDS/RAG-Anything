"""Content management related Pydantic models."""

from datetime import datetime
from typing import Any, Dict, List, Optional, Union

from pydantic import BaseModel, Field, validator

from .common import (
    BaseResponse,
    BoundingBox,
    ContentTypeEnum,
    StatusEnum,
)


class ContentItem(BaseModel):
    """Content item for insertion."""
    
    content_type: ContentTypeEnum = Field(..., description="Type of content")
    content_data: Union[str, Dict[str, Any]] = Field(
        ...,
        description="Content data (format depends on content_type)"
    )
    metadata: Dict[str, Any] = Field(
        default_factory=dict,
        description="Additional metadata"
    )
    
    # Position and context
    page_number: Optional[int] = Field(None, ge=1, description="Page number")
    bbox: Optional[BoundingBox] = Field(None, description="Bounding box coordinates")
    
    # Relationships
    parent_id: Optional[str] = Field(None, description="Parent content item ID")
    chunk_id: Optional[str] = Field(None, description="Chunk identifier")
    
    @validator("content_data")
    def validate_content_data(cls, v, values):
        """Validate content data based on content type."""
        content_type = values.get("content_type")
        
        if content_type == ContentTypeEnum.TEXT:
            if not isinstance(v, str):
                raise ValueError("Text content must be a string")
        elif content_type == ContentTypeEnum.TABLE:
            if not isinstance(v, dict):
                raise ValueError("Table content must be a dictionary")
            if "headers" not in v or "rows" not in v:
                raise ValueError("Table content must have 'headers' and 'rows'")
        elif content_type == ContentTypeEnum.IMAGE:
            if isinstance(v, str):
                # Base64 encoded image or file path
                pass
            elif isinstance(v, dict):
                # Image metadata with path/url
                if "path" not in v and "url" not in v:
                    raise ValueError("Image content must have 'path' or 'url'")
            else:
                raise ValueError("Image content must be string or dict")
        elif content_type == ContentTypeEnum.EQUATION:
            if not isinstance(v, (str, dict)):
                raise ValueError("Equation content must be string or dict")
        
        return v
    
    class Config:
        """Pydantic configuration."""
        schema_extra = {
            "example": {
                "content_type": "text",
                "content_data": "This is the introduction section discussing the methodology...",
                "metadata": {
                    "section": "Introduction",
                    "confidence": 0.95,
                    "language": "en"
                },
                "page_number": 1,
                "bbox": {
                    "x1": 50,
                    "y1": 100,
                    "x2": 400,
                    "y2": 200
                }
            }
        }


class ContentInsertRequest(BaseModel):
    """Content insertion request."""
    
    content_list: List[ContentItem] = Field(
        ...,
        min_items=1,
        description="List of content items to insert"
    )
    file_path: Optional[str] = Field(
        None,
        description="Original file path (for reference)"
    )
    doc_id: Optional[str] = Field(
        None,
        description="Custom document ID (auto-generated if not provided)"
    )
    kb_id: str = Field(
        "default",
        description="Target knowledge base"
    )
    
    class Config:
        """Pydantic configuration."""
        schema_extra = {
            "example": {
                "content_list": [
                    {
                        "content_type": "text",
                        "content_data": "This is the introduction section...",
                        "metadata": {
                            "section": "Introduction"
                        },
                        "page_number": 1
                    },
                    {
                        "content_type": "table",
                        "content_data": {
                            "headers": ["Year", "Revenue", "Growth"],
                            "rows": [["2023", "$100M", "15%"]]
                        },
                        "metadata": {
                            "table_caption": "Financial Performance"
                        },
                        "page_number": 5
                    }
                ],
                "file_path": "/uploads/annual_report.pdf",
                "doc_id": "annual_report_2023",
                "kb_id": "default"
            }
        }


class ContentInsertResult(BaseResponse):
    """Content insertion result."""
    
    document_id: str = Field(..., description="Document identifier")
    inserted_items: int = Field(..., ge=0, description="Number of content items inserted")
    processing_time: float = Field(..., ge=0, description="Processing time in seconds")
    status: str = Field("success", description="Insertion status")
    errors: List[Dict[str, Any]] = Field(
        default_factory=list,
        description="Insertion errors"
    )
    
    class Config:
        """Pydantic configuration."""
        schema_extra = {
            "example": {
                "document_id": "doc_789012",
                "inserted_items": 25,
                "processing_time": 2.15,
                "status": "success",
                "errors": [],
                "timestamp": "2024-01-15T10:30:00Z"
            }
        }


class KnowledgeBaseStats(BaseModel):
    """Knowledge base statistics."""
    
    content_types: Dict[str, int] = Field(
        default_factory=dict,
        description="Count by content type"
    )
    languages: Dict[str, int] = Field(
        default_factory=dict,
        description="Count by language"
    )
    avg_query_response_time: Optional[float] = Field(
        None,
        ge=0,
        description="Average query response time"
    )
    total_size_mb: float = Field(0, ge=0, description="Total storage size in MB")


class KnowledgeBaseInfo(BaseResponse):
    """Knowledge base information."""
    
    kb_id: str = Field(..., description="Knowledge base identifier")
    name: str = Field(..., description="Human-readable name")
    description: Optional[str] = Field(None, description="Knowledge base description")
    created_at: datetime = Field(..., description="Creation timestamp")
    updated_at: datetime = Field(..., description="Last update timestamp")
    document_count: int = Field(0, ge=0, description="Number of documents")
    total_content_items: int = Field(0, ge=0, description="Total content items")
    storage_size_mb: float = Field(0, ge=0, description="Storage size in megabytes")
    last_indexed: Optional[datetime] = Field(
        None,
        description="Last indexing timestamp"
    )
    statistics: KnowledgeBaseStats = Field(
        default_factory=KnowledgeBaseStats,
        description="Detailed statistics"
    )
    
    class Config:
        """Pydantic configuration."""
        schema_extra = {
            "example": {
                "kb_id": "default",
                "name": "Default Knowledge Base",
                "description": "Main knowledge base for document storage",
                "created_at": "2024-01-01T00:00:00Z",
                "updated_at": "2024-01-15T10:30:00Z",
                "document_count": 150,
                "total_content_items": 5420,
                "storage_size_mb": 256.5,
                "last_indexed": "2024-01-15T09:45:00Z",
                "statistics": {
                    "content_types": {
                        "text": 4800,
                        "images": 420,
                        "tables": 180,
                        "equations": 20
                    },
                    "languages": {
                        "en": 5000,
                        "fr": 300,
                        "es": 120
                    },
                    "avg_query_response_time": 1.23
                },
                "timestamp": "2024-01-15T10:30:00Z"
            }
        }


class KnowledgeBaseCreateRequest(BaseModel):
    """Knowledge base creation request."""
    
    kb_id: str = Field(..., min_length=1, description="Knowledge base identifier")
    name: str = Field(..., min_length=1, description="Human-readable name")
    description: Optional[str] = Field(None, description="Knowledge base description")
    config: Dict[str, Any] = Field(
        default_factory=dict,
        description="Configuration options"
    )
    
    @validator("kb_id")
    def validate_kb_id(cls, v):
        """Validate knowledge base ID format."""
        if not v.replace("_", "").replace("-", "").isalnum():
            raise ValueError("KB ID must contain only alphanumeric characters, hyphens, and underscores")
        return v
    
    class Config:
        """Pydantic configuration."""
        schema_extra = {
            "example": {
                "kb_id": "research_papers",
                "name": "Research Papers Knowledge Base",
                "description": "Collection of academic research papers",
                "config": {
                    "max_documents": 10000,
                    "auto_cleanup": True
                }
            }
        }


class DocumentDeleteRequest(BaseModel):
    """Document deletion request."""
    
    document_ids: List[str] = Field(
        ...,
        min_items=1,
        description="List of document IDs to delete"
    )
    force: bool = Field(
        False,
        description="Force deletion even if referenced by other content"
    )


class DocumentDeleteResult(BaseResponse):
    """Document deletion result."""
    
    deleted_documents: List[str] = Field(
        default_factory=list,
        description="Successfully deleted document IDs"
    )
    failed_documents: Dict[str, str] = Field(
        default_factory=dict,
        description="Failed deletions with error messages"
    )
    total_deleted: int = Field(0, ge=0, description="Total documents deleted")
    
    class Config:
        """Pydantic configuration."""
        schema_extra = {
            "example": {
                "deleted_documents": ["doc_001", "doc_002"],
                "failed_documents": {
                    "doc_003": "Document is referenced by other content"
                },
                "total_deleted": 2,
                "timestamp": "2024-01-15T10:30:00Z"
            }
        }