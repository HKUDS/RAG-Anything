"""
Admin Router — /api/settings, /api/monitor, /api/health,
/api/workflows, /api/manufacturing/*, WebSocket endpoints.
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
)

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
    enable_image: Optional[bool] = None
    enable_table: Optional[bool] = None
    enable_equation: Optional[bool] = None
    enable_video: Optional[bool] = None


class WorkflowRunRequest(BaseModel):
    query_text: str = ""


# ════════════════════════════════════════════════════════
# 工作流编排 API
# ════════════════════════════════════════════════════════

@router.get("/workflows")
async def list_workflows(current_user: dict = Depends(get_current_user)):
    """列出所有工作流"""
    workflows = []
    for f in sorted(shared.WORKFLOW_DIR.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True):
        try:
            wf = json.loads(f.read_text(encoding="utf-8"))
            workflows.append({"id": wf.get("id"), "name": wf.get("name"), "created_at": wf.get("created_at"), "updated_at": wf.get("updated_at")})
        except Exception:
            pass
    return {"workflows": workflows}


@router.get("/workflows/files")
async def list_workflow_files(file_type: str = "", current_user: dict = Depends(get_current_user)):
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
async def upload_workflow(file: UploadFile = File(...), current_user: dict = Depends(get_current_user)):
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
async def get_workflow(workflow_id: str, current_user: dict = Depends(get_current_user)):
    """获取单个工作流"""
    fpath = shared.WORKFLOW_DIR / f"{workflow_id}.json"
    if not fpath.exists():
        raise HTTPException(404, "工作流不存在")
    return json.loads(fpath.read_text(encoding="utf-8"))


@router.post("/workflows")
async def create_workflow(request: Request, current_user: dict = Depends(get_current_user)):
    """创建新工作流"""
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(400, "无效的请求体")
    wf_id = str(uuid.uuid4())
    now = datetime.now().isoformat()
    wf = {
        "id": wf_id,
        "name": body.get("name", "未命名工作流"),
        "created_at": now,
        "updated_at": now,
        "nodes": body.get("nodes", []),
        "edges": body.get("edges", []),
    }
    (shared.WORKFLOW_DIR / f"{wf_id}.json").write_text(json.dumps(wf, ensure_ascii=False, indent=2), encoding="utf-8")
    return wf


@router.put("/workflows/{workflow_id}")
async def update_workflow(workflow_id: str, request: Request, current_user: dict = Depends(get_current_user)):
    """更新工作流"""
    fpath = shared.WORKFLOW_DIR / f"{workflow_id}.json"
    if not fpath.exists():
        raise HTTPException(404, "工作流不存在")
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(400, "无效的请求体")
    existing = json.loads(fpath.read_text(encoding="utf-8"))
    existing["name"] = body.get("name", existing["name"])
    existing["nodes"] = body.get("nodes", existing["nodes"])
    existing["edges"] = body.get("edges", existing["edges"])
    existing["updated_at"] = datetime.now().isoformat()
    fpath.write_text(json.dumps(existing, ensure_ascii=False, indent=2), encoding="utf-8")
    return existing


@router.delete("/workflows/{workflow_id}")
async def delete_workflow(workflow_id: str, current_user: dict = Depends(get_current_user)):
    """删除工作流"""
    fpath = shared.WORKFLOW_DIR / f"{workflow_id}.json"
    if not fpath.exists():
        raise HTTPException(404, "工作流不存在")
    fpath.unlink()
    return {"status": "ok"}


# ── WebSocket 连接管理 ─────────────────────────────

@router.websocket("/ws/workflow-run/{run_id}")
async def websocket_workflow_run(ws: WebSocket, run_id: str):
    """WebSocket: 推送工作流执行状态"""
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
        shared.active_ws_connections[run_id].remove(ws)
        if not shared.active_ws_connections[run_id]:
            del shared.active_ws_connections[run_id]


@router.post("/workflows/{workflow_id}/run")
async def run_workflow(workflow_id: str, body: WorkflowRunRequest = WorkflowRunRequest(), current_user: dict = Depends(get_current_user)):
    """执行工作流 DAG，支持运行时 query_text 注入到 retriever 节点"""
    fpath = shared.WORKFLOW_DIR / f"{workflow_id}.json"
    if not fpath.exists():
        raise HTTPException(404, "工作流不存在")
    wf = json.loads(fpath.read_text(encoding="utf-8"))
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
async def list_workflow_runs(workflow_id: str, current_user: dict = Depends(get_current_user)):
    """列出工作流的所有运行记录"""
    runs = []
    for f in sorted(RUNS_DIR.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True):
        try:
            r = json.loads(f.read_text(encoding="utf-8"))
            if r.get("workflow_id") == workflow_id:
                runs.append({
                    "run_id": r["run_id"], "status": r["status"],
                    "started_at": r.get("started_at"), "completed_at": r.get("completed_at"),
                    "workflow_name": r.get("workflow_name"),
                })
        except Exception:
            pass
    return {"runs": runs}


@router.get("/workflows/{workflow_id}/runs/{run_id}")
async def get_workflow_run(workflow_id: str, run_id: str, current_user: dict = Depends(get_current_user)):
    """获取单次运行详情"""
    fpath = RUNS_DIR / f"{run_id}.json"
    if not fpath.exists():
        raise HTTPException(404, "运行记录不存在")
    return json.loads(fpath.read_text(encoding="utf-8"))


@router.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
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
async def get_settings(current_user: dict = Depends(get_current_user)):
    """获取当前配置"""
    return {
        "parser": os.getenv("PARSER", "docling"),
        "entity_types": os.getenv("ENTITY_TYPES", ""),
        "entity_extraction_min_degree": int(os.getenv("ENTITY_EXTRACTION_MIN_DEGREE", "0")),
        "llm_model": shared.LLM_MODEL,
        "vision_model": shared.VISION_MODEL,
        "embedding_model": shared.EMB_MODEL,
        "embedding_dim": shared.EMB_DIM,
        "chunk_size": os.getenv("CHUNK_SIZE", "1200"),
        "chunking_strategy": shared.CHUNKING_STRATEGY,
        "chunking_strategies": shared.CHUNKING_STRATEGY_META,
        "max_async": os.getenv("MAX_ASYNC", "4"),
        "llm_max_async": os.getenv("LLM_MODEL_MAX_ASYNC", "4"),
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
            "bm25_tokenizer": os.getenv("BM25_TOKENIZER", "jieba"),
            "rrf_channel_timeout": float(os.getenv("RRF_CHANNEL_TIMEOUT", "0.15")),
            "enabled_channels": os.getenv("RRF_ENABLED_CHANNELS", "bm25,vector,graph"),
        },
    }


@router.put("/settings")
async def update_settings(settings: SettingsUpdate, current_user: dict = Depends(get_current_user)):
    """更新配置(runtime)"""
    changes = {}
    if settings.parser is not None:
        os.environ["PARSER"] = settings.parser
        changes["parser"] = settings.parser
    if settings.chunk_size is not None:
        os.environ["CHUNK_SIZE"] = str(settings.chunk_size)
        changes["chunk_size"] = settings.chunk_size
    if settings.chunking_strategy is not None:
        os.environ["CHUNKING_STRATEGY"] = settings.chunking_strategy
        shared.CHUNKING_STRATEGY = settings.chunking_strategy
        changes["chunking_strategy"] = settings.chunking_strategy
        # 分块策略变更需要重建所有知识库实例
        for name in list(shared.kb_instances.keys()):
            del shared.kb_instances[name]
    if settings.max_async is not None:
        os.environ["MAX_ASYNC"] = str(settings.max_async)
        changes["max_async"] = settings.max_async
    if settings.enable_image is not None:
        os.environ["ENABLE_IMAGE_PROCESSING"] = str(settings.enable_image).lower()
        changes["enable_image"] = settings.enable_image
    if settings.enable_table is not None:
        os.environ["ENABLE_TABLE_PROCESSING"] = str(settings.enable_table).lower()
        changes["enable_table"] = settings.enable_table
    if settings.enable_equation is not None:
        os.environ["ENABLE_EQUATION_PROCESSING"] = str(settings.enable_equation).lower()
        changes["enable_equation"] = settings.enable_equation
    if settings.enable_video is not None:
        os.environ["ENABLE_VIDEO_PROCESSING"] = str(settings.enable_video).lower()
        changes["enable_video"] = settings.enable_video
    if settings.entity_types is not None:
        os.environ["ENTITY_TYPES"] = settings.entity_types
        changes["entity_types"] = settings.entity_types
    if settings.entity_extraction_min_degree is not None:
        os.environ["ENTITY_EXTRACTION_MIN_DEGREE"] = str(settings.entity_extraction_min_degree)
        changes["entity_extraction_min_degree"] = settings.entity_extraction_min_degree
    # 部分配置需要重建 RAG 实例才能生效
    need_rebuild = (
        settings.parser is not None
        or settings.entity_types is not None
        or settings.enable_image is not None
        or settings.enable_table is not None
        or settings.enable_equation is not None
        or settings.enable_video is not None
    )
    if need_rebuild:
        # Clear all cached KB instances so they pick up the new config on next access
        for name in list(shared.kb_instances.keys()):
            del shared.kb_instances[name]
    return {"status": "ok", "changes": changes, "note": "配置已更新，下次访问知识库时生效"}


# ── 📈 监控面板 ─────────────────────────────────────
@router.get("/monitor/status")
async def monitor_status(current_user: dict = Depends(get_current_user)):
    """获取当前处理状态（按用户隔离，管理员看全部）"""
    is_admin = current_user.get("is_admin", False)
    if is_admin:
        filtered_tasks = list(shared.processing_tasks.values())
        filtered_events = shared.processing_events[-20:]
    else:
        filtered_tasks = [t for t in shared.processing_tasks.values()
                         if t.get("user_id", 0) == current_user["id"]]
        filtered_events = [e for e in shared.processing_events[-20:]
                          if e.get("user_id", 0) in (0, current_user["id"])]
    return {
        "tasks": filtered_tasks,
        "events": filtered_events,
        "cache_size": len(shared.query_history),
    }


@router.get("/monitor/stats")
async def monitor_stats(current_user: dict = Depends(get_current_user)):
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
async def monitor_logs(limit: int = 50, current_user: dict = Depends(get_current_user)):
    """获取最近事件日志（按用户隔离，管理员看全部）"""
    is_admin = current_user.get("is_admin", False)
    if is_admin:
        return {"events": shared.processing_events[-limit:]}
    filtered = [e for e in reversed(shared.processing_events)
                if e.get("user_id", 0) in (0, current_user["id"])]
    return {"events": filtered[-limit:]}


@router.get("/health")
async def health():
    """健康检查（公开接口，用于 Docker/监控探测）"""
    components = {"server": "ok", "active_kb": shared.active_kb}

    # 检查 KB 存储状态
    try:
        meta = shared.load_kb_meta()
        components["kb_count"] = len(meta)
    except Exception as e:
        components["kb_meta"] = f"error: {e}"

    # 检查认证数据库
    try:
        import sqlite3
        conn = sqlite3.connect("auth.db")
        conn.execute("SELECT 1 FROM users LIMIT 1")
        conn.close()
        components["auth_db"] = "ok"
    except Exception as e:
        components["auth_db"] = f"error: {e}"

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
        "components": components,
    }


# ════════════════════════════════════════════════════════

