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

import asyncio
import os
import re as _re
import logging
from pathlib import Path
from raganything.services.runtime_settings import bootstrap_runtime_settings

from dotenv import load_dotenv
load_dotenv(dotenv_path=".env", override=False)

bootstrap_runtime_settings()

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
    _reprocess_multimodal_for_kb,
    _build_citation_block,
    _get_kb_doc_list,
    infer_entity_type,
    _compute_file_hash,
    _is_file_being_processed,
    _register_processing_file,
    _ensure_queue_draining,
    cleanup_kb_resources,
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
    load_persisted_monitor_events,
    get_monitor_events,
    add_event,
)

# ── State Service (canonical source) ───────────────────────
from raganything.services.state_service import (  # noqa: F401 — re-export
    processing_tasks,
    query_history,
    QUERY_HISTORY_FILE,
    load_query_history,
    save_query_history,
    record_query,
    get_query_history,
    cleanup_completed_tasks,
    update_task_progress,
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
    STRATEGY_META as CHUNKING_STRATEGY_META,
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


# ── Per-KB Processing Queue ──────────────────────────────

# Each KB gets its own FIFO queue of pending file-processing tasks.
# Tasks are (task_id, file_path, filename, kb_name, strategy, user_id) tuples.
_kb_queues: dict = {}          # kb_name → asyncio.Queue
_kb_draining: dict = {}        # kb_name → bool (drain coroutine is active)

# Max concurrent processing tasks per KB (from config / env).
# Default 1 — safe for single LightRAG storage backend.
from raganything.config import RAGAnythingConfig
_MAX_CONCURRENT_FILES: int = int(
    os.getenv("MAX_CONCURRENT_FILES",
              str(getattr(RAGAnythingConfig, "max_concurrent_files", 1)))
)

# ── Server Logger ──────────────────────────────────────────

server_logger = logging.getLogger("rag_server")


# ── Image Path Validation ──────────────────────────────────

def _validate_image_paths(paths: list[str]) -> list[str]:
    """Filter out image paths that don't exist on disk.

    Extracted paths from chunk content may reference files that have been
    deleted or moved since document processing.  This validator ensures
    the frontend only receives paths it can actually load.
    """
    if not paths:
        return []
    valid: list[str] = []
    for p in paths:
        if p and Path(p).exists():
            valid.append(p)
    return valid


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


# ── Graph-based Image Discovery ─────────────────────────────


def _build_backfill_context(scored_texts: list, max_chars: int = 4800) -> tuple:
    """Build backfill context from bigram-matched chunks.

    Args:
        scored_texts: list of (chunk_id, content, score, doc_name) tuples
        max_chars: max total characters for backfill text

    Returns:
        (backfill_text, num_chunks_used, total_chars_used)
    """
    if not scored_texts:
        return "", 0, 0

    # Deduplicate by chunk_id, keep highest score
    best_by_id: dict = {}
    for chunk_id, content, score, doc_name in scored_texts:
        if chunk_id not in best_by_id or score > best_by_id[chunk_id][1]:
            best_by_id[chunk_id] = (f"{doc_name or '未知文档'}\t{content}", score)

    # Sort by score descending
    sorted_entries = sorted(best_by_id.items(), key=lambda x: -x[1][1])

    formatted: list = []
    total_chars = 0
    chunk_count = 0

    for chunk_id, (full_text, score) in sorted_entries:
        doc_name, content = full_text.split("\t", 1) if "\t" in full_text else ("未知文档", full_text)
        chunk_count += 1
        source_label = f"{doc_name} (回填片段{chunk_count})"
        block = f"[来源 {source_label}]\n{content}"
        if total_chars + len(block) > max_chars and formatted:
            break
        formatted.append(block)
        total_chars += len(block)
        if total_chars >= max_chars:
            break

    return "\n\n".join(formatted), chunk_count, total_chars


async def _discover_images_via_graph(instance, query: str, kb_name: str,
                                      ctx: str = ""):
    """Discover related images via entity graph traversal (mode-agnostic).

    Uses the knowledge graph's ``belongs_to`` edges to find image entities
    connected to query-matched text entities.  Runs only when
    ``extract_image_paths(ctx)`` returned nothing — a semantic fallback
    between the direct extraction and the bigram scan.

    Args:
        instance: RAGAnything instance with ``hybrid_search_engine``.
        query: User query text.
        kb_name: Knowledge base name (for logging context).
        ctx: Current retrieval context (for dedup).

    Returns:
        (image_paths: list[str], backfill_text: str)
    """
    hybrid_engine = getattr(instance, "hybrid_search_engine", None)
    if hybrid_engine is None:
        return [], ""

    graph_retriever = getattr(hybrid_engine, "graph_retriever", None)
    if graph_retriever is None:
        return [], ""

    try:
        # Step 1: Entity matching + neighbor traversal (with timeout + retry)
        max_attempts = 3  # 1 initial + 2 retries
        matched = []
        results = []
        for attempt in range(max_attempts):
            try:
                result = await asyncio.wait_for(
                    graph_retriever.search_with_paths(query, top_k=30),
                    timeout=8.0,
                )
                matched = result.get("matched_entities", [])
                results = result.get("results", [])
                if matched:
                    break  # entities found, proceed
                if attempt < max_attempts - 1:
                    await asyncio.sleep(1.0)
            except asyncio.TimeoutError:
                if attempt < max_attempts - 1:
                    lightrag_logger.debug(
                        "[IMG-GRAPH] KB=%s attempt %d/%d: search_with_paths timed out, retrying...",
                        kb_name, attempt + 1, max_attempts,
                    )
                    await asyncio.sleep(1.0)
                else:
                    raise  # last attempt timed out → handled by outer except

        if not matched:
            lightrag_logger.info(
                "[IMG-GRAPH] KB=%s 图谱未匹配到实体 (重试 %d 次后仍为空)，回退到 bigram 兜底",
                kb_name, max_attempts,
            )
            return [], ""

        # Step 2: Identify image-type entities from matched set
        image_entity_names = {
            e["name"]
            for e in matched
            if e.get("type") == "image"
        }

        # Step 3: Collect chunks whose traversal paths touch an image entity
        # Path format: {"entity": entity_name, "relation": rel, "depth": hop}
        image_chunks: dict = {}  # chunk_id → {chunk, entity_name}
        for item in results:
            paths = item.get("paths", [])
            for path in paths:
                entity_name = path["entity"]
                is_image = (
                    entity_name in image_entity_names
                    or " (image)" in entity_name
                )
                if is_image:
                    chunk = item["chunk"]
                    cid = chunk.chunk_id
                    if cid not in image_chunks:
                        image_chunks[cid] = {
                            "chunk": chunk,
                            "entity_name": entity_name,
                        }
                    break  # one image association is enough per chunk

        if not image_chunks:
            return [], ""

        # Step 4: Extract image paths & build backfill text (dedup)
        image_paths: list = []
        backfill_parts: list = []
        seen_paths: set = set()
        existing_ids: set = set()

        # Track chunks whose content (first 80 chars) already appears in ctx
        for cid, info in image_chunks.items():
            content = info["chunk"].content
            if content[:80] in ctx:
                existing_ids.add(cid)

        for cid, info in image_chunks.items():
            chunk = info["chunk"]
            content = chunk.content

            # Extract image paths
            for p in extract_image_paths(content):
                if p not in seen_paths:
                    seen_paths.add(p)
                    image_paths.append(p)

            # Build backfill (skip chunks already in ctx)
            if cid not in existing_ids and content:
                doc_name = (
                    getattr(chunk, "document_name", "")
                    or getattr(chunk, "file_path", "")
                    or "未知文档"
                )
                backfill_parts.append(
                    f"[来源 {doc_name}（图谱关联）]\n{content[:1500]}"
                )

        backfill_text = (
            "\n\n".join(backfill_parts[:5]) if backfill_parts else ""
        )

        # Validate paths exist on disk before returning
        image_paths = _validate_image_paths(image_paths)

        if image_paths:
            lightrag_logger.info(
                "[IMG-GRAPH] KB=%s 图谱发现 %d 张图片 (匹配实体 %d 个)",
                kb_name, len(image_paths), len(matched),
            )

        return image_paths[:5], backfill_text

    except asyncio.TimeoutError:
        lightrag_logger.warning(
            "[IMG-GRAPH] KB=%s 图谱图片发现超时 (8s)", kb_name
        )
        return [], ""
    except Exception as exc:
        lightrag_logger.warning(
            "[IMG-GRAPH] KB=%s 图谱图片发现失败: %s", kb_name, exc
        )
        return [], ""


async def _bigram_image_scan(kb_dir_path, query: str, ctx: str = "", instance=None):
    """Full-scan fallback for image discovery.

    Two-path strategy:
    1. **BM25 path** (primary): Uses the existing BM25 index (jieba + Okapi IDF)
       for proper Chinese text relevance scoring. Zero API cost, zero extra latency.
    2. **Improved bigram path** (fallback): Jaccard-normalized character bigram
       scoring with chunk-level diversity, for when BM25 index isn't ready.

    Args:
        kb_dir_path: Path to the knowledge base directory.
        query: User query text.
        ctx: Current retrieval context (for dedup).
        instance: Optional RAGAnything instance (enables BM25 path).

    Returns:
        (image_paths: list[str], backfill_text: str)
    """
    import json as _json
    import math
    import hashlib
    import random as _random

    q = query.lower().strip()

    # Early exit: queries too short for meaningful matching
    if len(q) < 2:
        return [], ""

    # ── Path 1: BM25 scoring (when available) ────────────────
    if instance is not None:
        hybrid_engine = getattr(instance, "hybrid_search_engine", None)
        bm25_mgr = getattr(hybrid_engine, "_bm25", None) if hybrid_engine else None
        if bm25_mgr is not None and bm25_mgr.is_ready:
            try:
                return await _bm25_image_scan(
                    bm25_mgr, query, ctx
                )
            except Exception:
                pass  # BM25 failed → fall through to bigram path

    # ── Path 2: PG-based bigram scan (last resort) ───────────
    # Query PG for all text chunks in this KB workspace
    _all = None
    try:
        from raganything.services.pg_state_repo import get_pg_pool
        workspace = str(kb_dir_path)
        pool = get_pg_pool()
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT chunks_list FROM LIGHTRAG_DOC_STATUS WHERE workspace=$1",
                workspace,
            )
        all_chunk_ids = []
        for row in rows:
            cl = row["chunks_list"]
            if isinstance(cl, str):
                try:
                    cl = _json.loads(cl)
                except Exception:
                    cl = []
            if cl:
                all_chunk_ids.extend(cl)

        if all_chunk_ids and instance is not None and instance.lightrag:
            raw_chunks = await instance.lightrag.text_chunks.get_by_ids(all_chunk_ids)
            _all = {}
            for c in raw_chunks:
                if c:
                    cid = c.get("id") or c.get("__id__")
                    if cid:
                        _all[cid] = {"content": c.get("content", ""), "file_path": c.get("file_path", "")}
    except Exception as exc:
        lightrag_logger.warning("[IMG-FALLBACK] PG chunk load failed: %s", exc)

    if _all is None or not _all:
        return [], ""

    # Build query bigram set
    query_grams = set()
    for i in range(len(q) - 1):
        query_grams.add(q[i:i+2])

    # Score chunks with Jaccard-like normalization to eliminate length bias.
    # score = |query_grams ∩ chunk_grams| / sqrt(|chunk|)
    # The sqrt normalization penalizes long chunks without over-penalizing
    # moderately long ones.  Pure Jaccard (division by union) over-penalizes
    # long chunks; raw count favours them.  sqrt is a pragmatic middle ground.
    # Per-chunk data: (chunk_id, score, paths, doc_name)
    _existing_content_ids = set()
    _chunk_results = []  # (cid, norm_score, paths, doc_name)

    for _cid, _chunk in _all.items():
        content = _chunk.get('content', '')
        if not content:
            continue
        paths = extract_image_paths(content)
        if not paths:
            continue
        content_lower = content.lower()
        raw = sum(1 for bg in query_grams if bg in content_lower)
        if raw == 0:
            continue
        norm_score = raw / math.sqrt(max(len(content_lower), 1))
        _content_key = content[:80]
        if _content_key in ctx:
            _existing_content_ids.add(_cid)
        doc_name = _chunk.get('document_name', '') or _chunk.get('source', '')
        _chunk_results.append((_cid, norm_score, paths, doc_name))

    if not _chunk_results:
        # All scores are zero — hash-based pseudo-random (deterministic per
        # query, varied across queries).  Gives different queries different
        # images instead of always returning the same first-two-in-file.
        _all_paths = []
        for _cid, _chunk in _all.items():
            _all_paths.extend(extract_image_paths(_chunk.get('content', '')))
        _all_paths = list(dict.fromkeys(_all_paths))  # dedup, preserve order
        if not _all_paths:
            return [], ""
        seed = int(hashlib.md5(query.encode()).hexdigest()[:8], 16)
        rng = _random.Random(seed)
        rng.shuffle(_all_paths)
        # Validate before returning — stop at first 2 that exist
        image_paths = []
        for _p in _all_paths:
            if Path(_p).exists():
                image_paths.append(_p)
                if len(image_paths) >= 2:
                    break
        if image_paths:
            lightrag_logger.info(
                "[IMG-FALLBACK] bigram得分全零，降级为hash-random选择 query_hash=%s candidates=%d",
                hashlib.md5(query.encode()).hexdigest()[:8], len(image_paths),
            )
        else:
            lightrag_logger.info(
                "[IMG-FALLBACK] bigram得分全零，%d候选路径无一存在",
                len(_all_paths),
            )
        return image_paths, ""

    # ── Diversity: one image per chunk ──
    # Within a chunk, pick the FIRST image (position bias: images that appear
    # earlier in the text are more likely to be topically relevant).  Across
    # chunks, rank by normalized score.  Skip paths that don't exist on disk.
    _chunk_results.sort(key=lambda x: -x[1])
    image_paths = []
    seen_chunks = set()
    for _cid, _score, _paths, _dname in _chunk_results:
        if _cid in seen_chunks:
            continue
        seen_chunks.add(_cid)
        for _p in _paths:
            if Path(_p).exists():
                image_paths.append(_p)
                break  # first existing image in chunk
        if len(image_paths) >= 3:
            break

    # ── Build backfill ──
    scored_texts = [
        (cid, _all[cid].get('content', ''), score, dname)
        for cid, score, _, dname in _chunk_results
    ]
    _fresh_texts = [(cid, c, s, dn) for cid, c, s, dn in scored_texts
                    if cid not in _existing_content_ids]
    backfill_text, _bf_count, _bf_chars = _build_backfill_context(_fresh_texts)

    if image_paths:
        lightrag_logger.info(
            "[IMG-FALLBACK] bigram(标准化)匹配到 %d 张图片 (来自 %d 个不同chunk), +回填 %d 文本片段 (%d 字符)",
            len(image_paths), len(seen_chunks), _bf_count, _bf_chars,
        )

    return image_paths, backfill_text


async def _bm25_image_scan(bm25_mgr, query: str, ctx: str = "") -> tuple:
    """BM25-based image scan — primary path inside _bigram_image_scan.

    Uses the existing BM25 index (jieba tokenization + Okapi IDF weighting)
    for proper Chinese keyword relevance.  Zero API cost, O(1) index lookup
    vs O(N) full-scan for the bigram fallback.

    Args:
        bm25_mgr: BM25IndexManager instance with ready index.
        query: User query text.
        ctx: Current retrieval context (for dedup).

    Returns:
        (image_paths: list[str], backfill_text: str)
    """
    bm25_results = bm25_mgr.search(query, top_k=100)

    # Score images by their chunk's BM25 score, one image per chunk
    _chunk_results = []  # (chunk_id, score, first_image_path, doc_name)
    _existing_content_ids = set()

    for result in bm25_results:
        content = result.content
        if not content:
            continue
        paths = extract_image_paths(content)
        if not paths:
            continue
        _content_key = content[:80]
        if _content_key in ctx:
            _existing_content_ids.add(result.chunk_id)
        doc_name = result.document_name or getattr(result, 'file_path', '') or ''
        _chunk_results.append((result.chunk_id, result.score, paths[0], doc_name))

    # Dedup by chunk, keep highest BM25 score
    best_per_chunk = {}
    for cid, score, path, dname in _chunk_results:
        if cid not in best_per_chunk or score > best_per_chunk[cid][0]:
            best_per_chunk[cid] = (score, path, dname)

    # Top-3 images from different chunks (validate existence)
    ranked = sorted(best_per_chunk.items(), key=lambda x: -x[1][0])
    image_paths = []
    for _, (_, path, _) in ranked:
        if Path(path).exists():
            image_paths.append(path)
            if len(image_paths) >= 3:
                break

    # Build backfill from top-scoring chunks
    scored_texts = []
    for cid, (score, path, dname) in ranked[:10]:
        # Content is in the BM25 result — find it
        for r in bm25_results:
            if r.chunk_id == cid and r.content:
                scored_texts.append((cid, r.content, score, dname))
                break

    _fresh_texts = [(cid, c, s, dn) for cid, c, s, dn in scored_texts
                    if cid not in _existing_content_ids]
    backfill_text, _bf_count, _bf_chars = _build_backfill_context(_fresh_texts)

    if image_paths:
        lightrag_logger.info(
            "[IMG-FALLBACK] BM25匹配到 %d 张图片 (来自 %d 个不同chunk), +回填 %d 文本片段 (%d 字符)",
            len(image_paths), len(ranked[:3]), _bf_count, _bf_chars,
        )

    return image_paths, backfill_text


# ── Image Relevance Filter ──────────────────────────────────

def _filter_images_by_relevance(
    image_paths: list[str],
    query: str,
    ctx: str = "",
    min_overlap: int = 2,
) -> list[str]:
    """Filter images by keyword overlap between query and image context.

    Extracts text surrounding each image path in *ctx* (captions, VLM
    descriptions, entity names) and computes overlap with *query* keywords.
    Images with fewer than *min_overlap* matching keywords are dropped.

    This is a lightweight post-filter — it trades recall for precision.
    False positives (irrelevant images in retrieval context) are the
    dominant failure mode for text queries, and this eliminates the most
    obvious ones without requiring an extra API call.

    Args:
        image_paths: Candidate image paths from any discovery tier.
        query: Original user query.
        ctx: Retrieval context (contains image descriptions).
        min_overlap: Minimum number of query keywords that must appear in
            the image's surrounding text. Default 2.

    Returns:
        Filtered list of image paths (may be empty).
    """
    if not image_paths or not query or not ctx:
        return image_paths

    # Tokenize query into keywords (jieba for Chinese, split for ASCII)
    try:
        import jieba as _jieba
        _q_kw = set(
            w.strip().lower()
            for w in _jieba.cut(query)
            if len(w.strip()) >= 2
        )
    except Exception:
        _q_kw = set(query.lower().split())

    if len(_q_kw) < 2:
        return image_paths  # query too short to filter meaningfully

    # For each image, extract a text window from ctx around the image path
    _ctx_lower = ctx.lower()
    _scored: list[tuple[str, int]] = []

    for _img in image_paths:
        _img_lower = _img.lower()
        _img_name = _img_lower.replace("\\", "/").split("/")[-1]

        # Find the image in context and extract surrounding text window.
        # Use a tight window (500 chars each side) to avoid cross-chunk
        # contamination when multiple images appear in the same context.
        _window = ""
        _idx = _ctx_lower.find(_img_name)
        if _idx == -1:
            _idx = _ctx_lower.find(_img_lower.split("/")[-1])

        if _idx >= 0:
            _start = max(0, _idx - 500)
            _end = min(len(ctx), _idx + 500)
            _window = ctx[_start:_end].lower()
            # Tighten further: trim to nearest double-newline (chunk boundary)
            # so we don't bleed into adjacent chunks' descriptions
            if "\n\n" in _window:
                # Find the chunk that actually contains the image path
                _parts = _window.split("\n\n")
                for _part in _parts:
                    if _img_name in _part:
                        _window = _part
                        break
        else:
            # Image not found in ctx — keep it (no evidence to filter)
            _scored.append((_img, min_overlap))
            continue

        # Count keyword overlaps
        _overlap = sum(1 for kw in _q_kw if kw in _window)
        _scored.append((_img, _overlap))

    # Filter
    _filtered = [img for img, score in _scored if score >= min_overlap]
    _dropped = len(image_paths) - len(_filtered)

    if _dropped > 0:
        lightrag_logger.info(
            "[IMG-FILTER] %d/%d images dropped (below overlap threshold %d). "
            "Query keywords: %s",
            _dropped, len(image_paths), min_overlap,
            ", ".join(sorted(_q_kw)[:10]),
        )

    return _filtered


async def recall_query_images(
    instance,
    query: str,
    kb_name: str,
    ctx: str = "",
) -> tuple[list[str], str, str]:
    """Recall query-related images with a unified multi-stage strategy."""
    source = "none"
    backfill_text = ""
    raw_paths = extract_image_paths(ctx)

    if raw_paths:
        source = "direct"
    else:
        raw_paths, backfill_text = await _discover_images_via_graph(
            instance, query, kb_name, ctx
        )
        if raw_paths:
            source = "graph"
        else:
            raw_paths, backfill_text = await _bigram_image_scan(
                kb_dir(kb_name), query, ctx, instance
            )
            if raw_paths:
                source = "bigram"

    raw_count = len(raw_paths)
    valid_paths = _validate_image_paths(raw_paths)
    filtered_paths = list(valid_paths)

    if source in ("graph", "bigram") and valid_paths:
        relevance_ctx = ctx or ""
        if backfill_text:
            relevance_ctx = (
                f"{relevance_ctx}\n\n{backfill_text}"
                if relevance_ctx else backfill_text
            )
        filtered_paths = _filter_images_by_relevance(
            valid_paths,
            query,
            relevance_ctx,
            min_overlap=1,
        )
        if not filtered_paths and valid_paths:
            filtered_paths = valid_paths[:1]

    final_paths = filtered_paths[:3]
    lightrag_logger.info(
        "[IMG-RECALL] KB=%s source=%s raw=%d filtered=%d final=%d",
        kb_name,
        source,
        raw_count,
        len(filtered_paths),
        len(final_paths),
    )
    return final_paths, backfill_text, source


# ── Thinking/Progress Translation ──────────────────────────

THINKING_PATTERNS = [
    "executing", "query mode", "keywords", "query nodes", "local query",
    "query edges", "global query", "raw search", "after truncation",
    "entity-related chunks", "relations-related chunks", "merged chunks",
    "final context", "final chunks", "text query completed", "cache",
    "retrying request", "embedding",
]

QUERY_SYSTEM_PROMPT = "基于检索内容回答。对话历史可用作理解用户上下文和指代关系，但事实性回答必须引用检索内容中的具体信息。检索内容没有的信息不要编造。"


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
    "_reprocess_multimodal_for_kb",
    "_build_citation_block", "_get_kb_doc_list", "infer_entity_type",
    "API_KEY", "BASE_URL", "LLM_MODEL", "VISION_MODEL",
    "EMB_MODEL", "EMB_DIM", "WORKING_DIR", "CHUNKING_STRATEGY",
    "WORKFLOW_DIR",
    # WebSocket
    "ws_clients", "active_ws_connections", "processing_events",
    "ws_broadcast", "push_run_status", "emit_progress",
    "load_persisted_monitor_events", "get_monitor_events", "add_event",
    # State
    "processing_tasks", "query_history", "QUERY_HISTORY_FILE", "load_query_history", "save_query_history",
    "cleanup_completed_tasks",
    # Security
    "validate_query_input", "PROMPT_INJECTION_REGEX",
    # Local
    "MAX_UPLOAD_SIZE", "MAX_BODY_SIZE", "RequestSizeMiddleware",
    "server_logger", "extract_image_paths",
    "_discover_images_via_graph", "_build_backfill_context",
    "_bigram_image_scan",
    "recall_query_images",
    "THINKING_PATTERNS", "QUERY_SYSTEM_PROMPT",
    "_is_thinking_msg", "_translate_thinking_msg",
    # Re-exports from other modules
    "ANSWER_FORMAT_INSTRUCTION", "INLINE_QUOTE_INSTRUCTION",
    "recursive_chunking", "sentence_chunking", "structure_chunking",
    "make_semantic_chunking", "make_agentic_chunking",
]
