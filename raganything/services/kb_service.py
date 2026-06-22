# -*- coding: utf-8 -*-
"""
RAG-Anything Knowledge Base (KB) Service.

Layer: Service
Primary Responsibility: KB instance lifecycle — create, retrieve, delete,
    metadata persistence, RAGAnything factory.
Key Dependencies: raganything (RAGAnything, RAGAnythingConfig), lightrag

Extracted from routers/shared.py. All KB instance management is centralized here.
"""

from __future__ import annotations

import json
from typing import Any, Optional
import os
import sys
import re
import asyncio
import logging
from datetime import datetime
from functools import partial
from pathlib import Path

from dotenv import load_dotenv
load_dotenv(dotenv_path=".env", override=False)

from lightrag.llm.openai import openai_complete_if_cache, openai_embed
from lightrag.utils import EmbeddingFunc
from raganything import RAGAnything, RAGAnythingConfig
from raganything.chunking import (
    recursive_chunking,
    sentence_chunking,
    structure_chunking,
    make_semantic_chunking,
    make_agentic_chunking,
)

# ── Configuration ─────────────────────────────────────────
API_KEY = os.getenv("LLM_BINDING_API_KEY")
BASE_URL = os.getenv("LLM_BINDING_HOST")
LLM_MODEL = os.getenv("LLM_MODEL", "qwen-plus")
VISION_MODEL = os.getenv("VISION_MODEL", "qwen-vl-plus")
EMB_MODEL = os.getenv("EMBEDDING_MODEL", "text-embedding-v3")
EMB_DIM = int(os.getenv("EMBEDDING_DIM", "1024"))
WORKING_DIR = os.getenv("WORKING_DIR", "./rag_storage")
CHUNKING_STRATEGY = os.getenv("CHUNKING_STRATEGY", "recursive")

# ── KB State ──────────────────────────────────────────────
kb_instances: dict[str, RAGAnything] = {}
_kb_locks: dict[str, asyncio.Lock] = {}
active_kb: str = "default"
KB_META_FILE = Path("./rag_storage_kb_meta.json")

kb_logger = logging.getLogger("rag_server.kb")

# ── Upload Dedup Tracking ───────────────────────────────────
# Maps (kb_name, file_hash) -> task_id for active processing tasks.
# Entries are removed when the worker completes or fails.
_processing_files: dict[tuple[str, str], str] = {}


def _compute_file_hash(file_path: str) -> str:
    """Compute a short content hash for upload deduplication.

    Uses SHA256 on the **first 64 KiB** of the file for speed (uploaded
    files may be hundreds of MB). Returns the first 16 hex chars.
    """
    import hashlib
    h = hashlib.sha256()
    with open(file_path, "rb") as f:
        h.update(f.read(65536))
    return h.hexdigest()[:16]


def _is_file_being_processed(kb_name: str, file_hash: str) -> str | None:
    """Check if a file is currently being processed in the given KB.

    Returns:
        The existing task_id if processing, or None.
    """
    return _processing_files.get((kb_name, file_hash))


def _register_processing_file(kb_name: str, file_hash: str, task_id: str) -> None:
    """Register a file as currently being processed."""
    _processing_files[(kb_name, file_hash)] = task_id


def _unregister_processing_file(kb_name: str, file_hash: str) -> None:
    """Remove a file from the processing tracker (called on completion/failure)."""
    _processing_files.pop((kb_name, file_hash), None)


# ── KB Metadata Persistence ────────────────────────────────

def load_kb_meta() -> dict[str, Any]:
    """Load KB metadata from JSON file."""
    if KB_META_FILE.exists():
        with open(KB_META_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {"default": {"name": "默认知识库", "created": datetime.now().isoformat()}}


def save_kb_meta(meta: dict[str, Any]) -> None:
    """Persist KB metadata to JSON file atomically (tmp + replace)."""
    tmp = KB_META_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(KB_META_FILE)


def kb_dir(name: str) -> str:
    """Get storage directory path for a KB name."""
    return "./rag_storage" if name == "default" else f"./rag_storage_{name}"


# ── KB Instance Management ─────────────────────────────────

async def get_kb(name: str = None) -> RAGAnything:
    """Get or create a KB instance.

    Args:
        name: KB name (defaults to active_kb)

    Returns:
        RAGAnything instance for the named KB
    """
    name = name or active_kb
    # Serialize initialization per KB to prevent concurrent creation race
    if name not in _kb_locks:
        _kb_locks[name] = asyncio.Lock()
    async with _kb_locks[name]:
        if name not in kb_instances:
            from lightrag.kg.shared_storage import set_default_workspace
            target = kb_dir(name)
            set_default_workspace(target)
            instance = create_rag(working_dir=target)
            await instance._ensure_lightrag_initialized()
            # Lower vector retrieval cosine threshold for broader semantic recall
            if instance.lightrag and hasattr(instance.lightrag, 'chunks_vdb'):
                instance.lightrag.chunks_vdb.cosine_better_than_threshold = 0.0
            kb_instances[name] = instance
            kb_logger.info(f"[KB] 初始化知识库实例: {name} workspace={target}")
    return kb_instances[name]


async def delete_kb(name: str) -> bool:
    """Delete a KB instance and its storage.

    Args:
        name: KB name to delete

    Returns:
        True if deleted, False if not found
    """
    if name not in kb_instances and name not in load_kb_meta():
        return False

    # Remove from in-memory cache
    if name in kb_instances:
        try:
            await kb_instances[name].finalize_storages()
        except Exception:
            pass
        del kb_instances[name]

    # Remove metadata
    meta = load_kb_meta()
    if name in meta:
        del meta[name]
        save_kb_meta(meta)

    kb_logger.info(f"[KB] 已删除知识库: {name}")
    return True


def list_kbs() -> dict[str, Any]:
    """List all KB metadata entries."""
    return load_kb_meta()


# ── RAGAnything Factory ────────────────────────────────────

def create_rag(
    parser: str = None,
    working_dir: str = None,
    chunking_strategy: str = None,
) -> RAGAnything:
    """Create a RAGAnything instance with configured LLM/embedding functions.

    Args:
        parser: Parser name (default from env PARSER or "mineru")
        working_dir: Working directory for LightRAG storage
        chunking_strategy: Chunking strategy name

    Returns:
        Configured RAGAnything instance
    """
    if parser is None:
        parser = os.getenv("PARSER", "mineru")
    if chunking_strategy is None:
        chunking_strategy = CHUNKING_STRATEGY
    wd = working_dir or WORKING_DIR

    def llm_func(prompt, system_prompt=None, history_messages=[], **kw):
        if "max_tokens" not in kw:
            kw["max_tokens"] = int(os.getenv("MAX_TOKENS", "4096"))
        return openai_complete_if_cache(
            LLM_MODEL, prompt, system_prompt=system_prompt,
            history_messages=history_messages, api_key=API_KEY, base_url=BASE_URL, **kw,
        )

    def vision_func(prompt, system_prompt=None, history_messages=[],
                    image_data=None, messages=None, **kw):
        if messages is not None:
            return openai_complete_if_cache(
                VISION_MODEL, "", system_prompt=None, history_messages=[],
                messages=messages, api_key=API_KEY, base_url=BASE_URL, **kw,
            )
        elif image_data is not None:
            return openai_complete_if_cache(
                VISION_MODEL, "", system_prompt=None, history_messages=[],
                messages=[
                    {"role": "system", "content": system_prompt} if system_prompt else None,
                    {"role": "user", "content": [
                        {"type": "text", "text": prompt},
                        {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{image_data}"}},
                    ]},
                ],
                api_key=API_KEY, base_url=BASE_URL, **kw,
            )
        else:
            return llm_func(prompt, system_prompt, history_messages, **kw)

    # LightRAG's @wrap_embedding_func_with_attrs hardcodes embedding_dim=1536,
    # but DashScope text-embedding-v3 returns 1024-dim vectors. We override the
    # embedding_dim attribute on the partial function so LightRAG allocates
    # vector storage at the correct (API-native) dimension.
    _embed_func = partial(
        openai_embed.func, model=EMB_MODEL, api_key=API_KEY, base_url=BASE_URL
    )
    _embed_func.embedding_dim = EMB_DIM

    embedding_func = EmbeddingFunc(
        embedding_dim=EMB_DIM, max_token_size=8192,
        func=_embed_func,
    )

    # ── Chunking strategy mapping ──────────────────────────
    chunk_token_size = int(os.getenv("CHUNK_SIZE", "800"))

    def _get_embedding_func_for_chunk(texts: list[str]) -> list[list[float]]:
        return embedding_func.func(texts, model=EMB_MODEL)

    async def _get_llm_func_for_chunk(prompt: str, system_prompt: str = "",
                                       history_messages=None, **kw):
        return await llm_func(prompt, system_prompt=system_prompt,
                              history_messages=history_messages or [], **kw)

    chunking_strategy_map = {
        "fixed_size": None,  # Use LightRAG default
        "recursive": recursive_chunking,
        "sentence": sentence_chunking,
        "structure": structure_chunking,
        "semantic": make_semantic_chunking(_get_embedding_func_for_chunk),
        "agentic": make_agentic_chunking(_get_llm_func_for_chunk, LLM_MODEL),
    }
    chosen_chunking_func = chunking_strategy_map.get(chunking_strategy)

    lightrag_kwargs = {
        "chunk_token_size": chunk_token_size,
        "chunk_overlap_token_size": int(os.getenv("CHUNK_OVERLAP", "100")),
        "enable_llm_cache": os.getenv("ENABLE_LLM_CACHE", "true").lower() == "true",
        "enable_llm_cache_for_entity_extract": os.getenv("ENABLE_LLM_CACHE_FOR_EXTRACT", "true").lower() == "true",
        "embedding_batch_num": int(os.getenv("EMBEDDING_BATCH_SIZE", "10")),
        "embedding_func_max_async": int(os.getenv("ENTITY_EXTRACT_CONCURRENCY", "3")),
    }
    if chosen_chunking_func is not None:
        lightrag_kwargs["chunking_func"] = chosen_chunking_func

    config = RAGAnythingConfig(
        working_dir=wd,
        parser=parser,
        enable_image_processing=os.getenv("ENABLE_IMAGE_PROCESSING", "false").lower() == "true",
        enable_table_processing=os.getenv("ENABLE_TABLE_PROCESSING", "false").lower() == "true",
        enable_equation_processing=os.getenv("ENABLE_EQUATION_PROCESSING", "false").lower() == "true",
        enable_video_processing=os.getenv("ENABLE_VIDEO_PROCESSING", "false").lower() == "true",
    )

    return RAGAnything(config=config, llm_model_func=llm_func,
                       vision_model_func=vision_func, embedding_func=embedding_func,
                       lightrag_kwargs=lightrag_kwargs)


# ── Stuck Document Recovery ─────────────────────────────────

async def _fix_stuck_doc_status(kb_name: str, filename: str):
    """Fix documents stuck in 'handling' state after subprocess crash/timeout.

    Args:
        kb_name: KB name
        filename: The file whose doc_status may be stuck
    """
    try:
        status_path = Path(kb_dir(kb_name)) / "kv_store_doc_status.json"
        if not status_path.exists():
            return
        with open(status_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        changed = False
        for doc_id, info in data.items():
            if info.get("file_path") == filename and info.get("status") == "handling":
                info["status"] = "failed"
                info["error_msg"] = "处理中断：子进程异常退出或超时"
                changed = True
                kb_logger.warning(
                    f"[FIX-STUCK] 修复卡住的文档: {filename} (KB={kb_name}) handling→failed"
                )
        if changed:
            tmp = status_path.with_suffix(".tmp")
            tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
            tmp.replace(status_path)
    except Exception as ex:
        kb_logger.error(f"[FIX-STUCK] 修复失败: {ex}")


# ── Document Upload Processing ─────────────────────────────

def _verify_document_persisted(kb_name: str, filename: str) -> None:
    """Verify that a processed document has chunks in doc_status.

    Raises RuntimeError if the document is missing from doc_status or has
    zero chunks after worker subprocess reports success.
    """
    import json as _json
    status_path = Path(kb_dir(kb_name)) / "kv_store_doc_status.json"
    if not status_path.exists():
        raise RuntimeError(
            f"文档处理异常：doc_status 文件不存在 ({status_path})"
        )
    try:
        data = _json.loads(status_path.read_text(encoding="utf-8"))
    except Exception:
        raise RuntimeError("文档处理异常：doc_status 文件无法解析")

    fname = os.path.basename(filename)
    for doc_id, info in data.items():
        stored = os.path.basename(info.get("file_path", ""))
        if stored == fname:
            chunks = info.get("chunks_count", 0)
            status = info.get("status", "?")
            if chunks == 0:
                raise RuntimeError(
                    f"文档处理异常：chunks=0, status={status} (doc_id={doc_id[:16]})"
                )
            return
    raise RuntimeError(f"文档处理异常：doc_status 中未找到匹配记录 ({fname})")


async def _process_uploaded_file(
    task_id: str, file_path: str, filename: str,
    kb_name: str = "default", chunking_strategy: str = "", user_id: int = 0,
):
    """Background upload processing via isolated subprocess.

    This function coordinates with ws_service and state_service for
    progress reporting and status tracking.

    Args:
        task_id: Unique task identifier
        file_path: Path to the uploaded file
        filename: Original filename
        kb_name: Target KB name
        chunking_strategy: Chunking strategy override
        user_id: Owner user ID
    """
    from raganything.services.ws_service import ws_broadcast, emit_progress, add_event
    from raganything.services.state_service import processing_tasks

    processing_tasks[task_id] = {
        "id": task_id, "file": filename, "status": "processing",
        "started_at": datetime.now().isoformat(), "progress": 0,
        "kb": kb_name, "user_id": user_id,
    }
    await add_event("upload_start", file=filename, task_id=task_id, user_id=user_id)
    actual_strategy = chunking_strategy or CHUNKING_STRATEGY

    # Register for dedup tracking
    file_hash = _compute_file_hash(file_path)
    _register_processing_file(kb_name, file_hash, task_id)

    try:
        await emit_progress(task_id, 5, f"子进程处理: {filename}")
        kb_logger.info(f"[UPLOAD] 任务={task_id} 文件={filename} KB={kb_name} 策略={actual_strategy}")

        worker_script = Path(__file__).parent.parent.parent / "process_worker.py"
        cmd = [
            sys.executable, str(worker_script),
            "--file", str(Path(file_path).resolve()),
            "--kb", kb_name,
            "--strategy", actual_strategy,
        ]

        await emit_progress(task_id, 10, "处理中...")

        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=str(Path(__file__).parent.parent.parent),
        )

        worker_output_lines: list[str] = []

        async def _read_stream(stream):
            while True:
                line = await stream.readline()
                if not line:
                    break
                text = line.decode("utf-8", errors="replace").strip()
                if text:
                    worker_output_lines.append(text)
                    kb_logger.info(f"[WORKER:{task_id}] {text}")
                    # Parse structured progress lines from worker
                    m = re.match(
                        r"\[PROGRESS\]\s+phase=(\S+)\s+status=(\S+)(?:\s+file=(.+))?",
                        text,
                    )
                    if m and task_id in processing_tasks:
                        phase = m.group(1)
                        status = m.group(2)
                        # Map phases to progress percentages
                        phase_map = {
                            "parsing": (5, 25),
                            "entity-extraction": (25, 55),
                            "embedding": (55, 75),
                            "graph-building": (75, 90),
                            "multimodal-tasks": (90, 98),
                        }
                        if phase in phase_map:
                            pct = phase_map[phase][1] if status == "done" else phase_map[phase][0]
                        else:
                            pct = processing_tasks[task_id].get("progress", 0)
                        processing_tasks[task_id]["progress"] = pct
                        processing_tasks[task_id]["phase"] = phase
                        processing_tasks[task_id]["phase_status"] = status
                        await ws_broadcast({
                            "type": "progress", "task_id": task_id,
                            "progress": pct, "phase": phase, "phase_status": status,
                            "message": f"{phase}: {status}",
                        })

        stdout_task = asyncio.ensure_future(_read_stream(proc.stdout))
        stderr_task = asyncio.ensure_future(_read_stream(proc.stderr))
        try:
            timeout_sec = int(os.getenv("PROCESS_TIMEOUT", "3600"))
            await asyncio.wait_for(proc.wait(), timeout=timeout_sec)
        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()
            raise RuntimeError(
                f"子进程处理超时（{timeout_sec // 60}分钟），"
                "文档过大或图片过多，可设置环境变量 PROCESS_TIMEOUT 调整"
            )
        await stdout_task
        await stderr_task

        # Check worker output for merge/extraction errors
        worker_has_errors = any(
            "ERROR:" in line and ("Merging stage failed" in line or "chunks=0" in line)
            for line in worker_output_lines
        )

        if proc.returncode != 0:
            # Exit code 3 = worker conflict (file already locked by another worker)
            if proc.returncode == 3:
                conflict_lines = [l for l in worker_output_lines if "already being processed" in l or "active processor" in l]
                conflict_detail = conflict_lines[0] if conflict_lines else "文件正在被另一个 Worker 处理"
                raise RuntimeError(f"处理冲突: {conflict_detail}")
            error_lines = [l for l in worker_output_lines if "ERROR" in l]
            error_detail = "; ".join(error_lines[-2:]) if error_lines else f"exit code {proc.returncode}"
            raise RuntimeError(f"子进程处理失败: {error_detail}")

        if worker_has_errors:
            error_lines = [l for l in worker_output_lines if "ERROR:" in l and "Merging" in l]
            error_detail = error_lines[0] if error_lines else "Merging stage failed"
            raise RuntimeError(f"子进程实体提取失败 (chunks=0): {error_detail}")

        # Verify data was actually persisted: the worker may exit 0 even when
        # LightRAG internally marked the document as failed.
        _verify_document_persisted(kb_name, filename)

        # Clear cached instance so next query reloads from disk
        if kb_name in kb_instances:
            try:
                await kb_instances[kb_name].finalize_storages()
            except Exception as e:
                kb_logger.warning(f"[KB] finalize_storages 失败 ({kb_name}): {e}")
            del kb_instances[kb_name]
            kb_logger.info(f"[KB] 清除缓存实例: {kb_name}（子进程写入新数据）")

        await emit_progress(task_id, 100, "处理完成")
        processing_tasks[task_id]["status"] = "completed"
        processing_tasks[task_id]["chunking_strategy"] = actual_strategy
        await add_event("upload_complete", file=filename, task_id=task_id, kb=kb_name, user_id=user_id)
        await ws_broadcast({"type": "upload_done", "task_id": task_id, "filename": filename, "kb": kb_name})
        _unregister_processing_file(kb_name, file_hash)

    except Exception as e:
        processing_tasks[task_id]["status"] = "failed"
        processing_tasks[task_id]["error"] = str(e)
        await add_event("upload_error", file=filename, task_id=task_id, error=str(e), user_id=user_id)
        await _fix_stuck_doc_status(kb_name, filename)
        _unregister_processing_file(kb_name, file_hash)


WORKFLOW_DIR = Path("./workflows")
WORKFLOW_DIR.mkdir(exist_ok=True)


# ── Utility: Citation block builder ────────────────────────

def _build_citation_block(ctx: str, answer: str) -> str:
    """Build a citation source block from retrieval context.

    Parses [来源 文档名] markers in the context and builds a structured
    reference summary. Returns empty string if none found or already present.

    Args:
        ctx: Retrieval context text
        answer: LLM answer text

    Returns:
        Citation block string or empty string
    """
    import re as _re
    if ctx is None or answer is None:
        return ""
    if '📚 参考来源' in answer or '【引用来源】' in answer:
        return ""

    seen_docs: set[str] = set()
    for m in _re.finditer(r'\[来源\s*([^\]]+?)\]', ctx):
        name = m.group(1).strip()
        if name and not name.isdigit():
            seen_docs.add(name)

    if not seen_docs:
        return ""

    lines = ["\n📚 参考来源"]
    for doc in sorted(seen_docs):
        lines.append(f"[来源 {doc}]")
    lines.append("\n（系统自动追加：LLM 未生成引用块，此处仅列出相关文档名。）")

    return "\n".join(lines)


async def _get_kb_doc_list(kb: str) -> str:
    """Get formatted list of available documents in a KB for prompt context.

    Args:
        kb: KB name

    Returns:
        Formatted document list string for LLM prompts
    """
    try:
        instance = await get_kb(kb)
        doc_names = set()
        if hasattr(instance, '_ensure_chunk_source_cache'):
            await instance._ensure_chunk_source_cache()
        if hasattr(instance, '_chunk_source_cache') and instance._chunk_source_cache:
            for info in instance._chunk_source_cache.values():
                name = info.get('document_name', '')
                if name and name != 'unknown':
                    doc_names.add(name)
        if not doc_names and instance.lightrag:
            try:
                store = instance.lightrag.doc_status
                if hasattr(store, '_data'):
                    async with store._storage_lock:
                        for ds in store._data.values():
                            fp = ds.get('file_path', '')
                            if fp:
                                doc_names.add(fp)
            except Exception:
                pass

        if not doc_names:
            return ""

        lines = [f"- 《{name}》" for name in sorted(doc_names)[:10]]
        return (
            "## 可用文档\n"
            "以下文档在检索内容中以 `[来源 文档名]` 标注。"
            "回答时请用 `[来源 文档名]` 标注每条引用来源。\n"
            + "\n".join(lines)
        )
    except Exception:
        return ""


# ── Utility: Entity type inference ─────────────────────────

def infer_entity_type(name: str) -> str:
    """Infer entity type from name for knowledge graph classification.

    Args:
        name: Entity name string

    Returns:
        Entity type: 'organization', 'method', 'metric', 'image',
        'equation', 'component', 'ui', or 'concept'
    """
    n = str(name).lower()
    if any(w in n for w in ['大学', '学院', '公司', '医院', '研究所', '实验室',
                              'institute', 'university', 'hospital']):
        return 'organization'
    if any(w in n for w in ['模型', '算法', '方法', '网络', '框架', 'model',
                              'algorithm', 'network', 'method', 'mobilenet',
                              'resnet', 'efficientnet', 'cnn', 'rnn', 'transformer']):
        return 'method'
    if n.replace('.', '').replace('%', '').replace('-', '').isdigit() or \
       any(c in n for c in ['%', 'ms', 'mb', 'db']):
        return 'metric'
    if any(w in n for w in ['.png', '.jpg', '.jpeg', '.gif', 'image', '图像', '图片', '图']):
        return 'image'
    if any(w in n for w in ['函数', '公式', 'function', 'equation', 'loss',
                              'sigmoid', 'relu', 'softmax']):
        return 'equation'
    if any(w in n for w in ['层', '卷积', 'layer', 'conv', 'batch', 'norm',
                              'dropout', 'pool']):
        return 'component'
    if any(w in n for w in ['接口', 'api', '页面', '系统', '界面', 'interface',
                              'page', 'system', 'button', 'icon', 'form']):
        return 'ui'
    if any(w in n for w in ['数据', '精度', '准确率', '召回', 'f1', 'accuracy',
                              'precision', 'recall']):
        return 'metric'
    return 'concept'


__all__ = [
    "kb_instances",
    "active_kb",
    "KB_META_FILE",
    "load_kb_meta",
    "save_kb_meta",
    "kb_dir",
    "get_kb",
    "create_kb",
    "delete_kb",
    "list_kbs",
    "create_rag",
    "_fix_stuck_doc_status",
    "_process_uploaded_file",
    "_build_citation_block",
    "_get_kb_doc_list",
    "infer_entity_type",
    "API_KEY",
    "BASE_URL",
    "LLM_MODEL",
    "VISION_MODEL",
    "EMB_MODEL",
    "EMB_DIM",
    "WORKING_DIR",
    "CHUNKING_STRATEGY",
    "WORKFLOW_DIR",
]
