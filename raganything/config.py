"""
Configuration classes for RAGAnything

Contains configuration dataclasses with environment variable support
"""

from dataclasses import dataclass, field
from typing import List
from lightrag.utils import get_env_value


@dataclass
class RAGAnythingConfig:
    """Configuration class for RAGAnything with environment variable support"""

    # Directory Configuration
    # ---
    working_dir: str = field(default=get_env_value("WORKING_DIR", "./rag_storage", str))
    """Directory where RAG storage and cache files are stored."""

    # Parser Configuration
    # ---
    parse_method: str = field(default=get_env_value("PARSE_METHOD", "auto", str))
    """Default parsing method for document parsing: 'auto', 'ocr', or 'txt'."""

    parser_output_dir: str = field(default=get_env_value("OUTPUT_DIR", "./output", str))
    """Default output directory for parsed content."""

    parser: str = field(default=get_env_value("PARSER", "mineru", str))
    """Parser selection: 'mineru', 'docling', 'paddleocr', or 'marker'."""

    # Entity Extraction Configuration
    # ---
    entity_types: str = field(default=get_env_value("ENTITY_TYPES", "", str))
    """Comma-separated list of entity types for LightRAG extraction.
    When empty (default), LightRAG uses its built-in default entity types
    (Person, Organization, Location, Event, Concept, Method, Content, Data,
    Artifact, NaturalObject). When set (e.g. "Part,Process,Material"), only
    the specified types are extracted. Maps to LightRAG's
    ``addon_params.entity_types``."""

    lightrag_language: str = field(default=get_env_value("LIGHTRAG_LANGUAGE", "Chinese", str))
    """Language for LightRAG keyword extraction and summarization.
    Default is 'Chinese' for Chinese knowledge bases. Set to 'English' for
    English KBs. Maps to LightRAG's ``addon_params.language``."""

    entity_extraction_min_degree: int = field(
        default=get_env_value("ENTITY_EXTRACTION_MIN_DEGREE", 0, int)
    )
    """Minimum graph degree for entities to be retained. Entities with degree
    below this threshold are removed after extraction. Default 0 means no
    filtering. Set to 1 to remove completely isolated entities (no relations)."""

    entity_extract_concurrency: int = field(
        default=get_env_value("ENTITY_EXTRACT_CONCURRENCY", 3, int)
    )
    """Maximum number of concurrent entity extraction calls during LightRAG processing.
    Higher values reduce total processing time but increase API rate limit pressure."""

    embedding_batch_size: int = field(
        default=get_env_value("EMBEDDING_BATCH_SIZE", 10, int)
    )
    """Number of text chunks to batch into a single embedding API call.
    Reduces API round-trips from N to N/batch_size. Default 10."""

    display_content_stats: bool = field(
        default=get_env_value("DISPLAY_CONTENT_STATS", True, bool)
    )
    """Whether to display content statistics during parsing."""

    # Multimodal Processing Configuration
    # ---
    enable_image_processing: bool = field(
        default=get_env_value("ENABLE_IMAGE_PROCESSING", True, bool)
    )
    """Enable image content processing."""

    enable_table_processing: bool = field(
        default=get_env_value("ENABLE_TABLE_PROCESSING", True, bool)
    )
    """Enable table content processing."""

    enable_equation_processing: bool = field(
        default=get_env_value("ENABLE_EQUATION_PROCESSING", True, bool)
    )
    """Enable equation content processing."""

    enable_video_processing: bool = field(
        default=get_env_value("ENABLE_VIDEO_PROCESSING", False, bool)
    )
    """Enable video content processing. Defaults to False due to heavy optional dependencies (ffmpeg, opencv, whisper)."""

    video_sample_rate: float = field(
        default=get_env_value("VIDEO_SAMPLE_RATE", 1.0, float)
    )
    """Frames per second to extract from video."""

    video_max_duration: int = field(
        default=get_env_value("VIDEO_MAX_DURATION", 3600, int)
    )
    """Maximum video duration in seconds to process."""

    video_max_frames: int = field(
        default=get_env_value("VIDEO_MAX_FRAMES", 60, int)
    )
    """Hard cap on frames extracted per video. Overrides video_sample_rate if exceeded to prevent excessive API calls."""

    enable_audio_transcription: bool = field(
        default=get_env_value("ENABLE_AUDIO_TRANSCRIPTION", False, bool)
    )
    """Enable audio transcription via Whisper for video processing. Requires openai-whisper (~1.5GB model)."""

    enable_scene_detection: bool = field(
        default=get_env_value("ENABLE_SCENE_DETECTION", True, bool)
    )
    """Enable scene boundary detection for intelligent frame selection in video processing."""

    max_transcript_tokens: int = field(
        default=get_env_value("MAX_TRANSCRIPT_TOKENS", 4000, int)
    )
    """Maximum number of tokens for audio transcript."""

    whisper_model_size: str = field(
        default=get_env_value("WHISPER_MODEL_SIZE", "small", str)
    )
    """Whisper model size for audio transcription.
    Allowed values: ``"tiny"``, ``"base"``, ``"small"``, ``"medium"``, ``"large"``.
    Default ``"small"`` balances accuracy and resource usage (~2GB RAM, ~10-15% Chinese WER)."""

    video_max_concurrent: int = field(
        default=get_env_value("VIDEO_MAX_CONCURRENT", 2, int)
    )
    """Maximum concurrent video processing tasks."""

    video_frame_concurrent: int = field(
        default=get_env_value("VIDEO_FRAME_CONCURRENT", 3, int)
    )
    """Maximum number of concurrent frame VLM analysis calls per video. Default 3."""

    enable_frame_cache: bool = field(
        default=get_env_value("ENABLE_FRAME_CACHE", True, bool)
    )
    """Enable frame description cache to skip repeated VLM calls for the same video. Default true."""

    enforce_citation: bool = field(
        default=get_env_value("RAG_ENFORCE_CITATION", True, bool)
    )
    """Enforce mandatory source citations in all query answers.
    When True (default), uses ANSWER_FORMAT_INSTRUCTION which requires every
    factual statement to carry a [来源 N] marker with 《文档名》,
    a 📚 参考来源 block, and 关联实体 summary (when entity relations exist).
    When False, falls back to the lighter INLINE_QUOTE_INSTRUCTION.
    Maps to environment variable RAG_ENFORCE_CITATION."""

    # Batch Processing Configuration
    # ---
    max_concurrent_files: int = field(
        default=get_env_value("MAX_CONCURRENT_FILES", 1, int)
    )
    """Maximum number of files to process concurrently."""

    supported_file_extensions: List[str] = field(
        default_factory=lambda: [
            x.strip()
            for x in get_env_value(
                "SUPPORTED_FILE_EXTENSIONS",
                ".pdf,.jpg,.jpeg,.png,.bmp,.tiff,.tif,.gif,.webp,.doc,.docx,.ppt,.pptx,.xls,.xlsx,.txt,.md,.mp4,.avi,.mov,.mkv,.webm",
                str,
            ).split(",")
        ]
    )
    """List of supported file extensions for batch processing."""

    recursive_folder_processing: bool = field(
        default=get_env_value("RECURSIVE_FOLDER_PROCESSING", True, bool)
    )
    """Whether to recursively process subfolders in batch mode."""

    # Context Extraction Configuration
    # ---
    context_window: int = field(default=get_env_value("CONTEXT_WINDOW", 1, int))
    """Number of pages/chunks to include before and after current item for context."""

    context_mode: str = field(default=get_env_value("CONTEXT_MODE", "page", str))
    """Context extraction mode: 'page' for page-based, 'chunk' for chunk-based."""

    max_context_tokens: int = field(
        default=get_env_value("MAX_CONTEXT_TOKENS", 2000, int)
    )
    """Maximum number of tokens in extracted context."""

    include_headers: bool = field(default=get_env_value("INCLUDE_HEADERS", True, bool))
    """Whether to include document headers and titles in context."""

    include_captions: bool = field(
        default=get_env_value("INCLUDE_CAPTIONS", True, bool)
    )
    """Whether to include image/table captions in context."""

    context_filter_content_types: List[str] = field(
        default_factory=lambda: [
            x.strip()
            for x in get_env_value("CONTEXT_FILTER_CONTENT_TYPES", "text", str).split(
                ","
            )
        ]
    )
    """Content types to include in context extraction (e.g., 'text', 'image', 'table')."""

    content_format: str = field(default=get_env_value("CONTENT_FORMAT", "minerU", str))
    """Default content format for context extraction when processing documents."""

    # Path Handling Configuration
    # ---
    use_full_path: bool = field(default=get_env_value("USE_FULL_PATH", False, bool))
    """Whether to use full file path (True) or just basename (False) for file references in LightRAG."""

    def __post_init__(self):
        """Post-initialization setup for backward compatibility and bounds validation"""
        # Support legacy environment variable names for backward compatibility
        legacy_parse_method = get_env_value("MINERU_PARSE_METHOD", None, str)
        if legacy_parse_method and not get_env_value("PARSE_METHOD", None, str):
            self.parse_method = legacy_parse_method
            import warnings

            warnings.warn(
                "MINERU_PARSE_METHOD is deprecated. Use PARSE_METHOD instead.",
                DeprecationWarning,
                stacklevel=2,
            )

        # ── 安全上限校验：防止恶意/误配置导致 API 预算耗尽 ──
        import warnings as _w

        _max_entity_concurrency = 16
        if self.entity_extract_concurrency > _max_entity_concurrency:
            _w.warn(
                f"ENTITY_EXTRACT_CONCURRENCY={self.entity_extract_concurrency} "
                f"超过上限 {_max_entity_concurrency}，已钳制",
                UserWarning, stacklevel=2,
            )
            self.entity_extract_concurrency = _max_entity_concurrency

        _max_embed_batch = 10
        if self.embedding_batch_size > _max_embed_batch:
            _w.warn(
                f"EMBEDDING_BATCH_SIZE={self.embedding_batch_size} "
                f"超过 DashScope 上限 {_max_embed_batch}，已钳制",
                UserWarning, stacklevel=2,
            )
            self.embedding_batch_size = _max_embed_batch

        # ── whisper_model_size 枚举验证 ──────────────────────────
        _allowed_whisper = frozenset({"tiny", "base", "small", "medium", "large"})
        if self.whisper_model_size not in _allowed_whisper:
            _w.warn(
                f"WHISPER_MODEL_SIZE={self.whisper_model_size!r} 无效，"
                f"允许值: {sorted(_allowed_whisper)}，已钳制为 'small'",
                UserWarning, stacklevel=2,
            )
            self.whisper_model_size = "small"

        # ── video_max_duration 边界验证 ──────────────────────────
        if self.video_max_duration < 1:
            _w.warn(
                f"VIDEO_MAX_DURATION={self.video_max_duration} < 1，已钳制为 1",
                UserWarning, stacklevel=2,
            )
            self.video_max_duration = 1
        elif self.video_max_duration > 86400:
            _w.warn(
                f"VIDEO_MAX_DURATION={self.video_max_duration} > 86400，已钳制为 86400",
                UserWarning, stacklevel=2,
            )
            self.video_max_duration = 86400

    @property
    def mineru_parse_method(self) -> str:
        """
        Backward compatibility property for old code.

        .. deprecated::
           Use `parse_method` instead. This property will be removed in a future version.
        """
        import warnings

        warnings.warn(
            "mineru_parse_method is deprecated. Use parse_method instead.",
            DeprecationWarning,
            stacklevel=2,
        )
        return self.parse_method

    @mineru_parse_method.setter
    def mineru_parse_method(self, value: str):
        """Setter for backward compatibility"""
        import warnings

        warnings.warn(
            "mineru_parse_method is deprecated. Use parse_method instead.",
            DeprecationWarning,
            stacklevel=2,
        )
        self.parse_method = value
