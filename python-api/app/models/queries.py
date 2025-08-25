"""Query processing related Pydantic models."""

from datetime import datetime
from typing import Any, Dict, List, Optional, Union

from pydantic import BaseModel, Field, validator

from .common import (
    BaseResponse,
    ContentTypeEnum,
    QueryModeEnum,
    SourceInfo,
)


class TextQueryRequest(BaseModel):
    """Text query request."""
    
    query: str = Field(
        ...,
        min_length=1,
        max_length=2000,
        description="Query text"
    )
    mode: QueryModeEnum = Field(
        QueryModeEnum.HYBRID,
        description="Query processing mode"
    )
    kb_id: str = Field(
        "default",
        description="Knowledge base to query"
    )
    top_k: int = Field(
        10,
        ge=1,
        le=100,
        description="Maximum number of results"
    )
    stream: bool = Field(
        False,
        description="Enable streaming response"
    )
    filters: Optional[Dict[str, Any]] = Field(
        None,
        description="Additional query filters"
    )
    
    class Config:
        """Pydantic configuration."""
        schema_extra = {
            "example": {
                "query": "What are the main conclusions of the research?",
                "mode": "hybrid",
                "kb_id": "default",
                "top_k": 10,
                "stream": False,
                "filters": {
                    "document_ids": ["doc_001", "doc_002"],
                    "content_types": ["text", "table"],
                    "date_range": {
                        "start": "2024-01-01",
                        "end": "2024-01-31"
                    }
                }
            }
        }


class MultimodalContent(BaseModel):
    """Multimodal content for queries."""
    
    content_type: ContentTypeEnum = Field(..., description="Type of content")
    content_data: Union[str, Dict[str, Any]] = Field(
        ...,
        description="Content data (format depends on content_type)"
    )
    metadata: Optional[Dict[str, Any]] = Field(
        None,
        description="Additional metadata"
    )
    
    class Config:
        """Pydantic configuration."""
        schema_extra = {
            "example": {
                "content_type": "table",
                "content_data": {
                    "headers": ["Model", "Accuracy", "F1-Score"],
                    "rows": [
                        ["BERT", "92.3%", "0.89"],
                        ["GPT-4", "95.1%", "0.92"]
                    ]
                },
                "metadata": {
                    "table_caption": "Model Performance Comparison"
                }
            }
        }


class MultimodalQueryRequest(TextQueryRequest):
    """Multimodal query request."""
    
    multimodal_content: List[MultimodalContent] = Field(
        ...,
        min_items=1,
        description="Multimodal content to include in query"
    )
    
    class Config:
        """Pydantic configuration."""
        schema_extra = {
            "example": {
                "query": "Compare this table with similar data in documents",
                "mode": "hybrid",
                "kb_id": "default",
                "top_k": 10,
                "multimodal_content": [
                    {
                        "content_type": "table",
                        "content_data": {
                            "headers": ["Model", "Accuracy"],
                            "rows": [["BERT", "92.3%"], ["GPT-4", "95.1%"]]
                        },
                        "metadata": {
                            "table_caption": "Performance Comparison"
                        }
                    }
                ]
            }
        }


class VLMQueryRequest(TextQueryRequest):
    """VLM-enhanced query request."""
    
    vlm_enhanced: bool = Field(
        True,
        description="Enable VLM enhancement"
    )
    vlm_model: str = Field(
        "gpt-4-vision",
        description="VLM model to use"
    )
    
    @validator("vlm_model")
    def validate_vlm_model(cls, v):
        """Validate VLM model."""
        allowed = {"gpt-4-vision", "claude-3-vision", "gemini-pro-vision"}
        if v not in allowed:
            raise ValueError(f"VLM model must be one of {allowed}")
        return v
    
    class Config:
        """Pydantic configuration."""
        schema_extra = {
            "example": {
                "query": "Analyze the charts and graphs in the financial reports",
                "mode": "hybrid",
                "kb_id": "default",
                "top_k": 10,
                "vlm_enhanced": True,
                "vlm_model": "gpt-4-vision"
            }
        }


class QueryResultItem(BaseModel):
    """Individual query result item."""
    
    content: str = Field(..., description="Retrieved content")
    score: float = Field(
        ...,
        ge=0,
        le=1,
        description="Relevance score"
    )
    source: SourceInfo = Field(..., description="Source information")
    metadata: Dict[str, Any] = Field(
        default_factory=dict,
        description="Additional metadata"
    )
    
    class Config:
        """Pydantic configuration."""
        schema_extra = {
            "example": {
                "content": "Machine learning models showed 95% accuracy in the evaluation phase.",
                "score": 0.892,
                "source": {
                    "document_id": "doc_123",
                    "page": 5,
                    "bbox": {
                        "x1": 100,
                        "y1": 200,
                        "x2": 300,
                        "y2": 250
                    },
                    "section": "Results",
                    "filename": "research_paper.pdf"
                },
                "metadata": {
                    "content_type": "text",
                    "chunk_id": "chunk_123",
                    "confidence": 0.95
                }
            }
        }


class VLMAnalysis(BaseModel):
    """VLM analysis result."""
    
    image_id: str = Field(..., description="Image identifier")
    analysis: str = Field(..., description="VLM analysis text")
    confidence: float = Field(
        ...,
        ge=0,
        le=1,
        description="Analysis confidence score"
    )
    metadata: Optional[Dict[str, Any]] = Field(
        None,
        description="Additional analysis metadata"
    )


class QueryResult(BaseResponse):
    """Query execution result."""
    
    query: str = Field(..., description="Original query text")
    mode: QueryModeEnum = Field(..., description="Query mode used")
    results: List[QueryResultItem] = Field(
        default_factory=list,
        description="Query results"
    )
    processing_time: float = Field(..., ge=0, description="Query processing time in seconds")
    total_results: int = Field(..., ge=0, description="Total number of results found")
    metadata: Dict[str, Any] = Field(
        default_factory=dict,
        description="Additional query metadata"
    )
    
    # VLM-specific fields (optional)
    vlm_analysis: Optional[List[VLMAnalysis]] = Field(
        None,
        description="VLM analysis results"
    )
    
    @property
    def has_results(self) -> bool:
        """Check if query has results."""
        return len(self.results) > 0
    
    @property
    def average_score(self) -> float:
        """Calculate average relevance score."""
        if not self.results:
            return 0.0
        return sum(item.score for item in self.results) / len(self.results)
    
    class Config:
        """Pydantic configuration."""
        schema_extra = {
            "example": {
                "query": "What are the key findings about machine learning performance?",
                "mode": "hybrid",
                "results": [
                    {
                        "content": "Machine learning models showed 95% accuracy...",
                        "score": 0.892,
                        "source": {
                            "document_id": "doc_123",
                            "page": 5,
                            "filename": "research_paper.pdf"
                        },
                        "metadata": {
                            "content_type": "text"
                        }
                    }
                ],
                "processing_time": 1.23,
                "total_results": 15,
                "metadata": {
                    "kb_id": "default",
                    "model_used": "gpt-4",
                    "cache_hit": False
                },
                "timestamp": "2024-01-15T10:30:00Z"
            }
        }


class StreamChunk(BaseModel):
    """Streaming query result chunk."""
    
    chunk_id: int = Field(..., ge=0, description="Chunk identifier")
    content: str = Field(..., description="Partial result content")
    is_final: bool = Field(False, description="Whether this is the final chunk")
    metadata: Optional[Dict[str, Any]] = Field(None, description="Chunk metadata")


class QueryComplete(BaseModel):
    """Query completion notification."""
    
    total_results: int = Field(..., ge=0, description="Total results found")
    processing_time: float = Field(..., ge=0, description="Total processing time")
    metadata: Dict[str, Any] = Field(
        default_factory=dict,
        description="Final query metadata"
    )


# Alias for backward compatibility
QueryResponse = QueryResult