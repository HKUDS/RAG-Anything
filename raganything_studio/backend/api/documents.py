from __future__ import annotations

import asyncio

from fastapi import APIRouter, Depends, UploadFile, status

from raganything_studio.backend.core.document_store import DocumentStore
from raganything_studio.backend.core.errors import api_error
from raganything_studio.backend.core.job_manager import JobManager
from raganything_studio.backend.dependencies import (
    get_content_list_service,
    get_document_store,
    get_job_manager,
    get_rag_service,
)
from raganything_studio.backend.schemas.document import (
    ContentListResponse,
    DocumentRecord,
    DocumentListResponse,
    DocumentStatus,
    DocumentUploadResponse,
)
from raganything_studio.backend.schemas.job import JobStartResponse, ProcessOptions
from raganything_studio.backend.services.content_list_service import ContentListService
from raganything_studio.backend.services.raganything_service import (
    RAGAnythingService,
    format_traceback,
)

router = APIRouter()


@router.get("", response_model=DocumentListResponse)
async def list_documents(
    document_store: DocumentStore = Depends(get_document_store),
    job_manager: JobManager = Depends(get_job_manager),
) -> DocumentListResponse:
    items = [_with_latest_job(doc, job_manager) for doc in document_store.list_documents()]
    return DocumentListResponse(items=items)


@router.post("/upload", response_model=DocumentUploadResponse)
async def upload_document(
    file: UploadFile,
    document_store: DocumentStore = Depends(get_document_store),
) -> DocumentUploadResponse:
    document = document_store.save_upload(file)
    return DocumentUploadResponse(
        document_id=document.id,
        filename=document.filename,
        status=document.status,
    )


@router.post("/{document_id}/process", response_model=JobStartResponse)
async def process_document(
    document_id: str,
    options: ProcessOptions,
    document_store: DocumentStore = Depends(get_document_store),
    job_manager: JobManager = Depends(get_job_manager),
    rag_service: RAGAnythingService = Depends(get_rag_service),
) -> JobStartResponse:
    document = document_store.get_document(document_id)
    if document.status == DocumentStatus.PROCESSING:
        raise api_error(
            "INVALID_PROCESS_OPTIONS",
            f"Document {document_id} is already processing",
            status.HTTP_409_CONFLICT,
        )

    if options.output_dir is None:
        options = _copy_process_options(options, {"output_dir": document.output_dir})
    if options.working_dir is None:
        options = _copy_process_options(options, {"working_dir": document.working_dir})

    job = job_manager.create_job(document_id=document_id)
    document_store.set_status(document_id, DocumentStatus.PROCESSING)
    asyncio.create_task(
        _run_process_job(
            document_id=document_id,
            document_path=document.original_path,
            options=options,
            document_store=document_store,
            job_manager=job_manager,
            rag_service=rag_service,
            job_id=job.id,
        )
    )
    return JobStartResponse(job_id=job.id, status=job.status)


@router.get("/{document_id}/content-list", response_model=ContentListResponse)
async def get_content_list(
    document_id: str,
    document_store: DocumentStore = Depends(get_document_store),
    content_list_service: ContentListService = Depends(get_content_list_service),
) -> ContentListResponse:
    document = document_store.get_document(document_id)
    return ContentListResponse(
        document_id=document_id,
        items=content_list_service.get_content_list(document),
    )


async def _run_process_job(
    document_id: str,
    document_path: str,
    options: ProcessOptions,
    document_store: DocumentStore,
    job_manager: JobManager,
    rag_service: RAGAnythingService,
    job_id: str,
) -> None:
    try:
        result = await rag_service.process_document(
            document_path=document_path,
            document_id=document_id,
            options=options,
            log=lambda message: job_manager.append_log(job_id, message),
            set_progress=lambda stage, progress, message: job_manager.update_progress(
                job_id, stage, progress, message
            ),
        )
        job_manager.update_metrics(job_id, **result.stats)
    except Exception as exc:
        error = format_traceback(exc)
        job_manager.mark_failed(job_id, error)
        document_store.set_status(document_id, DocumentStatus.FAILED, error=str(exc))
        return

    job_manager.mark_succeeded(job_id)
    document_store.set_status(
        document_id,
        DocumentStatus.INDEXED if result.indexed else DocumentStatus.UPLOADED,
    )


def _copy_process_options(options: ProcessOptions, update: dict) -> ProcessOptions:
    if hasattr(options, "model_copy"):
        return options.model_copy(update=update)
    return options.copy(update=update)


def _with_latest_job(document: DocumentRecord, job_manager: JobManager) -> DocumentRecord:
    job = job_manager.latest_job_for_document(document.id)
    if job is None:
        return document

    update = {
        "latest_job_id": job.id,
        "latest_job_status": job.status.value,
        "latest_job_stage": job.stage.value,
        "latest_job_progress": job.progress,
        "latest_job_message": job.message,
    }
    if hasattr(document, "model_copy"):
        return document.model_copy(update=update)
    return document.copy(update=update)
