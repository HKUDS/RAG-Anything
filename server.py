"""
RAG-Anything FastAPI 服务器
启动: python server.py
访问: http://localhost:8000
"""
import io
import os
import sys
import asyncio
from datetime import datetime
from pathlib import Path
from raganything.services.runtime_settings import bootstrap_runtime_settings

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

_RESET_MARKER = Path(__file__).resolve().parent / ".system-reset-in-progress"
if _RESET_MARKER.exists():
    raise RuntimeError(f"System reset is in progress: {_RESET_MARKER}")

from dotenv import load_dotenv
load_dotenv(dotenv_path=".env", override=False)


bootstrap_runtime_settings()

from fastapi import FastAPI, Request
from fastapi.security import HTTPBearer
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
from starlette.middleware.base import BaseHTTPMiddleware
import uvicorn



# Hint appended to LLM prompt when context has no text chunks (only entities/relations)
_DEGRADED_HINT = (
    "\n\n⚠️ 注意：本次检索未能获取到关联的文档文本内容，"
    "以下回答仅基于实体名称和关系路径，可能不够详细。"
    "如果信息不足，请如实说明。"
)
from raganything.services.auth import (
    init_db,
)

security = HTTPBearer()

# ── 配置 ──────────────────────────────────────────
API_KEY = os.getenv("LLM_BINDING_API_KEY")
BASE_URL = os.getenv("LLM_BINDING_HOST")
LLM_MODEL = os.getenv("LLM_MODEL", "qwen-plus")
VISION_MODEL = os.getenv("VISION_MODEL", "qwen-vl-plus")
EMB_MODEL = os.getenv("EMBEDDING_MODEL", "text-embedding-v3")
EMB_DIM = int(os.getenv("EMBEDDING_DIM", "1024"))
WORKING_DIR = os.getenv("WORKING_DIR", "./rag_storage")
CHUNKING_STRATEGY = os.getenv("CHUNKING_STRATEGY", "recursive")

# ── 日志（轮转文件 + 控制台）─────────────────────
import logging
from logging.handlers import RotatingFileHandler

LOG_DIR = os.getenv("LOG_DIR", os.path.join(WORKING_DIR, "logs"))
LOG_MAX_BYTES = int(os.getenv("LOG_MAX_BYTES", str(10 * 1024 * 1024)))  # 10MB
LOG_BACKUP_COUNT = int(os.getenv("LOG_BACKUP_COUNT", "10"))
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")

def _setup_logging() -> logging.Logger:
    """配置 rag_server 日志：轮转文件 + 控制台输出"""
    Path(LOG_DIR).mkdir(parents=True, exist_ok=True)
    _logger = logging.getLogger("rag_server")
    _logger.setLevel(getattr(logging, LOG_LEVEL.upper(), logging.INFO))

    # 避免重复添加 handler（多 worker 模式下每个子进程各自添加）
    if not _logger.handlers:
        # 轮转文件 handler
        _fh = RotatingFileHandler(
            Path(LOG_DIR) / "server.log",
            maxBytes=LOG_MAX_BYTES,
            backupCount=LOG_BACKUP_COUNT,
            encoding="utf-8",
        )
        _fh.setFormatter(logging.Formatter(
            "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
            datefmt="%Y-%m-%dT%H:%M:%S",
        ))
        _logger.addHandler(_fh)

        # 控制台 handler（stderr，uvicorn 会捕获）
        _ch = logging.StreamHandler(sys.stderr)
        _ch.setFormatter(logging.Formatter(
            "[%(levelname)s] %(name)s: %(message)s"
        ))
        _logger.addHandler(_ch)

    return _logger

# 立即初始化日志
_server_logger = _setup_logging()

# ── 存储空间监控 ──────────────────────────────────
from prometheus_client import Gauge as PromGauge
from prometheus_client import REGISTRY as _PROM_REGISTRY

DISK_ALERT_THRESHOLD_MB = int(os.getenv("DISK_ALERT_THRESHOLD_MB", "10240"))  # 10GB
DISK_ALERT_PERCENT = float(os.getenv("DISK_ALERT_PERCENT", "85"))  # 85%
DISK_CHECK_INTERVAL = int(os.getenv("DISK_CHECK_INTERVAL", "300"))  # 5 min

def _get_or_create_gauge(name: str, description: str, labelnames: list) -> PromGauge:
    """Create a Prometheus Gauge, reusing existing if already registered
    (handles uvicorn multi-worker module re-import)."""
    try:
        return PromGauge(name, description, labelnames)
    except ValueError:
        return _PROM_REGISTRY._names_to_collectors[name]

_storage_usage_bytes_g = _get_or_create_gauge(
    "rag_storage_bytes",
    "Storage directory total size in bytes",
    ["dir"],
)
_storage_file_count_g = _get_or_create_gauge(
    "rag_storage_file_count",
    "Number of files in storage directory",
    ["dir"],
)

async def _disk_monitor_loop(interval: int = DISK_CHECK_INTERVAL):
    """周期性扫描存储目录，更新 Prometheus 指标并在超阈值时告警"""
    # 延迟首次检查，等所有 KB 加载完毕
    await asyncio.sleep(60)
    while True:
        try:
            storage_path = Path(WORKING_DIR)
            if storage_path.exists():
                total_bytes = 0
                file_count = 0
                for f in storage_path.rglob("*"):
                    if f.is_file():
                        try:
                            total_bytes += f.stat().st_size
                            file_count += 1
                        except OSError:
                            pass
                _storage_usage_bytes_g.labels(dir=WORKING_DIR).set(total_bytes)
                _storage_file_count_g.labels(dir=WORKING_DIR).set(file_count)
                total_mb = total_bytes / (1024 * 1024)
                if total_mb > DISK_ALERT_THRESHOLD_MB:
                    _server_logger.warning(
                        f"磁盘告警: 存储目录 {WORKING_DIR} 占用 {total_mb:.1f}MB，"
                        f"超过阈值 {DISK_ALERT_THRESHOLD_MB}MB"
                    )
        except Exception as exc:
            _server_logger.error(f"磁盘监控错误: {exc}")
        await asyncio.sleep(interval)

app = FastAPI(title="RAG-Anything API", version="1.3.1")

# ── Rate Limiting ──────────────────────────────────
limiter = Limiter(key_func=get_remote_address, default_limits=["120/minute"])
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# ── Prometheus Metrics ─────────────────────────────
from prometheus_fastapi_instrumentator import Instrumentator
_metrics_path = os.getenv("METRICS_PATH", "/metrics")
_instrumentator = Instrumentator(
    should_group_status_codes=True,
    should_ignore_untemplated=True,
    should_respect_env_var=True,
    should_instrument_requests_inprogress=True,
    excluded_handlers=[_metrics_path, "/health", "/favicon.ico"],
    env_var_name="ENABLE_METRICS",
    inprogress_name="rag_requests_inprogress",
    inprogress_labels=True,
)
_instrumentator.instrument(app).expose(app, endpoint=_metrics_path, include_in_schema=True)

# ── CORS 白名单 ─────────────────────────────────────
_cors_origins_str = os.getenv("CORS_ORIGINS", "http://localhost:5173,http://localhost:3000,http://127.0.0.1:5173")
_cors_origins = [o.strip() for o in _cors_origins_str.split(",") if o.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type"],
    allow_credentials=True,
)

# ── 安全响应头 ──────────────────────────────────────
class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-XSS-Protection"] = "1; mode=block"
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
        response.headers["Content-Security-Policy"] = "default-src 'self'; script-src 'self' 'unsafe-inline' 'unsafe-eval'; style-src 'self' 'unsafe-inline'; img-src 'self' data: blob:; connect-src 'self' ws: wss:"
        return response

app.add_middleware(SecurityHeadersMiddleware)

MAX_UPLOAD_SIZE = int(os.getenv("MAX_UPLOAD_SIZE_MB", "500")) * 1024 * 1024
MAX_BODY_SIZE = int(os.getenv("MAX_BODY_SIZE_MB", "10")) * 1024 * 1024

class RequestSizeMiddleware(BaseHTTPMiddleware):
    """请求大小限制中间件"""
    async def dispatch(self, request: Request, call_next):
        content_length = request.headers.get("content-length")
        if content_length:
            cl = int(content_length)
            if request.url.path.startswith("/api/upload") and cl > MAX_UPLOAD_SIZE:
                return JSONResponse(
                    {"detail": f"文件超过最大限制 {os.getenv('MAX_UPLOAD_SIZE_MB','500')}MB"},
                    status_code=413,
                )
            elif not request.url.path.startswith("/api/upload") and cl > MAX_BODY_SIZE:
                return JSONResponse(
                    {"detail": f"请求体超过最大限制 {os.getenv('MAX_BODY_SIZE_MB','10')}MB"},
                    status_code=413,
                )
        return await call_next(request)

app.add_middleware(RequestSizeMiddleware)

# ── 日志敏感信息脱敏 ────────────────────────────────
from raganything.utils.security import apply_sensitive_log_filter
apply_sensitive_log_filter()

# ── 多知识库管理 ──────────────────────────────────
# 共享状态从 services 层导入，保持模块级别名向后兼容
from raganything.services.kb_service import (
    kb_instances, get_kb, create_rag as create_rag,
    load_kb_meta, save_kb_meta, kb_dir as kb_dir,
    infer_entity_type as infer_entity_type,
    _build_citation_block as _build_citation_block,
    _get_kb_doc_list as _get_kb_doc_list,
    _fix_stuck_doc_status as _fix_stuck_doc_status,
    _process_uploaded_file as _process_uploaded_file,
    KB_META_FILE as KB_META_FILE,
)
from raganything.services.ws_service import (
    ws_clients as ws_clients,
    processing_events as processing_events,
    ws_broadcast as ws_broadcast,
    emit_progress as emit_progress,
    add_event as add_event,
    load_persisted_monitor_events,
)
from raganything.services.state_service import (
    processing_tasks as processing_tasks, load_tasks_from_pg,
)
from raganything.routers.shared import (
    get_current_user as get_current_user,
    get_admin_user as get_admin_user,
    verify_kb_access as verify_kb_access,
    validate_query_input as validate_query_input,
    extract_image_paths as extract_image_paths,
    _is_thinking_msg as _is_thinking_msg,
    _translate_thinking_msg as _translate_thinking_msg,
    QUERY_SYSTEM_PROMPT as QUERY_SYSTEM_PROMPT,
    THINKING_PATTERNS as THINKING_PATTERNS,
    server_logger,
)
# Router 注册
from raganything.routers.auth import router as auth_router
from raganything.routers.knowledge import router as knowledge_router
from raganything.routers.agent import router as agent_router
from raganything.routers.admin import router as admin_router
from raganything.routers.autorepair import router as autorepair_router
from raganything.routers.vision import router as vision_router

app.include_router(auth_router, prefix="/api")
app.include_router(knowledge_router, prefix="/api")
app.include_router(agent_router, prefix="/api")
app.include_router(admin_router, prefix="/api")
app.include_router(autorepair_router, prefix="/api")
app.include_router(vision_router, prefix="/api")

@app.on_event("startup")
async def startup():
    # 初始化 PostgreSQL 连接池（必需 — 无 SQLite 回退）
    from raganything.services.pg_state_repo import init_pg_pool, ensure_monitor_event_table
    from raganything.services.kb_tag_repo import ensure_tag_schema
    await init_pg_pool()
    await ensure_monitor_event_table()
    await ensure_tag_schema()
    from raganything.embedding.image_vector_repo import _ensure_workspace_schema
    await _ensure_workspace_schema()
    # 验证 P0 数据表（智能体 + KB 元数据）
    from raganything.services.pg_agent_repo import pg_ensure_agent_tables
    from raganything.services.pg_kb_meta_repo import pg_ensure_kb_tables
    await pg_ensure_agent_tables()
    await pg_ensure_kb_tables()
    from raganything.services.document_repair import ensure_document_repair_jobs_table
    await ensure_document_repair_jobs_table()
    from raganything.services.document_tagging import ensure_document_tag_jobs_table
    await ensure_document_tag_jobs_table()
    from raganything.services.upload_retry import (
        ensure_upload_retry_jobs_table,
        start_upload_retry_runner,
    )
    await ensure_upload_retry_jobs_table()
    from raganything.services.pg_graph_edit_repo import ensure_graph_edit_tables
    await ensure_graph_edit_tables()
    server_logger.info("PG P0 tables (agents, kb_metadata, graph_edit) verified")

    # 初始化认证数据库
    await init_db()
    from raganything.services.auth import (
        DEFAULT_ADMIN_USERNAME,
        get_user_by_username,
        refresh_runtime_constants,
    )
    refresh_runtime_constants()
    admin_user = await get_user_by_username(DEFAULT_ADMIN_USERNAME)
    if not admin_user:
        raise RuntimeError("Default administrator was not created")
    admin_id = int(admin_user["id"])
    admin_username = str(admin_user["username"])
    # 加载所有知识库元数据
    meta = await load_kb_meta()
    # Ensure the first-install baseline exists and always belongs to the
    # administrator's real database ID (which is not necessarily 1).
    default_created = "default" not in meta
    if default_created:
        now = datetime.now().isoformat()
        meta["default"] = {
            "name": "默认知识库",
            "created": now,
            "domain": "general",
            "description": "",
            "owner_id": admin_id,
            "owner_username": admin_username,
            "status": "ready",
            "document_count": 0,
            "updated_at": now,
            "extra": {},
        }
    # 迁移旧知识库：无 owner_id 的 KB 全部归当前管理员
    changed = False
    for kb_name, kb_info in meta.items():
        if not int(kb_info.get("owner_id") or 0):
            kb_info["owner_id"] = admin_id
            kb_info["owner_username"] = admin_username
            changed = True
    if changed or default_created:
        await save_kb_meta(meta)
    if changed:
        print(
            f"[KB-MIGRATE] 已将 {sum(1 for v in meta.values() if v.get('owner_id') == admin_id)} 个知识库分配给管理员",
            flush=True,
        )
    # 从 PG 恢复处理中任务（崩溃恢复）
    await load_tasks_from_pg()
    await load_persisted_monitor_events()
    # 初始化智能体（PG）
    from raganything.services.pg_agent_repo import (
        pg_ensure_default_agent,
        pg_list_agents,
    )
    # 迁移旧智能体和对话：无 owner_id 的归管理员
    from raganything.services.pg_state_repo import get_pg_pool
    pool = get_pg_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE agents SET owner_id=$1, owner_username=$2 WHERE owner_id=0",
            admin_id,
            admin_username,
        )
        await conn.execute(
            "UPDATE agent_conversations SET owner_id=$1 WHERE owner_id=0",
            admin_id,
        )
    await pg_ensure_default_agent(
        LLM_MODEL,
        owner_id=admin_id,
        owner_username=admin_username,
    )
    agents = await pg_list_agents(is_admin=True)
    # Recovery can inspect many persistent workspaces, so keep it out of the
    # startup critical path. The loop performs its first scan after a short
    # delay and is cancelled before storage teardown on shutdown.
    from raganything.services.kb_service import _stuck_recovery_loop
    app.state.stuck_recovery_task = asyncio.create_task(_stuck_recovery_loop(300))
    from raganything.services.document_repair import repair_loop
    app.state.document_repair_task = asyncio.create_task(repair_loop(15))
    from raganything.services.document_tagging import document_tagging_loop
    app.state.document_tagging_task = asyncio.create_task(document_tagging_loop(3))
    await start_upload_retry_runner()
    # 启动磁盘空间监控（Prometheus 指标 + 阈值告警）
    asyncio.create_task(_disk_monitor_loop(DISK_CHECK_INTERVAL))
    # 预加载默认知识库
    await get_kb("default")
    server_logger.info(f"RAG-Anything 服务器已启动，智能体: {len(agents)}个, 知识库: {list(meta.keys())}")

@app.on_event("shutdown")
async def shutdown():
    from raganything.services.upload_retry import stop_upload_retry_runner
    await stop_upload_retry_runner()
    recovery_task = getattr(app.state, "stuck_recovery_task", None)
    if recovery_task is not None:
        recovery_task.cancel()
        try:
            await recovery_task
        except asyncio.CancelledError:
            pass
        except Exception:
            server_logger.warning("Recovery task failed during shutdown", exc_info=True)

    repair_task = getattr(app.state, "document_repair_task", None)
    if repair_task is not None:
        repair_task.cancel()
        try:
            await repair_task
        except asyncio.CancelledError:
            pass
        except Exception:
            server_logger.warning("Document repair task failed during shutdown", exc_info=True)

    tagging_task = getattr(app.state, "document_tagging_task", None)
    if tagging_task is not None:
        tagging_task.cancel()
        try:
            await tagging_task
        except asyncio.CancelledError:
            pass
        except Exception:
            server_logger.warning("Document tagging task failed during shutdown", exc_info=True)

    from raganything.services.kb_service import _cancel_deferred_auto_tag_tasks
    await _cancel_deferred_auto_tag_tasks()

    for name, kb in list(kb_instances.items()):
        try:
            await kb.finalize_storages()
        except asyncio.CancelledError:
            raise
        except Exception:
            server_logger.warning(
                "Failed to finalize KB storage during shutdown: %s",
                name,
                exc_info=True,
            )
    # 关闭 PostgreSQL 连接池
    try:
        from raganything.services.pg_state_repo import close_pg_pool
        await close_pg_pool()
    except Exception:
        server_logger.warning("Failed to close PG pool during shutdown", exc_info=True)

# ── Server Startup Guard ─────────────────────────────────────
def _acquire_server_lock(port: int, workers: int = 1) -> None:
    """Ensure server instances don't conflict.

    - Single-worker mode (default): exclusive PID lock — refuses to start
      if another instance is already running on the same port.
    - Multi-worker mode (workers > 1): skips PID lock. Workers share the
      port via SO_REUSEPORT (uvicorn handles this). Port pre-check is
      still performed to catch obvious misconfiguration.

    On success, writes a PID file (single-worker) or a multi-worker PID
    manifest (multi-worker) and registers cleanup handlers.
    """
    import atexit
    import signal
    import socket
    from datetime import datetime, timezone
    from raganything.utils.process_lock import get_server_pid_path

    pid_path = get_server_pid_path(WORKING_DIR)
    pid_path.parent.mkdir(parents=True, exist_ok=True)

    if workers <= 1:
        # ── Single-worker: exclusive PID lock ──
        if pid_path.exists():
            try:
                stale_pid = int(pid_path.read_text(encoding="utf-8").strip())
            except (ValueError, OSError):
                stale_pid = None
            if stale_pid is not None:
                try:
                    os.kill(stale_pid, 0)
                    server_logger.error(
                        f"Server 已在运行 (PID {stale_pid})。"
                        f"如果确定未运行，请删除 {pid_path}"
                    )
                    sys.exit(1)
                except OSError:
                    server_logger.warning(
                        f"发现过时 PID 文件 (PID {stale_pid} 已不存在)，覆盖"
                    )

        # Port pre-check
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            sock.bind(("0.0.0.0", port))
        except OSError:
            server_logger.error(
                f"端口 {port} 已被占用，Server 可能已在运行"
            )
            sys.exit(1)
        finally:
            sock.close()

        pid_path.write_text(
            f"{os.getpid()}\n{datetime.now(timezone.utc).isoformat()}",
            encoding="utf-8",
        )
        server_logger.info(f"PID 文件已创建: {pid_path} (PID {os.getpid()})")
    else:
        # ── Multi-worker: append to manifest ──
        server_logger.info(
            f"多 Worker 模式 ({workers} workers)，跳过 PID 独占锁"
        )
        manifest = (
            f"{os.getpid()}\t{datetime.now(timezone.utc).isoformat()}\tworker\n"
        )
        with open(pid_path, "a", encoding="utf-8") as f:
            f.write(manifest)

    # Cleanup handlers (single-worker only: full cleanup on exit)
    def _cleanup_pid() -> None:
        try:
            if pid_path.exists():
                pid_path.unlink()
        except Exception:
            pass

    if workers <= 1:
        atexit.register(_cleanup_pid)

        def _signal_handler(signum, frame):
            _cleanup_pid()
            sys.exit(0)

        signal.signal(signal.SIGTERM, _signal_handler)
        signal.signal(signal.SIGINT, _signal_handler)


if __name__ == "__main__":
    import argparse

    _parser = argparse.ArgumentParser(description="RAG-Anything Server")
    _parser.add_argument(
        "--workers", "-w",
        type=int,
        default=int(os.getenv("SERVER_WORKERS", "1")),
        help="Number of worker processes (default: 1, from SERVER_WORKERS env)",
    )
    _args = _parser.parse_args()

    _server_port = int(os.getenv("PORT", "8001"))
    _acquire_server_lock(port=_server_port, workers=_args.workers)
    uvicorn.run(
        "server:app",
        host="0.0.0.0",
        port=_server_port,
        workers=_args.workers if _args.workers > 1 else None,
        reload=False,
    )
