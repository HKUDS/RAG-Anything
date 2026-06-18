# -*- coding: utf-8 -*-
"""
RAG-Anything Security Utilities.

Layer: Core
Primary Responsibility: Prompt injection detection, input validation, sanitization.
Key Dependencies: fastapi (HTTPException), stdlib (re)

Extracted from routers/shared.py to provide a single import source for
security-related validation used across all router modules.
"""

import re as _re_valid
from fastapi import HTTPException


# ── Prompt Injection Detection Patterns ────────────────────

PROMPT_INJECTION_PATTERNS = [
    r"(ignore|forget|disregard)\s+(all\s+)?(previous|prior|above|earlier)\s+(instructions?|prompts?|commands?)",
    r"(you\s+are|act\s+as|pretend\s+to\s+be|roleplay\s+as)\s+(now|from\s+now\s+on)",
    r"(system\s*(prompt|message|instruction))",
    r"<\s*(script|iframe|object|embed|style)\b",
    r"(javascript|onerror|onload|onclick)\s*:",
    r"(\.\./|\.\.\\)",  # path traversal
]

PROMPT_INJECTION_REGEX = [
    _re_valid.compile(p, _re_valid.IGNORECASE) for p in PROMPT_INJECTION_PATTERNS
]

# ── Validation ─────────────────────────────────────────────

MAX_QUERY_LENGTH = 5000


def validate_query_input(query: str) -> str:
    """Validate query input and detect prompt injection attacks.

    Args:
        query: Raw user query string

    Returns:
        Cleaned query string

    Raises:
        HTTPException(400): Empty query, too long query, or detected injection
    """
    if not query or not query.strip():
        raise HTTPException(400, "查询内容不能为空")

    if len(query) > MAX_QUERY_LENGTH:
        raise HTTPException(400, "查询内容超过最大长度限制")

    for pattern in PROMPT_INJECTION_REGEX:
        if pattern.search(query):
            raise HTTPException(400, "请求包含不安全内容")

    return query.strip()


__all__ = [
    "PROMPT_INJECTION_PATTERNS",
    "PROMPT_INJECTION_REGEX",
    "validate_query_input",
    "MAX_QUERY_LENGTH",
]
