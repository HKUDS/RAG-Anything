from __future__ import annotations

import os
import json
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv


@dataclass
class ModelChannelConfig:
    """Provider settings for one model role inside a Studio profile."""

    provider: str
    model: str
    base_url: str | None = None
    api_key: str | None = None
    embedding_dim: int | None = None
    embedding_max_token_size: int | None = None


@dataclass
class ModelProviderProfile:
    """A reusable RAG model profile selected during indexing/querying."""

    id: str
    name: str
    llm: ModelChannelConfig
    embedding: ModelChannelConfig
    vision: ModelChannelConfig


@dataclass
class StudioSettings:
    """Runtime settings for the local Studio process."""

    data_dir: Path
    upload_dir: Path
    output_dir: Path
    working_dir: Path
    static_dir: Path
    settings_file: Path

    llm_provider: str
    llm_model: str
    llm_base_url: str | None
    llm_api_key: str | None
    embedding_provider: str
    embedding_model: str
    embedding_dim: int
    embedding_max_token_size: int
    embedding_base_url: str | None
    embedding_api_key: str | None
    vision_provider: str
    vision_model: str
    vision_base_url: str | None
    vision_api_key: str | None

    default_parser: str
    default_parse_method: str
    default_language: str
    default_device: str
    default_enable_vlm_enhancement: bool = False
    max_concurrent_files: int = 1
    default_processing_preset: str = "balanced"
    default_enable_parse_cache: bool = True
    default_enable_modal_cache: bool = True
    default_preview_mode: bool = False
    embedding_batch_size: int = 16
    llm_max_concurrency: int = 2
    vlm_max_concurrency: int = 1
    embedding_max_concurrency: int = 4
    retry_max_attempts: int = 3
    retry_base_delay: float = 0.75
    retry_max_delay: float = 8.0
    write_lock_enabled: bool = True
    kv_storage: str = "JsonKVStorage"
    vector_storage: str = "NanoVectorDBStorage"
    graph_storage: str = "NetworkXStorage"
    doc_status_storage: str = "JsonDocStatusStorage"
    vector_db_storage_cls_kwargs: dict = field(default_factory=dict)
    storage_env: dict[str, str] = field(default_factory=dict)
    active_profile_id: str = "default"
    profiles: list[ModelProviderProfile] = field(default_factory=list)


def _env_path(name: str, default: str) -> Path:
    return Path(os.getenv(name, default)).expanduser().resolve()


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _env_json(name: str) -> dict:
    raw = os.getenv(name)
    if not raw:
        return {}
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}


def get_settings() -> StudioSettings:
    for env_file in (Path(".env"), Path("reproduce/.env")):
        if env_file.exists():
            load_dotenv(env_file, override=False)

    data_dir = _env_path("RAGANYTHING_STUDIO_DATA_DIR", "./studio_data")
    static_dir = Path(__file__).parent / "static"

    llm_provider = os.getenv("LLM_PROVIDER", "openai-compatible")
    llm_model = os.getenv("LLM_MODEL", "gpt-4o-mini")
    llm_base_url = os.getenv("LLM_BASE_URL") or os.getenv("OPENAI_BASE_URL")
    llm_api_key = (
        os.getenv("LLM_API_KEY")
        or os.getenv("OPENAI_API_KEY")
        or os.getenv("LLM_BINDING_API_KEY")
    )
    embedding_provider = os.getenv("EMBEDDING_PROVIDER", "openai-compatible")
    embedding_model = os.getenv("EMBEDDING_MODEL", "text-embedding-3-large")
    embedding_dim = int(os.getenv("EMBEDDING_DIM", "3072"))
    embedding_max_token_size = int(os.getenv("EMBEDDING_MAX_TOKEN_SIZE", "8192"))
    embedding_base_url = os.getenv("EMBEDDING_BASE_URL") or os.getenv("OPENAI_BASE_URL")
    embedding_api_key = (
        os.getenv("EMBEDDING_API_KEY")
        or os.getenv("OPENAI_API_KEY")
        or os.getenv("EMBEDDING_BINDING_API_KEY")
    )
    vision_provider = os.getenv("VISION_PROVIDER", "openai-compatible")
    vision_model = os.getenv("VISION_MODEL", "gpt-4o")
    vision_base_url = os.getenv("VISION_BASE_URL") or os.getenv("OPENAI_BASE_URL")
    vision_api_key = (
        os.getenv("VISION_API_KEY")
        or os.getenv("OPENAI_API_KEY")
        or os.getenv("VLM_BINDING_API_KEY")
    )

    settings = StudioSettings(
        data_dir=data_dir,
        upload_dir=_env_path("RAGANYTHING_STUDIO_UPLOAD_DIR", str(data_dir / "uploads")),
        output_dir=_env_path("RAGANYTHING_STUDIO_OUTPUT_DIR", str(data_dir / "output")),
        working_dir=_env_path(
            "RAGANYTHING_STUDIO_WORKING_DIR", str(data_dir / "rag_storage")
        ),
        static_dir=static_dir,
        settings_file=_env_path(
            "RAGANYTHING_STUDIO_SETTINGS_FILE", str(data_dir / "settings.json")
        ),
        llm_provider=llm_provider,
        llm_model=llm_model,
        llm_base_url=llm_base_url,
        llm_api_key=llm_api_key,
        embedding_provider=embedding_provider,
        embedding_model=embedding_model,
        embedding_dim=embedding_dim,
        embedding_max_token_size=embedding_max_token_size,
        embedding_base_url=embedding_base_url,
        embedding_api_key=embedding_api_key,
        vision_provider=vision_provider,
        vision_model=vision_model,
        vision_base_url=vision_base_url,
        vision_api_key=vision_api_key,
        default_parser=os.getenv("RAGANYTHING_STUDIO_DEFAULT_PARSER", "mineru"),
        default_parse_method=os.getenv("RAGANYTHING_STUDIO_DEFAULT_PARSE_METHOD", "auto"),
        default_language=os.getenv("RAGANYTHING_STUDIO_DEFAULT_LANGUAGE", "ch"),
        default_device=os.getenv("RAGANYTHING_STUDIO_DEFAULT_DEVICE", "cpu"),
        default_enable_vlm_enhancement=_env_bool(
            "RAGANYTHING_STUDIO_ENABLE_VLM_ENHANCEMENT", False
        ),
        max_concurrent_files=max(
            1,
            int(
                os.getenv(
                    "RAGANYTHING_STUDIO_MAX_CONCURRENT_FILES",
                    os.getenv("MAX_CONCURRENT_FILES", "1"),
                )
            ),
        ),
        default_processing_preset=os.getenv(
            "RAGANYTHING_STUDIO_PROCESSING_PRESET", "balanced"
        ),
        default_enable_parse_cache=_env_bool(
            "RAGANYTHING_STUDIO_ENABLE_PARSE_CACHE", True
        ),
        default_enable_modal_cache=_env_bool(
            "RAGANYTHING_STUDIO_ENABLE_MODAL_CACHE", True
        ),
        default_preview_mode=_env_bool("RAGANYTHING_STUDIO_PREVIEW_MODE", False),
        embedding_batch_size=max(
            1, int(os.getenv("RAGANYTHING_STUDIO_EMBEDDING_BATCH_SIZE", "16"))
        ),
        llm_max_concurrency=max(
            1, int(os.getenv("RAGANYTHING_STUDIO_LLM_MAX_CONCURRENCY", "2"))
        ),
        vlm_max_concurrency=max(
            1, int(os.getenv("RAGANYTHING_STUDIO_VLM_MAX_CONCURRENCY", "1"))
        ),
        embedding_max_concurrency=max(
            1, int(os.getenv("RAGANYTHING_STUDIO_EMBEDDING_MAX_CONCURRENCY", "4"))
        ),
        retry_max_attempts=max(
            1, int(os.getenv("RAGANYTHING_STUDIO_RETRY_MAX_ATTEMPTS", "3"))
        ),
        retry_base_delay=max(
            0.0, float(os.getenv("RAGANYTHING_STUDIO_RETRY_BASE_DELAY", "0.75"))
        ),
        retry_max_delay=max(
            0.0, float(os.getenv("RAGANYTHING_STUDIO_RETRY_MAX_DELAY", "8.0"))
        ),
        write_lock_enabled=_env_bool("RAGANYTHING_STUDIO_WRITE_LOCK_ENABLED", True),
        kv_storage=os.getenv("RAGANYTHING_STUDIO_KV_STORAGE", "JsonKVStorage"),
        vector_storage=os.getenv(
            "RAGANYTHING_STUDIO_VECTOR_STORAGE", "NanoVectorDBStorage"
        ),
        graph_storage=os.getenv("RAGANYTHING_STUDIO_GRAPH_STORAGE", "NetworkXStorage"),
        doc_status_storage=os.getenv(
            "RAGANYTHING_STUDIO_DOC_STATUS_STORAGE", "JsonDocStatusStorage"
        ),
        vector_db_storage_cls_kwargs=_env_json(
            "RAGANYTHING_STUDIO_VECTOR_DB_STORAGE_CLS_KWARGS"
        ),
        storage_env=_env_json("RAGANYTHING_STUDIO_STORAGE_ENV"),
        active_profile_id=os.getenv("RAGANYTHING_STUDIO_ACTIVE_PROFILE_ID", "default"),
        profiles=[
            ModelProviderProfile(
                id="default",
                name="Default RAG Profile",
                llm=ModelChannelConfig(
                    provider=llm_provider,
                    model=llm_model,
                    base_url=llm_base_url,
                    api_key=llm_api_key,
                ),
                embedding=ModelChannelConfig(
                    provider=embedding_provider,
                    model=embedding_model,
                    base_url=embedding_base_url,
                    api_key=embedding_api_key,
                    embedding_dim=embedding_dim,
                    embedding_max_token_size=embedding_max_token_size,
                ),
                vision=ModelChannelConfig(
                    provider=vision_provider,
                    model=vision_model,
                    base_url=vision_base_url,
                    api_key=vision_api_key,
                ),
            )
        ],
    )

    for directory in (
        settings.data_dir,
        settings.upload_dir,
        settings.output_dir,
        settings.working_dir,
        settings.static_dir,
        settings.settings_file.parent,
    ):
        directory.mkdir(parents=True, exist_ok=True)

    return settings
