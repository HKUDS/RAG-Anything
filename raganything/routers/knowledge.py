"""Knowledge Router — /api/upload/*, /api/knowledge/*, /api/kb/*, /api/files/image"""

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
)
from raganything.dependencies import get_optional_user, get_current_user_from_token
from raganything.chunking import build_chunking_func, STRATEGY_META as CHUNKING_STRATEGY_META

# Module reference for writing to shared mutable state (active_kb)
from . import shared as _shared

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
                       current_user: dict = Depends(get_current_user)):
    """Upload a single file — immediate return, background processing"""
    task_id = str(uuid.uuid4())[:8]
    upload_dir = Path("./uploads")
    upload_dir.mkdir(exist_ok=True)
    safe_name = os.path.basename(file.filename)
    file_path = upload_dir / (secrets.token_hex(4) + "_" + safe_name)
    content = await file.read()
    file_path.write_bytes(content)

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

        # Dedup check per file
        file_hash = _compute_file_hash(str(file_path))
        existing_task = _is_file_being_processed(kb, file_hash)
        if existing_task:
            lightrag_logger.warning(
                f"[UPLOAD-BATCH] 跳过重复: file={file.filename} existing_task={existing_task}"
            )
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
                         chunking_strategy: str = "", current_user: dict = Depends(get_current_user)):
    """批量处理文件夹"""
    if not os.path.isdir(folder_path):
        raise HTTPException(400, "文件夹不存在")
    task_id = str(uuid.uuid4())[:8]
    instance = await get_kb(kb)
    processing_tasks[task_id] = {
        "id": task_id, "file": folder_path, "status": "processing",
        "started_at": datetime.now().isoformat(), "kb": kb, "user_id": current_user["id"],
    }
    # 临时切换分块策略
    original_func = None
    try:
        if chunking_strategy and instance.lightrag:
            new_func = build_chunking_func(chunking_strategy, instance.lightrag)
            if new_func is not None:
                original_func = instance.lightrag.chunking_func
                instance.lightrag.chunking_func = new_func
        await instance.process_folder_complete(folder_path, output_dir="./output", recursive=True)
        processing_tasks[task_id]["status"] = "completed"
        processing_tasks[task_id]["chunking_strategy"] = chunking_strategy or CHUNKING_STRATEGY
    except Exception as e:
        processing_tasks[task_id]["status"] = "failed"
        processing_tasks[task_id]["error"] = str(e)
        raise HTTPException(500, str(e))
    finally:
        if original_func and instance.lightrag:
            instance.lightrag.chunking_func = original_func
    return {"task_id": task_id, "folder": folder_path, "status": "completed"}


@router.post("/upload/content")
async def upload_content(req: PasteContentRequest, kb: str = Depends(verify_kb_access),
                          chunking_strategy: str = ""):
    """直接粘贴内容入库"""
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


@router.post("/upload/url")
async def upload_from_url(url: str = QueryParam(...), current_user: dict = Depends(get_current_user)):
    """从 URL 下载文档并入库"""
    if not url.startswith("http"):
        raise HTTPException(400, "无效 URL")
    task_id = str(uuid.uuid4())[:8]
    await add_event("url_download_start", url=url, task_id=task_id, user_id=current_user.get("id", 0))
    try:
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
async def list_documents(kb: str = Depends(verify_kb_access)):
    """列出所有文档及其状态（含处理中的任务）"""
    try:
        # Clean up completed/failed tasks before building the response
        cleanup_completed_tasks()

        status_path = Path(kb_dir(kb)) / "kv_store_doc_status.json"
        data = {}
        if status_path.exists():
            try:
                data = json.loads(status_path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                lightrag_logger.warning(f"doc_status JSON 损坏，返回空列表: {status_path}")
                data = {}

        # Deduplicate doc_status entries by original filename: keep only the
        # most recently updated entry per stripped filename.
        best_doc: dict[str, tuple[str, dict]] = {}  # orig_name → (doc_id, info)
        for doc_id, info in data.items():
            orig = _strip_hash_prefix(info.get("file_path", ""))
            if orig not in best_doc or info.get("updated_at", "") > best_doc[orig][1].get("updated_at", ""):
                best_doc[orig] = (doc_id, info)

        docs = []
        seen_files = set()
        for orig_name, (doc_id, info) in best_doc.items():
            # Check if there's a matching processing task with phase info
            doc_phase = ""
            for tid, task in processing_tasks.items():
                task_file = _strip_hash_prefix(task.get("file", ""))
                if task_file == orig_name and task.get("kb", "") == kb:
                    doc_phase = task.get("phase", "")
                    break
            docs.append({
                "id": doc_id[:16],
                "full_id": doc_id,
                "file": _strip_hash_prefix(info.get("file_path", "?")),
                "status": info.get("status", "?"),
                "chunks": info.get("chunks_count", 0),
                "length": info.get("content_length", 0),
                "created": info.get("created_at", ""),
                "updated": info.get("updated_at", ""),
                "phase": doc_phase,
            })
            seen_files.add(orig_name)

        # 合并处理中的任务（还未写入 doc_status），仅限当前 KB
        for tid, task in processing_tasks.items():
            if task.get("kb", "") != kb:
                continue
            fn = task.get("file", "")
            if fn and _strip_hash_prefix(fn) not in seen_files:
                docs.append({
                    "id": tid,
                    "full_id": tid,
                    "file": fn,
                    "status": task.get("status", "processing"),
                    "chunks": 0,
                    "length": 0,
                    "created": task.get("started_at", ""),
                    "updated": task.get("started_at", ""),
                    "phase": task.get("phase", ""),
                })
        return {"documents": sorted(docs, key=lambda d: d["updated"], reverse=True), "total": len(docs)}
    except Exception as e:
        raise HTTPException(500, str(e))


@router.get("/knowledge/stats")
async def knowledge_stats(kb: str = Depends(verify_kb_access)):
    """知识库总体统计"""

    def _safe_load_json(path: Path) -> dict:
        """安全加载 JSON，文件损坏时返回空 dict 并记录警告。"""
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            lightrag_logger.warning(f"JSON 文件损坏: {path} — {exc}")
            # 尝试修复：读取原始文本，移除尾部多余的内容后重新解析
            try:
                raw = path.read_text(encoding="utf-8")
                # 找到最后一个合法 JSON 对象的结束位置
                depth = 0
                last_valid = 0
                for i, ch in enumerate(raw):
                    if ch == '{':
                        depth += 1
                    elif ch == '}':
                        depth -= 1
                        if depth == 0:
                            last_valid = i + 1
                if last_valid > 0:
                    fixed = raw[:last_valid]
                    # 验证修复后的 JSON
                    data = json.loads(fixed)
                    lightrag_logger.info(f"JSON 修复成功: {path} (截取 {last_valid}/{len(raw)} 字符)")
                    # 写回修复后的内容
                    path.write_text(fixed, encoding="utf-8")
                    return data
            except Exception:
                pass
            return {}

    stats = {"documents": 0, "entities": 0, "relations": 0, "chunks": 0}
    base = Path(kb_dir(kb))

    # 实体总数（聚合 count）
    ep = base / "kv_store_full_entities.json"
    if ep.exists():
        for v in _safe_load_json(ep).values():
            stats["entities"] += v.get("count", len(v.get("entity_names", [])))

    # 关系总数
    rp = base / "kv_store_full_relations.json"
    if rp.exists():
        for v in _safe_load_json(rp).values():
            stats["relations"] += v.get("count", len(v.get("relation_pairs", [])))

    # 文档总数 & 分块总数 — 从 doc_status 聚合
    # （vdb_chunks.json 是 LightRAG NanoVectorDB 内部存储文件，其 JSON 键数不等于实际分块数）
    dp = base / "kv_store_doc_status.json"
    if dp.exists():
        doc_data = _safe_load_json(dp)
        stats["documents"] = len(doc_data)
        stats["chunks"] = sum(v.get("chunks_count", 0) for v in doc_data.values())
    return stats


@router.get("/knowledge/entities")
async def list_entities(request: Request, limit: int = 50, kb: str = Depends(verify_kb_access)):
    """列出知识图谱实体"""
    p = Path(kb_dir(kb)) / "kv_store_full_entities.json"
    if not p.exists():
        return {"entities": []}
    with open(p, "r", encoding="utf-8") as f:
        data = json.load(f)
    entities = []
    seen = set()
    for k, v in data.items():
        names = v.get("entity_names", [])
        for name in names:
            if name not in seen and len(entities) < limit:
                seen.add(name)
                entities.append({"id": name[:16], "name": name, "type": infer_entity_type(name)})
    # 类型筛选
    type_filter = request.query_params.get("type", "")
    if type_filter:
        entities = [e for e in entities if e["type"] == type_filter]

    return {"entities": entities, "total": sum(v.get("count", len(v.get("entity_names", []))) for v in data.values())}


@router.get("/knowledge/graph")
async def graph_data(kb: str = Depends(verify_kb_access)):
    """返回知识图谱数据(前端可视化用)"""
    ep = Path(kb_dir(kb)) / "kv_store_full_entities.json"
    rp = Path(kb_dir(kb)) / "kv_store_full_relations.json"
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

    # 从 entities 建节点
    if ep.exists():
        with open(ep, "r", encoding="utf-8") as f:
            for k, v in json.load(f).items():
                for name in v.get("entity_names", []):
                    if is_valid_node(name) and name not in node_ids:
                        node_ids.add(name)
                        nodes.append({"id": name, "label": name[:25]})

    # 从 relations 建边
    if rp.exists():
        with open(rp, "r", encoding="utf-8") as f:
            for k, v in json.load(f).items():
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


def _cleanup_document_files(kb_name: str, file_path: str, doc_id: str = "") -> None:
    """Delete uploaded file and parse output for a document.

    Called when a document or KB is deleted from the frontend.  Ensures the
    ``uploads/`` directory and per-KB parser output directory stay in sync
    with the knowledge base.
    """
    # 1. Delete the original uploaded file from uploads/
    if file_path:
        upload_file = Path("./uploads") / Path(file_path).name
        if upload_file.exists():
            try:
                upload_file.unlink()
                lightrag_logger.info(f"[CLEANUP] 已删除上传文件: {upload_file}")
            except FileNotFoundError:
                pass  # 已被并发请求删除

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


@router.delete("/knowledge/documents/{doc_id}")
async def delete_document(doc_id: str, kb: str = Depends(verify_kb_access), current_user: dict = Depends(get_current_user)):
    """删除文档 - 使用 LightRAG 的 adelete_by_doc_id 彻底清理所有关联数据"""
    instance = await get_kb(kb)
    if not instance.lightrag:
        raise HTTPException(500, "知识库未初始化")

    status_path = Path(kb_dir(kb)) / "kv_store_doc_status.json"
    if not status_path.exists():
        raise HTTPException(404, "无文档记录")

    with open(status_path, "r", encoding="utf-8") as f:
        doc_status = json.load(f)

    # 通过前缀匹配找到完整 doc_id
    full_id = None
    for k in doc_status:
        if k.startswith(doc_id):
            full_id = k
            break

    if not full_id:
        # 可能是一个处理中/失败的 processing task，尝试从 processing_tasks 中移除
        if doc_id in processing_tasks:
            task = processing_tasks.pop(doc_id)
            fname = task.get("file", "未知")
            await add_event("doc_delete", file=fname, doc_id=doc_id, kb=kb, source="processing_tasks", user_id=current_user["id"])
            return {"status": "deleted", "doc_id": doc_id, "file": fname, "message": "已从处理队列中移除"}
        # 也尝试按 file_path 匹配（前端可能传文件名相关的 ID）
        for tid, task in list(processing_tasks.items()):
            if task.get("kb", "") == kb and task.get("file", "") == doc_id:
                del processing_tasks[tid]
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
        # Force LightRAG storages to persist deletions to disk so that
        # _bigram_image_scan and other disk-level readers see up-to-date data.
        await instance.lightrag.finalize_storages()
        # Invalidate query cache to prevent stale results referencing deleted data
        from raganything.query_cache import get_query_cache
        get_query_cache().invalidate()
        return {"status": "deleted", "doc_id": full_id, "file": file_name, "message": result.message}
    elif result.status == "not_found":
        # Data may be partially missing (e.g. multimodal processing was
        # killed mid-flight).  Still remove the doc_status entry so the
        # user isn't stuck with an undeletable ghost document.
        try:
            del doc_status[full_id]
            tmp = status_path.with_suffix(".tmp")
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(doc_status, f, ensure_ascii=False, indent=2)
            tmp.replace(status_path)
            # Clean up file system leftovers and multimodal status cache
            _cleanup_document_files(kb, file_name, full_id)
            if hasattr(instance, "multimodal_status_cache") and instance.multimodal_status_cache is not None:
                try:
                    await instance.multimodal_status_cache.delete([full_id])
                    await instance.multimodal_status_cache.index_done_callback()
                except Exception:
                    pass
            # Invalidate query cache even for partial cleanup
            from raganything.query_cache import get_query_cache
            get_query_cache().invalidate()
            return {
                "status": "deleted",
                "doc_id": full_id,
                "file": file_name,
                "message": "文档记录已清理（部分数据不完整）",
            }
        except Exception:
            raise HTTPException(404, f"文档 {file_name} 数据未找到")
    else:
        raise HTTPException(500, result.message)


@router.post("/knowledge/documents/batch-delete")
async def batch_delete_documents(req: BatchDeleteRequest, kb: str = Depends(verify_kb_access), current_user: dict = Depends(get_current_user)):
    """批量删除文档 - 一次请求删除多个文档"""
    instance = await get_kb(kb)
    if not instance.lightrag:
        raise HTTPException(500, "知识库未初始化")

    status_path = Path(kb_dir(kb)) / "kv_store_doc_status.json"
    if not status_path.exists():
        raise HTTPException(404, "无文档记录")

    with open(status_path, "r", encoding="utf-8") as f:
        doc_status = json.load(f)

    deleted = []
    not_found = []
    errors = []

    deleted_full_ids: list[str] = []  # for multimodal_status_cache batch cleanup

    for doc_id in req.doc_ids:
        full_id = None
        for k in doc_status:
            if k.startswith(doc_id):
                full_id = k
                break

        if not full_id:
            # Try processing_tasks
            if doc_id in processing_tasks:
                task = processing_tasks.pop(doc_id)
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
                # Also clean up matching processing_tasks entry
                for tid, task in list(processing_tasks.items()):
                    if task.get("kb", "") == kb and task.get("file", "") == file_name:
                        del processing_tasks[tid]
            else:
                errors.append({"doc_id": doc_id, "error": result.message})
        except Exception as e:
            errors.append({"doc_id": doc_id, "error": str(e)})

    # Clean up multimodal status cache entries for deleted documents
    if deleted_full_ids and hasattr(instance, "multimodal_status_cache") and instance.multimodal_status_cache is not None:
        try:
            await instance.multimodal_status_cache.delete(deleted_full_ids)
            await instance.multimodal_status_cache.index_done_callback()
        except Exception:
            pass

    # Write doc_status back once
    with open(status_path, "w", encoding="utf-8") as f:
        json.dump(doc_status, f, ensure_ascii=False, indent=2)

    # Force LightRAG storages to persist deletions + invalidate query cache
    if deleted:
        await instance.lightrag.finalize_storages()
        from raganything.query_cache import get_query_cache
        get_query_cache().invalidate()

    return {"deleted": deleted, "not_found": not_found, "errors": errors,
            "total_deleted": len(deleted), "total_failed": len(errors)}


@router.post("/knowledge/documents/{doc_id}/retry")
async def retry_document(doc_id: str, kb: str = Depends(verify_kb_access), current_user: dict = Depends(get_current_user), background_tasks: BackgroundTasks = None):
    """重试处理失败的文档"""
    status_path = Path(kb_dir(kb)) / "kv_store_doc_status.json"
    if not status_path.exists():
        raise HTTPException(404, "文档不存在")
    with open(status_path, "r", encoding="utf-8") as f:
        data = json.load(f)

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

    # 删除旧的失败记录，触发重新处理
    del data[full_id]
    with open(status_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

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
        # Scan first to get count
        import json as _json
        from pathlib import Path as _Path
        from raganything.services.kb_service import kb_dir
        status_path = _Path(kb_dir(kb_name)) / "kv_store_doc_status.json"
        total = 0
        if status_path.exists():
            with open(status_path, "r", encoding="utf-8") as _f:
                all_docs = _json.load(_f)
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
    meta = load_kb_meta()
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
        save_kb_meta(meta)
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
async def create_kb(kb_name: str = QueryParam(...), current_user: dict = Depends(get_current_user), label: str = QueryParam("")):
    meta = load_kb_meta()
    if kb_name in meta:
        raise HTTPException(400, f"知识库 '{kb_name}' 已存在")
    label = label or kb_name
    meta[kb_name] = {
        "name": label, "created": datetime.now().isoformat(),
        "owner_id": current_user["id"],
        "owner_username": current_user["username"],
    }
    save_kb_meta(meta)
    # 预加载
    await get_kb(kb_name)
    return {"status": "created", "name": kb_name, "label": label}


@router.put("/kb/switch")
async def switch_kb(name: str = QueryParam(...), current_user: dict = Depends(get_current_user)):
    meta = load_kb_meta()
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
    if name == "default":
        raise HTTPException(400, "不能删除默认知识库")
    meta = load_kb_meta()
    if name not in meta:
        raise HTTPException(404, f"知识库 '{name}' 不存在")
    # 权限检查（仅 KB 所有者和管理员可删除）
    kb_info = meta[name]
    owner_id = kb_info.get("owner_id")
    if owner_id is not None and owner_id != current_user["id"] and not current_user.get("is_admin"):
        raise HTTPException(403, "无权删除该知识库")
    # 清理实例和文件
    if name in kb_instances:
        await kb_instances[name].finalize_storages()
        del kb_instances[name]

    # 清理该 KB 对应的上传文件
    # 从 doc_status 和 text_chunks 两个来源收集 file_path（兜底防止 doc_status 中 file_path 为空）
    _found_files: set = set()
    _kb_dir = Path(kb_dir(name))

    # 来源 1：doc_status
    doc_status_path = _kb_dir / "kv_store_doc_status.json"
    if doc_status_path.exists():
        try:
            doc_status = json.loads(doc_status_path.read_text("utf-8"))
            for info in doc_status.values():
                fp = info.get("file_path", "")
                if fp:
                    _found_files.add(fp)
        except Exception as e:
            lightrag_logger.warning(f"[CLEANUP] 读取 doc_status 失败 (KB={name}): {e}")

    # 来源 2：text_chunks（兜底 — 每个 chunk 都记录了 file_path）
    chunks_path = _kb_dir / "kv_store_text_chunks.json"
    if chunks_path.exists():
        try:
            chunks = json.loads(chunks_path.read_text("utf-8"))
            for chunk_data in chunks.values():
                try:
                    cd = json.loads(chunk_data) if isinstance(chunk_data, str) else chunk_data
                    fp = cd.get("file_path", "")
                    if fp and fp not in _found_files:
                        _found_files.add(fp)
                except Exception:
                    pass
        except Exception as e:
            lightrag_logger.warning(f"[CLEANUP] 读取 text_chunks 失败 (KB={name}): {e}")

    for fp in _found_files:
        upload_file = Path("./uploads") / Path(fp).name
        if upload_file.exists():
            try:
                upload_file.unlink()
                lightrag_logger.info(f"[CLEANUP] 已删除上传文件: {upload_file}")
            except FileNotFoundError:
                pass  # 已被并发请求删除
    # 删除该 KB 的解析输出目录
    output_dir = "./output" if name == "default" else f"./output_{name}"
    shutil.rmtree(output_dir, ignore_errors=True)
    # 清理该 KB 的处理中任务
    for tid, task in list(processing_tasks.items()):
        if task.get("kb", "") == name:
            del processing_tasks[tid]

    shutil.rmtree(kb_dir(name), ignore_errors=True)
    del meta[name]
    save_kb_meta(meta)
    if _shared.active_kb == name:
        _shared.active_kb = "default"
    # Invalidate query cache to prevent stale results referencing deleted KB data
    from raganything.query_cache import get_query_cache
    get_query_cache().invalidate()
    return {"status": "deleted", "name": name}


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
