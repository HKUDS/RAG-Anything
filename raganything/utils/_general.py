# -*- coding: utf-8 -*-
"""
General Utilities — Processor Helpers, Response Formatting, SSE Events.

Layer: Core
Primary Responsibility: Modal processor dispatch, standardized JSON responses,
    Server-Sent Events formatting, pagination parsing.
Key Dependencies: lightrag.utils (logger), stdlib (json)
"""

from __future__ import annotations

import json
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List
from lightrag.utils import logger


BEIJING_TZ = timezone(timedelta(hours=8))


def beijing_now() -> str:
    """Return current Beijing time (UTC+8) formatted as ISO 8601 with offset.

    Returns:
        str: Timestamp like "2026-06-23T15:20:30+08:00"
    """
    return datetime.now(BEIJING_TZ).strftime("%Y-%m-%dT%H:%M:%S+08:00")


def get_processor_for_type(modal_processors: Dict[str, Any], content_type: str):
    """
    Get appropriate processor based on content type

    Args:
        modal_processors: Dictionary of available processors
        content_type: Content type

    Returns:
        Corresponding processor instance
    """
    if content_type == "image":
        return modal_processors.get("image") or modal_processors.get("generic")
    elif content_type == "table":
        return modal_processors.get("table")
    elif content_type == "equation":
        return modal_processors.get("equation")
    elif content_type == "video":
        return modal_processors.get("video") or modal_processors.get("generic")
    else:
        return modal_processors.get("generic")


def get_processor_supports(proc_type: str) -> List[str]:
    """Get processor supported features"""
    supports_map = {
        "image": [
            "Image content analysis", "Visual understanding",
            "Image description generation", "Image entity extraction",
        ],
        "table": [
            "Table structure analysis", "Data statistics",
            "Trend identification", "Table entity extraction",
        ],
        "equation": [
            "Mathematical formula parsing", "Variable identification",
            "Formula meaning explanation", "Formula entity extraction",
        ],
        "generic": [
            "General content analysis", "Structured processing",
            "Entity extraction",
        ],
        "video": [
            "Video content analysis", "Frame extraction and analysis",
            "Audio transcription", "Scene detection",
            "Temporal structure understanding", "Video entity extraction",
        ],
    }
    return supports_map.get(proc_type, ["Basic processing"])


def error_response(message: str, code: int = 400) -> dict:
    """Construct a standardized error response dict.

    Args:
        message: Human-readable error description
        code: HTTP status code (default 400)

    Returns:
        {"error": {"message": "...", "code": N}}
    """
    return {"error": {"message": message, "code": code}}


def success_response(data: Any = None, message: str = "ok") -> dict:
    """Construct a standardized success response dict.

    Args:
        data: Response data
        message: Status message

    Returns:
        {"status": "ok", "data": ...}
    """
    return {"status": "ok", "data": data or {}, "message": message}


def sse_event(data: dict, event_type: str = "message") -> str:
    """Construct an SSE (Server-Sent Events) formatted string.

    Args:
        data: Event data (JSON-serializable)
        event_type: Event type identifier

    Returns:
        Formatted SSE string: "data: {...}\\n\\n"
    """
    return f"data: {json.dumps(data, ensure_ascii=False)}\n\n"


def parse_pagination(
    page: int = 1, page_size: int = 20, max_page_size: int = 100,
) -> tuple:
    """Parse and normalize pagination parameters.

    Args:
        page: Page number (1-based)
        page_size: Items per page
        max_page_size: Maximum items per page

    Returns:
        (page, page_size, offset) tuple
    """
    page = max(1, page) if isinstance(page, int) else 1
    page_size = (
        page_size
        if (isinstance(page_size, int) and 0 < page_size <= max_page_size)
        else min(20, max_page_size)
    )
    offset = (page - 1) * page_size
    return page, page_size, offset


def loguru_warning_context(module_name: str, message: str, **context) -> None:
    """Log a warning with structured context using loguru patterns.

    Args:
        module_name: Module identifier
        message: Log message
        **context: Additional context fields
    """
    log = logger.bind(name=module_name, **context)
    log.warning(message)
