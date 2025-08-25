"""Query processing endpoints for RAG-Anything API."""

import json
from typing import List, Dict, Any, Optional

from fastapi import APIRouter, Depends, HTTPException, status, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, validator, Field
from loguru import logger

from app.middleware.auth import require_auth
from app.services.rag_service import get_rag_service, RAGService
from app.models.queries import QueryResponse
from app.integration.exceptions import RAGIntegrationError, LightRAGError

router = APIRouter(prefix="/api/v1/query", tags=["Query Processing"])


class TextQueryRequest(BaseModel):
    """Text query request model."""
    query: str = Field(..., min_length=1, max_length=10000, description="Query text")
    mode: str = Field(default="hybrid", description="Query mode")
    kb_id: str = Field(default="default", description="Knowledge base ID")
    stream: bool = Field(default=False, description="Enable streaming response")
    top_k: int = Field(default=10, ge=1, le=100, description="Maximum results")
    
    @validator('mode')
    def validate_mode(cls, v):
        valid_modes = ["hybrid", "local", "global", "naive"]
        if v not in valid_modes:
            raise ValueError(f"Invalid mode. Must be one of: {valid_modes}")
        return v
    
    @validator('query')
    def validate_query(cls, v):
        if not v.strip():
            raise ValueError("Query cannot be empty")
        return v.strip()


class MultimodalContent(BaseModel):
    """Multimodal content item model."""
    type: str = Field(..., description="Content type")
    image_path: Optional[str] = Field(None, description="Path to image file")
    table_data: Optional[str] = Field(None, description="Table data (CSV or structured)")
    table_caption: Optional[str] = Field(None, description="Table caption/description")
    equation: Optional[str] = Field(None, description="Mathematical equation")
    metadata: Optional[Dict[str, Any]] = Field(default_factory=dict, description="Additional metadata")
    
    @validator('type')
    def validate_type(cls, v):
        valid_types = ["image", "table", "equation"]
        if v not in valid_types:
            raise ValueError(f"Invalid content type. Must be one of: {valid_types}")
        return v
    
    @validator('image_path')
    def validate_image_path(cls, v, values):
        if values.get('type') == 'image' and not v:
            raise ValueError("Image content requires image_path")
        return v
    
    @validator('table_data')
    def validate_table_data(cls, v, values):
        if values.get('type') == 'table' and not v:
            raise ValueError("Table content requires table_data")
        return v
    
    @validator('equation')
    def validate_equation(cls, v, values):
        if values.get('type') == 'equation' and not v:
            raise ValueError("Equation content requires equation")
        return v


class MultimodalQueryRequest(BaseModel):
    """Multimodal query request model."""
    query: str = Field(..., min_length=1, max_length=10000, description="Query text")
    multimodal_content: List[MultimodalContent] = Field(..., min_items=1, max_items=20, description="Multimodal content items")
    mode: str = Field(default="hybrid", description="Query mode")
    kb_id: str = Field(default="default", description="Knowledge base ID")
    
    @validator('mode')
    def validate_mode(cls, v):
        valid_modes = ["hybrid", "local", "global", "naive"]
        if v not in valid_modes:
            raise ValueError(f"Invalid mode. Must be one of: {valid_modes}")
        return v


class VLMQueryRequest(BaseModel):
    """VLM-enhanced query request model."""
    query: str = Field(..., min_length=1, max_length=10000, description="Query text")
    mode: str = Field(default="hybrid", description="Query mode")
    kb_id: str = Field(default="default", description="Knowledge base ID")
    enable_image_analysis: bool = Field(default=True, description="Enable image analysis")
    vlm_model: Optional[str] = Field(None, description="Specific VLM model to use")
    
    @validator('mode')
    def validate_mode(cls, v):
        valid_modes = ["hybrid", "local", "global", "naive"]
        if v not in valid_modes:
            raise ValueError(f"Invalid mode. Must be one of: {valid_modes}")
        return v


class TextInsertRequest(BaseModel):
    """Text insertion request model."""
    text: str = Field(..., min_length=1, max_length=100000, description="Text to insert")
    document_id: Optional[str] = Field(None, description="Optional document identifier")
    metadata: Optional[Dict[str, Any]] = Field(default_factory=dict, description="Additional metadata")
    
    @validator('text')
    def validate_text(cls, v):
        if not v.strip():
            raise ValueError("Text cannot be empty")
        return v.strip()


@router.post("/text", response_model=QueryResponse)
async def query_text(
    request: TextQueryRequest,
    user_id: str = Depends(require_auth),
    rag_service: RAGService = Depends(get_rag_service)
):
    """Execute text-based query against the knowledge base.
    
    This endpoint processes natural language queries and returns relevant results
    from the knowledge base using various query modes.
    """
    try:
        logger.info(f"Text query from user {user_id}: {request.query[:100]}...")
        
        if request.stream:
            # Return streaming response
            return StreamingResponse(
                _stream_query_results(rag_service, request),
                media_type="text/plain",
                headers={
                    "Cache-Control": "no-cache",
                    "Connection": "keep-alive",
                    "Content-Type": "text/event-stream"
                }
            )
        
        # Regular query
        result = await rag_service.query_text(
            query=request.query,
            mode=request.mode,
            kb_id=request.kb_id,
            top_k=request.top_k
        )
        
        # Wrap in standard response format
        response = QueryResponse(
            success=True,
            data=result,
            query_type="text",
            user_id=user_id
        )
        
        logger.info(f"Text query completed for user {user_id}")
        return response
        
    except ValueError as e:
        logger.warning(f"Invalid text query request: {e}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )
    except (RAGIntegrationError, LightRAGError) as e:
        logger.error(f"RAG service error: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Query processing failed: {str(e)}"
        )
    except Exception as e:
        logger.error(f"Unexpected error in text query: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An unexpected error occurred during query processing"
        )


@router.post("/multimodal", response_model=QueryResponse)
async def query_multimodal(
    request: MultimodalQueryRequest,
    user_id: str = Depends(require_auth),
    rag_service: RAGService = Depends(get_rag_service)
):
    """Execute multimodal query with structured content (images, tables, equations).
    
    This endpoint processes queries that include multimodal content alongside
    text, providing enhanced retrieval for complex documents.
    """
    try:
        logger.info(f"Multimodal query from user {user_id}: {len(request.multimodal_content)} items")
        
        # Convert Pydantic models to dicts for service layer
        multimodal_content = [content.dict() for content in request.multimodal_content]
        
        result = await rag_service.query_multimodal(
            query=request.query,
            multimodal_content=multimodal_content,
            mode=request.mode,
            kb_id=request.kb_id
        )
        
        response = QueryResponse(
            success=True,
            data=result,
            query_type="multimodal",
            user_id=user_id
        )
        
        logger.info(f"Multimodal query completed for user {user_id}")
        return response
        
    except ValueError as e:
        logger.warning(f"Invalid multimodal query request: {e}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )
    except (RAGIntegrationError, LightRAGError) as e:
        logger.error(f"RAG service error in multimodal query: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Multimodal query processing failed: {str(e)}"
        )
    except Exception as e:
        logger.error(f"Unexpected error in multimodal query: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An unexpected error occurred during multimodal query processing"
        )


@router.post("/vlm-enhanced", response_model=QueryResponse)
async def query_vlm_enhanced(
    request: VLMQueryRequest,
    user_id: str = Depends(require_auth),
    rag_service: RAGService = Depends(get_rag_service)
):
    """Execute VLM-enhanced query with automatic visual content analysis.
    
    This endpoint uses Vision-Language Models to automatically analyze and
    understand visual content in documents for enhanced retrieval.
    """
    try:
        logger.info(f"VLM-enhanced query from user {user_id}: {request.query[:100]}...")
        
        result = await rag_service.query_vlm_enhanced(
            query=request.query,
            mode=request.mode,
            kb_id=request.kb_id,
            enable_image_analysis=request.enable_image_analysis
        )
        
        response = QueryResponse(
            success=True,
            data=result,
            query_type="vlm_enhanced",
            user_id=user_id
        )
        
        logger.info(f"VLM-enhanced query completed for user {user_id}")
        return response
        
    except ValueError as e:
        logger.warning(f"Invalid VLM query request: {e}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )
    except (RAGIntegrationError, LightRAGError) as e:
        logger.error(f"RAG service error in VLM query: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"VLM-enhanced query processing failed: {str(e)}"
        )
    except Exception as e:
        logger.error(f"Unexpected error in VLM query: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An unexpected error occurred during VLM-enhanced query processing"
        )


@router.post("/insert-text")
async def insert_text(
    request: TextInsertRequest,
    user_id: str = Depends(require_auth),
    rag_service: RAGService = Depends(get_rag_service)
):
    """Insert text directly into the knowledge base.
    
    This endpoint allows direct insertion of text content into the knowledge base
    without requiring file upload and processing.
    """
    try:
        logger.info(f"Text insertion from user {user_id}: {len(request.text)} characters")
        
        result = await rag_service.insert_text(
            text=request.text,
            document_id=request.document_id,
            metadata={
                **request.metadata,
                "inserted_by": user_id,
                "insertion_method": "direct_api"
            }
        )
        
        return {
            "success": True,
            "data": result,
            "message": f"Text inserted successfully: {result.get('document_id')}",
            "user_id": user_id
        }
        
    except ValueError as e:
        logger.warning(f"Invalid text insertion request: {e}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )
    except (RAGIntegrationError, LightRAGError) as e:
        logger.error(f"RAG service error in text insertion: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Text insertion failed: {str(e)}"
        )
    except Exception as e:
        logger.error(f"Unexpected error in text insertion: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An unexpected error occurred during text insertion"
        )


@router.get("/kb/{kb_id}/info")
async def get_knowledge_base_info(
    kb_id: str,
    user_id: str = Depends(require_auth),
    rag_service: RAGService = Depends(get_rag_service)
):
    """Get knowledge base information and statistics.
    
    Returns detailed information about the specified knowledge base including
    storage statistics, configuration, and operational status.
    """
    try:
        logger.info(f"Knowledge base info request from user {user_id} for KB: {kb_id}")
        
        info = await rag_service.get_knowledge_base_info(kb_id=kb_id)
        
        return {
            "success": True,
            "data": info,
            "user_id": user_id
        }
        
    except (RAGIntegrationError, LightRAGError) as e:
        logger.error(f"RAG service error getting KB info: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get knowledge base info: {str(e)}"
        )
    except Exception as e:
        logger.error(f"Unexpected error getting KB info: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An unexpected error occurred while retrieving knowledge base information"
        )


async def _stream_query_results(rag_service: RAGService, request: TextQueryRequest):
    """Stream query results for long-running queries.
    
    Args:
        rag_service: RAG service instance
        request: Query request
        
    Yields:
        Server-sent events with query results
    """
    try:
        logger.info(f"Starting streaming query: {request.query[:50]}...")
        
        async for chunk in rag_service.stream_query(
            query=request.query,
            mode=request.mode,
            kb_id=request.kb_id
        ):
            # Format as Server-Sent Events
            yield f"data: {json.dumps(chunk)}\n\n"
        
        # Send completion event
        yield f"data: {json.dumps({'type': 'end', 'message': 'Query completed'})}\n\n"
        
    except Exception as e:
        logger.error(f"Streaming query error: {e}")
        error_chunk = {
            "type": "error",
            "error": str(e),
            "message": "Query processing failed"
        }
        yield f"data: {json.dumps(error_chunk)}\n\n"


# Additional utility endpoints

@router.get("/modes")
async def get_supported_modes(
    user_id: str = Depends(require_auth)
):
    """Get list of supported query modes.
    
    Returns information about available query modes and their descriptions.
    """
    modes = {
        "hybrid": {
            "name": "Hybrid",
            "description": "Combines local and global search for balanced results",
            "use_case": "General purpose queries with good precision and recall"
        },
        "local": {
            "name": "Local",
            "description": "Focuses on local document context and relationships",
            "use_case": "Detailed questions about specific document sections"
        },
        "global": {
            "name": "Global",
            "description": "Leverages global document relationships and summaries",
            "use_case": "High-level questions requiring broad context"
        },
        "naive": {
            "name": "Naive",
            "description": "Simple similarity-based retrieval without complex reasoning",
            "use_case": "Fast queries when simple matching is sufficient"
        }
    }
    
    return {
        "success": True,
        "data": {
            "supported_modes": modes,
            "default_mode": "hybrid",
            "total_modes": len(modes)
        }
    }


@router.get("/content-types")
async def get_supported_content_types(
    user_id: str = Depends(require_auth)
):
    """Get list of supported multimodal content types.
    
    Returns information about supported content types for multimodal queries.
    """
    content_types = {
        "image": {
            "name": "Image",
            "description": "Visual content including photos, diagrams, and charts",
            "required_fields": ["image_path"],
            "optional_fields": ["metadata"],
            "supported_formats": ["jpg", "jpeg", "png", "tiff", "bmp"]
        },
        "table": {
            "name": "Table",
            "description": "Structured tabular data",
            "required_fields": ["table_data"],
            "optional_fields": ["table_caption", "metadata"],
            "supported_formats": ["csv", "structured_text"]
        },
        "equation": {
            "name": "Equation",
            "description": "Mathematical equations and formulas",
            "required_fields": ["equation"],
            "optional_fields": ["metadata"],
            "supported_formats": ["latex", "mathml", "plain_text"]
        }
    }
    
    return {
        "success": True,
        "data": {
            "supported_content_types": content_types,
            "max_items_per_query": 20,
            "total_types": len(content_types)
        }
    }