from __future__ import annotations

from pydantic import BaseModel, Field


class EnvironmentResponse(BaseModel):
    python: str
    raganything_installed: bool
    lightrag_installed: bool
    mineru_available: bool
    libreoffice_available: bool
    cuda_available: bool


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


class SettingsSaveResponse(BaseModel):
    settings: StudioSettingsResponse


class ConnectionTestRequest(BaseModel):
    """Payload for testing a single provider connection using unsaved form values."""
    kind: str  # "llm" | "embedding" | "vision"
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


class ModelListRequest(BaseModel):
    provider: str
    base_url: str | None = None
    api_key: str | None = None


class ModelListResponse(BaseModel):
    ok: bool
    models: list[ModelInfo] = []
    error: str | None = None
