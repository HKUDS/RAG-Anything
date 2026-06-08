"""
RAG-Anything FastAPI 服务器
启动: python server.py
访问: http://localhost:8000
"""
import asyncio
import io
import json
import logging
import os
import queue
import sys
import time
import uuid
import base64
import tempfile
from datetime import datetime
from functools import partial
from pathlib import Path
from typing import Optional

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

from dotenv import load_dotenv
load_dotenv(dotenv_path=".env", override=False)

import pypdfium2 as pdfium
from PIL import Image

from fastapi import FastAPI, UploadFile, File, HTTPException, Query as QueryParam, WebSocket, WebSocketDisconnect, Request, BackgroundTasks, Depends
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from fastapi.responses import StreamingResponse, JSONResponse, FileResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
import uvicorn
import shutil
import httpx

from lightrag.llm.openai import openai_complete_if_cache, openai_embed
from lightrag.utils import EmbeddingFunc, logger as lightrag_logger
from raganything import RAGAnything, RAGAnythingConfig
from raganything.chunking import (
    recursive_chunking,
    sentence_chunking,
    structure_chunking,
    make_semantic_chunking,
    make_agentic_chunking,
    build_chunking_func,
    STRATEGY_META as CHUNKING_STRATEGY_META,
)
from agent_manager import (
    AgentConfig,
    AgentManager,
    ConversationThread,
    init_agent_manager,
    get_agent_manager,
)
from auth import (
    init_db,
    get_user_by_username,
    get_user_by_id,
    create_user,
    verify_password,
    create_token,
    decode_token,
    list_users,
    update_user,
    delete_user,
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
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

# ── 多知识库管理 ──────────────────────────────────
kb_instances: dict[str, RAGAnything] = {}
active_kb: str = "default"
processing_tasks: dict[str, dict] = {}
query_history: list[dict] = []
processing_events: list[dict] = []
ws_clients: list[WebSocket] = []

KB_META_FILE = Path("./rag_storage_kb_meta.json")
QUERY_HISTORY_FILE = Path("./query_history.json")
server_logger = logging.getLogger("rag_server")

# ── 认证模型 ──────────────────────────────────────
class AuthRegisterRequest(BaseModel):
    username: str
    email: str
    password: str

class AuthLoginRequest(BaseModel):
    username: str
    password: str

class AdminUpdateUserRequest(BaseModel):
    username: Optional[str] = None
    email: Optional[str] = None
    password: Optional[str] = None
    is_admin: Optional[bool] = None
    is_active: Optional[bool] = None

# ── 认证依赖 ──────────────────────────────────────
async def get_current_user(credentials: HTTPAuthorizationCredentials = Depends(security)):
    """JWT Token 验证，返回当前用户"""
    try:
        payload = decode_token(credentials.credentials)
    except Exception:
        raise HTTPException(401, "Token 格式无效")
    if payload is None:
        raise HTTPException(401, "Token 无效或已过期")
    user = await get_user_by_id(payload["user_id"])
    if not user:
        raise HTTPException(401, "用户不存在")
    if not user.get("is_active"):
        raise HTTPException(401, "账号已被禁用")
    return user

async def get_admin_user(current_user: dict = Depends(get_current_user)):
    """管理员权限检查"""
    if not current_user.get("is_admin"):
        raise HTTPException(403, "需要管理员权限")
    return current_user

async def verify_kb_access(kb: str = QueryParam("default"), current_user: dict = Depends(get_current_user)):
    """验证当前用户是否有权访问指定知识库，返回 kb 名称"""
    meta = load_kb_meta()
    if kb not in meta:
        raise HTTPException(404, f"知识库 '{kb}' 不存在")
    kb_info = meta[kb]
    owner_id = kb_info.get("owner_id")
    # 无 owner 的旧数据仅管理员可访问
    if owner_id is None:
        if not current_user.get("is_admin"):
            raise HTTPException(403, "无权访问该知识库（旧数据）")
    elif owner_id != current_user["id"] and not current_user.get("is_admin"):
        raise HTTPException(403, "无权访问该知识库")
    return kb

# ── 图片路径提取 ──────────────────────────────────
import re as _re

def extract_image_paths(text: str) -> list[str]:
    """从检索上下文中提取图片路径"""
    if not text:
        return []
    pattern = _re.compile(
        r"Image Path:\s*([^\r\n]*?\.(?:jpg|jpeg|png|gif|bmp|webp|tiff|tif))",
        _re.IGNORECASE,
    )
    seen = set()
    paths = []
    for m in pattern.finditer(text):
        p = m.group(1).strip()
        if p not in seen:
            seen.add(p)
            paths.append(p)
    return paths

# ── 查询历史持久化 ──────────────────────────────────
def load_query_history():
    """从 JSON 文件加载查询历史"""
    global query_history
    try:
        if QUERY_HISTORY_FILE.exists():
            data = json.loads(QUERY_HISTORY_FILE.read_text(encoding="utf-8"))
            query_history = data if isinstance(data, list) else []
            server_logger.info(f"Loaded {len(query_history)} query history records")
    except Exception as e:
        server_logger.warning(f"Failed to load query history: {e}")
        query_history = []

def save_query_history():
    """将查询历史保存到 JSON 文件"""
    try:
        QUERY_HISTORY_FILE.write_text(
            json.dumps(query_history, ensure_ascii=False, indent=2),
            encoding="utf-8"
        )
    except Exception as e:
        server_logger.warning(f"Failed to save query history: {e}")

def load_kb_meta() -> dict:
    if KB_META_FILE.exists():
        with open(KB_META_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {"default": {"name": "默认知识库", "created": datetime.now().isoformat()}}

def save_kb_meta(meta: dict):
    with open(KB_META_FILE, "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)

def kb_dir(name: str) -> str:
    return f"./rag_storage" if name == "default" else f"./rag_storage_{name}"

async def get_kb(name: str = None) -> RAGAnything:
    """获取或创建知识库实例"""
    name = name or active_kb
    if name not in kb_instances:
        from lightrag.kg.shared_storage import set_default_workspace
        target = kb_dir(name)
        set_default_workspace(target)
        instance = create_rag(working_dir=target)
        await instance._ensure_lightrag_initialized()
        # 降低向量检索余弦阈值，让更多语义相关但非精确匹配的 chunk 被检索到
        if instance.lightrag and hasattr(instance.lightrag, 'chunks_vdb'):
            instance.lightrag.chunks_vdb.cosine_better_than_threshold = 0.0
        kb_instances[name] = instance
        print(f"[KB] 初始化知识库实例: {name} workspace={target}", flush=True)
    return kb_instances[name]

async def ws_broadcast(data: dict):
    """向所有 WebSocket 客户端广播消息"""
    dead = []
    for ws in ws_clients:
        try: await ws.send_json(data)
        except Exception: dead.append(ws)
    for ws in dead: ws_clients.remove(ws)

_event_lock = asyncio.Lock()

async def add_event(event: str, **kw):
    e = {"time": datetime.now().isoformat(), "event": event, **kw}
    async with _event_lock:
        processing_events.append(e)
        if len(processing_events) > 200:
            processing_events[:] = processing_events[-200:]

async def emit_progress(task_id: str, progress: int, msg: str = ""):
    if task_id in processing_tasks:
        processing_tasks[task_id]["progress"] = progress
        processing_tasks[task_id]["message"] = msg
    await ws_broadcast({"type": "progress", "task_id": task_id, "progress": progress, "message": msg})


def create_rag(parser: str = None, working_dir: str = None, chunking_strategy: str = None) -> RAGAnything:
    if parser is None:
        parser = os.getenv("PARSER", "mineru")
    if chunking_strategy is None:
        chunking_strategy = CHUNKING_STRATEGY
    wd = working_dir or WORKING_DIR
    def llm_func(prompt, system_prompt=None, history_messages=[], **kw):
        # 确保 max_tokens 足够大，防止回答被截断
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

    embedding_func = EmbeddingFunc(
        embedding_dim=EMB_DIM, max_token_size=8192,
        func=partial(openai_embed.func, model=EMB_MODEL, api_key=API_KEY, base_url=BASE_URL),
    )

    # ── 分块策略映射 ──────────────────────────────
    chunk_token_size = int(os.getenv("CHUNK_SIZE", "800"))

    def _get_embedding_func_for_chunk(texts: list[str]) -> list[list[float]]:
        """Embedding 辅助函数，用于语义分块"""
        return embedding_func.func(texts, model=EMB_MODEL)

    async def _get_llm_func_for_chunk(prompt: str, system_prompt: str = "",
                                       history_messages=None, **kw):
        """LLM 辅助函数，用于智能分块"""
        return await llm_func(prompt, system_prompt=system_prompt,
                              history_messages=history_messages or [], **kw)

    chunking_strategy_map = {
        "fixed_size": None,  # 使用 LightRAG 默认
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
    }
    if chosen_chunking_func is not None:
        lightrag_kwargs["chunking_func"] = chosen_chunking_func

    config = RAGAnythingConfig(
        working_dir=wd,
        parser=parser,
        enable_image_processing=os.getenv("ENABLE_IMAGE_PROCESSING", "false").lower() == "true",
        enable_table_processing=os.getenv("ENABLE_TABLE_PROCESSING", "false").lower() == "true",
        enable_equation_processing=os.getenv("ENABLE_EQUATION_PROCESSING", "false").lower() == "true",
    )

    return RAGAnything(config=config, llm_model_func=llm_func,
                       vision_model_func=vision_func, embedding_func=embedding_func,
                       lightrag_kwargs=lightrag_kwargs)


# ── 请求/响应模型 ──────────────────────────────────
class QueryRequest(BaseModel):
    query: str
    mode: str = "hybrid"
    vlm_enhanced: bool = False
    only_need_context: bool = False

class PasteContentRequest(BaseModel):
    content: str
    title: str = ""

class SettingsUpdate(BaseModel):
    parser: Optional[str] = None
    llm_model: Optional[str] = None
    chunk_size: Optional[int] = None
    chunking_strategy: Optional[str] = None

class BatchDeleteRequest(BaseModel):
    doc_ids: list[str]

    max_async: Optional[int] = None
    enable_image: Optional[bool] = None
    enable_table: Optional[bool] = None
    enable_equation: Optional[bool] = None


# ── 生命周期 ───────────────────────────────────────
@app.on_event("startup")
async def startup():
    # 初始化认证数据库
    await init_db()
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
    # 确保默认智能体存在（迁移旧查询历史）
    default_agent, _ = mgr.ensure_default_agent(
        llm_model=LLM_MODEL,
        query_history=query_history,
    )
    # 预加载默认知识库
    kb = await get_kb("default")
    print(f"✅ RAG-Anything 服务器已启动，智能体: {len(mgr.agents)}个, 知识库: {list(meta.keys())}")


@app.on_event("shutdown")
async def shutdown():
    for name, kb in kb_instances.items():
        try: await kb.finalize_storages()
        except: pass


# ── 📤 文档上传 ─────────────────────────────────────
def auto_parser(filename: str) -> str:
    """根据文件扩展名自动选择最佳解析器"""
    ext = filename.lower().rsplit(".", 1)[-1] if "." in filename else ""
    # PDF: 先用 Docling，扫描件再考虑 MinerU（MinerU API 不稳定）
    if ext in ("pdf",):
        return "docling"
    # Office: Docling 原生支持更好
    if ext in ("docx", "pptx", "xlsx", "doc", "ppt", "xls"):
        return "docling"
    # 图片: MinerU OCR
    if ext in ("png", "jpg", "jpeg", "bmp", "tiff", "tif", "gif", "webp"):
        return "mineru"
    # 文本: PaddleOCR 或直接处理
    if ext in ("txt", "md"):
        return "docling"
    # 默认用 MinerU
    return os.getenv("PARSER", "mineru")

async def _vlm_ocr_page(image_base64: str, page_num: int) -> str:
    """用千问 VL 模型 OCR 单页"""
    try:
        async with httpx.AsyncClient(timeout=120) as client:
            resp = await client.post(
                f"{BASE_URL}/chat/completions",
                headers={"Authorization": f"Bearer {API_KEY}"},
                json={
                    "model": VISION_MODEL,
                    "messages": [{
                        "role": "user",
                        "content": [
                            {"type": "text", "text": "请提取这张图片中的所有文字内容，直接输出文字，不要添加任何解释。如果是中文文档，保持中文输出。"},
                            {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{image_base64}"}},
                        ]
                    }],
                    "max_tokens": 4096,
                }
            )
            if resp.status_code == 200:
                data = resp.json()
                return data.get("choices", [{}])[0].get("message", {}).get("content", "[OCR: 空响应]")
            return f"[OCR错误: HTTP {resp.status_code}]"
    except Exception as e:
        return f"[OCR异常: {e}]"

async def _vlm_ocr_document(file_path: str, max_pages: int = 30) -> str:
    """用 VLM 对 PDF 或图片做 OCR，返回提取的文字"""
    ext = file_path.lower().rsplit(".", 1)[-1] if "." in file_path else ""

    if ext in ("pdf",):
        pages_text = []
        pdf = pdfium.PdfDocument(file_path)
        total = min(len(pdf), max_pages)
        for i in range(total):
            page = pdf[i]
            bitmap = page.render(scale=1.5)
            pil_img = bitmap.to_pil()
            buf = io.BytesIO()
            pil_img.save(buf, format="PNG")
            b64 = base64.b64encode(buf.getvalue()).decode()
            text = await _vlm_ocr_page(b64, i + 1)
            pages_text.append(f"--- 第{i+1}页 ---\n{text}")
        pdf.close()
        return "\n\n".join(pages_text)

    elif ext in ("png", "jpg", "jpeg", "bmp", "tiff", "tif", "gif", "webp"):
        img = Image.open(file_path)
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        b64 = base64.b64encode(buf.getvalue()).decode()
        return await _vlm_ocr_page(b64, 1)

    return ""

# 纯文本扩展名（绕过解析器，直接读内容入库）
PLAIN_TEXT_EXTS = {"txt", "md", "csv", "json", "xml", "yaml", "yml",
                   "py", "js", "ts", "java", "c", "cpp", "h", "html", "css", "log"}

# 处理锁：防止并发处理导致 LightRAG 共享 pipeline 交叉污染
_process_lock = asyncio.Lock()

async def _process_uploaded_file(task_id: str, file_path: str, filename: str, kb_name: str = "default", chunking_strategy: str = ""):
    """后台处理上传文件 — 通过独立子进程隔离 LightRAG 实例"""
    processing_tasks[task_id] = {
        "id": task_id, "file": filename, "status": "processing",
        "started_at": datetime.now().isoformat(), "progress": 0,
        "kb": kb_name,
    }
    await add_event("upload_start", file=filename, task_id=task_id)
    actual_strategy = chunking_strategy or CHUNKING_STRATEGY

    try:
        await emit_progress(task_id, 5, f"子进程处理: {filename}")
        print(f"[UPLOAD] 任务={task_id} 文件={filename} KB={kb_name} 策略={actual_strategy}", flush=True)

        worker_script = Path(__file__).parent / "process_worker.py"
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
            cwd=str(Path(__file__).parent),
        )

        # 读取子进程输出
        worker_output_lines: list[str] = []

        async def _read_stream(stream):
            while True:
                line = await stream.readline()
                if not line:
                    break
                text = line.decode("utf-8", errors="replace").strip()
                if text:
                    worker_output_lines.append(text)
                    print(f"[WORKER:{task_id}] {text}", flush=True)

        stdout_task = asyncio.ensure_future(_read_stream(proc.stdout))
        stderr_task = asyncio.ensure_future(_read_stream(proc.stderr))
        try:
            timeout_sec = int(os.getenv("PROCESS_TIMEOUT", "3600"))  # 默认60分钟
            await asyncio.wait_for(proc.wait(), timeout=timeout_sec)
        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()
            raise RuntimeError(f"子进程处理超时（{timeout_sec // 60}分钟），文档过大或图片过多，可设置环境变量 PROCESS_TIMEOUT 调整")
        await stdout_task
        await stderr_task

        # Check worker output for merge/extraction errors even when
        # the return code is 0 (LightRAG may log ERROR without exiting)
        worker_has_errors = any(
            "ERROR:" in line and ("Merging stage failed" in line or "chunks=0" in line)
            for line in worker_output_lines
        )

        if proc.returncode != 0:
            # Collect error context from worker output
            error_lines = [l for l in worker_output_lines if "ERROR" in l]
            error_detail = "; ".join(error_lines[-2:]) if error_lines else f"exit code {proc.returncode}"
            raise RuntimeError(f"子进程处理失败: {error_detail}")

        if worker_has_errors:
            # Worker exited 0 but merging/extraction failed
            error_lines = [l for l in worker_output_lines if "ERROR:" in l and "Merging" in l]
            error_detail = error_lines[0] if error_lines else "Merging stage failed"
            raise RuntimeError(f"子进程实体提取失败 (chunks=0): {error_detail}")

        # 子进程写入新数据后，清除缓存实例，下次查询时重新加载
        if kb_name in kb_instances:
            try:
                await kb_instances[kb_name].finalize_storages()
            except Exception:
                pass
            del kb_instances[kb_name]
            print(f"[KB] 清除缓存实例: {kb_name}（子进程写入新数据）", flush=True)

        await emit_progress(task_id, 100, "处理完成")
        processing_tasks[task_id]["status"] = "completed"
        processing_tasks[task_id]["chunking_strategy"] = actual_strategy
        await add_event("upload_complete", file=filename, task_id=task_id, kb=kb_name)
        await ws_broadcast({"type": "upload_done", "task_id": task_id, "filename": filename, "kb": kb_name})

    except Exception as e:
        processing_tasks[task_id]["status"] = "failed"
        processing_tasks[task_id]["error"] = str(e)
        await add_event("upload_error", file=filename, task_id=task_id, error=str(e))

# ════════════════════════════════════════════════════════
# 图片文件服务
# ════════════════════════════════════════════════════════

@app.get("/api/files/image")
async def serve_image(path: str = QueryParam(...)):
    """服务图片文件 — 仅允许项目目录内的图片"""
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


# ════════════════════════════════════════════════════════
# 认证路由
# ════════════════════════════════════════════════════════

@app.post("/api/auth/register")
async def auth_register(req: AuthRegisterRequest):
    """用户注册"""
    try:
        user = await create_user(req.username, req.email, req.password)
        return {"status": "ok", "user": user}
    except ValueError as e:
        raise HTTPException(400, str(e))


@app.post("/api/auth/login")
async def auth_login(req: AuthLoginRequest):
    """用户登录，返回 JWT Token"""
    user = await get_user_by_username(req.username)
    if not user:
        raise HTTPException(401, "用户名或密码错误")
    if not user.get("is_active"):
        raise HTTPException(403, "账号已被禁用")
    if not verify_password(req.password, user["password_hash"]):
        raise HTTPException(401, "用户名或密码错误")
    token = create_token(user["id"], user["username"], bool(user["is_admin"]))
    return {
        "status": "ok",
        "token": token,
        "user": {k: v for k, v in user.items() if k != "password_hash"},
    }


@app.get("/api/auth/me")
async def auth_me(current_user: dict = Depends(get_current_user)):
    """获取当前登录用户信息"""
    return {"status": "ok", "user": current_user}


@app.post("/api/auth/logout")
async def auth_logout(current_user: dict = Depends(get_current_user)):
    """登出（客户端清除 token 即可，服务端预留黑名单扩展点）"""
    return {"status": "ok", "message": "已登出"}


# ════════════════════════════════════════════════════════
# 管理员路由
# ════════════════════════════════════════════════════════

@app.get("/api/admin/users")
async def admin_list_users(admin: dict = Depends(get_admin_user)):
    """列出所有用户"""
    users = await list_users()
    return {"status": "ok", "users": users}


@app.put("/api/admin/users/{user_id}")
async def admin_update_user(user_id: int, req: AdminUpdateUserRequest, admin: dict = Depends(get_admin_user)):
    """修改用户信息"""
    if user_id == admin["id"] and req.is_admin is False:
        raise HTTPException(400, "不能取消自己的管理员权限")
    data = req.model_dump(exclude_none=True)
    try:
        user = await update_user(user_id, data)
        if not user:
            raise HTTPException(404, "用户不存在")
        return {"status": "ok", "user": user}
    except ValueError as e:
        raise HTTPException(400, str(e))


@app.delete("/api/admin/users/{user_id}")
async def admin_delete_user(user_id: int, admin: dict = Depends(get_admin_user)):
    """删除用户"""
    if user_id == admin["id"]:
        raise HTTPException(400, "不能删除自己")
    ok = await delete_user(user_id)
    if not ok:
        raise HTTPException(404, "用户不存在")
    return {"status": "deleted", "user_id": user_id}


# ════════════════════════════════════════════════════════
# 业务路由（需认证）
# ════════════════════════════════════════════════════════

@app.post("/api/upload")
async def upload_file(file: UploadFile = File(...), background_tasks: BackgroundTasks = None,
                       kb: str = Depends(verify_kb_access), chunking_strategy: str = ""):
    """上传单个文件 - 立即返回，后台异步处理"""
    task_id = str(uuid.uuid4())[:8]
    upload_dir = Path("./uploads")
    upload_dir.mkdir(exist_ok=True)
    file_path = upload_dir / file.filename
    content = await file.read()
    file_path.write_bytes(content)

    print(f"[UPLOAD-API] 收到上传请求: file={file.filename} kb={kb} strategy={chunking_strategy}", flush=True)

    # 后台异步处理
    if background_tasks is None:
        raise HTTPException(500, "服务器内部错误：BackgroundTasks 未注入")
    background_tasks.add_task(_process_uploaded_file, task_id, str(file_path.absolute()),
                               file.filename, kb, chunking_strategy)
    strategy_name = CHUNKING_STRATEGY_META.get(chunking_strategy or CHUNKING_STRATEGY, {}).get('name', '默认')
    return {"task_id": task_id, "filename": file.filename, "status": "queued", "kb": kb,
            "chunking_strategy": chunking_strategy or CHUNKING_STRATEGY,
            "message": f"文档已接收，使用{strategy_name}分块，后台处理中。请到知识库页面查看进度。"}


@app.post("/api/upload/batch")
async def upload_files(files: list[UploadFile] = File(...), background_tasks: BackgroundTasks = None,
                       kb: str = Depends(verify_kb_access), chunking_strategy: str = ""):
    """批量上传文件 - 接收多个文件，逐个后台处理"""
    if not files:
        raise HTTPException(400, "请至少选择一个文件")

    upload_dir = Path("./uploads")
    upload_dir.mkdir(exist_ok=True)

    tasks = []
    for file in files:
        task_id = str(uuid.uuid4())[:8]
        file_path = upload_dir / file.filename
        content = await file.read()
        file_path.write_bytes(content)

        if background_tasks is None:
            raise HTTPException(500, "服务器内部错误：BackgroundTasks 未注入")
        background_tasks.add_task(_process_uploaded_file, task_id, str(file_path.absolute()),
                                   file.filename, kb, chunking_strategy)
        tasks.append({"task_id": task_id, "filename": file.filename, "status": "queued"})
        print(f"[UPLOAD-BATCH] 任务={task_id} 文件={file.filename} kb={kb}", flush=True)

    strategy_name = CHUNKING_STRATEGY_META.get(chunking_strategy or CHUNKING_STRATEGY, {}).get('name', '默认')
    return {"status": "queued", "tasks": tasks, "total": len(tasks), "kb": kb,
            "chunking_strategy": chunking_strategy or CHUNKING_STRATEGY,
            "message": f"已接收 {len(tasks)} 个文件，使用{strategy_name}分块，后台处理中"}


@app.post("/api/upload/folder")
async def upload_folder(folder_path: str = QueryParam(...), kb: str = Depends(verify_kb_access),
                         chunking_strategy: str = ""):
    """批量处理文件夹"""
    if not os.path.isdir(folder_path):
        raise HTTPException(400, "文件夹不存在")
    task_id = str(uuid.uuid4())[:8]
    instance = await get_kb(kb)
    processing_tasks[task_id] = {
        "id": task_id, "file": folder_path, "status": "processing",
        "started_at": datetime.now().isoformat(), "kb": kb,
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


@app.post("/api/upload/content")
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


# ── 📊 知识库管理 ───────────────────────────────────
@app.get("/api/knowledge/documents")
async def list_documents(kb: str = Depends(verify_kb_access)):
    """列出所有文档及其状态（含处理中的任务）"""
    try:
        status_path = Path(kb_dir(kb)) / "kv_store_doc_status.json"
        data = {}
        if status_path.exists():
            with open(status_path, "r", encoding="utf-8") as f:
                data = json.load(f)
        docs = []
        seen_files = set()
        for doc_id, info in data.items():
            docs.append({
                "id": doc_id[:16],
                "full_id": doc_id,
                "file": info.get("file_path", "?"),
                "status": info.get("status", "?"),
                "chunks": info.get("chunks_count", 0),
                "length": info.get("content_length", 0),
                "created": info.get("created_at", ""),
                "updated": info.get("updated_at", ""),
            })
            seen_files.add(info.get("file_path", ""))

        # 合并处理中的任务（还未写入 doc_status），仅限当前 KB
        for tid, task in processing_tasks.items():
            if task.get("kb", "") != kb:
                continue
            fn = task.get("file", "")
            if fn and fn not in seen_files:
                docs.append({
                    "id": tid,
                    "full_id": tid,
                    "file": fn,
                    "status": task.get("status", "processing"),
                    "chunks": 0,
                    "length": 0,
                    "created": task.get("started_at", ""),
                    "updated": task.get("started_at", ""),
                })
        return {"documents": sorted(docs, key=lambda d: d["updated"], reverse=True), "total": len(docs)}
    except Exception as e:
        raise HTTPException(500, str(e))


@app.get("/api/knowledge/stats")
async def knowledge_stats(kb: str = Depends(verify_kb_access)):
    """知识库总体统计"""
    stats = {"documents": 0, "entities": 0, "relations": 0, "chunks": 0}
    base = Path(kb_dir(kb))

    # 实体总数（聚合 count）
    ep = base / "kv_store_full_entities.json"
    if ep.exists():
        with open(ep, "r", encoding="utf-8") as fh:
            for v in json.load(fh).values():
                stats["entities"] += v.get("count", len(v.get("entity_names", [])))

    # 关系总数
    rp = base / "kv_store_full_relations.json"
    if rp.exists():
        with open(rp, "r", encoding="utf-8") as fh:
            for v in json.load(fh).values():
                stats["relations"] += v.get("count", len(v.get("relation_pairs", [])))

    # chunk 总数
    cp = base / "vdb_chunks.json"
    if cp.exists():
        with open(cp, "r", encoding="utf-8") as fh:
            stats["chunks"] = len(json.load(fh))

    dp = base / "kv_store_doc_status.json"
    if dp.exists():
        with open(dp, "r", encoding="utf-8") as fh:
            stats["documents"] = len(json.load(fh))
    return stats


@app.get("/api/knowledge/entities")
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

def infer_entity_type(name: str) -> str:
    """从实体名称推断类型"""
    n = str(name).lower()
    if any(w in n for w in ['大学', '学院', '公司', '医院', '研究所', '实验室', 'institute', 'university', 'hospital']):
        return 'organization'
    if any(w in n for w in ['模型', '算法', '方法', '网络', '框架', 'model', 'algorithm', 'network', 'method', 'mobilenet', 'resnet', 'efficientnet', 'cnn', 'rnn', 'transformer']):
        return 'method'
    if n.replace('.','').replace('%','').replace('-','').isdigit() or any(c in n for c in ['%', 'ms', 'mb', 'db']):
        return 'metric'
    if any(w in n for w in ['.png', '.jpg', '.jpeg', '.gif', 'image', '图像', '图片', '图']):
        return 'image'
    if any(w in n for w in ['函数', '公式', 'function', 'equation', 'loss', 'sigmoid', 'relu', 'softmax']):
        return 'equation'
    if any(w in n for w in ['层', '卷积', 'layer', 'conv', 'batch', 'norm', 'dropout', 'pool']):
        return 'component'
    if any(w in n for w in ['接口', '接口', 'api', '页面', '系统', '界面', 'interface', 'page', 'system', 'button', 'icon', 'form']):
        return 'ui'
    if any(w in n for w in ['数据', '精度', '准确率', '召回', 'f1', 'accuracy', 'precision', 'recall']):
        return 'metric'
    return 'concept'

@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    await ws.accept()
    ws_clients.append(ws)
    try:
        while True:
            await ws.receive_text()  # keep alive
    except WebSocketDisconnect:
        pass
    finally:
        if ws in ws_clients:
            ws_clients.remove(ws)


@app.get("/api/knowledge/graph")
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
                for name in v.get("entity_names", [])[:40]:
                    if is_valid_node(name) and name not in node_ids:
                        node_ids.add(name)
                        nodes.append({"id": name, "label": name[:25]})

    # 从 relations 建边
    if rp.exists():
        with open(rp, "r", encoding="utf-8") as f:
            for k, v in json.load(f).items():
                for src, tgt in v.get("relation_pairs", [])[:100]:
                    if not is_valid_node(src) or not is_valid_node(tgt):
                        continue
                    if src not in node_ids:
                        node_ids.add(src)
                        nodes.append({"id": src, "label": src[:25]})
                    if tgt not in node_ids:
                        node_ids.add(tgt)
                        nodes.append({"id": tgt, "label": tgt[:25]})
                    edges.append({"source": src, "target": tgt, "label": ""})

    return {"nodes": nodes[:120], "edges": edges[:80]}


@app.delete("/api/knowledge/documents/{doc_id}")
async def delete_document(doc_id: str, kb: str = Depends(verify_kb_access)):
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
            await add_event("doc_delete", file=fname, doc_id=doc_id, kb=kb, source="processing_tasks")
            return {"status": "deleted", "doc_id": doc_id, "file": fname, "message": "已从处理队列中移除"}
        # 也尝试按 file_path 匹配（前端可能传文件名相关的 ID）
        for tid, task in list(processing_tasks.items()):
            if task.get("kb", "") == kb and task.get("file", "") == doc_id:
                del processing_tasks[tid]
                await add_event("doc_delete", file=doc_id, doc_id=tid, kb=kb, source="processing_tasks")
                return {"status": "deleted", "doc_id": tid, "file": doc_id, "message": "已从处理队列中移除"}
        raise HTTPException(404, f"文档 {doc_id} 不存在（知识库: {kb}）")

    file_name = doc_status[full_id].get("file_path", "未知")

    # 使用 LightRAG 的正式删除方法，彻底清理所有关联数据
    result = await instance.lightrag.adelete_by_doc_id(full_id, delete_llm_cache=True)

    await add_event("doc_delete", file=file_name, doc_id=full_id, kb=kb)

    if result.status == "success":
        return {"status": "deleted", "doc_id": full_id, "file": file_name, "message": result.message}
    elif result.status == "not_found":
        raise HTTPException(404, f"文档 {file_name} 数据未找到")
    else:
        raise HTTPException(500, result.message)


@app.post("/api/knowledge/documents/batch-delete")
async def batch_delete_documents(req: BatchDeleteRequest, kb: str = Depends(verify_kb_access)):
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
                await add_event("doc_delete", file=task.get("file", "?"), doc_id=doc_id, kb=kb, source="processing_tasks")
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
                await add_event("doc_delete", file=file_name, doc_id=full_id, kb=kb)
                # Also clean up matching processing_tasks entry
                for tid, task in list(processing_tasks.items()):
                    if task.get("kb", "") == kb and task.get("file", "") == file_name:
                        del processing_tasks[tid]
            else:
                errors.append({"doc_id": doc_id, "error": result.message})
        except Exception as e:
            errors.append({"doc_id": doc_id, "error": str(e)})

    # Write doc_status back once
    with open(status_path, "w", encoding="utf-8") as f:
        json.dump(doc_status, f, ensure_ascii=False, indent=2)

    return {"deleted": deleted, "not_found": not_found, "errors": errors,
            "total_deleted": len(deleted), "total_failed": len(errors)}


@app.post("/api/upload/url")
async def upload_from_url(url: str = QueryParam(...), current_user: dict = Depends(get_current_user)):
    """从 URL 下载文档并入库"""
    if not url.startswith("http"):
        raise HTTPException(400, "无效 URL")
    task_id = str(uuid.uuid4())[:8]
    await add_event("url_download_start", url=url, task_id=task_id)
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
        await add_event("url_download_complete", file=fname, task_id=task_id, size=len(content))

        instance = await get_kb()
        await instance.process_document_complete(str(fp.absolute()), output_dir="./output")
        await add_event("url_process_complete", file=fname, task_id=task_id)
        return {"status": "completed", "filename": fname, "size": len(content)}
    except HTTPException:
        raise
    except Exception as e:
        await add_event("url_error", url=url, error=str(e))
        raise HTTPException(500, str(e))


# ── 🤖 智能体管理 ─────────────────────────────────────

class AgentCreateRequest(BaseModel):
    name: str = "新智能体"
    icon: str = "🤖"
    description: str = ""
    kb_name: str = "default"
    llm_model: str = "qwen-plus"
    temperature: float = 0.0
    query_mode: str = "hybrid"
    system_prompt: str = ""
    use_default_prompt: bool = True
    welcome_message: str = ""
    template_id: str = ""


class AgentUpdateRequest(BaseModel):
    name: Optional[str] = None
    icon: Optional[str] = None
    description: Optional[str] = None
    kb_name: Optional[str] = None
    llm_model: Optional[str] = None
    temperature: Optional[float] = None
    max_response_tokens: Optional[int] = None
    query_mode: Optional[str] = None
    retrieval_top_k: Optional[int] = None
    system_prompt: Optional[str] = None
    use_default_prompt: Optional[bool] = None
    welcome_message: Optional[str] = None


@app.get("/api/agents")
async def list_agents(current_user: dict = Depends(get_current_user)):
    """列出所有智能体"""
    mgr = get_agent_manager()
    agents = mgr.list_agents()
    return {
        "agents": [a.model_dump() for a in agents],
        "total": len(agents),
    }


@app.get("/api/agents/templates")
async def get_agent_templates(current_user: dict = Depends(get_current_user)):
    """获取智能体模板"""
    try:
        templates_file = Path("agent_templates.json")
        if templates_file.exists():
            data = json.loads(templates_file.read_text(encoding="utf-8"))
            return {"templates": data.get("templates", [])}
    except Exception:
        pass
    return {"templates": []}


@app.post("/api/agents")
async def create_agent(req: AgentCreateRequest, current_user: dict = Depends(get_current_user)):
    """创建新智能体"""
    # 验证 KB 访问权限
    await verify_kb_access(kb=req.kb_name, current_user=current_user)
    mgr = get_agent_manager()
    config = AgentConfig(
        name=req.name,
        icon=req.icon,
        description=req.description,
        welcome_message=req.welcome_message or f"你好！我是{req.name}，有什么可以帮你的？",
        kb_name=req.kb_name,
        llm_model=req.llm_model,
        temperature=req.temperature,
        query_mode=req.query_mode,
        system_prompt=req.system_prompt,
        use_default_prompt=req.use_default_prompt,
        template_id=req.template_id,
    )
    config = mgr.create_agent(config)
    return {"status": "ok", "agent": config.model_dump()}


@app.put("/api/agents/{agent_id}")
async def update_agent(agent_id: str, req: AgentUpdateRequest, current_user: dict = Depends(get_current_user)):
    """更新智能体配置"""
    mgr = get_agent_manager()
    updates = {k: v for k, v in req.model_dump().items() if v is not None}
    agent = mgr.update_agent(agent_id, updates)
    if not agent:
        raise HTTPException(404, "智能体不存在")
    return {"status": "ok", "agent": agent.model_dump()}


@app.delete("/api/agents/{agent_id}")
async def delete_agent(agent_id: str, current_user: dict = Depends(get_current_user)):
    """删除智能体"""
    mgr = get_agent_manager()
    if not mgr.delete_agent(agent_id):
        raise HTTPException(404, "智能体不存在")
    return {"status": "ok"}


# ── 💬 对话线程管理 ─────────────────────────────────────

@app.get("/api/agents/{agent_id}/conversations")
async def list_conversations(agent_id: str, current_user: dict = Depends(get_current_user)):
    """列出智能体的所有对话线程"""
    mgr = get_agent_manager()
    if not mgr.get_agent(agent_id):
        raise HTTPException(404, "智能体不存在")
    threads = mgr.list_conversations(agent_id)
    return {
        "threads": [t.model_dump() for t in threads],
        "total": len(threads),
    }


@app.post("/api/agents/{agent_id}/conversations")
async def create_conversation(agent_id: str, title: str = "新对话", current_user: dict = Depends(get_current_user)):
    """创建新对话线程"""
    mgr = get_agent_manager()
    if not mgr.get_agent(agent_id):
        raise HTTPException(404, "智能体不存在")
    thread = mgr.create_conversation(agent_id, title)
    return {"status": "ok", "thread": thread.model_dump()}


@app.put("/api/agents/{agent_id}/conversations/{thread_id}")
async def update_conversation(agent_id: str, thread_id: str, title: str = None, current_user: dict = Depends(get_current_user)):
    """更新对话线程（重命名）"""
    mgr = get_agent_manager()
    thread = mgr.update_conversation(agent_id, thread_id, {"title": title})
    if not thread:
        raise HTTPException(404, "对话线程不存在")
    return {"status": "ok", "thread": thread.model_dump()}


@app.delete("/api/agents/{agent_id}/conversations/{thread_id}")
async def delete_conversation(agent_id: str, thread_id: str, current_user: dict = Depends(get_current_user)):
    """删除对话线程"""
    mgr = get_agent_manager()
    if not mgr.delete_conversation(agent_id, thread_id):
        raise HTTPException(404, "对话线程不存在")
    return {"status": "ok"}


# ── 🔍 智能查询（智能体增强）─────────────────────────────

class AgentQueryRequest(BaseModel):
    query: str
    thread_id: str = ""  # 关联的对话线程 ID
    mode: str = ""  # 空则使用智能体默认模式
    vlm_enhanced: bool = False


# 🔍 智能体流式查询（SSE）
@app.post("/api/agents/{agent_id}/query/stream")
async def agent_query_stream(agent_id: str, req: AgentQueryRequest, current_user: dict = Depends(get_current_user)):
    """智能体流式查询：使用智能体配置执行查询"""
    global query_history
    mgr = get_agent_manager()
    agent = mgr.get_agent(agent_id)
    if not agent:
        raise HTTPException(404, "智能体不存在")

    # 验证 KB 访问权限
    await verify_kb_access(kb=agent.kb_name, current_user=current_user)

    instance = await get_kb(agent.kb_name)
    query_mode = req.mode or agent.query_mode

    # 构建 system_prompt
    system_prompt = agent.system_prompt
    if agent.use_default_prompt:
        system_prompt = (system_prompt + "\n\n" + QUERY_SYSTEM_PROMPT).strip()

    # 确保对话线程存在
    thread_id = req.thread_id
    if not thread_id:
        thread = mgr.create_conversation(agent_id, title="新对话")
        thread_id = thread.id

    async def event_stream():
        global query_history
        log_queue: queue.Queue = queue.Queue()
        handler = LogCaptureHandler(log_queue)
        lightrag_logger.addHandler(handler)
        query_id = str(uuid.uuid4())[:8]
        full_answer = ""

        try:
            yield f"data: {json.dumps({'type': 'agent_info', 'agent': agent.name, 'icon': agent.icon, 'thread_id': thread_id}, ensure_ascii=False)}\n\n"
            yield f"data: {json.dumps({'type': 'thinking', 'content': f'🔍 开始查询: {req.query[:80]}...'}, ensure_ascii=False)}\n\n"

            start_time = time.time()

            # Step 1: 获取检索上下文
            ctx_task = asyncio.ensure_future(
                instance.aquery(req.query, mode=query_mode, vlm_enhanced=False,
                                only_need_context=True, enable_rerank=False,
                                chunk_top_k=40, top_k=60,
                                max_entity_tokens=3000, max_relation_tokens=2000,
                                max_total_tokens=16000)
            )
            while not ctx_task.done():
                while True:
                    try:
                        msg = log_queue.get_nowait()
                        if _is_thinking_msg(msg):
                            dm = _translate_thinking_msg(msg)
                            if dm:
                                yield f"data: {json.dumps({'type': 'thinking', 'content': dm}, ensure_ascii=False)}\n\n"
                    except queue.Empty:
                        break
                await asyncio.sleep(0.06)

            ctx = ctx_task.result()
            # 从检索上下文提取图片，没有则扫全库
            agent_images = extract_image_paths(ctx)
            if not agent_images:
                try:
                    import json as _json
                    _chunk_file = Path(kb_dir(agent.kb_name)) / 'kv_store_text_chunks.json'
                    if _chunk_file.exists():
                        _all = _json.loads(_chunk_file.read_text(encoding='utf-8'))
                        _all_text = '\n'.join(v.get('content', '') for v in _all.values() if isinstance(v, dict))
                        agent_images = extract_image_paths(_all_text)
                except Exception:
                    pass
            agent_images = agent_images[:5]
            yield f"data: {json.dumps({'type': 'thinking', 'content': f'📋 检索到 {len(ctx)} 字符上下文' + (f'，{len(agent_images)} 张图片' if agent_images else '')}, ensure_ascii=False)}\n\n"
            yield f"data: {json.dumps({'type': 'thinking', 'content': '💬 正在生成回答...'}, ensure_ascii=False)}\n\n"

            # Step 2: 构造 prompt 并使用智能体配置的模型
            sp = (agent.system_prompt or "") + ("\n你是知识库助手。只使用检索内容回答。" if agent.use_default_prompt else "")
            final_prompt = f"以下是知识库检索内容。必须基于这些内容回答，不得使用你自己的知识。\n\n## 检索内容\n{ctx}\n\n## 问题\n{req.query}\n\n## 要求\n从检索内容提取事实和数据。有数字必须引用。没有就说未找到。不编造。"

            # 使用智能体配置的模型，而非 .env 全局模型
            use_model = agent.llm_model or LLM_MODEL
            llm_response = await openai_complete_if_cache(
                use_model, final_prompt, system_prompt=sp,
                api_key=API_KEY, base_url=BASE_URL,
                max_tokens=int(os.getenv("MAX_TOKENS", "8192")),
                temperature=agent.temperature, stream=True,
            )

            if llm_response is None:
                yield f"data: {json.dumps({'type': 'error', 'content': '模型返回空'}, ensure_ascii=False)}\n\n"
                return
            if isinstance(llm_response, str):
                full_answer = llm_response
                yield f"data: {json.dumps({'type': 'token', 'content': llm_response}, ensure_ascii=False)}\n\n"
            else:
                async for token in llm_response:
                    full_answer += token
                    yield f"data: {json.dumps({'type': 'token', 'content': token}, ensure_ascii=False)}\n\n"

            elapsed = round(time.time() - start_time, 2)

            # 保存到对话线程
            mgr.add_message(agent_id, thread_id, {
                "role": "user",
                "content": req.query,
                "time": datetime.now().isoformat(),
            })
            mgr.add_message(agent_id, thread_id, {
                "role": "assistant",
                "content": full_answer,
                "elapsed": elapsed,
                "mode": query_mode,
                "time": datetime.now().isoformat(),
            })

            # 记录全局查询历史
            record = {
                "id": query_id,
                "query": req.query,
                "mode": query_mode,
                "answer": full_answer,
                "images": agent_images,
                "time": datetime.now().isoformat(),
                "elapsed": elapsed,
                "kb": agent.kb_name,
                "agent_id": agent_id,
                "thread_id": thread_id,
            }
            query_history.insert(0, record)
            if len(query_history) > 100:
                query_history = query_history[:100]
            save_query_history()

            yield f"data: {json.dumps({'type': 'done', 'id': query_id, 'elapsed': elapsed, 'thread_id': thread_id, 'images': agent_images}, ensure_ascii=False)}\n\n"

        except Exception as exc:
            yield f"data: {json.dumps({'type': 'error', 'content': str(exc)}, ensure_ascii=False)}\n\n"
        finally:
            lightrag_logger.removeHandler(handler)

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


# ── 🔍 智能查询 ─────────────────────────────────────
# 格式化回答的 system prompt
QUERY_SYSTEM_PROMPT = """基于检索内容回答。引用检索内容中的具体事实和数据。检索内容没有的信息不要编造。"""

@app.post("/api/query")
async def query_rag(req: QueryRequest, kb: str = Depends(verify_kb_access)):
    """执行查询 - 手动构造 prompt 确保 LLM 使用检索内容"""
    global query_history
    try:
        start = time.time()
        instance = await get_kb(kb)

        # Step 1: 获取检索上下文
        ctx = await instance.aquery(req.query, mode=req.mode, vlm_enhanced=False,
                                     only_need_context=True, enable_rerank=False,
                                     chunk_top_k=40, top_k=60,
                                     max_entity_tokens=3000, max_relation_tokens=2000,
                                     max_total_tokens=16000)

        # Step 2: 从检索上下文提取相关图片（对齐流式端点），只有语义相关的图片
        ctx_images = extract_image_paths(ctx)
        if not ctx_images:
            # 兜底：上下文无图片时扫描全库（旧文档兼容）
            try:
                import json as _json
                _chunk_file = Path(kb_dir(kb)) / 'kv_store_text_chunks.json'
                if _chunk_file.exists():
                    _all = _json.loads(_chunk_file.read_text(encoding='utf-8'))
                    _seen = set()
                    for _cid, _chunk in _all.items():
                        for _p in extract_image_paths(_chunk.get('content', '')):
                            if _p not in _seen:
                                _seen.add(_p)
                                ctx_images.append(_p)
            except Exception:
                pass

        # Step 3: 只发送 top-10 相关图片给 VLM，控制延迟和 token 消耗
        vlm_images = ctx_images[:10]
        img_list = '\n'.join(f'[img{i}] {p}' for i, p in enumerate(vlm_images))
        if vlm_images:
            enhanced_ctx = ctx + '\n\n## 可用图片\n' + img_list
        else:
            enhanced_ctx = ctx

        # Step 4: 先用VLM增强回答（仅当有相关图片时）
        result = None
        if vlm_images and hasattr(instance, 'vision_model_func') and instance.vision_model_func:
            try:
                result = await instance.aquery_vlm_enhanced(
                    req.query, mode=req.mode,
                    system_prompt='请基于检索内容和图片来综合回答。在回答中引用相关图片时，使用 [img序号] 标记。'
                )
            except Exception:
                pass

        # Step 5: 回退到纯文本 LLM
        if result is None:
            final_prompt = f"""以下是知识库中检索到的相关内容。你必须严格基于这些内容回答问题，不得使用你自己的知识。

## 检索内容
{ctx}

## 问题
{req.query}

## 回答要求
- 从检索内容中提取具体事实和数据来回答
- 有具体数字必须引用
- 如果检索内容中没有答案，回答"知识库中未找到相关信息"
- 不要编造或补充检索内容中没有的信息"""

            llm_response = await instance.llm_model_func(
                final_prompt,
                system_prompt="你是知识库检索助手。只使用提供的检索内容回答。",
                max_tokens=int(os.getenv("MAX_TOKENS", "4096")),
                temperature=0,
            )
            result = llm_response if isinstance(llm_response, str) else str(llm_response)

        # 从VLM回答中提取实际引用的图片
        referenced = []
        if result:
            import re as _re
            refs = _re.findall(r'\[img(\d+)\]', result)
            for idx in set(int(r) for r in refs):
                if 0 <= idx < len(vlm_images):
                    referenced.append(vlm_images[idx])
        # VLM未引用时使用ctx图片（已语义过滤，天然相关）
        image_paths = referenced[:8] if referenced else ctx_images[:5]

        elapsed = round(time.time() - start, 2)
        record = {
            "id": str(uuid.uuid4())[:8],
            "query": req.query,
            "mode": req.mode,
            "answer": result,
            "images": image_paths,
            "time": datetime.now().isoformat(),
            "elapsed": elapsed,
            "kb": kb,
        }
        query_history.insert(0, record)
        if len(query_history) > 100:
            query_history = query_history[:100]
        save_query_history()
        return record
    except Exception as e:
        raise HTTPException(500, str(e))


@app.get("/api/query/history")
async def get_query_history(limit: int = 20, current_user: dict = Depends(get_current_user)):
    """查询历史"""
    return {"history": query_history[:limit]}


@app.delete("/api/query/history")
async def clear_query_history(kb: str = Depends(verify_kb_access)):
    """清空查询历史"""
    global query_history
    count = len(query_history)
    query_history.clear()
    save_query_history()
    await add_event("history_cleared", count=count, kb=kb)
    return {"status": "cleared", "count": count}


# ── 日志捕获器（用于流式查询思考过程）────────────────
class LogCaptureHandler(logging.Handler):
    """将 lightrag 日志消息捕获到线程安全队列中"""

    def __init__(self, msg_queue: queue.Queue):
        super().__init__()
        self.msg_queue = msg_queue
        self.setLevel(logging.INFO)
        self.setFormatter(logging.Formatter("%(message)s"))

    def emit(self, record):
        try:
            msg = self.format(record)
            if msg.strip():
                self.msg_queue.put(msg)
        except Exception:
            pass


# 需要在思考过程中显示的日志关键词（过滤掉不相关的日志）
THINKING_PATTERNS = [
    "executing", "query mode", "keywords", "query nodes", "local query",
    "query edges", "global query", "raw search", "after truncation",
    "entity-related chunks", "relations-related chunks", "merged chunks",
    "final context", "final chunks", "text query completed", "cache",
    "retrying request", "embedding",
]


def _is_thinking_msg(msg: str) -> bool:
    """判断日志消息是否应该作为思考过程展示"""
    msg_lower = msg.lower()
    return any(p in msg_lower for p in THINKING_PATTERNS)


# ── 🔍 流式查询（SSE）─────────────────────────────────
@app.post("/api/query/stream")
async def query_rag_stream(req: QueryRequest, kb: str = Depends(verify_kb_access)):
    """
    流式查询：通过 Server-Sent Events 实时推送思考过程和回答
    事件类型：
      - thinking: 思考步骤（检索、实体匹配、关键词提取等）
      - token: 回答的单个 token
      - done: 查询完成，包含元数据
      - error: 查询出错
    """
    global query_history
    instance = await get_kb(kb)

    async def event_stream():
        global query_history
        log_queue: queue.Queue = queue.Queue()
        handler = LogCaptureHandler(log_queue)
        lightrag_logger.addHandler(handler)
        query_id = str(uuid.uuid4())[:8]
        full_answer = ""

        try:
            yield f"data: {json.dumps({'type': 'thinking', 'content': f'🔍 开始查询: {req.query[:80]}...'}, ensure_ascii=False)}\n\n"

            start_time = time.time()

            # Step 1: 获取检索上下文
            ctx_task = asyncio.ensure_future(
                instance.aquery(req.query, mode=req.mode, vlm_enhanced=False,
                                only_need_context=True, enable_rerank=False,
                                chunk_top_k=40, top_k=60,
                                max_entity_tokens=3000, max_relation_tokens=2000,
                                max_total_tokens=16000)
            )

            # 轮询日志
            while not ctx_task.done():
                while True:
                    try:
                        msg = log_queue.get_nowait()
                        if _is_thinking_msg(msg):
                            dm = _translate_thinking_msg(msg)
                            if dm:
                                yield f"data: {json.dumps({'type': 'thinking', 'content': dm}, ensure_ascii=False)}\n\n"
                    except queue.Empty:
                        break
                await asyncio.sleep(0.06)

            ctx = ctx_task.result()
            # 从检索上下文提取图片，没有则扫全库
            stream_images = extract_image_paths(ctx)
            if not stream_images:
                try:
                    import json as _json
                    _chunk_file = Path(kb_dir(kb)) / 'kv_store_text_chunks.json'
                    if _chunk_file.exists():
                        _all = _json.loads(_chunk_file.read_text(encoding='utf-8'))
                        _all_text = '\n'.join(v.get('content', '') for v in _all.values() if isinstance(v, dict))
                        stream_images = extract_image_paths(_all_text)
                except Exception:
                    pass
            stream_images = stream_images[:5]
            yield f"data: {json.dumps({'type': 'thinking', 'content': f'📋 检索到 {len(ctx)} 字符上下文' + (f'，{len(stream_images)} 张图片' if stream_images else '')}, ensure_ascii=False)}\n\n"
            yield f"data: {json.dumps({'type': 'thinking', 'content': '💬 正在生成回答...'}, ensure_ascii=False)}\n\n"

            # Step 2: 构造 prompt 并流式调用 LLM
            final_prompt = f"以下是知识库检索内容。必须基于这些内容回答，不得使用你自己的知识。\n\n## 检索内容\n{ctx}\n\n## 问题\n{req.query}\n\n## 要求\n从检索内容提取事实和数据。有数字必须引用。没有就说未找到。不编造。"

            llm_response = await instance.llm_model_func(
                final_prompt,
                system_prompt="你是知识库助手。只使用检索内容回答。",
                max_tokens=int(os.getenv("MAX_TOKENS", "8192")),
                temperature=0,
                stream=True,
            )

            # 处理流式响应
            if llm_response is None:
                yield f"data: {json.dumps({'type': 'error', 'content': '模型返回空'}, ensure_ascii=False)}\n\n"
                return
            if isinstance(llm_response, str):
                full_answer = llm_response
                yield f"data: {json.dumps({'type': 'token', 'content': llm_response}, ensure_ascii=False)}\n\n"
            else:
                async for token in llm_response:
                    full_answer += token
                    yield f"data: {json.dumps({'type': 'token', 'content': token}, ensure_ascii=False)}\n\n"

            elapsed = round(time.time() - start_time, 2)
            record = {"id": query_id, "query": req.query, "mode": req.mode, "answer": full_answer,
                      "time": datetime.now().isoformat(), "elapsed": elapsed, "kb": kb}
            query_history.insert(0, record)
            if len(query_history) > 100: query_history = query_history[:100]
            save_query_history()
            yield f"data: {json.dumps({'type': 'done', 'id': query_id, 'elapsed': elapsed, 'images': stream_images}, ensure_ascii=False)}\n\n"

        except Exception as exc:
            yield f"data: {json.dumps({'type': 'error', 'content': str(exc)}, ensure_ascii=False)}\n\n"
        finally:
            lightrag_logger.removeHandler(handler)

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


def _translate_thinking_msg(msg: str) -> str:
    """将英文日志翻译/美化为中文思考过程"""
    msg_lower = msg.lower()

    if "executing text query" in msg_lower:
        return f"📝 正在解析查询意图..."
    if "query mode" in msg_lower:
        mode = msg.split(":")[-1].strip() if ":" in msg else ""
        mode_cn = {"hybrid": "混合检索", "local": "本地检索", "global": "全局检索", "naive": "朴素检索", "mix": "混合模式"}
        return f"📋 查询策略: {mode_cn.get(mode, mode)}"
    if "keywords" in msg_lower and "cache" in msg_lower:
        return f"🔑 提取关键词完成"
    if "keywords" in msg_lower:
        return f"🔑 正在提取查询关键词..."
    if "query nodes" in msg_lower:
        return f"🔗 检索知识图谱实体节点..."
    if "local query" in msg_lower:
        match = msg.split(":")[-1].strip() if ":" in msg else msg
        return f"📊 本地子图检索: {match}"
    if "query edges" in msg_lower:
        return f"🔗 检索知识图谱关系边..."
    if "global query" in msg_lower:
        match = msg.split(":")[-1].strip() if ":" in msg else msg
        return f"🌐 全局社区检索: {match}"
    if "raw search results" in msg_lower:
        return f"📦 原始检索结果: {msg.split(':')[-1].strip() if ':' in msg else msg}"
    if "after truncation" in msg_lower:
        return f"✂️ 结果优化截断: {msg.split(':')[-1].strip() if ':' in msg else msg}"
    if "entity-related chunks" in msg_lower:
        return f"📄 选取相关文本块..."
    if "relations-related chunks" in msg_lower:
        return f"📄 选取关系文本块..."
    if "merged chunks" in msg_lower:
        return f"🔄 合并排序文本块: {msg.split(':')[-1].strip() if ':' in msg else msg}"
    if "final context" in msg_lower:
        return f"📋 构建最终上下文: {msg.split(':')[-1].strip() if ':' in msg else msg}"
    if "final chunks" in msg_lower:
        return f"✅ 上下文整理完成"
    if "retrying request" in msg_lower:
        return f"⏳ API 请求重试中..."
    if "cache" in msg_lower and "saving" in msg_lower:
        return ""  # 静默缓存保存消息
    if "text query completed" in msg_lower:
        return ""  # 静默，因为有 done 事件

    # 默认：截取关键信息
    if len(msg) > 120:
        msg = msg[:120] + "..."
    return f"ℹ️ {msg}"


# ── ⚙️ 系统设置 ─────────────────────────────────────
@app.get("/api/settings")
async def get_settings(current_user: dict = Depends(get_current_user)):
    """获取当前配置"""
    return {
        "parser": os.getenv("PARSER", "docling"),
        "llm_model": LLM_MODEL,
        "vision_model": VISION_MODEL,
        "embedding_model": EMB_MODEL,
        "embedding_dim": EMB_DIM,
        "chunk_size": os.getenv("CHUNK_SIZE", "1200"),
        "chunking_strategy": CHUNKING_STRATEGY,
        "chunking_strategies": CHUNKING_STRATEGY_META,
        "max_async": os.getenv("MAX_ASYNC", "4"),
        "llm_max_async": os.getenv("LLM_MODEL_MAX_ASYNC", "4"),
        "enable_image": os.getenv("ENABLE_IMAGE_PROCESSING", "false").lower() == "true",
        "enable_table": os.getenv("ENABLE_TABLE_PROCESSING", "false").lower() == "true",
        "enable_equation": os.getenv("ENABLE_EQUATION_PROCESSING", "false").lower() == "true",
        "working_dir": WORKING_DIR,
        "parser_output_dir": os.getenv("OUTPUT_DIR", "./output"),
        "supported_extensions": [
            ".pdf", ".jpg", ".jpeg", ".png", ".bmp", ".tiff", ".gif", ".webp",
            ".doc", ".docx", ".ppt", ".pptx", ".xls", ".xlsx", ".txt", ".md",
        ],
    }


@app.put("/api/settings")
async def update_settings(settings: SettingsUpdate, current_user: dict = Depends(get_current_user)):
    """更新配置(runtime)"""
    global rag
    changes = {}
    if settings.parser is not None:
        os.environ["PARSER"] = settings.parser
        changes["parser"] = settings.parser
    if settings.chunk_size is not None:
        os.environ["CHUNK_SIZE"] = str(settings.chunk_size)
        changes["chunk_size"] = settings.chunk_size
    if settings.chunking_strategy is not None:
        global CHUNKING_STRATEGY
        os.environ["CHUNKING_STRATEGY"] = settings.chunking_strategy
        CHUNKING_STRATEGY = settings.chunking_strategy
        changes["chunking_strategy"] = settings.chunking_strategy
        # 分块策略变更需要重建所有知识库实例
        for name in list(kb_instances.keys()):
            del kb_instances[name]
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
    # 部分配置需要重建 RAG 实例才能生效
    if settings.parser is not None:
        rag = create_rag()
        await rag._ensure_lightrag_initialized()
    return {"status": "ok", "changes": changes, "note": "model/config changes may require restart"}


# ── 📈 监控面板 ─────────────────────────────────────
@app.get("/api/monitor/status")
async def monitor_status(current_user: dict = Depends(get_current_user)):
    """获取当前处理状态"""
    return {
        "tasks": list(processing_tasks.values()),
        "events": processing_events[-20:],
        "cache_size": len(query_history),
    }


@app.get("/api/monitor/stats")
async def monitor_stats(current_user: dict = Depends(get_current_user)):
    """LLM 调用统计"""
    cache_path = Path(WORKING_DIR) / "kv_store_llm_response_cache.json"
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


@app.get("/api/monitor/logs")
async def monitor_logs(limit: int = 50, current_user: dict = Depends(get_current_user)):
    """获取最近事件日志"""
    return {"events": processing_events[-limit:]}


@app.get("/api/health")
async def health(current_user: dict = Depends(get_current_user)):
    return {"status": "ok", "active_kb": active_kb}

# ── 🗂️ 多知识库管理 ─────────────────────────────────
@app.get("/api/kb/list")
async def list_kbs(current_user: dict = Depends(get_current_user)):
    meta = load_kb_meta()
    kbs = []
    for name, info in meta.items():
        # 数据隔离：普通用户只看自己的 KB，管理员看全部
        owner_id = info.get("owner_id")
        if owner_id is not None and owner_id != current_user["id"] and not current_user.get("is_admin"):
            continue
        kbs.append({
            "name": name,
            "label": info.get("name", name),
            "created": info.get("created", ""),
            "owner_id": owner_id,
            "owner_username": info.get("owner_username", ""),
            "active": name == active_kb,
        })
    return {"knowledge_bases": kbs, "active": active_kb}

@app.post("/api/kb/create")
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

@app.put("/api/kb/switch")
async def switch_kb(name: str = QueryParam(...), current_user: dict = Depends(get_current_user)):
    global active_kb
    meta = load_kb_meta()
    if name not in meta:
        raise HTTPException(404, f"知识库 '{name}' 不存在")
    # 权限检查（管理员可切换任意 KB）
    kb_info = meta[name]
    owner_id = kb_info.get("owner_id")
    if owner_id is not None and owner_id != current_user["id"] and not current_user.get("is_admin"):
        raise HTTPException(403, "无权访问该知识库")
    active_kb = name
    return {"status": "switched", "active": name}

@app.delete("/api/kb/{name}")
async def delete_kb(name: str, current_user: dict = Depends(get_current_user)):
    global active_kb
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
    import shutil
    shutil.rmtree(kb_dir(name), ignore_errors=True)
    del meta[name]
    save_kb_meta(meta)
    if active_kb == name:
        active_kb = "default"
    return {"status": "deleted", "name": name}


# ── 前端静态文件 ────────────────────────────────────
if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8001)
