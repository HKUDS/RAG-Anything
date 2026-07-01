"""Knowledge Router — /api/upload/*, /api/knowledge/*, /api/kb/*, /api/files/image"""

import asyncio
import json
import os
import re
import secrets
import uuid
import shutil
from datetime import datetime
from pathlib import Path

import httpx
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Request, BackgroundTasks, Query as QueryParam
from fastapi.responses import FileResponse
from pydantic import BaseModel
from typing import Optional

# Import shared module-level state (for read access)
from raganything.services.state_service import (
    upsert_task_state, complete_task, delete_task, get_task_status,
)
from .shared import (
    limiter,
    verify_kb_access,
    get_current_user,
    CHUNKING_STRATEGY,
    _process_uploaded_file,
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
    pg_register_upload,
    pg_update_upload_status,
    _load_doc_status_json,
    _load_full_docs_json,
)
from raganything.dependencies import get_current_user, get_optional_user, get_current_user_from_token, require_permission
from raganything.permissions import Permission
from raganything.chunking import build_chunking_func, STRATEGY_META as CHUNKING_STRATEGY_META

# Module reference for writing to shared mutable state (active_kb)
from . import shared as _shared

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


# ── Upload handlers ────────────────────────────────────

@router.post("/upload")
@limiter.limit("30/minute")
async def upload_file(request: Request, file: UploadFile = File(...), background_tasks: BackgroundTasks = None,
                       kb: str = Depends(verify_kb_access), chunking_strategy: str = "",
                       enable_image: str = "", enable_table: str = "",
                       enable_equation: str = "", enable_video: str = "",
                       current_user: dict = Depends(get_current_user)):
    """Upload a single file — immediate return, background processing"""
    task_id = str(uuid.uuid4())[:8]
    upload_dir = Path("./uploads")
    upload_dir.mkdir(exist_ok=True)
    safe_name = os.path.basename(file.filename)
    file_path = upload_dir / safe_name
    content = await file.read()
    file_path.write_bytes(content)
    file_size = len(content)

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
        raise HTTPException(
            409,
            f"文件正在处理中 (task_id={existing_task})",
        )

    # Register file metadata in PG (dedup enforced by UNIQUE on file_hash + kb_name)
    pg_id = await pg_register_upload(
        filename=safe_name,
        file_path=str(file_path.absolute()),
        file_hash=file_hash,
        file_size=file_size,
        kb_name=kb,
        uploaded_by=current_user.get("id", 0),
    )
    if pg_id is None:
        # PG insert failed — either a true duplicate or PG unavailable.
        # Clean up the written file and report the conflict.
        try:
            file_path.unlink(missing_ok=True)
        except OSError:
            pass
        raise HTTPException(
            409,
            f"文件内容重复或上传注册失败: {file.filename}",
        )

    lightrag_logger.info(f"[UPLOAD-API] 收到上传请求: file={file.filename} kb={kb} strategy={chunking_strategy}")

    # Register for dedup tracking BEFORE spawning the background task
    _register_processing_file(kb, file_hash, task_id)

    # 推入 per-KB 处理队列（统一排队，防止并发竞争 LightRAG 存储）
    from .shared import _ensure_queue_draining
    task_info = {
        "task_id": task_id,
        "file_path": str(file_path.absolute()),
        "filename": file.filename,
        "kb_name": kb,
        "chunking_strategy": chunking_strategy,
        "user_id": current_user["id"],
        "enable_image": enable_image.lower() == "true" if enable_image else None,
        "enable_table": enable_table.lower() == "true" if enable_table else None,
        "enable_equation": enable_equation.lower() == "true" if enable_equation else None,
        "enable_video": enable_video.lower() == "true" if enable_video else None,
    }
    queue, qsize = await _ensure_queue_draining(kb)
    queue.put_nowait(task_info)
    strategy_name = CHUNKING_STRATEGY_META.get(chunking_strategy or CHUNKING_STRATEGY, {}).get('name', '默认')
    return {"task_id": task_id, "filename": file.filename, "status": "queued", "kb": kb,
            "chunking_strategy": chunking_strategy or CHUNKING_STRATEGY,
            "position": qsize + 1, "queue_size": qsize + 1,
            "message": f"文档已加入队列（第 {qsize + 1} 位），使用{strategy_name}分块。请到知识库页面查看进度。"}


@router.post("/upload/batch")
@limiter.limit("20/minute")
async def upload_files(request: Request, files: list[UploadFile] = File(...), background_tasks: BackgroundTasks = None,
                       kb: str = Depends(verify_kb_access), chunking_strategy: str = "",
                       enable_image: str = "", enable_table: str = "",
                       enable_equation: str = "", enable_video: str = "",
                       current_user: dict = Depends(get_current_user)):
    """批量上传文件 - 接收多个文件，逐个后台处理"""
    if not files:
        raise HTTPException(400, "请至少选择一个文件")

    upload_dir = Path("./uploads")
    upload_dir.mkdir(exist_ok=True)

    tasks = []
    skipped: list[str] = []
    from .shared import _ensure_queue_draining

    for file in files:
        task_id = str(uuid.uuid4())[:8]
        file_path = upload_dir / file.filename
        content = await file.read()
        file_path.write_bytes(content)
        file_size = len(content)

        # Dedup check per file
        file_hash = _compute_file_hash(str(file_path))
        existing_task = _is_file_being_processed(kb, file_hash)
        if existing_task:
            lightrag_logger.warning(
                f"[UPLOAD-BATCH] 跳过重复: file={file.filename} existing_task={existing_task}"
            )
            skipped.append(file.filename)
            continue

        # Register file metadata in PG (dedup enforced by UNIQUE on file_hash + kb_name)
        pg_id = await pg_register_upload(
            filename=file.filename,
            file_path=str(file_path.absolute()),
            file_hash=file_hash,
            file_size=file_size,
            kb_name=kb,
            uploaded_by=current_user.get("id", 0),
        )
        if pg_id is None:
            # PG insert failed — duplicate content hash or PG unavailable
            lightrag_logger.warning(
                f"[UPLOAD-BATCH] 注册失败（重复或PG不可用）: file={file.filename} hash={file_hash}"
            )
            try:
                file_path.unlink(missing_ok=True)
            except OSError:
                pass
            skipped.append(file.filename)
            continue
        _register_processing_file(kb, file_hash, task_id)

        # Push to per-KB queue (shared with single-file upload endpoint)
        task_info = {
            "task_id": task_id,
            "file_path": str(file_path.absolute()),
            "filename": file.filename,
            "kb_name": kb,
            "chunking_strategy": chunking_strategy,
            "user_id": current_user["id"],
            "enable_image": enable_image.lower() == "true" if enable_image else None,
            "enable_table": enable_table.lower() == "true" if enable_table else None,
            "enable_equation": enable_equation.lower() == "true" if enable_equation else None,
            "enable_video": enable_video.lower() == "true" if enable_video else None,
        }
        queue, pre_qsize = await _ensure_queue_draining(kb)
        queue.put_nowait(task_info)
        tasks.append({
            "task_id": task_id, "filename": file.filename,
            "status": "queued", "position": pre_qsize + len(tasks),
        })
        lightrag_logger.info(f"[UPLOAD-BATCH] 任务={task_id} 文件={file.filename} kb={kb}")

    strategy_name = CHUNKING_STRATEGY_META.get(chunking_strategy or CHUNKING_STRATEGY, {}).get('name', '默认')
    result = {"status": "queued", "tasks": tasks, "total": len(tasks), "kb": kb,
              "chunking_strategy": chunking_strategy or CHUNKING_STRATEGY,
              "queue_size": queue.qsize(),
              "message": f"已接收 {len(tasks)} 个文件，使用{strategy_name}分块，排队处理中"}
    if skipped:
        result["skipped"] = skipped
        result["message"] += f"，{len(skipped)} 个跳过（重复）"
    return result


@router.post("/upload/folder")
async def upload_folder(folder_path: str = QueryParam(...), kb: str = Depends(verify_kb_access),
                         chunking_strategy: str = "", current_user: dict = Depends(get_current_user),
                         enable_image: str = "", enable_table: str = "",
                         enable_equation: str = "", enable_video: str = ""):
    """批量处理文件夹"""
    if not os.path.isdir(folder_path):
        raise HTTPException(400, "文件夹不存在")

    import os as _os
    _prev_env = {}
    for key, val in [
        ("ENABLE_IMAGE_PROCESSING", enable_image),
        ("ENABLE_TABLE_PROCESSING", enable_table),
        ("ENABLE_EQUATION_PROCESSING", enable_equation),
        ("ENABLE_VIDEO_PROCESSING", enable_video),
    ]:
        if val:
            _prev_env[key] = _os.environ.get(key)
            _os.environ[key] = val.lower()

    try:
        task_id = str(uuid.uuid4())[:8]
        instance = await get_kb(kb)
        task_data = {
            "id": task_id, "file": folder_path, "status": "processing",
            "started_at": datetime.now().isoformat(), "kb": kb, "user_id": current_user["id"],
        }
        await upsert_task_state(task_id, task_data)
        # 临时切换分块策略
        original_func = None
        try:
            if chunking_strategy and instance.lightrag:
                new_func = build_chunking_func(chunking_strategy, instance.lightrag)
                if new_func is not None:
                    original_func = instance.lightrag.chunking_func
                    instance.lightrag.chunking_func = new_func
            await instance.process_folder_complete(folder_path, output_dir="./output", recursive=True)
            await complete_task(task_id)
        except Exception as e:
            await upsert_task_state(task_id, {
                "id": task_id, "status": "failed", "error": str(e),
                "kb": kb, "file": folder_path, "user_id": current_user["id"],
            })
            raise HTTPException(500, str(e))
        finally:
            if original_func and instance.lightrag:
                instance.lightrag.chunking_func = original_func
        return {"task_id": task_id, "folder": folder_path, "status": "completed"}
    finally:
        for key, val in _prev_env.items():
            if val is None:
                _os.environ.pop(key, None)
            else:
                _os.environ[key] = val


@router.post("/upload/content")
async def upload_content(req: PasteContentRequest, kb: str = Depends(verify_kb_access),
                          current_user: dict = Depends(get_current_user),
                          chunking_strategy: str = "",
                          enable_image: str = "", enable_table: str = "",
                          enable_equation: str = "", enable_video: str = ""):
    """直接粘贴内容入库"""
    import os as _os

    # ── Per-upload multimodal overrides ─────────────
    _prev_env = {}
    for key, val in [
        ("ENABLE_IMAGE_PROCESSING", enable_image),
        ("ENABLE_TABLE_PROCESSING", enable_table),
        ("ENABLE_EQUATION_PROCESSING", enable_equation),
        ("ENABLE_VIDEO_PROCESSING", enable_video),
    ]:
        if val:
            _prev_env[key] = _os.environ.get(key)
            _os.environ[key] = val.lower()

    try:
        instance = await get_kb(kb)
        content_list = [{"type": "text", "text": req.content, "page_idx": 0}]
        original_func = None
        try:
            if chunking_strategy and instance.lightrag:
                new_func = build_chunking_func(chunking_strategy, instance.lightrag)
                if new_func is not None:
                    original_func = instance.lightrag.chunking_func
                    instance.lightrag.chunking_func = new_func
            await instance.insert_content_list(content_list, file_path=req.title or "pasted_content")
            return {"status": "completed", "title": req.title or "pasted_content",
                    "chunking_strategy": chunking_strategy or CHUNKING_STRATEGY}
        except Exception as e:
            raise HTTPException(500, str(e))
        finally:
            if original_func and instance.lightrag:
                instance.lightrag.chunking_func = original_func
    finally:
        # Restore env vars
        for key, val in _prev_env.items():
            if val is None:
                _os.environ.pop(key, None)
            else:
                _os.environ[key] = val


@router.post("/upload/url")
async def upload_from_url(url: str = QueryParam(...), kb: str = Depends(verify_kb_access),
                         current_user: dict = Depends(get_current_user),
                         enable_image: str = "", enable_table: str = "",
                         enable_equation: str = "", enable_video: str = ""):
    """从 URL 下载文档并入库"""
    if not url.startswith("http"):
        raise HTTPException(400, "无效 URL")

    import os as _os
    _prev_env = {}
    for key, val in [
        ("ENABLE_IMAGE_PROCESSING", enable_image),
        ("ENABLE_TABLE_PROCESSING", enable_table),
        ("ENABLE_EQUATION_PROCESSING", enable_equation),
        ("ENABLE_VIDEO_PROCESSING", enable_video),
    ]:
        if val:
            _prev_env[key] = _os.environ.get(key)
            _os.environ[key] = val.lower()

    try:
        task_id = str(uuid.uuid4())[:8]
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

        instance = await get_kb()
        await instance.process_document_complete(str(fp.absolute()), output_dir="./output")
        await add_event("url_process_complete", file=fname, task_id=task_id, user_id=current_user.get("id", 0))
        return {"status": "completed", "filename": fname, "size": len(content)}
    except HTTPException:
        raise
    except Exception as e:
        await add_event("url_error", url=url, error=str(e), user_id=current_user.get("id", 0))
        raise HTTPException(500, str(e))
    finally:
        # Restore env vars
        for key, val in _prev_env.items():
            if val is None:
                _os.environ.pop(key, None)
            else:
                _os.environ[key] = val


# ── Knowledge / Document handlers ──────────────────────

# Compiled regex for stripping secrets.token_hex(4) prefix (8 hex chars + "_")
_HASH_PREFIX_RE = re.compile(r'^[0-9a-f]{8}_(.+)$')


def _strip_hash_prefix(filename: str) -> str:
    """Strip 8-char hex prefix inserted by upload (e.g. '593dbd4b_test.docx' → 'test.docx').

    Returns the original filename unchanged if no hash prefix is found.
    """
    m = _HASH_PREFIX_RE.match(filename)
    return m.group(1) if m else filename


@router.get("/knowledge/documents")
async def list_documents(kb: str = Depends(verify_kb_access), current_user: dict = Depends(get_current_user)):
    """列出所有文档及其状态（含处理中的任务）"""
    try:
        # Clean up completed/failed tasks before building the response
        await cleanup_completed_tasks()

        data = await _load_doc_status_json(kb)

        # Deduplicate doc_status entries by original filename: keep only the
        # most recently updated entry per stripped filename.
        best_doc: dict[str, tuple[str, dict]] = {}  # orig_name → (doc_id, info)
        for doc_id, info in data.items():
            if not isinstance(info, dict):
                continue  # skip non-dict entries (corrupted data)
            orig = _strip_hash_prefix(info.get("file_path", "") or "")
            if orig not in best_doc or (info.get("updated_at") or "") > (best_doc[orig][1].get("updated_at") or ""):
                best_doc[orig] = (doc_id, info)

        docs = []
        seen_files = set()
        for orig_name, (doc_id, info) in best_doc.items():
            # Check if there's a matching processing task with phase info
            doc_phase = ""
            for tid, task in processing_tasks.items():
                if not isinstance(task, dict):
                    continue  # skip non-dict entries
                task_file = _strip_hash_prefix(task.get("file", "") or "")
                if task_file == orig_name and task.get("kb", "") == kb:
                    doc_phase = task.get("phase", "") or ""
                    break
            docs.append({
                "id": (doc_id or "")[:16],
                "full_id": doc_id or "",
                "file": _strip_hash_prefix((info.get("file_path") or "?")),
                "status": info.get("status") or "?",
                "chunks": info.get("chunks_count") or 0,
                "length": info.get("content_length") or 0,
                "created": info.get("created_at") or "",
                "updated": info.get("updated_at") or "",
                "phase": doc_phase,
            })
            seen_files.add(orig_name)

        # 合并处理中的任务（还未写入 doc_status），仅限当前 KB
        for tid, task in processing_tasks.items():
            if not isinstance(task, dict):
                continue  # skip non-dict entries
            if task.get("kb", "") != kb:
                continue
            fn = task.get("file") or ""
            if fn and _strip_hash_prefix(fn) not in seen_files:
                docs.append({
                    "id": tid or "",
                    "full_id": tid or "",
                    "file": fn,
                    "status": task.get("status") or "processing",
                    "chunks": 0,
                    "length": 0,
                    "created": task.get("started_at") or "",
                    "updated": task.get("started_at") or "",
                    "phase": task.get("phase") or "",
                })

        # Sort with None-safe key: treat None/empty as empty string
        def _sort_key(d):
            return d.get("updated") or ""
        return {"documents": sorted(docs, key=_sort_key, reverse=True), "total": len(docs)}
    except Exception as e:
        lightrag_logger.error(f"[list_documents] kb={kb} error: {e}", exc_info=True)
        raise HTTPException(500, str(e))


@router.get("/knowledge/stats")
async def knowledge_stats(kb: str = Depends(verify_kb_access), current_user: dict = Depends(get_current_user)):
    """知识库总体统计 — 与 list_documents 使用相同的数据源和去重逻辑"""

    import json as _json
    stats = {"documents": 0, "entities": 0, "relations": 0, "chunks": 0}
    base = Path(kb_dir(kb))
    # Use raw kb_dir(kb) for workspace matching, NOT str(Path(...)).
    # On Windows Path("./rag_storage_11") strips the "./" prefix, causing
    # a mismatch with the workspace value that LightRAG writes to PG tables
    # (e.g. "./rag_storage_11" vs "rag_storage_11").  The graph endpoint
    # already uses kb_dir(kb) directly and works correctly.
    workspace = kb_dir(kb)

    # ── doc_status: reuse the same PG→JSON pipeline as list_documents ──
    data = await _load_doc_status_json(kb)

    # Apply same dedup logic as list_documents (keep most-recent per stripped filename)
    best_doc: dict[str, tuple[str, dict]] = {}
    for doc_id, info in data.items():
        if not isinstance(info, dict):
            continue
        orig = _strip_hash_prefix(info.get("file_path", "") or "")
        if orig not in best_doc or (info.get("updated_at") or "") > (best_doc[orig][1].get("updated_at") or ""):
            best_doc[orig] = (doc_id, info)

    valid_doc_ids = {doc_id for orig, (doc_id, info) in best_doc.items()}
    stats["documents"] = len(best_doc)
    for orig, (doc_id, info) in best_doc.items():
        stats["chunks"] += info.get("chunks_count", 0) if isinstance(info, dict) else 0

    # ── Entities & Relations: PG first, JSON fallback ──
    # Determine whether PG graph tables have data; if not, read JSON files.
    _pg_graph_ok = False
    try:
        from raganything.services.pg_state_repo import get_pg_pool
        _pool = get_pg_pool()
        async with _pool.acquire() as _conn:
            await _conn.fetchval("SELECT 1")
        _pg_graph_ok = True
    except Exception:
        pass

    # ── Entities & Relations: count ALL records from PG directly ──
    # The graph endpoint does NOT filter by doc_id — it reads all entities
    # and relations from the tables.  We match that behaviour here so the
    # stats header always agrees with the graph visualization.
    #
    # Previous versions filtered by _effective_doc_ids (from
    # LIGHTRAG_DOC_STATUS), which broke when the cached LightRAG instance
    # had a stale workspace or doc_status was temporarily out of sync with
    # full_entities / full_relations.

    _entities_from_pg = False
    if _pg_graph_ok:
        try:
            pg_entities = await _pg_fetch_graph_entities(workspace)
            if pg_entities:
                _entities_from_pg = True
                for _doc_id, v in pg_entities.items():
                    stats["entities"] += v.get("count", len(v.get("entity_names", [])))
        except Exception:
            pass
    if not _entities_from_pg:
        ent_path = base / "kv_store_full_entities.json"
        if ent_path.exists():
            try:
                entities = _json.loads(ent_path.read_text(encoding="utf-8"))
                if isinstance(entities, dict):
                    for _doc_id, v in entities.items():
                        if isinstance(v, dict):
                            stats["entities"] += v.get("count", len(v.get("entity_names", [])))
            except (_json.JSONDecodeError, OSError):
                pass

    _relations_from_pg = False
    if _pg_graph_ok:
        try:
            pg_relations = await _pg_fetch_graph_relations(workspace)
            if pg_relations:
                _relations_from_pg = True
                for _doc_id, v in pg_relations.items():
                    stats["relations"] += v.get("count", len(v.get("relation_pairs", [])))
        except Exception:
            pass
    if not _relations_from_pg:
        rel_path = base / "kv_store_full_relations.json"
        if rel_path.exists():
            try:
                relations = _json.loads(rel_path.read_text(encoding="utf-8"))
                if isinstance(relations, dict):
                    for _doc_id, v in relations.items():
                        if isinstance(v, dict):
                            stats["relations"] += v.get("count", len(v.get("relation_pairs", [])))
            except (_json.JSONDecodeError, OSError):
                pass

    return stats


@router.post("/knowledge/repair")
async def repair_kb_orphans(
    kb: str = Depends(verify_kb_access),
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

    base = Path(kb_dir(kb))
    workspace = kb_dir(kb)  # raw string for workspace matching (see knowledge_stats)

    # 加载合法文档白名单 — PG-backed
    doc_data = await _load_doc_status_json(kb)
    if not doc_data:
        return {"status": "ok", "message": "无文档记录，无需修复", "cleaned": {}}
    valid_doc_ids = set(doc_data.keys())

    _lg = instance.lightrag
    report: dict[str, int] = {}

    # ── 1. 扫描 full_entities ──
    entities_data = await _pg_fetch_graph_entities(workspace)
    if entities_data:
        orphan_entity_keys = [k for k in entities_data if k not in valid_doc_ids]
        if orphan_entity_keys:
            _ent_names_to_delete: list[str] = []
            for _ok in orphan_entity_keys:
                _ed = entities_data.get(_ok, {})
                _ent_names_to_delete.extend(_ed.get("entity_names", []))
                try:
                    await _lg.full_entities.delete([_ok])
                except Exception:
                    pass
            # 删除孤儿实体向量和图谱节点
            if _ent_names_to_delete:
                try:
                    await _lg.entities_vdb.delete(_ent_names_to_delete)
                except Exception:
                    pass
                try:
                    _graph = getattr(_lg, "chunk_entity_relation_graph", None)
                    if _graph:
                        for _en in _ent_names_to_delete:
                            try:
                                await _graph.delete_node(_en)
                            except Exception:
                                pass
                except Exception:
                    pass
            report["orphan_entities"] = len(orphan_entity_keys)
            lightrag_logger.info(
                "[REPAIR] KB=%s 清理 %d 个孤儿实体组 (%d 个实体向量)",
                kb, len(orphan_entity_keys), len(_ent_names_to_delete),
            )

    # ── 2. 扫描 full_relations ──
    relations_data = await _pg_fetch_graph_relations(workspace)
    if relations_data:
        orphan_rel_keys = [k for k in relations_data if k not in valid_doc_ids]
        if orphan_rel_keys:
            for _ok in orphan_rel_keys:
                try:
                    await _lg.full_relations.delete([_ok])
                except Exception:
                    pass
            report["orphan_relations"] = len(orphan_rel_keys)
            lightrag_logger.info(
                "[REPAIR] KB=%s 清理 %d 个孤儿关系组", kb, len(orphan_rel_keys),
            )

    # ── 3. 扫描 full_docs ──
    full_docs_data = await _load_full_docs_json(kb)
    if full_docs_data:
        orphan_doc_keys = [k for k in full_docs_data if k not in valid_doc_ids]
        if orphan_doc_keys:
            for _ok in orphan_doc_keys:
                try:
                    await _lg.full_docs.delete([_ok])
                except Exception:
                    pass
            report["orphan_docs"] = len(orphan_doc_keys)

    # ── 4. 扫描 image_vision_repo（PG/NVDB 统一接口）──
    if hasattr(_lg, "image_vision_repo") and _lg.image_vision_repo is not None:
        try:
            _repo = _lg.image_vision_repo
            _orphan_ids = await _repo.get_orphan_ids(valid_doc_ids)
            if _orphan_ids:
                _orphan_img = await _repo.delete_by_ids(_orphan_ids)
                await _repo.flush()
                report["orphan_vision_vectors"] = _orphan_img
                lightrag_logger.info(
                    "[REPAIR] KB=%s 清理 %d 个孤儿视觉向量", kb, _orphan_img,
                )
        except Exception as e:
            lightrag_logger.warning("[REPAIR] 视觉向量清理失败: %s", e)

    # ── 5. 持久化（绕过 finalize 对非 cache 命名空间的 NO-OP）──
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

    return {"nodes": nodes, "edges": edges}


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

    display_name = Path(stored_path).name
    return real_path.resolve(), display_name


# ── File Download Endpoint ────────────────────────────────────

@router.get("/knowledge/documents/{doc_id}/download")
async def download_document(
    doc_id: str,
    kb: str = Depends(verify_kb_access),
    current_user: dict = Depends(get_current_user),
):
    """下载文档的原始上传文件（PDF / DOCX / PPTX / 视频 等）。

    支持 HTTP Range 请求（视频拖动进度条、断点续传）。
    Content-Type 根据文件扩展名自动检测。
    """
    import mimetypes

    resolved = await _resolve_download_file(kb, doc_id)
    if resolved is None:
        raise HTTPException(404, f"文档 {doc_id} 的原始文件未找到，可能已被清理")

    real_path, display_name = resolved

    # 安全检查：确保文件在项目目录内
    try:
        real_path.relative_to(Path.cwd())
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


def _cleanup_document_files(kb_name: str, file_path: str, doc_id: str = "") -> None:
    """Delete uploaded file and parse output for a document.

    Called when a document or KB is deleted from the frontend.  Ensures the
    ``uploads/`` directory and per-KB parser output directory stay in sync
    with the knowledge base.
    """
    # 1. Delete the original uploaded file from uploads/
    if file_path:
        real = _find_upload_file(file_path)
        if real and real.exists():
            try:
                real.unlink()
                lightrag_logger.info(f"[CLEANUP] 已删除上传文件: {real}")
            except (FileNotFoundError, OSError):
                pass  # 已被并发请求删除或无权限

    # 2. Delete the parser output subdirectory for this document
    output_base = "./output" if kb_name == "default" else f"./output_{kb_name}"
    output_dir = Path(output_base)
    if output_dir.exists():
        file_stem = Path(file_path).stem
        for d in output_dir.iterdir():
            if d.is_dir() and d.name.startswith(file_stem):
                shutil.rmtree(d, ignore_errors=True)
                lightrag_logger.info(f"[CLEANUP] 已删除解析输出: {d}")
                break  # one document → one output directory

    # 3. Remove parse cache entry for this doc_id
    if doc_id:
        cache_path = Path(kb_dir(kb_name)) / "kv_store_parse_cache.json"
        if cache_path.exists():
            try:
                cache = json.loads(cache_path.read_text("utf-8"))
                if doc_id in cache:
                    del cache[doc_id]
                    cache_path.write_text(
                        json.dumps(cache, ensure_ascii=False, indent=2), "utf-8"
                    )
                    lightrag_logger.info(f"[CLEANUP] 已删除解析缓存: {doc_id[:16]}...")
            except Exception:
                pass


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

    # 2. 清理实体/关系向量库和图谱
    if _ent_names:
        try:
            if hasattr(_lg, "entities_vdb") and _lg.entities_vdb is not None:
                await _lg.entities_vdb.delete(_ent_names)
                _cleaned.append("entities_vdb")
        except Exception:
            pass
        try:
            if hasattr(_lg, "relationships_vdb") and _lg.relationships_vdb is not None:
                await _lg.relationships_vdb.delete(_ent_names)
        except Exception:
            pass
        try:
            _graph = getattr(_lg, "chunk_entity_relation_graph", None)
            if _graph is not None:
                for _ename in _ent_names:
                    try:
                        await _graph.delete_node(_ename)
                    except Exception:
                        pass
        except Exception:
            pass
    if _rel_pairs:
        try:
            _graph = getattr(_lg, "chunk_entity_relation_graph", None)
            if _graph is not None:
                for _src, _tgt in _rel_pairs:
                    try:
                        await _graph.delete_edge(_src, _tgt)
                    except Exception:
                        pass
        except Exception:
            pass

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


async def _purge_all_orphans(instance, kb: str) -> dict[str, int]:
    """全量扫描并清除所有不在 doc_status 白名单中的孤儿数据。

    每次文档删除后调用此函数，确保 full_entities / full_relations /
    full_docs / image_vision_repo 中不残留任何已删除文档的数据。

    Returns:
        {"entities": N, "relations": N, "docs": N, "vision_vectors": N}
    """
    _lg = instance.lightrag
    base = Path(kb_dir(kb))
    workspace = kb_dir(kb)  # raw string for workspace matching (see knowledge_stats)
    report: dict[str, int] = {}

    # ── 加载 doc_status 白名单 — PG-backed ──
    doc_data = await _load_doc_status_json(kb)
    if not doc_data:
        return report
    valid_doc_ids = set(doc_data.keys())
    if not valid_doc_ids:
        # 全部文档已删除 → 清空所有存储
        valid_doc_ids = set()

    # ── 1. full_entities ──
    entities_data: dict = await _pg_fetch_graph_entities(workspace)
    if entities_data:
        try:
            orphan_keys = [k for k in entities_data if k not in valid_doc_ids]
            if orphan_keys:
                _ent_names: list[str] = []
                for _ok in orphan_keys:
                    _ed = entities_data.get(_ok, {})
                    _ent_names.extend(_ed.get("entity_names", []))
                    try:
                        await _lg.full_entities.delete([_ok])
                    except Exception:
                        pass
                # 清理实体向量和图谱节点
                if _ent_names and hasattr(_lg, "entities_vdb") and _lg.entities_vdb is not None:
                    try:
                        await _lg.entities_vdb.delete(_ent_names)
                    except Exception:
                        pass
                _graph = getattr(_lg, "chunk_entity_relation_graph", None)
                if _graph and _ent_names:
                    for _en in _ent_names:
                        try:
                            await _graph.delete_node(_en)
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
                # 收集孤儿 relation pairs 用于清理 VDB
                _rel_pairs: list[list[str]] = []
                for _ok in orphan_keys:
                    _rd = relations_data.get(_ok, {})
                    _rel_pairs.extend(_rd.get("relation_pairs", []))
                    try:
                        await _lg.full_relations.delete([_ok])
                    except Exception:
                        pass
                # 清理 relationships_vdb 中的向量
                if _rel_pairs and hasattr(_lg, "relationships_vdb") and _lg.relationships_vdb is not None:
                    try:
                        # Relation VDB keys: "src<SEP>tgt" format
                        _rel_ids = [f"{src}<SEP>{tgt}" for src, tgt in _rel_pairs]
                        await _lg.relationships_vdb.delete(_rel_ids)
                    except Exception:
                        pass
                report["relations"] = len(orphan_keys)
        except Exception:
            pass

    # ── 3. full_docs ──
    full_docs_data = await _load_full_docs_json(kb)
    if full_docs_data:
        try:
            orphan_keys = [k for k in full_docs_data if k not in valid_doc_ids]
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

    # ── 6. VDB + 图谱深层扫描 ──
    # 步骤 1-3 依赖 full_entities.json 里的 doc_id → entity_names 映射来
    # 定位孤儿。但如果 full_entities 本身因为旧 bug 没写盘，实体向量会残留
    # 在 entities_vdb / relationships_vdb / 图谱中无法被追踪到。
    # 此处直接扫描 VDB 和图谱，清理所有不在 full_entities 白名单中的条目。
    _vdb_purged = await _purge_orphan_vdb_entries(_lg, entities_data, relations_data)
    if _vdb_purged:
        for k, v in _vdb_purged.items():
            report[k] = report.get(k, 0) + v

    return report


async def _purge_orphan_vdb_entries(lg, entities_data: dict, relations_data: dict = None) -> dict[str, int]:
    """Deep-scan entities_vdb, relationships_vdb, and graph for entries
    whose names are not referenced by any doc in full_entities or full_relations.

    This catches stale vectors left over when ``full_entities``/``full_relations``
    entries were lost due to old bugs (e.g. ``finalize_storages`` not writing to disk).

    Returns:
        {"entities_vdb": N, "relationships_vdb": N, "graph_nodes": N}
    """
    report: dict[str, int] = {}
    if relations_data is None:
        relations_data = {}

    # Build whitelist: all entity names known to full_entities
    valid_ent_names: set[str] = set()
    for v in entities_data.values():
        valid_ent_names.update(v.get("entity_names", []))

    # Build whitelist: all relation keys known to full_relations
    # Relation VDB uses "src<SEP>tgt" format
    valid_rel_keys: set[str] = set()
    for v in relations_data.values():
        for src, tgt in v.get("relation_pairs", []):
            valid_rel_keys.add(f"{src}<SEP>{tgt}")

    # ── Helper: safely enumerate NanoVectorDB data rows ──
    def _vdb_rows(vdb):
        """Return list of data rows from a NanoVectorDB instance.

        Uses the private ``_NanoVectorDB__storage`` attribute (name-mangled).
        Returns empty list if VDB is None or attribute access fails.
        """
        if vdb is None:
            return []
        storage = getattr(vdb, "_NanoVectorDB__storage", None)
        if not isinstance(storage, dict):
            return []
        data = storage.get("data")
        if not isinstance(data, list):
            return []
        return data

    # ── entities_vdb deep scan ──
    if hasattr(lg, "entities_vdb") and lg.entities_vdb is not None:
        try:
            _vdb = lg.entities_vdb
            orphan_names: list[str] = []
            for _row in _vdb_rows(_vdb):
                _name = _row.get("__id__") or _row.get("entity_name") or ""
                if _name and _name not in valid_ent_names:
                    orphan_names.append(_name)
            if orphan_names:
                await _vdb.delete(orphan_names)
                report["entities_vdb"] = len(orphan_names)
                lightrag_logger.info(
                    "[PURGE-ORPHANS-VDB] entities_vdb 清理了 %d 个不在白名单的向量",
                    len(orphan_names),
                )
        except Exception as _e:
            lightrag_logger.warning("[PURGE-ORPHANS-VDB] entities_vdb 扫描失败: %s", _e)

    # ── relationships_vdb deep scan ──
    if hasattr(lg, "relationships_vdb") and lg.relationships_vdb is not None:
        try:
            _rvdb = lg.relationships_vdb
            orphan_rel_names: list[str] = []
            for _row in _vdb_rows(_rvdb):
                _name = _row.get("__id__") or _row.get("relation_name") or ""
                if _name and _name not in valid_rel_keys:
                    orphan_rel_names.append(_name)
            if orphan_rel_names:
                await _rvdb.delete(orphan_rel_names)
                report["relationships_vdb"] = len(orphan_rel_names)
                lightrag_logger.info(
                    "[PURGE-ORPHANS-VDB] relationships_vdb 清理了 %d 个不在白名单的向量",
                    len(orphan_rel_names),
                )
        except Exception as _e:
            lightrag_logger.warning("[PURGE-ORPHANS-VDB] relationships_vdb 扫描失败: %s", _e)

    # ── graph node deep scan ──
    _graph = getattr(lg, "chunk_entity_relation_graph", None)
    if _graph is not None and valid_ent_names:
        try:
            # Use existing graph API to enumerate nodes if available
            orphan_graph_nodes: list[str] = []
            _all_nodes = set()
            # Try getting all nodes via graph storage
            _graph_storage = getattr(_graph, "_graph", None)
            if _graph_storage is not None:
                # NetworkX graph
                _all_nodes = set(_graph_storage.nodes())
            elif hasattr(_graph, "get_all_nodes"):
                _all_nodes = set(_graph.get_all_nodes() or [])
            else:
                # Fallback: enumerate from _node_data if available
                _nd = getattr(_graph, "_node_data", None)
                if _nd:
                    _all_nodes = set(_nd.keys())

            for _node in _all_nodes:
                _node_name = str(_node)
                if _node_name and _node_name not in valid_ent_names:
                    orphan_graph_nodes.append(_node_name)

            if orphan_graph_nodes:
                for _gn in orphan_graph_nodes:
                    try:
                        await _graph.delete_node(_gn)
                    except Exception:
                        pass
                report["graph_nodes"] = len(orphan_graph_nodes)
                lightrag_logger.info(
                    "[PURGE-ORPHANS-VDB] graph 清理了 %d 个不在白名单的节点",
                    len(orphan_graph_nodes),
                )
        except Exception as _e:
            lightrag_logger.warning("[PURGE-ORPHANS-VDB] graph 扫描失败: %s", _e)

    # Persist VDB changes
    if report:
        try:
            if hasattr(lg, "entities_vdb") and lg.entities_vdb is not None:
                await lg.entities_vdb.index_done_callback()
        except Exception:
            pass
        try:
            if hasattr(lg, "relationships_vdb") and lg.relationships_vdb is not None:
                await lg.relationships_vdb.index_done_callback()
        except Exception:
            pass

    return report


@router.delete("/knowledge/documents/{doc_id}")
async def delete_document(doc_id: str, kb: str = Depends(verify_kb_access), current_user: dict = Depends(get_current_user)):
    """删除文档 - 使用 LightRAG 的 adelete_by_doc_id 彻底清理所有关联数据"""
    instance = await get_kb(kb)
    if not instance.lightrag:
        raise HTTPException(500, "知识库未初始化")

    # PG-backed doc_status lookup
    doc_status = await _load_doc_status_json(kb)
    if not doc_status:
        raise HTTPException(404, "无文档记录")

    # 通过前缀匹配找到完整 doc_id
    full_id = None
    for k in doc_status:
        if k.startswith(doc_id):
            full_id = k
            break

    if not full_id:
        # 可能是一个处理中/失败的 processing task，尝试从 processing_tasks 中移除
        task = await get_task_status(doc_id)
        if task:
            fname = task.get("file", "未知")
            await delete_task(doc_id)
            await add_event("doc_delete", file=fname, doc_id=doc_id, kb=kb, source="processing_tasks", user_id=current_user["id"])
            return {"status": "deleted", "doc_id": doc_id, "file": fname, "message": "已从处理队列中移除"}
        # 也尝试按 file_path 匹配（前端可能传文件名相关的 ID）
        for tid, task in list(processing_tasks.items()):
            if task.get("kb", "") == kb and task.get("file", "") == doc_id:
                await delete_task(tid)
                await add_event("doc_delete", file=doc_id, doc_id=tid, kb=kb, source="processing_tasks", user_id=current_user["id"])
                return {"status": "deleted", "doc_id": tid, "file": doc_id, "message": "已从处理队列中移除"}
        raise HTTPException(404, f"文档 {doc_id} 不存在（知识库: {kb}）")

    file_name = doc_status[full_id].get("file_path", "未知")

    # 使用 LightRAG 的正式删除方法，彻底清理所有关联数据
    result = await instance.lightrag.adelete_by_doc_id(full_id, delete_llm_cache=True)

    await add_event("doc_delete", file=file_name, doc_id=full_id, kb=kb, user_id=current_user["id"])

    if result.status == "success":
        _cleanup_document_files(kb, file_name, full_id)
        # Clean up multimodal status cache entry for this document
        if hasattr(instance, "multimodal_status_cache") and instance.multimodal_status_cache is not None:
            try:
                await instance.multimodal_status_cache.delete([full_id])
                await instance.multimodal_status_cache.index_done_callback()
            except Exception:
                pass
        # Clean up vision embedding repository for this document
        if (hasattr(instance.lightrag, 'image_vision_repo')
                and instance.lightrag.image_vision_repo is not None):
            try:
                await instance.lightrag.image_vision_repo.delete_by_doc_id(full_id)
                await instance.lightrag.image_vision_repo.flush()
            except Exception:
                pass

        # Force LightRAG storages to persist deletions to disk so that
        # _bigram_image_scan and other disk-level readers see up-to-date data.
        await instance.lightrag.finalize_storages()
        # Invalidate query cache to prevent stale results referencing deleted data
        from raganything.query_cache import get_query_cache
        get_query_cache().invalidate()
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
            _cleanup_document_files(kb, file_name, full_id)
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
            # Invalidate query cache even for partial cleanup
            from raganything.query_cache import get_query_cache
            get_query_cache().invalidate()
            _delete_response = {
                "status": "deleted",
                "doc_id": full_id,
                "file": file_name,
                "message": "文档记录已清理（部分数据不完整）",
            }
        except Exception:
            raise HTTPException(404, f"文档 {file_name} 数据未找到")
    else:
        raise HTTPException(500, result.message)

    # ── 删除后全量孤儿扫描：确保 full_entities/full_relations 等存储中
    #    不残留任何已删除文档的数据（包括历史残留）。 ──
    await _purge_all_orphans(instance, kb)
    return _delete_response


@router.post("/knowledge/documents/batch-delete")
async def batch_delete_documents(req: BatchDeleteRequest, kb: str = Depends(verify_kb_access), current_user: dict = Depends(get_current_user)):
    """批量删除文档 - 一次请求删除多个文档"""
    instance = await get_kb(kb)
    if not instance.lightrag:
        raise HTTPException(500, "知识库未初始化")

    # PG-backed doc_status lookup
    doc_status = await _load_doc_status_json(kb)
    if not doc_status:
        raise HTTPException(404, "无文档记录")

    deleted = []
    not_found = []
    errors = []

    deleted_full_ids: list[str] = []  # for multimodal_status_cache batch cleanup
    not_found_full_ids: list[str] = []  # for LightRAG orphan cleanup

    for doc_id in req.doc_ids:
        full_id = None
        for k in doc_status:
            if k.startswith(doc_id):
                full_id = k
                break

        if not full_id:
            # Try processing_tasks
            task = await get_task_status(doc_id)
            if task:
                await delete_task(doc_id)
                await add_event("doc_delete", file=task.get("file", "?"), doc_id=doc_id, kb=kb, source="processing_tasks", user_id=current_user["id"])
                deleted.append(doc_id)
            else:
                not_found.append(doc_id)
            continue

        try:
            file_name = doc_status[full_id].get("file_path", "未知")
            result = await instance.lightrag.adelete_by_doc_id(full_id, delete_llm_cache=True)
            if result.status in ("success", "not_found"):
                del doc_status[full_id]
                deleted.append(doc_id)
                deleted_full_ids.append(full_id)
                _cleanup_document_files(kb, file_name, full_id)
                await add_event("doc_delete", file=file_name, doc_id=full_id, kb=kb, user_id=current_user["id"])
                if result.status == "not_found":
                    not_found_full_ids.append(full_id)
                    # Remove from PG doc_status via LightRAG
                    try:
                        await instance.lightrag.doc_status.delete([full_id])
                        await instance.lightrag.doc_status.index_done_callback()
                    except Exception:
                        pass
                # Also clean up matching processing_tasks entry
                for tid, task in list(processing_tasks.items()):
                    if task.get("kb", "") == kb and task.get("file", "") == file_name:
                        del processing_tasks[tid]
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

    # PG-backed: doc_status is already updated via LightRAG; no JSON file to write

    # Force LightRAG storages to persist deletions + invalidate query cache
    if deleted:
        await instance.lightrag.finalize_storages()
        from raganything.query_cache import get_query_cache
        get_query_cache().invalidate()

    # ── 删除后全量孤儿扫描 ──
    await _purge_all_orphans(instance, kb)

    return {"deleted": deleted, "not_found": not_found, "errors": errors,
            "total_deleted": len(deleted), "total_failed": len(errors)}


@router.post("/knowledge/documents/{doc_id}/retry")
async def retry_document(doc_id: str, kb: str = Depends(verify_kb_access), current_user: dict = Depends(get_current_user), background_tasks: BackgroundTasks = None):
    """重试处理失败的文档 — PG-backed"""
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

    # 查找原始文件路径
    upload_dir = Path("./uploads")
    file_path = upload_dir / file_name
    if not file_path.exists():
        # 尝试从 doc_status 获取完整路径
        file_path = Path(file_name) if Path(file_name).exists() else None
    if not file_path or not file_path.exists():
        raise HTTPException(404, f"原始文件不存在: {file_name}")

    # 删除旧的失败记录 via LightRAG PG (trigger reprocessing)
    try:
        kb_instance = await get_kb(kb)
        if kb_instance and kb_instance.lightrag:
            await kb_instance.lightrag.doc_status.delete([full_id])
            await kb_instance.lightrag.doc_status.index_done_callback()
    except Exception:
        pass
    del data[full_id]

    # 推入 per-KB 处理队列（统一排队）
    task_id = str(uuid.uuid4())[:8]
    from .shared import _ensure_queue_draining
    task_info = {
        "task_id": task_id,
        "file_path": str(file_path.absolute()),
        "filename": file_name,
        "kb_name": kb,
        "chunking_strategy": "",
        "user_id": current_user["id"],
    }
    queue, qsize = await _ensure_queue_draining(kb)
    queue.put_nowait(task_info)
    return {"status": "queued", "task_id": task_id, "filename": file_name,
            "position": qsize + 1, "queue_size": qsize + 1,
            "message": "文档已加入处理队列"}


@router.post("/kb/{kb_name}/reprocess-multimodal")
async def reprocess_multimodal(
    kb_name: str,
    background_tasks: BackgroundTasks,
    current_user: dict = Depends(get_current_user),
):
    """回溯处理知识库中文档的多模态内容（图片/表格/公式）。

    扫描 KB 中 ``multimodal_processed`` 不为 ``true`` 的文档，从原始文件
    重新解析（优先走解析缓存），仅执行多模态处理——不重新插入文本。
    """
    # Require admin permission
    if not current_user.get("is_admin", False):
        raise HTTPException(403, "仅管理员可执行此操作")

    try:
        # Scan first to get count — PG-backed
        all_docs = await _load_doc_status_json(kb_name)
        total = sum(
            1 for info in all_docs.values()
            if info.get("status") != "failed"
            and not info.get("multimodal_processed", False)
        )

        if total == 0:
            return {
                "status": "ok", "processed": 0, "skipped": 0, "total": 0,
                "message": "所有文档已完成多模态处理",
            }

        # Schedule background processing
        background_tasks.add_task(
            _reprocess_multimodal_for_kb, kb_name, user_id=current_user.get("id", 1)
        )
        return {
            "status": "queued", "total": total,
            "message": f"已排队 {total} 个文档，后台处理中。通过 WebSocket 获取进度更新。",
        }
    except ValueError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        lightrag_logger.error(f"[REPROCESS-API] 回溯处理失败 kb={kb_name}: {e}")
        raise HTTPException(500, f"回溯处理失败: {e}")

    return {"status": "ok", **result}


# ── KB management handlers ─────────────────────────────

@router.get("/kb/list")
async def list_kbs(current_user: dict = Depends(get_current_user)):
    meta = await load_kb_meta()
    kbs = []
    is_admin = current_user.get("is_admin", False)
    for name, info in meta.items():
        # 数据隔离：普通用户只看自己的 KB，管理员看全部
        owner_id = info.get("owner_id")
        if owner_id is not None and owner_id != current_user["id"] and not is_admin:
            continue
        kbs.append({
            "name": name,
            "label": info.get("name", name),
            "created": info.get("created", ""),
            "owner_id": owner_id,
            "owner_username": info.get("owner_username", ""),
            "active": name == _shared.active_kb,
        })
    # 新用户没有 KB 时自动创建个人 KB 并初始化存储
    if not kbs and not is_admin:
        personal_kb = current_user["username"]
        label = f"{current_user['username']}的知识库"
        meta[personal_kb] = {
            "name": label, "created": datetime.now().isoformat(),
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
            "owner_id": current_user["id"],
            "owner_username": current_user["username"],
            "active": True,
        })
    return {"knowledge_bases": kbs, "active": _shared.active_kb}


@router.post("/kb/create")
async def create_kb(kb_name: str = QueryParam(...), current_user: dict = Depends(get_current_user), label: str = QueryParam(""), domain: str = QueryParam("general")):
    meta = await load_kb_meta()
    if kb_name in meta:
        raise HTTPException(400, f"知识库 '{kb_name}' 已存在")
    label = label or kb_name
    meta[kb_name] = {
        "name": label, "created": datetime.now().isoformat(),
        "owner_id": current_user["id"],
        "owner_username": current_user["username"],
        "domain": domain,
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
    if owner_id is not None and owner_id != current_user["id"] and not current_user.get("is_admin"):
        raise HTTPException(403, "无权访问该知识库")
    _shared.active_kb = name
    return {"status": "switched", "active": name}


@router.delete("/kb/{name}")
async def delete_kb(name: str, current_user: dict = Depends(get_current_user)):
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
    import os as _os
    if _os.getenv("VISION_SEARCH_ENABLED", "false").lower() != "true":
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
            501,
            "视觉嵌入搜索未启用。请配置 VISION_EMBEDDING_MODEL 环境变量。",
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

        # Query similar images
        results = await repo.query(vec, top_k=top_k)

        return {
            "query": image.filename,
            "results": results,
            "count": len(results),
            "repo_count": repo.count(),
        }
    finally:
        try:
            _os.unlink(tmp_path)
        except OSError:
            pass


# ── File serving ───────────────────────────────────────

@router.get("/files/image")
async def serve_image(
    path: str = QueryParam(...),
    token: Optional[str] = QueryParam(None, description="认证 Token（用于 img 标签等无法设置 Header 的场景）"),
    current_user: Optional[dict] = Depends(get_optional_user),
):
    """服务图片文件 — 支持 query 参数 token 或 Authorization header。

    浏览器 <img> 标签无法设置 Authorization header，因此额外支持 ?token=xxx 认证。
    """
    if current_user is None and token:
        current_user = await get_current_user_from_token(token=token)
    if current_user is None:
        raise HTTPException(401, "请提供有效的认证 Token（query 参数 ?token= 或 Authorization header）")

    abs_path = Path(path).resolve()
    cwd = Path.cwd()
    # 安全检查：只允许项目目录内的文件
    try:
        abs_path.relative_to(cwd)
    except ValueError:
        raise HTTPException(403, "不允许访问项目目录外的文件")
    if not abs_path.exists():
        raise HTTPException(404, "图片文件不存在")
    if abs_path.suffix.lower() not in (".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp", ".tiff", ".tif"):
        raise HTTPException(400, "不支持的文件类型")
    return FileResponse(str(abs_path))
