"""Knowledge Router — /api/upload/*, /api/knowledge/*, /api/kb/*, /api/files/image"""

import asyncio
import copy
import hashlib
import json
import os
import re
import uuid
import shutil
import time
import inspect
from dataclasses import asdict
from contextlib import asynccontextmanager
from functools import wraps
from datetime import date, datetime, timezone
from pathlib import Path

import httpx
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Request, BackgroundTasks, Query as QueryParam
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, Field
from typing import Any, Optional

# Import shared module-level state (for read access)
from raganything.services.state_service import (
    upsert_task_state, complete_task, delete_task, get_task_status, get_all_tasks,
)
from .shared import (
    limiter,
    verify_kb_access,
    CHUNKING_STRATEGY,
    _reprocess_multimodal_for_kb,
    _compute_file_hash,
    _is_file_being_processed,
    _register_processing_file,
    get_kb,
    processing_tasks,
    cleanup_completed_tasks,
    kb_dir,
    lightrag_logger,
    infer_entity_type,
    add_event,
    load_kb_meta,
    save_kb_meta,
    kb_instances,
    cleanup_kb_resources,
)
from raganything.services.kb_service import (
    WORKING_DIR,
    pg_register_upload,
    pg_mark_upload_reusable,
    pg_release_upload_for_deleted_document,
    pg_update_upload_status,
    pg_update_upload_status_by_task_id,
    pg_get_upload_by_task_id,
    pg_list_uploads,
    pg_get_latest_content_updates_batch,
    cancel_inflight_upload,
    bump_kb_corpus_revision,
    _unregister_processing_file,
    _load_doc_status_json,
    _load_doc_status_summaries,
    _generate_uploaded_document_tags,
    _resolve_uploaded_document_id,
    _kb_worker_procs,
)
from raganything.dependencies import (
    get_current_user,
    get_optional_user,
    get_current_user_from_token,
    require_permission,
    verify_kb_manage_access,
    verify_kb_operate_access,
)
from raganything.permissions import Permission
from raganything.services.auth import audit_log, has_permission as _auth_has_permission
from raganything.processor.chunk_processor import compute_chunk_id
from raganything.chunking import build_chunking_func, STRATEGY_META as CHUNKING_STRATEGY_META
from raganything.utils import display_document_name, is_multimodal_processed
from raganything.services.document_tagging import (
    enqueue_document_tagging,
    wait_for_document_tagging,
)
from raganything.services.kb_tag_repo import (
    TagValidationError,
    delete_chunk_tags,
    delete_document_tags,
    delete_kb_tags,
    get_tag_assignments,
    get_tags_for_chunks,
    list_tags,
    document_mutation_lock_key,
    move_chunk_tags,
    replace_chunk_tags,
)
from raganything.services.kb_chunk_repo import (
    PersistedChunkQueryError,
    query_chunks_by_document_id,
)

# Module reference for writing to shared mutable state (active_kb)
from . import shared as _shared


def _lease_kb_cache_for_operation(handler):
    """Keep a KB's storage handles alive for the duration of a request."""

    @wraps(handler)
    async def wrapped(*args, **kwargs):
        bound = inspect.signature(handler).bind_partial(*args, **kwargs)
        kb_name = bound.arguments.get("kb")
        if not kb_name:
            return await handler(*args, **kwargs)

        was_pinned = kb_instances.is_pinned(kb_name)
        if not was_pinned:
            kb_instances.pin(kb_name)

        try:
            return await handler(*args, **kwargs)
        finally:
            if not was_pinned:
                kb_instances.unpin(kb_name)

    return wrapped


def _lease_kb_mutation_for_operation(mutation_kind: str):
    """Hold the durable KB mutation lease across a request-level mutation."""
    def decorate(handler):
        @wraps(handler)
        async def wrapped(*args, **kwargs):
            bound = inspect.signature(handler).bind_partial(*args, **kwargs)
            kb = bound.arguments.get("kb") or bound.arguments.get("kb_name")
            if not kb:
                return await handler(*args, **kwargs)
            from raganything.services.kb_mutation import run_kb_mutation_with_lease
            try:
                return await run_kb_mutation_with_lease(
                    str(kb),
                    f"request:{uuid.uuid4()}",
                    lambda: handler(*args, **kwargs),
                    mutation_kind=mutation_kind,
                )
            except RuntimeError as exc:
                if str(exc) == "reindex_in_progress":
                    raise HTTPException(
                        409,
                        {"code": "reindex_in_progress", "message": "knowledge base is reindexing"},
                    ) from exc
                raise
        return wrapped
    return decorate


# ── PG Graph Helpers: read knowledge graph data from LightRAG PG tables ──
# LightRAG stores entities/relations/doc_status in PG tables (PGKVStorage +
# PGDocStatusStorage). PG is the mandatory sole storage backend — no JSON fallback.

async def _pg_fetch_graph_entities(workspace: str) -> dict[str, dict]:
    """Fetch full entity records for a workspace from PG LIGHTRAG_FULL_ENTITIES.

    Returns:
        dict keyed by doc_id, values like {"entity_names": [...], "count": int}
    """
    from raganything.services.pg_state_repo import get_pg_pool
    pool = get_pg_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """SELECT id, entity_names, count
               FROM LIGHTRAG_FULL_ENTITIES
               WHERE workspace=$1""",
            workspace,
        )
    result = {}
    for row in rows:
        entity_names = row["entity_names"]
        if isinstance(entity_names, str):
            try:
                entity_names = json.loads(entity_names)
            except json.JSONDecodeError:
                entity_names = []
        result[row["id"]] = {
            "entity_names": entity_names or [],
            "count": row["count"] or len(entity_names or []),
        }
    return result


async def _pg_fetch_graph_relations(workspace: str) -> dict[str, dict]:
    """Fetch full relation records for a workspace from PG LIGHTRAG_FULL_RELATIONS.

    Returns:
        dict keyed by doc_id, values like {"relation_pairs": [...], "count": int}
    """
    from raganything.services.pg_state_repo import get_pg_pool
    pool = get_pg_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """SELECT id, relation_pairs, count
               FROM LIGHTRAG_FULL_RELATIONS
               WHERE workspace=$1""",
            workspace,
        )
    result = {}
    for row in rows:
        relation_pairs = row["relation_pairs"]
        if isinstance(relation_pairs, str):
            try:
                relation_pairs = json.loads(relation_pairs)
            except json.JSONDecodeError:
                relation_pairs = []
        result[row["id"]] = {
            "relation_pairs": relation_pairs or [],
            "count": row["count"] or len(relation_pairs or []),
        }
    return result


async def _pg_fetch_doc_ids(workspace: str) -> set[str]:
    """Fetch valid document IDs from PG LIGHTRAG_DOC_STATUS for a workspace."""
    from raganything.services.pg_state_repo import get_pg_pool
    pool = get_pg_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT id FROM LIGHTRAG_DOC_STATUS WHERE workspace=$1",
            workspace,
        )
    return {row["id"] for row in rows}


async def _pg_fetch_full_doc_ids(workspace: str) -> set[str]:
    """Fetch every full-document ID, including rows missing doc_status.

    ``full_docs.get_by_ids()`` can only retrieve IDs already known to
    ``doc_status``. Orphan repair needs the inverse: all persisted rows in the
    workspace, including historical records whose doc-status row is gone.
    """
    from raganything.services.pg_state_repo import get_pg_pool

    pool = get_pg_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT id FROM LIGHTRAG_DOC_FULL WHERE workspace=$1",
            workspace,
        )
    return {row["id"] for row in rows}


async def _pg_fetch_graph_totals(workspace: str) -> tuple[int, int]:
    """Fetch aggregated entity/relation totals for a workspace from PG."""
    from raganything.services.pg_state_repo import get_pg_pool

    pool = get_pg_pool()
    async with pool.acquire() as conn:
        entity_total = await conn.fetchval(
            """SELECT COALESCE(SUM(count), 0)
               FROM LIGHTRAG_FULL_ENTITIES
               WHERE workspace=$1""",
            workspace,
        )
        relation_total = await conn.fetchval(
            """SELECT COALESCE(SUM(count), 0)
               FROM LIGHTRAG_FULL_RELATIONS
               WHERE workspace=$1""",
            workspace,
        )

    return int(entity_total or 0), int(relation_total or 0)


async def _pg_fetch_doc_totals(workspace: str) -> tuple[int, int] | None:
    """Fetch deduped document and chunk totals directly from PG doc_status."""
    batch_totals = await _pg_fetch_doc_totals_batch([workspace])
    return batch_totals.get(workspace, (0, 0))


async def _pg_fetch_doc_totals_batch(workspaces: list[str]) -> dict[str, tuple[int, int]]:
    """Fetch deduped document and chunk totals for multiple workspaces in one query."""
    from raganything.services.pg_state_repo import get_pg_pool

    if not workspaces:
        return {}

    pool = get_pg_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """WITH ranked_docs AS (
                   SELECT
                       workspace,
                       regexp_replace(
                           COALESCE(file_path, ''),
                           '^[0-9a-f]{8}_(.+)$',
                           '\\1'
                       ) AS original_name,
                       COALESCE(chunks_count, 0) AS chunks_count,
                       ROW_NUMBER() OVER (
                           PARTITION BY
                               workspace,
                               regexp_replace(
                                   COALESCE(file_path, ''),
                                   '^[0-9a-f]{8}_(.+)$',
                                   '\\1'
                               )
                           ORDER BY updated_at DESC NULLS LAST, id DESC
                       ) AS rn
                   FROM LIGHTRAG_DOC_STATUS
                   WHERE workspace = ANY($1::text[])
               )
               SELECT
                   workspace,
                   COUNT(*)::int AS documents,
                   COALESCE(SUM(chunks_count), 0)::int AS chunks
               FROM ranked_docs
               WHERE rn = 1
               GROUP BY workspace""",
            workspaces,
        )

    totals = {workspace: (0, 0) for workspace in workspaces}
    for row in rows:
        totals[row["workspace"]] = (
            int(row["documents"] or 0),
            int(row["chunks"] or 0),
        )

    return totals


async def _pg_fetch_graph_totals_batch(workspaces: list[str]) -> dict[str, tuple[int, int]]:
    """Fetch entity/relation totals for multiple workspaces with batched PG queries."""
    from raganything.services.pg_state_repo import get_pg_pool

    if not workspaces:
        return {}

    pool = get_pg_pool()
    async with pool.acquire() as conn:
        entity_rows = await conn.fetch(
            """SELECT workspace, COALESCE(SUM(count), 0) AS total
               FROM LIGHTRAG_FULL_ENTITIES
               WHERE workspace = ANY($1::text[])
               GROUP BY workspace""",
            workspaces,
        )
        relation_rows = await conn.fetch(
            """SELECT workspace, COALESCE(SUM(count), 0) AS total
               FROM LIGHTRAG_FULL_RELATIONS
               WHERE workspace = ANY($1::text[])
               GROUP BY workspace""",
            workspaces,
        )

    totals = {workspace: [0, 0] for workspace in workspaces}
    for row in entity_rows:
        totals.setdefault(row["workspace"], [0, 0])[0] = int(row["total"] or 0)
    for row in relation_rows:
        totals.setdefault(row["workspace"], [0, 0])[1] = int(row["total"] or 0)

    return {
        workspace: (values[0], values[1])
        for workspace, values in totals.items()
    }


router = APIRouter(tags=["knowledge"])

# ── Pydantic models ────────────────────────────────────

class PasteContentRequest(BaseModel):
    content: str
    title: str = ""

class BatchDeleteRequest(BaseModel):
    doc_ids: list[str]

    max_async: Optional[int] = None
    enable_image: Optional[bool] = None
    enable_table: Optional[bool] = None
    enable_equation: Optional[bool] = None
    enable_video: Optional[bool] = None


class CreateEntityRequest(BaseModel):
    name: str
    entity_type: str = ""
    description: str = ""


class RenameEntityRequest(BaseModel):
    new_name: str


class CreateRelationRequest(BaseModel):
    source_entity: str
    target_entity: str
    relation_type: str = "related_to"
    description: str = ""


class KBStatsBatchRequest(BaseModel):
    kb_names: list[str]


class VisionSettingsUpdate(BaseModel):
    profile_id: str
    reindex: bool = False


class KBIngestionSettingsUpdate(BaseModel):
    expected_revision: int
    values: dict[str, Any] | None


class KBMetadataUpdate(BaseModel):
    display_name: str
    expected_updated_at: str


class KBMemberGrantUpdate(BaseModel):
    access_level: str


KB_STATS_BATCH_TIMEOUT_SECONDS = 6.0


def _kb_editor_capabilities_from_metadata(metadata: dict, current_user: dict) -> dict[str, bool]:
    """Derive editor actions from the role plus the already-checked KB scope."""
    role_name = (current_user.get("role") or {}).get("name")
    role_permissions = (current_user.get("role") or {}).get("permissions") or []
    is_owner = metadata.get("owner_id") == current_user.get("id")
    has_manage_permission = current_user.get("is_admin") or Permission.KB_MANAGE in role_permissions
    can_edit = bool(
        has_manage_permission
        and (
            current_user.get("is_admin")
            or role_name == "dept_admin"
            or (role_name == "teacher" and is_owner)
        )
    )
    return {
        "edit": can_edit,
        "rename": can_edit,
        "manage_members": can_edit,
    }


async def _require_kb_editor_access(kb: str, current_user: dict) -> tuple[dict, dict[str, bool]]:
    metadata = (await load_kb_meta()).get(kb)
    if metadata is None:
        raise HTTPException(404, "knowledge base not found")
    if not await _auth_has_permission(int(current_user["id"]), Permission.KB_MANAGE):
        raise HTTPException(403, "权限不足，需要 kb:manage")
    await verify_kb_manage_access(kb, current_user)
    capabilities = _kb_editor_capabilities_from_metadata(metadata, current_user)
    if not capabilities["edit"]:
        raise HTTPException(403, "knowledge-base editor access is required")
    return metadata, capabilities


async def _resolve_upload_vlm_snapshot(user_id: int):
    from raganything.services import vision_models
    from raganything.services import user_settings

    try:
        resolved = await user_settings.resolve_user_settings_for_task(
            user_id,
            permitted_sections=await user_settings.available_sections_for_user(user_id),
        )
        return vision_models.require_available(resolved.models.vlm_profile_id, "vlm")
    except (KeyError, ValueError, RuntimeError) as exc:
        raise HTTPException(
            status_code=503,
            detail={
                "code": "profile_unavailable",
                "message": "selected image-understanding profile is unavailable",
            },
        ) from exc


def _optional_upload_boolean(value: str) -> bool | None:
    return value.lower() == "true" if value else None


async def _create_upload_settings_snapshot(
    task_id: str,
    user_id: int,
    *,
    kb: str = "",
    chunking_strategy: str = "",
    enable_image: str = "",
    enable_table: str = "",
    enable_equation: str = "",
    enable_video: str = "",
) -> Any:
    """Persist the complete effective upload configuration before enqueueing."""
    from raganything.services.user_settings import (
        available_sections_for_user,
        create_task_settings_snapshot,
        resolve_user_settings_for_task,
        with_task_ingestion_overrides,
    )

    ingestion_overrides = {
        field: value
        for field, value in {
            "chunking_strategy": chunking_strategy or None,
            "enable_image": _optional_upload_boolean(enable_image),
            "enable_table": _optional_upload_boolean(enable_table),
            "enable_equation": _optional_upload_boolean(enable_equation),
            "enable_video": _optional_upload_boolean(enable_video),
        }.items()
        if value is not None
    }
    kb_defaults: dict[str, Any] = {}
    if kb:
        meta = (await load_kb_meta()).get(kb, {})
        extra = meta.get("extra", {}) if isinstance(meta, dict) else {}
        if isinstance(extra, dict) and isinstance(extra.get("ingestion_defaults"), dict):
            kb_defaults = extra["ingestion_defaults"]
    resolved = await resolve_user_settings_for_task(
        user_id,
        request_overrides={"ingestion": ingestion_overrides},
        knowledge_base_settings={"ingestion": kb_defaults},
        permitted_sections=await available_sections_for_user(user_id),
    )
    # 启用视频处理的上传快照冻结语义分段 profile（v2）；旧快照保持整片路径。
    if resolved.ingestion.enable_video:
        resolved = with_task_ingestion_overrides(resolved, enable_video=True)
    await create_task_settings_snapshot(task_id, user_id, resolved)
    return resolved.ingestion


async def _delete_upload_settings_snapshot(task_id: str) -> None:
    from raganything.services.user_settings import delete_task_settings_snapshot

    try:
        await delete_task_settings_snapshot(task_id)
    except Exception:
        lightrag_logger.warning(
            "Could not remove unqueued settings snapshot: task=%s",
            task_id,
            exc_info=True,
        )


async def _get_snapshot_task_kb(task_id: str, kb: str):
    """Create an uncached KB instance from a persisted task snapshot."""
    from raganything.services.user_settings import get_task_settings_snapshot

    snapshot = await get_task_settings_snapshot(task_id)
    settings = snapshot.get("settings")
    if not isinstance(settings, dict):
        raise RuntimeError("settings_snapshot_invalid")
    settings = dict(settings)
    profile_ids = snapshot.get("profile_ids") or {}
    llm_profile = profile_ids.get("llm") if isinstance(profile_ids, dict) else None
    if isinstance(llm_profile, dict):
        llm_profile_id = llm_profile.get("id")
        llm_fingerprint = str(llm_profile.get("fingerprint") or "unknown")
    else:
        llm_profile_id = llm_profile
        llm_fingerprint = "unknown"
    if isinstance(llm_profile_id, str) and llm_profile_id:
        from raganything.services.vision_models import require_available

        entry = require_available(llm_profile_id, "llm")
        if llm_fingerprint != "unknown" and entry.fingerprint != llm_fingerprint:
            raise RuntimeError("profile_changed")
        llm_fingerprint = entry.fingerprint
    updates = await pg_get_latest_content_updates_batch([kb])
    settings["_query_scope"] = {
        "workspace": kb,
        "permission_scope": f"user:{int(snapshot['user_id'])}",
        "corpus_revision": updates.get(kb) or f"task:{task_id}",
        "settings_fingerprint": str(snapshot.get("fingerprint") or "unknown"),
        "llm_profile_fingerprint": llm_fingerprint,
    }
    return await get_kb(kb, task_settings=settings)


async def _ensure_vision_index_mutable(kb: str) -> None:
    from raganything.services import vision_models
    if await vision_models._pg_pool() is None:
        return
    meta = (await load_kb_meta()).get(kb, {})
    extra = meta.get("extra", {}) if isinstance(meta, dict) else {}
    state = extra.get("vision_embedding", {}) if isinstance(extra, dict) else {}
    if isinstance(state, dict) and state.get("index_state") == "reindexing":
        raise HTTPException(
            status_code=409,
            detail={
                "code": "reindex_in_progress",
                "task_id": (state.get("task") or {}).get("id"),
            },
        )


async def _verify_kb_path_access(
    kb: str,
    current_user: dict = Depends(get_current_user),
) -> str:
    """Bind KB authorization to a path parameter, not Query("default")."""
    return await verify_kb_access(kb, current_user)


async def _verify_kb_vision_read_access(
    kb: str,
    current_user: dict = Depends(get_current_user),
) -> str:
    """Read guard for vision settings: KB visibility + kb:read."""
    actual_kb = await verify_kb_access(kb, current_user)
    if not await _auth_has_permission(int(current_user["id"]), Permission.KB_READ):
        raise HTTPException(403, "权限不足，需要 kb:read")
    return actual_kb


async def _verify_kb_vision_write_access(
    kb: str,
    current_user: dict = Depends(get_current_user),
) -> str:
    """Require operate scope as well as the global KB write permission."""
    actual_kb = await verify_kb_operate_access(kb, current_user)
    if await _auth_has_permission(int(current_user["id"]), Permission.KB_WRITE):
        return actual_kb
    raise HTTPException(403, "权限不足，需要 kb:write")


@router.get("/kb/{kb}/vision-settings")
async def get_kb_vision_settings(
    kb: str,
    _access: str = Depends(_verify_kb_vision_read_access),
    _user: dict = Depends(get_current_user),
):
    meta = (await load_kb_meta()).get(kb)
    if not meta:
        raise HTTPException(404, "知识库不存在")
    state = (meta.get("extra") or {}).get("vision_embedding") or {}
    return {"kb": kb, "vision_embedding": state}


def _sparse_ingestion_values(values: dict[str, Any] | None) -> dict[str, Any]:
    """Validate one KB's explicit ingestion overrides and drop inheritance markers."""
    from raganything.services import user_settings

    raw = values or {}
    if not isinstance(raw, dict):
        raise ValueError("ingestion settings must be an object")
    allowed = user_settings.ALLOWED_FIELDS["ingestion"]
    if not set(raw).issubset(allowed):
        raise ValueError("invalid ingestion settings fields")
    result = {key: value for key, value in raw.items() if value is not None}
    if "parsers_by_type" in result:
        result["parsers_by_type"] = user_settings._normalize_parsers_by_type(result["parsers_by_type"])
    user_settings._validate_section("ingestion", result)
    return result


async def _kb_ingestion_state(kb: str, user_id: int) -> dict[str, Any]:
    from raganything.services import user_settings

    meta = (await load_kb_meta()).get(kb)
    if not meta:
        raise HTTPException(404, "knowledge base not found")
    extra = meta.get("extra", {}) if isinstance(meta, dict) else {}
    extra = extra if isinstance(extra, dict) else {}
    stored = extra.get("ingestion_defaults", {})
    stored = stored if isinstance(stored, dict) else {}
    sections = await user_settings.available_sections_for_user(user_id)
    personal = await user_settings.get_user_settings(user_id, permitted_sections=sections)
    platform = await user_settings.get_platform_settings()
    resolved, sources, constraints = user_settings.resolve_settings(
        stored=personal.get("stored") or {},
        platform=platform.get("settings") or {},
        revision=int(personal.get("revision", 0)),
        knowledge_base_settings={"ingestion": stored},
    )
    return {
        "kb": kb,
        "revision": int(extra.get("ingestion_defaults_revision", 0) or 0),
        "stored": stored,
        "effective": asdict(resolved.ingestion),
        "sources": sources.get("ingestion", {}),
        "constraints": constraints.get("ingestion", {}),
    }


@router.get("/kb/{kb}/ingestion-settings")
async def get_kb_ingestion_settings(
    kb: str,
    _access: str = Depends(_verify_kb_vision_read_access),
    user: dict = Depends(get_current_user),
):
    return await _kb_ingestion_state(kb, int(user["id"]))


@router.put("/kb/{kb}/ingestion-settings")
async def update_kb_ingestion_settings(
    kb: str,
    payload: KBIngestionSettingsUpdate,
    _perm: None = Depends(require_permission(Permission.KB_WRITE)),
    user: dict = Depends(get_current_user),
):
    await verify_kb_operate_access(kb, user)
    try:
        values = _sparse_ingestion_values(payload.values)
        from raganything.services import user_settings
        platform = await user_settings.get_platform_settings()
        user_settings._validate_section_against_platform_policy("ingestion", values, platform["settings"])
        from raganything.services.pg_kb_meta_repo import pg_update_kb_ingestion_defaults
        result = await pg_update_kb_ingestion_defaults(kb, values, payload.expected_revision)
    except ValueError as exc:
        raise HTTPException(422, {"code": "invalid_settings", "message": str(exc)}) from exc
    except KeyError as exc:
        raise HTTPException(404, "knowledge base not found") from exc
    except RuntimeError as exc:
        raise HTTPException(503, {"code": "settings_unavailable", "message": "knowledge base settings storage is unavailable"}) from exc
    if result is None:
        raise HTTPException(409, {"code": "revision_conflict", "message": "knowledge base settings revision has changed"})
    await audit_log(int(user["id"]), "kb.ingestion_settings.updated", details={"kb": kb, "revision": result[1]})
    return await _kb_ingestion_state(kb, int(user["id"]))


@router.put("/kb/{kb}/vision-settings")
async def update_kb_vision_settings(
    kb: str,
    payload: VisionSettingsUpdate,
    _access: str = Depends(_verify_kb_vision_write_access),
    current_user: dict = Depends(get_current_user),
):
    """Switch a KB-owned visual vector space, guarding populated indexes."""
    from raganything.services import vision_models

    meta = await load_kb_meta()
    kb_meta = meta.get(kb)
    if not kb_meta:
        raise HTTPException(404, "知识库不存在")
    try:
        target = vision_models.require_available(payload.profile_id, "embedding")
    except ValueError as exc:
        raise HTTPException(422, {"code": "invalid_profile", "message": "invalid vision embedding profile"}) from exc
    except RuntimeError as exc:
        raise HTTPException(503, {"code": "profile_unavailable", "message": "vision embedding profile is unavailable"}) from exc
    extra = kb_meta.setdefault("extra", {})
    current = extra.get("vision_embedding") or {}
    if current.get("index_state") == "reindexing":
        raise HTTPException(409, {"code": "reindex_in_progress", "task_id": (current.get("task") or {}).get("id")})
    if current.get("profile_id") == target.profile.id and current.get("profile_fingerprint") == target.fingerprint:
        return {"kb": kb, "vision_embedding": current}

    pool = await vision_models._pg_pool()
    if pool is None:
        raise HTTPException(503, {"code": "vision_storage_unavailable", "message": "PostgreSQL is required for visual vector settings"})
    workspace = str(Path(kb_dir(kb)).resolve())
    source_id = current.get("profile_id")
    source_fingerprint = current.get("profile_fingerprint")
    async with pool.acquire() as conn:
        if source_id and source_fingerprint:
            total = await conn.fetchval(
                "SELECT COUNT(*) FROM image_vision_vectors WHERE workspace=$1 "
                "AND profile_id=$2 AND profile_fingerprint=$3",
                workspace,
                source_id,
                source_fingerprint,
            )
        else:
            total = await conn.fetchval(
                "SELECT COUNT(*) FROM image_vision_vectors WHERE workspace=$1",
                workspace,
            )
    total = int(total or 0)
    # NanoVectorDB is an explicitly supported profile-scoped store. Its
    # active partition must count as populated even when the PG table is empty.
    if total == 0 and source_id and source_fingerprint:
        nano_rows, _ = vision_models._load_nano_reindex_rows(
            workspace, source_id, source_fingerprint
        )
        total = len(nano_rows)
    if total == 0 or not source_id:
        try:
            next_state = await vision_models.activate_empty_vision_profile(
                kb=kb, workspace=workspace, target=target,
            )
        except RuntimeError as exc:
            code = str(exc)
            if code in {"reindex_in_progress", "vision_mutation_in_progress"}:
                raise HTTPException(409, {"code": code, "message": "cannot switch visual profile during KB mutation"}) from exc
            if code == "vision_index_populated":
                raise HTTPException(409, {"code": "reindex_required", "message": "visual vectors were added; refresh and confirm reindex"}) from exc
            raise HTTPException(503, {"code": "vision_storage_unavailable", "message": "visual vector storage is unavailable"}) from exc
        await vision_models.audit_vision_event(
            int(current_user["id"]),
            "vision.kb_profile.updated",
            profile_id=target.profile.id,
            previous_profile_id=source_id,
            kb=kb,
        )
        return {"kb": kb, "vision_embedding": next_state}
    if not payload.reindex:
        raise HTTPException(409, {"code": "reindex_required", "message": "visual vectors already exist; confirm reindex"})
    try:
        # A reindex reads raw document media and only needs the target adapter.
        # Preserve an old active partition even after its profile is retired.
        source = vision_models.get_entry(source_id, "embedding")
        task_id = str(uuid.uuid4())
        await vision_models.create_reindex_job(task_id=task_id, kb=kb, actor_id=int(current_user["id"]), source=source, target=target, total=total)
        vision_models.schedule_reindex_job(task_id)
    except RuntimeError as exc:
        code = str(exc)
        if code in {"reindex_in_progress", "vision_mutation_in_progress"}:
            raise HTTPException(409, {"code": code, "message": "cannot start visual reindex"}) from exc
        raise HTTPException(503, {"code": "profile_unavailable", "message": "vision reindex source is unavailable"}) from exc
    await vision_models.audit_vision_event(int(current_user["id"]), "vision.kb_reindex.queued", profile_id=target.profile.id, kb=kb, result="queued")
    return JSONResponse(
        status_code=202,
        content={"task_id": task_id, "status": "queued"},
    )


# ── Upload handlers ────────────────────────────────────


def _staged_upload_path(upload_dir: Path, task_id: str, filename: str) -> Path:
    """Allocate a task-owned staged filename without changing its display name."""
    safe_name = os.path.basename(str(filename or "")) or "upload"
    return upload_dir / f"{task_id.replace('-', '')}_{safe_name}"

@router.post("/upload")
@limiter.limit("30/minute")
async def upload_file(request: Request, file: UploadFile = File(...), background_tasks: BackgroundTasks = None,
                       kb: str = Depends(verify_kb_operate_access), chunking_strategy: str = "",
                       enable_image: str = "", enable_table: str = "",
                       enable_equation: str = "", enable_video: str = "",
                       _perm: None = Depends(require_permission(Permission.KB_WRITE)),
                       current_user: dict = Depends(get_current_user)):
    """Upload a single file — immediate return, background processing"""
    await _ensure_vision_index_mutable(kb)
    vlm_snapshot = await _resolve_upload_vlm_snapshot(current_user["id"])
    actual_strategy = _resolve_chunking_strategy(chunking_strategy)
    task_id = str(uuid.uuid4())
    upload_dir = Path("./uploads")
    upload_dir.mkdir(exist_ok=True)
    safe_name = os.path.basename(file.filename)
    file_path = _staged_upload_path(upload_dir, task_id, safe_name)

    # Stream write to disk (avoid loading full file into memory)
    try:
        with open(file_path, 'wb') as dest:
            shutil.copyfileobj(file.file, dest)
    except Exception:
        # Clean up partial file on write failure
        try:
            file_path.unlink(missing_ok=True)
        except OSError:
            pass
        raise HTTPException(507, "存储空间不足或写入失败，请稍后重试")

    file_size = file_path.stat().st_size

    # Dedup check: reject if same file content is already being processed in this KB
    file_hash = _compute_file_hash(str(file_path))
    existing_task = _is_file_being_processed(kb, file_hash)
    if existing_task:
        lightrag_logger.warning(
            f"[UPLOAD-API] 重复上传拒绝: file={file.filename} kb={kb} "
            f"existing_task={existing_task}"
        )
        from raganything.services.ws_service import ws_broadcast
        await ws_broadcast({
            "type": "duplicate", "file": file.filename,
            "existing_task_id": existing_task, "kb": kb,
        })
        file_path.unlink(missing_ok=True)
        raise HTTPException(
            409,
            f"文件正在处理中 (task_id={existing_task})",
        )

    try:
        ingestion = await _create_upload_settings_snapshot(
            task_id, int(current_user["id"]), kb=kb, chunking_strategy=actual_strategy,
            enable_image=enable_image, enable_table=enable_table,
            enable_equation=enable_equation, enable_video=enable_video,
        )
        actual_strategy = ingestion.chunking_strategy
    except RuntimeError as exc:
        file_path.unlink(missing_ok=True)
        raise HTTPException(
            503,
            {"code": "settings_snapshot_unavailable", "message": "无法创建任务设置快照"},
        ) from exc

    # Register file metadata in PG (dedup enforced by UNIQUE on file_hash + kb_name)
    pg_id = await _register_upload_with_stale_recovery(
        filename=safe_name,
        file_path=str(file_path.absolute()),
        file_hash=file_hash,
        file_size=file_size,
        kb_name=kb,
        uploaded_by=current_user.get("id", 0),
        task_id=task_id,
    )
    if pg_id is None:
        # PG insert failed — either a true duplicate or PG unavailable.
        # Clean up the written file and report the conflict.
        try:
            file_path.unlink(missing_ok=True)
        except OSError:
            pass
        await _delete_upload_settings_snapshot(task_id)
        raise HTTPException(
            409,
            f"文件内容重复或上传注册失败: {file.filename}",
        )

    lightrag_logger.info(f"[UPLOAD-API] 收到上传请求: file={file.filename} kb={kb} strategy={actual_strategy}")

    # Register for dedup tracking BEFORE spawning the background task
    _register_processing_file(kb, file_hash, task_id)

    # 推入 per-KB 处理队列（统一排队，防止并发竞争 LightRAG 存储）
    from .shared import _enqueue_upload_task
    task_info = {
        "task_id": task_id,
        "file_path": str(file_path.absolute()),
        "filename": file.filename,
        "kb_name": kb,
        "chunking_strategy": actual_strategy,
        "user_id": current_user["id"],
        "vision_vlm_profile_id": vlm_snapshot.profile.id,
        "vision_vlm_profile_fingerprint": vlm_snapshot.fingerprint,
        "enable_image": ingestion.enable_image,
        "enable_table": ingestion.enable_table,
        "enable_equation": ingestion.enable_equation,
        "enable_video": ingestion.enable_video,
        "settings_snapshot_id": task_id,
    }
    queue, qsize = await _enqueue_upload_task(task_info)
    strategy_name = CHUNKING_STRATEGY_META.get(actual_strategy, {}).get('name', '默认')
    return {"task_id": task_id, "filename": file.filename, "status": "queued", "kb": kb,
            "chunking_strategy": actual_strategy,
            "position": qsize + 1, "queue_size": qsize + 1,
            "can_delete": True,
            "message": f"文档已加入队列（第 {qsize + 1} 位），使用{strategy_name}分块。请到知识库页面查看进度。"}


@router.post("/upload/batch")
@limiter.limit("20/minute")
async def upload_files(request: Request, files: list[UploadFile] = File(...), background_tasks: BackgroundTasks = None,
                       kb: str = Depends(verify_kb_operate_access), chunking_strategy: str = "",
                       enable_image: str = "", enable_table: str = "",
                       enable_equation: str = "", enable_video: str = "",
                       _perm: None = Depends(require_permission(Permission.KB_WRITE)),
                       current_user: dict = Depends(get_current_user)):
    """批量上传文件 - 接收多个文件，逐个后台处理"""
    if not files:
        raise HTTPException(400, "请至少选择一个文件")
    await _ensure_vision_index_mutable(kb)

    actual_strategy = _resolve_chunking_strategy(chunking_strategy)

    upload_dir = Path("./uploads")
    upload_dir.mkdir(exist_ok=True)

    vlm_snapshot = await _resolve_upload_vlm_snapshot(current_user["id"])
    tasks = []
    skipped: list[str] = []
    skipped_details: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    queue_size = 0
    from .shared import _enqueue_upload_task

    for file_index, file in enumerate(files):
        task_id = str(uuid.uuid4())
        safe_name = os.path.basename(file.filename)
        file_path = _staged_upload_path(upload_dir, task_id, safe_name)

        # Stream write to disk (avoid loading full file into memory)
        try:
            with open(file_path, 'wb') as dest:
                shutil.copyfileobj(file.file, dest)
        except Exception:
            try:
                file_path.unlink(missing_ok=True)
            except OSError:
                pass
            lightrag_logger.error(f"[UPLOAD-BATCH] 写入失败: file={file.filename}")
            errors.append({
                "filename": file.filename,
                "file_index": file_index,
                "code": "storage_write_failed",
                "message": "文件写入失败，请稍后重试",
            })
            continue

        file_size = file_path.stat().st_size

        # Dedup check per file
        file_hash = _compute_file_hash(str(file_path))
        existing_task = _is_file_being_processed(kb, file_hash)
        if existing_task:
            lightrag_logger.warning(
                f"[UPLOAD-BATCH] 跳过重复: file={file.filename} existing_task={existing_task}"
            )
            file_path.unlink(missing_ok=True)
            skipped.append(file.filename)
            skipped_details.append({"filename": file.filename, "file_index": file_index})
            continue

        try:
            ingestion = await _create_upload_settings_snapshot(
                task_id, int(current_user["id"]), kb=kb, chunking_strategy=actual_strategy,
                enable_image=enable_image, enable_table=enable_table,
                enable_equation=enable_equation, enable_video=enable_video,
            )
            actual_strategy = ingestion.chunking_strategy
        except RuntimeError as exc:
            file_path.unlink(missing_ok=True)
            lightrag_logger.warning(
                "[UPLOAD-BATCH] settings snapshot failed for file=%s: %s",
                file.filename,
                exc,
            )
            errors.append({
                "filename": file.filename,
                "file_index": file_index,
                "code": "settings_snapshot_unavailable",
                "message": "无法创建任务设置快照",
            })
            continue

        # Register file metadata in PG (dedup enforced by UNIQUE on file_hash + kb_name)
        pg_id = await _register_upload_with_stale_recovery(
            filename=safe_name,
            file_path=str(file_path.absolute()),
            file_hash=file_hash,
            file_size=file_size,
            kb_name=kb,
            uploaded_by=current_user.get("id", 0),
            task_id=task_id,
        )
        if pg_id is None:
            # The registration layer cannot distinguish an existing durable
            # document from a transient PG failure.  Do not present either as
            # a successful duplicate skip: retain the source row and let the
            # user retry after checking the existing document.
            lightrag_logger.warning(
                f"[UPLOAD-BATCH] 注册失败（重复或PG不可用）: file={file.filename} hash={file_hash}"
            )
            try:
                file_path.unlink(missing_ok=True)
            except OSError:
                pass
            await _delete_upload_settings_snapshot(task_id)
            errors.append({
                "filename": file.filename,
                "file_index": file_index,
                "code": "upload_registration_failed",
                "message": "文件内容已存在或上传注册暂不可用，请稍后重试",
            })
            continue
        _register_processing_file(kb, file_hash, task_id)

        # Push to per-KB queue (shared with single-file upload endpoint)
        task_info = {
            "task_id": task_id,
            "file_path": str(file_path.absolute()),
            "filename": file.filename,
            "kb_name": kb,
            "chunking_strategy": actual_strategy,
            "user_id": current_user["id"],
            "vision_vlm_profile_id": vlm_snapshot.profile.id,
            "vision_vlm_profile_fingerprint": vlm_snapshot.fingerprint,
            "enable_image": ingestion.enable_image,
            "enable_table": ingestion.enable_table,
            "enable_equation": ingestion.enable_equation,
            "enable_video": ingestion.enable_video,
            "settings_snapshot_id": task_id,
        }
        queue, pre_qsize = await _enqueue_upload_task(task_info)
        queue_size = queue.qsize()
        tasks.append({
            "task_id": task_id, "filename": file.filename, "file_index": file_index,
            "status": "queued", "position": queue_size,
            "can_delete": True,
        })
        lightrag_logger.info(f"[UPLOAD-BATCH] 任务={task_id} 文件={file.filename} kb={kb}")

    strategy_name = CHUNKING_STRATEGY_META.get(actual_strategy, {}).get('name', '默认')
    if tasks:
        message = f"已接收 {len(tasks)} 个文件，使用{strategy_name}分块，排队处理中"
        if skipped:
            message += f"，跳过 {len(skipped)} 个重复文件"
        if errors:
            message += f"，{len(errors)} 个提交失败"
    elif skipped:
        message = f"{len(skipped)} 个重复文件已跳过，没有新任务入队"
    elif errors:
        message = f"{len(errors)} 个文件提交失败，没有新任务入队"
    else:
        message = "没有新文件进入上传队列"

    result = {"status": "queued" if tasks else "skipped", "tasks": tasks, "total": len(tasks), "kb": kb,
              "chunking_strategy": actual_strategy,
              "queue_size": queue_size,
              "message": message}
    if skipped:
        result["skipped"] = skipped
        result["skipped_details"] = skipped_details
    if errors:
        result["errors"] = errors
    return result


@router.get("/upload/tasks")
async def list_upload_tasks(
    kb: str = Depends(verify_kb_access),
    current_user: dict = Depends(get_current_user),
):
    """List persisted upload tasks for the current KB."""
    uploads, _total = await pg_list_uploads(
        kb_name=kb,
        uploaded_by=current_user.get("id"),
        is_admin=current_user.get("is_admin", False),
        limit=200,
        offset=0,
        exclude_statuses=["deleted"],
    )
    active_tasks = {
        (task.get("id") or task.get("task_id")): task
        for task in await get_all_tasks()
        if task.get("kb", task.get("kb_name", "")) == kb
    }
    from raganything.services.upload_retry import get_retry_metadata
    retry_by_task = await get_retry_metadata(
        [str(upload.get("task_id")) for upload in uploads if upload.get("task_id")]
    )

    tasks = []
    for upload in uploads:
        task_id = upload.get("task_id")
        if not task_id:
            continue

        runtime_task = active_tasks.get(task_id, {})
        retry = retry_by_task.get(str(task_id), {})
        durable_status = upload.get("status") or "queued"
        if durable_status == "cancelling":
            # Restart cleanup after a process restart; the coordinator is idempotent.
            await cancel_inflight_upload(str(task_id), kb)
        status = durable_status if durable_status in {"cancelling", "deleted"} else (
            runtime_task.get("status") or durable_status
        )
        progress = runtime_task.get("progress")
        if progress is None:
            progress = 100 if status == "completed" else 0
        phase = runtime_task.get("phase") or ""
        error_message = (
            runtime_task.get("error_message")
            or runtime_task.get("error")
            or upload.get("error_message")
            or ""
        )
        outcome = runtime_task.get("outcome") or upload.get("outcome") or ""
        warning_message = (
            runtime_task.get("warning_message")
            or runtime_task.get("warning")
            or upload.get("warning_message")
            or ""
        )
        tasks.append({
            "task_id": task_id,
            "filename": upload.get("filename", ""),
            "file_size": upload.get("file_size", 0),
            "status": status,
            "progress": progress,
            "phase": phase,
            "error_message": error_message,
            "outcome": outcome,
            "warning_message": warning_message,
            "retryable": bool(
                runtime_task.get("retryable")
                if "retryable" in runtime_task
                else retry.get("status") in {"queued", "running", "retry_wait"}
            ),
            "failure_stage": runtime_task.get("failure_stage") or retry.get("stage") or "",
            "retry_count": int(runtime_task.get("retry_count") or retry.get("attempt_count") or 0),
            "max_retries": int(runtime_task.get("max_retries") or retry.get("max_attempts") or 5),
            "next_retry_at": (
                runtime_task.get("next_retry_at")
                or (retry["next_attempt_at"].isoformat() if retry.get("next_attempt_at") else None)
            ),
            "created_at": upload.get("created_at", ""),
            "updated_at": runtime_task.get("updated_at") or upload.get("updated_at", ""),
            "can_delete": status in {"queued", "processing", "retry_wait"},
        })

    return {"tasks": tasks, "total": len(tasks)}


@router.post("/upload/tasks/{task_id}/retry-now")
async def retry_upload_task_now(
    task_id: str,
    kb: str = Depends(verify_kb_operate_access),
    _perm: None = Depends(require_permission(Permission.KB_WRITE)),
    current_user: dict = Depends(get_current_user),
):
    upload = await pg_get_upload_by_task_id(
        task_id, kb_name=kb, uploaded_by=current_user.get("id"),
        is_admin=current_user.get("is_admin", False),
    )
    if not upload:
        raise HTTPException(404, "Upload task not found")
    from raganything.services.upload_retry import retry_now
    if not await retry_now(task_id, reset_budget=upload.get("status") == "failed"):
        raise HTTPException(409, "Upload task is not waiting for retry")
    return {"task_id": task_id, "status": "retry_wait", "queued": True}


@router.post("/upload/tasks/{task_id}/cancel-retry")
async def cancel_upload_task_retry(
    task_id: str,
    kb: str = Depends(verify_kb_operate_access),
    _perm: None = Depends(require_permission(Permission.KB_WRITE)),
    current_user: dict = Depends(get_current_user),
):
    upload = await pg_get_upload_by_task_id(
        task_id, kb_name=kb, uploaded_by=current_user.get("id"),
        is_admin=current_user.get("is_admin", False),
    )
    if not upload:
        raise HTTPException(404, "Upload task not found")
    from raganything.services.upload_retry import cancel_retry
    if not await cancel_retry(task_id):
        raise HTTPException(409, "Upload retry is already running or terminal")
    from raganything.services.state_service import processing_tasks
    if task_id in processing_tasks:
        processing_tasks[task_id].update({
            "status": "failed",
            "retryable": False,
            "next_retry_at": None,
            "message": "Automatic retry cancelled",
        })
    return {"task_id": task_id, "status": "failed", "cancelled": True}


@router.delete("/upload/tasks/{task_id}")
async def delete_upload_task(
    task_id: str,
    kb: str = Depends(verify_kb_operate_access),
    _perm: None = Depends(require_permission(Permission.KB_WRITE)),
    current_user: dict = Depends(get_current_user),
):
    """Delete a queued task or start durable cancellation for unfinished work."""
    upload = await pg_get_upload_by_task_id(
        task_id,
        kb_name=kb,
        uploaded_by=current_user.get("id"),
        is_admin=current_user.get("is_admin", False),
    )
    if not upload:
        raise HTTPException(404, "上传任务不存在")
    upload_status = upload.get("status")
    if upload_status in {"processing", "retry_wait", "cancelling"}:
        cancellation = await cancel_inflight_upload(task_id, kb)
        if cancellation is None:
            raise HTTPException(409, "上传任务状态已变化，请刷新后重试")
        if cancellation.get("status") != "cancelling":
            raise HTTPException(409, "仅未完成的上传任务可删除")
        return JSONResponse(status_code=202, content={
            "task_id": task_id,
            "filename": upload.get("filename", ""),
            "status": "cancelling",
            "cancelled": True,
            "message": "正在停止处理，完成后将删除",
        })
    if upload_status != "queued":
        raise HTTPException(409, "仅未完成的上传任务可删除")

    deleted = await pg_update_upload_status_by_task_id(
        task_id,
        "deleted",
        kb_name=kb,
        expected_current_status="queued",
        error_message="",
    )
    if not deleted:
        raise HTTPException(409, "上传任务状态已变化，请刷新后重试")

    staged_file = Path(upload.get("file_path") or "")
    try:
        if staged_file.exists() and staged_file.is_file():
            staged_file.unlink()
    except OSError:
        lightrag_logger.warning("[UPLOAD-DELETE] staged file cleanup failed: %s", staged_file)

    _unregister_processing_file(kb, upload.get("file_hash", ""))
    await delete_task(task_id)
    await _delete_upload_settings_snapshot(task_id)
    await add_event(
        "upload_delete",
        task_id=task_id,
        file=upload.get("filename", ""),
        kb=kb,
        user_id=current_user.get("id", 0),
    )
    return {
        "task_id": task_id,
        "filename": upload.get("filename", ""),
        "status": "deleted",
        "message": "上传任务已删除",
    }


def _folder_upload_roots() -> list[str]:
    """Resolve allowed roots for POST /upload/folder.

    FOLDER_UPLOAD_ROOTS overrides the default whitelist (comma-separated).
    Defaults: the absolute path of ./uploads and WORKING_DIR.
    """
    raw = os.getenv("FOLDER_UPLOAD_ROOTS", "").strip()
    if raw:
        candidates = [part.strip() for part in raw.split(",") if part.strip()]
    else:
        candidates = [
            os.path.join(os.getcwd(), "uploads"),
            os.path.abspath(WORKING_DIR),
        ]
    roots: list[str] = []
    for candidate in candidates:
        real = os.path.realpath(candidate)
        if real and real not in roots:
            roots.append(real)
    return roots


def _is_path_within(path: str, root: str) -> bool:
    """True if realpath-normalized ``path`` equals or lies under ``root``."""
    try:
        return os.path.commonpath([os.path.realpath(path), os.path.realpath(root)]) == os.path.realpath(root)
    except ValueError:
        return False


@router.post("/upload/folder")
async def upload_folder(folder_path: str = QueryParam(...), kb: str = Depends(verify_kb_operate_access),
                         chunking_strategy: str = "", current_user: dict = Depends(get_current_user),
                         _perm: None = Depends(require_permission(Permission.KB_WRITE)),
                         enable_image: str = "", enable_table: str = "",
                         enable_equation: str = "", enable_video: str = ""):
    """批量处理文件夹（folder_path 必须位于白名单根目录内）"""
    await _ensure_vision_index_mutable(kb)
    # 目录白名单：realpath 归一化后必须位于 FOLDER_UPLOAD_ROOTS 任一根内
    if not any(_is_path_within(folder_path, root) for root in _folder_upload_roots()):
        raise HTTPException(403, "文件夹路径不在允许的上传根目录内")
    if not os.path.isdir(folder_path):
        raise HTTPException(400, "文件夹不存在")

    actual_strategy = _resolve_chunking_strategy(chunking_strategy)

    task_id = str(uuid.uuid4())
    try:
        ingestion = await _create_upload_settings_snapshot(
            task_id, int(current_user["id"]), kb=kb, chunking_strategy=actual_strategy,
            enable_image=enable_image, enable_table=enable_table,
            enable_equation=enable_equation, enable_video=enable_video,
        )
        actual_strategy = ingestion.chunking_strategy
        instance = await _get_snapshot_task_kb(task_id, kb)
        supported_extensions = {
            str(ext).lower()
            for ext in getattr(getattr(instance, "config", None), "supported_file_extensions", [])
        }
        folder_files = [
            str(path)
            for path in Path(folder_path).rglob("*")
            if path.is_file()
            and (not supported_extensions or path.suffix.lower() in supported_extensions)
        ]
        task_data = {
            "id": task_id, "file": folder_path, "status": "processing",
            "started_at": datetime.now(timezone.utc).isoformat(), "kb": kb, "user_id": current_user["id"],
        }
        await upsert_task_state(task_id, task_data)
        # 临时切换分块策略
        original_func = None
        try:
            from raganything.services.user_settings import run_ingestion_with_quota
            from raganything.services.kb_mutation import run_kb_mutation_with_lease
            from raganything.services.kb_corpus_revision import run_corpus_mutation
            await run_ingestion_with_quota(
                task_id,
                lambda: run_kb_mutation_with_lease(
                    kb,
                    task_id,
                    lambda: run_corpus_mutation(
                        kb,
                        task_id,
                        "folder",
                        lambda: instance.process_folder_complete(
                            folder_path,
                            output_dir="./output",
                            recursive=True,
                            chunking_strategy=actual_strategy,
                        ),
                    ),
                    mutation_kind="folder",
                ),
            )
            tag_warnings = await _settle_in_process_upload(
                kb, folder_files, current_user["id"],
            )
            warning = "; ".join(tag_warnings)
            outcome = "degraded" if warning else ""
            await complete_task(task_id, outcome=outcome, warning=warning)
        except Exception as e:
            await upsert_task_state(task_id, {
                "id": task_id, "status": "failed", "error": str(e),
                "kb": kb, "file": folder_path, "user_id": current_user["id"],
            })
            raise HTTPException(500, str(e))
        return {
            "task_id": task_id,
            "folder": folder_path,
            "status": "degraded" if tag_warnings else "completed",
            "warning": "; ".join(tag_warnings),
            "chunking_strategy": actual_strategy,
        }
    finally:
        if 'instance' in locals():
            await instance.finalize_storages()


@router.post("/upload/content")
async def upload_content(req: PasteContentRequest, kb: str = Depends(verify_kb_operate_access),
                          current_user: dict = Depends(get_current_user),
                          _perm: None = Depends(require_permission(Permission.KB_WRITE)),
                          chunking_strategy: str = "",
                          enable_image: str = "", enable_table: str = "",
                          enable_equation: str = "", enable_video: str = ""):
    """直接粘贴内容入库"""
    await _ensure_vision_index_mutable(kb)
    actual_strategy = _resolve_chunking_strategy(chunking_strategy)
    task_id = str(uuid.uuid4())
    try:
        ingestion = await _create_upload_settings_snapshot(
            task_id, int(current_user["id"]), kb=kb, chunking_strategy=actual_strategy,
            enable_image=enable_image, enable_table=enable_table,
            enable_equation=enable_equation, enable_video=enable_video,
        )
        actual_strategy = ingestion.chunking_strategy
        instance = await _get_snapshot_task_kb(task_id, kb)
        content_list = [{"type": "text", "text": req.content, "page_idx": 0}]
        original_func = None
        try:
            from raganything.services.user_settings import run_ingestion_with_quota
            from raganything.services.kb_mutation import run_kb_mutation_with_lease
            from raganything.services.kb_corpus_revision import run_corpus_mutation
            await run_ingestion_with_quota(
                task_id,
                lambda: run_kb_mutation_with_lease(
                    kb,
                    task_id,
                    lambda: run_corpus_mutation(
                        kb,
                        task_id,
                        "content",
                        lambda: instance.insert_content_list(
                            content_list,
                            file_path=req.title or "pasted_content",
                            chunking_strategy=actual_strategy,
                        ),
                    ),
                    mutation_kind="content",
                ),
            )
            return {"status": "completed", "title": req.title or "pasted_content",
                    "chunking_strategy": actual_strategy}
        except Exception as e:
            raise HTTPException(500, str(e))
    finally:
        if 'instance' in locals():
            await instance.finalize_storages()


@router.post("/upload/url")
async def upload_from_url(url: str = QueryParam(...), kb: str = Depends(verify_kb_operate_access),
                         current_user: dict = Depends(get_current_user),
                         _perm: None = Depends(require_permission(Permission.KB_WRITE)),
                         chunking_strategy: str = "",
                         enable_image: str = "", enable_table: str = "",
                         enable_equation: str = "", enable_video: str = ""):
    """从 URL 下载文档并入库"""
    await _ensure_vision_index_mutable(kb)
    if not url.startswith("http"):
        raise HTTPException(400, "无效 URL")

    actual_strategy = _resolve_chunking_strategy(chunking_strategy)

    task_id = str(uuid.uuid4())
    try:
        ingestion = await _create_upload_settings_snapshot(
            task_id, int(current_user["id"]), kb=kb, chunking_strategy=actual_strategy,
            enable_image=enable_image, enable_table=enable_table,
            enable_equation=enable_equation, enable_video=enable_video,
        )
        actual_strategy = ingestion.chunking_strategy
        await add_event("url_download_start", url=url, task_id=task_id, user_id=current_user.get("id", 0))
        async with httpx.AsyncClient(timeout=120, follow_redirects=True) as client:
            resp = await client.get(url)
            if resp.status_code != 200:
                raise HTTPException(400, f"下载失败: HTTP {resp.status_code}")
            content = resp.content
            # 从 URL 提取文件名
            fname = url.split("/")[-1].split("?")[0] or "downloaded_file"
            if "." not in fname:
                ct = resp.headers.get("content-type", "").lower()
                # Map common MIME types to file extensions
                _mime_map = {
                    "application/pdf": ".pdf",
                    "application/msword": ".doc",
                    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": ".docx",
                    "application/vnd.ms-powerpoint": ".ppt",
                    "application/vnd.openxmlformats-officedocument.presentationml.presentation": ".pptx",
                    "application/vnd.ms-excel": ".xls",
                    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": ".xlsx",
                    "text/html": ".html",
                    "text/plain": ".txt",
                    "text/markdown": ".md",
                    "image/png": ".png",
                    "image/jpeg": ".jpg",
                    "image/gif": ".gif",
                    "image/webp": ".webp",
                }
                matched = False
                for mime, ext in _mime_map.items():
                    if mime in ct:
                        fname += ext
                        matched = True
                        break
                if not matched:
                    fname += ".bin"

        upload_dir = Path("./uploads")
        upload_dir.mkdir(exist_ok=True)
        fp = upload_dir / fname
        fp.write_bytes(content)
        await add_event("url_download_complete", file=fname, task_id=task_id, size=len(content), user_id=current_user.get("id", 0))

        instance = await _get_snapshot_task_kb(task_id, kb)
        original_func = None
        try:
            from raganything.services.user_settings import run_ingestion_with_quota
            from raganything.services.kb_mutation import run_kb_mutation_with_lease
            from raganything.services.kb_corpus_revision import run_corpus_mutation
            await run_ingestion_with_quota(
                task_id,
                lambda: run_kb_mutation_with_lease(
                    kb,
                    task_id,
                    lambda: run_corpus_mutation(
                        kb,
                        task_id,
                        "url",
                        lambda: instance.process_document_complete(
                            str(fp.absolute()),
                            output_dir="./output",
                            chunking_strategy=actual_strategy,
                            odl_owner_kb=kb,
                        ),
                    ),
                    mutation_kind="url",
                ),
            )
            tag_warnings = await _settle_in_process_upload(
                kb, [fname], current_user.get("id", 0),
            )
        finally:
            pass
        await add_event("url_process_complete", file=fname, task_id=task_id, user_id=current_user.get("id", 0))
        return {
            "status": "degraded" if tag_warnings else "completed",
            "warning": "; ".join(tag_warnings),
            "filename": fname,
            "size": len(content),
            "chunking_strategy": actual_strategy,
        }
    except HTTPException:
        raise
    except Exception as e:
        await add_event("url_error", url=url, error=str(e), user_id=current_user.get("id", 0))
        raise HTTPException(500, str(e))
    finally:
        if 'instance' in locals():
            await instance.finalize_storages()


# ── Knowledge / Document handlers ──────────────────────

# Compiled regex for stripping secrets.token_hex(4) prefix (8 hex chars + "_")
_HASH_PREFIX_RE = re.compile(r'^(?:[0-9a-f]{8}|[0-9a-f]{32})_(.+)$')


def _strip_hash_prefix(filename: str) -> str:
    """Strip legacy hash or task ID prefixes from staged upload filenames."""
    return display_document_name(filename)


def _resolve_chunking_strategy(requested_strategy: str) -> str:
    """Keep only an explicit valid one-upload override.

    An empty value must reach settings resolution unchanged so KB and personal
    defaults can determine the snapshot's strategy.
    """
    requested = (requested_strategy or "").strip()
    if requested in CHUNKING_STRATEGY_META:
        return requested
    return ""


async def _settle_in_process_upload(
    kb_name: str,
    filenames: list[str],
    user_id: int,
) -> list[str]:
    """Wait for this request's documents and tags without touching shared tasks."""
    timeout = float(os.getenv("UPLOAD_PROCESS_SETTLE_TIMEOUT", "1800"))
    loop = asyncio.get_running_loop()
    warnings: list[str] = []
    for filename in filenames:
        deadline = loop.time() + max(0.0, timeout)
        doc_id = None
        status_info = None
        while True:
            doc_id = await _resolve_uploaded_document_id(
                kb_name, os.path.basename(filename),
            )
            if doc_id:
                status_info = (await _load_doc_status_json(kb_name)).get(doc_id)
            if isinstance(status_info, dict):
                raw_status = str(status_info.get("status") or "").lower()
                if raw_status == "failed":
                    warnings.append(
                        str(status_info.get("error_msg") or "多模态处理失败")
                    )
                    break
                if (
                    raw_status in {"processed", "completed"}
                    and is_multimodal_processed(status_info)
                ):
                    break
            if loop.time() >= deadline:
                raise TimeoutError(f"文档后台处理未完成: {filename}")
            await asyncio.sleep(0.5)
        if not doc_id or not isinstance(status_info, dict):
            raise RuntimeError(f"无法确认文档处理状态: {filename}")
        if str(status_info.get("status") or "").lower() == "failed":
            continue
        await enqueue_document_tagging(
            kb_name, doc_id, filename=os.path.basename(filename), user_id=user_id,
        )
        tag_health = await wait_for_document_tagging(kb_name, doc_id)
        if tag_health.get("tag_status") in {"failed", "disabled"}:
            warnings.append(
                tag_health.get("tag_error_message")
                or f"自动标签未完成: {filename}"
            )
    return warnings


def _normalized_upload_filename(filename: str) -> str:
    return os.path.normcase(_strip_hash_prefix(os.path.basename(str(filename or ""))))


async def _document_exists_for_upload_filename(kb: str, filename: str) -> bool:
    """Keep real duplicate documents protected when recovering legacy upload rows."""
    target = _normalized_upload_filename(filename)
    if not target:
        return False
    try:
        documents = await _load_doc_status_json(kb)
    except Exception:
        return True
    return any(
        _normalized_upload_filename(info.get("file_path", "")) == target
        for info in documents.values()
        if isinstance(info, dict)
    )


async def _register_upload_with_stale_recovery(
    *,
    filename: str,
    file_path: str,
    file_hash: str,
    file_size: int,
    kb_name: str,
    uploaded_by: int,
    task_id: str,
) -> dict[str, Any] | None:
    """Register an upload and reclaim legacy terminal metadata only when safe."""
    registered = await pg_register_upload(
        filename=filename,
        file_path=file_path,
        file_hash=file_hash,
        file_size=file_size,
        kb_name=kb_name,
        uploaded_by=uploaded_by,
        task_id=task_id,
        status="queued",
    )
    if registered is not None:
        return registered
    if await _document_exists_for_upload_filename(kb_name, filename):
        return None
    if not await pg_mark_upload_reusable(file_hash, kb_name):
        return None
    return await pg_register_upload(
        filename=filename,
        file_path=file_path,
        file_hash=file_hash,
        file_size=file_size,
        kb_name=kb_name,
        uploaded_by=uploaded_by,
        task_id=task_id,
        status="queued",
    )


_GRAPH_READY_STATUSES = {"ready", "completed", "processed", "complete"}


def _document_health_contract(info: dict[str, Any]) -> dict[str, Any]:
    """Derive the public document health without changing LightRAG's status."""
    metadata = info.get("metadata") or {}
    metadata = metadata if isinstance(metadata, dict) else {}
    raw_status = str(info.get("status") or "?")
    graph_status = str(metadata.get("graph_status") or "")
    content_ready = metadata.get("content_ready") is True
    try:
        chunk_count = int(info.get("chunks_count") or 0)
    except (TypeError, ValueError):
        chunk_count = 0

    is_degraded = (
        raw_status == "failed"
        and content_ready
        and chunk_count > 0
        and graph_status.lower() not in _GRAPH_READY_STATUSES
    )
    multimodal_pending = metadata.get("multimodal_processed") is False
    if multimodal_pending and raw_status in {"processed", "completed"}:
        health = "processing"
        status = "handling"
    elif is_degraded:
        health = "degraded"
        status = "degraded"
    elif raw_status == "failed":
        health = "failed"
        status = raw_status
    elif raw_status in {"processed", "completed"}:
        health = "healthy"
        status = raw_status
    else:
        health = raw_status
        status = raw_status

    retryable_value = metadata.get("retryable")
    retryable = (
        raw_status == "failed"
        if retryable_value is None
        else retryable_value is True
    )
    return {
        "status": status,
        "raw_status": raw_status,
        "health": health,
        "content_ready": content_ready,
        "graph_status": graph_status,
        "failure_stage": str(metadata.get("failure_stage") or ""),
        "retryable": retryable,
        "error_message": str(
            metadata.get("last_error") or info.get("error_msg") or ""
        ),
    }


async def _document_tag_health_contract(
    kb: str, doc_ids: list[str]
) -> dict[str, dict[str, Any]]:
    try:
        from raganything.services.document_tagging import get_document_tag_health

        return await get_document_tag_health(kb, doc_ids)
    except Exception:
        lightrag_logger.warning(
            "Unable to load document tag health: kb=%s", kb, exc_info=True
        )
        return {
            doc_id: {
                "tag_status": "unavailable",
                "tag_raw_status": "unavailable",
                "tagged_chunks": 0,
                "eligible_tag_chunks": 0,
                "tag_not_applicable_chunks": 0,
                "unique_auto_tag_count": 0,
                "auto_tag_assignment_count": 0,
                "avg_auto_tags_per_tagged_chunk": 0.0,
                "tag_error_message": "标签状态暂时不可用",
                "tag_retryable": True,
            }
            for doc_id in doc_ids
        }


def _apply_enrichment_status_overlay(document: dict[str, Any]) -> dict[str, Any]:
    """Prevent public completion while tags are pending or terminally failed."""
    result = dict(document)
    tag_status = str(result.get("tag_status") or "")
    if tag_status in {"pending", "running", "retry_wait"}:
        if result.get("status") in {"processed", "completed"}:
            result["status"] = "handling"
            if "health" in result:
                result["health"] = "processing"
    elif tag_status == "failed" and result.get("status") in {"processed", "completed"}:
        result["status"] = "degraded"
        if "health" in result:
            result["health"] = "degraded"
        if not result.get("error_message"):
            result["error_message"] = str(result.get("tag_error_message") or "")
    return result


async def _get_tags_for_chunks_best_effort(
    kb: str, doc_id: str, chunk_ids: list[str]
) -> dict[str, list[dict[str, Any]]]:
    try:
        return await get_tags_for_chunks(kb, doc_id, chunk_ids)
    except Exception:
        lightrag_logger.warning(
            "Unable to load chunk tags: kb=%s doc=%s", kb, doc_id,
            exc_info=True,
        )
        return {chunk_id: [] for chunk_id in chunk_ids}


def _document_timestamp(value: Any) -> str:
    """Return a stable, JSON-safe timestamp for document summaries."""
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    return value if isinstance(value, str) else ""


def _document_upload_task_id(info: dict[str, Any]) -> str | None:
    """Return durable upload provenance without falling back to filenames."""
    metadata = info.get("metadata") or {}
    metadata_task_id = metadata.get("task_id") if isinstance(metadata, dict) else None
    for task_id in (info.get("track_id"), info.get("task_id"), metadata_task_id):
        if task_id:
            return str(task_id)
    return None


@router.get("/knowledge/documents")
async def list_documents(kb: str = Depends(verify_kb_access), current_user: dict = Depends(get_current_user)):
    """列出所有文档及其状态（含处理中的任务）"""
    try:
        # Clean up completed/failed tasks before building the response
        await cleanup_completed_tasks()

        uploads, _total = await pg_list_uploads(
            kb_name=kb,
            uploaded_by=current_user.get("id"),
            is_admin=current_user.get("is_admin", False),
            limit=200,
            offset=0,
            exclude_statuses=["deleted"],
        )
        active_tasks = {
            str(task.get("id") or task.get("task_id")): task
            for task in await get_all_tasks()
            if task.get("kb", task.get("kb_name", "")) == kb
            and (task.get("id") or task.get("task_id"))
        }
        upload_task_statuses: dict[str, str] = {}
        for upload in uploads:
            task_id = str(upload.get("task_id") or "")
            if not task_id:
                continue
            durable_status = str(upload.get("status") or "queued")
            runtime_task = active_tasks.get(task_id, {})
            upload_task_statuses[task_id] = (
                durable_status
                if durable_status in {"cancelling", "deleted"}
                else str(runtime_task.get("status") or durable_status)
            )

        data = await _load_doc_status_summaries(kb)

        # Deduplicate doc_status entries by original filename: keep only the
        # most recently updated entry per stripped filename.
        best_doc: dict[str, tuple[str, dict]] = {}  # dedupe key → (doc_id, info)
        for doc_id, info in data.items():
            if not isinstance(info, dict):
                continue  # skip non-dict entries (corrupted data)
            orig = _strip_hash_prefix(info.get("file_path", "") or "")
            # A missing filename is not proof that two document-status rows
            # describe the same document.  Preserve every such row by its ID;
            # valid filenames retain the existing retry/re-upload dedupe rule.
            dedupe_key = orig or f"__missing_doc__:{doc_id}"
            if dedupe_key not in best_doc or _document_timestamp(
                info.get("updated_at")
            ) > _document_timestamp(best_doc[dedupe_key][1].get("updated_at")):
                best_doc[dedupe_key] = (doc_id, info)

        tag_health_by_doc = await _document_tag_health_contract(
            kb, [doc_id for doc_id, _info in best_doc.values()]
        )

        docs = []
        seen_files = set()
        for dedupe_key, (doc_id, info) in best_doc.items():
            orig_name = _strip_hash_prefix(info.get("file_path", "") or "")
            # Check if there's a matching processing task with phase info
            doc_phase = ""
            for tid, task in processing_tasks.items():
                if not isinstance(task, dict):
                    continue  # skip non-dict entries
                task_file = _strip_hash_prefix(task.get("file", "") or "")
                if task_file == orig_name and task.get("kb", "") == kb:
                    doc_phase = task.get("phase", "") or ""
                    break
            metadata = info.get("metadata") or {}
            upload_task_id = _document_upload_task_id(info)
            upload_task_status = upload_task_statuses.get(upload_task_id or "")
            stored_strategy = (
                metadata.get("chunking_strategy")
                if isinstance(metadata, dict)
                else None
            )
            health_fields = _document_health_contract(info)
            tag_health = tag_health_by_doc.get(doc_id, {
                "tag_status": "pending",
                "tag_raw_status": "missing",
                "tagged_chunks": 0,
                "eligible_tag_chunks": 0,
                "tag_not_applicable_chunks": 0,
                "unique_auto_tag_count": 0,
                "auto_tag_assignment_count": 0,
                "avg_auto_tags_per_tagged_chunk": 0.0,
                "tag_error_message": "",
                "tag_retryable": True,
            })
            completion_fields = _apply_enrichment_status_overlay({
                **health_fields,
                **tag_health,
            })
            if upload_task_status == "cancelling":
                completion_fields = {
                    **completion_fields,
                    "status": "cancelling",
                    "raw_status": "cancelling",
                    "health": "cancelling",
                }
            docs.append({
                "id": (doc_id or "")[:16],
                "full_id": doc_id or "",
                "file": _strip_hash_prefix((info.get("file_path") or "?")),
                **completion_fields,
                "chunks": info.get("chunks_count") or 0,
                "length": info.get("content_length") or 0,
                "created": _document_timestamp(info.get("created_at")),
                "updated": _document_timestamp(info.get("updated_at")),
                "phase": doc_phase,
                "upload_task_id": upload_task_id,
                "upload_task_status": upload_task_status,
                "can_cancel_upload": upload_task_status in {"queued", "processing", "retry_wait"},
                "chunking_strategy": stored_strategy if isinstance(stored_strategy, str) else None,
            })
            if orig_name:
                seen_files.add(orig_name)

        # 合并处理中的任务（还未写入 doc_status），仅限当前 KB
        for tid, task in processing_tasks.items():
            if not isinstance(task, dict):
                continue  # skip non-dict entries
            if task.get("kb", "") != kb:
                continue
            fn = task.get("file") or ""
            if fn and _strip_hash_prefix(fn) not in seen_files:
                task_id = str(tid)
                upload_task_status = upload_task_statuses.get(task_id)
                docs.append({
                    "id": tid or "",
                    "full_id": tid or "",
                    "file": display_document_name(fn),
                    "status": upload_task_status or task.get("status") or "processing",
                    "raw_status": upload_task_status or task.get("status") or "processing",
                    "health": upload_task_status or task.get("status") or "processing",
                    "content_ready": False,
                    "graph_status": "",
                    "failure_stage": "",
                    "retryable": False,
                    "error_message": str(
                        task.get("error_message") or task.get("error") or ""
                    ),
                    "tag_status": "not_started",
                    "tag_raw_status": "missing",
                    "tagged_chunks": 0,
                    "eligible_tag_chunks": 0,
                    "tag_not_applicable_chunks": 0,
                    "unique_auto_tag_count": 0,
                    "auto_tag_assignment_count": 0,
                    "avg_auto_tags_per_tagged_chunk": 0.0,
                    "tag_error_message": "",
                    "tag_retryable": False,
                    "chunks": 0,
                    "length": 0,
                    "created": _document_timestamp(task.get("started_at")),
                    "updated": _document_timestamp(task.get("started_at")),
                    "phase": task.get("phase") or "",
                    "upload_task_id": task_id,
                    "upload_task_status": upload_task_status,
                    "can_cancel_upload": upload_task_status in {"queued", "processing", "retry_wait"},
                    "chunking_strategy": (
                        task.get("chunking_strategy")
                        if isinstance(task.get("chunking_strategy"), str)
                        else None
                    ),
                })

        # Sort with None-safe key: treat None/empty as empty string
        def _sort_key(d):
            return d.get("updated") or ""
        return {"documents": sorted(docs, key=_sort_key, reverse=True), "total": len(docs)}
    except Exception as e:
        lightrag_logger.error(f"[list_documents] kb={kb} error: {e}", exc_info=True)
        raise HTTPException(500, str(e))


def _multimodal_chunk_metadata(status_info: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Read application-owned multimodal metadata from a document status row."""
    metadata = status_info.get("metadata") or {}
    if not isinstance(metadata, dict):
        return {}
    chunks = metadata.get("multimodal_chunks") or {}
    if not isinstance(chunks, dict):
        return {}
    return {
        str(chunk_id): value
        for chunk_id, value in chunks.items()
        if isinstance(value, dict)
    }


def _infer_multimodal_fields(
    chunk_data: dict[str, Any], metadata: dict[str, Any] | None = None
) -> dict[str, Any]:
    """Restore multimodal fields lost by legacy PGKV text-chunk storage."""
    fields = dict(metadata or {})
    content = str(chunk_data.get("content") or "")
    normalized = content.lower()
    inferred_type = fields.get("original_type")
    if not inferred_type:
        if "image content analysis:" in normalized:
            inferred_type = "image"
        elif "table analysis:" in normalized:
            inferred_type = "table"
        elif "mathematical equation analysis:" in normalized:
            inferred_type = "equation"
        elif "video content analysis:" in normalized:
            inferred_type = "video"
    if inferred_type:
        fields["original_type"] = inferred_type
        fields["is_multimodal"] = True
        fields.setdefault("modal_entity_name", f"{inferred_type} content")
    return fields


_chunk_document_locks: dict[tuple[str, str], asyncio.Lock] = {}
_chunk_document_locks_guard = asyncio.Lock()
_chunk_bm25_locks: dict[str, asyncio.Lock] = {}
_chunk_bm25_locks_guard = asyncio.Lock()
_document_delete_locks: dict[str, asyncio.Lock] = {}
_document_delete_locks_guard = asyncio.Lock()


class ChunkContentUpdate(BaseModel):
    content: str


class ChunkTagsUpdate(BaseModel):
    tag_names: list[str] = Field(default_factory=list)


async def _get_chunk_document_lock(kb: str, doc_id: str) -> asyncio.Lock:
    async with _chunk_document_locks_guard:
        return _chunk_document_locks.setdefault((kb, doc_id), asyncio.Lock())


async def _get_document_delete_lock(kb: str) -> asyncio.Lock:
    """Serialize LightRAG's KB-wide deletion pipeline within this app."""
    async with _document_delete_locks_guard:
        return _document_delete_locks.setdefault(kb, asyncio.Lock())


@asynccontextmanager
async def _chunk_document_lock_scope(
    kb: str,
    doc_id: str,
    lg: Any,
    *,
    acquire_pg_lock: bool = True,
):
    """Serialize mutations locally and across workers for PG-backed stores."""
    local_lock = await _get_chunk_document_lock(kb, doc_id)
    async with local_lock:
        pool = None
        connection = None
        is_pg_store = lg.doc_status.__class__.__module__.startswith(
            "lightrag.kg.postgres_impl"
        )
        if is_pg_store and acquire_pg_lock:
            lock_key = document_mutation_lock_key(kb, doc_id)
            try:
                from raganything.services.pg_state_repo import get_pg_pool

                pool = get_pg_pool()
                connection = await pool.acquire()
                await connection.execute("SELECT pg_advisory_lock($1)", lock_key)
            except Exception as exc:
                if pool is not None and connection is not None:
                    await pool.release(connection)
                raise HTTPException(
                    503, "Unable to acquire the document mutation lock"
                ) from exc
        try:
            yield
        finally:
            if pool is not None and connection is not None:
                try:
                    await connection.execute("SELECT pg_advisory_unlock($1)", lock_key)
                finally:
                    await pool.release(connection)


async def _delete_lightrag_document(lg: Any, kb: str, doc_id: str):
    """Run one document deletion through LightRAG's KB-wide pipeline at a time."""
    delete_lock = await _get_document_delete_lock(kb)
    async with delete_lock:
        async with _chunk_document_lock_scope(kb, doc_id, lg):
            return await lg.adelete_by_doc_id(doc_id, delete_llm_cache=True)


def _resolve_chunk_document(
    all_status: dict[str, Any], requested_id: str
) -> tuple[str, dict[str, Any]]:
    if requested_id in all_status and isinstance(all_status[requested_id], dict):
        return requested_id, all_status[requested_id]
    matches = [
        (key, value)
        for key, value in all_status.items()
        if str(key).startswith(requested_id) and isinstance(value, dict)
    ]
    if len(matches) == 1:
        return matches[0]
    raise HTTPException(404, f"Document {requested_id} does not exist")


def _stored_chunk_id(chunk: dict[str, Any]) -> str:
    return str(chunk.get("chunk_id") or chunk.get("id") or "")


async def _load_document_chunk_records(
    lg: Any, doc_id: str, status_info: dict[str, Any], kb: str
) -> list[dict[str, Any]]:
    ids = [str(value) for value in status_info.get("chunks_list", []) if value]
    records = await lg.text_chunks.get_by_ids(ids) if ids else []
    if not records and int(status_info.get("chunks_count") or 0) > 0:
        records = await _query_chunks_by_doc_id(lg, doc_id, kb)
    result = [dict(value) for value in (records or []) if isinstance(value, dict)]
    result.sort(key=lambda value: int(value.get("chunk_order_index") or 0))
    return result


def _controlled_odl_chunk_media(
    *,
    status_info: dict[str, Any] | None,
    kb: str | None,
    chunk_id: str,
) -> dict[str, Any] | None:
    """Return a path-free media payload for a catalog-bound ODL image chunk.

    The generic chunk endpoints predate the ODL delivery contract and still
    support non-ODL media paths.  An ODL chunk with an audited catalog record
    must not use that compatibility representation: browser-visible data is
    restricted to the same controlled URL/data-URL boundary as Agent SSE.
    """
    if not status_info or not kb or not chunk_id:
        return None
    metadata = status_info.get("metadata") or {}
    if not isinstance(metadata, dict):
        return None
    catalog = metadata.get("odl_media_catalog")
    if not isinstance(catalog, list):
        return None
    from raganything.services.odl_media_delivery import (
        catalog_media_payload,
        resolve_catalog_media,
    )

    matches = [
        entry for entry in catalog
        if isinstance(entry, dict) and entry.get("chunk_id") == chunk_id
    ]
    if len(matches) != 1:
        return None
    media_id = matches[0].get("media_id")
    if not isinstance(media_id, str):
        return None
    resolved = resolve_catalog_media(catalog, kb_name=kb, media_id=media_id)
    if resolved is None:
        return None
    payload = catalog_media_payload(catalog, kb_name=kb, path=str(resolved.path))
    if payload is None or payload.get("media_id") != resolved.media_id:
        return None
    return {
        "media_id": resolved.media_id,
        "media_kb": kb,
        "media_url": payload["url"],
        "media_available": True,
    }


def _serialize_document_chunk(
    chunk_data: dict[str, Any],
    multimodal_metadata: dict[str, dict[str, Any]],
    *,
    status_info: dict[str, Any] | None = None,
    kb: str | None = None,
) -> dict[str, Any]:
    chunk_id = _stored_chunk_id(chunk_data)
    fields = _infer_multimodal_fields(chunk_data, multimodal_metadata.get(chunk_id))
    media_path = fields.get("media_path") or _extract_media_path(chunk_data)
    media_available = bool(media_path and Path(media_path).exists())
    media_url = None
    media_id = None
    media_kb = None
    metadata = status_info.get("metadata") if isinstance(status_info, dict) else None
    metadata = metadata if isinstance(metadata, dict) else {}
    is_odl_document = any(
        key in metadata
        for key in ("odl_media_catalog", "image_media_counts", "provenance_ref")
    )
    controlled_media = _controlled_odl_chunk_media(
        status_info=status_info, kb=kb, chunk_id=chunk_id,
    )
    if controlled_media is not None:
        # Do not leak the local ODL parser artifact path through chunk detail
        # responses.  The catalog has revalidated the media before exposure.
        media_path = None
        media_available = controlled_media["media_available"]
        media_url = controlled_media["media_url"]
        media_id = controlled_media["media_id"]
        media_kb = controlled_media["media_kb"]
    elif is_odl_document:
        # ODL parser paths are not delivery authority. Missing catalog ownership
        # must fail closed rather than falling back to a local path.
        media_path = None
        media_available = False
    elif media_available:
        base_url = os.environ.get("RAGANYTHING_PUBLIC_ASSET_BASE_URL", "").strip()
        strip_prefix = os.environ.get("RAGANYTHING_PUBLIC_ASSET_STRIP_PREFIX", "").strip()
        if base_url and strip_prefix:
            from raganything.asset_urls import public_url_for_local_path

            media_url = public_url_for_local_path(
                media_path, base_url=base_url, strip_prefix=strip_prefix
            )
    return {
        "chunk_id": chunk_id,
        "content": chunk_data.get("content", ""),
        "tokens": int(chunk_data.get("tokens") or 0),
        "chunk_order_index": int(chunk_data.get("chunk_order_index") or 0),
        "file_path": chunk_data.get("file_path", ""),
        "is_multimodal": bool(chunk_data.get("is_multimodal") or fields.get("is_multimodal")),
        "original_type": chunk_data.get("original_type") or fields.get("original_type"),
        "modal_entity_name": chunk_data.get("modal_entity_name") or fields.get("modal_entity_name"),
        "page_idx": chunk_data.get("page_idx")
        if chunk_data.get("page_idx") is not None else fields.get("page_idx"),
        "media_id": media_id,
        "media_kb": media_kb,
        "media_path": media_path,
        "media_url": media_url,
        "media_available": media_available,
    }


async def _attach_video_segment_metadata(kb: str, chunks: list[dict[str, Any]]) -> None:
    """Attach authorized video timing/media metadata to serialized chunk DTOs."""
    try:
        from raganything.services.video_segments import (
            controlled_video_media_url,
            list_video_segments_for_chunks,
        )
    except Exception:
        return
    try:
        segments = await list_video_segments_for_chunks(
            kb, [chunk["chunk_id"] for chunk in chunks if chunk.get("chunk_id")]
        )
    except Exception:
        return
    for chunk in chunks:
        segment = segments.get(str(chunk.get("chunk_id")))
        if not segment:
            continue
        media_id = str(segment["media_id"])
        chunk["video_segment"] = {
            "segment_id": str(segment["segment_id"]),
            "start_ms": int(segment["start_ms"]),
            "end_ms": int(segment["end_ms"]),
        }
        chunk["media_id"] = media_id
        chunk["media_kb"] = kb
        chunk["media_url"] = controlled_video_media_url(media_id, kb)


def _chunk_document_payload(doc_id: str, status_info: dict[str, Any]) -> dict[str, Any]:
    metadata = status_info.get("metadata") or {}
    metadata = metadata if isinstance(metadata, dict) else {}
    return {
        "id": doc_id,
        "file": _strip_hash_prefix(str(status_info.get("file_path") or "")),
        "status": status_info.get("status") or "",
        "content_summary": status_info.get("content_summary") or "",
        "content_length": int(status_info.get("content_length") or 0),
        "chunking_strategy": metadata.get("chunking_strategy"),
        "created": status_info.get("created_at") or "",
        "updated": status_info.get("updated_at") or "",
    }


def _chunk_graph_sync_state(status_info: dict[str, Any]) -> str:
    metadata = status_info.get("metadata") or {}
    return "stale" if isinstance(metadata, dict) and metadata.get("graph_sync_state") == "stale" else "synced"


def _chunk_document_is_processing(
    doc_id: str, kb: str, status_info: dict[str, Any]
) -> bool:
    if str(status_info.get("status") or "").lower() in {
        "queued", "pending", "ready", "handling", "processing",
        "preprocessing", "indexing",
    }:
        return True
    file_name = _strip_hash_prefix(str(status_info.get("file_path") or ""))
    for task_id, task in processing_tasks.items():
        if not isinstance(task, dict) or task.get("kb") != kb:
            continue
        if str(task.get("status") or "").lower() in {"completed", "failed"}:
            continue
        task_file = _strip_hash_prefix(str(task.get("file") or ""))
        if task_id == doc_id or task.get("doc_id") == doc_id or task_file == file_name:
            return True
    return False


async def _chunk_store_get(store: Any, item_id: str) -> dict[str, Any] | None:
    if hasattr(store, "get_by_id"):
        value = await store.get_by_id(item_id)
    else:
        values = await store.get_by_ids([item_id])
        value = values[0] if values else None
    return dict(value) if isinstance(value, dict) else None


def _is_pg_vector_store(store: Any) -> bool:
    return store.__class__.__module__.startswith("lightrag.kg.postgres_impl")


def _validated_pg_table_name(store: Any) -> str:
    table_name = str(getattr(store, "table_name", "") or "")
    if not table_name and hasattr(store, "namespace"):
        from lightrag.kg.postgres_impl import namespace_to_table_name

        table_name = str(namespace_to_table_name(store.namespace) or "")
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", table_name):
        raise RuntimeError("Invalid PG vector table name")
    return table_name


async def _chunk_text_get(store: Any, item_id: str) -> dict[str, Any] | None:
    if not store.__class__.__module__.startswith("lightrag.kg.postgres_impl"):
        return await _chunk_store_get(store, item_id)
    table_name = _validated_pg_table_name(store)
    result = await store.db.query(
        f"SELECT id, content FROM {table_name} WHERE workspace=$1 AND id=$2",
        [store.workspace, item_id],
    )
    return dict(result) if result else None


async def _delete_chunk_text(store: Any, item_ids: list[str]) -> None:
    if store.__class__.__module__.startswith("lightrag.kg.postgres_impl"):
        table_name = _validated_pg_table_name(store)
        await store.db.execute(
            f"DELETE FROM {table_name} WHERE workspace=$1 AND id = ANY($2)",
            {"workspace": store.workspace, "ids": item_ids},
        )
    else:
        await store.delete(item_ids)
    for item_id in item_ids:
        if await _chunk_text_get(store, item_id):
            raise RuntimeError(f"Text chunk {item_id} still exists after deletion")


async def _chunk_vector_get(store: Any, item_id: str) -> dict[str, Any] | None:
    """Read PG vectors directly so database errors cannot look like absence."""
    if not _is_pg_vector_store(store):
        return await _chunk_store_get(store, item_id)
    table_name = _validated_pg_table_name(store)
    result = await store.db.query(
        f"SELECT id FROM {table_name} WHERE workspace=$1 AND id=$2",
        [store.workspace, item_id],
    )
    return {"id": item_id} if result else None


async def _delete_chunk_vectors(store: Any, item_ids: list[str]) -> None:
    """Delete and verify vectors without PGVectorStorage swallowing errors."""
    if _is_pg_vector_store(store):
        table_name = _validated_pg_table_name(store)
        await store.db.execute(
            f"DELETE FROM {table_name} WHERE workspace=$1 AND id = ANY($2)",
            {"workspace": store.workspace, "ids": item_ids},
        )
    else:
        await store.delete(item_ids)
    for item_id in item_ids:
        if await _chunk_vector_get(store, item_id):
            raise RuntimeError(f"Chunk vector {item_id} still exists after deletion")


async def _flush_chunk_mutation_stores(lg: Any) -> None:
    for store in (lg.text_chunks, lg.chunks_vdb, lg.doc_status):
        callback = getattr(store, "index_done_callback", None)
        if callback:
            await callback()


def _edited_chunk_tokens(lg: Any, content: str) -> int:
    tokenizer = getattr(lg, "tokenizer", None)
    if tokenizer is not None and hasattr(tokenizer, "encode"):
        return len(tokenizer.encode(content))
    return max(1, len(content.split()))


async def _all_kb_chunk_records(instance: Any, kb: str) -> list[dict[str, Any]]:
    """Load the complete KB corpus because BM25 rebuild replaces the whole index."""
    all_status = await _load_doc_status_json(kb)
    chunks_by_id: dict[str, dict[str, Any]] = {}
    for doc_id, status_info in (all_status or {}).items():
        if not isinstance(status_info, dict):
            continue
        records = await _load_document_chunk_records(
            instance.lightrag, str(doc_id), status_info, kb
        )
        for record in records:
            record_id = _stored_chunk_id(record)
            if record_id:
                chunks_by_id[record_id] = record
    return list(chunks_by_id.values())


async def _refresh_chunk_search(instance: Any, kb: str) -> None:
    async with _chunk_bm25_locks_guard:
        lock = _chunk_bm25_locks.setdefault(kb, asyncio.Lock())
    # BM25 indexes are process-local. Serialize replacement rebuilds per worker.
    async with lock:
        engine = getattr(instance, "hybrid_search_engine", None)
        if engine is not None and hasattr(engine, "build_bm25_index"):
            chunks = await _all_kb_chunk_records(instance, kb)
            await engine.build_bm25_index(chunks)
        from raganything.query_cache import get_query_cache

        get_query_cache().invalidate()


async def _log_chunk_mutation(
    *, action: str, user_id: int, kb: str, doc_id: str, chunk_id: str,
    new_chunk_id: str | None, before_hash: str | None, after_hash: str | None,
    result: str,
) -> None:
    details = {
        "kb": kb, "doc_id": doc_id, "chunk_id": chunk_id,
        "new_chunk_id": new_chunk_id, "before_hash": before_hash,
        "after_hash": after_hash, "result": result,
    }
    try:
        await add_event(action, user_id=user_id, **details)
    except Exception:
        lightrag_logger.warning("Failed to record %s monitor event", action, exc_info=True)
    try:
        await audit_log(user_id, action, details={**details, "user_id": user_id})
    except Exception:
        lightrag_logger.warning("Failed to record %s audit event", action, exc_info=True)


async def _restore_chunk_mutation(
    lg: Any, doc_id: str, old_status: dict[str, Any], old_chunk_id: str,
    old_chunk: dict[str, Any], new_chunk_id: str | None,
) -> None:
    try:
        await lg.text_chunks.upsert({old_chunk_id: old_chunk})
        await lg.chunks_vdb.upsert({old_chunk_id: old_chunk})
        await lg.doc_status.upsert({doc_id: old_status})
        if new_chunk_id and new_chunk_id != old_chunk_id:
            await _delete_chunk_text(lg.text_chunks, [new_chunk_id])
            await _delete_chunk_vectors(lg.chunks_vdb, [new_chunk_id])
        await _flush_chunk_mutation_stores(lg)
    except Exception:
        lightrag_logger.error(
            "Chunk compensation failed for doc=%s chunk=%s",
            doc_id, old_chunk_id, exc_info=True,
        )


@router.get("/knowledge/documents/{doc_id}/chunks")
async def get_document_chunks(
    doc_id: str,
    kb: str = Depends(verify_kb_access),
    current_user: dict = Depends(get_current_user),
):
    """Return document metadata and ordered chunks for a reloadable detail page."""
    try:
        instance = await get_kb(kb)
        if not instance or not instance.lightrag:
            raise HTTPException(500, "Knowledge base is not initialized")
        all_status = await _load_doc_status_json(kb)
        full_id, status_info = _resolve_chunk_document(all_status or {}, doc_id)
        records = await _load_document_chunk_records(instance.lightrag, full_id, status_info, kb)
        metadata = _multimodal_chunk_metadata(status_info)
        chunks = [
            _serialize_document_chunk(record, metadata, status_info=status_info, kb=kb)
            for record in records
        ]
        tags_by_chunk = await _get_tags_for_chunks_best_effort(
            kb, full_id, [value["chunk_id"] for value in chunks]
        )
        for chunk in chunks:
            chunk["tags"] = tags_by_chunk.get(chunk["chunk_id"], [])
        await _attach_video_segment_metadata(kb, chunks)
        document = _chunk_document_payload(full_id, status_info)
        tag_health = await _document_tag_health_contract(kb, [full_id])
        document.update(tag_health.get(full_id, {
            "tag_status": "pending",
            "tag_raw_status": "missing",
            "tagged_chunks": 0,
            "eligible_tag_chunks": 0,
            "tag_not_applicable_chunks": 0,
            "unique_auto_tag_count": 0,
            "auto_tag_assignment_count": 0,
            "avg_auto_tags_per_tagged_chunk": 0.0,
            "tag_error_message": "",
            "tag_retryable": True,
        }))
        document = _apply_enrichment_status_overlay(document)
        if not document["content_summary"] and chunks:
            document["content_summary"] = str(chunks[0].get("content") or "")[:240]
        return {
            "doc_id": full_id,
            "document": document,
            "chunks": chunks,
            "total": len(chunks),
            "total_tokens": sum(value["tokens"] for value in chunks),
            "graph_sync_state": _chunk_graph_sync_state(status_info),
        }
    except HTTPException:
        raise
    except Exception as exc:
        lightrag_logger.error(
            "[get_document_chunks] doc_id=%s kb=%s error=%s", doc_id, kb, exc,
            exc_info=True,
        )
        raise HTTPException(500, "Unable to load document chunks") from exc


@router.get("/knowledge/documents/{doc_id}/chunks/{chunk_id}")
async def get_document_chunk(
    doc_id: str,
    chunk_id: str,
    kb: str = Depends(verify_kb_access),
    current_user: dict = Depends(get_current_user),
):
    """Return one document chunk for a permalinked detail page."""
    try:
        instance = await get_kb(kb)
        if not instance or not instance.lightrag:
            raise HTTPException(500, "Knowledge base is not initialized")
        all_status = await _load_doc_status_json(kb)
        full_id, status_info = _resolve_chunk_document(all_status or {}, doc_id)
        document_chunk_ids = {
            str(value) for value in status_info.get("chunks_list", []) if value
        }
        record = await _chunk_store_get(instance.lightrag.text_chunks, chunk_id)
        if record is None:
            raise HTTPException(404, f"Chunk {chunk_id} does not exist")
        belongs_to_document = (
            chunk_id in document_chunk_ids
            if document_chunk_ids
            else str(record.get("full_doc_id") or "") == full_id
        )
        if not belongs_to_document:
            raise HTTPException(404, f"Chunk {chunk_id} does not exist")

        chunk = _serialize_document_chunk(
            dict(record), _multimodal_chunk_metadata(status_info),
            status_info=status_info, kb=kb,
        )
        if chunk["chunk_id"] != chunk_id:
            raise HTTPException(404, f"Chunk {chunk_id} does not exist")
        chunk["tags"] = (
            await _get_tags_for_chunks_best_effort(kb, full_id, [chunk_id])
        ).get(chunk_id, [])
        await _attach_video_segment_metadata(kb, [chunk])
        document = _chunk_document_payload(full_id, status_info)
        tag_health = await _document_tag_health_contract(kb, [full_id])
        document.update(tag_health.get(full_id, {
            "tag_status": "pending",
            "tag_raw_status": "missing",
            "tagged_chunks": 0,
            "eligible_tag_chunks": 0,
            "tag_not_applicable_chunks": 0,
            "unique_auto_tag_count": 0,
            "auto_tag_assignment_count": 0,
            "avg_auto_tags_per_tagged_chunk": 0.0,
            "tag_error_message": "",
            "tag_retryable": True,
        }))
        document = _apply_enrichment_status_overlay(document)
        if not document["content_summary"]:
            document["content_summary"] = str(chunk.get("content") or "")[:240]
        return {
            "doc_id": full_id,
            "document": document,
            "chunk": chunk,
            "total": len(document_chunk_ids) or int(status_info.get("chunks_count") or 1),
            "graph_sync_state": _chunk_graph_sync_state(status_info),
        }
    except HTTPException:
        raise
    except Exception as exc:
        lightrag_logger.error(
            "[get_document_chunk] doc_id=%s chunk_id=%s kb=%s error=%s",
            doc_id, chunk_id, kb, exc, exc_info=True,
        )
        raise HTTPException(500, "Unable to load document chunk") from exc


@router.get("/knowledge/documents/{doc_id}/video-segments")
async def get_document_video_segments(
    doc_id: str,
    kb: str = Depends(verify_kb_access),
    _perm: None = Depends(require_permission(Permission.KB_READ)),
):
    """Return authorized video time anchors without a server filesystem path."""
    from raganything.services.video_segments import (
        controlled_video_media_url,
        list_video_segments,
    )

    full_id, _status_info = _resolve_chunk_document(
        await _load_doc_status_json(kb) or {}, doc_id
    )
    segments = await list_video_segments(kb, full_id)
    return {
        "document_id": full_id,
        "segments": [
            {
                "segment_id": str(segment["segment_id"]),
                "segment_index": int(segment["segment_index"]),
                "start_ms": int(segment["start_ms"]),
                "end_ms": int(segment["end_ms"]),
                "media_id": str(segment["media_id"]),
                "media_kb": kb,
                "media_url": controlled_video_media_url(str(segment["media_id"]), kb),
            }
            for segment in segments
            if segment.get("status") == "ready" and segment.get("media_id")
        ],
    }


@router.get("/knowledge/tags")
async def list_knowledge_tags(
    q: str = "",
    limit: int = 100,
    offset: int = 0,
    kb: str = Depends(verify_kb_access),
    current_user: dict = Depends(get_current_user),
):
    return {"tags": await list_tags(kb, q, limit, offset)}


@router.get("/knowledge/tags/{tag_id}/links")
async def get_knowledge_tag_links(
    tag_id: int,
    kb: str = Depends(verify_kb_access),
    current_user: dict = Depends(get_current_user),
):
    tag, assignments = await get_tag_assignments(kb, tag_id)
    if not tag:
        raise HTTPException(404, "Tag does not exist in this knowledge base")
    instance = await get_kb(kb)
    if not instance or not instance.lightrag:
        raise HTTPException(500, "Knowledge base is not initialized")
    status_by_id = await _load_doc_status_json(kb)
    grouped: dict[str, list[str]] = {}
    for assignment in assignments:
        grouped.setdefault(assignment["document_id"], []).append(assignment["chunk_id"])
    documents = []
    for document_id, chunk_ids in grouped.items():
        status_info = (status_by_id or {}).get(document_id)
        if not isinstance(status_info, dict):
            continue
        records = await _load_document_chunk_records(instance.lightrag, document_id, status_info, kb)
        by_id = {_stored_chunk_id(record): record for record in records}
        matched = []
        for chunk_id in chunk_ids:
            record = by_id.get(chunk_id)
            if record:
                serialized = _serialize_document_chunk(
                    record,
                    _multimodal_chunk_metadata(status_info),
                    status_info=status_info,
                    kb=kb,
                )
                serialized["tags"] = [{"id": tag["id"], "name": tag["name"]}]
                matched.append(serialized)
        if matched:
            documents.append({"document": _chunk_document_payload(document_id, status_info), "chunks": matched})
    return {
        "tag": tag,
        "documents": documents,
        "document_count": len(documents),
        "chunk_count": sum(len(value["chunks"]) for value in documents),
    }


@router.post("/knowledge/documents/{doc_id}/tags/regenerate")
@_lease_kb_cache_for_operation
async def regenerate_document_automatic_tags(
    doc_id: str,
    kb: str = Depends(verify_kb_operate_access),
    _perm: None = Depends(require_permission(Permission.KB_WRITE)),
    current_user: dict = Depends(get_current_user),
):
    """Rebuild local automatic tags without affecting manual tag choices."""
    instance = await get_kb(kb)
    if not instance or not instance.lightrag:
        raise HTTPException(500, "Knowledge base is not initialized")
    all_status = await _load_doc_status_json(kb)
    full_id, status_info = _resolve_chunk_document(all_status or {}, doc_id)
    if _chunk_document_is_processing(full_id, kb, status_info):
        raise HTTPException(409, "Document is currently being processed")

    result = await _generate_uploaded_document_tags(
        kb,
        full_id,
        filename=_strip_hash_prefix(
            os.path.basename(str(status_info.get("file_path") or ""))
        ),
        user_id=int(current_user.get("id") or 0),
    )
    from raganything.services.document_tagging import (
        enqueue_document_tagging_best_effort,
        record_document_tagging_complete,
    )
    await enqueue_document_tagging_best_effort(
        kb, full_id,
        filename=_strip_hash_prefix(
            os.path.basename(str(status_info.get("file_path") or ""))
        ),
        user_id=int(current_user.get("id") or 0),
    )
    await record_document_tagging_complete(kb, full_id, result)
    await _log_chunk_mutation(
        action="document_tags_regenerate",
        user_id=int(current_user.get("id") or 0),
        kb=kb,
        doc_id=full_id,
        chunk_id=None,
        new_chunk_id=None,
        before_hash=None,
        after_hash=None,
        result="success" if result["chunk_count"] else "no_chunks",
    )
    return {
        "status": "generated" if result["chunk_count"] else "no_chunks",
        "doc_id": full_id,
        **result,
    }


@router.put("/knowledge/documents/{doc_id}/chunks/{chunk_id}/tags")
@_lease_kb_cache_for_operation
async def replace_document_chunk_tags(
    doc_id: str,
    chunk_id: str,
    update: ChunkTagsUpdate,
    kb: str = Depends(verify_kb_operate_access),
    _perm: None = Depends(require_permission(Permission.KB_WRITE)),
    current_user: dict = Depends(get_current_user),
):
    instance = await get_kb(kb)
    if not instance or not instance.lightrag:
        raise HTTPException(500, "Knowledge base is not initialized")
    lg = instance.lightrag
    initial_status = await _load_doc_status_json(kb)
    canonical_id, _ = _resolve_chunk_document(initial_status or {}, doc_id)
    try:
        async with _chunk_document_lock_scope(
            kb, canonical_id, lg, acquire_pg_lock=False
        ):
            all_status = await _load_doc_status_json(kb)
            full_id, status_info = _resolve_chunk_document(all_status or {}, doc_id)
            if _chunk_document_is_processing(full_id, kb, status_info):
                raise HTTPException(409, "Document is currently being processed")
            records = await _load_document_chunk_records(lg, full_id, status_info, kb)
            if not any(_stored_chunk_id(record) == chunk_id for record in records):
                raise HTTPException(404, f"Chunk {chunk_id} does not exist")
            tags = await replace_chunk_tags(kb, full_id, chunk_id, update.tag_names, user_id=current_user["id"])
        await _log_chunk_mutation(
            action="chunk_tags_update", user_id=current_user["id"], kb=kb,
            doc_id=full_id, chunk_id=chunk_id, new_chunk_id=None,
            before_hash=None, after_hash=None, result="success",
        )
        return {"status": "updated", "doc_id": full_id, "chunk_id": chunk_id, "tags": tags}
    except TagValidationError as exc:
        raise HTTPException(422, str(exc)) from exc
    except HTTPException as exc:
        await _log_chunk_mutation(
            action="chunk_tags_update", user_id=current_user["id"], kb=kb,
            doc_id=doc_id, chunk_id=chunk_id, new_chunk_id=None,
            before_hash=None, after_hash=None, result=f"failed:{exc.status_code}",
        )
        raise


@router.patch("/knowledge/documents/{doc_id}/chunks/{chunk_id}")
@_lease_kb_cache_for_operation
async def update_document_chunk(
    doc_id: str,
    chunk_id: str,
    update: ChunkContentUpdate,
    kb: str = Depends(verify_kb_operate_access),
    _perm: None = Depends(require_permission(Permission.KB_WRITE)),
    current_user: dict = Depends(get_current_user),
):
    if not update.content.strip() or len(update.content) > 8000:
        raise HTTPException(422, "content must contain 1 to 8000 characters")
    instance = await get_kb(kb)
    if not instance or not instance.lightrag:
        raise HTTPException(500, "Knowledge base is not initialized")
    lg = instance.lightrag
    initial_status = await _load_doc_status_json(kb)
    canonical_id, _ = _resolve_chunk_document(initial_status or {}, doc_id)
    before_hash = None
    new_id = compute_chunk_id(update.content)
    try:
        async with _chunk_document_lock_scope(kb, canonical_id, lg):
            all_status = await _load_doc_status_json(kb)
            full_id, status_info = _resolve_chunk_document(all_status or {}, doc_id)
            if _chunk_document_is_processing(full_id, kb, status_info):
                raise HTTPException(409, "Document is currently being processed")
            records = await _load_document_chunk_records(lg, full_id, status_info, kb)
            old_chunk = next((value for value in records if _stored_chunk_id(value) == chunk_id), None)
            if old_chunk is None:
                raise HTTPException(404, f"Chunk {chunk_id} does not exist")
            before_hash = hashlib.sha256(str(old_chunk.get("content") or "").encode()).hexdigest()
            if new_id != chunk_id and await _chunk_store_get(lg.text_chunks, new_id):
                raise HTTPException(409, "A chunk with the same content already exists")

            old_status = copy.deepcopy(status_info)
            new_chunk = copy.deepcopy(old_chunk)
            new_chunk.update({
                "id": new_id, "chunk_id": new_id, "content": update.content,
                "tokens": _edited_chunk_tokens(lg, update.content),
                "full_doc_id": old_chunk.get("full_doc_id") or full_id,
                "file_path": old_chunk.get("file_path") or status_info.get("file_path", ""),
            })
            new_status = copy.deepcopy(status_info)
            ordered_chunk_ids = [_stored_chunk_id(value) for value in records]
            new_status["chunks_list"] = [
                new_id if value == chunk_id else value
                for value in ordered_chunk_ids
            ]
            new_status["chunks_count"] = len(records)
            new_status["content_length"] = max(
                0, int(status_info.get("content_length") or 0)
                - len(str(old_chunk.get("content") or "")) + len(update.content),
            )
            new_status["updated_at"] = datetime.now().astimezone().isoformat()
            raw_metadata = status_info.get("metadata")
            metadata = copy.deepcopy(raw_metadata) if isinstance(raw_metadata, dict) else {}
            metadata["graph_sync_state"] = "stale"
            multimodal = metadata.get("multimodal_chunks")
            if isinstance(multimodal, dict) and chunk_id in multimodal:
                multimodal[new_id] = multimodal.pop(chunk_id)
            new_status["metadata"] = metadata

            try:
                await lg.text_chunks.upsert({new_id: new_chunk})
                saved_text = await _chunk_text_get(lg.text_chunks, new_id)
                if not saved_text or saved_text.get("content") != update.content:
                    raise RuntimeError("text chunk read-back verification failed")
                await lg.chunks_vdb.upsert({new_id: new_chunk})
                if not await _chunk_vector_get(lg.chunks_vdb, new_id):
                    raise RuntimeError("chunk vector read-back verification failed")
                await lg.doc_status.upsert({full_id: new_status})
                saved_status = await lg.doc_status.get_by_id(full_id)
                if not saved_status or saved_status.get("chunks_list") != new_status["chunks_list"]:
                    raise RuntimeError("document status read-back verification failed")
                if new_id != chunk_id:
                    await _delete_chunk_text(lg.text_chunks, [chunk_id])
                    await _delete_chunk_vectors(lg.chunks_vdb, [chunk_id])
                await _flush_chunk_mutation_stores(lg)
                updated_records = [new_chunk if _stored_chunk_id(value) == chunk_id else value for value in records]
                await _refresh_chunk_search(instance, kb)
                await move_chunk_tags(kb, full_id, chunk_id, new_id)
                await bump_kb_corpus_revision(kb)
            except Exception as exc:
                await _restore_chunk_mutation(lg, full_id, old_status, chunk_id, old_chunk, new_id)
                try:
                    await _refresh_chunk_search(instance, kb)
                except Exception:
                    pass
                raise HTTPException(500, "Chunk update failed and was rolled back") from exc

            response = {
                "status": "updated", "doc_id": full_id, "old_chunk_id": chunk_id,
                "new_chunk_id": new_id,
                "chunk": _serialize_document_chunk(
                    new_chunk,
                    _multimodal_chunk_metadata(new_status),
                    status_info=new_status,
                    kb=kb,
                ),
                "total": len(updated_records),
                "total_tokens": sum(int(value.get("tokens") or 0) for value in updated_records),
                "graph_sync_state": "stale",
            }
            response["chunk"]["tags"] = (await get_tags_for_chunks(kb, full_id, [new_id])).get(new_id, [])
            from raganything.services.document_tagging import enqueue_document_tagging_best_effort
            await enqueue_document_tagging_best_effort(
                kb, full_id,
                filename=os.path.basename(str(new_status.get("file_path") or "")),
                user_id=int(current_user.get("id") or 0),
            )
        await _log_chunk_mutation(
            action="chunk_update", user_id=current_user["id"], kb=kb,
            doc_id=response["doc_id"], chunk_id=chunk_id, new_chunk_id=new_id,
            before_hash=before_hash, after_hash=hashlib.sha256(update.content.encode()).hexdigest(),
            result="success",
        )
        return response
    except HTTPException as exc:
        await _log_chunk_mutation(
            action="chunk_update", user_id=current_user["id"], kb=kb,
            doc_id=doc_id, chunk_id=chunk_id, new_chunk_id=new_id,
            before_hash=before_hash, after_hash=hashlib.sha256(update.content.encode()).hexdigest(),
            result=f"failed:{exc.status_code}",
        )
        raise


@router.delete("/knowledge/documents/{doc_id}/chunks/{chunk_id}")
@_lease_kb_cache_for_operation
async def delete_document_chunk(
    doc_id: str,
    chunk_id: str,
    kb: str = Depends(verify_kb_operate_access),
    _perm: None = Depends(require_permission(Permission.KB_WRITE)),
    current_user: dict = Depends(get_current_user),
):
    instance = await get_kb(kb)
    if not instance or not instance.lightrag:
        raise HTTPException(500, "Knowledge base is not initialized")
    lg = instance.lightrag
    initial_status = await _load_doc_status_json(kb)
    canonical_id, _ = _resolve_chunk_document(initial_status or {}, doc_id)
    before_hash = None
    try:
        async with _chunk_document_lock_scope(kb, canonical_id, lg):
            all_status = await _load_doc_status_json(kb)
            full_id, status_info = _resolve_chunk_document(all_status or {}, doc_id)
            if _chunk_document_is_processing(full_id, kb, status_info):
                raise HTTPException(409, "Document is currently being processed")
            records = await _load_document_chunk_records(lg, full_id, status_info, kb)
            old_chunk = next((value for value in records if _stored_chunk_id(value) == chunk_id), None)
            if old_chunk is None:
                raise HTTPException(404, f"Chunk {chunk_id} does not exist")
            if len(records) <= 1:
                raise HTTPException(409, "The final chunk cannot be deleted; delete the document instead")
            before_hash = hashlib.sha256(str(old_chunk.get("content") or "").encode()).hexdigest()
            old_status = copy.deepcopy(status_info)
            remaining = [value for value in records if _stored_chunk_id(value) != chunk_id]
            new_status = copy.deepcopy(status_info)
            ordered_chunk_ids = [_stored_chunk_id(value) for value in records]
            new_status["chunks_list"] = [value for value in ordered_chunk_ids if value != chunk_id]
            new_status["chunks_count"] = len(remaining)
            new_status["content_length"] = max(
                0, int(status_info.get("content_length") or 0)
                - len(str(old_chunk.get("content") or "")),
            )
            new_status["updated_at"] = datetime.now().astimezone().isoformat()
            raw_metadata = status_info.get("metadata")
            metadata = copy.deepcopy(raw_metadata) if isinstance(raw_metadata, dict) else {}
            metadata["graph_sync_state"] = "stale"
            multimodal = metadata.get("multimodal_chunks")
            if isinstance(multimodal, dict):
                multimodal.pop(chunk_id, None)
            new_status["metadata"] = metadata
            try:
                await lg.doc_status.upsert({full_id: new_status})
                saved_status = await lg.doc_status.get_by_id(full_id)
                if not saved_status or saved_status.get("chunks_list") != new_status["chunks_list"]:
                    raise RuntimeError("document status read-back verification failed")
                await _delete_chunk_text(lg.text_chunks, [chunk_id])
                await _delete_chunk_vectors(lg.chunks_vdb, [chunk_id])
                await _flush_chunk_mutation_stores(lg)
                await _refresh_chunk_search(instance, kb)
                await delete_chunk_tags(kb, full_id, chunk_id)
                await bump_kb_corpus_revision(kb)
            except Exception as exc:
                await _restore_chunk_mutation(lg, full_id, old_status, chunk_id, old_chunk, None)
                try:
                    await _refresh_chunk_search(instance, kb)
                except Exception:
                    pass
                raise HTTPException(500, "Chunk deletion failed and was rolled back") from exc
            response = {
                "status": "deleted", "doc_id": full_id, "deleted_chunk_id": chunk_id,
                "total": len(remaining),
                "total_tokens": sum(int(value.get("tokens") or 0) for value in remaining),
                "graph_sync_state": "stale",
            }
            from raganything.services.document_tagging import enqueue_document_tagging_best_effort
            await enqueue_document_tagging_best_effort(
                kb, full_id,
                filename=os.path.basename(str(new_status.get("file_path") or "")),
                user_id=int(current_user.get("id") or 0),
            )
        await _log_chunk_mutation(
            action="chunk_delete", user_id=current_user["id"], kb=kb,
            doc_id=response["doc_id"], chunk_id=chunk_id, new_chunk_id=None,
            before_hash=before_hash, after_hash=None, result="success",
        )
        return response
    except HTTPException as exc:
        await _log_chunk_mutation(
            action="chunk_delete", user_id=current_user["id"], kb=kb,
            doc_id=doc_id, chunk_id=chunk_id, new_chunk_id=None,
            before_hash=before_hash, after_hash=None, result=f"failed:{exc.status_code}",
        )
        raise


async def _query_chunks_by_doc_id(_lg, doc_id: str, kb: str) -> list[dict]:
    """Compatibility wrapper for the shared PostgreSQL chunk fallback."""
    try:
        return await query_chunks_by_document_id(_lg, doc_id)
    except PersistedChunkQueryError:
        lightrag_logger.warning(
            "Unable to query persisted chunks; KB=%s doc=%s", kb, doc_id,
            exc_info=True,
        )
        return []


def _extract_media_path(chunk_data: dict) -> str | None:
    """从 chunk content 文本中提取媒体文件路径。"""
    content = chunk_data.get("content", "")
    if not content:
        return None
    import re as _re
    for pattern in (
        r"Image Path:\s*(\S+)",
        r"Table Image Path:\s*(\S+)",
        r"- Video Path:\s*(\S+)",
    ):
        match = _re.search(pattern, content)
        if match:
            path_str = match.group(1).strip()
            if path_str:
                return path_str
    return None


async def _compute_kb_stats(kb: str) -> dict[str, int]:
    """Compute KB stats using the same document dedupe logic as list_documents."""
    import json as _json

    stats = {"documents": 0, "entities": 0, "relations": 0, "chunks": 0}
    base = Path(kb_dir(kb))
    workspace = kb_dir(kb)

    pg_graph_ok = False
    try:
        from raganything.services.pg_state_repo import get_pg_pool
        pool = get_pg_pool()
        async with pool.acquire() as conn:
            await conn.fetchval("SELECT 1")
        pg_graph_ok = True
    except Exception:
        pass

    pg_doc_totals_loaded = False
    if pg_graph_ok:
        try:
            doc_total, chunk_total = await _pg_fetch_doc_totals(workspace)
            stats["documents"] = doc_total
            stats["chunks"] = chunk_total
            pg_doc_totals_loaded = True
        except Exception:
            pass

    if not pg_doc_totals_loaded:
        data = await _load_doc_status_summaries(kb)
        best_doc: dict[str, tuple[str, dict]] = {}
        for doc_id, info in data.items():
            if not isinstance(info, dict):
                continue
            orig = _strip_hash_prefix(info.get("file_path", "") or "")
            if orig not in best_doc or _document_timestamp(
                info.get("updated_at")
            ) > _document_timestamp(best_doc[orig][1].get("updated_at")):
                best_doc[orig] = (doc_id, info)

        stats["documents"] = len(best_doc)
        for _, info in best_doc.values():
            stats["chunks"] += info.get("chunks_count", 0) if isinstance(info, dict) else 0

    pg_totals_loaded = False
    if pg_graph_ok:
        try:
            entity_total, relation_total = await _pg_fetch_graph_totals(workspace)
            pg_totals_loaded = True
            stats["entities"] = entity_total
            stats["relations"] = relation_total
        except Exception:
            pass

    if not pg_totals_loaded:
        ent_path = base / "kv_store_full_entities.json"
        if ent_path.exists():
            try:
                entities = _json.loads(ent_path.read_text(encoding="utf-8"))
                if isinstance(entities, dict):
                    for _, value in entities.items():
                        if isinstance(value, dict):
                            stats["entities"] += value.get("count", len(value.get("entity_names", [])))
            except (_json.JSONDecodeError, OSError):
                pass

        rel_path = base / "kv_store_full_relations.json"
        if rel_path.exists():
            try:
                relations = _json.loads(rel_path.read_text(encoding="utf-8"))
                if isinstance(relations, dict):
                    for _, value in relations.items():
                        if isinstance(value, dict):
                            stats["relations"] += value.get("count", len(value.get("relation_pairs", [])))
            except (_json.JSONDecodeError, OSError):
                pass

    return stats


def _is_kb_visible_to_user(kb_name: str, kb_info: dict, current_user: dict) -> bool:
    if current_user.get("is_admin"):
        return True

    allowed_kbs = current_user.get("allowed_kbs", [])
    if kb_name in allowed_kbs:
        return True

    owner_id = kb_info.get("owner_id")
    return owner_id is not None and owner_id == current_user["id"]


async def _compute_kb_stats_batch_fast(allowed_names: list[str]) -> dict[str, dict[str, int]]:
    stats_map: dict[str, dict[str, int]] = {
        name: {"documents": 0, "entities": 0, "relations": 0, "chunks": 0}
        for name in allowed_names
    }
    if not allowed_names:
        return stats_map

    workspaces = [kb_dir(name) for name in allowed_names]
    workspace_to_name = dict(zip(workspaces, allowed_names))

    try:
        doc_totals_by_workspace, graph_totals_by_workspace = await asyncio.gather(
            _pg_fetch_doc_totals_batch(workspaces),
            _pg_fetch_graph_totals_batch(workspaces),
        )
    except Exception:
        return {}

    for workspace, name in workspace_to_name.items():
        doc_total, chunk_total = doc_totals_by_workspace.get(workspace, (0, 0))
        entity_total, relation_total = graph_totals_by_workspace.get(workspace, (0, 0))
        stats_map[name] = {
            "documents": int(doc_total or 0),
            "entities": int(entity_total or 0),
            "relations": int(relation_total or 0),
            "chunks": int(chunk_total or 0),
        }

    return stats_map


def _stats_unavailable_payload() -> dict[str, int | bool]:
    return {
        "documents": 0,
        "entities": 0,
        "relations": 0,
        "chunks": 0,
        "unavailable": True,
    }


@router.get("/knowledge/stats")
async def knowledge_stats(kb: str = Depends(verify_kb_access), current_user: dict = Depends(get_current_user)):
    """知识库总体统计 — 与 list_documents 使用相同的数据源和去重逻辑"""
    return await _compute_kb_stats(kb)


@router.post("/knowledge/stats/batch")
async def knowledge_stats_batch(
    req: KBStatsBatchRequest,
    current_user: dict = Depends(get_current_user),
):
    started_at = time.perf_counter()
    requested_names = [name for name in req.kb_names if isinstance(name, str) and name]
    unique_names = list(dict.fromkeys(requested_names))

    meta = await load_kb_meta()
    allowed_names = [
        name for name in unique_names
        if name in meta and _is_kb_visible_to_user(name, meta.get(name, {}), current_user)
    ]

    try:
        batched_stats = await asyncio.wait_for(
            _compute_kb_stats_batch_fast(allowed_names),
            timeout=KB_STATS_BATCH_TIMEOUT_SECONDS,
        )
    except Exception:
        batched_stats = {}

    if batched_stats:
        elapsed_ms = (time.perf_counter() - started_at) * 1000
        lightrag_logger.info(
            "[KB-STATS-BATCH] user=%s requested=%s allowed=%s mode=fast elapsed_ms=%.1f",
            current_user.get("username", "?"),
            len(unique_names),
            len(allowed_names),
            elapsed_ms,
        )
        return {"stats": batched_stats}

    async def _compute_with_timeout(name: str):
        try:
            return await asyncio.wait_for(
                _compute_kb_stats(name),
                timeout=KB_STATS_BATCH_TIMEOUT_SECONDS,
            )
        except Exception as exc:
            return exc

    results = await asyncio.gather(
        *[_compute_with_timeout(name) for name in allowed_names],
        return_exceptions=False,
    )

    stats_map: dict[str, dict[str, int]] = {}
    for name, result in zip(allowed_names, results):
        if isinstance(result, Exception):
            stats_map[name] = _stats_unavailable_payload()
            continue
        stats_map[name] = result

    elapsed_ms = (time.perf_counter() - started_at) * 1000
    lightrag_logger.info(
        "[KB-STATS-BATCH] user=%s requested=%s allowed=%s mode=fallback elapsed_ms=%.1f",
        current_user.get("username", "?"),
        len(unique_names),
        len(allowed_names),
        elapsed_ms,
    )
    return {"stats": stats_map}


@router.post("/knowledge/repair")
async def repair_kb_orphans(
    kb: str = Depends(verify_kb_operate_access),
    current_user: dict = Depends(get_current_user),
    _perm: None = Depends(require_permission(Permission.SETTINGS_WRITE)),
):
    """扫描并清理知识库中所有孤儿数据（doc_status 中不存在的文档残留）。

    适用场景：
    - 之前删除文档后实体/关系数未归零
    - 文档处理中断导致部分数据残留
    - 多模态处理产生的实体/向量引用了已不存在的文档
    """
    instance = await get_kb(kb)
    if not instance.lightrag:
        raise HTTPException(500, "知识库未初始化")

    # Full reconciliation is intentionally explicit. Normal successful
    # document deletion is handled by LightRAG's targeted delete path and
    # must not scan an entire KB after every request.
    try:
        report = await _purge_all_orphans(
            instance, kb, deep_scan=True, strict=True
        )
    except RuntimeError as exc:
        raise HTTPException(503, f"知识库修复检查不可用: {exc}") from exc

    # 清除查询缓存
    try:
        from raganything.query_cache import get_query_cache
        get_query_cache().invalidate()
    except Exception:
        pass

    if not report:
        return {"status": "ok", "message": "未发现孤儿数据，知识库状态正常", "cleaned": {}}
    return {"status": "repaired", "message": f"已清理 {sum(report.values())} 条孤儿记录", "cleaned": report}


@router.get("/knowledge/entities")
async def list_entities(request: Request, limit: int = 50, kb: str = Depends(verify_kb_access), current_user: dict = Depends(get_current_user)):
    """列出知识图谱实体 — PG-first with JSON fallback"""
    workspace = kb_dir(kb)
    entities: list[dict] = []
    seen: set[str] = set()
    valid_doc_ids: set[str] = set()
    total = 0
    data: dict[str, dict] = {}

    # ── PG-only ──
    valid_doc_ids = await _pg_fetch_doc_ids(workspace)
    data = await _pg_fetch_graph_entities(workspace)

    for k, v in data.items():
        if valid_doc_ids and k not in valid_doc_ids:
            continue
        names = v.get("entity_names", [])
        for name in names:
            if name not in seen and len(entities) < limit:
                seen.add(name)
                entities.append({"id": name[:16], "name": name, "type": infer_entity_type(name)})
        total += v.get("count", len(names))

    # 类型筛选
    type_filter = request.query_params.get("type", "")
    if type_filter:
        entities = [e for e in entities if e["type"] == type_filter]

    return {"entities": entities, "total": total}


@router.get("/knowledge/graph")
async def graph_data(kb: str = Depends(verify_kb_access), current_user: dict = Depends(get_current_user)):
    """返回知识图谱数据(前端可视化用) — PG-first with JSON fallback"""
    workspace = kb_dir(kb)
    nodes, edges = [], []
    node_ids = set()

    def is_valid_node(name: str) -> bool:
        """过滤掉文件路径、图片名等无效实体"""
        if not name or not isinstance(name, str):
            return False
        if "\\" in name or "/" in name and "." in name.split("/")[-1]:
            return False
        if name.endswith((".png", ".jpg", ".jpeg", ".bmp", ".gif", ".pdf", ".docx")):
            return False
        if len(name) > 80:
            return False
        return True

    entities_data: dict[str, dict] = {}
    relations_data: dict[str, dict] = {}
    valid_doc_ids: set[str] = set()

    # ── PG-only ──
    valid_doc_ids = await _pg_fetch_doc_ids(workspace)
    entities_data = await _pg_fetch_graph_entities(workspace)
    relations_data = await _pg_fetch_graph_relations(workspace)

    # 交叉校验 doc_status，过滤已删除文档的孤儿节点/边
    # 从 entities 建节点
    for k, v in entities_data.items():
        if valid_doc_ids and k not in valid_doc_ids:
            continue
        for name in v.get("entity_names", []):
            if is_valid_node(name) and name not in node_ids:
                node_ids.add(name)
                nodes.append({"id": name, "label": name[:25]})

    # 从 relations 建边
    for k, v in relations_data.items():
        if valid_doc_ids and k not in valid_doc_ids:
            continue
        for src, tgt in v.get("relation_pairs", []):
            if not is_valid_node(src) or not is_valid_node(tgt):
                continue
            if src not in node_ids:
                node_ids.add(src)
                nodes.append({"id": src, "label": src[:25]})
            if tgt not in node_ids:
                node_ids.add(tgt)
                nodes.append({"id": tgt, "label": tgt[:25]})
            edges.append({"source": src, "target": tgt, "label": ""})

    # ── Apply user edits (renames, additions, deletions, manual relations) ──
    try:
        from raganything.services.pg_graph_edit_repo import apply_user_edits_to_graph
        nodes, edges = await apply_user_edits_to_graph(workspace, nodes, edges)
        # Rebuild node_ids from merged result
        node_ids = {n["id"] for n in nodes}
    except Exception:
        lightrag_logger.warning(
            "[GRAPH] apply_user_edits_to_graph failed for kb=%s — "
            "user-created entities/relations will not appear in graph",
            kb,
            exc_info=True,
        )

    return {"nodes": nodes, "edges": edges}


# ═══════════════════════════════════════════════════════════════
# Retrieval-layer sync — Propagate user edits into LightRAG's
# chunk_entity_relation_graph so that renames, additions, and
# deletions visibly affect entity matching during retrieval.
# ═══════════════════════════════════════════════════════════════

async def _sync_entity_to_retrieval_graph(
    kb: str,
    operation: str,  # "rename", "delete", "create"
    entity_name: str,
    new_name: str = "",
    entity_type: str = "",
) -> None:
    """Propagate an entity edit into LightRAG's in-memory graph so that
    the retrieval pipeline (GraphRetriever._match_entities) sees the change.

    This is the critical bridge between the user_entities PG table
    (visualization layer) and chunk_entity_relation_graph (retrieval layer).
    """
    try:
        instance = await get_kb(kb)
        if not instance or not instance.lightrag:
            return
        graph = getattr(instance.lightrag, "chunk_entity_relation_graph", None)
        if graph is None:
            return

        if operation == "delete":
            await graph.delete_node(entity_name)
            lightrag_logger.info(
                "[GRAPH-SYNC] Deleted entity from retrieval graph: %s", entity_name,
            )

        elif operation == "rename":
            # ⚠️  delete_node() cascades to remove all edges in NetworkX.
            # Save edges BEFORE deleting, re-create them under the new name.
            old_edges: list[tuple[str, str, dict]] = []
            try:
                raw_edges = await graph.get_node_edges(entity_name)
                if raw_edges:
                    for src, tgt in (raw_edges or []):
                        # Collect edge data to preserve
                        edge_data = {}
                        try:
                            ed = await graph.get_edge(src, tgt)
                            if ed:
                                edge_data = ed
                        except Exception:
                            pass
                        old_edges.append((src, tgt, edge_data))
            except Exception:
                pass

            # Read old node data, delete old node, upsert new node
            old_data = await graph.get_node(entity_name)
            node_data = old_data or {"entity_type": infer_entity_type(new_name)}
            await graph.delete_node(entity_name)
            await graph.upsert_node(new_name, node_data)

            # Re-create edges with renamed references
            for src, tgt, edata in old_edges:
                new_src = new_name if src == entity_name else src
                new_tgt = new_name if tgt == entity_name else tgt
                try:
                    await graph.upsert_edge(new_src, new_tgt, edata)
                except Exception:
                    pass

            lightrag_logger.info(
                "[GRAPH-SYNC] Renamed entity in retrieval graph: %s → %s (preserved %d edges)",
                entity_name, new_name, len(old_edges),
            )

        elif operation == "create":
            await graph.upsert_node(
                entity_name,
                {"entity_type": entity_type or infer_entity_type(entity_name)},
            )
            lightrag_logger.info(
                "[GRAPH-SYNC] Created entity in retrieval graph: %s", entity_name,
            )

        # Persist the graph mutation to disk
        try:
            await graph.index_done_callback()
        except Exception:
            pass

    except Exception as e:
        lightrag_logger.warning(
            "[GRAPH-SYNC] Failed to sync '%s' op='%s': %s",
            entity_name, operation, e,
        )


async def _sync_edge_to_retrieval_graph(
    kb: str,
    operation: str,  # "create", "delete"
    source_entity: str,
    target_entity: str,
    relation_type: str = "related_to",
) -> None:
    """Propagate a user-created/deleted edge into LightRAG's
    chunk_entity_relation_graph so that BFS traversal during retrieval
    follows user-defined relations.
    """
    try:
        instance = await get_kb(kb)
        if not instance or not instance.lightrag:
            return
        graph = getattr(instance.lightrag, "chunk_entity_relation_graph", None)
        if graph is None:
            return

        if operation == "create":
            edge_data = {"relation_type": relation_type, "source": "manual"}
            await graph.upsert_edge(source_entity, target_entity, edge_data)
            lightrag_logger.info(
                "[GRAPH-SYNC] Created edge in retrieval graph: %s → %s",
                source_entity, target_entity,
            )

        elif operation == "delete":
            try:
                await graph.remove_edges([(source_entity, target_entity)])
            except Exception:
                pass
            lightrag_logger.info(
                "[GRAPH-SYNC] Deleted edge from retrieval graph: %s → %s",
                source_entity, target_entity,
            )

        try:
            await graph.index_done_callback()
        except Exception:
            pass

    except Exception as e:
        lightrag_logger.warning(
            "[GRAPH-SYNC] Failed to sync edge '%s'→'%s' op='%s': %s",
            source_entity, target_entity, operation, e,
        )


# ═══════════════════════════════════════════════════════════════
# Graph Editing API — Manual entity / relation CRUD
# ═══════════════════════════════════════════════════════════════

@router.get("/knowledge/graph/nodes/{entity_name:path}")
async def graph_node_detail(
    entity_name: str,
    kb: str = Depends(verify_kb_access),
    current_user: dict = Depends(get_current_user),
):
    """Get details for a single graph entity (auto-extracted + user-edited)."""
    from raganything.services.pg_graph_edit_repo import (
        get_user_relations_for_entity,
    )

    workspace = kb_dir(kb)

    # Fetch auto-extracted data
    entities_data = await _pg_fetch_graph_entities(workspace)
    relations_data = await _pg_fetch_graph_relations(workspace)
    valid_doc_ids = await _pg_fetch_doc_ids(workspace)

    # Find which documents contain this entity
    source_docs: list[str] = []
    for doc_id, v in entities_data.items():
        if valid_doc_ids and doc_id not in valid_doc_ids:
            continue
        if entity_name in v.get("entity_names", []):
            source_docs.append(doc_id)

    # Find auto-extracted relations involving this entity
    auto_relations: list[dict] = []
    connected_entities: set[str] = set()
    for k, v in relations_data.items():
        if valid_doc_ids and k not in valid_doc_ids:
            continue
        for src, tgt in v.get("relation_pairs", []):
            if src == entity_name and tgt != entity_name:
                auto_relations.append({"source": src, "target": tgt, "type": "auto"})
                connected_entities.add(tgt)
            elif tgt == entity_name and src != entity_name:
                auto_relations.append({"source": src, "target": tgt, "type": "auto"})
                connected_entities.add(src)

    # Fetch user-edited relations involving this entity
    try:
        user_rels = await get_user_relations_for_entity(workspace, entity_name)
        for ur in user_rels:
            auto_relations.append({
                "source": ur["source_entity"],
                "target": ur["target_entity"],
                "type": "manual",
                "relation_type": ur.get("relation_type", ""),
                "relation_id": ur.get("id", ""),
            })
            if ur["source_entity"] != entity_name:
                connected_entities.add(ur["source_entity"])
            if ur["target_entity"] != entity_name:
                connected_entities.add(ur["target_entity"])
    except Exception:
        pass

    return {
        "name": entity_name,
        "entity_type": infer_entity_type(entity_name),
        "source_doc_count": len(source_docs),
        
        "source_docs": [d[:16] for d in source_docs[:10]],
        "connected_entities": sorted(connected_entities),
        "relation_count": len(auto_relations),
        "relations": auto_relations[:50],
    }


async def _ensure_edit_tables() -> None:
    """Eagerly ensure user_entities / user_relations tables exist.

    Called at the top of every graph-edit endpoint so that even if the
    server hasn't been restarted since the migration was added, the
    tables are created on first use.
    """
    from raganything.services.pg_graph_edit_repo import ensure_graph_edit_tables
    await ensure_graph_edit_tables()


@router.post("/knowledge/graph/nodes")
async def create_graph_node(
    req: CreateEntityRequest,
    kb: str = Depends(verify_kb_operate_access),
    current_user: dict = Depends(get_current_user),
    _perm: None = Depends(require_permission(Permission.GRAPH_WRITE)),
):
    """Manually create a new entity node in the knowledge graph."""
    await _ensure_edit_tables()
    from raganything.services.pg_graph_edit_repo import create_user_entity

    name = req.name.strip()
    if not name:
        raise HTTPException(400, "实体名称不能为空")

    result = await create_user_entity(
        kb_name=kb_dir(kb),
        name=name,
        entity_type=req.entity_type,
        description=req.description,
        created_by=current_user.get("id", 0),
    )
    if not result:
        raise HTTPException(500, "创建实体失败，请检查数据库连接")
    # Sync to retrieval graph (best-effort, won't fail the request)
    await _sync_entity_to_retrieval_graph(
        kb, "create", name, entity_type=req.entity_type,
    )
    await add_event("graph_entity_create", entity=name, kb=kb, user_id=current_user.get("id", 0))
    return {"status": "created", "entity": result}


@router.put("/knowledge/graph/nodes/{entity_name:path}")
async def rename_graph_node(
    entity_name: str,
    req: RenameEntityRequest,
    kb: str = Depends(verify_kb_operate_access),
    current_user: dict = Depends(get_current_user),
    _perm: None = Depends(require_permission(Permission.GRAPH_WRITE)),
):
    """Rename a graph entity node."""
    await _ensure_edit_tables()
    from raganything.services.pg_graph_edit_repo import rename_user_entity

    new_name = req.new_name.strip()
    if not new_name:
        raise HTTPException(400, "新名称不能为空")
    if new_name == entity_name:
        raise HTTPException(400, "新名称与旧名称相同")

    result = await rename_user_entity(
        kb_name=kb_dir(kb),
        old_name=entity_name,
        new_name=new_name,
        created_by=current_user.get("id", 0),
    )
    if not result:
        raise HTTPException(500, "重命名实体失败，请检查数据库连接")
    # Sync to retrieval graph (best-effort, won't fail the request)
    await _sync_entity_to_retrieval_graph(
        kb, "rename", entity_name, new_name=new_name,
    )
    await add_event("graph_entity_rename", old=entity_name, new=new_name, kb=kb, user_id=current_user.get("id", 0))
    return {"status": "renamed", "entity": result}


@router.delete("/knowledge/graph/nodes/{entity_name:path}")
async def delete_graph_node(
    entity_name: str,
    kb: str = Depends(verify_kb_operate_access),
    current_user: dict = Depends(get_current_user),
    _perm: None = Depends(require_permission(Permission.GRAPH_WRITE)),
):
    """Soft-delete a graph entity node."""
    await _ensure_edit_tables()
    from raganything.services.pg_graph_edit_repo import delete_user_entity

    ok = await delete_user_entity(
        kb_name=kb_dir(kb),
        name=entity_name,
        created_by=current_user.get("id", 0),
    )
    if not ok:
        raise HTTPException(404, f"实体 '{entity_name}' 不存在或已删除")
    # Sync to retrieval graph (best-effort, won't fail the request)
    await _sync_entity_to_retrieval_graph(kb, "delete", entity_name)
    await add_event("graph_entity_delete", entity=entity_name, kb=kb, user_id=current_user.get("id", 0))
    return {"status": "deleted", "entity": entity_name}


@router.post("/knowledge/graph/edges")
async def create_graph_edge(
    req: CreateRelationRequest,
    kb: str = Depends(verify_kb_operate_access),
    current_user: dict = Depends(get_current_user),
    _perm: None = Depends(require_permission(Permission.GRAPH_WRITE)),
):
    """Manually create a relation (edge) between two entities."""
    await _ensure_edit_tables()
    from raganything.services.pg_graph_edit_repo import create_user_relation

    source = req.source_entity.strip()
    target = req.target_entity.strip()

    if source == target:
        raise HTTPException(400, "源实体和目标实体不能相同")

    # Validate both entities exist (check auto-extracted + user-created)
    workspace = kb_dir(kb)
    entities_data = await _pg_fetch_graph_entities(workspace)
    auto_names: set[str] = set()
    for v in entities_data.values():
        auto_names.update(v.get("entity_names", []))

    from raganything.services.pg_graph_edit_repo import list_user_entities, get_deleted_entity_names
    user_ents = await list_user_entities(workspace)
    deleted_names = await get_deleted_entity_names(workspace)
    user_names = {ue["name"] for ue in user_ents}

    all_valid = (auto_names | user_names) - deleted_names
    missing = []
    if source not in all_valid:
        missing.append(f"源实体 '{source}'")
    if target not in all_valid:
        missing.append(f"目标实体 '{target}'")
    if missing:
        raise HTTPException(400, f"实体不存在: {', '.join(missing)}。请先创建实体或确认名称正确。")

    result = await create_user_relation(
        kb_name=workspace,
        source_entity=source,
        target_entity=target,
        relation_type=req.relation_type,
        description=req.description,
        created_by=current_user.get("id", 0),
    )
    if not result:
        raise HTTPException(500, "创建关系失败")
    # Sync edge to retrieval graph for BFS traversal
    await _sync_edge_to_retrieval_graph(
        kb, "create", source, target, req.relation_type,
    )
    await add_event("graph_edge_create", source=source, target=target, kb=kb, user_id=current_user.get("id", 0))
    return {"status": "created", "relation": result}


@router.delete("/knowledge/graph/edges/{relation_id}")
async def delete_graph_edge(
    relation_id: str,
    kb: str = Depends(verify_kb_operate_access),
    current_user: dict = Depends(get_current_user),
    _perm: None = Depends(require_permission(Permission.GRAPH_WRITE)),
):
    """Delete a manual relation (edge) by ID."""
    await _ensure_edit_tables()
    from raganything.services.pg_graph_edit_repo import delete_user_relation

    # Fetch relation info before deletion (for graph sync)
    from raganything.services.pg_graph_edit_repo import list_user_relations
    workspace = kb_dir(kb)
    all_rels = await list_user_relations(workspace)
    rel_info = next((r for r in all_rels if r.get("id") == relation_id), None)

    ok = await delete_user_relation(
        relation_id=relation_id,
        kb_name=workspace,
    )
    if not ok:
        raise HTTPException(404, f"关系 '{relation_id}' 不存在")
    # Sync edge removal to retrieval graph
    if rel_info:
        await _sync_edge_to_retrieval_graph(
            kb, "delete", rel_info["source_entity"], rel_info["target_entity"],
        )
    await add_event("graph_edge_delete", relation_id=relation_id, kb=kb, user_id=current_user.get("id", 0))
    return {"status": "deleted", "relation_id": relation_id}


# ── File Download Helpers ────────────────────────────────────

def _find_upload_file(file_path_str: str) -> Path | None:
    """Locate a previously uploaded file on disk using multiple strategies.

    Strategy (tried in order):
      1. ``file_path_str`` as an absolute path — check directly.
      2. ``./uploads/{basename}`` — exact filename match.
      3. ``./uploads/*_{basename}`` — glob for random-prefixed uploads.
    """
    if not file_path_str:
        return None

    # Strategy 1: direct path
    direct = Path(file_path_str)
    if direct.is_absolute() and direct.exists():
        return direct

    # Strategy 2: basename in uploads dir
    uploads = Path("./uploads")
    if not uploads.is_dir():
        return None
    basename = Path(file_path_str).name
    exact = uploads / basename
    if exact.exists():
        return exact

    # Strategy 3: glob for random-prefixed file (secrets.token_hex(4) + "_" + name)
    candidates = list(uploads.glob(f"*_{basename}"))
    # Prefer most recently modified
    candidates.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    return candidates[0] if candidates else None


async def _resolve_download_file(kb: str, doc_id: str) -> tuple[Path, str] | None:
    """Resolve a document ID to a physical file path for download.

    Queries doc_status (PG-first → JSON fallback), extracts the stored
    ``file_path``, then uses ``_find_upload_file()`` to locate the real file.

    Returns:
        ``(absolute_path, display_filename)`` or ``None`` if not found.
    """
    workspace = kb_dir(kb)

    # ── PG-only: doc_status from LightRAG ──
    from raganything.services.pg_state_repo import get_pg_pool
    doc_status: dict = {}
    pool = get_pg_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """SELECT file_path, status FROM LIGHTRAG_DOC_STATUS
               WHERE workspace=$1 AND id=$2""",
            workspace, doc_id,
        )
    if row:
        doc_status = {doc_id: {"file_path": row["file_path"], "status": row["status"]}}
    # Try prefix match on PG miss
    if not doc_status:
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                """SELECT id, file_path, status FROM LIGHTRAG_DOC_STATUS
                   WHERE workspace=$1 AND id LIKE $2 LIMIT 5""",
                workspace, f"{doc_id}%",
            )
        if rows:
            doc_status = {rows[0]["id"]: {"file_path": rows[0]["file_path"],
                                           "status": rows[0]["status"]}}
            doc_id = rows[0]["id"]

    info = doc_status.get(doc_id, {})
    stored_path = info.get("file_path", "")

    # Also try processing_tasks for in-flight docs
    if not stored_path:
        task = processing_tasks.get(doc_id)
        if task:
            stored_path = task.get("file_path", task.get("file", ""))
            if not stored_path:
                for tid, t in processing_tasks.items():
                    if tid.startswith(doc_id) or str(t.get("file", "")).startswith(doc_id):
                        stored_path = t.get("file_path", t.get("file", ""))
                        break

    if not stored_path:
        return None

    real_path = _find_upload_file(stored_path)
    if real_path is None:
        return None

    display_name = display_document_name(stored_path)
    return real_path.resolve(), display_name


# ── File Download Endpoint ────────────────────────────────────


async def _verify_kb_access_for_download(kb: str, current_user: dict) -> None:
    """验证用户对指定知识库的访问权限（下载端点专用，不通过 FastAPI 依赖注入）。

    与 dependencies.verify_kb_access 逻辑一致，但作为普通函数调用而非 FastAPI 依赖，
    从而避免其内部的 get_current_user → HTTPBearer() 阻断 ?token=xxx 回退认证路径。
    """
    from raganything.services.kb_service import load_kb_meta
    from fastapi import HTTPException as _HTTPException

    kb_meta = await load_kb_meta()
    if kb not in kb_meta:
        raise _HTTPException(404, f"知识库 '{kb}' 不存在")
    if current_user.get("is_admin"):
        return
    allowed_kbs = current_user.get("allowed_kbs", [])
    if kb in allowed_kbs:
        return
    kb_info = kb_meta.get(kb, {})
    owner_id = kb_info.get("owner_id")
    if owner_id is not None and owner_id == current_user["id"]:
        return
    if kb not in allowed_kbs:
        raise _HTTPException(403, "无权访问该知识库")


@router.get("/knowledge/documents/{doc_id}/download")
async def download_document(
    doc_id: str,
    kb: str = QueryParam("default"),
    token: Optional[str] = QueryParam(None, description="认证 Token（用于 a 标签等无法设置 Header 的场景）"),
    current_user: Optional[dict] = Depends(get_optional_user),
):
    """下载文档的原始上传文件（PDF / DOCX / PPTX / 视频 等）。

    支持 HTTP Range 请求（视频拖动进度条、断点续传）。
    Content-Type 根据文件扩展名自动检测。
    支持 Authorization header 和 ?token=xxx query 参数两种认证方式。
    KB 访问验证在双模式认证完成后执行，避免 HTTPBearer 依赖链阻断 ?token 回退。
    """
    import mimetypes

    # 双模式认证：header 优先，query 参数回退（用于 <a> 标签下载）
    if current_user is None and token:
        current_user = await get_current_user_from_token(token=token)
    if current_user is None:
        raise HTTPException(401, "请提供有效的认证 Token（query 参数 ?token= 或 Authorization header）")

    # KB 访问验证（必须在认证后执行，不能用 FastAPI 依赖注入 — 否则 verify_kb_access
    # 内部会触发 get_current_user → HTTPBearer() 在无 Authorization header 时直接报 401）
    await _verify_kb_access_for_download(kb, current_user)

    resolved = await _resolve_download_file(kb, doc_id)
    if resolved is None:
        raise HTTPException(404, f"文档 {doc_id} 的原始文件未找到，可能已被清理")

    real_path, display_name = resolved

    # 安全检查：确保文件在项目目录内
    try:
        real_path.relative_to(Path.cwd().resolve())
    except ValueError:
        raise HTTPException(403, "不允许访问项目目录外的文件")

    content_type, _encoding = mimetypes.guess_type(str(real_path))
    if content_type is None:
        content_type = "application/octet-stream"

    # 对常见文档类型设置 inline 预览（浏览器能处理的话），其他下载
    inline_types = {
        "application/pdf", "image/jpeg", "image/png", "image/gif",
        "image/webp", "image/bmp", "video/mp4", "video/webm",
        "audio/mpeg", "audio/wav", "text/plain", "text/html",
    }
    disposition = "inline" if content_type in inline_types else "attachment"

    lightrag_logger.info(
        "[DOWNLOAD] doc=%s kb=%s file=%s size=%s type=%s user=%s",
        doc_id, kb, display_name, real_path.stat().st_size, content_type,
        current_user.get("id", 0),
    )

    return FileResponse(
        str(real_path),
        media_type=content_type,
        filename=display_name,
        content_disposition_type=disposition,
    )


def _cleanup_document_files(
    kb_name: str, file_path: str, doc_id: str = ""
) -> dict[str, bool]:
    """Delete uploaded file and parse output for a document.

    Called when a document or KB is deleted from the frontend.  Ensures the
    ``uploads/`` directory and per-KB parser output directory stay in sync
    with the knowledge base.
    """
    lifecycle_result = {"artifact_cleanup_pending": False}

    # OpenDataLoader artifacts are not authorized by a filename prefix or a
    # doc_status/cache path.  If a server-side registry owns this doc, delete
    # exactly that registered run; unsupported Windows cleanup is explicitly
    # reported as pending and never falls through to rmtree().
    output_base = "./output" if kb_name == "default" else f"./output_{kb_name}"
    output_dir = Path(output_base)
    registered_odl_artifact = False
    legacy_odl_registry_present = (output_dir / ".odl-artifact-registry.sqlite3").is_file()
    if doc_id:
        from raganything.services.odl_artifact_lifecycle import (
            ArtifactLifecycleCapabilityError,
            ArtifactOwner,
            OpenDataLoaderArtifactLifecycle,
            configured_odl_artifact_root,
        )
        artifact_root = configured_odl_artifact_root()
        if artifact_root is not None and artifact_root.is_dir():
            lifecycle = OpenDataLoaderArtifactLifecycle(artifact_root)
            owner = ArtifactOwner(kb_name, doc_id)
            record = lifecycle.get(owner)
            if record is not None and record.state != "deleted":
                registered_odl_artifact = True
                workers_exited = all(
                    getattr(process, "returncode", None) is not None
                    for process, _task_id in _kb_worker_procs.get(kb_name, [])
                )
                try:
                    lifecycle.delete(
                        owner,
                        expected_generation=record.generation,
                        worker_exited=workers_exited,
                    )
                    lightrag_logger.info("[CLEANUP] Deleted registered OpenDataLoader artifact")
                except ArtifactLifecycleCapabilityError:
                    lifecycle_result["artifact_cleanup_pending"] = True
                    lightrag_logger.warning(
                        "[CLEANUP] OpenDataLoader artifact retained: secure cleanup is unsupported on this runtime"
                    )
        # A pre-isolation registry proves this legacy output tree may contain
        # ODL artifacts.  It is never eligible for prefix deletion, even when
        # the requested document lacks a registry row.
        if legacy_odl_registry_present:
            lifecycle_result["artifact_cleanup_pending"] = True

    # 1. Delete the original uploaded file from uploads/
    if file_path:
        real = _find_upload_file(file_path)
        if real and real.exists():
            try:
                real.unlink()
                lightrag_logger.info(f"[CLEANUP] 已删除上传文件: {real}")
            except (FileNotFoundError, OSError):
                pass  # 已被并发请求删除或无权限

    # 2. Legacy parsers retain their historical prefix cleanup.  An ODL run
    # registered above never uses this path, which would otherwise allow a
    # filename collision to widen the destructive scope.
    if output_dir.exists() and not registered_odl_artifact and not legacy_odl_registry_present:
        file_stem = Path(file_path).stem
        for d in output_dir.iterdir():
            if d.is_dir() and d.name.startswith(file_stem):
                shutil.rmtree(d, ignore_errors=True)
                lightrag_logger.info(f"[CLEANUP] 已删除解析输出: {d}")
                break  # one document → one output directory

    # 3. Invalidate only cache entries whose stored document identity matches.
    # Cache keys are configuration hashes, not doc IDs, so indexing by the
    # filename or a provenance reference would be both incorrect and unsafe.
    if doc_id:
        cache_path = Path(kb_dir(kb_name)) / "kv_store_parse_cache.json"
        if cache_path.exists():
            try:
                cache = json.loads(cache_path.read_text("utf-8"))
                matching_keys = [
                    key
                    for key, value in cache.items()
                    if isinstance(value, dict) and value.get("doc_id") == doc_id
                ]
                if matching_keys:
                    for key in matching_keys:
                        del cache[key]
                    cache_path.write_text(
                        json.dumps(cache, ensure_ascii=False, indent=2), "utf-8"
                    )
                    lightrag_logger.info(f"[CLEANUP] 已删除解析缓存: {doc_id[:16]}...")
            except Exception:
                pass
    return lifecycle_result


async def _cleanup_document_vision_vectors(instance, doc_ids: list[str]) -> None:
    """Cancel pending writes, then remove vision vectors for deleted documents."""
    doc_ids = [doc_id for doc_id in doc_ids if doc_id]
    if not doc_ids:
        return

    image_processor = (getattr(instance, "modal_processors", None) or {}).get("image")
    if image_processor is not None and hasattr(
        image_processor, "cancel_pending_vision_tasks"
    ):
        try:
            await image_processor.cancel_pending_vision_tasks(set(doc_ids))
        except Exception:
            lightrag_logger.warning(
                "[CLEANUP] Unable to cancel pending vision tasks for docs=%s",
                doc_ids,
                exc_info=True,
            )

    repo = getattr(instance.lightrag, "image_vision_repo", None)
    if repo is None:
        return

    for doc_id in doc_ids:
        try:
            await repo.delete_by_doc_id(doc_id)
        except Exception:
            lightrag_logger.warning(
                "[CLEANUP] Unable to delete vision vectors for doc=%s",
                doc_id,
                exc_info=True,
            )
    try:
        await repo.flush()
    except Exception:
        lightrag_logger.warning("[CLEANUP] Unable to flush vision vectors", exc_info=True)


async def _force_cleanup_lightrag_orphans(instance, full_id: str) -> list[str]:
    """显式清理 LightRAG 内部存储中属于 full_id 的孤儿数据。

    当 LightRAG 的 ``adelete_by_doc_id`` 返回 "not_found" 时，
    LightRAG 内部的 doc_status 已丢失但 full_entities/full_relations
    等存储可能仍有残留。此函数执行尽力而为的彻底清理。

    Returns:
        已清理的存储名称列表（用于日志）。
    """
    _lg = instance.lightrag
    _cleaned: list[str] = []

    # 0. 从 full_entities 读取实体名列表，用于清理 entities_vdb 和图谱节点
    _ent_names: list[str] = []
    try:
        _ent_data = await _lg.full_entities.get_by_id(full_id)
        if _ent_data and "entity_names" in _ent_data:
            _ent_names = _ent_data["entity_names"]
    except Exception:
        pass
    # 0b. 从 full_relations 读取关系对，用于清理图谱边
    _rel_pairs: list[tuple] = []
    try:
        _rel_data = await _lg.full_relations.get_by_id(full_id)
        if _rel_data and "relation_pairs" in _rel_data:
            _rel_pairs = _rel_data["relation_pairs"]
    except Exception:
        pass

    # 1. 清理 KV 存储（full_entities / full_relations / full_docs）
    for _store_attr, _label in [
        ("full_entities", "entities"),
        ("full_relations", "relations"),
        ("full_docs", "docs"),
    ]:
        try:
            _store = getattr(_lg, _store_attr, None)
            if _store is not None:
                await _store.delete([full_id])
                _cleaned.append(_label)
        except Exception:
            pass

    # 2. VDB and graph cleanup is deferred to _purge_all_orphans(). Vector
    # store IDs are backend-specific hashes, and an entity/relation can still
    # be referenced by another document. Deleting by raw names here risks
    # removing valid shared vectors.

    # 3. 显式持久化（绕过 LightRAG finalize() 对非 cache 命名空间的 NO-OP）
    for _store in [_lg.full_entities, _lg.full_relations, _lg.full_docs]:
        try:
            await _store.index_done_callback()
        except Exception:
            pass
    try:
        if hasattr(_lg, "entities_vdb") and _lg.entities_vdb is not None:
            await _lg.entities_vdb.index_done_callback()
    except Exception:
        pass

    return _cleaned


async def _purge_all_orphans(
    instance, kb: str, *, deep_scan: bool = False, strict: bool = False
) -> dict[str, int]:
    """Reconcile persisted orphan data during explicit repair flows.

    Successful LightRAG document deletion is already targeted and must not
    call this O(KB) reconciliation routine. Callers use it only after a
    ``not_found`` recovery or through the explicit repair endpoint.

    Returns:
        {"entities": N, "relations": N, "docs": N, "vision_vectors": N}
    """
    _lg = instance.lightrag
    workspace = kb_dir(kb)  # raw string for workspace matching (see knowledge_stats)
    report: dict[str, int] = {}

    # Fetch directly from PG so an empty result is an authoritative empty
    # whitelist rather than the ambiguous empty-dict fallback returned by
    # _load_doc_status_json() during a transient storage failure.
    try:
        valid_doc_ids = await _pg_fetch_doc_ids(workspace)
    except Exception as exc:
        lightrag_logger.warning(
            "[PURGE-ORPHANS] Unable to load authoritative doc IDs for KB=%s: %s",
            kb,
            exc,
        )
        if strict:
            raise RuntimeError("authoritative doc-status lookup failed") from exc
        return report

    # ── 1. full_entities ──
    entities_data: dict = await _pg_fetch_graph_entities(workspace)
    if entities_data:
        try:
            orphan_keys = [k for k in entities_data if k not in valid_doc_ids]
            if orphan_keys:
                for _ok in orphan_keys:
                    try:
                        await _lg.full_entities.delete([_ok])
                    except Exception:
                        pass
                report["entities"] = len(orphan_keys)
        except Exception:
            pass

    # ── 2. full_relations ──
    relations_data: dict = await _pg_fetch_graph_relations(workspace)
    if relations_data:
        try:
            orphan_keys = [k for k in relations_data if k not in valid_doc_ids]
            if orphan_keys:
                for _ok in orphan_keys:
                    try:
                        await _lg.full_relations.delete([_ok])
                    except Exception:
                        pass
                report["relations"] = len(orphan_keys)
        except Exception:
            pass

    # ── 3. full_docs ──
    try:
        full_doc_ids = await _pg_fetch_full_doc_ids(workspace)
    except Exception as exc:
        lightrag_logger.warning(
            "[PURGE-ORPHANS] Unable to enumerate full docs for KB=%s: %s",
            kb,
            exc,
        )
        if strict:
            raise RuntimeError("full-document enumeration failed") from exc
        full_doc_ids = set()
    if full_doc_ids:
        try:
            orphan_keys = [k for k in full_doc_ids if k not in valid_doc_ids]
            if orphan_keys:
                for _ok in orphan_keys:
                    try:
                        await _lg.full_docs.delete([_ok])
                    except Exception:
                        pass
                report["docs"] = len(orphan_keys)
        except Exception:
            pass

    # ── 4. image_vision_repo ──
    if hasattr(_lg, "image_vision_repo") and _lg.image_vision_repo is not None:
        try:
            _repo = _lg.image_vision_repo
            # 获取当前 VDB 内的所有记录（PG/NVDB 统一接口）
            _orphan_ids = await _repo.get_orphan_ids(valid_doc_ids)
            if _orphan_ids:
                await _repo.delete_by_ids(_orphan_ids)
                await _repo.flush()
                report["vision_vectors"] = len(_orphan_ids)
        except Exception:
            pass

    # ── 5. 持久化 ──
    # ⚠️ LightRAG JsonKVStorage.finalize() 对 full_entities/full_relations/
    #    full_docs 是 NO-OP（仅 _cache 后缀才会调用 index_done_callback）。
    #    这里必须显式调用 index_done_callback() 确保内存删除落到磁盘。
    if report:
        for _store, _label in [
            (_lg.full_entities, "entities"),
            (_lg.full_relations, "relations"),
            (_lg.full_docs, "docs"),
        ]:
            try:
                await _store.index_done_callback()
            except Exception:
                pass
        try:
            # 向量库和图谱的持久化
            if hasattr(_lg, "entities_vdb") and _lg.entities_vdb is not None:
                await _lg.entities_vdb.index_done_callback()
        except Exception:
            pass
        try:
            if hasattr(_lg, "chunks_vdb") and _lg.chunks_vdb is not None:
                await _lg.chunks_vdb.index_done_callback()
        except Exception:
            pass
        lightrag_logger.info(
            "[PURGE-ORPHANS] KB=%s 清理: %s", kb,
            ", ".join(f"{k}={v}" for k, v in report.items()),
        )

    # ── 6. Optional VDB + 图谱深层扫描 ──
    # 步骤 1-3 依赖 full_entities.json 里的 doc_id → entity_names 映射来
    # 定位孤儿。但如果 full_entities 本身因为旧 bug 没写盘，实体向量会残留
    # 在 entities_vdb / relationships_vdb / 图谱中无法被追踪到。
    # 此处直接扫描 VDB 和图谱，清理所有不在 full_entities 白名单中的条目。
    if deep_scan:
        valid_entities_data = {
            doc_id: value
            for doc_id, value in entities_data.items()
            if doc_id in valid_doc_ids
        }
        valid_relations_data = {
            doc_id: value
            for doc_id, value in relations_data.items()
            if doc_id in valid_doc_ids
        }
        _vdb_purged = await _purge_orphan_vdb_entries(
            _lg, valid_entities_data, valid_relations_data
        )
        if _vdb_purged:
            for k, v in _vdb_purged.items():
                report[k] = report.get(k, 0) + v

    return report


async def _purge_orphan_vdb_entries(lg, entities_data: dict, relations_data: dict = None) -> dict[str, int]:
    """Reconcile orphan VDB and graph entries without guessing hashed IDs.

    LightRAG stores opaque vector IDs (for example ``ent-*`` hashes). The
    metadata fields identify the entity or relation, so they are the only
    safe basis for membership tests; once a row is known to be orphaned, its
    actual ``__id__`` is passed to the VDB delete operation.
    """
    report: dict[str, int] = {}
    relations_data = relations_data or {}

    valid_ent_names = {
        str(name)
        for value in entities_data.values()
        for name in value.get("entity_names", [])
        if name
    }
    valid_rel_keys = {
        f"{src}<SEP>{tgt}"
        for value in relations_data.values()
        for src, tgt in value.get("relation_pairs", [])
        if src and tgt
    }

    def _vdb_rows(vdb) -> list[dict]:
        """Return inspectable NanoVectorDB rows; opaque backends are skipped."""
        storage = getattr(vdb, "_NanoVectorDB__storage", None)
        data = storage.get("data") if isinstance(storage, dict) else None
        return [row for row in data if isinstance(row, dict)] if isinstance(data, list) else []

    if hasattr(lg, "entities_vdb") and lg.entities_vdb is not None:
        try:
            vdb = lg.entities_vdb
            orphan_ids = [
                row.get("__id__")
                for row in _vdb_rows(vdb)
                if row.get("__id__")
                and row.get("entity_name")
                and str(row["entity_name"]) not in valid_ent_names
            ]
            if orphan_ids:
                await vdb.delete(orphan_ids)
                report["entities_vdb"] = len(orphan_ids)
        except Exception as exc:
            lightrag_logger.warning("[PURGE-ORPHANS-VDB] entities_vdb scan failed: %s", exc)

    if hasattr(lg, "relationships_vdb") and lg.relationships_vdb is not None:
        try:
            vdb = lg.relationships_vdb
            orphan_ids: list[str] = []
            for row in _vdb_rows(vdb):
                vector_id = row.get("__id__")
                src = row.get("src_id")
                tgt = row.get("tgt_id")
                relation_key = (
                    f"{src}<SEP>{tgt}" if src and tgt else row.get("relation_name")
                )
                if vector_id and relation_key and str(relation_key) not in valid_rel_keys:
                    orphan_ids.append(str(vector_id))
            if orphan_ids:
                await vdb.delete(orphan_ids)
                report["relationships_vdb"] = len(orphan_ids)
        except Exception as exc:
            lightrag_logger.warning("[PURGE-ORPHANS-VDB] relationships_vdb scan failed: %s", exc)

    graph = getattr(lg, "chunk_entity_relation_graph", None)
    if graph is not None:
        try:
            graph_storage = getattr(graph, "_graph", None)
            if graph_storage is not None:
                raw_nodes = list(graph_storage.nodes())
            elif hasattr(graph, "get_all_nodes"):
                raw_nodes = graph.get_all_nodes()
                if inspect.isawaitable(raw_nodes):
                    raw_nodes = await raw_nodes
            else:
                raw_nodes = list((getattr(graph, "_node_data", None) or {}).keys())

            orphan_nodes: list[str] = []
            for node in raw_nodes or []:
                if isinstance(node, dict):
                    node_name = node.get("id") or node.get("entity_id") or node.get("name")
                else:
                    node_name = node
                node_name = str(node_name or "")
                if node_name and node_name not in valid_ent_names:
                    orphan_nodes.append(node_name)

            if orphan_nodes:
                for node_name in orphan_nodes:
                    await graph.delete_node(node_name)
                report["graph_nodes"] = len(orphan_nodes)
                if hasattr(graph, "index_done_callback"):
                    await graph.index_done_callback()
        except Exception as exc:
            lightrag_logger.warning("[PURGE-ORPHANS-VDB] graph scan failed: %s", exc)

    if report:
        for attr in ("entities_vdb", "relationships_vdb"):
            vdb = getattr(lg, attr, None)
            if vdb is not None and hasattr(vdb, "index_done_callback"):
                try:
                    await vdb.index_done_callback()
                except Exception:
                    pass

    return report


def _task_is_active_for_document_delete(task: dict[str, Any]) -> bool:
    """Keep recovery's KB liveness guard until a worker reaches a terminal state."""
    return str(task.get("status") or "").lower() not in {"completed", "failed"}


# Give a live parser time to report progress; after a restart, the in-memory
# worker registry is empty and an old PG task can otherwise block deletion.
_ORPHAN_TASK_STALE_SECONDS = 15 * 60


def _task_belongs_to_kb(task: dict[str, Any], kb: str) -> bool:
    """Require a task's persisted KB identity before allowing document cleanup."""
    task_kb = task.get("kb") or task.get("kb_name")
    return bool(task_kb) and str(task_kb) == str(kb)


def _task_updated_at(task: dict[str, Any]) -> datetime | None:
    """Normalize persisted task timestamps to an aware UTC datetime."""
    value = task.get("updated_at") or task.get("started_at")
    if isinstance(value, datetime):
        timestamp = value
    elif value:
        try:
            timestamp = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except (TypeError, ValueError):
            return None
    else:
        return None
    if timestamp.tzinfo is None:
        timestamp = timestamp.replace(tzinfo=timezone.utc)
    return timestamp.astimezone(timezone.utc)


def _has_active_worker_for_task(kb: str, task_id: str | None) -> bool:
    """Return whether this process still owns a live worker for the task."""
    if not task_id:
        return False
    for process, running_task_id in _kb_worker_procs.get(kb, []):
        if str(running_task_id) != str(task_id):
            continue
        # asyncio subprocesses expose ``returncode=None`` while running.
        return getattr(process, "returncode", None) is None
    return False


def _is_stalled_parsing_task(
    task: dict[str, Any], kb: str | None = None, task_id: str | None = None,
) -> bool:
    """Allow cleanup of a parsing task left behind after its worker vanished."""
    if kb is not None and not _task_belongs_to_kb(task, kb):
        return False
    updated_at = _task_updated_at(task)
    if updated_at is None:
        return False
    age_seconds = (datetime.now(timezone.utc) - updated_at).total_seconds()
    if age_seconds < _ORPHAN_TASK_STALE_SECONDS:
        return False
    effective_task_id = task_id or task.get("id") or task.get("task_id")
    return not _has_active_worker_for_task(str(kb or task.get("kb") or ""), effective_task_id)


def _is_orphaned_post_parse_task(
    task: dict[str, Any], doc_status: dict[str, Any],
    *, kb: str | None = None, task_id: str | None = None,
) -> bool:
    """Identify a stale task whose document record has already been removed."""
    task_file = _normalized_upload_filename(
        task.get("file_path") or task.get("file") or task.get("file_name") or ""
    )
    if not task_file:
        return False
    if any(
        isinstance(info, dict)
        and _normalized_upload_filename(info.get("file_path") or "") == task_file
        for info in doc_status.values()
    ):
        return False
    effective_task_id = task_id or task.get("id") or task.get("task_id")
    if kb is not None and _has_active_worker_for_task(kb, effective_task_id):
        return False
    phase = str(task.get("phase") or "").lower()
    if phase == "parsing":
        return _is_stalled_parsing_task(task, kb=kb, task_id=task_id)
    return phase not in {"", "queued", "initializing", "model-preflight", "parsing"}


async def _remove_document_processing_tasks(
    kb: str, doc_id: str, file_path: str,
) -> list[str]:
    """Remove task rows that would otherwise resurrect a deleted document."""
    target_file = _normalized_upload_filename(file_path)
    matching_ids = []
    for task_id, task in list(processing_tasks.items()):
        if not isinstance(task, dict) or not _task_belongs_to_kb(task, kb):
            continue
        task_doc_id = str(task.get("doc_id") or "")
        task_file = _normalized_upload_filename(
            task.get("file_path") or task.get("file") or task.get("file_name") or ""
        )
        if task_id == doc_id or task_doc_id == doc_id or (
            target_file and task_file == target_file
        ):
            matching_ids.append(task_id)

    for task_id in matching_ids:
        await delete_task(task_id)
    return matching_ids


@router.delete("/knowledge/documents/{doc_id}")
@_lease_kb_cache_for_operation
async def delete_document(doc_id: str, kb: str = Depends(verify_kb_operate_access), _perm: None = Depends(require_permission(Permission.KB_WRITE)), current_user: dict = Depends(get_current_user)):
    """删除文档 - 使用 LightRAG 的 adelete_by_doc_id 彻底清理所有关联数据"""
    instance = await get_kb(kb)
    if not instance.lightrag:
        raise HTTPException(500, "知识库未初始化")

    # PG-backed doc_status lookup
    doc_status = await _load_doc_status_json(kb) or {}

    # 通过前缀匹配找到完整 doc_id
    full_id = None
    for k in doc_status:
        if k.startswith(doc_id):
            full_id = k
            break

    if not full_id:
        # 可能是一个处理中/失败的 processing task，尝试从 processing_tasks 中移除
        task = await get_task_status(doc_id)
        if task and _task_belongs_to_kb(task, kb):
            if _task_is_active_for_document_delete(task) and not _is_orphaned_post_parse_task(
                task, doc_status, kb=kb, task_id=doc_id,
            ):
                raise HTTPException(409, "文档仍在处理中，不能删除活动任务")
            fname = task.get("file", "未知")
            _cleanup_document_files(kb, fname)
            await pg_release_upload_for_deleted_document(kb, fname)
            await delete_task(doc_id)
            await add_event("doc_delete", file=fname, doc_id=doc_id, kb=kb, source="processing_tasks", user_id=current_user["id"])
            return {"status": "deleted", "doc_id": doc_id, "file": fname, "message": "已从处理队列中移除"}
        # 也尝试按 file_path 匹配（前端可能传文件名相关的 ID）
        for tid, task in list(processing_tasks.items()):
            if _task_belongs_to_kb(task, kb) and (
                task.get("file") or task.get("file_name") or ""
            ) == doc_id:
                if _task_is_active_for_document_delete(task) and not _is_orphaned_post_parse_task(
                    task, doc_status, kb=kb, task_id=tid,
                ):
                    raise HTTPException(409, "文档仍在处理中，不能删除活动任务")
                _cleanup_document_files(kb, doc_id)
                await pg_release_upload_for_deleted_document(kb, doc_id)
                await delete_task(tid)
                await add_event("doc_delete", file=doc_id, doc_id=tid, kb=kb, source="processing_tasks", user_id=current_user["id"])
                return {"status": "deleted", "doc_id": tid, "file": doc_id, "message": "已从处理队列中移除"}
        raise HTTPException(404, f"文档 {doc_id} 不存在（知识库: {kb}）")

    file_name = doc_status[full_id].get("file_path", "未知")

    # 使用 LightRAG 的正式删除方法，彻底清理所有关联数据
    result = await _delete_lightrag_document(instance.lightrag, kb, full_id)

    await add_event("doc_delete", file=file_name, doc_id=full_id, kb=kb, user_id=current_user["id"])

    needs_orphan_repair = False
    cleanup_result = {"artifact_cleanup_pending": False}
    if result.status == "success":
        cleanup_result = _cleanup_document_files(kb, file_name, full_id) or {}
        # Clean up multimodal status cache entry for this document
        if hasattr(instance, "multimodal_status_cache") and instance.multimodal_status_cache is not None:
            try:
                await instance.multimodal_status_cache.delete([full_id])
                await instance.multimodal_status_cache.index_done_callback()
            except Exception:
                pass
        await _cleanup_document_vision_vectors(instance, [full_id])

        # adelete_by_doc_id() persists its own storage mutations via
        # LightRAG's _insert_done(). Do not finalize here: finalize_storages()
        # closes the cached instance's storage handles.
        # Invalidate query cache to prevent stale results referencing deleted data.
        from raganything.query_cache import get_query_cache
        get_query_cache().invalidate()
        await delete_document_tags(kb, full_id)
        from raganything.services.video_segments import delete_video_segments
        await delete_video_segments(kb, full_id)
        await pg_release_upload_for_deleted_document(kb, file_name)
        await _remove_document_processing_tasks(kb, full_id, file_name)
        from raganything.services.document_repair import cancel_repair_jobs
        await cancel_repair_jobs(kb, [full_id])
        from raganything.services.document_tagging import cancel_document_tagging
        await cancel_document_tagging(kb, [full_id])
        _delete_response = {"status": "deleted", "doc_id": full_id, "file": file_name, "message": result.message}
    elif result.status == "not_found":
        # Data may be partially missing (e.g. multimodal processing was
        # killed mid-flight, or LightRAG's internal doc_status is out of
        # sync with the PG LIGHTRAG_DOC_STATUS table).
        # Remove the doc_status entry via LightRAG so the user isn't stuck
        # with an undeletable ghost document, AND explicitly purge orphaned
        # entities/relations/chunks from LightRAG's internal KV stores
        # and vector DBs so KB stats reflect the actual state.
        try:
            # Remove from PG doc_status via LightRAG
            try:
                await instance.lightrag.doc_status.delete([full_id])
                await instance.lightrag.doc_status.index_done_callback()
            except Exception:
                pass
            # Clean up file system leftovers and multimodal status cache
            cleanup_result = _cleanup_document_files(kb, file_name, full_id) or {}
            if hasattr(instance, "multimodal_status_cache") and instance.multimodal_status_cache is not None:
                try:
                    await instance.multimodal_status_cache.delete([full_id])
                    await instance.multimodal_status_cache.index_done_callback()
                except Exception:
                    pass

            # ── 显式清理 LightRAG 内部存储（防止实体/关系/文块孤儿）──
            _cleaned_stores = await _force_cleanup_lightrag_orphans(instance, full_id)
            lightrag_logger.info(
                "[NOT_FOUND-CLEANUP] doc=%s 已清理存储: %s",
                full_id, ", ".join(_cleaned_stores) if _cleaned_stores else "无额外存储需清理",
            )
            await _cleanup_document_vision_vectors(instance, [full_id])
            # Invalidate query cache even for partial cleanup
            from raganything.query_cache import get_query_cache
            get_query_cache().invalidate()
            await delete_document_tags(kb, full_id)
            from raganything.services.video_segments import delete_video_segments
            await delete_video_segments(kb, full_id)
            await pg_release_upload_for_deleted_document(kb, file_name)
            await _remove_document_processing_tasks(kb, full_id, file_name)
            from raganything.services.document_repair import cancel_repair_jobs
            await cancel_repair_jobs(kb, [full_id])
            from raganything.services.document_tagging import cancel_document_tagging
            await cancel_document_tagging(kb, [full_id])
            _delete_response = {
        "status": "deleted",
        "cancelled": False,
                "doc_id": full_id,
                "file": file_name,
                "message": "文档记录已清理（部分数据不完整）",
            }
            needs_orphan_repair = True
        except Exception:
            raise HTTPException(404, f"文档 {file_name} 数据未找到")
    else:
        raise HTTPException(500, result.message)

    if needs_orphan_repair:
        try:
            await _purge_all_orphans(instance, kb, deep_scan=True)
        except Exception:
            lightrag_logger.warning(
                "[NOT_FOUND-CLEANUP] Deep orphan repair failed for doc=%s",
                full_id,
                exc_info=True,
            )
    if cleanup_result.get("artifact_cleanup_pending"):
        _delete_response["artifact_cleanup_pending"] = True
    return _delete_response


@router.post("/knowledge/documents/batch-delete")
@_lease_kb_cache_for_operation
async def batch_delete_documents(req: BatchDeleteRequest, kb: str = Depends(verify_kb_operate_access), _perm: None = Depends(require_permission(Permission.KB_WRITE)), current_user: dict = Depends(get_current_user)):
    """批量删除文档 - 一次请求删除多个文档"""
    instance = await get_kb(kb)
    if not instance.lightrag:
        raise HTTPException(500, "知识库未初始化")

    # PG-backed doc_status lookup
    doc_status = await _load_doc_status_json(kb) or {}

    deleted = []
    not_found = []
    errors = []

    deleted_full_ids: list[str] = []  # for multimodal_status_cache batch cleanup
    not_found_full_ids: list[str] = []  # for LightRAG orphan cleanup
    artifact_cleanup_pending: list[str] = []

    for doc_id in req.doc_ids:
        full_id = None
        for k in doc_status:
            if k.startswith(doc_id):
                full_id = k
                break

        if not full_id:
            # Try processing_tasks
            task = await get_task_status(doc_id)
            if task and _task_belongs_to_kb(task, kb):
                if _task_is_active_for_document_delete(task) and not _is_orphaned_post_parse_task(
                    task, doc_status, kb=kb, task_id=doc_id,
                ):
                    errors.append({"doc_id": doc_id, "error": "文档仍在处理中，不能删除活动任务"})
                    continue
                task_file = task.get("file") or task.get("file_name") or ""
                _cleanup_document_files(kb, task_file)
                await pg_release_upload_for_deleted_document(kb, task_file)
                await delete_task(doc_id)
                await add_event("doc_delete", file=task.get("file", "?"), doc_id=doc_id, kb=kb, source="processing_tasks", user_id=current_user["id"])
                deleted.append(doc_id)
            else:
                not_found.append(doc_id)
            continue

        try:
            file_name = doc_status[full_id].get("file_path", "未知")
            result = await _delete_lightrag_document(instance.lightrag, kb, full_id)
            if result.status in ("success", "not_found"):
                del doc_status[full_id]
                deleted.append(doc_id)
                deleted_full_ids.append(full_id)
                cleanup_result = _cleanup_document_files(kb, file_name, full_id) or {}
                if cleanup_result.get("artifact_cleanup_pending"):
                    artifact_cleanup_pending.append(full_id)
                await pg_release_upload_for_deleted_document(kb, file_name)
                await _remove_document_processing_tasks(kb, full_id, file_name)
                await add_event("doc_delete", file=file_name, doc_id=full_id, kb=kb, user_id=current_user["id"])
                if result.status == "not_found":
                    not_found_full_ids.append(full_id)
                    # Remove from PG doc_status via LightRAG
                    try:
                        await instance.lightrag.doc_status.delete([full_id])
                        await instance.lightrag.doc_status.index_done_callback()
                    except Exception:
                        pass
            else:
                errors.append({"doc_id": doc_id, "error": result.message})
        except Exception as e:
            errors.append({"doc_id": doc_id, "error": str(e)})

    # ── 对 "not_found" 文档执行 LightRAG 深层存储清理 ──
    for _nf_id in not_found_full_ids:
        try:
            _cleaned = await _force_cleanup_lightrag_orphans(instance, _nf_id)
            lightrag_logger.info(
                "[BATCH-NOT_FOUND-CLEANUP] doc=%s 已清理存储: %s",
                _nf_id, ", ".join(_cleaned) if _cleaned else "无额外存储需清理",
            )
        except Exception:
            pass

    # Clean up multimodal status cache entries for deleted documents
    if deleted_full_ids and hasattr(instance, "multimodal_status_cache") and instance.multimodal_status_cache is not None:
        try:
            await instance.multimodal_status_cache.delete(deleted_full_ids)
            await instance.multimodal_status_cache.index_done_callback()
        except Exception:
            pass

    # Success and not_found recoveries both remove the document record, so
    # clean each document's vision vectors directly and flush once per batch.
    await _cleanup_document_vision_vectors(instance, deleted_full_ids)
    for deleted_document_id in deleted_full_ids:
        await delete_document_tags(kb, deleted_document_id)
        from raganything.services.video_segments import delete_video_segments
        await delete_video_segments(kb, deleted_document_id)
    if deleted_full_ids:
        from raganything.services.document_repair import cancel_repair_jobs
        await cancel_repair_jobs(kb, deleted_full_ids)
        from raganything.services.document_tagging import cancel_document_tagging
        await cancel_document_tagging(kb, deleted_full_ids)

    # PG-backed: doc_status is already updated via LightRAG; no JSON file to write

    # adelete_by_doc_id() persists its own storage mutations. Keep the cached
    # instance alive and only invalidate query results after a successful batch.
    if deleted:
        from raganything.query_cache import get_query_cache
        get_query_cache().invalidate()

    if not_found_full_ids:
        try:
            await _purge_all_orphans(instance, kb, deep_scan=True)
        except Exception:
            lightrag_logger.warning(
                "[BATCH-NOT_FOUND-CLEANUP] Deep orphan repair failed for docs=%s",
                not_found_full_ids,
                exc_info=True,
            )

    return {"deleted": deleted, "not_found": not_found, "errors": errors,
            "artifact_cleanup_pending": artifact_cleanup_pending,
            "total_deleted": len(deleted), "total_failed": len(errors)}


@router.post("/knowledge/documents/{doc_id}/retry")
@_lease_kb_mutation_for_operation("retry")
async def retry_document(doc_id: str, kb: str = Depends(verify_kb_operate_access), _perm: None = Depends(require_permission(Permission.KB_WRITE)), current_user: dict = Depends(get_current_user), background_tasks: BackgroundTasks = None):
    """重试处理失败的文档 — PG-backed"""
    await _ensure_vision_index_mutable(kb)
    vlm_snapshot = await _resolve_upload_vlm_snapshot(current_user["id"])
    # PG-backed doc_status lookup
    data = await _load_doc_status_json(kb)
    if not data:
        raise HTTPException(404, "文档不存在")

    full_id = None
    file_name = None
    for k, v in data.items():
        if k.startswith(doc_id):
            full_id = k
            file_name = v.get("file_path", "")
            if v.get("status") != "failed":
                raise HTTPException(400, "只能重试处理失败的文档")
            break

    if not full_id:
        raise HTTPException(404, "文档不存在")

    stored_metadata = data.get(full_id, {}).get("metadata") or {}
    stored_strategy = (
        stored_metadata.get("chunking_strategy")
        if isinstance(stored_metadata, dict)
        else ""
    )
    actual_strategy = _resolve_chunking_strategy(stored_strategy) or "recursive"

    # Preserve durable text chunks and repair graph enrichment in place.
    if int(data.get(full_id, {}).get("chunks_count") or 0) > 0:
        from raganything.services.document_repair import prepare_document_repair

        try:
            repair = await prepare_document_repair(
                kb,
                full_id,
                error=data.get(full_id, {}).get("error_msg", ""),
            )
        except ValueError:
            repair = None
        if repair is not None:
            return {
                "status": "queued",
                "outcome": "degraded",
                "doc_id": full_id,
                "filename": file_name,
                "repair_job": repair["job"],
                "message": "文本内容已可用，图谱补偿已加入队列",
            }

    # 查找原始文件路径
    upload_dir = Path("./uploads")
    file_path = upload_dir / file_name
    if not file_path.exists():
        # 尝试从 doc_status 获取完整路径
        file_path = Path(file_name) if Path(file_name).exists() else None
    if not file_path or not file_path.exists():
        raise HTTPException(404, f"原始文件不存在: {file_name}")

    # A retried v2 video must rebuild its controlled catalog from the same
    # immutable snapshot; stale partial rows are never kept as playable media.
    from raganything.services.video_segments import delete_video_segments
    await delete_video_segments(kb, full_id)

    # A retry must replace its previous ODL generation through the registry
    # before it removes the failed doc_status.  This prevents an old retry from
    # leaving two active runs or deleting a newer run by filename prefix.
    output_base = "./output" if kb == "default" else f"./output_{kb}"
    legacy_registry_file = Path(output_base) / ".odl-artifact-registry.sqlite3"
    from raganything.services.odl_artifact_lifecycle import configured_odl_artifact_root

    artifact_root = configured_odl_artifact_root()
    registry_file = (
        artifact_root / ".odl-artifact-registry.sqlite3"
        if artifact_root is not None
        else None
    )
    if legacy_registry_file.is_file():
        raise HTTPException(
            409,
            "OpenDataLoader legacy artifact root is retained for controlled cleanup; "
            "retry cannot use filename-based deletion",
        )
    if registry_file is not None and registry_file.is_file():
        from raganything.services.odl_artifact_lifecycle import (
            ArtifactLifecycleCapabilityError,
            ArtifactOwner,
            OpenDataLoaderArtifactLifecycle,
        )

        lifecycle = OpenDataLoaderArtifactLifecycle(artifact_root)
        owner = ArtifactOwner(kb, full_id)
        record = lifecycle.get(owner)
        if record is not None and record.state != "deleted":
            if record.state != "active":
                raise HTTPException(
                    409,
                    "OpenDataLoader artifact cleanup is pending; recover it before retrying",
                )
            workers_exited = all(
                getattr(process, "returncode", None) is not None
                for process, _task_id in _kb_worker_procs.get(kb, [])
            )
            try:
                lifecycle.delete(
                    owner,
                    expected_generation=record.generation,
                    worker_exited=workers_exited,
                )
            except ArtifactLifecycleCapabilityError as exc:
                raise HTTPException(
                    409,
                    "odl_artifact_cleanup_unsupported_windows: artifact retained for controlled cleanup",
                ) from exc

    # 删除旧的失败记录 via LightRAG PG (trigger reprocessing)
    # Create the retry's immutable snapshot before changing the failed
    # document state. A missing PostgreSQL snapshot must not leave the old
    # record deleted with no runnable replacement task.
    task_id = str(uuid.uuid4())
    try:
        await _create_upload_settings_snapshot(
            task_id, int(current_user["id"]), chunking_strategy=actual_strategy,
        )
    except RuntimeError as exc:
        raise HTTPException(
            503,
            {"code": "settings_snapshot_unavailable", "message": "unable to create task settings snapshot"},
        ) from exc

    try:
        kb_instance = await get_kb(kb)
        if kb_instance and kb_instance.lightrag:
            await kb_instance.lightrag.doc_status.delete([full_id])
            await kb_instance.lightrag.doc_status.index_done_callback()
    except Exception:
        pass
    del data[full_id]

    # 推入 per-KB 处理队列（统一排队）
    from .shared import _enqueue_upload_task
    task_info = {
        "task_id": task_id,
        "file_path": str(file_path.absolute()),
        "filename": file_name,
        "kb_name": kb,
        "chunking_strategy": actual_strategy,
        "user_id": current_user["id"],
        "vision_vlm_profile_id": vlm_snapshot.profile.id,
        "vision_vlm_profile_fingerprint": vlm_snapshot.fingerprint,
        "settings_snapshot_id": task_id,
    }
    await upsert_task_state(
        task_id,
        {
            "id": task_id,
            "file": file_name,
            "status": "queued",
            "started_at": datetime.now(timezone.utc).isoformat(),
            "progress": 0,
            "kb": kb,
            "user_id": current_user["id"],
            "phase": "queued",
            "phase_status": "queued",
            "message": "Retry queued",
            "chunking_strategy": actual_strategy,
        },
    )
    try:
        file_hash = _compute_file_hash(str(file_path))
        await pg_update_upload_status(
            file_hash,
            kb,
            "queued",
            task_id=task_id,
            error_message="",
        )
    except Exception:
        lightrag_logger.warning(
            "[RETRY] Could not reset uploaded_files state for file=%s kb=%s",
            file_name,
            kb,
            exc_info=True,
        )
    queue, qsize = await _enqueue_upload_task(task_info)
    await add_event(
        "upload_retry_queued",
        file=file_name,
        task_id=task_id,
        kb=kb,
        user_id=current_user["id"],
    )
    return {"status": "queued", "task_id": task_id, "filename": file_name,
            "chunking_strategy": actual_strategy,
            "position": qsize + 1, "queue_size": qsize + 1,
            "message": "文档已加入处理队列"}


@router.post("/kb/{kb_name}/reprocess-multimodal")
async def reprocess_multimodal(
    kb_name: str,
    background_tasks: BackgroundTasks,
    _perm: None = Depends(require_permission(Permission.KB_WRITE)),
    current_user: dict = Depends(get_current_user),
):
    """回溯处理知识库中文档的多模态内容（图片/表格/公式）。

    扫描 KB 中 ``multimodal_processed`` 不为 ``true`` 的文档，从原始文件
    重新解析（优先走解析缓存），仅执行多模态处理——不重新插入文本。
    """
    await verify_kb_operate_access(kb_name, current_user)
    await _ensure_vision_index_mutable(kb_name)
    try:
        # Scan first to get count — PG-backed
        all_docs = await _load_doc_status_json(kb_name)
        total = sum(
            1 for info in all_docs.values()
            if info.get("status") != "failed"
            and not is_multimodal_processed(info)
        )

        if total == 0:
            return {
                "status": "ok", "processed": 0, "skipped": 0, "total": 0,
                "message": "所有文档已完成多模态处理",
            }

        task_id = str(uuid.uuid4())
        try:
            await _create_upload_settings_snapshot(task_id, int(current_user["id"]), kb=kb_name)
        except RuntimeError as exc:
            raise HTTPException(
                503,
                {"code": "settings_snapshot_unavailable", "message": "unable to create task settings snapshot"},
            ) from exc
        # Schedule background processing from the immutable task snapshot.
        background_tasks.add_task(
            _reprocess_multimodal_for_kb,
            kb_name,
            user_id=current_user.get("id", 1),
            task_id=task_id,
        )
        return {
            "status": "queued", "task_id": task_id, "total": total,
            "message": f"已排队 {total} 个文档，后台处理中。通过 WebSocket 获取进度更新。",
        }
    except ValueError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        lightrag_logger.error(f"[REPROCESS-API] 回溯处理失败 kb={kb_name}: {e}")
        raise HTTPException(500, f"回溯处理失败: {e}")

# ── KB management handlers ─────────────────────────────

@router.get("/kb/list")
async def list_kbs(current_user: dict = Depends(get_current_user)):
    started_at = time.perf_counter()
    meta = await load_kb_meta()
    kbs = []
    is_admin = current_user.get("is_admin", False)
    allowed_kbs = set(current_user.get("allowed_kbs", []))
    for name, info in meta.items():
        # 数据隔离：普通用户只看自己的 KB，管理员看全部
        owner_id = info.get("owner_id")
        if owner_id is not None and owner_id != current_user["id"] and name not in allowed_kbs and not is_admin:
            continue
        kbs.append({
            "name": name,
            "label": info.get("name", name),
            "created": info.get("created", ""),
            "updated_at": info.get("updated_at", ""),
            "owner_id": owner_id,
            "owner_username": info.get("owner_username", ""),
            "active": name == _shared.active_kb,
            "capabilities": _kb_editor_capabilities_from_metadata(info, current_user),
        })
    # 新用户没有 KB 时自动创建个人 KB 并初始化存储
    if not kbs and not is_admin and await _auth_has_permission(current_user["id"], Permission.KB_WRITE):
        personal_kb = current_user["username"]
        label = f"{current_user['username']}的知识库"
        meta[personal_kb] = {
            "name": label, "created": datetime.now(timezone.utc).isoformat(),
            "owner_id": current_user["id"],
            "owner_username": current_user["username"],
        }
        await save_kb_meta(meta)
        _shared.active_kb = personal_kb
        # 初始化存储目录
        await get_kb(personal_kb)
        kbs.append({
            "name": personal_kb,
            "label": label,
            "created": meta[personal_kb]["created"],
            "updated_at": meta[personal_kb]["created"],
            "owner_id": current_user["id"],
            "owner_username": current_user["username"],
            "active": True,
            "capabilities": _kb_editor_capabilities_from_metadata(meta[personal_kb], current_user),
        })

    visible_names = [kb["name"] for kb in kbs]
    stats_by_name: dict[str, dict[str, int]] = {}
    if visible_names:
        try:
            stats_result = await asyncio.wait_for(
                _compute_kb_stats_batch_fast(visible_names),
                timeout=KB_STATS_BATCH_TIMEOUT_SECONDS,
            )
        except Exception:
            lightrag_logger.warning("KB stats batch failed", exc_info=True)
            stats_result = {}
        if isinstance(stats_result, dict):
            stats_by_name = stats_result

    for kb in kbs:
        kb["stats"] = stats_by_name.get(kb["name"], _stats_unavailable_payload())
        last_updated_at = kb["updated_at"] or kb["created"] or ""
        kb["last_updated_at"] = last_updated_at
        # Retain the legacy key while clients migrate to the generic KB update time.
        kb["last_content_updated_at"] = last_updated_at

    elapsed_ms = (time.perf_counter() - started_at) * 1000
    lightrag_logger.info(
        "[KB-LIST] user=%s visible_kbs=%s stats_embedded=%s elapsed_ms=%.1f",
        current_user.get("username", "?"),
        len(kbs),
        len(stats_by_name),
        elapsed_ms,
    )
    return {"knowledge_bases": kbs, "active": _shared.active_kb}


@router.get("/kb/{kb}/editor")
async def get_kb_editor(
    kb: str,
    current_user: dict = Depends(get_current_user),
):
    """Return one editor-safe KB view, including immutable owner context."""
    metadata, capabilities = await _require_kb_editor_access(kb, current_user)
    from raganything.services.auth import get_user_role
    from raganything.services.pg_auth_repo import pg_list_kb_members

    owner_role = await get_user_role(int(metadata.get("owner_id") or 0))
    owner = {
        "id": metadata.get("owner_id"),
        "username": metadata.get("owner_username", ""),
        "role_name": (owner_role or {}).get("name", ""),
        "is_owner": True,
        "removable": False,
        "effective_access": "owner",
    }
    return {
        "kb": kb,
        "internal_name": kb,
        "label": metadata.get("name", kb),
        "updated_at": metadata.get("updated_at", ""),
        "owner": owner,
        "members": await pg_list_kb_members(kb),
        "capabilities": capabilities,
    }


@router.patch("/kb/{kb}/metadata")
async def update_kb_metadata(
    kb: str,
    payload: KBMetadataUpdate,
    current_user: dict = Depends(get_current_user),
):
    """Rename only the presentation label; the internal KB identity is immutable."""
    metadata, _capabilities = await _require_kb_editor_access(kb, current_user)
    from raganything.services.pg_kb_meta_repo import pg_update_kb_display_name

    try:
        updated = await pg_update_kb_display_name(
            kb,
            payload.display_name,
            payload.expected_updated_at,
        )
    except KeyError as exc:
        raise HTTPException(404, "knowledge base not found") from exc
    except ValueError as exc:
        raise HTTPException(422, {"code": "invalid_display_name", "message": str(exc)}) from exc
    if updated is None:
        raise HTTPException(409, {"code": "metadata_conflict", "message": "knowledge-base metadata has changed"})
    await audit_log(
        int(current_user["id"]),
        "kb.display_name.updated",
        details={
            "kb": kb,
            "previous_label": metadata.get("name", kb),
            "label": updated["label"],
        },
    )
    return updated


@router.get("/kb/{kb}/members")
async def list_kb_members(
    kb: str,
    current_user: dict = Depends(get_current_user),
):
    metadata, capabilities = await _require_kb_editor_access(kb, current_user)
    from raganything.services.auth import get_user_role
    from raganything.services.pg_auth_repo import pg_list_kb_members

    owner_role = await get_user_role(int(metadata.get("owner_id") or 0))
    owner = {
        "id": metadata.get("owner_id"),
        "username": metadata.get("owner_username", ""),
        "role_name": (owner_role or {}).get("name", ""),
        "is_owner": True,
        "removable": False,
        "effective_access": "owner",
    }
    return {
        "kb": kb,
        "updated_at": metadata.get("updated_at", ""),
        "members": [owner, *await pg_list_kb_members(kb)],
        "capabilities": capabilities,
    }


@router.get("/kb/{kb}/member-candidates")
async def search_kb_member_candidates(
    kb: str,
    q: str = QueryParam(...),
    page: int = QueryParam(1, ge=1),
    page_size: int = QueryParam(20, ge=1, le=50),
    current_user: dict = Depends(get_current_user),
):
    _metadata, _capabilities = await _require_kb_editor_access(kb, current_user)
    from raganything.services.pg_auth_repo import pg_search_kb_member_candidates

    try:
        return await pg_search_kb_member_candidates(
            kb, q, actor_id=int(current_user["id"]), page=page, page_size=page_size,
        )
    except ValueError as exc:
        raise HTTPException(422, {"code": "invalid_member_search", "message": str(exc)}) from exc


@router.put("/kb/{kb}/members/{user_id}")
async def upsert_kb_member(
    kb: str,
    user_id: int,
    payload: KBMemberGrantUpdate,
    current_user: dict = Depends(get_current_user),
):
    _metadata, _capabilities = await _require_kb_editor_access(kb, current_user)
    from raganything.services.pg_auth_repo import pg_upsert_kb_member_grant

    try:
        member = await pg_upsert_kb_member_grant(
            kb, user_id, payload.access_level, actor_id=int(current_user["id"]),
        )
    except KeyError as exc:
        raise HTTPException(404, "knowledge base not found") from exc
    except PermissionError as exc:
        raise HTTPException(403, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(422, {"code": "invalid_member_grant", "message": str(exc)}) from exc
    return {"kb": kb, "member": member}


@router.delete("/kb/{kb}/members/{user_id}")
async def revoke_kb_member(
    kb: str,
    user_id: int,
    current_user: dict = Depends(get_current_user),
):
    _metadata, _capabilities = await _require_kb_editor_access(kb, current_user)
    from raganything.services.pg_auth_repo import pg_revoke_kb_member_grant

    try:
        await pg_revoke_kb_member_grant(kb, user_id, actor_id=int(current_user["id"]))
    except KeyError as exc:
        raise HTTPException(404, "knowledge base not found") from exc
    except PermissionError as exc:
        raise HTTPException(403, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(422, {"code": "invalid_member_grant", "message": str(exc)}) from exc
    return {"status": "revoked", "kb": kb, "user_id": user_id}


@router.post("/kb/create")
async def create_kb(kb_name: str = QueryParam(...), _perm: None = Depends(require_permission(Permission.KB_WRITE)), current_user: dict = Depends(get_current_user), label: str = QueryParam(""), domain: str = QueryParam("general")):
    meta = await load_kb_meta()
    if kb_name in meta:
        raise HTTPException(400, f"知识库 '{kb_name}' 已存在")
    label = label or kb_name
    from raganything.services import vision_models
    vision_defaults = await vision_models.get_platform_defaults()
    embedding_profile_id = (
        vision_defaults.get("vision_embedding_profile_id")
        or "legacy-doubao-embedding"
    )
    try:
        embedding_profile = vision_models.get_entry(embedding_profile_id, "embedding")
    except KeyError as exc:
        raise HTTPException(503, "平台默认视觉向量模型不可用") from exc
    meta[kb_name] = {
        "name": label, "created": datetime.now(timezone.utc).isoformat(),
        "owner_id": current_user["id"],
        "owner_username": current_user["username"],
        "domain": domain,
        "extra": {
            "vision_embedding": {
                "profile_id": embedding_profile_id,
                "profile_fingerprint": embedding_profile.fingerprint,
                "embedding_dim": embedding_profile.profile.embedding_dim,
                "index_state": "idle",
                "target_profile_id": None,
                "task": None,
            }
        },
    }
    await save_kb_meta(meta)
    # 预加载
    await get_kb(kb_name)
    return {"status": "created", "name": kb_name, "label": label}


@router.put("/kb/switch")
async def switch_kb(name: str = QueryParam(...), current_user: dict = Depends(get_current_user)):
    meta = await load_kb_meta()
    if name not in meta:
        raise HTTPException(404, f"知识库 '{name}' 不存在")
    # 权限检查（管理员可切换任意 KB）
    kb_info = meta[name]
    owner_id = kb_info.get("owner_id")
    if owner_id is not None and owner_id != current_user["id"] and name not in set(current_user.get("allowed_kbs", [])) and not current_user.get("is_admin"):
        raise HTTPException(403, "无权访问该知识库")
    _shared.active_kb = name
    return {"status": "switched", "active": name}


@router.delete("/kb/{name}")
async def delete_kb(name: str, _perm: None = Depends(require_permission(Permission.KB_DELETE)), current_user: dict = Depends(get_current_user)):
    """删除知识库 — 清理所有资源（Worker 进程、队列、缓存、文件、元数据）。

    委托给 ``cleanup_kb_resources()`` 统一处理，确保不遗漏任何状态。
    """
    if name == "default":
        raise HTTPException(400, "不能删除默认知识库")
    meta = await load_kb_meta()
    if name not in meta:
        raise HTTPException(404, f"知识库 '{name}' 不存在")
    # 权限检查（仅 KB 所有者和管理员可删除）
    kb_info = meta[name]
    owner_id = kb_info.get("owner_id")
    if owner_id is not None and owner_id != current_user["id"] and not current_user.get("is_admin"):
        raise HTTPException(403, "无权删除该知识库")

    await cleanup_kb_resources(name)
    await delete_kb_tags(name)
    from raganything.services.document_tagging import delete_kb_tag_jobs
    await delete_kb_tag_jobs(name)
    return {"status": "deleted", "name": name}


# ── Vision Embedding Image Search ────────────────────────

@router.post("/image-search")
async def image_search(
    request: Request,
    image: UploadFile = File(...),
    top_k: int = QueryParam(10, ge=1, le=50),
    kb: str = Depends(verify_kb_access),
    current_user: dict = Depends(get_current_user),
):
    """搜索视觉相似图片 — 上传图片，返回知识库中视觉最相似的图片列表。

    需要配置 ``VISION_EMBEDDING_MODEL`` 环境变量且 ``VISION_SEARCH_ENABLED=true``。
    如果未启用，返回 501。
    """
    kb_metadata = (await load_kb_meta()).get(kb, {})
    vision_state = (kb_metadata.get("extra") or {}).get("vision_embedding") or {}
    if not vision_state.get("profile_id") or not vision_state.get("profile_fingerprint"):
        raise HTTPException(
            501,
            "视觉搜索功能未启用。请设置环境变量 VISION_SEARCH_ENABLED=true 并配置 VISION_EMBEDDING_MODEL。",
        )

    instance = await get_kb(kb)
    if not instance.lightrag:
        raise HTTPException(500, "知识库未初始化")

    repo = getattr(instance.lightrag, 'image_vision_repo', None)
    vision_func = getattr(instance, 'vision_embed_func', None)

    if repo is None or vision_func is None:
        raise HTTPException(
            503,
            detail={
                "code": "profile_unavailable",
                "message": "当前视觉向量模型不可用",
            },
        )

    # Reload VDB from disk to pick up data written by worker subprocesses
    await repo.reload()

    # Save uploaded image to temp file
    import tempfile
    import os as _os

    suffix = _os.path.splitext(image.filename or "image.jpg")[1] or ".jpg"
    tmp_fd, tmp_path = tempfile.mkstemp(suffix=suffix)
    try:
        with open(tmp_fd, "wb") as f:
            content = await image.read()
            f.write(content)

        # Compute vision embedding for query image
        vec = await vision_func.embed_image(tmp_path)
        if vec is None:
            raise HTTPException(
                400, "无法从上传图片中提取视觉特征，请确认图片格式正确。"
            )

        # Query similar images, then convert only catalog-owned matches to the
        # path-free media contract. A vision-vector path is never API authority.
        results = await repo.query(vec, top_k=top_k)
        statuses = await _load_doc_status_json(kb)
        catalog: list[dict[str, Any]] = []
        for status in statuses.values():
            metadata = status.get("metadata") if isinstance(status, dict) else None
            entries = metadata.get("odl_media_catalog") if isinstance(metadata, dict) else None
            if isinstance(entries, list):
                catalog.extend(entry for entry in entries if isinstance(entry, dict))

        from raganything.services.odl_media_delivery import catalog_media_payload

        controlled_results = []
        for result in results:
            if not isinstance(result, dict):
                continue
            payload = catalog_media_payload(
                catalog,
                kb_name=kb,
                path=str(result.get("image_path") or ""),
            )
            if payload is None:
                continue
            controlled_results.append({
                **payload,
                "entity_name": str(result.get("entity_name") or ""),
                "description": str(result.get("description") or ""),
                "score": round(float(result.get("_score") or 0), 3),
            })

        return {
            "query": image.filename,
            "results": controlled_results,
            "count": len(controlled_results),
            "repo_count": repo.count(),
        }
    finally:
        try:
            _os.unlink(tmp_path)
        except OSError:
            pass


# ── File serving ───────────────────────────────────────

def _resolve_controlled_video_path(server_path: object) -> Path | None:
    """Revalidate a worker-recorded video path under controlled upload roots."""
    if not isinstance(server_path, str) or not server_path:
        return None
    roots = [Path.cwd() / "uploads"]
    roots.extend(Path(item) for item in os.environ.get("VIDEO_ASSET_ROOTS", "").split(os.pathsep) if item)
    try:
        candidate = Path(server_path)
        if not candidate.is_absolute() or candidate.is_symlink():
            return None
        resolved = candidate.resolve(strict=True)
        if not resolved.is_file() or resolved.suffix.lower() not in {".mp4", ".webm", ".mov", ".mkv", ".avi"}:
            return None
        for root in roots:
            controlled_root = root.resolve(strict=True)
            if controlled_root.is_symlink():
                continue
            try:
                resolved.relative_to(controlled_root)
            except ValueError:
                continue
            return resolved
    except (OSError, RuntimeError, ValueError):
        return None
    return None

@router.get("/knowledge/media/{media_id}")
async def serve_odl_media(
    media_id: str,
    kb: str = QueryParam(...),
    _perm: None = Depends(require_permission(Permission.KB_READ)),
    current_user: dict = Depends(get_current_user),
):
    """Serve one persisted ODL asset after KB-scoped authorization."""
    actual_kb = await verify_kb_access(kb, current_user)
    from raganything.services.odl_media_delivery import resolve_catalog_media

    records = await _load_doc_status_json(actual_kb)
    resolved = []
    for status in records.values():
        metadata = status.get("metadata") if isinstance(status, dict) else None
        media = resolve_catalog_media(
            metadata.get("odl_media_catalog") if isinstance(metadata, dict) else None,
            kb_name=actual_kb,
            media_id=media_id,
        )
        if media is not None:
            resolved.append(media)
    if len(resolved) == 1:
        media = resolved[0]
        return FileResponse(
            str(media.path), media_type=media.mime,
            headers={"Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff"},
        )
    if len(resolved) > 1:
        raise HTTPException(404, "media unavailable")

    from raganything.services.video_segments import get_video_asset
    try:
        asset = await get_video_asset(actual_kb, media_id)
    except Exception:
        # A media lookup outage must not turn an arbitrary media ID into a
        # backend detail leak, and cannot grant access without the catalog row.
        asset = None
    path = _resolve_controlled_video_path(asset.get("server_path") if asset else None)
    if asset is None or path is None:
        raise HTTPException(404, "media unavailable")
    import mimetypes
    media_type = mimetypes.guess_type(path.name)[0] or "video/mp4"
    if not media_type.startswith("video/"):
        raise HTTPException(404, "media unavailable")
    # FileResponse implements HTTP Range for browser seeks in supported Starlette.
    return FileResponse(
        str(path), media_type=media_type,
        headers={"Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff"},
    )


@router.get("/knowledge/media/legacy/{grant}")
async def serve_legacy_odl_media(
    grant: str,
    kb: str = QueryParam(...),
    _perm: None = Depends(require_permission(Permission.KB_READ)),
    current_user: dict = Depends(get_current_user),
):
    """Serve a short-lived grant created from a persisted KB chunk marker."""
    actual_kb = await verify_kb_access(kb, current_user)
    from raganything.services.odl_media_delivery import resolve_legacy_media_grant

    media = resolve_legacy_media_grant(actual_kb, grant)
    if media is None:
        raise HTTPException(404, "media unavailable")
    return FileResponse(
        str(media.path),
        media_type=media.mime,
        headers={
            "Cache-Control": "private, no-store",
            "X-Content-Type-Options": "nosniff",
        },
    )


@router.get("/files/image")
async def serve_image():
    """Retired raw-path endpoint; use KB-scoped opaque media IDs."""
    raise HTTPException(410, "raw-path image delivery is unavailable")
