"""
独立文件处理 Worker — 每个上传在独立子进程中运行
彻底隔离 LightRAG 实例，避免多 KB 共享 pipeline 状态

用法: python process_worker.py --file=<path> --kb=<name> [--strategy=<name>]
"""
import argparse
import asyncio
import json
import os
import sys
import io
import math
import uuid
from pathlib import Path
from functools import partial

_RESET_MARKER = Path(__file__).resolve().parent / ".system-reset-in-progress"
if _RESET_MARKER.exists():
    raise RuntimeError(f"System reset is in progress: {_RESET_MARKER}")

# Set the numeric-library limit before importing Docling, LightRAG, or any
# library that may load OpenBLAS.  The parent process overrides this value for
# managed uploads; this guard also protects manual worker runs.
try:
    _worker_threads = int(os.getenv("DOCUMENT_WORKER_MAX_THREADS", "1"))
except ValueError:
    _worker_threads = 1
_worker_threads = max(1, min(_worker_threads, 4))
for _thread_env in ("OPENBLAS_NUM_THREADS", "OMP_NUM_THREADS", "MKL_NUM_THREADS", "NUMEXPR_NUM_THREADS"):
    os.environ[_thread_env] = str(_worker_threads)

if __name__ == "__main__" and hasattr(sys.stdout, "buffer"):
    sys.stdout = io.TextIOWrapper(
        sys.stdout.buffer, encoding="utf-8", errors="replace", write_through=True
    )

# ── 配置来源：os.environ ────────────────────────────────
# Worker 子进程通过 asyncio.create_subprocess_exec() 继承父进程
# 的完整 os.environ。父进程的 PUT /api/settings 修改 os.environ
# 后，新启动的 Worker 自动获得最新配置 — 无需读取 .env 文件。
#
# 重要：不再调用 load_dotenv() 或从 .env 文件强制覆盖！
# 这确保 Admin API 的运行时设置变更能真正传播到 Worker。

from lightrag.llm.openai import openai_complete_if_cache, openai_embed
from lightrag.utils import EmbeddingFunc
from raganything import RAGAnything, RAGAnythingConfig
from raganything.embedding import create_vision_embed_func, make_cached_embed_func
from raganything.chunking import STRATEGY_META
from raganything.processor import get_pending_background_tasks
from raganything.utils.pdf_fallback import extract_pdf_embedded_images
from raganything.utils.process_lock import FileLock, get_file_lock_path

# 所有配置从 os.environ 读取（继承自父进程，反映 Admin API 最新设置）
API_KEY = os.getenv("LLM_BINDING_API_KEY")
BASE_URL = os.getenv("LLM_BINDING_HOST")
EMB_API_KEY = os.getenv("EMBEDDING_BINDING_API_KEY") or API_KEY
EMB_BASE_URL = os.getenv("EMBEDDING_BINDING_HOST") or BASE_URL
LLM_MODEL = os.getenv("LLM_MODEL", "qwen-plus")
EMB_MODEL = os.getenv("EMBEDDING_MODEL", "text-embedding-v3")
EMB_DIM = int(os.getenv("EMBEDDING_DIM", "1024"))
CHUNKING_STRATEGY = os.getenv("CHUNKING_STRATEGY", "recursive")
_VLM_IMAGE_MIME_TYPES = {"image/gif", "image/jpeg", "image/png", "image/webp"}


class RetryableExternalServiceError(RuntimeError):
    """Raised before durable writes when a configured model endpoint is offline."""


def _emit_worker_error(
    *, stage: str, error: BaseException, retryable: bool, secondary: list[str] | None = None,
) -> None:
    """Emit the single machine-readable error record consumed by the parent."""
    payload = {
        "stage": stage,
        "root_type": type(error).__name__,
        "failure_code": str(getattr(error, "failure_code", "")),
        "retryable": bool(retryable),
        "message": str(error)[:2000],
        "secondary": [str(item)[:1000] for item in (secondary or [])],
    }
    page_coverage = getattr(error, "page_coverage", None)
    if isinstance(page_coverage, dict):
        payload["page_coverage"] = {
            key: page_coverage.get(key, [])
            for key in (
                "source_total_pages",
                "successful_pages",
                "failed_pages",
                "skipped_pages",
                "retried_pages",
            )
        }
    print("WORKER_ERROR_JSON " + json.dumps(payload, ensure_ascii=False), flush=True)


def _exception_chain_text(exc: BaseException) -> str:
    values: list[str] = []
    seen: set[int] = set()
    current: BaseException | None = exc
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        values.extend((type(current).__name__, str(current), repr(current)))
        last_attempt = getattr(current, "last_attempt", None)
        if last_attempt is not None:
            try:
                nested = last_attempt.exception()
            except Exception:
                nested = None
            if isinstance(nested, BaseException) and id(nested) not in seen:
                current = nested
                continue
        current = current.__cause__ or current.__context__
    return " ".join(values).casefold()


def _is_retryable_external_error(exc: BaseException) -> bool:
    text = _exception_chain_text(exc)
    return any(marker in text for marker in (
        "apiconnectionerror",
        "connecterror",
        "connection error",
        "all connection attempts failed",
        "connection reset",
        "connection refused",
        "timed out",
        "timeout",
        "rate limit",
        "status code: 429",
        "status_code=429",
        "status code: 500",
        "status code: 502",
        "status code: 503",
        "status code: 504",
    ))


def _is_ocr_memory_error(exc: BaseException) -> bool:
    """Classify only the local OCR allocation failures, never remote model errors."""
    if getattr(exc, "failure_stage", "") == "ocr":
        return True
    text = _exception_chain_text(exc)
    return any(marker in text for marker in (
        "bad allocation",
        "std::bad_alloc",
        "memoryerror",
        "out of memory",
    )) and any(marker in text for marker in ("onnx", "rapidocr", "ocr", "bad_alloc"))


def _is_incomplete_pdf_coverage_error(exc: BaseException) -> bool:
    return (
        getattr(exc, "failure_code", "") == "pdf_page_coverage_incomplete"
        or "pdf page coverage is incomplete" in _exception_chain_text(exc)
    )


async def _preflight_embedding_service(rag) -> None:
    """Verify embedding availability before parsing or persisting a document."""
    if os.getenv("MODEL_PREFLIGHT_ENABLED", "true").strip().lower() in {
        "0", "false", "no", "off",
    }:
        return
    try:
        timeout = max(5, min(int(os.getenv("MODEL_PREFLIGHT_TIMEOUT", "20")), 120))
    except ValueError:
        timeout = 20
    probe = f"RAGAnything upload preflight {uuid.uuid4().hex}"
    try:
        provider = getattr(
            rag, "_raw_embedding_preflight_provider", rag._raw_embedding_provider
        )
        result = await asyncio.wait_for(
            provider([probe], timeout=timeout),
            timeout=timeout,
        )
        if result is None or len(result) != 1:
            raise RuntimeError("embedding preflight returned an invalid vector batch")
        vector = result[0]
        if len(vector) != EMB_DIM:
            raise RuntimeError(
                f"embedding preflight dimension mismatch: expected {EMB_DIM}, got {len(vector)}"
            )
        values = [float(value) for value in vector]
        if not all(math.isfinite(value) for value in values):
            raise RuntimeError("embedding preflight returned non-finite values")
        if math.sqrt(sum(value * value for value in values)) <= 0.0:
            raise RuntimeError("embedding preflight returned a zero-norm vector")
    except Exception as exc:
        if _is_retryable_external_error(exc):
            raise RetryableExternalServiceError(
                "外部 Embedding 服务暂时无法连接，请恢复模型网络后重试"
            ) from exc
        raise RuntimeError(f"Embedding 服务预检失败: {exc}") from exc



# VLM OCR 函数（内嵌，避免跨模块导入 server）
import base64
import pypdfium2 as pdfium
from PIL import Image

async def _vlm_ocr_document(file_path: str) -> str:
    """用千问 VL 模型对 PDF/图片做 OCR"""
    try:
        ext = file_path.lower().rsplit(".", 1)[-1] if "." in file_path else ""
        images = []
        if ext == "pdf":
            pdf = pdfium.PdfDocument(file_path)
            for i in range(min(len(pdf), 30)):
                page = pdf[i]
                bitmap = page.render(scale=2)
                img = bitmap.to_pil()
                buf = io.BytesIO()
                img.save(buf, format="JPEG", quality=70)
                images.append(base64.b64encode(buf.getvalue()).decode())
        elif ext in ("png", "jpg", "jpeg", "bmp", "tiff", "tif", "gif", "webp"):
            img = Image.open(file_path).convert("RGB")
            buf = io.BytesIO()
            img.save(buf, format="JPEG", quality=70)
            images.append(base64.b64encode(buf.getvalue()).decode())
        else:
            return ""

        all_text = []
        VISION_MODEL = os.getenv("VISION_MODEL", "qwen-vl-plus")
        for idx, b64 in enumerate(images):
            msgs = [
                {"role": "user", "content": [
                    {"type": "text", "text": "请对这张图片进行 OCR，提取所有文字内容。只输出提取的文字，不要添加任何解释。"},
                    {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}},
                ]},
            ]
            result = await openai_complete_if_cache(
                VISION_MODEL, "", system_prompt=None, history_messages=[],
                messages=msgs, api_key=API_KEY, base_url=BASE_URL,
            )
            if result and isinstance(result, str):
                all_text.append(result.strip())
            else:
                all_text.append("")

        return "\n\n".join(all_text)
    except Exception as e:
        print(f"[WORKER] VLM OCR 异常: {e}", flush=True)
        if _is_retryable_external_error(e):
            raise RetryableExternalServiceError(
                "外部 VLM 服务暂时无法连接，请恢复模型网络后重试"
            ) from e
        raise RuntimeError(f"VLM OCR 失败: {e}") from e


PLAIN_TEXT_EXTS = {"txt", "md", "csv", "json", "xml", "yaml", "yml",
                   "py", "js", "ts", "java", "c", "cpp", "h", "html", "css", "log"}


def kb_dir(name: str) -> str:
    return "./rag_storage" if name == "default" else f"./rag_storage_{name}"


def auto_parser(filename: str) -> str:
    ext = filename.lower().rsplit(".", 1)[-1] if "." in filename else ""
    if ext in ("epub",):
        return "marker"
    if ext in ("pdf", "docx", "pptx", "xlsx", "doc", "ppt", "xls", "txt", "md"):
        return "docling"
    if ext in ("png", "jpg", "jpeg", "bmp", "tiff", "tif", "gif", "webp"):
        return "mineru"
    if ext in ("mp4", "avi", "mov", "mkv", "webm"):
        return "video"
    return os.getenv("PARSER", "docling")


async def create_rag(parser=None, working_dir=None, chunking_strategy=None):
    if parser is None:
        parser = os.getenv("PARSER", "docling")
    if chunking_strategy is None:
        chunking_strategy = CHUNKING_STRATEGY
    wd = working_dir or os.getenv("WORKING_DIR", "./rag_storage")

    def llm_func(prompt, system_prompt=None, history_messages=None, **kw):
        if "max_tokens" not in kw:
            kw["max_tokens"] = int(os.getenv("MAX_TOKENS", "4096"))
        kw.setdefault("timeout", int(os.getenv("LLM_TIMEOUT", "180")))
        return openai_complete_if_cache(
            LLM_MODEL, prompt, system_prompt=system_prompt,
            history_messages=history_messages or [], api_key=API_KEY, base_url=BASE_URL, **kw,
        )

    VISION_MODEL = os.getenv("VISION_MODEL", "qwen-vl-plus")

    async def vision_func(prompt, system_prompt=None, history_messages=None,
                          image_data=None, image_mime_type=None, messages=None, **kw):
        """VLM 视觉模型函数（async）"""
        if messages is not None:
            return await openai_complete_if_cache(
                VISION_MODEL, "", system_prompt=None, history_messages=[],
                messages=messages, api_key=API_KEY, base_url=BASE_URL, **kw,
            )
        elif image_data is not None:
            mime_type = (
                image_mime_type
                if image_mime_type in _VLM_IMAGE_MIME_TYPES
                else "image/jpeg"
            )
            msgs = [
                {"role": "user", "content": [
                    {"type": "text", "text": prompt},
                    {"type": "image_url", "image_url": {"url": f"data:{mime_type};base64,{image_data}"}},
                ]},
            ]
            if system_prompt:
                msgs.insert(0, {"role": "system", "content": system_prompt})
            return await openai_complete_if_cache(
                VISION_MODEL, "", system_prompt=None, history_messages=[],
                messages=msgs, api_key=API_KEY, base_url=BASE_URL, **kw,
            )
        else:
            return await llm_func(
                prompt, system_prompt, history_messages or [], **kw
            )

    _raw_embed_func = partial(
        openai_embed.func,
        model=EMB_MODEL,
        api_key=EMB_API_KEY,
        base_url=EMB_BASE_URL,
        client_configs={
            "timeout": int(os.getenv("LLM_TIMEOUT", "180")),
            "max_retries": 0,
        },
    )
    _raw_embed_func.embedding_dim = EMB_DIM

    async def _preflight_embed_func(texts, *, timeout: int):
        raw_call = getattr(openai_embed.func, "__wrapped__", openai_embed.func)
        return await raw_call(
            texts,
            model=EMB_MODEL,
            api_key=EMB_API_KEY,
            base_url=EMB_BASE_URL,
            client_configs={"timeout": timeout, "max_retries": 0},
        )

    _cached_embed_func = make_cached_embed_func(_raw_embed_func, wd, EMB_MODEL)

    embedding_func = EmbeddingFunc(
        embedding_dim=EMB_DIM, max_token_size=8192,
        func=_cached_embed_func,
    )

    async def _embed_wrapper(texts):
        return await embedding_func.func(texts, model=EMB_MODEL)

    async def _llm_wrapper(prompt, system_prompt="", history_messages=None, **kw):
        return await llm_func(prompt, system_prompt=system_prompt,
                              history_messages=history_messages or [], **kw)

    chunking_map = {
        "fixed_size": None,
        "recursive": __import__("raganything.chunking", fromlist=["recursive_chunking"]).recursive_chunking,
        "sentence": __import__("raganything.chunking", fromlist=["sentence_chunking"]).sentence_chunking,
        "structure": __import__("raganything.chunking", fromlist=["structure_chunking"]).structure_chunking,
        "semantic": __import__("raganything.chunking", fromlist=["make_semantic_chunking"]).make_semantic_chunking(_embed_wrapper),
        "agentic": __import__("raganything.chunking", fromlist=["make_agentic_chunking"]).make_agentic_chunking(_llm_wrapper, LLM_MODEL),
    }
    chosen = chunking_map.get(chunking_strategy)

    def _env_int(key: str, default: int, min_val: int = 1, max_val: int = 100) -> int:
        """安全读取整数环境变量，防止 typo 导致启动崩溃或恶意超限值"""
        try:
            val = int(os.getenv(key, str(default)))
            return max(min_val, min(val, max_val))
        except ValueError:
            return default

    lightrag_kwargs = {
        "chunk_token_size": _env_int("CHUNK_SIZE", 800, max_val=4096),
        "chunk_overlap_token_size": _env_int("CHUNK_OVERLAP", 100, max_val=500),
        "embedding_batch_num": _env_int("EMBEDDING_BATCH_SIZE", 10, max_val=10),
        "embedding_func_max_async": _env_int("ENTITY_EXTRACT_CONCURRENCY", 3, max_val=16),
        # 显式传入 LightRAG 参数，消除 import-order 依赖
        "llm_model_max_async": _env_int("MAX_ASYNC", 4, max_val=16),
        "entity_extract_max_gleaning": _env_int("MAX_GLEANING", 1, max_val=2),
    }
    if chosen is not None:
        lightrag_kwargs["chunking_func"] = chosen

    # ── PG Storage Backends (align with kb_service.py create_rag) ──
    # When PostgreSQL is available, switch LightRAG from file-based
    # JSON storage to PG-backed storage. This is the P0 fix that ensures
    # the worker writes to the same PG tables that the server reads from.
    from raganything.services.kb_service import _pg_storage_ready as _srv_pg_ready
    from raganything.services.kb_service import _pg_vector_ready, _pg_age_ready

    if _srv_pg_ready():
        lightrag_kwargs["kv_storage"] = "PGKVStorage"
        lightrag_kwargs["doc_status_storage"] = "PGDocStatusStorage"

        if await _pg_vector_ready():
            lightrag_kwargs["vector_storage"] = "PGVectorStorage"

        if await _pg_age_ready():
            lightrag_kwargs["graph_storage"] = "PGGraphStorage"

    # ── PG workspace isolation ──────────────────────────────
    # LightRAG defaults workspace=os.getenv("WORKSPACE","") which is "".
    # Without an explicit workspace, ALL KBs share the same PG tables.
    lightrag_kwargs["workspace"] = wd

    config = RAGAnythingConfig(
        working_dir=wd, parser=parser,
        enable_image_processing=os.getenv("ENABLE_IMAGE_PROCESSING", "true").lower() == "true",
        enable_table_processing=os.getenv("ENABLE_TABLE_PROCESSING", "true").lower() == "true",
        enable_equation_processing=os.getenv("ENABLE_EQUATION_PROCESSING", "true").lower() == "true",
        enable_video_processing=os.getenv("ENABLE_VIDEO_PROCESSING", "false").lower() == "true",
        entity_types=os.getenv("ENTITY_TYPES", ""),
        entity_extraction_min_degree=int(os.getenv("ENTITY_EXTRACTION_MIN_DEGREE", "0")),
    )
    # Feature gate: only create vision_embed_func if VISION_SEARCH_ENABLED
    _vision_embed_func = None
    if os.getenv("VISION_SEARCH_ENABLED", "false").lower() == "true":
        _vision_embed_func = create_vision_embed_func(working_dir=wd)
    rag = RAGAnything(config=config, llm_model_func=llm_func,
                      vision_model_func=vision_func,
                      embedding_func=embedding_func,
                      vision_embed_func=_vision_embed_func,
                      lightrag_kwargs=lightrag_kwargs)
    # The availability probe must never hit the application's embedding cache.
    rag._raw_embedding_provider = _raw_embed_func
    rag._raw_embedding_preflight_provider = _preflight_embed_func
    return rag


def _fix_stuck_doc(filename: str, target_dir: str, error_msg: str) -> bool:
    """修复卡在 handling 的文档状态为 failed"""
    sp = Path(target_dir) / "kv_store_doc_status.json"
    if not sp.exists():
        return False
    try:
        with open(sp, "r", encoding="utf-8") as f:
            ds = json.load(f)
        changed = False
        for did, info in ds.items():
            stored = info.get("file_path", "")
            stored_base = os.path.basename(stored)
            search_base = os.path.basename(filename)
            # Robust match: handles hash-prefixed uploads (8-hex + "_" + original)
            # Length guard: prefix is exactly 9 chars (8 hex + 1 underscore)
            if (stored == filename
                    or stored_base == search_base
                    or (stored_base.endswith("_" + search_base)
                        and len(stored_base) - len(search_base) == 9)):
                if info.get("status") != "failed":
                    info["status"] = "failed"
                    info["error_msg"] = error_msg
                    changed = True
                break
        if changed:
            with open(sp, "w", encoding="utf-8") as f:
                json.dump(ds, f, ensure_ascii=False, indent=2)
            print(f"[WORKER] 已将文档状态标记为 failed: {filename}", flush=True)
        return changed
    except Exception as e:
        print(f"[WORKER] 无法更新文档状态: {e}", flush=True)
        return False


# Maximum seconds to wait for background multimodal tasks before giving up.
# Keep the worker-side guard aligned with the parent watchdog unless explicitly
# overridden. A 30-minute fixed default is too short for image-heavy manuals.
try:
    _BG_TASK_MAX_WAIT = int(
        os.getenv(
            "BG_TASK_MAX_WAIT",
            os.getenv("PROCESS_IDLE_TIMEOUT", os.getenv("PROCESS_TIMEOUT", "1800")),
        )
    )
except (TypeError, ValueError):
    _BG_TASK_MAX_WAIT = 1800
_BG_TASK_MAX_WAIT = max(1, _BG_TASK_MAX_WAIT)


async def _await_pending_background_tasks() -> None:
    """Wait for all registered background tasks to finish before subprocess exit."""
    pending = get_pending_background_tasks()
    if not pending:
        return

    print(
        f"[WORKER] 等待 {len(pending)} 个后台多模态任务完成 "
        f"(最长 {_BG_TASK_MAX_WAIT}s)...",
        flush=True,
    )
    try:
        done, still_pending = await asyncio.wait(
            pending, timeout=_BG_TASK_MAX_WAIT
        )
        if still_pending:
            print(
                f"[WORKER] ⚠ 超时: {len(still_pending)} 个后台任务未在 "
                f"{_BG_TASK_MAX_WAIT}s 内完成，强制退出",
                flush=True,
            )
            for t in still_pending:
                t.cancel()
        else:
            print(
                f"[WORKER] 所有 {len(done)} 个后台任务已完成",
                flush=True,
            )
    except Exception as exc:
        print(f"[WORKER] 等待后台任务时出错: {exc}", flush=True)


async def _drain_background_tasks_or_raise() -> None:
    """Drain this isolated worker's registry and fail on timeout or task errors."""
    loop = asyncio.get_running_loop()
    deadline = loop.time() + _BG_TASK_MAX_WAIT
    while True:
        pending = get_pending_background_tasks()
        if not pending:
            return
        remaining = deadline - loop.time()
        if remaining <= 0:
            for task in pending:
                task.cancel()
            await asyncio.gather(*pending, return_exceptions=True)
            raise TimeoutError(
                f"background processing exceeded {_BG_TASK_MAX_WAIT} seconds"
            )
        done, still_pending = await asyncio.wait(pending, timeout=remaining)
        results = await asyncio.gather(*done, return_exceptions=True)
        errors = [result for result in results if isinstance(result, BaseException)]
        if errors:
            raise RuntimeError(f"background processing failed: {errors[0]}")
        if still_pending:
            for task in still_pending:
                task.cancel()
            await asyncio.gather(*still_pending, return_exceptions=True)
            raise TimeoutError(
                f"background processing exceeded {_BG_TASK_MAX_WAIT} seconds"
            )


async def _flush_background_tasks_and_finalize(rag, filename: str) -> None:
    """Complete background multimodal writes before closing LightRAG storage."""
    print(f"[PROGRESS] phase=multimodal-tasks status=start file={filename}", flush=True)
    await _drain_background_tasks_or_raise()
    print(f"[PROGRESS] phase=multimodal-tasks status=done file={filename}", flush=True)
    print(f"[PROGRESS] phase=graph-building status=start file={filename}", flush=True)
    await rag.finalize_storages()
    print(f"[PROGRESS] phase=graph-building status=done file={filename}", flush=True)


async def process_file(file_path: str, kb_name: str, chunking_strategy: str = "",
                     enable_image: bool | None = None, enable_table: bool | None = None,
                     enable_equation: bool | None = None, enable_video: bool | None = None) -> int:
    """处理单个文件并写入对应 KB 目录"""
    filename = os.path.basename(file_path)
    target_dir = kb_dir(kb_name)
    strategy = chunking_strategy or CHUNKING_STRATEGY

    # ── Per-upload multimodal overrides ─────────────────
    # If any multimodal toggle is explicitly set, override the env var
    # so the RAGAnythingConfig picks it up.
    if enable_image is not None:
        os.environ["ENABLE_IMAGE_PROCESSING"] = str(enable_image).lower()
    if enable_table is not None:
        os.environ["ENABLE_TABLE_PROCESSING"] = str(enable_table).lower()
    if enable_equation is not None:
        os.environ["ENABLE_EQUATION_PROCESSING"] = str(enable_equation).lower()
    if enable_video is not None:
        os.environ["ENABLE_VIDEO_PROCESSING"] = str(enable_video).lower()
    ext = filename.lower().rsplit(".", 1)[-1] if "." in filename else ""
    merge_failed = False  # Track merging/extraction failures

    # ── PG pool init for worker subprocess ─────────────────
    # The parent server process's PG connection pool is an in-memory
    # Python object that does NOT survive asyncio.create_subprocess_exec().
    # Without this init, _pg_storage_ready() returns False in the worker,
    # causing a storage-backend mismatch: worker writes to JSON files,
    # server reads from PG tables → documents 2..N become invisible.
    try:
        from raganything.services.pg_state_repo import init_pg_pool
        await init_pg_pool()
    except Exception:
        pass  # PG unavailable → worker falls back to JSON (backward compatible)

    strategy_name = STRATEGY_META.get(strategy, {}).get("name", strategy)
    print(f"[WORKER] 开始处理: file={filename} kb={kb_name} dir={target_dir} strategy={strategy_name}", flush=True)

    # ── Duplicate worker guard (L3 + L4) ───────────────────
    # L3: Check doc_status — is another worker already processing this file?
    _DOC_STATUS_STALE_SEC = 300  # 5 minutes
    sp_status = Path(target_dir) / "kv_store_doc_status.json"
    if sp_status.exists():
        try:
            with open(sp_status, "r", encoding="utf-8") as f:
                ds = json.load(f)
            for _did, _info in ds.items():
                _stored = _info.get("file_path", "")
                _s_base = os.path.basename(_stored)
                _f_base = os.path.basename(filename)
                if not (_stored == filename
                        or _s_base == _f_base
                        or (_s_base.endswith("_" + _f_base)
                            and len(_s_base) - len(_f_base) == 9)):
                    continue
                if _info.get("status") == "processing":
                    from datetime import datetime, timezone
                    _updated = _info.get("updated_at", "")
                    try:
                        _dt = datetime.fromisoformat(str(_updated))
                        _age = (datetime.now(timezone.utc) - _dt).total_seconds()
                    except Exception:
                        _age = 0
                    if _age < _DOC_STATUS_STALE_SEC:
                        print(
                            f"[WORKER] 文档 {filename} 有活跃的处理器 "
                            f"(updated {_age:.0f}s ago)，退出",
                            flush=True,
                        )
                        return 3
                    else:
                        print(
                            f"[WORKER] 文档 {filename} 的 processing 状态已过期 "
                            f"({_age:.0f}s)，继续处理",
                            flush=True,
                        )
                break
        except Exception as exc:
            print(f"[WORKER] 读取 doc_status 失败: {exc}，跳过检查", flush=True)

    # L4: Acquire exclusive file lock (based on content hash, not filename —
    # two uploads of the same file get different random prefixes but identical content)
    import hashlib
    _fh = hashlib.sha256()
    with open(file_path, "rb") as _rf:
        _fh.update(_rf.read(65536))
    _fh = _fh.hexdigest()[:16]
    lock_path = get_file_lock_path(os.getenv("WORKING_DIR", "./rag_storage"), _fh)
    file_lock = FileLock(str(lock_path))
    if not file_lock.acquire():
        print(
            f"[WORKER] 文件已被另一个 Worker 锁定: {filename} (lock: {lock_path})",
            flush=True,
        )
        return 3

    rag = None
    finalized = False
    current_stage = "initializing"
    primary_error: BaseException | None = None
    secondary_errors: list[str] = []
    exit_code = 0
    try:
        # Initialize storage handles, then prove that the external embedding
        # dependency is reachable before parsing or writing any document rows.
        rag = await create_rag(working_dir=target_dir, chunking_strategy=strategy)
        rag.disable_atexit_cleanup()
        await rag._ensure_lightrag_initialized()
        current_stage = "model_preflight"
        print(f"[PROGRESS] phase=model-preflight status=start file={filename}", flush=True)
        await _preflight_embedding_service(rag)
        print(f"[PROGRESS] phase=model-preflight status=done file={filename}", flush=True)

        safe_path = str(Path(file_path).resolve())
        current_stage = "parsing"
        if ext in PLAIN_TEXT_EXTS:
            print("[WORKER] 纯文本模式，直接读取", flush=True)
            print(f"[PROGRESS] phase=parsing status=start file={filename}", flush=True)
            with open(file_path, "r", encoding="utf-8", errors="replace") as f:
                text_content = f.read()
            if text_content.strip():
                await rag.insert_content_list(
                    [{"type": "text", "text": text_content, "page_idx": 0}],
                    file_path=filename,
                    chunking_strategy=strategy,
                )
            print(f"[PROGRESS] phase=parsing status=done file={filename}", flush=True)
        else:
            output_dir = f"./output_{kb_name}" if kb_name != "default" else "./output"
            docling_ok = False
            print(f"[PROGRESS] phase=parsing status=start file={filename}", flush=True)
            try:
                await rag.process_document_complete(
                    safe_path,
                    output_dir=output_dir,
                    chunking_strategy=strategy,
                )
                docling_ok = True
            except Exception as e:
                if _is_retryable_external_error(e):
                    current_stage = "embedding"
                    raise RetryableExternalServiceError(
                        "External model service is temporarily unavailable"
                    ) from e
                if _is_ocr_memory_error(e):
                    # Docling's bounded PDF path already retried the individual
                    # failing page once. A whole-document VLM fallback cannot
                    # prove 100% page coverage, so it must not mask this error.
                    current_stage = "ocr"
                    raise
                if _is_incomplete_pdf_coverage_error(e):
                    # A partial result is not an eligible VLM fallback: the
                    # fallback has no all-source-page completion proof.
                    current_stage = "parsing"
                    raise
                err_msg = str(e)
                print(f"[WORKER] Docling 处理失败: {err_msg[:150]}", flush=True)
                # "Separator is not found" 错误：PDF 文本是大段连续内容，手动分行后重试
                if "Separator is not found" in err_msg or "chunk exceed" in err_msg:
                    print("[WORKER] 检测到大段连续文本，尝试预处理后重试...", flush=True)
                    try:
                        # 读取 PDF 文本内容，每隔 400 字符插入换行
                        with open(safe_path, "rb") as f:
                            raw = f.read()
                        # 尝试读取已解析的文本
                        import glob as _glob
                        md_files = _glob.glob(f"{output_dir}/**/*.md", recursive=True)
                        if md_files:
                            for mf in md_files[:3]:
                                with open(mf, "r", encoding="utf-8", errors="replace") as f:
                                    text = f.read()
                                # 插入段落分隔符
                                text = text.replace("。", "。\n\n").replace(". ", ".\n\n")
                                # 长行强制换行
                                lines = text.split("\n")
                                new_lines = []
                                for line in lines:
                                    if len(line) > 400:
                                        for i in range(0, len(line), 400):
                                            new_lines.append(line[i:i+400])
                                    else:
                                        new_lines.append(line)
                                with open(mf, "w", encoding="utf-8") as f:
                                    f.write("\n".join(new_lines))
                            print("[WORKER] 预处理完成，重试中...", flush=True)
                            await rag.process_document_complete(
                                safe_path,
                                output_dir=output_dir,
                                chunking_strategy=strategy,
                            )
                            docling_ok = True
                        else:
                            print("[WORKER] 未找到解析输出文件，使用 VLM OCR 兜底", flush=True)
                    except Exception as e2:
                        print(f"[WORKER] 预处理失败: {e2}，使用 VLM OCR 兜底", flush=True)

            # VLM OCR 兜底（Docling 失败或产生 0 chunk 时触发）
            if ext in ("pdf", "doc", "png", "jpg", "jpeg", "bmp", "tiff", "tif", "gif", "webp"):
                chunks_ok = False
                sp = Path(target_dir) / "kv_store_doc_status.json"
                if sp.exists():
                    with open(sp, "r", encoding="utf-8") as f:
                        ds = json.load(f)
                    for did, info in ds.items():
                        _stored = info.get("file_path", "")
                        _s_base = os.path.basename(_stored)
                        _f_base = os.path.basename(filename)
                        if (_stored == filename
                                or _s_base == _f_base
                                or (_s_base.endswith("_" + _f_base)
                                    and len(_s_base) - len(_f_base) == 9)):
                            if info.get("chunks_count", 0) > 0:
                                chunks_ok = True
                            break
                # A PG-backed worker may not have a local JSON doc-status file.
                # In that case a successful Docling run is not evidence that it
                # produced zero chunks, so only use the local status result when
                # it was actually available.
                chunks_status_known = sp.exists()
                needs_fallback = not docling_ok or (chunks_status_known and not chunks_ok)
                if needs_fallback:
                    current_stage = "vlm_ocr"
                    print(f"[WORKER] VLM OCR 兜底: {filename}", flush=True)
                    try:
                        ocr_text = await _vlm_ocr_document(file_path)
                        if not ocr_text.strip():
                            raise RuntimeError("VLM OCR returned no usable text")
                        fallback_content = [
                            {"type": "text", "text": ocr_text, "page_idx": 0}
                        ]
                        if (
                            ext == "pdf"
                            and os.getenv("ENABLE_IMAGE_PROCESSING", "true").lower()
                            == "true"
                        ):
                            fallback_content.extend(
                                extract_pdf_embedded_images(file_path, output_dir)
                            )
                        if fallback_content:
                            await rag.insert_content_list(
                                fallback_content,
                                file_path=filename,
                                chunking_strategy=strategy,
                            )
                            print(f"[WORKER] VLM OCR 完成: {len(ocr_text)} 字符", flush=True)
                    except Exception as e2:
                        print(f"[WORKER] VLM OCR 失败: {e2}", flush=True)
                        raise

        current_stage = "finalize"
        await _flush_background_tasks_and_finalize(rag, filename)
        finalized = True

        # Verify that chunks were actually created — if the merging/extraction
        # stage failed silently, the document status will report zero chunks.
        sp = Path(target_dir) / "kv_store_doc_status.json"
        if sp.exists():
            with open(sp, "r", encoding="utf-8") as f:
                ds = json.load(f)
            found = False
            for did, info in ds.items():
                stored = info.get("file_path", "")
                if stored == filename or stored.endswith(filename) or os.path.basename(stored) == filename:
                    found = True
                    chunks_count = info.get("chunks_count", 0)
                    doc_status = info.get("status", "")
                    if chunks_count == 0:
                        # Truly failed: no text chunks were produced
                        merge_failed = True
                        print(
                            f"[WORKER] ERROR: 文档处理失败 (chunks=0). "
                            f"status={doc_status} doc_id={did}",
                            flush=True,
                        )
                    elif doc_status == "failed":
                        # Partial success: chunks exist but entity extraction failed
                        # Data is still usable for Q&A; log warning, don't exit 1
                        print(
                            f"[WORKER] WARNING: 实体提取失败但文本块已入库 "
                            f"(chunks={chunks_count} status=failed doc_id={did}). "
                            f"向量检索可用，知识图谱可能不完整。",
                            flush=True,
                        )
                    break
            if not found:
                print(f"[WORKER] WARNING: 文档记录未在 doc_status 中找到: {filename}", flush=True)

        if merge_failed:
            print(f"[WORKER] 失败 (合并阶段错误): {filename}", flush=True)
            raise RuntimeError("document processing produced zero chunks")

        print(f"[WORKER] 完成: {filename}", flush=True)

    except Exception as e:
        # 兜底：任何未捕获异常都将文档标记为失败，避免永久卡在 handling
        import traceback
        print(f"[WORKER] ERROR: unhandled {type(e).__name__}: {e}", flush=True)
        traceback.print_exc()
        primary_error = e
        retryable = (
            not _is_ocr_memory_error(e)
            and (isinstance(e, RetryableExternalServiceError) or _is_retryable_external_error(e))
        )
        exit_code = 4 if retryable else 1
        chain_text = _exception_chain_text(e)
        if current_stage == "parsing" and _is_ocr_memory_error(e):
            current_stage = "ocr"
        elif current_stage == "parsing" and "embedding" in chain_text:
            current_stage = "embedding"
        elif current_stage == "parsing" and any(
            marker in chain_text for marker in ("entity", "llm", "completion")
        ):
            current_stage = "entity_extraction"
        if current_stage != "model_preflight":
            _fix_stuck_doc(filename, target_dir, f"Worker 异常退出: {str(e)[:200]}")

    finally:
        if rag is not None and not finalized:
            try:
                await rag.finalize_storages()
            except Exception as exc:
                secondary_errors.append(f"finalize: {type(exc).__name__}: {exc}")
                print(f"[WORKER] WARNING: storage cleanup failed: {exc}", flush=True)
        if file_lock.is_locked():
            file_lock.release()
        # Clean up PG pool created by this worker subprocess
        try:
            from raganything.services.pg_state_repo import close_pg_pool
            await close_pg_pool()
        except Exception as exc:
            secondary_errors.append(f"pg_pool: {type(exc).__name__}: {exc}")

    if primary_error is not None:
        _emit_worker_error(
            stage=current_stage,
            error=primary_error,
            retryable=exit_code == 4,
            secondary=secondary_errors,
        )
    return exit_code


def _flush_standard_streams() -> None:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.flush()
        except Exception:
            pass


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--file", required=True)
    parser.add_argument("--kb", required=True)
    parser.add_argument("--strategy", default="")
    parser.add_argument("--enable-image", dest="enable_image", default=None,
                        choices=["true", "false"])
    parser.add_argument("--enable-table", dest="enable_table", default=None,
                        choices=["true", "false"])
    parser.add_argument("--enable-equation", dest="enable_equation", default=None,
                        choices=["true", "false"])
    parser.add_argument("--enable-video", dest="enable_video", default=None,
                        choices=["true", "false"])
    args = parser.parse_args()

    try:
        worker_exit_code = asyncio.run(process_file(
            args.file, args.kb, args.strategy,
            enable_image=args.enable_image == "true" if args.enable_image else None,
            enable_table=args.enable_table == "true" if args.enable_table else None,
            enable_equation=args.enable_equation == "true" if args.enable_equation else None,
            enable_video=args.enable_video == "true" if args.enable_video else None,
        ))
    except BaseException as exc:
        retryable = _is_retryable_external_error(exc)
        _emit_worker_error(
            stage="bootstrap", error=exc, retryable=retryable, secondary=[],
        )
        worker_exit_code = 4 if retryable else 1
    _flush_standard_streams()
    os._exit(int(worker_exit_code))
