"""Document processing endpoints."""

from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form
from loguru import logger

from app.models.documents import (
    DocumentProcessResult,
    ProcessingConfig,
    BatchProcessRequest,
    BatchProcessResult,
    JobStatus,
)
from app.models.files import FileUploadResult
from app.services.document_service import DocumentService
from app.services.file_service import FileService


router = APIRouter()


# Dependency to get services (in production, use proper DI)
async def get_file_service() -> FileService:
    """Get file service instance."""
    return FileService()


async def get_document_service(
    file_service: FileService = Depends(get_file_service)
) -> DocumentService:
    """Get document service instance."""
    return DocumentService(file_service=file_service)


@router.post("/documents/process", response_model=DocumentProcessResult)
async def process_document(
    file: UploadFile = File(...),
    parser: str = Form("auto"),
    parse_method: str = Form("auto"),
    lang: str = Form("en"),
    device: str = Form("cpu"),
    chunk_size: int = Form(1000),
    chunk_overlap: int = Form(200),
    enable_image_processing: bool = Form(True),
    enable_multimodal: bool = Form(True),
    document_service: DocumentService = Depends(get_document_service)
):
    """
    Process a single document through the RAG pipeline.
    
    Upload and process a document, extracting content and optionally
    inserting it into the knowledge base.
    """
    try:
        logger.info(f"Processing document upload: {file.filename}")
        
        # First, upload the file - reset file position first
        await file.seek(0)
        
        # Create a temporary file upload
        file_service = document_service.file_service
        upload_result = await file_service.upload_file(
            file=file,
            user_id="api-user"  # Using default user for API testing
        )
        
        # Create processing configuration
        config = ProcessingConfig(
            parser=parser,
            parse_method=parse_method,
            lang=lang,
            device=device,
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
            enable_image_processing=enable_image_processing,
            enable_multimodal=enable_multimodal
        )
        
        # Process the document
        result = await document_service.process_document(
            file_id=upload_result.file_id,
            config=config,
            auto_insert=True
        )
        
        logger.info(f"Document processed successfully: {result.document_id}")
        return result
        
    except Exception as e:
        logger.error(f"Failed to process document: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Document processing failed: {str(e)}"
        )


@router.post("/documents/batch", response_model=BatchProcessResult)
async def batch_process_documents(
    request: BatchProcessRequest,
    document_service: DocumentService = Depends(get_document_service)
):
    """
    Process multiple documents concurrently in a batch job.
    
    Creates a background job to process multiple documents and returns
    a job ID for tracking progress.
    """
    try:
        logger.info(f"Creating batch job for {len(request.file_ids)} files")
        
        result = await document_service.create_batch_job(request)
        
        logger.info(f"Batch job created: {result.job_id}")
        return result
        
    except Exception as e:
        logger.error(f"Failed to create batch job: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Batch job creation failed: {str(e)}"
        )


@router.get("/documents/{job_id}/status", response_model=JobStatus)
async def get_job_status(
    job_id: str,
    document_service: DocumentService = Depends(get_document_service)
):
    """
    Get the status and progress of a document processing job.
    
    Retrieve detailed information about a batch processing job,
    including progress, results, and any errors.
    """
    try:
        status = await document_service.get_job_status(job_id)
        
        if not status:
            raise HTTPException(
                status_code=404,
                detail=f"Job not found: {job_id}"
            )
        
        return status
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get job status {job_id}: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to retrieve job status: {str(e)}"
        )