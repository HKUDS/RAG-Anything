from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


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


def _env_path(name: str, default: str) -> Path:
    return Path(os.getenv(name, default)).expanduser().resolve()


def get_settings() -> StudioSettings:
    data_dir = _env_path("RAGANYTHING_STUDIO_DATA_DIR", "./studio_data")
    static_dir = Path(__file__).parent / "static"

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
        llm_provider=os.getenv("LLM_PROVIDER", "openai-compatible"),
        llm_model=os.getenv("LLM_MODEL", "gpt-4o-mini"),
        llm_base_url=os.getenv("LLM_BASE_URL") or os.getenv("OPENAI_BASE_URL"),
        llm_api_key=os.getenv("LLM_API_KEY") or os.getenv("OPENAI_API_KEY"),
        embedding_provider=os.getenv("EMBEDDING_PROVIDER", "openai-compatible"),
        embedding_model=os.getenv("EMBEDDING_MODEL", "text-embedding-3-large"),
        embedding_dim=int(os.getenv("EMBEDDING_DIM", "3072")),
        embedding_max_token_size=int(os.getenv("EMBEDDING_MAX_TOKEN_SIZE", "8192")),
        embedding_base_url=os.getenv("EMBEDDING_BASE_URL") or os.getenv("OPENAI_BASE_URL"),
        embedding_api_key=os.getenv("EMBEDDING_API_KEY") or os.getenv("OPENAI_API_KEY"),
        vision_provider=os.getenv("VISION_PROVIDER", "openai-compatible"),
        vision_model=os.getenv("VISION_MODEL", "gpt-4o"),
        vision_base_url=os.getenv("VISION_BASE_URL") or os.getenv("OPENAI_BASE_URL"),
        vision_api_key=os.getenv("VISION_API_KEY") or os.getenv("OPENAI_API_KEY"),
        default_parser=os.getenv("RAGANYTHING_STUDIO_DEFAULT_PARSER", "mineru"),
        default_parse_method=os.getenv("RAGANYTHING_STUDIO_DEFAULT_PARSE_METHOD", "auto"),
        default_language=os.getenv("RAGANYTHING_STUDIO_DEFAULT_LANGUAGE", "ch"),
        default_device=os.getenv("RAGANYTHING_STUDIO_DEFAULT_DEVICE", "cpu"),
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
