"""
Configuration classes for RAGAnything

Contains configuration dataclasses with environment variable support
"""

from dataclasses import dataclass, field

from lightrag.utils import get_env_value


@dataclass
class RAGAnythingConfig:
    """Configuration whose environment defaults are read at instantiation."""

    # Directory Configuration
    # ---
    working_dir: str = field(
        default_factory=lambda: get_env_value("WORKING_DIR", "./rag_storage", str)
    )
    """Directory where RAG storage and cache files are stored."""

    # Parser Configuration
    # ---
    parse_method: str = field(
        default_factory=lambda: get_env_value("PARSE_METHOD", "auto", str)
    )
    """Default parsing method for document parsing: 'auto', 'ocr', or 'txt'."""

    parser_output_dir: str = field(
        default_factory=lambda: get_env_value("OUTPUT_DIR", "./output", str)
    )
    """Default output directory for parsed content."""

    parser: str = field(default_factory=lambda: get_env_value("PARSER", "mineru", str))
    """Parser selection: 'mineru', 'docling', or 'paddleocr'."""

    display_content_stats: bool = field(
        default_factory=lambda: get_env_value("DISPLAY_CONTENT_STATS", True, bool)
    )
    """Whether to display content statistics during parsing."""

    # Multimodal Processing Configuration
    # ---
    enable_image_processing: bool = field(
        default_factory=lambda: get_env_value("ENABLE_IMAGE_PROCESSING", True, bool)
    )
    """Enable image content processing."""

    enable_table_processing: bool = field(
        default_factory=lambda: get_env_value("ENABLE_TABLE_PROCESSING", True, bool)
    )
    """Enable table content processing."""

    enable_equation_processing: bool = field(
        default_factory=lambda: get_env_value("ENABLE_EQUATION_PROCESSING", True, bool)
    )
    """Enable equation content processing."""

    enable_audio_processing: bool = field(
        default_factory=lambda: get_env_value("ENABLE_AUDIO_PROCESSING", False, bool)
    )
    """Enable audio content processing. Requires optional 'audio' dependencies
    (``pip install raganything[audio]``); disabled by default."""

    enable_video_processing: bool = field(
        default_factory=lambda: get_env_value("ENABLE_VIDEO_PROCESSING", False, bool)
    )
    """Enable video content processing. Requires optional 'video' dependencies
    (``pip install raganything[video]``); disabled by default."""

    # Batch Processing Configuration
    # ---
    max_concurrent_files: int = field(
        default_factory=lambda: get_env_value("MAX_CONCURRENT_FILES", 1, int)
    )
    """Maximum number of files to process concurrently."""

    supported_file_extensions: list[str] = field(
        default_factory=lambda: [
            x.strip()
            for x in get_env_value(
                "SUPPORTED_FILE_EXTENSIONS",
                ".pdf,.jpg,.jpeg,.png,.bmp,.tiff,.tif,.gif,.webp,.doc,.docx,.ppt,.pptx,.xls,.xlsx,.txt,.md,.mp3,.wav,.flac,.m4a,.ogg,.wma,.aac,.opus,.mp4,.mov,.webm,.avi,.mkv,.flv,.wmv,.m4v",
                str,
            ).split(",")
        ]
    )
    """List of supported file extensions for batch processing."""

    recursive_folder_processing: bool = field(
        default_factory=lambda: get_env_value("RECURSIVE_FOLDER_PROCESSING", True, bool)
    )
    """Whether to recursively process subfolders in batch mode."""

    # Context Extraction Configuration
    # ---
    context_window: int = field(
        default_factory=lambda: get_env_value("CONTEXT_WINDOW", 1, int)
    )
    """Number of pages/chunks to include before and after current item for context."""

    context_mode: str = field(
        default_factory=lambda: get_env_value("CONTEXT_MODE", "page", str)
    )
    """Context extraction mode: 'page' for page-based, 'chunk' for chunk-based."""

    max_context_tokens: int = field(
        default_factory=lambda: get_env_value("MAX_CONTEXT_TOKENS", 2000, int)
    )
    """Maximum number of tokens in extracted context."""

    include_headers: bool = field(
        default_factory=lambda: get_env_value("INCLUDE_HEADERS", True, bool)
    )
    """Whether to include document headers and titles in context."""

    include_captions: bool = field(
        default_factory=lambda: get_env_value("INCLUDE_CAPTIONS", True, bool)
    )
    """Whether to include image/table captions in context."""

    context_filter_content_types: list[str] = field(
        default_factory=lambda: [
            x.strip()
            for x in get_env_value("CONTEXT_FILTER_CONTENT_TYPES", "text", str).split(
                ","
            )
        ]
    )
    """Content types to include in context extraction (e.g., 'text', 'image', 'table')."""

    content_format: str = field(
        default_factory=lambda: get_env_value("CONTENT_FORMAT", "minerU", str)
    )
    """Default content format for context extraction when processing documents."""

    # Multimodal KG extraction (call-count controls for issue #348)
    # ---
    multimodal_kg_extraction_mode: str = field(
        default_factory=lambda: get_env_value(
            "MULTIMODAL_KG_EXTRACTION_MODE", "packed", str
        )
    )
    """How multimodal items feed LightRAG entity extraction after vision/captioning.

    - ``packed`` (default): pack description-only captions into token-budgeted
      extraction units so extract/merge call count scales with caption tokens,
      not image count. Full templated chunks (including neighbor text) still
      go to the vector store for retrieval.
    - ``per_item``: legacy behaviour — one extract call per multimodal chunk
      (still uses description-only content for extraction to avoid re-feeding
      surrounding page text through the KG pipeline).
    - ``skip``: vision + store chunks/main entities only; no multimodal
      extract/merge. Lowest LLM call count.
    """

    max_parallel_modal_items: int | None = field(
        default_factory=lambda: get_env_value("MAX_PARALLEL_MODAL_ITEMS", None, int)
    )
    """Optional concurrency limit for multimodal section generation (vision/
    caption). When unset, falls back to ``LightRAG.max_parallel_insert`` (or 2).
    Separate from text-insert parallelism so image-heavy pages can tune vision
    concurrency without changing LightRAG's document insert limit.
    """

    # Path Handling Configuration
    # ---
    use_full_path: bool = field(
        default_factory=lambda: get_env_value("USE_FULL_PATH", False, bool)
    )
    """Whether to use full file path (True) or just basename (False) for file references in LightRAG."""

    def __post_init__(self):
        """Post-initialization setup for backward compatibility"""
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
