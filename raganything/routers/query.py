"""
Query Router — /api/query, /api/conversations, streaming endpoints.
Extracted from server.py.
"""
import asyncio
import json
import logging
import os
import queue
import time
import uuid
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse, JSONResponse
from pydantic import BaseModel

from lightrag.utils import logger as lightrag_logger
from raganything.prompt import ANSWER_FORMAT_INSTRUCTION, INLINE_QUOTE_INSTRUCTION
from raganything.routers import shared  # mutable state accessed via shared. prefix
from raganything.dependencies import get_current_user, limiter, verify_kb_access

router = APIRouter(tags=["query"])


# ── 请求/响应模型 ──────────────────────────────────
class QueryRequest(BaseModel):
    query: str
    mode: str = "hybrid"
    vlm_enhanced: bool = False
    only_need_context: bool = False
    agent_mode: Optional[str] = None  # "react" | "cot" | None（默认普通模式）
    thread_id: str = ""  # 多轮对话会话 ID，空则单轮模式


class ConversationCreateRequest(BaseModel):
    title: str = "新对话"


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


# ── 查询执行 ──────────────────────────────────────

@router.post("/query")
@limiter.limit("60/minute")
async def query_rag(request: Request, req: QueryRequest, kb: str = Depends(verify_kb_access), current_user: dict = Depends(get_current_user)):
    """执行查询 - 支持普通模式和 Agentic RAG 模式"""
    shared.validate_query_input(req.query)

    # Query cache (skip for agentic mode or explicit refresh)
    refresh = request.query_params.get("refresh", "").lower() == "true"
    agent_mode = req.agent_mode or os.getenv("AGENT_MODE", "none")
    if not refresh and agent_mode == "none":
        try:
            from raganything.query_cache import get_query_cache
            cache = get_query_cache()
            cached = cache.get(req.query)
            if cached:
                cached["cache_hit"] = True
                return JSONResponse(content=cached, headers={"X-Cache": "HIT"})
        except Exception:
            pass

    try:
        start = time.time()
        instance = await shared.get_kb(kb)

        # ── Agentic RAG 模式 ──
        agent_mode = req.agent_mode or os.getenv("AGENT_MODE", "none")
        if agent_mode in ("react", "cot"):
            from raganything.agentic_rag import (
                AgenticRAG, SearchTool, CalculatorTool,
                DatabaseQueryTool, WebSearchTool,
            )
            max_steps = int(os.getenv("AGENT_MAX_STEPS", "5"))

            agentic = AgenticRAG(
                llm_func=instance.llm_model_func,
                max_steps=max_steps,
                mode=agent_mode,
            )
            # 注册 SearchTool（核心工具）
            agentic.register_tool(SearchTool(instance, query_mode=req.mode))
            # 注册 CalculatorTool
            agentic.register_tool(CalculatorTool())
            # 注册 DatabaseQueryTool（预留）
            agentic.register_tool(DatabaseQueryTool(shared.kb_dir(kb)))
            # 注册 WebSearchTool
            agentic.register_tool(WebSearchTool())

            agent_result = await agentic.run(req.query)

            elapsed = round(time.time() - start, 2)
            record = {
                "id": str(uuid.uuid4())[:8],
                "query": req.query,
                "mode": req.mode,
                "agent_mode": agent_mode,
                "answer": agent_result.answer,
                "reasoning_trace": {
                    "steps": [
                        {
                            "step_number": s.step_number,
                            "thought": s.thought,
                            "action": s.action,
                            "action_input": s.action_input,
                            "observation": s.observation,
                            "elapsed_ms": s.elapsed_ms,
                        }
                        for s in agent_result.trace
                    ],
                    "total_steps": agent_result.total_steps,
                    "total_elapsed_ms": agent_result.total_elapsed_ms,
                },
                "images": [],
                "time": datetime.now().isoformat(),
                "elapsed": elapsed,
                "kb": kb,
                "user_id": current_user["id"],
                "username": current_user["username"],
                "thread_id": req.thread_id,
            }
            shared.query_history.insert(0, record)
            if len(shared.query_history) > 100:
                shared.query_history = shared.query_history[:100]
            shared.save_query_history()
            lightrag_logger.info(f"[AGENTIC] mode={agent_mode} steps={agent_result.total_steps} elapsed={elapsed}s")
            return record

        # ── 普通 RAG 模式（原有逻辑）──
        # 多轮对话上下文：获取会话历史
        conv_history_for_rewrite = []
        conversation_context = ""
        active_thread_id = ""

        if req.thread_id and shared.conversation_manager:
            active_thread_id = req.thread_id
            # 确保会话存在（不存在则自动创建）
            thread = await shared.conversation_manager.get_or_create_thread(
                current_user["id"], thread_id=req.thread_id,
                title=req.query[:50],
            )
            if "error" in thread:
                active_thread_id = ""  # 会话超限则降级为单轮
            else:
                active_thread_id = thread["id"]
                conv_history_for_rewrite = (
                    await shared.conversation_manager.get_context_for_rewrite(
                        active_thread_id
                    )
                )
                ctx_result = await shared.conversation_manager.get_context(
                    active_thread_id, req.query
                )
                conversation_context = ctx_result.history_text

        # 查询改写（可选，ENABLE_QUERY_REWRITE=true 开启）
        rewritten_query = req.query
        if os.getenv("ENABLE_QUERY_REWRITE", "false").lower() == "true":
            try:
                from raganything.query import rewrite_query
                rewritten_query = await rewrite_query(
                    req.query, instance.llm_model_func,
                    history=conv_history_for_rewrite if conv_history_for_rewrite else None,
                    api_key=shared.API_KEY, base_url=shared.BASE_URL,
                )
                if rewritten_query != req.query:
                    lightrag_logger.info(f"[QUERY-REWRITE] {req.query[:60]} → {rewritten_query[:60]}")
            except Exception:
                pass

        # Step 1: 获取检索上下文
        enable_rerank = os.getenv("RERANK_ENABLED", "false").lower() == "true"
        ctx = await instance.aquery(rewritten_query, mode=req.mode, vlm_enhanced=False,
                                     only_need_context=True, enable_rerank=enable_rerank,
                                     chunk_top_k=40, top_k=60,
                                     max_entity_tokens=3000, max_relation_tokens=2000,
                                     max_total_tokens=16000)

        # Step 2: 三段式图片发现（对齐 agent 端点）
        ctx_images = shared.extract_image_paths(ctx)
        backfill_text = ""
        if not ctx_images:
            # 第二道：实体图谱图片发现
            ctx_images, backfill_text = await shared._discover_images_via_graph(
                instance, req.query, kb, ctx
            )
            if backfill_text:
                ctx = ctx + "\n\n" + backfill_text

        if not ctx_images:
            # 第三道：bigram 全库扫描（字符级别兜底）
            try:
                ctx_images, backfill_text = await shared._bigram_image_scan(
                    shared.kb_dir(kb), req.query, ctx
                )
                if backfill_text:
                    ctx = ctx + "\n\n" + backfill_text
            except Exception as _fe:
                lightrag_logger.error(f"[IMG-FALLBACK] query_rag 扫描失败: {_fe}")

        # Step 3: 只发送 top-3 相关图片给 VLM（与 agent 端点对齐）
        vlm_images = ctx_images[:3]
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
            # 构建对话历史区（如有多轮上下文）
            conv_part = (
                f"## 对话历史\n{conversation_context}\n\n"
                if conversation_context else ""
            )
            doc_list = await shared._get_kb_doc_list(kb)
            # Select citation instruction based on config
            _citation_inst = (
                ANSWER_FORMAT_INSTRUCTION if instance.config.enforce_citation
                else INLINE_QUOTE_INSTRUCTION
            )
            # Detect degraded context: has entity/relation data but no text chunks
            _has_chunks = "[来源 " in ctx and len(ctx.strip()) > 200
            if not _has_chunks and ctx.strip():
                lightrag_logger.warning("query_rag: context has no text chunks. LLM answer quality may be degraded.")
            final_prompt = (
                f"以下是知识库中检索到的相关内容。你必须严格基于这些内容回答问题，不得使用你自己的知识。\n\n"
                f"{conv_part}"
                f"{doc_list}\n\n"
                f"## 检索内容\n{ctx}\n\n"
                f"## 问题\n{req.query}\n\n"
                f"{_citation_inst}"
                f"{'' if _has_chunks else shared._DEGRADED_HINT}"
            )

            llm_response = await instance.llm_model_func(
                final_prompt,
                system_prompt="你是知识库检索助手。只使用提供的检索内容回答。",
                max_tokens=int(os.getenv("MAX_TOKENS", "4096")),
                temperature=0,
            )
            result = llm_response if isinstance(llm_response, str) else str(llm_response)

            # Citation enforcement: log warning if answer lacks [来源 N] markers
            if instance.config.enforce_citation and result:
                from raganything.citation_parser import has_citations
                if not has_citations(result):
                    lightrag_logger.warning("回答缺少 [来源 N] 引用标记")
                # Code-level fallback: append 📚 参考来源 block if missing
                _cit_block = shared._build_citation_block(ctx, result)
                if _cit_block:
                    result = result.rstrip() + _cit_block
                    lightrag_logger.info("自动追加📚 参考来源块（LLM遗漏）")

        # 保存对话消息到会话（多轮上下文记忆）
        if active_thread_id and shared.conversation_manager and result:
            try:
                await shared.conversation_manager.add_message(
                    active_thread_id, "user", req.query
                )
                await shared.conversation_manager.add_message(
                    active_thread_id, "assistant", result
                )
            except Exception as _conv_err:
                lightrag_logger.error(f"[CONV] 保存消息失败: {_conv_err}")

        # 从VLM回答中提取实际引用的图片
        referenced = []
        if result:
            import re as _re
            refs = _re.findall(r'\[img(\d+)\]', result)
            for idx in set(int(r) for r in refs):
                if 0 <= idx < len(vlm_images):
                    referenced.append(vlm_images[idx])
        # VLM未引用时使用ctx图片（已语义过滤，天然相关）
        image_paths = referenced[:3] if referenced else ctx_images[:3]

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
            "user_id": current_user["id"],
            "username": current_user["username"],
            "thread_id": active_thread_id,
        }
        shared.query_history.insert(0, record)
        if len(shared.query_history) > 100:
            shared.query_history = shared.query_history[:100]
        shared.save_query_history()

        # Save to query cache
        if not refresh and agent_mode == "none":
            try:
                from raganything.query_cache import get_query_cache
                get_query_cache().set(req.query, record)
            except Exception:
                pass

        return JSONResponse(content=record, headers={"X-Cache": "MISS"})
    except Exception as e:
        raise HTTPException(500, str(e))


@router.get("/query/history")
async def get_query_history(limit: int = 20, current_user: dict = Depends(get_current_user)):
    """查询历史（按用户隔离，管理员看全部）"""
    is_admin = current_user.get("is_admin", False)
    if is_admin:
        return {"history": shared.query_history[:limit]}
    filtered = [r for r in shared.query_history if r.get("user_id") == current_user["id"]]
    return {"history": filtered[:limit]}


@router.delete("/query/history")
async def clear_query_history(current_user: dict = Depends(get_current_user)):
    """清空当前用户的查询历史"""
    is_admin = current_user.get("is_admin", False)
    if is_admin:
        count = len(shared.query_history)
        shared.query_history.clear()
    else:
        to_keep = [r for r in shared.query_history if r.get("user_id") != current_user["id"]]
        count = len(shared.query_history) - len(to_keep)
        shared.query_history[:] = to_keep
    shared.save_query_history()
    await shared.add_event("history_cleared", count=count, user_id=current_user["id"])
    return {"status": "cleared", "count": count}


# ── 💬 多轮对话会话管理 ─────────────────────────────────

@router.get("/conversations")
async def list_conversations(current_user: dict = Depends(get_current_user)):
    """列出当前用户的会话列表"""
    if shared.conversation_manager is None:
        return {"conversations": []}
    threads = await shared.conversation_manager.list_threads(current_user["id"])
    return {
        "conversations": [
            {
                "id": t.id,
                "title": t.title,
                "message_count": t.message_count,
                "created_at": t.created_at,
                "updated_at": t.updated_at,
            }
            for t in threads
        ]
    }


@router.post("/conversations")
async def create_conversation(
    req: ConversationCreateRequest,
    current_user: dict = Depends(get_current_user),
):
    """创建新会话"""
    if shared.conversation_manager is None:
        raise HTTPException(500, "ConversationManager 未初始化")
    thread = await shared.conversation_manager.get_or_create_thread(
        current_user["id"], title=req.title,
    )
    if "error" in thread:
        raise HTTPException(400, thread["error"])
    return {
        "thread_id": thread["id"],
        "title": thread["title"],
        "created_at": thread["created_at"],
    }


@router.delete("/conversations/{thread_id}")
async def delete_conversation(
    thread_id: str,
    current_user: dict = Depends(get_current_user),
):
    """删除指定会话（需归属校验）"""
    if shared.conversation_manager is None:
        raise HTTPException(500, "ConversationManager 未初始化")
    # 归属校验
    if not await shared.conversation_manager.thread_exists(thread_id, current_user["id"]):
        raise HTTPException(404, "会话不存在")
    success = await shared.conversation_manager.delete_thread(thread_id)
    if success:
        return {"status": "deleted", "thread_id": thread_id}
    raise HTTPException(404, "会话不存在")


# ── 🔍 流式查询（SSE）─────────────────────────────────
@router.post("/query/stream")
async def query_rag_stream(req: QueryRequest, kb: str = Depends(verify_kb_access), current_user: dict = Depends(get_current_user)):
    """
    流式查询：通过 Server-Sent Events 实时推送思考过程和回答
    事件类型：
      - thinking: 思考步骤（检索、实体匹配、关键词提取等）
      - token: 回答的单个 token
      - done: 查询完成，包含元数据
      - error: 查询出错
    """
    shared.validate_query_input(req.query)
    instance = await shared.get_kb(kb)

    async def event_stream():
        log_queue: queue.Queue = queue.Queue()
        handler = LogCaptureHandler(log_queue)
        lightrag_logger.addHandler(handler)
        query_id = str(uuid.uuid4())[:8]
        full_answer = ""

        try:
            yield f"data: {json.dumps({'type': 'thinking', 'content': f'🔍 开始查询: {req.query[:80]}...'}, ensure_ascii=False)}\n\n"

            start_time = time.time()

            # 多轮对话上下文
            stream_conv_context = ""
            stream_thread_id = ""
            if req.thread_id and shared.conversation_manager:
                stream_thread_id = req.thread_id
                thread = await shared.conversation_manager.get_or_create_thread(
                    current_user["id"], thread_id=req.thread_id,
                    title=req.query[:50],
                )
                if "error" not in thread:
                    stream_thread_id = thread["id"]
                    ctx_result = await shared.conversation_manager.get_context(
                        stream_thread_id, req.query
                    )
                    stream_conv_context = ctx_result.history_text

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
                        if shared._is_thinking_msg(msg):
                            dm = shared._translate_thinking_msg(msg)
                            if dm:
                                yield f"data: {json.dumps({'type': 'thinking', 'content': dm}, ensure_ascii=False)}\n\n"
                    except queue.Empty:
                        break
                await asyncio.sleep(0.06)

            ctx = ctx_task.result()
            # 三段式图片发现（对齐 agent 端点）
            stream_images = shared.extract_image_paths(ctx)
            if not stream_images:
                # 第二道：实体图谱图片发现
                stream_images, backfill_text = await shared._discover_images_via_graph(
                    instance, req.query, kb, ctx
                )
                if backfill_text:
                    ctx = ctx + "\n\n" + backfill_text

            if not stream_images:
                # 第三道：bigram 全库扫描（字符级别兜底）
                try:
                    stream_images, backfill_text = await shared._bigram_image_scan(
                        shared.kb_dir(kb), req.query, ctx
                    )
                    if backfill_text:
                        ctx = ctx + "\n\n" + backfill_text
                except Exception as _fe:
                    lightrag_logger.error(f"[IMG-FALLBACK] query_stream 扫描失败: {_fe}")
            stream_images = stream_images[:3]
            yield f"data: {json.dumps({'type': 'thinking', 'content': f'📋 检索到 {len(ctx)} 字符上下文' + (f'，{len(stream_images)} 张图片' if stream_images else '')}, ensure_ascii=False)}\n\n"
            yield f"data: {json.dumps({'type': 'thinking', 'content': '💬 正在生成回答...'}, ensure_ascii=False)}\n\n"

            # Step 2: 构造 prompt 并流式调用 LLM
            stream_conv_part = (
                f"## 对话历史\n{stream_conv_context}\n\n"
                if stream_conv_context else ""
            )
            stream_doc_list = await shared._get_kb_doc_list(kb)
            _citation_inst = (
                ANSWER_FORMAT_INSTRUCTION if instance.config.enforce_citation
                else INLINE_QUOTE_INSTRUCTION
            )
            # Detect degraded context
            _has_chunks = "[来源 " in ctx and len(ctx.strip()) > 200
            if not _has_chunks and ctx.strip():
                lightrag_logger.warning("query_rag_stream: context has no text chunks.")
            final_prompt = (
                f"以下是知识库检索内容。必须基于这些内容回答，不得使用你自己的知识。\n\n"
                f"{stream_conv_part}"
                f"{stream_doc_list}\n\n"
                f"## 检索内容\n{ctx}\n\n"
                f"## 问题\n{req.query}\n\n"
                f"{_citation_inst}"
                f"{'' if _has_chunks else shared._DEGRADED_HINT}"
            )

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

            # Citation fallback: append 📚 参考来源 block if LLM omitted it
            if instance.config.enforce_citation and full_answer:
                _cit_block = shared._build_citation_block(ctx, full_answer)
                if _cit_block:
                    full_answer += _cit_block
                    yield f"data: {json.dumps({'type': 'token', 'content': _cit_block}, ensure_ascii=False)}\n\n"

            elapsed = round(time.time() - start_time, 2)
            record = {"id": query_id, "query": req.query, "mode": req.mode, "answer": full_answer,
                      "time": datetime.now().isoformat(), "elapsed": elapsed, "kb": kb,
                      "user_id": current_user["id"], "username": current_user["username"],
                      "thread_id": stream_thread_id}
            shared.query_history.insert(0, record)
            if len(shared.query_history) > 100: shared.query_history = shared.query_history[:100]
            shared.save_query_history()
            # 保存对话消息到会话
            if stream_thread_id and shared.conversation_manager and full_answer:
                try:
                    await shared.conversation_manager.add_message(
                        stream_thread_id, "user", req.query
                    )
                    await shared.conversation_manager.add_message(
                        stream_thread_id, "assistant", full_answer
                    )
                except Exception as _conv_err:
                    lightrag_logger.error(f"[CONV-STREAM] 保存消息失败: {_conv_err}")
            yield f"data: {json.dumps({'type': 'done', 'id': query_id, 'elapsed': elapsed, 'images': stream_images, 'thread_id': stream_thread_id}, ensure_ascii=False)}\n\n"

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
