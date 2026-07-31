"""
Admin Router — /api/settings, /api/monitor, /api/health,
/api/workflows, /api/autorepair/*, WebSocket endpoints.
Extracted from server.py.
"""
import json
import os
import uuid
from datetime import datetime
from pathlib import Path
from typing import Optional

from fastapi import (
    APIRouter,
    Depends,
    File,
    HTTPException,
    Request,
    Response,
    UploadFile,
    WebSocket,
    WebSocketDisconnect,
)
from pydantic import BaseModel

from lightrag.llm.openai import openai_complete_if_cache, openai_embed
from raganything.routers import shared  # mutable state accessed via shared. prefix
from raganything.workflow_executor import execute_workflow, RUNS_DIR, ExecutionContext
from raganything.dependencies import (
    get_current_user,
    require_permission,
)
from raganything.permissions import Permission
from raganything.services.auth import (
    decode_token,
    get_user_by_id,
    check_account_locked,
    has_permission as _auth_has_permission,
    is_token_revoked as _auth_is_token_revoked,
)
import raganything.services.runtime_settings as runtime_settings

router = APIRouter(tags=["admin"])


# ── 请求/响应模型 ──────────────────────────────────
class SettingsUpdate(BaseModel):
    parser: Optional[str] = None
    llm_model: Optional[str] = None
    chunk_size: Optional[int] = None
    chunking_strategy: Optional[str] = None
    entity_types: Optional[str] = None
    entity_extraction_min_degree: Optional[int] = None
    max_async: Optional[int] = None
    llm_timeout: Optional[int] = None
    enable_image: Optional[bool] = None
    enable_table: Optional[bool] = None
    enable_equation: Optional[bool] = None
    enable_video: Optional[bool] = None
    # RRF (Reciprocal Rank Fusion) 检索参数
    rrf_k: Optional[int] = None
    bm25_top_k: Optional[int] = None
    vector_top_k: Optional[int] = None
    graph_top_k: Optional[int] = None
    graph_depth: Optional[int] = None
    bm25_k1: Optional[float] = None
    bm25_b: Optional[float] = None
    bm25_tokenizer: Optional[str] = None
    rrf_channel_timeout: Optional[float] = None
    enabled_channels: Optional[str] = None


def _env_or_default(key: str, default: str) -> str:
    value = os.getenv(key)
    return value.strip() if value and value.strip() else default


def _serialize_settings() -> dict:
    return {
        "parser": os.getenv("PARSER", "docling"),
        "entity_types": os.getenv("ENTITY_TYPES", ""),
        "entity_extraction_min_degree": int(os.getenv("ENTITY_EXTRACTION_MIN_DEGREE", "0")),
        "llm_model": shared.LLM_MODEL,
        "vision_model": shared.VISION_MODEL,
        "embedding_model": shared.EMB_MODEL,
        "embedding_dim": shared.EMB_DIM,
        "chunk_size": os.getenv("CHUNK_SIZE", "800"),
        "chunking_strategy": shared.CHUNKING_STRATEGY,
        "chunking_strategies": shared.CHUNKING_STRATEGY_META,
        "max_async": os.getenv("MAX_ASYNC", "4"),
        "llm_timeout": int(os.getenv("LLM_TIMEOUT", "180")),
        "enable_image": os.getenv("ENABLE_IMAGE_PROCESSING", "true").lower() == "true",
        "enable_table": os.getenv("ENABLE_TABLE_PROCESSING", "true").lower() == "true",
        "enable_equation": os.getenv("ENABLE_EQUATION_PROCESSING", "true").lower() == "true",
        "enable_video": os.getenv("ENABLE_VIDEO_PROCESSING", "false").lower() == "true",
        "working_dir": shared.WORKING_DIR,
        "parser_output_dir": os.getenv("OUTPUT_DIR", "./output"),
        "supported_extensions": [
            ".pdf", ".jpg", ".jpeg", ".png", ".bmp", ".tiff", ".gif", ".webp",
            ".doc", ".docx", ".ppt", ".pptx", ".xls", ".xlsx", ".txt", ".md",
        ],
        "rrf": {
            "rrf_k": int(os.getenv("RRF_K", "60")),
            "bm25_top_k": int(os.getenv("BM25_TOP_K", "50")),
            "vector_top_k": int(os.getenv("VECTOR_TOP_K", "100")),
            "graph_top_k": int(os.getenv("GRAPH_TOP_K", "30")),
            "graph_depth": int(os.getenv("GRAPH_DEPTH", "2")),
            "bm25_k1": float(os.getenv("BM25_K1", "1.5")),
            "bm25_b": float(os.getenv("BM25_B", "0.75")),
            "bm25_tokenizer": _env_or_default("BM25_TOKENIZER", "jieba"),
            "rrf_channel_timeout": float(os.getenv("RRF_CHANNEL_TIMEOUT", "0.15")),
            "enabled_channels": os.getenv("RRF_ENABLED_CHANNELS", "bm25,vector,graph"),
        },
    }


class WorkflowRunRequest(BaseModel):
    query_text: str = ""


# ════════════════════════════════════════════════════════
# 工作流编排 API — PG-backed (Phase 3 migration)
# ════════════════════════════════════════════════════════

async def _wf_pg_pool():
    from raganything.services.pg_state_repo import get_pg_pool
    return get_pg_pool()


@router.get("/workflows")
async def list_workflows(
    _perm: None = Depends(require_permission(Permission.WORKFLOW_READ)),
    current_user: dict = Depends(get_current_user),
):
    """列出所有工作流 — PG-backed"""
    pool = await _wf_pg_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT id, name, created_at, updated_at "
            "FROM workflow_definitions ORDER BY updated_at DESC"
        )
    def _fmt(t):
        return t.isoformat() if hasattr(t, 'isoformat') else str(t)
    return {
        "workflows": [
            {"id": r["id"], "name": r["name"],
             "created_at": _fmt(r["created_at"]),
             "updated_at": _fmt(r["updated_at"])}
            for r in rows
        ]
    }


@router.get("/workflows/files")
async def list_workflow_files(file_type: str = "", _perm: None = Depends(require_permission(Permission.WORKFLOW_READ)), current_user: dict = Depends(get_current_user)):
    """列出 uploads/ 目录下的文件供工作流选择"""
    upload_dir = Path("./uploads")
    upload_dir.mkdir(exist_ok=True)
    files = []
    for f in sorted(upload_dir.iterdir(), key=lambda p: p.stat().st_mtime, reverse=True):
        if f.is_file():
            if file_type and f.suffix.lower() != file_type:
                continue
            files.append({
                "name": f.name, "size": f.stat().st_size, "suffix": f.suffix.lower(),
                "modified": datetime.fromtimestamp(f.stat().st_mtime).isoformat(),
            })
    return {"files": files}


@router.post("/workflows/upload")
async def upload_workflow(file: UploadFile = File(...), _perm: None = Depends(require_permission(Permission.WORKFLOW_WRITE)), current_user: dict = Depends(get_current_user)):
    """上传文件到 uploads/ 供工作流使用"""
    upload_dir = Path("./uploads")
    upload_dir.mkdir(exist_ok=True)
    content = await file.read()
    (upload_dir / file.filename).write_bytes(content)
    return {"status": "ok", "filename": file.filename, "size": len(content)}


@router.get("/workflows/models")
async def get_workflow_models(
    current_user: dict = Depends(get_current_user),
    type: str = "",
):
    """返回系统配置的可用模型列表（来自 .env 配置），支持 ?type=llm|embed 分类"""
    llm_model = os.getenv("LLM_MODEL", "")
    vision_model = os.getenv("VISION_MODEL", "")
    embed_model = os.getenv("EMBEDDING_MODEL", "")
    extra_llm = os.getenv("LLM_AVAILABLE_MODELS", "")
    extra_embed = os.getenv("EMBEDDING_AVAILABLE_MODELS", "")

    def _collect(*sources: str) -> list[dict]:
        seen = set()
        result = []
        for src in sources:
            for m in src.split(","):
                m = m.strip()
                if m and m not in seen:
                    seen.add(m)
                    result.append({"id": m, "name": m, "source": "env"})
        return result

    if type == "llm":
        models = _collect(llm_model, vision_model, extra_llm)
        if not models:
            models.append({"id": "qwen-plus", "name": "qwen-plus (默认)", "source": "fallback"})
    elif type == "embed":
        models = _collect(embed_model, extra_embed)
        if not models:
            models.append({"id": "text-embedding-v4", "name": "text-embedding-v4 (默认)", "source": "fallback"})
    else:
        # 兼容旧调用，不分类
        models = _collect(llm_model, vision_model, embed_model, extra_llm, extra_embed)
        if not models:
            models.append({"id": "qwen-plus", "name": "qwen-plus (默认)", "source": "fallback"})

    return {"models": models}


@router.get("/workflows/{workflow_id}")
async def get_workflow(
    workflow_id: str,
    _perm: None = Depends(require_permission(Permission.WORKFLOW_READ)),
    current_user: dict = Depends(get_current_user),
):
    """获取单个工作流 — PG-backed"""
    user_id = current_user.get("id", 0)

    pool = await _wf_pg_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT id, name, definition, created_at, updated_at "
            "FROM workflow_definitions WHERE id = $1",
            workflow_id,
        )
    if row:
        return {
            "id": row["id"],
            "name": row["name"],
            "created_at": row["created_at"].isoformat(),
            "updated_at": row["updated_at"].isoformat(),
            "nodes": row["definition"].get("nodes", []),
            "edges": row["definition"].get("edges", []),
        }
    raise HTTPException(404, "工作流不存在")


@router.post("/workflows")
async def create_workflow(
    request: Request,
    _perm: None = Depends(require_permission(Permission.WORKFLOW_WRITE)),
    current_user: dict = Depends(get_current_user),
):
    """创建新工作流 — PG-backed"""
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(400, "无效的请求体")

    wf_id = str(uuid.uuid4())
    user_id = current_user.get("id", 0)
    nodes = body.get("nodes", [])
    edges = body.get("edges", [])
    name = body.get("name", "未命名工作流")

    pool = await _wf_pg_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """INSERT INTO workflow_definitions (id, user_id, name, definition)
               VALUES ($1, $2, $3, $4::jsonb) RETURNING *""",
            wf_id, user_id, name, json.dumps({"nodes": nodes, "edges": edges}),
        )
    return {
        "id": row["id"], "name": row["name"],
        "created_at": row["created_at"].isoformat(),
        "updated_at": row["updated_at"].isoformat(),
        "nodes": row["definition"].get("nodes", []),
        "edges": row["definition"].get("edges", []),
    }


@router.put("/workflows/{workflow_id}")
async def update_workflow(
    workflow_id: str, request: Request,
    _perm: None = Depends(require_permission(Permission.WORKFLOW_WRITE)),
    current_user: dict = Depends(get_current_user),
):
    """更新工作流 — PG-backed"""
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(400, "无效的请求体")

    nodes = body.get("nodes")
    edges = body.get("edges")
    name = body.get("name")

    pool = await _wf_pg_pool()
    async with pool.acquire() as conn:
        existing = await conn.fetchrow(
            "SELECT id, name, definition FROM workflow_definitions WHERE id = $1",
            workflow_id,
        )
        if not existing:
            raise HTTPException(404, "工作流不存在")
        new_name = name if name is not None else existing["name"]
        new_def = dict(existing["definition"])
        if nodes is not None:
            new_def["nodes"] = nodes
        if edges is not None:
            new_def["edges"] = edges
        row = await conn.fetchrow(
            """UPDATE workflow_definitions
               SET name = $1, definition = $2::jsonb, updated_at = NOW()
               WHERE id = $3 RETURNING *""",
            new_name, json.dumps(new_def), workflow_id,
        )
    return {
        "id": row["id"], "name": row["name"],
        "created_at": row["created_at"].isoformat(),
        "updated_at": row["updated_at"].isoformat(),
        "nodes": row["definition"].get("nodes", []),
        "edges": row["definition"].get("edges", []),
    }


@router.delete("/workflows/{workflow_id}")
async def delete_workflow(
    workflow_id: str,
    _perm: None = Depends(require_permission(Permission.WORKFLOW_WRITE)),
    current_user: dict = Depends(get_current_user),
):
    """删除工作流 — PG-backed (CASCADE deletes runs)"""
    pool = await _wf_pg_pool()
    async with pool.acquire() as conn:
        result = await conn.execute(
            "DELETE FROM workflow_definitions WHERE id = $1", workflow_id,
        )
    deleted = result and "DELETE 0" not in result
    if not deleted:
        raise HTTPException(404, "工作流不存在")
    return {"status": "ok"}


# ── WebSocket 认证辅助 ─────────────────────────────

async def _authenticate_ws(ws: WebSocket, required_permission: str | None = None) -> dict | None:
    """验证 WebSocket 连接的 token（查询参数）。

    在 ws.accept() 之前调用。认证失败时自动关闭连接（code=4001）。

    Args:
        ws: WebSocket 连接
        required_permission: 若提供，额外检查用户是否具有该权限

    Returns:
        用户 dict（含 id, username, role），失败返回 None
    """
    token = ws.query_params.get("token")
    if not token:
        await ws.close(code=4001, reason="Missing authentication token")
        return None

    # 解码 Token
    try:
        payload = decode_token(token)
    except Exception:
        await ws.close(code=4001, reason="Invalid token format")
        return None

    if payload is None:
        await ws.close(code=4001, reason="Token invalid or expired")
        return None

    user_id = payload.get("user_id")
    if not user_id:
        await ws.close(code=4001, reason="Token missing user identity")
        return None

    # 检查 Token 是否已被撤销（PG-first dispatch）
    jti = payload.get("jti")
    if jti and await _auth_is_token_revoked(jti):
        await ws.close(code=4001, reason="Token has been revoked")
        return None

    # 检查用户状态
    user = await get_user_by_id(user_id)
    if not user:
        await ws.close(code=4001, reason="User not found")
        return None

    if not user.get("is_active"):
        await ws.close(code=4001, reason="Account disabled")
        return None

    lock_error = await check_account_locked(user_id)
    if lock_error:
        await ws.close(code=4001, reason="Account locked")
        return None

    # 可选权限检查
    if required_permission:
        if not await _auth_has_permission(user_id, required_permission):
            await ws.close(code=4001, reason=f"Insufficient permission: {required_permission}")
            return None

    return {"id": user_id, "username": user["username"]}


# ── WebSocket 端点 ─────────────────────────────────

@router.websocket("/ws/workflow-run/{run_id}")
async def websocket_workflow_run(ws: WebSocket, run_id: str):
    """WebSocket: 推送工作流执行状态（需要 token 查询参数 + workflow:read 权限）"""
    user = await _authenticate_ws(ws, required_permission=Permission.WORKFLOW_READ)
    if user is None:
        return  # 认证失败，连接已关闭

    await ws.accept()
    if run_id not in shared.active_ws_connections:
        shared.active_ws_connections[run_id] = []
    shared.active_ws_connections[run_id].append(ws)
    try:
        while True:
            await ws.receive_text()  # 保持连接，忽略客户端消息
    except WebSocketDisconnect:
        pass
    finally:
        try:
            shared.active_ws_connections[run_id].remove(ws)
        except (ValueError, KeyError):
            pass
        if run_id in shared.active_ws_connections and not shared.active_ws_connections[run_id]:
            del shared.active_ws_connections[run_id]


@router.post("/workflows/{workflow_id}/run")
async def run_workflow(workflow_id: str, body: WorkflowRunRequest = WorkflowRunRequest(), _perm: None = Depends(require_permission(Permission.WORKFLOW_WRITE)), current_user: dict = Depends(get_current_user)):
    """执行工作流 DAG，支持运行时 query_text 注入到 retriever 节点 — PG-backed"""
    pool = await _wf_pg_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT definition FROM workflow_definitions WHERE id = $1",
            workflow_id,
        )
    if not row:
        raise HTTPException(404, "工作流不存在")
    wf = row["definition"]
    nodes = wf.get("nodes", [])
    if not nodes:
        raise HTTPException(400, "工作流没有节点")

    # 运行时注入 query_text 到所有 retriever 节点
    if body.query_text.strip():
        for node in wf.get("nodes", []):
            if node.get("data", {}).get("nodeType") == "retriever":
                node["data"]["query_text"] = body.query_text.strip()

    # 构建执行上下文（注入真实 RAG 组件）
    default_kb = await shared.get_kb("default")
    exec_ctx = ExecutionContext(
        llm_model=shared.LLM_MODEL,
        llm_api_key=shared.API_KEY,
        llm_base_url=shared.BASE_URL,
        embed_model=shared.EMB_MODEL,
        embed_dim=shared.EMB_DIM,
        embed_api_key=shared.API_KEY,
        embed_base_url=shared.BASE_URL,
        kb_instance=default_kb,
        upload_dir=Path("./uploads"),
        openai_complete_func=openai_complete_if_cache,
        openai_embed_func=openai_embed,
        user_id=current_user.get("id", 0),
    )

    async def status_cb(node_id, status, data=None):
        # exec_ctx._run_id_cache is set by execute_workflow() when run starts
        if exec_ctx._run_id_cache:
            await shared.push_run_status(exec_ctx._run_id_cache, node_id, status, data)

    try:
        result = await execute_workflow(wf, ctx=exec_ctx, status_callback=status_cb)
    except ValueError as e:
        raise HTTPException(400, str(e))

    return result


@router.get("/workflows/{workflow_id}/runs")
async def list_workflow_runs(
    workflow_id: str,
    _perm: None = Depends(require_permission(Permission.WORKFLOW_READ)),
    current_user: dict = Depends(get_current_user),
):
    """列出工作流的所有运行记录 — PG-backed"""
    pool = await _wf_pg_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT run_id, status, started_at, completed_at, workflow_name "
            "FROM workflow_runs WHERE workflow_id = $1 "
            "ORDER BY started_at DESC LIMIT 100",
            workflow_id,
        )
    def _fmt(t):
        return t.isoformat() if hasattr(t, 'isoformat') else str(t) if t else None
    return {
        "runs": [
            {"run_id": r["run_id"], "status": r["status"],
             "started_at": _fmt(r["started_at"]),
             "completed_at": _fmt(r["completed_at"]),
             "workflow_name": r["workflow_name"]}
            for r in rows
        ]
    }


@router.get("/workflows/{workflow_id}/runs/{run_id}")
async def get_workflow_run(
    workflow_id: str, run_id: str,
    _perm: None = Depends(require_permission(Permission.WORKFLOW_READ)),
    current_user: dict = Depends(get_current_user),
):
    """获取单次运行详情 — PG-backed"""
    pool = await _wf_pg_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT * FROM workflow_runs WHERE run_id = $1", run_id,
        )
    if row:
        r = dict(row)
        def _fmt(t):
            return t.isoformat() if hasattr(t, 'isoformat') else str(t) if t else None
        r["started_at"] = _fmt(r["started_at"])
        r["completed_at"] = _fmt(r["completed_at"])
        return r
    raise HTTPException(404, "运行记录不存在")


@router.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    """WebSocket: 通用进度推送（需要 token 查询参数，任何有效用户均可连接）"""
    user = await _authenticate_ws(ws, required_permission=None)
    if user is None:
        return  # 认证失败，连接已关闭

    await ws.accept()
    shared.ws_clients.append(ws)
    try:
        while True:
            await ws.receive_text()  # keep alive
    except WebSocketDisconnect:
        pass
    finally:
        if ws in shared.ws_clients:
            shared.ws_clients.remove(ws)


# ── ⚙️ 系统设置 ─────────────────────────────────────
@router.get("/settings")
async def get_settings(response: Response, _perm: None = Depends(require_permission(Permission.SETTINGS_READ)), current_user: dict = Depends(get_current_user)):
    """Legacy read-only settings compatibility endpoint."""
    response.headers["Deprecation"] = "true"
    response.headers["Sunset"] = "personal-platform-settings-v1"
    return _serialize_settings()


@router.put("/settings")
async def update_settings(settings: SettingsUpdate,
                          current_user: dict = Depends(require_permission(Permission.SETTINGS_WRITE))):
    """Legacy writes are intentionally retired before the legacy read path."""
    raise HTTPException(410, {"code": "settings_write_deprecated", "message": "use /api/users/me/settings or /api/admin/platform"})


@router.post("/settings/reset")
async def reset_settings(current_user: dict = Depends(require_permission(Permission.SETTINGS_WRITE))):
    """Legacy resets are retired with legacy settings writes."""
    raise HTTPException(410, {"code": "settings_reset_deprecated", "message": "use /api/admin/platform"})


# ── 🔄 KB 缓存管理 ──────────────────────────────────
@router.post("/reload-kb/{kb_name}")
async def reload_kb(kb_name: str,
                    current_user: dict = Depends(require_permission(Permission.SETTINGS_WRITE))):
    """手动清除知识库内存缓存，下次查询从磁盘重新加载最新数据。

    适用场景:
    - 子进程写入磁盘后缓存未自动失效
    - 手动修改了存储文件
    - 排查查询返回旧数据的问题

    权限: settings:write
    """
    if kb_name in shared.kb_instances:
        await shared.kb_instances.retire(kb_name)
        await shared.add_event("kb_cache_reload", kb=kb_name, user_id=current_user.get("id", 0))
        return {"status": "ok", "message": f"知识库“{kb_name}”缓存已清除，下次查询将重新加载"}
    return {"status": "skipped", "message": f"知识库“{kb_name}”当前不在缓存中"}


# ── 📊 KB 缓存管理 ──────────────────────────────────

@router.get("/cache/stats")
async def cache_stats(
    _perm: None = Depends(require_permission(Permission.MONITOR_READ)),
    current_user: dict = Depends(get_current_user),
):
    """获取 KB 缓存统计信息。

    返回缓存命中率、已缓存 KB 列表、淘汰次数等。

    权限: monitor:read
    """
    return shared.kb_instances.get_stats()


@router.post("/cache/evict/{kb_name}")
async def cache_evict(
    kb_name: str,
    _perm: None = Depends(require_permission(Permission.SETTINGS_WRITE)),
    current_user: dict = Depends(get_current_user),
):
    """手动淘汰指定 KB 的内存缓存（持久化后移除）。

    固定 KB 和正在处理中的 KB 无法淘汰。

    权限: settings:write
    """
    if kb_name not in shared.kb_instances:
        return {"status": "skipped", "message": f"知识库“{kb_name}”当前不在缓存中"}

    if shared.kb_instances.is_pinned(kb_name):
        return {
            "status": "skipped",
            "message": f"知识库“{kb_name}”已固定，不可淘汰。请先取消固定。",
        }

    if shared.kb_instances.is_dirty(kb_name):
        return {
            "status": "skipped",
            "message": f"知识库“{kb_name}”正在处理中，无法淘汰。",
        }

    success = await shared.kb_instances.evict(kb_name)
    if success:
        await shared.add_event("kb_cache_evict", kb=kb_name, user_id=current_user.get("id", 0))
        return {"status": "ok", "message": f"知识库“{kb_name}”缓存已淘汰"}
    return {"status": "skipped", "message": f"知识库“{kb_name}”缓存淘汰失败"}


@router.post("/cache/pin/{kb_name}")
async def cache_pin(
    kb_name: str,
    _perm: None = Depends(require_permission(Permission.SETTINGS_WRITE)),
    current_user: dict = Depends(get_current_user),
):
    """固定 KB 到缓存中，永不自动淘汰。

    权限: settings:write
    """
    shared.kb_instances.pin(kb_name)
    await shared.add_event("kb_cache_pin", kb=kb_name, user_id=current_user.get("id", 0))
    return {"status": "ok", "message": f"知识库“{kb_name}”已固定到缓存"}


@router.post("/cache/unpin/{kb_name}")
async def cache_unpin(
    kb_name: str,
    _perm: None = Depends(require_permission(Permission.SETTINGS_WRITE)),
    current_user: dict = Depends(get_current_user),
):
    """取消固定 KB，允许自动淘汰。

    权限: settings:write
    """
    shared.kb_instances.unpin(kb_name)
    await shared.add_event("kb_cache_unpin", kb=kb_name, user_id=current_user.get("id", 0))
    return {"status": "ok", "message": f"知识库“{kb_name}”已取消固定"}


# ── 📈 监控面板 ─────────────────────────────────────
@router.get("/monitor/status")
async def monitor_status(_perm: None = Depends(require_permission(Permission.MONITOR_READ)), current_user: dict = Depends(get_current_user)):
    """获取当前处理状态（按用户隔离，管理员看全部）"""
    is_admin = current_user.get("is_admin", False)
    if is_admin:
        filtered_tasks = list(shared.processing_tasks.values())
    else:
        filtered_tasks = [t for t in shared.processing_tasks.values()
                         if t.get("user_id", 0) == current_user["id"]]
    filtered_events = await shared.get_monitor_events(
        limit=20,
        user_id=None if is_admin else current_user.get("id", 0),
        is_admin=is_admin,
    )
    return {
        "tasks": filtered_tasks,
        "events": filtered_events,
        "cache_size": len(shared.query_history),
    }


@router.get("/monitor/stats")
async def monitor_stats(_perm: None = Depends(require_permission(Permission.MONITOR_READ)), current_user: dict = Depends(get_current_user)):
    """LLM 调用统计（聚合数据，无用户隐私）"""
    cache_path = Path(shared.WORKING_DIR) / "kv_store_llm_response_cache.json"
    if not cache_path.exists():
        return {"total_calls": 0, "cache_entries": 0}
    with open(cache_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    extract_calls = sum(1 for v in data.values() if "extract" in str(v.get("cache_type", "")))
    return {
        "total_cache_entries": len(data),
        "extract_calls": extract_calls,
        "other_calls": len(data) - extract_calls,
    }


@router.get("/monitor/logs")
async def monitor_logs(limit: int = 50, _perm: None = Depends(require_permission(Permission.MONITOR_READ)), current_user: dict = Depends(get_current_user)):
    """获取最近事件日志（按用户隔离，管理员看全部）"""
    is_admin = current_user.get("is_admin", False)
    events = await shared.get_monitor_events(
        limit=limit,
        user_id=None if is_admin else current_user.get("id", 0),
        is_admin=is_admin,
    )
    return {"events": events}


@router.get("/health/vision-embedding")
async def vision_embedding_health(
    _perm: None = Depends(require_permission(Permission.SETTINGS_READ)),
):
    """Run a minimal, admin-only vision embedding authorization probe."""
    if os.getenv("VISION_SEARCH_ENABLED", "false").lower() != "true":
        return {
            "status": "disabled",
            "reason": "VISION_SEARCH_ENABLED is false",
        }

    from raganything.embedding import create_vision_embed_func

    adapter = create_vision_embed_func(working_dir=shared.WORKING_DIR)
    if adapter is None:
        return {
            "status": "disabled",
            "reason": "vision_embedding_not_configured",
        }

    result = await adapter.health_check()
    return {
        "status": "ok" if result.get("available") else "blocked",
        **result,
    }


@router.get("/health")
async def health():
    """健康检查（公开接口，用于 Docker/监控探测）"""
    components = {"server": "ok", "active_kb": shared.active_kb}
    system_data_epoch = ""

    # 检查 KB 存储状态
    try:
        meta = await shared.load_kb_meta()
        components["kb_count"] = len(meta)
    except Exception as e:
        components["kb_meta"] = f"error: {e}"

    # 检查认证数据库 (PG)
    try:
        from raganything.services.pg_state_repo import get_pg_pool
        pool = get_pg_pool()
        async with pool.acquire() as conn:
            await conn.fetchval("SELECT 1 FROM users LIMIT 1")
            monitor_table_ready = await conn.fetchval(
                "SELECT to_regclass('public.monitor_events') IS NOT NULL"
            )
            system_data_epoch = await conn.fetchval(
                "SELECT value FROM settings WHERE key = 'system_data_epoch'"
            )
        components["auth_db"] = "ok"
        components["monitor_logs"] = "ok" if monitor_table_ready else "error: monitor_events table missing"
    except Exception as e:
        components["auth_db"] = f"error: {e}"
        components["monitor_logs"] = f"error: {e}"

    # 检查磁盘空间
    try:
        import shutil as _shutil
        usage = _shutil.disk_usage(".")
        free_gb = usage.free / (1024 ** 3)
        components["disk_free_gb"] = round(free_gb, 1)
        if free_gb < 1:
            components["disk_warning"] = "low"
    except Exception:
        pass

    # 整体状态
    has_errors = any(v for v in components.values() if isinstance(v, str) and "error" in str(v))
    return {
        "status": "degraded" if has_errors else "ok",
        "version": "1.3.1",
        "system_data_epoch": system_data_epoch or "",
        "components": components,
    }


# ════════════════════════════════════════════════════════
