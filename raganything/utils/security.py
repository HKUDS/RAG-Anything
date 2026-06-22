# -*- coding: utf-8 -*-
"""
RAG-Anything Security Utilities.

Layer: Core
Primary Responsibility: Prompt injection detection, input validation, sanitization.
Key Dependencies: fastapi (HTTPException), stdlib (re, unicodedata, hashlib, logging)

Extracted from routers/shared.py to provide a single import source for
security-related validation used across all router modules.
"""

import re as _re_valid
import unicodedata
import hashlib
import logging
import time
import uuid
from fastapi import HTTPException


# ── Zero-width and invisible character stripping ────────────

_ZERO_WIDTH_RE = _re_valid.compile(
    r'[​‌‍‎‏﻿­'
    r'⁠⁡⁢⁣⁤᠎'
    r'  ‪‫‬‭‮'
    r'⁦⁧⁨⁩]'
)

_security_logger = logging.getLogger("rag_server.security")


# ── Prompt Injection Detection Patterns ────────────────────

PROMPT_INJECTION_PATTERNS = [
    # English patterns
    r"(ignore|forget|disregard|override)\s+(all\s+)?(previous|prior|above|earlier|former)\s+(instructions?|prompts?|commands?|directives?|rules?)",
    r"(you\s+are|act\s+as|pretend\s+to\s+be|roleplay\s+as)\s+(now|from\s+now\s+on)",
    r"(system\s*(prompt|message|instruction|directive))",
    r"<\s*(script|iframe|object|embed|style)\b",
    r"(javascript|onerror|onload|onclick)\s*:",
    r"(\.\./|\.\.\\)",  # path traversal
    # Chinese patterns
    r"(忽略|忘记|无视|不理|跳过)\s*(所有|全部)?\s*(之前的|以前的|上面的|上述的)?\s*(指令|提示|命令|规则|要求)",
    r"(现在|从现在开始|从现在起)\s*(你是|你扮演|你作为|你是我的|你的角色是)",
    r"(系统\s*(提示|指令|消息|设定))",
    r"(新的|更新的|秘密的)\s*(指令|提示|命令|规则)",
    r"(不要|别|禁止)\s*(遵守|遵循|执行).*?(指令|提示|规则)",
    # Universal jailbreak patterns
    r"DAN\s*(mode|jailbreak)",
    r"(developer|debug|admin|override)\s*mode",
    r"(do\s*anything\s*now)",
    # Structural injection
    r"(##\s*(系统|system)\s*(提示|prompt|指令))",
    r"(</?system[^>]*>)",
    # Encoded payload indicators
    r"(base64|fromCharCode|eval\s*\(|atob\s*\()",
]

PROMPT_INJECTION_REGEX = [
    _re_valid.compile(p, _re_valid.IGNORECASE | _re_valid.DOTALL)
    for p in PROMPT_INJECTION_PATTERNS
]

# ── Validation ─────────────────────────────────────────────

MAX_QUERY_LENGTH = 2000  # Reduced from 5000 — legitimate RAG queries rarely exceed 500 chars


def _normalize_input(text: str) -> str:
    """Normalize text for security analysis: strip zero-width chars, NFKC normalize."""
    text = _ZERO_WIDTH_RE.sub('', text)
    text = unicodedata.normalize('NFKC', text)
    return text


def validate_query_input(query: str, user_id: str = "anonymous") -> str:
    """Validate query input and detect prompt injection attacks.

    Applies: empty/length checks, Unicode normalization (NFKC),
    zero-width character stripping, regex-based injection pattern
    detection (English + Chinese), and delimiter injection detection.

    On detection, logs a structured security audit event.

    Args:
        query: Raw user query string
        user_id: Authenticated user ID or "anonymous"

    Returns:
        Cleaned query string

    Raises:
        HTTPException(400): Empty query, too long query, or detected injection
    """
    if not query or not query.strip():
        raise HTTPException(400, "查询内容不能为空")

    if len(query) > MAX_QUERY_LENGTH:
        raise HTTPException(400, "查询内容超过最大长度限制")

    # Step 1: Normalize to defeat homoglyph/bypass attacks
    normalized = _normalize_input(query)

    # Step 2: Check against injection patterns (on normalized text)
    for i, pattern in enumerate(PROMPT_INJECTION_REGEX):
        if pattern.search(normalized):
            # Build structured security audit event
            query_hash = hashlib.sha256(query.encode("utf-8", errors="replace")).hexdigest()
            preview = normalized[:200]

            _security_logger.warning(
                "PROMPT_INJECTION_BLOCKED | pattern_idx=%d | query_hash=%s | "
                "preview=%s | user=%s",
                i, query_hash, preview, user_id,
                extra={
                    "security_event": "prompt_injection_blocked",
                    "pattern_index": i,
                    "query_hash": query_hash,
                    "query_preview": preview,
                    "query_length": len(query),
                    "user_id": user_id,
                },
            )
            raise HTTPException(400, "请求包含不安全内容")

    # Step 3: Check for delimiter injection
    _INTERNAL_DELIMITERS = [
        "## 问题", "## 检索内容", "## 用户问题",
        "## 对话历史", "## 系统提示", "## System",
        "Thought:", "Action:", "Action Input:", "Observation:",
        "最终回答:", "思考步骤",
    ]
    for delimiter in _INTERNAL_DELIMITERS:
        if delimiter in normalized:
            _security_logger.warning(
                "PROMPT_INJECTION_BLOCKED | reason=delimiter_injection | "
                "delimiter=%s | user=%s",
                delimiter, user_id,
            )
            raise HTTPException(400, "请求包含不安全内容")

    return query.strip()


# ── Log Redaction Filter ───────────────────────────────────

class SensitiveLogFilter(logging.Filter):
    """自动脱敏日志中的敏感字段"""
    _patterns = [
        (_re_valid.compile(r'(api[_-]?key[=:"\s]*)([a-zA-Z0-9_\-]{8,})', _re_valid.IGNORECASE),
         r'\1***REDACTED***'),
        (_re_valid.compile(r'(password[=:"\s]*)([^,&\s"]+)', _re_valid.IGNORECASE),
         r'\1***REDACTED***'),
        (_re_valid.compile(r'(token[=:"\s]*)([a-zA-Z0-9_\-\.]{20,})', _re_valid.IGNORECASE),
         r'\1***REDACTED***'),
        (_re_valid.compile(r'(Bearer\s+)([a-zA-Z0-9_\-\.]{20,})'),
         r'\1***REDACTED***'),
        (_re_valid.compile(r'([a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,})'),
         r'***EMAIL***'),
    ]

    def filter(self, record):
        if hasattr(record, 'msg') and isinstance(record.msg, str):
            for pattern, replacement in self._patterns:
                record.msg = pattern.sub(replacement, record.msg)
        if record.args:
            if isinstance(record.args, dict):
                record.args = {
                    k: self._redact(v) if isinstance(v, str) else v
                    for k, v in record.args.items()
                }
            elif isinstance(record.args, (list, tuple)):
                record.args = tuple(
                    self._redact(a) if isinstance(a, str) else a
                    for a in record.args
                )
        return True

    def _redact(self, s: str) -> str:
        for pattern, replacement in self._patterns:
            s = pattern.sub(replacement, s)
        return s


def apply_sensitive_log_filter():
    """Apply SensitiveLogFilter to all handlers on relevant loggers."""
    for logger_name in ("rag_server", "lightrag"):
        for h in logging.getLogger(logger_name).handlers:
            h.addFilter(SensitiveLogFilter())
    for h in logging.getLogger().handlers:
        h.addFilter(SensitiveLogFilter())


__all__ = [
    "PROMPT_INJECTION_PATTERNS",
    "PROMPT_INJECTION_REGEX",
    "validate_query_input",
    "MAX_QUERY_LENGTH",
    "SensitiveLogFilter",
    "apply_sensitive_log_filter",
]
