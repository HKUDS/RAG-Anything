from __future__ import annotations

from pydantic import BaseModel, Field


class EnvironmentResponse(BaseModel):
    python: str
    raganything_installed: bool
    lightrag_installed: bool
    mineru_available: bool
    docling_available: bool
    paddleocr_available: bool
    libreoffice_available: bool
    cuda_gpu_present: bool   # NVIDIA GPU hardware detected (nvcc/nvidia-smi)
    cuda_available: bool     # torch.cuda.is_available() — full stack ready
    mps_available: bool      # Apple Silicon MPS (macOS arm64)


class BrowseDirEntry(BaseModel):
    name: str
    path: str
    is_dir: bool


class BrowseDirResponse(BaseModel):
    path: str          # resolved absolute path that was listed
    parent: str | None  # parent path, None at filesystem root
    entries: list[BrowseDirEntry]


class InstallDepRequest(BaseModel):
    package: str  # pip install target, e.g. "docling", "mineru[core]"


class InstallDepResponse(BaseModel):
    ok: bool
    output: str
    error: str | None = None


class ModelChannelResponse(BaseModel):
    provider: str
    model: str
    base_url: str | None = None
    api_key_configured: bool
    embedding_dim: int | None = None
    embedding_max_token_size: int | None = None


class ModelProfileResponse(BaseModel):
    id: str
    name: str
    llm: ModelChannelResponse
    embedding: ModelChannelResponse
    vision: ModelChannelResponse


class StudioSettingsResponse(BaseModel):
    data_dir: str
    upload_dir: str
    working_dir: str
    output_dir: str
    settings_file: str
    llm_provider: str
    llm_model: str
    llm_base_url: str | None = None
    llm_api_key_configured: bool
    embedding_provider: str
    embedding_model: str
    embedding_dim: int
    embedding_max_token_size: int
    embedding_base_url: str | None = None
    embedding_api_key_configured: bool
    vision_provider: str
    vision_model: str
    vision_base_url: str | None = None
    vision_api_key_configured: bool
    default_parser: str
    default_parse_method: str
    default_language: str
    default_device: str
    default_enable_vlm_enhancement: bool
    max_concurrent_files: int
    default_processing_preset: str
    default_enable_parse_cache: bool
    default_enable_modal_cache: bool
    default_preview_mode: bool
    embedding_batch_size: int
    llm_max_concurrency: int
    vlm_max_concurrency: int
    embedding_max_concurrency: int
    retry_max_attempts: int
    retry_base_delay: float
    retry_max_delay: float
    write_lock_enabled: bool
    kv_storage: str
    vector_storage: str
    graph_storage: str
    doc_status_storage: str
    vector_db_storage_cls_kwargs: dict = Field(default_factory=dict)
    storage_env: dict[str, str] = Field(default_factory=dict)
    active_profile_id: str
    profiles: list[ModelProfileResponse]


class ModelChannelUpdate(BaseModel):
    provider: str = "openai-compatible"
    model: str = Field(min_length=1)
    base_url: str | None = None
    api_key: str | None = None
    embedding_dim: int | None = Field(default=None, gt=0)
    embedding_max_token_size: int | None = Field(default=None, gt=0)


class ModelProfileUpdate(BaseModel):
    id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    llm: ModelChannelUpdate
    embedding: ModelChannelUpdate
    vision: ModelChannelUpdate


class StudioSettingsUpdate(BaseModel):
    data_dir: str | None = None
    upload_dir: str | None = None
    working_dir: str | None = None
    output_dir: str | None = None

    llm_provider: str = "openai-compatible"
    llm_model: str = Field(min_length=1)
    llm_base_url: str | None = None
    llm_api_key: str | None = None

    embedding_provider: str = "openai-compatible"
    embedding_model: str = Field(min_length=1)
    embedding_dim: int = Field(gt=0)
    embedding_max_token_size: int = Field(gt=0)
    embedding_base_url: str | None = None
    embedding_api_key: str | None = None

    vision_provider: str = "openai-compatible"
    vision_model: str = Field(min_length=1)
    vision_base_url: str | None = None
    vision_api_key: str | None = None

    default_parser: str = Field(min_length=1)
    default_parse_method: str = Field(min_length=1)
    default_language: str = Field(min_length=1)
    default_device: str = Field(min_length=1)
    default_enable_vlm_enhancement: bool = False
    max_concurrent_files: int = Field(default=1, ge=1, le=32)
    default_processing_preset: str = "balanced"
    default_enable_parse_cache: bool = True
    default_enable_modal_cache: bool = True
    default_preview_mode: bool = False
    embedding_batch_size: int = Field(default=16, ge=1, le=1024)
    llm_max_concurrency: int = Field(default=2, ge=1, le=64)
    vlm_max_concurrency: int = Field(default=1, ge=1, le=64)
    embedding_max_concurrency: int = Field(default=4, ge=1, le=128)
    retry_max_attempts: int = Field(default=3, ge=1, le=10)
    retry_base_delay: float = Field(default=0.75, ge=0, le=60)
    retry_max_delay: float = Field(default=8.0, ge=0, le=300)
    write_lock_enabled: bool = True
    kv_storage: str = "JsonKVStorage"
    vector_storage: str = "NanoVectorDBStorage"
    graph_storage: str = "NetworkXStorage"
    doc_status_storage: str = "JsonDocStatusStorage"
    vector_db_storage_cls_kwargs: dict = Field(default_factory=dict)
    storage_env: dict[str, str] = Field(default_factory=dict)
    active_profile_id: str | None = None
    profiles: list[ModelProfileUpdate] | None = None


class SettingsSaveResponse(BaseModel):
    settings: StudioSettingsResponse


class ConnectionTestRequest(BaseModel):
    """Payload for testing a single provider connection using unsaved form values."""
    kind: str  # "llm" | "embedding" | "vision"
    profile_id: str | None = None
    provider: str
    model: str
    base_url: str | None = None
    api_key: str | None = None
    embedding_dim: int = 1536
    embedding_max_token_size: int = 8192


class ConnectionTestResponse(BaseModel):
    ok: bool
    latency_ms: float | None = None
    error: str | None = None
    detected_dim: int | None = None  # populated only when kind=="embedding" and ok==True


class ModelInfo(BaseModel):
    id: str
    owned_by: str = ""
    context_length: int | None = None
    vision_capable: bool = False


class ModelListRequest(BaseModel):
    provider: str
    base_url: str | None = None
    api_key: str | None = None
    kind: str | None = None  # "llm" | "embedding" | "vision"


class ModelListResponse(BaseModel):
    ok: bool
    models: list[ModelInfo] = []
    error: str | None = None
