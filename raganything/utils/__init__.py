# -*- coding: utf-8 -*-
"""
RAG-Anything Utilities Sub-Package.

Layer: Core
Primary Responsibility: Pure utility functions — content separation,
    table/equation formatting, image encoding, text insertion,
    processor dispatch, SSE helpers, security validation.
Key Dependencies: lightrag.utils (logger), stdlib

Sub-modules:
    _content.py   — content separation, table/equation formatting, section paths
    _image.py     — base64 image encoding, file validation
    _insert.py    — LightRAG text insertion (pure + multimodal-aware)
    _general.py   — processor dispatch, response formatting, SSE, pagination
    security.py   — prompt injection detection, input validation

All public symbols are re-exported here for backward compatibility:
    from raganything.utils import separate_content, format_table_body, ...
"""

from raganything.utils._content import (  # noqa: F401 — re-export
    normalize_caption_list,
    get_table_body,
    format_table_body,
    simplify_table_body,
    get_equation_text_and_format,
    extract_section_path_from_content_list,
    extract_neighbor_text_from_content_list,
    separate_content,
)
from raganything.utils._image import (  # noqa: F401 — re-export
    encode_image_to_base64,
    image_mime_type,
    validate_image_file,
)
from raganything.utils._insert import (  # noqa: F401 — re-export
    insert_text_content,
    insert_text_content_with_multimodal_content,
)
from raganything.utils._general import (  # noqa: F401 — re-export
    beijing_now,
    get_processor_for_type,
    is_multimodal_processed,
    get_processor_supports,
    error_response,
    success_response,
    sse_event,
    parse_pagination,
    loguru_warning_context,
)
from raganything.utils._quality import (  # noqa: F401 — re-export
    check_ocr_quality,
    suggest_parse_method,
    detect_document_language,
    is_likely_scanned,
    validate_and_suggest,
)

__all__ = [
    # Beijing time
    "beijing_now",
    # Content separation & formatting
    "normalize_caption_list",
    "get_table_body",
    "format_table_body",
    "simplify_table_body",
    "get_equation_text_and_format",
    "extract_section_path_from_content_list",
    "extract_neighbor_text_from_content_list",
    "separate_content",
    # Image encoding
    "encode_image_to_base64",
    "image_mime_type",
    "validate_image_file",
    # Text insertion
    "insert_text_content",
    "insert_text_content_with_multimodal_content",
    # Processor dispatch & general
    "get_processor_for_type",
    "is_multimodal_processed",
    "get_processor_supports",
    "error_response",
    "success_response",
    "sse_event",
    "parse_pagination",
    "loguru_warning_context",
    # OCR quality + parse-method auto-selection
    "check_ocr_quality",
    "suggest_parse_method",
    "detect_document_language",
    "is_likely_scanned",
    "validate_and_suggest",
]
