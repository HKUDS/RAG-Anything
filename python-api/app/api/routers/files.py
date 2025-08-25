"""File management endpoints."""

from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, status, UploadFile, File, Query
from fastapi.responses import FileResponse
from loguru import logger

from app.middleware.auth import require_auth
from app.services.file_service import get_file_service, FileService
from app.models.files import FileUploadResult

router = APIRouter(prefix="/api/v1/files", tags=["File Management"])


@router.post("/upload", response_model=FileUploadResult)
async def upload_file(
    file: UploadFile = File(...),
    expires_in: int = Query(24 * 3600, ge=3600, le=7 * 24 * 3600, description="File expiration in seconds (1 hour to 7 days)"),
    user_id: str = Depends(require_auth),
    file_service: FileService = Depends(get_file_service)
):
    """Upload a file with security validation.
    
    Uploads a file to temporary storage with automatic expiration.
    Files are scanned for malware and validated against allowed types.
    
    **Supported file types:**
    - PDF documents (.pdf)
    - Microsoft Office documents (.docx, .pptx, .xlsx)
    - Text files (.txt, .md, .csv)
    - Images (.jpg, .png, .tiff, .bmp, .gif)
    
    **Security features:**
    - File type validation using MIME detection
    - Malware scanning
    - Size limits enforced
    - Automatic expiration
    """
    try:
        if not file.filename:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Filename is required"
            )
        
        logger.info(f"File upload request from user {user_id}: {file.filename}")
        
        result = await file_service.upload_file(
            file=file,
            user_id=user_id,
            expires_in=expires_in
        )
        
        logger.info(f"File uploaded successfully: {result.file_id}")
        return result
        
    except ValueError as e:
        logger.warning(f"File upload validation failed: {e}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )
    except Exception as e:
        logger.error(f"File upload failed: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="File upload failed"
        )


@router.get("")
async def list_files(
    limit: int = Query(50, ge=1, le=200, description="Maximum number of files to return"),
    offset: int = Query(0, ge=0, description="Number of files to skip"),
    user_id: str = Depends(require_auth),
    file_service: FileService = Depends(get_file_service)
):
    """List uploaded files for the authenticated user.
    
    Returns a paginated list of files uploaded by the current user,
    including metadata and expiration information.
    """
    try:
        logger.info(f"File list request from user {user_id} (limit={limit}, offset={offset})")
        
        files = await file_service.list_user_files(
            user_id=user_id,
            limit=limit,
            offset=offset
        )
        
        return {
            "success": True,
            "data": {
                "files": files,
                "count": len(files),
                "limit": limit,
                "offset": offset,
                "has_more": len(files) == limit  # Simple check for more results
            }
        }
        
    except Exception as e:
        logger.error(f"File listing failed: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to list files"
        )


@router.get("/{file_id}")
async def get_file_metadata(
    file_id: str,
    user_id: str = Depends(require_auth),
    file_service: FileService = Depends(get_file_service)
):
    """Get file metadata and information.
    
    Returns detailed metadata for a specific file including size,
    type, upload date, and expiration information.
    """
    try:
        logger.info(f"File metadata request from user {user_id}: {file_id}")
        
        metadata = await file_service.get_file_metadata(file_id, user_id)
        if not metadata:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="File not found"
            )
        
        # Remove sensitive internal information
        safe_metadata = {
            "file_id": metadata["file_id"],
            "original_filename": metadata["original_filename"],
            "mime_type": metadata["mime_type"],
            "size_bytes": int(metadata["size_bytes"]),
            "size_mb": round(int(metadata["size_bytes"]) / (1024 * 1024), 2),
            "created_at": metadata["created_at"],
            "expires_at": metadata["expires_at"],
            "status": metadata["status"],
            "hash_sha256": metadata["hash_sha256"]
        }
        
        return {
            "success": True,
            "data": safe_metadata
        }
        
    except PermissionError:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied"
        )
    except Exception as e:
        logger.error(f"Get file metadata failed: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to get file metadata"
        )


@router.get("/{file_id}/download")
async def download_file(
    file_id: str,
    user_id: str = Depends(require_auth),
    file_service: FileService = Depends(get_file_service)
):
    """Download an uploaded file.
    
    Downloads the file content with proper content type headers.
    The file must belong to the authenticated user and not be expired.
    """
    try:
        logger.info(f"File download request from user {user_id}: {file_id}")
        
        # Get file metadata first
        metadata = await file_service.get_file_metadata(file_id, user_id)
        if not metadata:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="File not found"
            )
        
        # Get file path
        file_path = await file_service.get_file_path(file_id, user_id)
        if not file_path:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="File not found on disk"
            )
        
        return FileResponse(
            path=file_path,
            filename=metadata["original_filename"],
            media_type=metadata["mime_type"],
            headers={
                "Content-Disposition": f"attachment; filename=\"{metadata['original_filename']}\"",
                "X-File-ID": file_id,
                "X-Content-SHA256": metadata["hash_sha256"]
            }
        )
        
    except PermissionError:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied"
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"File download failed: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to download file"
        )


@router.delete("/{file_id}")
async def delete_file(
    file_id: str,
    user_id: str = Depends(require_auth),
    file_service: FileService = Depends(get_file_service)
):
    """Delete an uploaded file.
    
    Permanently deletes the file and all associated metadata.
    This action cannot be undone.
    """
    try:
        logger.info(f"File deletion request from user {user_id}: {file_id}")
        
        result = await file_service.delete_file(file_id, user_id)
        
        return {
            "success": True,
            "data": result,
            "message": f"File {file_id} deleted successfully"
        }
        
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(e)
        )
    except PermissionError:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied"
        )
    except Exception as e:
        logger.error(f"File deletion failed: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to delete file"
        )


@router.post("/cleanup")
async def cleanup_expired_files(
    user_id: str = Depends(require_auth),
    file_service: FileService = Depends(get_file_service)
):
    """Manually trigger cleanup of expired files.
    
    Removes all expired files from storage. This operation is also
    performed automatically by the system periodically.
    """
    try:
        logger.info(f"Manual file cleanup requested by user {user_id}")
        
        cleaned_count = await file_service.cleanup_expired_files()
        
        return {
            "success": True,
            "data": {
                "cleaned_files": cleaned_count,
                "message": f"Cleaned up {cleaned_count} expired files"
            }
        }
        
    except Exception as e:
        logger.error(f"File cleanup failed: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to cleanup files"
        )


@router.get("/types/supported")
async def get_supported_file_types(
    user_id: str = Depends(require_auth)
):
    """Get list of supported file types and upload limits.
    
    Returns information about supported file formats, size limits,
    and upload restrictions.
    """
    try:
        supported_types = {
            "documents": {
                "pdf": {
                    "mime_type": "application/pdf",
                    "extensions": [".pdf"],
                    "description": "PDF documents"
                },
                "word": {
                    "mime_type": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                    "extensions": [".docx"],
                    "description": "Microsoft Word documents"
                },
                "powerpoint": {
                    "mime_type": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
                    "extensions": [".pptx"],
                    "description": "Microsoft PowerPoint presentations"
                },
                "excel": {
                    "mime_type": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    "extensions": [".xlsx"],
                    "description": "Microsoft Excel spreadsheets"
                }
            },
            "text": {
                "plain": {
                    "mime_type": "text/plain",
                    "extensions": [".txt"],
                    "description": "Plain text files"
                },
                "markdown": {
                    "mime_type": "text/markdown",
                    "extensions": [".md"],
                    "description": "Markdown files"
                },
                "csv": {
                    "mime_type": "text/csv",
                    "extensions": [".csv"],
                    "description": "CSV data files"
                }
            },
            "images": {
                "jpeg": {
                    "mime_type": "image/jpeg",
                    "extensions": [".jpg", ".jpeg"],
                    "description": "JPEG images"
                },
                "png": {
                    "mime_type": "image/png",
                    "extensions": [".png"],
                    "description": "PNG images"
                },
                "tiff": {
                    "mime_type": "image/tiff",
                    "extensions": [".tiff", ".tif"],
                    "description": "TIFF images"
                }
            }
        }
        
        limits = {
            "max_file_size_mb": file_service.max_file_size // (1024 * 1024),
            "max_file_size_bytes": file_service.max_file_size,
            "min_expiration_seconds": 3600,  # 1 hour
            "max_expiration_seconds": 7 * 24 * 3600,  # 7 days
            "default_expiration_seconds": 24 * 3600  # 24 hours
        }
        
        return {
            "success": True,
            "data": {
                "supported_types": supported_types,
                "limits": limits,
                "security_features": [
                    "MIME type validation",
                    "File size limits",
                    "Malware scanning",
                    "Automatic expiration",
                    "Content integrity verification"
                ]
            }
        }
        
    except Exception as e:
        logger.error(f"Failed to get supported file types: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to get file type information"
        )


# Utility endpoints for file processing integration

@router.post("/{file_id}/process")
async def process_file_with_rag(
    file_id: str,
    kb_id: str = Query("default", description="Knowledge base to add processed content to"),
    parser_type: str = Query("auto", description="Parser type to use"),
    user_id: str = Depends(require_auth),
    file_service: FileService = Depends(get_file_service)
):
    """Process uploaded file with RAG-Anything and add to knowledge base.
    
    Takes an uploaded file and processes it through the RAG system,
    extracting content and adding it to the specified knowledge base.
    """
    try:
        logger.info(f"File processing request from user {user_id}: {file_id} -> KB: {kb_id}")
        
        # Get file path
        file_path = await file_service.get_file_path(file_id, user_id)
        if not file_path:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="File not found"
            )
        
        # Get RAG service
        from app.services.rag_service import get_rag_service
        rag_service = get_rag_service()
        
        # Process document
        result = await rag_service.process_document(
            file_path=str(file_path),
            parser_type=parser_type,
            insert_to_kb=True
        )
        
        return {
            "success": True,
            "data": {
                "file_id": file_id,
                "kb_id": kb_id,
                "processing_result": result,
                "message": f"File processed and added to knowledge base '{kb_id}'"
            }
        }
        
    except PermissionError:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied"
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"File processing failed: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to process file: {str(e)}"
        )