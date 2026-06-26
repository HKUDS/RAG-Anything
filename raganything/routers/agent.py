"""Agent Router — /api/agents/* and agent query streaming"""

import asyncio
import json
import logging
import os
import queue
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from lightrag.llm.openai import openai_complete_if_cache
from lightrag.utils import logger as lightrag_logger

from raganything.routers.shared import (
    _bigram_image_scan,
    _build_citation_block,
    _DEGRADED_HINT,
    _discover_images_via_graph,
    _is_thinking_msg,
    _translate_thinking_msg,
    ANSWER_FORMAT_INSTRUCTION,
    API_KEY,
    BASE_URL,
    INLINE_QUOTE_INSTRUCTION,
    LLM_MODEL,
    QUERY_SYSTEM_PROMPT,
    VISION_MODEL,
    extract_image_paths,
    get_kb,
    kb_dir,
    query_history,
    record_query,
    verify_kb_access,
)
from raganything.utils.security import validate_query_input, decode_and_validate_query_image
from raganything.dependencies import get_current_user

from raganything.services.agent_manager import AgentConfig, get_agent_manager


# ═══════════════════════════════════════════════════════════
# LogCaptureHandler — 将 lightrag 日志消息捕获到线程安全队列中
# ═══════════════════════════════════════════════════════════

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


# ═══════════════════════════════════════════════════════════
# Empty context detection
# ═══════════════════════════════════════════════════════════

def _is_empty_context(ctx: str | None) -> bool:
    """Detect if retrieval context is effectively empty.

    Returns True when:
    - ctx is None or empty
    - ctx is LightRAG's fail_response (contains "[no-context]" marker)
    - ctx has no text chunk sources and is too short to be useful
    """
    if not ctx or not ctx.strip():
        return True
    if "[no-context]" in ctx:
        return True
    if "[来源 " not in ctx and len(ctx.strip()) <= 200:
        return True
    return False


# ═══════════════════════════════════════════════════════════
# Pydantic Models
# ═══════════════════════════════════════════════════════════

class AgentCreateRequest(BaseModel):
    name: str = "新智能体"
    icon: str = "🤖"
    description: str = ""
    kb_name: str = "default"
    llm_model: str = "qwen-plus"
    temperature: float = 0.0
    query_mode: str = "hybrid"
    agent_mode: str = "none"  # "none" | "react" | "cot"
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
    agent_mode: Optional[str] = None  # "none" | "react" | "cot"
    retrieval_top_k: Optional[int] = None
    system_prompt: Optional[str] = None
    use_default_prompt: Optional[bool] = None
    welcome_message: Optional[str] = None


class AgentQueryRequest(BaseModel):
    query: str
    thread_id: str = ""  # 关联的对话线程 ID
    mode: str = ""  # 空则使用智能体默认模式
    agent_mode: Optional[str] = None  # 空则使用智能体默认的 agent_mode
    vlm_enhanced: bool = False
    image: Optional[str] = None  # base64 data URI of user-uploaded query image (e.g. data:image/jpeg;base64,...)


# ═══════════════════════════════════════════════════════════
# Router
# ═══════════════════════════════════════════════════════════

router = APIRouter(tags=["agents"])


# ── 智能体 CRUD ─────────────────────────────────────

@router.get("/agents")
async def list_agents(current_user: dict = Depends(get_current_user)):
    """列出智能体（按用户隔离，管理员看全部）"""
    mgr = get_agent_manager()
    agents = mgr.list_agents(
        user_id=current_user["id"],
        is_admin=current_user.get("is_admin", False),
    )
    return {
        "agents": [a.model_dump() for a in agents],
        "total": len(agents),
    }


@router.get("/agents/templates")
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


@router.post("/agents")
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
        agent_mode=req.agent_mode,
        system_prompt=req.system_prompt,
        use_default_prompt=req.use_default_prompt,
        template_id=req.template_id,
    )
    config = mgr.create_agent(config, owner_id=current_user["id"], owner_username=current_user["username"])
    return {"status": "ok", "agent": config.model_dump()}


@router.put("/agents/{agent_id}")
async def update_agent(agent_id: str, req: AgentUpdateRequest, current_user: dict = Depends(get_current_user)):
    """更新智能体配置（仅所有者或管理员）"""
    mgr = get_agent_manager()
    agent = mgr.get_agent(agent_id)
    if not agent:
        raise HTTPException(404, "智能体不存在")
    is_admin = current_user.get("is_admin", False)
    if agent.owner_id != 0 and agent.owner_id != current_user["id"] and not is_admin:
        raise HTTPException(403, "无权修改该智能体")
    updates = {k: v for k, v in req.model_dump().items() if v is not None}
    agent = mgr.update_agent(agent_id, updates)
    if not agent:
        raise HTTPException(404, "智能体不存在")
    return {"status": "ok", "agent": agent.model_dump()}


@router.delete("/agents/{agent_id}")
async def delete_agent(agent_id: str, current_user: dict = Depends(get_current_user)):
    """删除智能体（仅所有者或管理员）"""
    mgr = get_agent_manager()
    agent = mgr.get_agent(agent_id)
    if not agent:
        raise HTTPException(404, "智能体不存在")
    is_admin = current_user.get("is_admin", False)
    if agent.owner_id != 0 and agent.owner_id != current_user["id"] and not is_admin:
        raise HTTPException(403, "无权删除该智能体")
    if not mgr.delete_agent(agent_id):
        raise HTTPException(404, "智能体不存在")
    return {"status": "ok"}


# ── 对话线程 CRUD ──────────────────────────────────

@router.get("/agents/{agent_id}/conversations")
async def list_conversations(agent_id: str, current_user: dict = Depends(get_current_user)):
    """列出智能体的对话线程（按用户隔离，管理员看全部）"""
    mgr = get_agent_manager()
    agent = mgr.get_agent(agent_id)
    if not agent:
        raise HTTPException(404, "智能体不存在")
    is_admin = current_user.get("is_admin", False)
    if agent.owner_id != 0 and agent.owner_id != current_user["id"] and not is_admin:
        raise HTTPException(403, "无权访问该智能体")
    threads = mgr.list_conversations(
        agent_id,
        user_id=current_user["id"],
        is_admin=current_user.get("is_admin", False),
    )
    return {
        "threads": [t.model_dump() for t in threads],
        "total": len(threads),
    }


@router.post("/agents/{agent_id}/conversations")
async def create_conversation(agent_id: str, title: str = "新对话", current_user: dict = Depends(get_current_user)):
    """创建新对话线程（注入所有权，需校验 Agent 所有权）"""
    mgr = get_agent_manager()
    agent = mgr.get_agent(agent_id)
    if not agent:
        raise HTTPException(404, "智能体不存在")
    is_admin = current_user.get("is_admin", False)
    if agent.owner_id != 0 and agent.owner_id != current_user["id"] and not is_admin:
        raise HTTPException(403, "无权使用该智能体")
    thread = mgr.create_conversation(agent_id, title, owner_id=current_user["id"])
    return {"status": "ok", "thread": thread.model_dump()}


@router.put("/agents/{agent_id}/conversations/{thread_id}")
async def update_conversation(agent_id: str, thread_id: str, title: str = None, current_user: dict = Depends(get_current_user)):
    """更新对话线程（需校验 Agent 所有权 + 对话所有权）"""
    mgr = get_agent_manager()
    agent = mgr.get_agent(agent_id)
    if not agent:
        raise HTTPException(404, "智能体不存在")
    is_admin = current_user.get("is_admin", False)
    if agent.owner_id != 0 and agent.owner_id != current_user["id"] and not is_admin:
        raise HTTPException(403, "无权访问该智能体")
    thread = mgr.get_conversation(agent_id, thread_id)
    if not thread:
        raise HTTPException(404, "对话线程不存在")
    if thread.owner_id != 0 and thread.owner_id != current_user["id"] and not is_admin:
        raise HTTPException(403, "无权修改该对话")
    thread = mgr.update_conversation(agent_id, thread_id, {"title": title})
    return {"status": "ok", "thread": thread.model_dump() if thread else None}


@router.delete("/agents/{agent_id}/conversations/{thread_id}")
async def delete_conversation(agent_id: str, thread_id: str, current_user: dict = Depends(get_current_user)):
    """删除对话线程（需校验 Agent 所有权 + 对话所有权）"""
    mgr = get_agent_manager()
    agent = mgr.get_agent(agent_id)
    if not agent:
        raise HTTPException(404, "智能体不存在")
    is_admin = current_user.get("is_admin", False)
    if agent.owner_id != 0 and agent.owner_id != current_user["id"] and not is_admin:
        raise HTTPException(403, "无权访问该智能体")
    thread = mgr.get_conversation(agent_id, thread_id)
    if not thread:
        raise HTTPException(404, "对话线程不存在")
    if thread.owner_id != 0 and thread.owner_id != current_user["id"] and not is_admin:
        raise HTTPException(403, "无权删除该对话")
    if not mgr.delete_conversation(agent_id, thread_id):
        raise HTTPException(404, "对话线程不存在")
    return {"status": "ok"}


# ── 🔍 智能查询（智能体增强）─────────────────────────────

@router.post("/agents/{agent_id}/query/stream")
async def agent_query_stream(agent_id: str, req: AgentQueryRequest, request: Request, current_user: dict = Depends(get_current_user)):
    """智能体流式查询：使用智能体配置执行查询"""
    mgr = get_agent_manager()
    agent = mgr.get_agent(agent_id)
    if not agent:
        raise HTTPException(404, "智能体不存在")

    # 验证 Agent 所有权（非所有者/管理员不可用）
    is_admin = current_user.get("is_admin", False)
    if agent.owner_id != 0 and agent.owner_id != current_user["id"] and not is_admin:
        raise HTTPException(403, "无权使用该智能体")
    # 输入校验 — Prompt Injection 防护
    # 当用户仅发送图片而无文字时，自动补全安全占位查询文本，
    # 确保 validate_query_input 始终有内容可校验，同时让下游
    # SSE / VLM / 历史记录等 20+ 处 req.query 引用获得一致的默认值。
    if (not req.query or not req.query.strip()) and req.image:
        req.query = "请分析这张图片"
    validate_query_input(req.query, user_id=str(current_user.get("id", "anonymous")))
    # 验证 KB 访问权限（可能自动切换到用户的个人 KB）
    actual_kb = await verify_kb_access(kb=agent.kb_name, current_user=current_user)

    instance = await get_kb(actual_kb)
    # 检索模式（agentic 路径优先 rrf 轻量模式，可被请求级覆盖；普通路径沿用 agent 配置）
    query_mode = req.mode or agent.query_mode
    # 推理模式：请求级覆盖 > 智能体配置 > 默认 none
    agent_mode = req.agent_mode or getattr(agent, 'agent_mode', 'none')
    # AgenticRAG 专用检索模式：优先请求级，否则默认 rrf（更快）
    agentic_query_mode = req.mode or "rrf"

    # 构建 system_prompt
    system_prompt = agent.system_prompt
    if agent.use_default_prompt:
        system_prompt = (system_prompt + "\n\n" + QUERY_SYSTEM_PROMPT).strip()

    # 确保对话线程存在
    thread_id = req.thread_id
    if not thread_id:
        thread = mgr.create_conversation(agent_id, title="新对话", owner_id=current_user["id"])
        thread_id = thread.id

    # ── 多轮对话上下文提取 ──
    conv_history_text = ""
    max_conv_rounds = int(os.getenv("CONVERSATION_MAX_ROUNDS", "3"))
    max_conv_tokens = int(os.getenv("CONVERSATION_MAX_TOKENS", "2000"))
    conv_thread = mgr.get_conversation(agent_id, thread_id)
    if conv_thread and conv_thread.messages:
        max_msgs = max_conv_rounds * 2
        recent = conv_thread.messages[-max_msgs:]
        lines = []
        token_est = 0
        for msg in reversed(recent):
            role_label = "用户" if msg.get("role") == "user" else "助手"
            line = f"{role_label}: {msg.get('content', '')[:500]}"
            est = max(1, len(line) // 2)
            if token_est + est > max_conv_tokens:
                break
            lines.insert(0, line)
            token_est += est
        if lines:
            conv_history_text = "\n".join(lines)

    async def event_stream():
        log_queue: queue.Queue = queue.Queue()
        handler = LogCaptureHandler(log_queue)
        lightrag_logger.addHandler(handler)
        query_id = str(uuid.uuid4())[:8]
        full_answer = ""

        try:
            yield f"data: {json.dumps({'type': 'agent_info', 'agent': agent.name, 'icon': agent.icon, 'thread_id': thread_id}, ensure_ascii=False)}\n\n"
            yield f"data: {json.dumps({'type': 'thinking', 'content': f'🔍 开始查询: {req.query[:80]}...'}, ensure_ascii=False)}\n\n"

            # ═══ Image Processing (user-uploaded query image) ═══
            image_description = None
            similar_images = []
            _similar_image_urls: list[dict] = []
            if req.image:
                yield f"data: {json.dumps({'type': 'image_analysis', 'status': 'analyzing'}, ensure_ascii=False)}\n\n"

                # 0. Validate and decode the base64 image
                image_bytes = decode_and_validate_query_image(req.image)
                if image_bytes is None:
                    yield f"data: {json.dumps({'type': 'image_analysis', 'status': 'error', 'error': '图片无效或大小超过限制（最大5MB）'}, ensure_ascii=False)}\n\n"
                else:
                    import base64 as _b64_mod
                    _img_b64 = _b64_mod.b64encode(image_bytes).decode("ascii")

                    # 1. Parallel: VLM description + Vision embedding search
                    async def _run_vlm_desc():
                        """Generate a text description of the uploaded image using VLM."""
                        try:
                            vis_func = getattr(instance, 'vision_model_func', None)
                            if vis_func is None:
                                return None
                            _prompt = f"请详细描述这张图片的内容。用户的问题是：「{req.query}」。请根据用户的问题，重点描述图片中与问题相关的元素。使用中文，100-300字。"
                            # vision_func returns a coroutine (from openai_complete_if_cache)
                            result = await vis_func(
                                _prompt,
                                system_prompt="你是一个视觉分析助手。请用简洁的自然语言描述图片内容，不要使用JSON格式。",
                                image_data=_img_b64,
                            )
                            if isinstance(result, str) and len(result.strip()) > 5:
                                return result.strip()
                            return None
                        except Exception as _e:
                            lightrag_logger.warning(f"[IMG-QUERY] VLM description failed: {_e}")
                            return None

                    async def _run_vision_search():
                        """Find similar images in the KB via vision embedding."""
                        if not instance.config.vision_search_enabled:
                            lightrag_logger.info("[IMG-QUERY] VISION_SEARCH_ENABLED=False, skipping vision search")
                            return []
                        try:
                            vef = getattr(instance, 'vision_embed_func', None)
                            repo = getattr(instance.lightrag, 'image_vision_repo', None) if hasattr(instance, 'lightrag') else None
                            if vef is None:
                                lightrag_logger.warning("[IMG-QUERY] vision_embed_func unavailable, skipping vision search")
                                return []
                            if repo is None:
                                lightrag_logger.warning("[IMG-QUERY] image_vision_repo not initialized, skipping vision search")
                                return []
                            # Reload VDB from disk so we see data written by worker subprocess
                            await repo.reload()
                            vdb_count_before = repo.count()
                            lightrag_logger.info("[IMG-QUERY] VDB count after reload: %d", vdb_count_before)
                            vec = await vef.embed_image_bytes(image_bytes, req.query[:500], label="query_image")
                            if vec is None:
                                lightrag_logger.warning("[IMG-QUERY] embed_image_bytes returned None, skipping vision search")
                                return []
                            results = await repo.query(vec, top_k=5)
                            return [
                                {"image_path": r.get("image_path", ""),
                                 "entity_name": r.get("entity_name", ""),
                                 "description": r.get("description", ""),
                                 "score": round(r.get("_score", 0), 3)}
                                for r in results if r.get("_score", 0) > 0.4
                            ]
                        except Exception as _e:
                            lightrag_logger.warning(f"[IMG-QUERY] Vision search failed: {_e}")
                            return []

                    vlm_task = asyncio.create_task(_run_vlm_desc())
                    vision_task = asyncio.create_task(_run_vision_search())
                    _vlm_res, _vis_res = await asyncio.gather(vlm_task, vision_task, return_exceptions=True)

                    image_description = _vlm_res if not isinstance(_vlm_res, Exception) else None
                    similar_images = _vis_res if not isinstance(_vis_res, Exception) else []

                    # Build shareable image URLs with the current user's token
                    _auth_token = request.headers.get("Authorization", "").removeprefix("Bearer ")
                    _similar_image_urls: list[dict] = []
                    if similar_images and _auth_token:
                        from urllib.parse import quote
                        for _si in similar_images:
                            _raw_path = _si.get("image_path", "")
                            if _raw_path:
                                _url = f"/api/files/image?path={quote(_raw_path, safe='')}&token={_auth_token}"
                                _similar_image_urls.append({
                                    "url": _url,
                                    "name": _si.get("entity_name", ""),
                                    "score": _si.get("score", 0),
                                })

                    _status_fields = {"status": "done"}
                    if image_description:
                        _status_fields["description_preview"] = image_description[:100]
                    if similar_images:
                        _status_fields["similar_count"] = len(similar_images)
                    yield f"data: {json.dumps({'type': 'image_analysis', **_status_fields}, ensure_ascii=False)}\n\n"
                    # Emit similar image URLs for frontend rendering
                    if _similar_image_urls:
                        yield f"data: {json.dumps({'type': 'image_results', 'images': _similar_image_urls}, ensure_ascii=False)}\n\n"

            # ═══ AgenticRAG 推理路径（ReAct / CoT） ═══
            if agent_mode in ("react", "cot"):
                start_time = time.time()
                from raganything.agentic_rag import AgenticRAG, SearchTool

                agentic = AgenticRAG(
                    llm_func=instance.llm_model_func,
                    max_steps=int(os.getenv("AGENT_MAX_STEPS", "5")),
                    mode=agent_mode,
                )
                agentic.register_tool(SearchTool(instance, query_mode=agentic_query_mode))

                full_answer = ""
                trace_steps = []

                if agent_mode == "react":
                    # ReAct 流式路径 — 注入对话历史 + 图片上下文
                    react_query = req.query
                    # Prepend image context if available
                    _img_ctx = ""
                    if image_description:
                        _img_ctx += f"## 用户上传图片的视觉描述\n{image_description}\n\n"
                    if _similar_image_urls:
                        _img_ctx += "## 知识库中找到的视觉相似图片\n"
                        for _si in _similar_image_urls[:5]:
                            _img_ctx += (
                                f"![{_si['name']}]({_si['url']})\n"
                                f"*{_si['name']} (视觉相似度: {_si['score']})*\n\n"
                            )
                    if _img_ctx:
                        react_query = f"{_img_ctx}## 用户问题\n{req.query}"
                    if conv_history_text:
                        react_query = (
                            f"## 对话历史\n{conv_history_text}\n\n"
                            f"{react_query}"
                        )
                    async for event in agentic.run_stream(react_query):
                        if event.type == "thinking":
                            sd = {
                                "step": event.step or 0,
                                "thought": event.thought or "",
                                "action": event.action or "",
                                "observation": event.observation or "",
                                "elapsed_ms": event.elapsed_ms,
                            }
                            trace_steps.append(sd)
                            yield f"data: {json.dumps({'type': 'thinking', **sd}, ensure_ascii=False)}\n\n"
                        elif event.type == "token":
                            full_answer += (event.content or "")
                            yield f"data: {json.dumps({'type': 'token', 'content': event.content or ''}, ensure_ascii=False)}\n\n"
                        elif event.type == "done":
                            if event.answer and len(event.answer) > len(full_answer):
                                full_answer = event.answer
                            break
                else:
                    # CoT 路径：先 RRF 检索获取上下文，再注入 CoT 推理
                    # If we have an image description, use it to enrich the search query
                    _cot_search_query = req.query
                    if image_description:
                        _cot_search_query = f"{req.query}\n\n[图片描述]\n{image_description[:500]}"
                    cot_context = ""
                    try:
                        cot_context = await instance.aquery(
                            _cot_search_query, mode="rrf", only_need_context=True,
                            top_k=30, max_total_tokens=8000,
                        ) or ""
                    except Exception:
                        pass
                    # Prepend image context before conversation history
                    _img_cot_ctx = ""
                    if image_description:
                        _img_cot_ctx += f"## 用户上传图片的视觉描述\n{image_description}\n\n"
                    if _similar_image_urls:
                        _img_cot_ctx += "## 知识库中找到的视觉相似图片\n"
                        for _si in _similar_image_urls[:5]:
                            _img_cot_ctx += (
                                f"![{_si['name']}]({_si['url']})\n"
                                f"*{_si['name']} (视觉相似度: {_si['score']})*\n\n"
                            )
                    # Inject conversation history
                    if conv_history_text:
                        _img_cot_ctx += f"## 对话历史\n{conv_history_text}\n\n"
                    if _img_cot_ctx and cot_context:
                        cot_context = _img_cot_ctx + "## 检索文档\n" + cot_context
                    if _is_empty_context(cot_context):
                        lightrag_logger.info("[AGENT-STREAM] CoT: no valid context, aborting")
                        full_answer = "抱歉，知识库中暂无与您问题相关的数据，无法回答此问题。请尝试上传相关文档或换个问题。"
                        yield f"data: {json.dumps({'type': 'thinking', 'content': '⚠️ 知识库中暂无相关数据'}, ensure_ascii=False)}\n\n"
                        yield f"data: {json.dumps({'type': 'token', 'content': full_answer}, ensure_ascii=False)}\n\n"
                        elapsed = round(time.time() - start_time, 2)
                        mgr.add_message(agent_id, thread_id, {
                            "role": "user", "content": req.query,
                            "time": datetime.now().isoformat(),
                        })
                        mgr.add_message(agent_id, thread_id, {
                            "role": "assistant", "content": full_answer,
                            "elapsed": elapsed, "mode": query_mode,
                            "agent_mode": agent_mode, "trace": [],
                            "fallback": True,
                            "time": datetime.now().isoformat(),
                        })
                        record = {
                            "id": query_id, "query": req.query, "mode": query_mode,
                            "agent_mode": agent_mode, "answer": full_answer,
                            "reasoning_trace": {"steps": [], "total_steps": 0},
                            "images": [], "time": datetime.now().isoformat(),
                            "elapsed": elapsed, "kb": actual_kb,
                            "agent_id": agent_id, "thread_id": thread_id,
                            "user_id": current_user["id"], "username": current_user["username"],
                            "fallback": True,
                        }
                        await record_query(record, max_history=100)
                        _done_cot_empty = {'type': 'done', 'id': query_id, 'elapsed': elapsed, 'thread_id': thread_id, 'images': [], 'fallback': True}
                        if image_description:
                            _done_cot_empty['image_description'] = image_description
                        if similar_images:
                            _done_cot_empty['similar_images'] = similar_images
                        yield f"data: {json.dumps(_done_cot_empty, ensure_ascii=False)}\n\n"
                        lightrag_logger.removeHandler(handler)
                        return
                    # 对话历史已在 line 527-530 注入到 _img_cot_ctx，此处不重复注入
                    agent_result = await agentic.run_with_context(req.query, cot_context)
                    full_answer = agent_result.answer
                    for s in agent_result.trace:
                        trace_steps.append({
                            "step": s.step_number,
                            "thought": s.thought,
                            "elapsed_ms": s.elapsed_ms,
                        })
                        yield f"data: {json.dumps({'type': 'thinking', 'step': s.step_number, 'thought': s.thought, 'elapsed_ms': s.elapsed_ms}, ensure_ascii=False)}\n\n"
                    yield f"data: {json.dumps({'type': 'token', 'content': full_answer}, ensure_ascii=False)}\n\n"

                elapsed = round(time.time() - start_time, 2)
                lightrag_logger.info(f"[AGENT-STREAM] mode={agent_mode} steps={len(trace_steps)} elapsed={elapsed}s")

                # ── 图片匹配（图谱发现 + bigram 兜底）──
                # 从 ReAct search observation 和 CoT 检索上下文中提取图片路径
                all_retrieved_text = ""
                for ts in trace_steps:
                    if ts.get("observation"):
                        all_retrieved_text += ts["observation"] + "\n"
                if agent_mode == "cot" and cot_context:
                    all_retrieved_text += cot_context + "\n"
                all_retrieved_text += " " + req.query
                all_retrieved_text += " " + full_answer

                agent_images = extract_image_paths(all_retrieved_text)
                _backfill_text_react = ""
                if not agent_images:
                    # 第二道：实体图谱图片发现
                    agent_images, _backfill_text_react = await _discover_images_via_graph(
                        instance, req.query, actual_kb, all_retrieved_text
                    )
                    if _backfill_text_react:
                        all_retrieved_text += "\n" + _backfill_text_react

                if not agent_images:
                    # 第三道：bigram 全库扫描
                    try:
                        agent_images, _backfill_text_react = await _bigram_image_scan(
                            kb_dir(actual_kb), req.query, all_retrieved_text, instance
                        )
                        if _backfill_text_react:
                            all_retrieved_text += "\n" + _backfill_text_react
                    except Exception as _fe:
                        lightrag_logger.error(f"[AGENT-IMG] 全库扫描失败: {_fe}")
                else:
                    agent_images = agent_images[:3]

                # Citation fallback for agent path: collect context from trace/COT
                _agent_ctx = ""
                if agent_mode == "cot":
                    _agent_ctx = cot_context
                else:
                    for ts in trace_steps:
                        if ts.get("observation"):
                            _agent_ctx += ts["observation"] + "\n"
                # 注入回填文本到 citation 上下文
                if _backfill_text_react and _agent_ctx:
                    _agent_ctx += "\n" + _backfill_text_react
                if instance.config.enforce_citation and full_answer and _agent_ctx:
                    _cit_block = _build_citation_block(_agent_ctx, full_answer)
                    if _cit_block:
                        full_answer += _cit_block
                        yield f"data: {json.dumps({'type': 'token', 'content': _cit_block}, ensure_ascii=False)}\n\n"

                # 保存到对话线程
                mgr.add_message(agent_id, thread_id, {
                    "role": "user", "content": req.query,
                    "time": datetime.now().isoformat(),
                })
                mgr.add_message(agent_id, thread_id, {
                    "role": "assistant", "content": full_answer,
                    "elapsed": elapsed, "mode": query_mode,
                    "agent_mode": agent_mode, "trace": trace_steps,
                    "time": datetime.now().isoformat(),
                })

                # 记录全局查询历史
                record = {
                    "id": query_id, "query": req.query, "mode": query_mode,
                    "agent_mode": agent_mode, "answer": full_answer,
                    "reasoning_trace": {"steps": trace_steps, "total_steps": len(trace_steps)},
                    "images": agent_images, "time": datetime.now().isoformat(),
                    "elapsed": elapsed, "kb": actual_kb,
                    "agent_id": agent_id, "thread_id": thread_id,
                    "user_id": current_user["id"], "username": current_user["username"],
                }
                await record_query(record, max_history=100)

                _done_agentic = {'type': 'done', 'id': query_id, 'elapsed': elapsed, 'thread_id': thread_id, 'images': agent_images}
                if image_description:
                    _done_agentic['image_description'] = image_description
                if similar_images:
                    _done_agentic['similar_images'] = similar_images
                yield f"data: {json.dumps(_done_agentic, ensure_ascii=False)}\n\n"
                return

            # ═══ 普通 RAG 流式路径（agent_mode=none） ═══
            start_time = time.time()

            # Step 1: 获取检索上下文
            # 对标 CoT 路径 — 用 VLM 描述 + 视觉相似实体富化检索查询，
            # 确保图片语义能够命中知识库中的相关文本块。
            _search_query = req.query
            if image_description:
                _search_query = f"{req.query}\n\n[图片描述]\n{image_description[:500]}"
            if similar_images:
                _en = [si['entity_name'] for si in similar_images if si.get('entity_name')]
                if _en:
                    _search_query += f"\n\n[视觉相似实体]\n{' '.join(_en[:5])}"
            ctx_task = asyncio.ensure_future(
                instance.aquery(_search_query, mode=query_mode, vlm_enhanced=False,
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

            # ── 快速检测：真正空的上下文（fail_response / None / 空字符串）──
            _is_truly_empty = not ctx or not ctx.strip() or "[no-context]" in ctx

            if _is_truly_empty:
                # ── 降级路径：无有效检索上下文 → 直接告知用户 ──
                agent_images = []
                yield f"data: {json.dumps({'type': 'thinking', 'content': '⚠️ 知识库中暂无相关数据'}, ensure_ascii=False)}\n\n"
                full_answer = "抱歉，知识库中暂无与您问题相关的数据，无法回答此问题。请尝试上传相关文档或换个问题。"

                # 保存到对话线程
                mgr.add_message(agent_id, thread_id, {
                    "role": "user",
                    "content": req.query,
                    "time": datetime.now().isoformat(),
                })
                mgr.add_message(agent_id, thread_id, {
                    "role": "assistant",
                    "content": full_answer,
                    "elapsed": round(time.time() - start_time, 2),
                    "mode": query_mode,
                    "fallback": True,
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
                    "elapsed": round(time.time() - start_time, 2),
                    "kb": actual_kb,
                    "agent_id": agent_id,
                    "thread_id": thread_id,
                    "user_id": current_user["id"],
                    "username": current_user["username"],
                    "fallback": True,
                }
                await record_query(record, max_history=100)

                yield f"data: {json.dumps({'type': 'token', 'content': full_answer}, ensure_ascii=False)}\n\n"
                _done_data = {
                    'type': 'done', 'id': query_id,
                    'elapsed': round(time.time() - start_time, 2),
                    'thread_id': thread_id, 'images': agent_images,
                    'fallback': True,
                }
                if image_description:
                    _done_data['image_description'] = image_description
                if similar_images:
                    _done_data['similar_images'] = similar_images
                yield f"data: {json.dumps(_done_data, ensure_ascii=False)}\n\n"
                # 提前返回，不走到下方的通用 LLM 调用路径
                lightrag_logger.removeHandler(handler)
                return

            # ── 图片提取（所有查询模式统一，三段式）──
            agent_images = extract_image_paths(ctx)
            backfill_text = ""

            if not agent_images:
                # Africa 第二道：实体图谱图片发现（语义级别，模式无关）
                agent_images, backfill_text = await _discover_images_via_graph(
                    instance, req.query, actual_kb, ctx
                )
                if backfill_text:
                    ctx = ctx + "\n\n" + backfill_text

            if not agent_images:
                # 第三道：bigram 全库扫描（字符级别兜底）
                try:
                    agent_images, backfill_text = await _bigram_image_scan(
                        kb_dir(actual_kb), req.query, ctx, instance
                    )
                    if backfill_text:
                        ctx = ctx + "\n\n" + backfill_text
                except Exception as _fe:
                    lightrag_logger.error(f"[IMG-FALLBACK] 全库扫描失败: {_fe}")
            else:
                agent_images = agent_images[:3]

            # ── 最终空上下文检测（使用富化后的 ctx）──
            is_fallback = _is_empty_context(ctx)

            if is_fallback:
                # ── 回填后仍为空 → 降级告知用户 ──
                yield f"data: {json.dumps({'type': 'thinking', 'content': '⚠️ 知识库中暂无相关数据'}, ensure_ascii=False)}\n\n"
                full_answer = "抱歉，知识库中暂无与您问题相关的数据，无法回答此问题。请尝试上传相关文档或换个问题。"

                # 保存到对话线程
                mgr.add_message(agent_id, thread_id, {
                    "role": "user",
                    "content": req.query,
                    "time": datetime.now().isoformat(),
                })
                mgr.add_message(agent_id, thread_id, {
                    "role": "assistant",
                    "content": full_answer,
                    "elapsed": round(time.time() - start_time, 2),
                    "mode": query_mode,
                    "fallback": True,
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
                    "elapsed": round(time.time() - start_time, 2),
                    "kb": actual_kb,
                    "agent_id": agent_id,
                    "thread_id": thread_id,
                    "user_id": current_user["id"],
                    "username": current_user["username"],
                    "fallback": True,
                }
                await record_query(record, max_history=100)

                yield f"data: {json.dumps({'type': 'token', 'content': full_answer}, ensure_ascii=False)}\n\n"
                _done_data = {
                    'type': 'done', 'id': query_id,
                    'elapsed': round(time.time() - start_time, 2),
                    'thread_id': thread_id, 'images': agent_images,
                    'fallback': True,
                }
                if image_description:
                    _done_data['image_description'] = image_description
                if similar_images:
                    _done_data['similar_images'] = similar_images
                yield f"data: {json.dumps(_done_data, ensure_ascii=False)}\n\n"
                lightrag_logger.removeHandler(handler)
                return

            # ── 正常路径：使用富化后的上下文 ──
            _ctx_think_msg = '📋 检索到 {} 字符上下文'.format(len(ctx))
            if agent_images:
                _ctx_think_msg += '，{} 张图片'.format(len(agent_images))
            yield f"data: {json.dumps({'type': 'thinking', 'content': _ctx_think_msg}, ensure_ascii=False)}\n\n"
            yield f"data: {json.dumps({'type': 'thinking', 'content': '💬 正在生成回答...'}, ensure_ascii=False)}\n\n"

            # Step 2: 构造 prompt 并使用智能体配置的模型
            sp = (agent.system_prompt or "") + ("\n你是知识库助手。只使用检索内容回答。" if agent.use_default_prompt else "")
            _conv_part = (
                f"## 对话历史\n{conv_history_text}\n\n"
                if conv_history_text else ""
            )
            # Select citation instruction based on config (same as non-agent endpoints)
            _cit_inst = (
                ANSWER_FORMAT_INSTRUCTION if instance.config.enforce_citation
                else INLINE_QUOTE_INSTRUCTION
            )
            # Detect degraded context (text chunks exist but may be thin)
            # Uses enriched ctx — may include backfilled chunks.
            # When backfill was applied, we KNOW valid text chunks exist, so bypass the length check.
            _has_chunks = ("[来源 " in ctx and len(ctx.strip()) > 200) or bool(backfill_text)
            # Build image context section for the prompt
            _img_section = ""
            if image_description:
                _img_section += f"## 用户上传图片的视觉分析\n{image_description}\n\n"
            if similar_images:
                _img_section += "## 知识库中视觉相似的图片\n"
                for _si in similar_images[:5]:
                    _img_section += f"- {_si['entity_name'] or _si['image_path']} (相似度: {_si['score']})\n"
                    if _si.get('description'):
                        _img_section += f"  描述: {_si['description'][:200]}\n"
                _img_section += "\n"

            if not _has_chunks and ctx.strip():
                lightrag_logger.warning("agent_query_stream: context has no text chunks.")
            final_prompt = (
                f"以下是知识库检索内容。必须基于这些内容回答，不得使用你自己的知识。\n\n"
                f"{_img_section}"
                f"{_conv_part}"
                f"## 检索内容\n{ctx}\n\n"
                f"## 问题\n{req.query}\n\n"
                f"{_cit_inst}"
                f"{'' if _has_chunks else _DEGRADED_HINT}"
            )

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
                _stream_tokens = []
                try:
                    async for token in llm_response:
                        _stream_tokens.append(token)
                        full_answer += token
                        yield f"data: {json.dumps({'type': 'token', 'content': token}, ensure_ascii=False)}\n\n"
                except Exception as _stream_err:
                    lightrag_logger.warning(
                        f"LLM stream interrupted after {len(_stream_tokens)} tokens: {_stream_err}"
                    )
                    if not _stream_tokens:
                        raise
                    yield f"data: {json.dumps({'type': 'warning', 'content': '⚠️ 模型响应被截断，以下回答可能不完整'}, ensure_ascii=False)}\n\n"

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
                "fallback": is_fallback,
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
                "kb": actual_kb,
                "agent_id": agent_id,
                "thread_id": thread_id,
                "user_id": current_user["id"],
                "username": current_user["username"],
                "fallback": is_fallback,
            }
            await record_query(record, max_history=100)

            _done_data = {
                'type': 'done', 'id': query_id, 'elapsed': elapsed,
                'thread_id': thread_id, 'images': agent_images,
            }
            if is_fallback:
                _done_data['fallback'] = True
            if image_description:
                _done_data['image_description'] = image_description
            if similar_images:
                _done_data['similar_images'] = similar_images
            yield f"data: {json.dumps(_done_data, ensure_ascii=False)}\n\n"

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
