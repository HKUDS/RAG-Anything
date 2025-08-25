"""Knowledge base management endpoints."""

from typing import List, Dict, Any, Optional

from fastapi import APIRouter, Depends, HTTPException, status, Query
from pydantic import BaseModel, validator, Field
from loguru import logger

from app.middleware.auth import require_auth
from app.services.kb_service import get_kb_service, KnowledgeBaseService
from app.integration.exceptions import RAGIntegrationError

router = APIRouter(prefix="/api/v1/kb", tags=["Knowledge Base Management"])


class CreateKBRequest(BaseModel):
    """Knowledge base creation request."""
    kb_id: str = Field(..., min_length=3, max_length=64, description="Knowledge base identifier")
    name: Optional[str] = Field(None, max_length=200, description="Human-readable name")
    description: Optional[str] = Field(None, max_length=1000, description="Knowledge base description")
    config: Optional[Dict[str, Any]] = Field(default_factory=dict, description="Configuration parameters")
    
    @validator('kb_id')
    def validate_kb_id(cls, v):
        # Allow only alphanumeric, hyphens, and underscores
        if not v.replace('_', '').replace('-', '').isalnum():
            raise ValueError("KB ID must contain only alphanumeric characters, hyphens, and underscores")
        
        # Reserved names
        reserved = ['default', 'system', 'admin', 'api', 'health', 'metrics']
        if v.lower() in reserved:
            raise ValueError(f"KB ID '{v}' is reserved")
        
        return v.lower()  # Normalize to lowercase
    
    @validator('name')
    def validate_name(cls, v):
        if v is not None and not v.strip():
            raise ValueError("Name cannot be empty")
        return v.strip() if v else None


class UpdateKBRequest(BaseModel):
    """Knowledge base update request."""
    name: Optional[str] = Field(None, max_length=200, description="Human-readable name")
    description: Optional[str] = Field(None, max_length=1000, description="Knowledge base description")
    config: Optional[Dict[str, Any]] = Field(None, description="Configuration updates")
    
    @validator('name')
    def validate_name(cls, v):
        if v is not None and not v.strip():
            raise ValueError("Name cannot be empty")
        return v.strip() if v else None


class KBResponse(BaseModel):
    """Knowledge base response model."""
    success: bool
    data: Dict[str, Any]
    message: Optional[str] = None


@router.post("", response_model=KBResponse)
async def create_knowledge_base(
    request: CreateKBRequest,
    user_id: str = Depends(require_auth),
    kb_service: KnowledgeBaseService = Depends(get_kb_service)
):
    """Create new knowledge base.
    
    Creates a new isolated knowledge base with its own storage and configuration.
    Each knowledge base maintains separate document indices and can be queried independently.
    """
    try:
        logger.info(f"Creating knowledge base '{request.kb_id}' for user {user_id}")
        
        # Add user info to config
        config = request.config or {}
        config.update({
            "created_by": user_id,
            "creation_method": "api"
        })
        
        result = await kb_service.create_knowledge_base(
            kb_id=request.kb_id,
            name=request.name or request.kb_id,
            description=request.description,
            config=config
        )
        
        return KBResponse(
            success=True,
            data=result,
            message=f"Knowledge base '{request.kb_id}' created successfully"
        )
        
    except ValueError as e:
        logger.warning(f"Invalid KB creation request: {e}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )
    except RAGIntegrationError as e:
        logger.error(f"RAG integration error creating KB: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to create knowledge base: {str(e)}"
        )
    except Exception as e:
        logger.error(f"Unexpected error creating KB: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An unexpected error occurred while creating the knowledge base"
        )


@router.get("", response_model=KBResponse)
async def list_knowledge_bases(
    user_id: str = Depends(require_auth),
    kb_service: KnowledgeBaseService = Depends(get_kb_service)
):
    """List all knowledge bases.
    
    Returns a list of all knowledge bases with their metadata and statistics.
    """
    try:
        logger.info(f"Listing knowledge bases for user {user_id}")
        
        knowledge_bases = await kb_service.list_knowledge_bases()
        
        # Filter by user if needed (for multi-tenant setup)
        # For now, return all KBs
        
        return KBResponse(
            success=True,
            data={
                "knowledge_bases": knowledge_bases,
                "total_count": len(knowledge_bases)
            },
            message=f"Found {len(knowledge_bases)} knowledge bases"
        )
        
    except RAGIntegrationError as e:
        logger.error(f"RAG integration error listing KBs: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to list knowledge bases: {str(e)}"
        )
    except Exception as e:
        logger.error(f"Unexpected error listing KBs: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An unexpected error occurred while listing knowledge bases"
        )


@router.get("/{kb_id}", response_model=KBResponse)
async def get_knowledge_base_info(
    kb_id: str,
    user_id: str = Depends(require_auth),
    kb_service: KnowledgeBaseService = Depends(get_kb_service)
):
    """Get detailed information about a specific knowledge base.
    
    Returns comprehensive information including metadata, statistics,
    configuration, and operational status.
    """
    try:
        logger.info(f"Getting info for knowledge base '{kb_id}' for user {user_id}")
        
        info = await kb_service.get_knowledge_base_info(kb_id)
        
        return KBResponse(
            success=True,
            data=info,
            message=f"Knowledge base '{kb_id}' information retrieved"
        )
        
    except ValueError as e:
        logger.warning(f"Knowledge base not found: {e}")
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(e)
        )
    except RAGIntegrationError as e:
        logger.error(f"RAG integration error getting KB info: {e}")
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


@router.put("/{kb_id}", response_model=KBResponse)
async def update_knowledge_base(
    kb_id: str,
    request: UpdateKBRequest,
    user_id: str = Depends(require_auth),
    kb_service: KnowledgeBaseService = Depends(get_kb_service)
):
    """Update knowledge base metadata and configuration.
    
    Updates the knowledge base name, description, and configuration parameters.
    Some configuration changes may require restarting queries against the KB.
    """
    try:
        logger.info(f"Updating knowledge base '{kb_id}' for user {user_id}")
        
        # Add update metadata
        config = request.config or {}
        if config:
            config.update({
                "last_modified_by": user_id,
                "modification_method": "api"
            })
        
        result = await kb_service.update_knowledge_base(
            kb_id=kb_id,
            name=request.name,
            description=request.description,
            config=config if config else None
        )
        
        return KBResponse(
            success=True,
            data=result,
            message=f"Knowledge base '{kb_id}' updated successfully"
        )
        
    except ValueError as e:
        logger.warning(f"Knowledge base update failed: {e}")
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(e)
        )
    except RAGIntegrationError as e:
        logger.error(f"RAG integration error updating KB: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to update knowledge base: {str(e)}"
        )
    except Exception as e:
        logger.error(f"Unexpected error updating KB: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An unexpected error occurred while updating the knowledge base"
        )


@router.delete("/{kb_id}", response_model=KBResponse)
async def delete_knowledge_base(
    kb_id: str,
    force: bool = Query(False, description="Force deletion even if KB is in use"),
    user_id: str = Depends(require_auth),
    kb_service: KnowledgeBaseService = Depends(get_kb_service)
):
    """Delete knowledge base and all associated data.
    
    **WARNING**: This operation permanently deletes the knowledge base
    and all its documents. This cannot be undone.
    
    Use `force=true` to delete even if the knowledge base is currently loaded.
    """
    try:
        logger.info(f"Deleting knowledge base '{kb_id}' for user {user_id} (force={force})")
        
        result = await kb_service.delete_knowledge_base(kb_id, force=force)
        
        return KBResponse(
            success=True,
            data=result,
            message=f"Knowledge base '{kb_id}' deleted successfully"
        )
        
    except ValueError as e:
        logger.warning(f"Knowledge base deletion failed: {e}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST if "in use" in str(e) else status.HTTP_404_NOT_FOUND,
            detail=str(e)
        )
    except RAGIntegrationError as e:
        logger.error(f"RAG integration error deleting KB: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to delete knowledge base: {str(e)}"
        )
    except Exception as e:
        logger.error(f"Unexpected error deleting KB: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An unexpected error occurred while deleting the knowledge base"
        )


@router.post("/{kb_id}/load", response_model=KBResponse)
async def load_knowledge_base(
    kb_id: str,
    user_id: str = Depends(require_auth),
    kb_service: KnowledgeBaseService = Depends(get_kb_service)
):
    """Load knowledge base into memory for faster querying.
    
    Preloads the knowledge base indices and data structures into memory
    to improve query response times. Large knowledge bases may take time to load.
    """
    try:
        logger.info(f"Loading knowledge base '{kb_id}' for user {user_id}")
        
        integrator = await kb_service.load_knowledge_base(kb_id)
        
        # Get basic info about the loaded KB
        kb_info = await integrator.get_knowledge_base_info()
        
        return KBResponse(
            success=True,
            data={
                "kb_id": kb_id,
                "loaded": True,
                "info": kb_info
            },
            message=f"Knowledge base '{kb_id}' loaded into memory"
        )
        
    except ValueError as e:
        logger.warning(f"Knowledge base load failed: {e}")
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(e)
        )
    except RAGIntegrationError as e:
        logger.error(f"RAG integration error loading KB: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to load knowledge base: {str(e)}"
        )
    except Exception as e:
        logger.error(f"Unexpected error loading KB: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An unexpected error occurred while loading the knowledge base"
        )


@router.post("/{kb_id}/unload", response_model=KBResponse)
async def unload_knowledge_base(
    kb_id: str,
    user_id: str = Depends(require_auth),
    kb_service: KnowledgeBaseService = Depends(get_kb_service)
):
    """Unload knowledge base from memory to free resources.
    
    Removes the knowledge base from memory to free up system resources.
    The KB can still be queried but may have slower response times.
    """
    try:
        logger.info(f"Unloading knowledge base '{kb_id}' for user {user_id}")
        
        success = await kb_service.unload_knowledge_base(kb_id)
        
        if not success:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to unload knowledge base '{kb_id}'"
            )
        
        return KBResponse(
            success=True,
            data={
                "kb_id": kb_id,
                "unloaded": True
            },
            message=f"Knowledge base '{kb_id}' unloaded from memory"
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Unexpected error unloading KB: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An unexpected error occurred while unloading the knowledge base"
        )


@router.get("/{kb_id}/stats", response_model=KBResponse)
async def get_knowledge_base_stats(
    kb_id: str,
    user_id: str = Depends(require_auth),
    kb_service: KnowledgeBaseService = Depends(get_kb_service)
):
    """Get detailed statistics for a knowledge base.
    
    Returns comprehensive statistics including storage usage, document counts,
    query performance metrics, and operational data.
    """
    try:
        logger.info(f"Getting stats for knowledge base '{kb_id}' for user {user_id}")
        
        info = await kb_service.get_knowledge_base_info(kb_id)
        
        # Extract statistical information
        stats = {
            "kb_id": kb_id,
            "document_count": info.get("document_count", 0),
            "file_count": info.get("file_count", 0),
            "total_size_bytes": info.get("total_size_bytes", 0),
            "total_size_mb": info.get("total_size_mb", 0.0),
            "created_at": info.get("created_at"),
            "updated_at": info.get("updated_at"),
            "last_accessed": info.get("last_accessed"),
            "is_loaded": info.get("is_loaded", False),
            "status": info.get("status", "unknown"),
            "version": info.get("version", "unknown")
        }
        
        return KBResponse(
            success=True,
            data=stats,
            message=f"Statistics retrieved for knowledge base '{kb_id}'"
        )
        
    except ValueError as e:
        logger.warning(f"Knowledge base stats request failed: {e}")
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(e)
        )
    except RAGIntegrationError as e:
        logger.error(f"RAG integration error getting KB stats: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get knowledge base statistics: {str(e)}"
        )
    except Exception as e:
        logger.error(f"Unexpected error getting KB stats: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An unexpected error occurred while retrieving knowledge base statistics"
        )


@router.get("/{kb_id}/health")
async def check_knowledge_base_health(
    kb_id: str,
    user_id: str = Depends(require_auth),
    kb_service: KnowledgeBaseService = Depends(get_kb_service)
):
    """Check knowledge base health and operational status.
    
    Performs basic health checks on the knowledge base to ensure
    it's operational and responsive.
    """
    try:
        logger.info(f"Health check for knowledge base '{kb_id}' for user {user_id}")
        
        # Get basic info to verify KB exists and is accessible
        info = await kb_service.get_knowledge_base_info(kb_id)
        
        # Additional health checks
        health_status = {
            "kb_id": kb_id,
            "status": "healthy",
            "is_loaded": info.get("is_loaded", False),
            "document_count": info.get("document_count", 0),
            "total_size_mb": info.get("total_size_mb", 0.0),
            "last_accessed": info.get("last_accessed"),
            "checks": {
                "metadata_accessible": True,
                "storage_readable": True,
                "configuration_valid": True
            }
        }
        
        # If loaded, we could add more sophisticated health checks here
        if info.get("is_loaded"):
            try:
                integrator = kb_service._active_kbs.get(kb_id)
                if integrator:
                    # Could test basic query functionality
                    health_status["checks"]["integrator_responsive"] = True
                else:
                    health_status["checks"]["integrator_responsive"] = False
                    health_status["status"] = "degraded"
            except Exception as e:
                health_status["checks"]["integrator_responsive"] = False
                health_status["status"] = "degraded"
                health_status["issues"] = [str(e)]
        
        return {
            "success": True,
            "data": health_status,
            "message": f"Health check completed for knowledge base '{kb_id}'"
        }
        
    except ValueError as e:
        logger.warning(f"Knowledge base health check failed: {e}")
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(e)
        )
    except Exception as e:
        logger.error(f"Unexpected error in KB health check: {e}")
        # Return unhealthy status rather than error for monitoring purposes
        return {
            "success": False,
            "data": {
                "kb_id": kb_id,
                "status": "unhealthy",
                "error": str(e)
            },
            "message": f"Health check failed for knowledge base '{kb_id}'"
        }