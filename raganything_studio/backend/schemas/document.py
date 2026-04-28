from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class DocumentStatus(str, Enum):
    UPLOADED = "uploaded"
    PROCESSING = "processing"
    INDEXED = "indexed"
    FAILED = "failed"


class DocumentRecord(BaseModel):
    id: str
    filename: str
    original_path: str
    working_dir: str
    output_dir: str
    status: DocumentStatus
    created_at: datetime
    updated_at: datetime
    error: str | None = None
    latest_job_id: str | None = None
    latest_job_status: str | None = None
    latest_job_stage: str | None = None
    latest_job_progress: float | None = None
    latest_job_message: str | None = None
    status_detail: str | None = None
    result_available: bool = False
    content_items_count: int | None = None
    chunks_count: int | None = None


class DocumentListResponse(BaseModel):
    items: list[DocumentRecord] = Field(default_factory=list)


class DocumentUploadResponse(BaseModel):
    document_id: str
    filename: str
    status: DocumentStatus


class ContentListResponse(BaseModel):
    document_id: str
    items: list[dict[str, Any]] = Field(default_factory=list)
