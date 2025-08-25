"""Document processing service."""

import asyncio
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from loguru import logger

from app.config import settings
from app.integration import RAGIntegrator
from app.models.documents import (
    DocumentProcessResult,
    ProcessingConfig,
    JobStatus,
    BatchProcessRequest,
    BatchProcessResult,
    JobFileResult,
)
from app.models.common import StatusEnum, TaskProgress
from .file_service import FileService


class DocumentService:
    """Service for document processing operations."""
    
    def __init__(self, file_service: FileService, cache_service=None):
        """Initialize document service.
        
        Args:
            file_service: File management service
            cache_service: Cache service for storing results
        """
        self.file_service = file_service
        self.cache_service = cache_service
        
        # RAG integrator (initialized lazily)
        self._rag_integrator = None
        
        # In-memory job tracking (in production, use database)
        self._jobs = {}
        
    async def get_rag_integrator(self) -> RAGIntegrator:
        """Get RAG integrator instance (lazy initialization)."""
        if self._rag_integrator is None:
            self._rag_integrator = RAGIntegrator(
                working_dir=settings.raganything.working_dir,
                lightrag_storage_dir=settings.raganything.lightrag_storage_dir,
                config={
                    "parsers": {
                        "default_parser": settings.raganything.default_parser,
                        "default_lang": settings.raganything.default_lang,
                        "default_device": settings.raganything.default_device,
                    },
                    "processors": {},
                    "lightrag": {}
                }
            )
            await self._rag_integrator.initialize()
        return self._rag_integrator
    
    async def process_document(
        self,
        file_id: str,
        config: ProcessingConfig,
        auto_insert: bool = True
    ) -> DocumentProcessResult:
        """Process a single document.
        
        Args:
            file_id: Uploaded file identifier
            config: Processing configuration
            auto_insert: Whether to automatically insert into knowledge base
            
        Returns:
            Document processing result
        """
        start_time = datetime.utcnow()
        
        try:
            # Get file metadata (using default user for API testing)
            file_metadata = await self.file_service.get_file_metadata(file_id, user_id="api-user")
            if not file_metadata:
                raise ValueError(f"File not found: {file_id}")
            
            # Get file path
            file_path = await self.file_service.get_file_path(file_id, user_id="api-user")
            
            logger.info(f"Processing document: {file_metadata.get('filename', 'unknown')}")
            
            # Get RAG integrator
            rag_integrator = await self.get_rag_integrator()
            
            # Process document
            if auto_insert:
                # Process and insert into knowledge base
                result = await rag_integrator.process_and_insert_document(
                    file_path=str(file_path),
                    parser_type=config.parser.value,
                    config={
                        "parse_method": config.parse_method.value,
                        "lang": config.lang,
                        "device": config.device.value,
                        "start_page": config.start_page,
                        "end_page": config.end_page,
                        "enable_image_processing": config.enable_image_processing,
                        "chunk_size": config.chunk_size,
                        "chunk_overlap": config.chunk_overlap,
                        "enable_multimodal": config.enable_multimodal,
                        **config.config
                    }
                )
                
                document_id = result["document_id"]
                content_stats = result.get("content_stats", {"total_items": 0})
                
            else:
                # Process only (no insertion)
                result = await rag_integrator.process_document(
                    file_path=str(file_path),
                    parser_type=config.parser.value,
                    config={
                        "parse_method": config.parse_method.value,
                        "lang": config.lang,
                        "device": config.device.value,
                        "start_page": config.start_page,
                        "end_page": config.end_page,
                        "enable_image_processing": config.enable_image_processing,
                        "chunk_size": config.chunk_size,
                        "chunk_overlap": config.chunk_overlap,
                        "enable_multimodal": config.enable_multimodal,
                        **config.config
                    }
                )
                
                document_id = result["document_id"]
                content_stats = result["content_stats"]
            
            # Calculate processing time
            processing_time = (datetime.utcnow() - start_time).total_seconds()
            
            # Update file metadata
            await self.file_service.update_file_metadata(
                file_id=file_id,
                updates={
                    "processed": True,
                    "document_id": document_id,
                    "processing_time": processing_time
                }
            )
            
            # Create result
            doc_result = DocumentProcessResult(
                document_id=document_id,
                status=StatusEnum.COMPLETED,
                processing_time=processing_time,
                content_stats=content_stats,
                metadata={
                    "filename": file_metadata.get('filename', 'unknown'),
                    "file_size": file_metadata.get('file_size', 0),
                    "file_id": file_id,
                    "parser_used": config.parser.value,
                    "parse_method": config.parse_method.value,
                    "auto_inserted": auto_insert,
                    "config": config.dict()
                },
                errors=[]
            )
            
            # Cache result if cache service available
            if self.cache_service:
                await self.cache_service.set_document_result(document_id, doc_result)
            
            logger.info(f"Document processed successfully: {document_id}")
            return doc_result
            
        except Exception as e:
            processing_time = (datetime.utcnow() - start_time).total_seconds()
            logger.error(f"Failed to process document {file_id}: {e}")
            
            # Return failed result
            return DocumentProcessResult(
                document_id=str(uuid.uuid4()),
                status=StatusEnum.FAILED,
                processing_time=processing_time,
                content_stats={"total_items": 0},
                metadata={
                    "filename": file_metadata.get('filename', 'unknown') if file_metadata else 'unknown',
                    "file_id": file_id,
                    "error": str(e)
                },
                errors=[{
                    "type": "processing_error",
                    "message": str(e),
                    "timestamp": datetime.utcnow().isoformat()
                }]
            )
    
    async def create_batch_job(
        self,
        request: BatchProcessRequest
    ) -> BatchProcessResult:
        """Create a batch processing job.
        
        Args:
            request: Batch processing request
            
        Returns:
            Batch job creation result
        """
        try:
            job_id = f"batch_{uuid.uuid4().hex[:12]}"
            
            # Validate all files exist (using default user for API testing)
            for file_id in request.file_ids:
                file_metadata = await self.file_service.get_file_metadata(file_id, user_id="api-user")
                if not file_metadata:
                    raise ValueError(f"File not found: {file_id}")
            
            # Create job record
            job = {
                "job_id": job_id,
                "status": StatusEnum.QUEUED,
                "file_ids": request.file_ids,
                "config": request.config,
                "max_concurrent": request.max_concurrent,
                "kb_id": request.kb_id,
                "created_at": datetime.utcnow(),
                "updated_at": datetime.utcnow(),
                "progress": TaskProgress(
                    current=0,
                    total=len(request.file_ids),
                    percentage=0.0,
                    message="Job queued"
                ),
                "results": [],
                "completed_files": 0,
                "failed_files": 0
            }
            
            self._jobs[job_id] = job
            
            # Start background processing
            asyncio.create_task(self._process_batch_job(job_id))
            
            result = BatchProcessResult(
                job_id=job_id,
                status=StatusEnum.QUEUED,
                estimated_completion=None,  # Could calculate based on file sizes
                files_count=len(request.file_ids)
            )
            
            logger.info(f"Created batch job {job_id} with {len(request.file_ids)} files")
            return result
            
        except Exception as e:
            logger.error(f"Failed to create batch job: {e}")
            raise
    
    async def get_job_status(self, job_id: str) -> Optional[JobStatus]:
        """Get batch job status.
        
        Args:
            job_id: Job identifier
            
        Returns:
            Job status or None if not found
        """
        job = self._jobs.get(job_id)
        if not job:
            return None
        
        return JobStatus(
            job_id=job_id,
            status=job["status"],
            progress=job["progress"],
            completed_files=job["completed_files"],
            failed_files=job["failed_files"],
            total_files=len(job["file_ids"]),
            results=job["results"],
            created_at=job["created_at"],
            updated_at=job["updated_at"],
            estimated_completion=job.get("estimated_completion"),
            error=job.get("error")
        )
    
    async def _process_batch_job(self, job_id: str) -> None:
        """Process batch job in background.
        
        Args:
            job_id: Job identifier
        """
        try:
            job = self._jobs[job_id]
            job["status"] = StatusEnum.PROCESSING
            job["updated_at"] = datetime.utcnow()
            job["progress"].message = "Processing files..."
            
            logger.info(f"Starting batch job processing: {job_id}")
            
            # Process files with concurrency control
            semaphore = asyncio.Semaphore(job["max_concurrent"])
            
            async def process_single_file(file_id: str, index: int) -> JobFileResult:
                async with semaphore:
                    try:
                        logger.info(f"Processing file {index + 1}/{len(job['file_ids'])}: {file_id}")
                        
                        # Process document
                        result = await self.process_document(
                            file_id=file_id,
                            config=job["config"],
                            auto_insert=True
                        )
                        
                        # Update job progress
                        job["completed_files"] += 1
                        job["progress"].current = job["completed_files"] + job["failed_files"]
                        job["progress"].percentage = (job["progress"].current / job["progress"].total) * 100
                        job["progress"].message = f"Processed {job['completed_files']}/{len(job['file_ids'])} files"
                        job["updated_at"] = datetime.utcnow()
                        
                        return JobFileResult(
                            file_id=file_id,
                            document_id=result.document_id,
                            status=result.status,
                            processing_time=result.processing_time,
                            content_stats=result.content_stats
                        )
                        
                    except Exception as e:
                        logger.error(f"Failed to process file {file_id} in batch {job_id}: {e}")
                        
                        # Update job progress
                        job["failed_files"] += 1
                        job["progress"].current = job["completed_files"] + job["failed_files"]
                        job["progress"].percentage = (job["progress"].current / job["progress"].total) * 100
                        job["updated_at"] = datetime.utcnow()
                        
                        return JobFileResult(
                            file_id=file_id,
                            status=StatusEnum.FAILED,
                            error=str(e)
                        )
            
            # Process all files
            tasks = [
                process_single_file(file_id, index)
                for index, file_id in enumerate(job["file_ids"])
            ]
            
            results = await asyncio.gather(*tasks, return_exceptions=True)
            
            # Update job with results
            job["results"] = [
                result if not isinstance(result, Exception) else JobFileResult(
                    file_id=job["file_ids"][i],
                    status=StatusEnum.FAILED,
                    error=str(result)
                )
                for i, result in enumerate(results)
            ]
            
            # Set final status
            if job["failed_files"] == 0:
                job["status"] = StatusEnum.COMPLETED
                job["progress"].message = f"All {job['completed_files']} files processed successfully"
            elif job["completed_files"] == 0:
                job["status"] = StatusEnum.FAILED
                job["progress"].message = f"All {job['failed_files']} files failed"
            else:
                job["status"] = StatusEnum.COMPLETED
                job["progress"].message = f"Completed: {job['completed_files']} succeeded, {job['failed_files']} failed"
            
            job["updated_at"] = datetime.utcnow()
            
            logger.info(f"Batch job {job_id} completed: {job['completed_files']} succeeded, {job['failed_files']} failed")
            
        except Exception as e:
            logger.error(f"Batch job {job_id} failed: {e}")
            
            job = self._jobs[job_id]
            job["status"] = StatusEnum.FAILED
            job["error"] = str(e)
            job["updated_at"] = datetime.utcnow()
            job["progress"].message = f"Job failed: {str(e)[:100]}"
    
    async def get_document_info(self, document_id: str) -> Optional[Dict[str, Any]]:
        """Get document information.
        
        Args:
            document_id: Document identifier
            
        Returns:
            Document information or None if not found
        """
        try:
            # Check cache first
            if self.cache_service:
                cached_result = await self.cache_service.get_document_result(document_id)
                if cached_result:
                    return {
                        "document_id": document_id,
                        "status": "indexed",
                        "metadata": cached_result.metadata
                    }
            
            # For now, return basic info
            # In production, this would query the database
            return {
                "document_id": document_id,
                "status": "unknown"
            }
            
        except Exception as e:
            logger.error(f"Failed to get document info for {document_id}: {e}")
            return None
    
    async def delete_document(self, document_id: str) -> bool:
        """Delete document from knowledge base.
        
        Args:
            document_id: Document identifier
            
        Returns:
            True if deleted successfully
        """
        try:
            # This would need to be implemented based on LightRAG's deletion API
            # For now, just remove from cache
            if self.cache_service:
                await self.cache_service.delete_document_result(document_id)
            
            logger.info(f"Document {document_id} deletion requested")
            return True
            
        except Exception as e:
            logger.error(f"Failed to delete document {document_id}: {e}")
            return False