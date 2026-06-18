"""
RAG-Anything FastAPI 服务器
启动: python server.py
访问: http://localhost:8000
"""
import io
import json
import logging
import os
import sys
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

from dotenv import load_dotenv
load_dotenv(dotenv_path=".env", override=False)


from fastapi import FastAPI, HTTPException, Request
from fastapi.security import HTTPBearer
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
from starlette.middleware.base import BaseHTTPMiddleware
import uvicorn

from raganything.query import ConversationManager

# Hint appended to LLM prompt when context has no text chunks (only entities/relations)
_DEGRADED_HINT = (
    "\n\n⚠️ 注意：本次检索未能获取到关联的文档文本内容，"
    "以下回答仅基于实体名称和关系路径，可能不够详细。"
    "如果信息不足，请如实说明。"
)
from raganything.services.agent_manager import (
    init_agent_manager,
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

app = FastAPI(title="RAG-Anything API", version="1.3.1")

# ── Rate Limiting ──────────────────────────────────
limiter = Limiter(key_func=get_remote_address, default_limits=["120/minute"])
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

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

# ── 输入校验 + Prompt Injection 防护 ────────────────
import re as _re_valid
PROMPT_INJECTION_PATTERNS = [
    r"(ignore|forget|disregard)\s+(all\s+)?(previous|prior|above|earlier)\s+(instructions?|prompts?|commands?)",
    r"(you\s+are|act\s+as|pretend\s+to\s+be|roleplay\s+as)\s+(now|from\s+now\s+on)",
    r"(system\s*(prompt|message|instruction))",
    r"<\s*(script|iframe|object|embed|style)\b",
    r"(javascript|onerror|onload|onclick)\s*:",
    r"(\.\./|\.\.\\)",  # 路径遍历
]
PROMPT_INJECTION_REGEX = [_re_valid.compile(p, _re_valid.IGNORECASE) for p in PROMPT_INJECTION_PATTERNS]

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
            elif cl > MAX_BODY_SIZE:
                return JSONResponse(
                    {"detail": f"请求体超过最大限制 {os.getenv('MAX_BODY_SIZE_MB','10')}MB"},
                    status_code=413,
                )
        return await call_next(request)

app.add_middleware(RequestSizeMiddleware)

def validate_query_input(query: str) -> str:
    """校验查询输入，检测 Prompt Injection 攻击"""
    if not query or not query.strip():
        raise HTTPException(400, "查询内容不能为空")
    if len(query) > 5000:
        raise HTTPException(400, "查询内容超过最大长度限制")
    for pattern in PROMPT_INJECTION_REGEX:
        if pattern.search(query):
            server_logger.warning(f"Prompt Injection 拦截: pattern={pattern.pattern[:40]} query={query[:80]}")
            raise HTTPException(400, "请求包含不安全内容")
    return query.strip()

# ── 日志敏感信息脱敏 ────────────────────────────────
class SensitiveLogFilter(logging.Filter):
    """自动脱敏日志中的敏感字段"""
    _patterns = [
        (_re_valid.compile(r'(api[_-]?key[=:"\s]*)([a-zA-Z0-9_\-]{8,})', _re_valid.IGNORECASE), r'\1***REDACTED***'),
        (_re_valid.compile(r'(password[=:"\s]*)([^,&\s"]+)', _re_valid.IGNORECASE), r'\1***REDACTED***'),
        (_re_valid.compile(r'(token[=:"\s]*)([a-zA-Z0-9_\-\.]{20,})', _re_valid.IGNORECASE), r'\1***REDACTED***'),
        (_re_valid.compile(r'(Bearer\s+)([a-zA-Z0-9_\-\.]{20,})'), r'\1***REDACTED***'),
        (_re_valid.compile(r'([a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,})'), r'***EMAIL***'),
    ]
    def filter(self, record):
        if hasattr(record, 'msg') and isinstance(record.msg, str):
            for pattern, replacement in self._patterns:
                record.msg = pattern.sub(replacement, record.msg)
        return True

# 应用到所有 handler
for _h in logging.getLogger().handlers + logging.getLogger("rag_server").handlers:
    _h.addFilter(SensitiveLogFilter())
logging.getLogger("rag_server").addFilter(SensitiveLogFilter())
logging.getLogger("lightrag").addFilter(SensitiveLogFilter())

# ── 多知识库管理 ──────────────────────────────────
# 共享状态从 services 层导入，保持模块级别名向后兼容
from raganything.services.kb_service import (
    kb_instances, get_kb, create_rag, load_kb_meta, save_kb_meta, kb_dir,
    infer_entity_type, _build_citation_block, _get_kb_doc_list,
    _fix_stuck_doc_status, _process_uploaded_file,
    KB_META_FILE,
)
from raganything.services.ws_service import (
    ws_clients, processing_events, ws_broadcast, emit_progress, add_event,
)
from raganything.services.state_service import (
    processing_tasks, query_history, load_query_history, save_query_history,
    QUERY_HISTORY_FILE,
)
from raganything.routers.shared import (
    get_current_user, get_admin_user, verify_kb_access,
    validate_query_input, extract_image_paths,
    _is_thinking_msg, _translate_thinking_msg,
    QUERY_SYSTEM_PROMPT, THINKING_PATTERNS, server_logger,
)
# Keep reference for ConversationManager init in startup
from raganything.routers import shared as _shared_state

# ── Router 注册 ───────────────────────────────────────
from raganything.routers.auth import router as auth_router
from raganything.routers.knowledge import router as knowledge_router
from raganything.routers.agent import router as agent_router
from raganything.routers.query import router as query_router
from raganything.routers.admin import router as admin_router
from raganything.routers.manufacturing import router as manufacturing_router

app.include_router(auth_router, prefix="/api")
app.include_router(knowledge_router, prefix="/api")
app.include_router(agent_router, prefix="/api")
app.include_router(query_router, prefix="/api")
app.include_router(admin_router, prefix="/api")
app.include_router(manufacturing_router, prefix="/api")

@app.on_event("startup")
async def startup():
    # 初始化认证数据库
    await init_db()
    # 初始化 ConversationManager（多轮对话上下文记忆）
    # 初始化 ConversationManager（多轮对话上下文记忆）
    conversations_file = os.getenv("CONVERSATIONS_FILE", "./conversations.json")
    max_rounds = int(os.getenv("CONVERSATION_MAX_ROUNDS", "3"))
    max_tokens = int(os.getenv("CONVERSATION_MAX_TOKENS", "2000"))
    max_per_user = int(os.getenv("CONVERSATION_MAX_PER_USER", "50"))
    _shared_state.conversation_manager = ConversationManager(
        storage_path=conversations_file,
        max_rounds=max_rounds,
        max_tokens=max_tokens,
        max_per_user=max_per_user,
    )
    await _shared_state.conversation_manager._load()
    server_logger.info(f"ConversationManager: {_shared_state.conversation_manager.get_stats()}")
    # 加载所有知识库元数据
    meta = load_kb_meta()
    # 迁移旧知识库：无 owner_id 的 KB 全部归管理员（user_id=1）
    changed = False
    for kb_name, kb_info in meta.items():
        if "owner_id" not in kb_info:
            kb_info["owner_id"] = 1
            kb_info["owner_username"] = "admin"
            changed = True
    if changed:
        save_kb_meta(meta)
        print(f"[KB-MIGRATE] 已将 {sum(1 for v in meta.values() if v.get('owner_id') == 1)} 个知识库分配给管理员", flush=True)
    # 加载查询历史
    load_query_history()
    # 初始化智能体管理器
    mgr = init_agent_manager(".")
    # 迁移旧智能体和对话：无 owner_id 的归管理员
    mgr.migrate_agents()
    # 确保默认智能体存在（迁移旧查询历史）
    default_agent, _ = mgr.ensure_default_agent(
        llm_model=LLM_MODEL,
        query_history=query_history,
    )
    # 启动时扫描所有 KB，修复卡在 handling 的文档（上次运行中断遗留）
    stuck_count = 0
    for kb_name in meta.keys():
        try:
            sp = Path(kb_dir(kb_name)) / "kv_store_doc_status.json"
            if sp.exists():
                d = json.loads(sp.read_text(encoding="utf-8"))
                changed = False
                for doc_id, info in d.items():
                    if info.get("status") == "handling":
                        info["status"] = "failed"
                        info["error_msg"] = "服务重启，上一次处理未完成"
                        stuck_count += 1
                        changed = True
                if changed:
                    sp.write_text(json.dumps(d, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception:
            pass
    if stuck_count:
        server_logger.info(f"[STARTUP-FIX] 修复了 {stuck_count} 个卡在 handling 的文档")
    # 预加载默认知识库
    kb = await get_kb("default")
    server_logger.info(f"RAG-Anything 服务器已启动，智能体: {len(mgr.agents)}个, 知识库: {list(meta.keys())}")

@app.on_event("shutdown")
async def shutdown():
    # Flush pending audit logs before exit
    try:
        from raganything.services.audit import get_audit_logger
        audit = get_audit_logger()
        audit.shutdown()
    except Exception:
        pass
    for name, kb in kb_instances.items():
        try: await kb.finalize_storages()
        except: pass

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8001)
