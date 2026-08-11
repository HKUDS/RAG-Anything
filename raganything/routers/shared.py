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

# Runtime settings must be bootstrapped before importing the service modules
# re-exported by this compatibility hub.
# ruff: noqa: E402

import asyncio
import dataclasses
import os
import re as _re
import logging
import time
from pathlib import Path
from raganything.services.runtime_settings import bootstrap_runtime_settings
from raganything.services.odl_media_delivery import validate_legacy_media_path
from raganything.utils import display_document_name

from dotenv import load_dotenv
load_dotenv(dotenv_path=".env", override=False)

bootstrap_runtime_settings()

from fastapi import Request
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
    _enqueue_upload_task,
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
    register_general_ws,
    unregister_general_ws,
    register_ws,
    unregister_ws,
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
from lightrag.utils import EmbeddingFunc, logger as lightrag_logger  # noqa: F401


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


# ── Controlled Image Path Extraction and Validation ────────

_IMAGE_SUFFIXES = frozenset({
    ".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp", ".tiff", ".tif",
})
_IMAGE_PATH_PROTOCOLS = (
    ("english", _re.compile(
        r"Image\s+Path\s*[:：]\s*(?P<path>[^\r\n]*)$",
        _re.IGNORECASE | _re.MULTILINE,
    )),
    ("chinese", _re.compile(
        r"\[\s*图片路径\s*[:：]\s*(?P<path>[^\r\n\]]*)\s*\]",
        _re.IGNORECASE,
    )),
)


@dataclasses.dataclass(frozen=True)
class ImagePathExtraction:
    """Bounded, path-free accounting for a retrieval image-path scan."""

    paths: list[str]
    candidate_count: int
    protocol_counts: dict[str, int]
    rejection_counts: dict[str, int]


def _registered_odl_media_roots() -> tuple[Path, ...]:
    """Return explicitly controlled roots accepted for legacy ODL media.

    Legacy chunks have no per-image manifest.  They are intentionally accepted
    only below the dedicated artifact root or roots explicitly provisioned by
    the operator; a marker can never widen this allow-list.
    """
    configured: list[str] = []
    primary = os.getenv("ODL_ARTIFACT_ROOT", "").strip()
    if primary:
        configured.append(primary)
    legacy = os.getenv("ODL_LEGACY_MEDIA_ROOTS", "").strip()
    if legacy:
        configured.extend(part.strip() for part in legacy.split(os.pathsep))

    # The project-owned dedicated root is a stable compatibility root for
    # previously parsed local ODL documents.  Do not derive a root from a KB,
    # document marker, or the process current directory.
    project_root = Path(__file__).resolve().parents[2]
    project_artifacts = project_root / "odl-artifacts"
    if project_artifacts.is_dir():
        configured.append(str(project_artifacts))

    roots: list[Path] = []
    for raw in configured:
        try:
            root = Path(raw)
            if not root.is_absolute() or not root.is_dir() or root.is_symlink():
                continue
            resolved = root.resolve(strict=True)
        except (OSError, RuntimeError, ValueError):
            continue
        if resolved not in roots:
            roots.append(resolved)
    return tuple(roots)


def _contains_symlink(path: Path, root: Path) -> bool:
    """Reject every symlinked child even when it resolves back into *root*."""
    try:
        relative = path.relative_to(root)
    except ValueError:
        return True
    current = root
    for component in relative.parts:
        current /= component
        if current.is_symlink():
            return True
    return False


def _validate_single_image_path(candidate: str) -> tuple[str | None, str | None]:
    """Fail closed for a marker path and return only an approved local path."""
    if not isinstance(candidate, str) or not candidate.strip():
        return None, "empty"
    raw_path = candidate.strip().strip("\"'")
    resolved, reason = validate_legacy_media_path(raw_path)
    return (str(resolved), None) if resolved is not None else (None, reason)


def _resolve_image_path_candidates(
    candidates: list[tuple[str, str]],
) -> ImagePathExtraction:
    protocols: dict[str, int] = {}
    rejected: dict[str, int] = {}
    paths: list[str] = []
    seen: set[str] = set()
    for protocol, candidate in candidates:
        protocols[protocol] = protocols.get(protocol, 0) + 1
        valid, reason = _validate_single_image_path(candidate)
        if valid is None:
            rejected[reason or "invalid"] = rejected.get(reason or "invalid", 0) + 1
            continue
        if valid not in seen:
            seen.add(valid)
            paths.append(valid)
    return ImagePathExtraction(
        paths=paths,
        candidate_count=len(candidates),
        protocol_counts=protocols,
        rejection_counts=rejected,
    )


def extract_image_paths_with_stats(text: str) -> ImagePathExtraction:
    """Parse both retrieval protocols and resolve candidates through one gate."""
    if not text:
        return ImagePathExtraction([], 0, {}, {})
    candidates: list[tuple[str, str]] = []
    for protocol, pattern in _IMAGE_PATH_PROTOCOLS:
        for match in pattern.finditer(text):
            candidates.append((protocol, match.group("path")))
    return _resolve_image_path_candidates(candidates)


def _validate_image_paths(paths: list[str]) -> list[str]:
    """Validate already-extracted paths through the same controlled-media gate."""
    return _resolve_image_path_candidates([("unknown", path) for path in paths]).paths


def extract_image_paths(text: str) -> list[str]:
    """Return only controlled image paths found in retrieval context text."""
    return extract_image_paths_with_stats(text).paths


async def resolve_controlled_media_payload(
    *, kb_name: str, image_path: str, text_chunk_reader=None
) -> dict | None:
    """Resolve one backend-only path through the KB's persisted media catalog.

    Callers must pass the already-authorised KB name. Legacy controlled-root
    validation is intentionally insufficient for delivery ownership.
    """
    from raganything.services.kb_service import _load_doc_status_json
    from raganything.services.odl_media_delivery import (
        catalog_media_payload,
        issue_owned_legacy_media_grant,
        validate_legacy_media_path,
    )

    try:
        statuses = await _load_doc_status_json(kb_name)
    except Exception as exc:
        lightrag_logger.warning(
            "[IMG-MEDIA] KB=%s outcome=status_unavailable error_type=%s",
            kb_name,
            type(exc).__name__,
        )
        return None
    catalog: list[dict] = []
    for status in statuses.values():
        metadata = status.get("metadata") if isinstance(status, dict) else None
        entries = metadata.get("odl_media_catalog") if isinstance(metadata, dict) else None
        if isinstance(entries, list):
            catalog.extend(entry for entry in entries if isinstance(entry, dict))
    payload = catalog_media_payload(catalog, kb_name=kb_name, path=image_path)
    if payload is not None:
        return payload

    # Old ODL chunks have no catalog. A controlled root alone is not enough:
    # prove that this exact canonical image path was persisted in this KB's
    # chunk content before issuing a short-lived, ownership-bound grant.
    validated, _reason = validate_legacy_media_path(image_path)
    if validated is None:
        return None
    try:
        storage = text_chunk_reader
        if storage is None:
            instance = await get_kb(kb_name)
            storage = getattr(getattr(instance, "lightrag", None), "text_chunks", None)
        if storage is None:
            return None
        for document_id, status in statuses.items():
            if not isinstance(status, dict):
                continue
            chunk_ids = [str(value) for value in status.get("chunks_list", []) if value]
            for start in range(0, len(chunk_ids), 200):
                records = await storage.get_by_ids(chunk_ids[start:start + 200])
                for record in records or []:
                    if not isinstance(record, dict):
                        continue
                    for candidate in extract_image_paths(str(record.get("content") or "")):
                        if candidate != str(validated):
                            continue
                        chunk_id = str(record.get("chunk_id") or record.get("id") or "")
                        grant = issue_owned_legacy_media_grant(
                            kb_name=kb_name,
                            path=validated,
                            document_id=str(document_id),
                            chunk_id=chunk_id,
                        )
                        if not grant:
                            return None
                        from urllib.parse import quote, urlencode

                        lightrag_logger.info(
                            "[IMG-MEDIA] KB=%s source=legacy_owned_chunk outcome=granted",
                            kb_name,
                        )
                        return {
                            "media_id": f"legacy:{grant.split('.', 1)[0]}",
                            "legacy_grant": grant,
                            "kb": kb_name,
                            "url": (
                                f"/api/knowledge/media/legacy/{quote(grant, safe='')}?"
                                f"{urlencode({'kb': kb_name})}"
                            ),
                            "caption": "",
                            "page": None,
                        }
    except Exception as exc:
        lightrag_logger.warning(
            "[IMG-MEDIA] KB=%s source=legacy_owned_chunk outcome=error error_type=%s",
            kb_name,
            type(exc).__name__,
        )
    return None


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
        source_label = f"{display_document_name(doc_name)} (回填片段{chunk_count})"
        block = f"[来源 {source_label}]\n{content}"
        if total_chars + len(block) > max_chars and formatted:
            break
        formatted.append(block)
        total_chars += len(block)
        if total_chars >= max_chars:
            break

    return "\n\n".join(formatted), chunk_count, total_chars


async def _discover_images_via_graph(instance, query: str, kb_name: str,
                                      ctx: str = "", timeout_budget_seconds: float = 2.0):
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

    started = time.perf_counter()
    attempt_count = 0
    timeout_budget_seconds = max(0.05, min(float(timeout_budget_seconds), 2.0))
    try:
        # Graph is an optional extension.  A single deadline avoids turning
        # image recall into three serial eight-second waits.
        attempt_count = 1
        result = await asyncio.wait_for(
            graph_retriever.search_with_paths(query, top_k=30),
            timeout=timeout_budget_seconds,
        )
        matched = result.get("matched_entities", [])
        results = result.get("results", [])

        if not matched:
            lightrag_logger.info(
                "[IMG-GRAPH] KB=%s outcome=no_match elapsed_ms=%.1f attempt_count=%d timeout_budget_ms=%d",
                kb_name,
                (time.perf_counter() - started) * 1000,
                attempt_count,
                int(timeout_budget_seconds * 1000),
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

        # A second call is intentionally harmless: graph chunks are parsed by
        # the same resolver as direct/local recall, then de-duplicated here.
        image_paths = _validate_image_paths(image_paths)

        if image_paths:
            lightrag_logger.info(
                "[IMG-GRAPH] KB=%s 图谱发现 %d 张图片 (匹配实体 %d 个)",
                kb_name, len(image_paths), len(matched),
            )

        return image_paths[:5], backfill_text

    except asyncio.TimeoutError:
        lightrag_logger.warning(
            "[IMG-GRAPH] KB=%s outcome=timeout elapsed_ms=%.1f attempt_count=%d timeout_budget_ms=%d",
            kb_name,
            (time.perf_counter() - started) * 1000,
            attempt_count,
            int(timeout_budget_seconds * 1000),
        )
        return [], ""
    except Exception as exc:
        lightrag_logger.warning(
            "[IMG-GRAPH] KB=%s outcome=error error_type=%s elapsed_ms=%.1f attempt_count=%d timeout_budget_ms=%d",
            kb_name,
            type(exc).__name__,
            (time.perf_counter() - started) * 1000,
            attempt_count,
            int(timeout_budget_seconds * 1000),
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
        # Values were resolved through the shared controlled-media gate.
        image_paths = _validate_image_paths(_all_paths)[:2]
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
    # chunks, rank by normalized score.  Paths are already controlled.
    _chunk_results.sort(key=lambda x: -x[1])
    image_paths = []
    seen_chunks = set()
    for _cid, _score, _paths, _dname in _chunk_results:
        if _cid in seen_chunks:
            continue
        seen_chunks.add(_cid)
        for _p in _paths:
            image_paths.append(_p)
            break  # first validated image in chunk
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

    # Top-3 images from different chunks (already validated at extraction)
    ranked = sorted(best_per_chunk.items(), key=lambda x: -x[1][0])
    image_paths = []
    for _, (_, path, _) in ranked:
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
    """Recall controlled images: context, local index, then optional graph."""
    backfill_text = ""
    direct = extract_image_paths_with_stats(ctx)
    direct_paths = direct.paths
    lightrag_logger.info(
        "[IMG-PATHS] stage=direct KB=%s candidates=%d protocols=%s valid=%d rejected=%s",
        kb_name,
        direct.candidate_count,
        direct.protocol_counts,
        len(direct_paths),
        direct.rejection_counts,
    )

    local_paths: list[str] = []
    local_backfill = ""
    # Direct context remains authoritative, but local image chunks may add
    # relevant media until the response cap is reached.
    if len(direct_paths) < 3:
        local_paths, local_backfill = await _bigram_image_scan(
            kb_dir(kb_name), query, ctx, instance
        )
        local_paths = _validate_image_paths(local_paths)
        local_paths = [path for path in local_paths if path not in set(direct_paths)]
        if local_paths:
            backfill_text = local_backfill

    graph_paths: list[str] = []
    graph_backfill = ""
    # Graph association is an optional final expansion.  Its own total budget
    # is bounded and a failure cannot remove direct/local results.
    if len(direct_paths) + len(local_paths) < 3:
        graph_paths, graph_backfill = await _discover_images_via_graph(
            instance, query, kb_name, ctx
        )
        graph_paths = _validate_image_paths(graph_paths)
        seen = set(direct_paths) | set(local_paths)
        graph_paths = [path for path in graph_paths if path not in seen]
        if graph_paths and not backfill_text:
            backfill_text = graph_backfill

    if direct_paths:
        source = "direct"
    elif local_paths:
        source = "bigram"
    elif graph_paths:
        source = "graph"
    else:
        source = "none"

    fallback_paths = local_paths + graph_paths
    filtered_fallback = list(fallback_paths)
    if fallback_paths:
        relevance_ctx = ctx or ""
        if backfill_text:
            relevance_ctx = (
                f"{relevance_ctx}\n\n{backfill_text}"
                if relevance_ctx else backfill_text
            )
        filtered_fallback = _filter_images_by_relevance(
            fallback_paths,
            query,
            relevance_ctx,
            min_overlap=1,
        )
        if not filtered_fallback:
            filtered_fallback = fallback_paths[:1]

    raw_paths = direct_paths + fallback_paths
    filtered_paths = direct_paths + filtered_fallback
    raw_count = len(raw_paths)
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

# Only these messages are suitable for the end-user progress panel.  Library
# initialisation, cache configuration, model settings, and storage warnings
# remain available in server logs but must never be forwarded through SSE.
THINKING_PATTERNS = [
    "initializing lightrag",
    "lightrag, parse cache, multimodal status cache, and multimodal processors initialized",
    "executing text query",
    "executing rrf hybrid query",
    "query mode",
    "keywords",
    "query nodes",
    "local query",
    "query edges",
    "global query",
    "raw search results",
    "after truncation",
    "entity-related chunks",
    "relations-related chunks",
    "merged chunks",
    "final context",
    "final chunks",
    "retrying request",
    "embedding func:",
]

QUERY_SYSTEM_PROMPT = "基于检索内容回答。对话历史可用作理解用户上下文和指代关系，但事实性回答必须引用检索内容中的具体信息。检索内容没有的信息不要编造。"


def _is_thinking_msg(msg: str) -> bool:
    """Check if a log message should be shown as thinking process."""
    return bool(_translate_thinking_msg(msg))


def _translate_thinking_msg(msg: str) -> str:
    """Convert allow-listed retrieval logs into concise user-facing progress."""
    if not isinstance(msg, str):
        return ""

    msg_lower = msg.lower()

    if "initializing lightrag" in msg_lower:
        return "正在准备知识库检索..."
    if "lightrag, parse cache, multimodal status cache" in msg_lower:
        return "知识库检索已准备就绪"
    if "executing rrf hybrid query" in msg_lower:
        return "正在综合检索相关资料..."
    if "executing text query" in msg_lower:
        return "正在理解您的问题..."
    if "query mode" in msg_lower:
        mode = msg.split(":")[-1].strip().lower() if ":" in msg else ""
        mode_cn = {"hybrid": "混合检索", "local": "本地检索", "global": "全局检索",
                    "naive": "朴素检索", "mix": "混合模式"}
        return f"正在使用{mode_cn.get(mode, '知识库')}查找资料..."
    if "keywords" in msg_lower and "cache" in msg_lower:
        return "已识别问题要点"
    if "keywords" in msg_lower:
        return "正在提取问题要点..."
    if "query nodes" in msg_lower:
        return "正在查找相关概念..."
    if "local query" in msg_lower:
        return "正在检索相关资料..."
    if "query edges" in msg_lower:
        return "正在梳理资料之间的关联..."
    if "global query" in msg_lower:
        return "正在扩展查找相关资料..."
    if "raw search results" in msg_lower:
        return "已找到候选资料，正在筛选..."
    if "after truncation" in msg_lower:
        return "正在筛选最相关的资料..."
    if "entity-related chunks" in msg_lower:
        return "正在整理相关内容..."
    if "relations-related chunks" in msg_lower:
        return "正在整理关联内容..."
    if "merged chunks" in msg_lower:
        return "正在合并并排序资料..."
    if "final context" in msg_lower:
        chunk_match = _re.search(r"(\d+)\s+chunks?", msg_lower)
        if chunk_match:
            return f"已整理 {chunk_match.group(1)} 条相关资料"
        return "相关资料整理完成"
    if "final chunks" in msg_lower:
        return "相关资料整理完成"
    if "retrying request" in msg_lower:
        return "服务响应较慢，正在重试..."
    if "embedding func:" in msg_lower and "workers initialized" in msg_lower:
        return "正在进行语义匹配..."

    return ""


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
    "register_general_ws", "unregister_general_ws", "register_ws", "unregister_ws",
    "load_persisted_monitor_events", "get_monitor_events", "add_event",
    # State
    "processing_tasks", "query_history", "QUERY_HISTORY_FILE", "load_query_history", "save_query_history",
    "cleanup_completed_tasks",
    # Security
    "validate_query_input", "PROMPT_INJECTION_REGEX",
    # Local
    "MAX_UPLOAD_SIZE", "MAX_BODY_SIZE", "RequestSizeMiddleware",
    "server_logger", "extract_image_paths", "resolve_controlled_media_payload",
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
