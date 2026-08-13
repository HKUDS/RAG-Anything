from __future__ import annotations

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field


class JobStatus(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"


class JobStage(str, Enum):
    QUEUED = "queued"
    PREPARING = "preparing"
    PARSING = "parsing"
    EXTRACTING_CONTENT = "extracting_content"
    PROCESSING_IMAGES = "processing_images"
    PROCESSING_TABLES = "processing_tables"
    PROCESSING_EQUATIONS = "processing_equations"
    BUILDING_INDEX = "building_index"
    FINALIZING = "finalizing"
    DONE = "done"
    FAILED = "failed"


class ProcessOptions(BaseModel):
    profile_id: str | None = None

    processing_preset: str = "balanced"
    enable_profiling: bool = True
    enable_parse_cache: bool = True
    enable_modal_cache: bool = True
    preview_mode: bool = False

    parser: str = "mineru"
    parse_method: str = "auto"

    enable_vlm_enhancement: bool = False
    enable_image_processing: bool = True
    enable_table_processing: bool = True
    enable_equation_processing: bool = True
    max_concurrent_files: int | None = Field(default=None, ge=1, le=32)
    embedding_batch_size: int | None = Field(default=None, ge=1, le=1024)
    llm_max_concurrency: int | None = Field(default=None, ge=1, le=64)
    vlm_max_concurrency: int | None = Field(default=None, ge=1, le=64)
    embedding_max_concurrency: int | None = Field(default=None, ge=1, le=128)
    retry_max_attempts: int | None = Field(default=None, ge=1, le=10)
    retry_base_delay: float | None = Field(default=None, ge=0, le=60)
    retry_max_delay: float | None = Field(default=None, ge=0, le=300)
    write_lock_enabled: bool = True

    lang: str = "ch"
    device: str = "cpu"

    start_page: int | None = None
    end_page: int | None = None

    output_dir: str | None = None
    working_dir: str | None = None


class JobRecord(BaseModel):
    id: str
    document_id: str | None = None
    status: JobStatus
    stage: JobStage
    progress: float = 0.0
    message: str = ""
    logs: list[str] = Field(default_factory=list)
    error: str | None = None
    stage_durations: dict[str, float] = Field(default_factory=dict)
    api_call_counts: dict[str, int] = Field(default_factory=dict)
    cache_hits: dict[str, int] = Field(default_factory=dict)
    cache_misses: dict[str, int] = Field(default_factory=dict)
    created_at: datetime
    updated_at: datetime


class JobStartResponse(BaseModel):
    job_id: str
    status: JobStatus
