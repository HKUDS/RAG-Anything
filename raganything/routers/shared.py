# -*- coding: utf-8 -*-
"""
RAG-Anything Router Shared Module — Backward-Compatibility Facade.

Layer: Router
Primary Responsibility: Re-exports all shared state and helpers from the
    Service layer for backward compatibility. Router modules can import from
    here or directly from raganything.services.*.
Key Dependencies: raganything.services (kb_service, ws_service, state_service),
    raganything.dependencies (get_current_user, get_admin_user, limiter)

This module previously contained ~700 lines of inline definitions (KB management,
WebSocket, state, auth, utilities). Those have been extracted into:
    - raganything.services.kb_service    (KB lifecycle, RAGAnything factory)
    - raganything.services.ws_service    (WebSocket broadcast, progress, events)
    - raganything.services.state_service (query history, task status)
    - raganything.utils.security         (prompt injection detection)
"""

import os
import re as _re
import logging
from pathlib import Path

from dotenv import load_dotenv
load_dotenv(dotenv_path=".env", override=False)

from fastapi import WebSocket, Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

# ── Auth (canonical source: raganything.dependencies) ──────
from raganything.dependencies import (
    get_current_user,
    get_admin_user,
    get_optional_user,
    verify_kb_access,
    limiter,
    security,
    PaginationParams,
)

# ── KB Service (canonical source) ──────────────────────────
from raganything.services.kb_service import (  # noqa: F401 — re-export
    kb_instances,
    active_kb,
    KB_META_FILE,
    load_kb_meta,
    save_kb_meta,
    kb_dir,
    get_kb,
    create_rag,
    _fix_stuck_doc_status,
    _process_uploaded_file,
    _build_citation_block,
    _get_kb_doc_list,
    infer_entity_type,
    API_KEY,
    BASE_URL,
    LLM_MODEL,
    VISION_MODEL,
    EMB_MODEL,
    EMB_DIM,
    WORKING_DIR,
    CHUNKING_STRATEGY,
    WORKFLOW_DIR,
)

# ── WebSocket Service (canonical source) ───────────────────
from raganything.services.ws_service import (  # noqa: F401 — re-export
    ws_clients,
    active_ws_connections,
    processing_events,
    ws_broadcast,
    push_run_status,
    emit_progress,
    add_event,
)

# ── State Service (canonical source) ───────────────────────
from raganything.services.state_service import (  # noqa: F401 — re-export
    processing_tasks,
    query_history,
    conversation_manager,
    QUERY_HISTORY_FILE,
    load_query_history,
    save_query_history,
)

# ── Security Utilities (canonical source) ──────────────────
from raganything.utils.security import (  # noqa: F401 — re-export
    validate_query_input,
    PROMPT_INJECTION_REGEX,
)

# ── Prompt / Query Helpers (still local — no other home yet) ──
from lightrag.llm.openai import openai_complete_if_cache, openai_embed
from lightrag.utils import EmbeddingFunc, logger as lightrag_logger  # noqa: F401
from raganything import RAGAnything, RAGAnythingConfig
from raganything.query import ConversationManager

_DEGRADED_HINT = (
    "\n\n⚠️ 注意：本次检索未能获取到关联的文档文本内容，"
    "以下回答仅基于实体名称和关系路径，可能不够详细。"
    "如果信息不足，请如实说明。"
)
from raganything.prompt import ANSWER_FORMAT_INSTRUCTION, INLINE_QUOTE_INSTRUCTION  # noqa: F401
from raganything.chunking import (  # noqa: F401 — re-export
    recursive_chunking,
    sentence_chunking,
    structure_chunking,
    make_semantic_chunking,
    make_agentic_chunking,
)

# ── Request Size Middleware ─────────────────────────────────

MAX_UPLOAD_SIZE = int(os.getenv("MAX_UPLOAD_SIZE_MB", "500")) * 1024 * 1024
MAX_BODY_SIZE = int(os.getenv("MAX_BODY_SIZE_MB", "10")) * 1024 * 1024


class RequestSizeMiddleware(BaseHTTPMiddleware):
    """Request size limiting middleware."""

    async def dispatch(self, request: Request, call_next):
        content_length = request.headers.get("content-length")
        if content_length:
            cl = int(content_length)
            if request.url.path.startswith("/api/upload") and cl > MAX_UPLOAD_SIZE:
                return JSONResponse(
                    {"detail": f"文件超过最大限制 {os.getenv('MAX_UPLOAD_SIZE_MB', '500')}MB"},
                    status_code=413,
                )
            elif cl > MAX_BODY_SIZE:
                return JSONResponse(
                    {"detail": f"请求体超过最大限制 {os.getenv('MAX_BODY_SIZE_MB', '10')}MB"},
                    status_code=413,
                )
        return await call_next(request)


# ── Server Logger ──────────────────────────────────────────

server_logger = logging.getLogger("rag_server")


# ── Image Path Extraction ──────────────────────────────────

def extract_image_paths(text: str) -> list[str]:
    """Extract image paths from retrieval context text."""
    if not text:
        return []
    pattern = _re.compile(
        r"Image Path:\s*([^\r\n]*?\.(?:jpg|jpeg|png|gif|bmp|webp|tiff|tif))",
        _re.IGNORECASE,
    )
    seen = set()
    paths = []
    for m in pattern.finditer(text):
        p = m.group(1).strip()
        if p not in seen:
            seen.add(p)
            paths.append(p)
    return paths


# ── Thinking/Progress Translation ──────────────────────────

THINKING_PATTERNS = [
    "executing", "query mode", "keywords", "query nodes", "local query",
    "query edges", "global query", "raw search", "after truncation",
    "entity-related chunks", "relations-related chunks", "merged chunks",
    "final context", "final chunks", "text query completed", "cache",
    "retrying request", "embedding",
]

QUERY_SYSTEM_PROMPT = "基于检索内容回答。引用检索内容中的具体事实和数据。检索内容没有的信息不要编造。"


def _is_thinking_msg(msg: str) -> bool:
    """Check if a log message should be shown as thinking process."""
    msg_lower = msg.lower()
    return any(p in msg_lower for p in THINKING_PATTERNS)


def _translate_thinking_msg(msg: str) -> str:
    """Translate English log messages to Chinese thinking process display."""
    msg_lower = msg.lower()

    if "executing text query" in msg_lower:
        return "📝 正在解析查询意图..."
    if "query mode" in msg_lower:
        mode = msg.split(":")[-1].strip() if ":" in msg else ""
        mode_cn = {"hybrid": "混合检索", "local": "本地检索", "global": "全局检索",
                    "naive": "朴素检索", "mix": "混合模式"}
        return f"📋 查询策略: {mode_cn.get(mode, mode)}"
    if "keywords" in msg_lower and "cache" in msg_lower:
        return "🔑 提取关键词完成"
    if "keywords" in msg_lower:
        return "🔑 正在提取查询关键词..."
    if "query nodes" in msg_lower:
        return "🔗 检索知识图谱实体节点..."
    if "local query" in msg_lower:
        match = msg.split(":")[-1].strip() if ":" in msg else msg
        return f"📊 本地子图检索: {match}"
    if "query edges" in msg_lower:
        return "🔗 检索知识图谱关系边..."
    if "global query" in msg_lower:
        match = msg.split(":")[-1].strip() if ":" in msg else msg
        return f"🌐 全局社区检索: {match}"
    if "raw search results" in msg_lower:
        return f"📦 原始检索结果: {msg.split(':')[-1].strip() if ':' in msg else msg}"
    if "after truncation" in msg_lower:
        return f"✂️ 结果优化截断: {msg.split(':')[-1].strip() if ':' in msg else msg}"
    if "entity-related chunks" in msg_lower:
        return "📄 选取相关文本块..."
    if "relations-related chunks" in msg_lower:
        return "📄 选取关系文本块..."
    if "merged chunks" in msg_lower:
        return f"🔄 合并排序文本块: {msg.split(':')[-1].strip() if ':' in msg else msg}"
    if "final context" in msg_lower:
        return f"📋 构建最终上下文: {msg.split(':')[-1].strip() if ':' in msg else msg}"
    if "final chunks" in msg_lower:
        return "✅ 上下文整理完成"
    if "retrying request" in msg_lower:
        return "⏳ API 请求重试中..."
    if "cache" in msg_lower and "saving" in msg_lower:
        return ""
    if "text query completed" in msg_lower:
        return ""

    if len(msg) > 120:
        msg = msg[:120] + "..."
    return f"ℹ️ {msg}"


__all__ = [
    # Auth (from dependencies)
    "get_current_user", "get_admin_user", "get_optional_user",
    "verify_kb_access", "limiter", "security", "PaginationParams",
    # KB Service
    "kb_instances", "active_kb", "KB_META_FILE", "load_kb_meta",
    "save_kb_meta", "kb_dir", "get_kb", "create_rag",
    "_fix_stuck_doc_status", "_process_uploaded_file",
    "_build_citation_block", "_get_kb_doc_list", "infer_entity_type",
    "API_KEY", "BASE_URL", "LLM_MODEL", "VISION_MODEL",
    "EMB_MODEL", "EMB_DIM", "WORKING_DIR", "CHUNKING_STRATEGY",
    "WORKFLOW_DIR",
    # WebSocket
    "ws_clients", "active_ws_connections", "processing_events",
    "ws_broadcast", "push_run_status", "emit_progress", "add_event",
    # State
    "processing_tasks", "query_history", "conversation_manager",
    "QUERY_HISTORY_FILE", "load_query_history", "save_query_history",
    # Security
    "validate_query_input", "PROMPT_INJECTION_REGEX",
    # Local
    "MAX_UPLOAD_SIZE", "MAX_BODY_SIZE", "RequestSizeMiddleware",
    "server_logger", "extract_image_paths",
    "THINKING_PATTERNS", "QUERY_SYSTEM_PROMPT",
    "_is_thinking_msg", "_translate_thinking_msg",
    # Re-exports from other modules
    "ANSWER_FORMAT_INSTRUCTION", "INLINE_QUOTE_INSTRUCTION",
    "recursive_chunking", "sentence_chunking", "structure_chunking",
    "make_semantic_chunking", "make_agentic_chunking",
]
