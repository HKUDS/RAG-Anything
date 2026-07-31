"""Agent Router — /api/agents/* and agent query streaming"""

import asyncio
import json
import logging
import os
import queue
import re
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
    _build_citation_block,
    _DEGRADED_HINT,
    _is_thinking_msg,
    _translate_thinking_msg,
    ANSWER_FORMAT_INSTRUCTION,
    API_KEY,
    BASE_URL,
    INLINE_QUOTE_INSTRUCTION,
    LLM_MODEL,
    QUERY_SYSTEM_PROMPT,
    get_kb,
    recall_query_images,
    record_query,
    resolve_controlled_media_payload,
    verify_kb_access,
)
from raganything.utils.security import validate_query_input, decode_and_validate_query_image
from raganything.dependencies import get_current_user, require_permission
from raganything.permissions import Permission

from raganything.services.agent_manager import AgentConfig
from raganything.services.pg_agent_repo import (
    pg_list_agents,
    pg_get_agent,
    pg_create_agent,
    pg_update_agent,
    pg_delete_agent,
    pg_list_conversations,
    pg_get_conversation,
    pg_create_conversation,
    pg_add_message,
    pg_update_message,
    pg_delete_conversation,
    pg_update_conversation,
    pg_get_summary,
    pg_update_summary,
    pg_get_summary_updated_at,
)
from raganything.services.prompt_builder import PromptBuilder, ContextLayer
from raganything.query.tag_scoped_retriever import resolve_tag_scope, retrieve_tag_scoped_context
from raganything.services.kb_service import (
    acquire_query_kb,
    _load_doc_status_json,
    load_kb_meta,
    pg_get_latest_content_updates_batch,
)
from raganything.services.odl_media_delivery import catalog_media_payload
from raganything.services.query_timing import QueryTiming
from raganything.services.query_execution import QueryExecutionScope, await_before_deadline


_SENSITIVE_MEDIA_REFERENCE_PATTERNS = (
    re.compile(r"(?i)data:image/[^\s,;]+;base64,[A-Za-z0-9+/=_-]+"),
    re.compile(r"(?i)file://[^\r\n\s<>\"']+"),
    re.compile(r"(?:[A-Za-z]:[\\/]|\\\\)[^\r\n<>\"']+"),
    re.compile(r"/(?:home|Users|var|tmp|etc|root|opt|mnt)/[^\r\n<>\"']+"),
)


def _consume_background_task_result(task: asyncio.Task) -> None:
    """Observe a detached task after cancellation without blocking cleanup."""
    if task.cancelled():
        return
    try:
        task.exception()
    except asyncio.CancelledError:
        pass


def _cancel_and_observe_task(task: asyncio.Task | None) -> None:
    if task is None or task.done():
        return
    task.cancel()
    task.add_done_callback(_consume_background_task_result)


def _sanitize_client_trace_step(step: dict) -> dict:
    """Keep internal retrieval observations out of SSE and durable history."""
    safe: dict = {}
    for key, value in step.items():
        if key == "observation":
            safe[key] = ""
        elif isinstance(value, str):
            text = value
            for pattern in _SENSITIVE_MEDIA_REFERENCE_PATTERNS:
                text = pattern.sub("[redacted-media-reference]", text)
            safe[key] = text
        else:
            safe[key] = value
    return safe


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
# Prompt builder helpers (deduplicated across modes)
# ═══════════════════════════════════════════════════════════

def _build_image_section(image_description: str = "", similar_image_urls: list = None) -> str:
    """Build image context section string.

    Used by all three modes (RAG/ReAct/CoT) to eliminate the duplicated
    image-description + visual-similar-images concatenation.
    """
    parts = []
    if image_description:
        parts.append(f"## 用户上传图片的视觉描述\n{image_description}\n\n")
    if similar_image_urls:
        parts.append("## 知识库中找到的视觉相似图片\n")
        for si in similar_image_urls[:5]:
            parts.append(
                f"![{si['name']}]({si['url']})\n"
                f"*{si['name']} (视觉相似度: {si['score']})*\n\n"
            )
    return "".join(parts)


async def _load_kb_media_catalog(kb_name: str) -> list[dict]:
    """Load only persisted, path-free catalog records from authorised KB state."""
    try:
        statuses = await _load_doc_status_json(kb_name)
    except Exception:
        statuses = {}
    catalog: list[dict] = []
    for status in statuses.values():
        metadata = status.get("metadata") if isinstance(status, dict) else None
        entries = metadata.get("odl_media_catalog") if isinstance(metadata, dict) else None
        if isinstance(entries, list):
            catalog.extend(entry for entry in entries if isinstance(entry, dict))
    return catalog


async def _controlled_recalled_media(
    kb_name: str, paths: list[str], *, text_chunk_reader=None
) -> list[dict]:
    """Convert backend-only recalled paths into path-free client metadata."""
    result: list[dict] = []
    seen: set[str] = set()
    for path in paths:
        kwargs = {"kb_name": kb_name, "image_path": path}
        if text_chunk_reader is not None:
            kwargs["text_chunk_reader"] = text_chunk_reader
        payload = await resolve_controlled_media_payload(**kwargs)
        media_id = payload.get("media_id") if isinstance(payload, dict) else None
        if isinstance(payload, dict) and isinstance(media_id, str) and media_id not in seen:
            seen.add(media_id)
            result.append(payload)
    return result


async def _controlled_similar_media(
    kb_name: str,
    results: list[dict],
) -> list[dict]:
    """Drop vision matches that are not bound to the KB media catalog."""
    catalog = await _load_kb_media_catalog(kb_name)
    controlled: list[dict] = []
    for result in results:
        if not isinstance(result, dict):
            continue
        payload = catalog_media_payload(
            catalog,
            kb_name=kb_name,
            path=str(result.get("image_path") or ""),
        )
        if payload is None:
            continue
        controlled.append({
            **payload,
            "entity_name": str(result.get("entity_name") or ""),
            "description": str(result.get("description") or ""),
            "score": round(float(result.get("score") or 0), 3),
        })
    return controlled


def _assistant_message_media(
    images: list[dict] | None = None,
    similar_images: list[dict] | None = None,
    image_description: str | None = None,
) -> dict:
    """Persist media fields with assistant messages so conversation reloads keep them."""
    payload: dict = {}
    if images is not None:
        payload["images"] = images
    if similar_images is not None:
        payload["similar_images"] = similar_images
    if image_description:
        payload["image_description"] = image_description
    return payload


def _build_layered_query(
    query: str,
    conv_history_text: str = "",
    image_description: str = "",
    similar_image_urls: list = None,
    summary_text: str = "",
    extra_context: str = "",
    citation_instruction: str = "",
    degraded_hint: str = "",
) -> str:
    """Build a layered prompt string using PromptBuilder.

    Returns the combined prompt body as a single string.
    For modes that need separate system_prompt, use PromptBuilder directly.
    """
    builder = PromptBuilder(max_total_tokens=int(os.getenv("MAX_TOKENS", "8192")))

    img_section = _build_image_section(image_description, similar_image_urls)
    if img_section:
        builder.add_image_context(img_section)

    if summary_text:
        builder.add_summary(summary_text)

    if conv_history_text:
        builder.add_recent_history(conv_history_text)

    if extra_context:
        builder.retrieval_context(extra_context)

    if degraded_hint:
        builder.degraded_hint(degraded_hint)

    builder.user_query(query, citation_instruction)
    prompt, _ = builder.build()
    return prompt


async def _maybe_generate_summary(
    agent_id: str,
    thread_id: str,
    conv_thread: dict | None,
) -> str | None:
    """Trigger conversation summary generation if threshold is met.

    Called after each message exchange. Checks:
    1. CONVERSATION_SUMMARY_ENABLED is true
    2. Message count exceeds CONVERSATION_SUMMARY_TRIGGER_ROUNDS * 2
    3. New messages exist since last summary update

    Returns the new summary text if generated, None otherwise.
    Runs asynchronously — does not block the user response.
    """
    if os.getenv("CONVERSATION_SUMMARY_ENABLED", "true").lower() != "true":
        return None

    trigger_rounds = int(os.getenv("CONVERSATION_SUMMARY_TRIGGER_ROUNDS", "3"))
    trigger_messages = trigger_rounds * 2

    messages = conv_thread.get("messages", []) if conv_thread else []
    if len(messages) <= trigger_messages:
        return None

    # Get last summary update time
    try:
        last_summary_at = await pg_get_summary_updated_at(thread_id)
    except Exception:
        last_summary_at = None

    # If summary exists and no new messages since, skip
    if last_summary_at:
        try:
            from raganything.services.pg_agent_repo import pg_get_messages_since
            new_msgs = await pg_get_messages_since(thread_id, last_summary_at)
        except Exception:
            new_msgs = []
        if len(new_msgs) < trigger_messages:
            return None

    # Generate summary (fire-and-forget)
    existing_summary = None
    try:
        existing_summary = await pg_get_summary(thread_id)
    except Exception:
        pass

    summary_model = os.getenv("CONVERSATION_SUMMARY_LLM_MODEL", LLM_MODEL)
    comp_ratio = float(os.getenv("CONVERSATION_COMPRESSION_RATIO", "0.60"))
    comp_max_retries = int(os.getenv("CONVERSATION_COMPRESSION_MAX_RETRIES", "2"))

    try:
        new_summary = await _call_summary_llm(
            messages=messages,
            existing_summary=existing_summary,
            model=summary_model,
            compression_ratio=comp_ratio,
            max_retries=comp_max_retries,
        )
        if new_summary:
            await pg_update_summary(thread_id, new_summary)
            return new_summary
    except Exception as e:
        lightrag_logger.warning(f"[SUMMARY] Generation failed: {e}")

    return None


async def _call_summary_llm(
    messages: list[dict],
    existing_summary: str | None = None,
    model: str = "qwen-plus",
    compression_ratio: float = 0.60,
    max_retries: int = 2,
) -> str | None:
    """Call LLM to generate or update conversation summary with compression ratio guarantee.

    After LLM returns, computes compression_ratio = 1 - len(summary)/len(transcript).
    If the ratio falls below the target, retries with progressively stricter compression
    instructions (up to max_retries times). On total failure, returns the best attempt.

    Args:
        messages: Full message list for the thread.
        existing_summary: Previous summary (for incremental update).
        model: LLM model to use.
        compression_ratio: Target compression ratio (default 0.60 = 60%).
        max_retries: Maximum retry attempts if compression ratio not met (default 2).

    Returns:
        Summary string, or None on failure.
    """
    # Build the conversation transcript
    transcript_lines = []
    for msg in messages:
        role_label = "用户" if msg.get("role") == "user" else "助手"
        content = (msg.get("content", "") or "")[:500]
        transcript_lines.append(f"{role_label}: {content}")
    transcript = "\n".join(transcript_lines)
    transcript_len = len(transcript)

    # Base prompt (same as before)
    if existing_summary:
        base_prompt = (
            "你是一个对话摘要助手。下面是已有的对话摘要和新增的对话内容。"
            "请将新增内容融入已有摘要，生成更新后的摘要。"
            "保持 2-5 句话，只总结事实和关键结论，不添加新信息，不编造内容。\n\n"
            f"## 已有摘要\n{existing_summary}\n\n"
            f"## 完整对话记录\n{transcript}\n\n"
            "## 更新后的摘要"
        )
    else:
        base_prompt = (
            "你是一个对话摘要助手。请用 2-5 句话总结以下对话的核心内容和关键结论。"
            "只总结事实，不添加新信息，不编造内容。使用对话中使用的语言回复。\n\n"
            f"## 对话记录\n{transcript}\n\n"
            "## 摘要"
        )

    # Progressive retry hints for stronger compression
    retry_hints = [
        "\n\n请大幅压缩摘要，目标是将原始对话压缩至 40% 以下长度。只保留最关键的事实和结论。",
        "\n\n极限压缩模式：每条信息不超过 10 个字，只输出核心结论。",
    ]

    best_summary = None
    best_ratio = float('-inf')  # ensure any real ratio (even negative) is captured
    total_attempts = max(1, max_retries + 1)  # guarantee at least 1 attempt

    for attempt in range(total_attempts):
        prompt = base_prompt
        if attempt > 0:
            hint_idx = min(attempt - 1, len(retry_hints) - 1)
            prompt += retry_hints[hint_idx]

        try:
            response = await openai_complete_if_cache(
                model,
                prompt,
                system_prompt="你是一个精确的对话摘要助手。只输出摘要文本，不加前缀或标记。",
                api_key=API_KEY,
                base_url=BASE_URL,
                max_tokens=500,
                temperature=0.3,
                stream=False,
            )
        except Exception as e:
            lightrag_logger.warning(
                f"[SUMMARY-COMPRESSION] LLM call failed (attempt {attempt+1}/{total_attempts}): {e}"
            )
            continue

        if not response or len(response.strip()) <= 10:
            continue

        summary = response.strip()
        summary_len = len(summary)
        ratio = 1.0 - (summary_len / max(transcript_len, 1))
        passed = ratio >= compression_ratio

        lightrag_logger.info(
            f"[SUMMARY-COMPRESSION] input_chars={transcript_len}, "
            f"output_chars={summary_len}, ratio={ratio:.1%}, "
            f"attempt={attempt+1}/{total_attempts}, pass={str(passed).lower()}"
        )

        if passed:
            return summary

        # Track best result for graceful degradation
        if ratio > best_ratio:
            best_ratio = ratio
            best_summary = summary

    # All retries exhausted — graceful degradation
    if best_summary:
        lightrag_logger.warning(
            f"[SUMMARY-COMPRESSION] All retries exhausted. "
            f"Best ratio: {best_ratio:.1%}, accepting degraded result."
        )

    return best_summary


# ═══════════════════════════════════════════════════════════════
# Pydantic Models
# ═══════════════════════════════════════════════════════════════

class AgentCreateRequest(BaseModel):
    name: str = "新智能体"
    icon: str = "🤖"
    description: str = ""
    kb_name: str = "default"
    llm_model: str = "qwen-plus"
    temperature: float = 0.0
    max_response_tokens: int = 4096
    query_mode: str = "hybrid"
    agent_mode: str = "none"  # "none" | "react" | "cot"
    retrieval_top_k: int = 40
    chunk_top_k: int = 20
    enable_rerank: bool = False
    include_references: bool = True
    system_prompt: str = ""
    use_default_prompt: bool = True
    welcome_message: Optional[str] = None
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
    chunk_top_k: Optional[int] = None
    enable_rerank: Optional[bool] = None
    include_references: Optional[bool] = None
    system_prompt: Optional[str] = None
    use_default_prompt: Optional[bool] = None
    welcome_message: Optional[str] = None
    template_id: Optional[str] = None


class AgentQueryRequest(BaseModel):
    query: str
    thread_id: str = ""  # 关联的对话线程 ID
    mode: str = ""  # 空则使用智能体默认模式
    agent_mode: Optional[str] = None  # 空则使用智能体默认的 agent_mode
    vlm_enhanced: bool = False
    image: Optional[str] = None  # base64 data URI of user-uploaded query image (e.g. data:image/jpeg;base64,...)
    tag_id: Optional[int] = None
    retrieval_only: bool = False  # 受权限保护的评测诊断：不暴露上下文正文，也不触发生成


class MessageUpdateRequest(BaseModel):
    content: str  # 新的消息内容（Markdown，≤10000 字符）


# Agent config helpers
# ═══════════════════════════════════════════════════════════
_AGENT_INT_BOUNDS = {
    "max_response_tokens": (512, 16384, 4096),
    "retrieval_top_k": (5, 200, 40),
    "chunk_top_k": (1, 100, 20),
}

_AGENT_BOOL_DEFAULTS = {
    "enable_rerank": False,
    "include_references": True,
    "use_default_prompt": True,
}


def _bounded_agent_int(field: str, value: object) -> int:
    minimum, maximum, default = _AGENT_INT_BOUNDS[field]
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = default
    return max(minimum, min(maximum, parsed))


def _agent_bool(field: str, value: object) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return _AGENT_BOOL_DEFAULTS[field]
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return bool(value)


def _normalise_agent_config_values(values: dict) -> dict:
    normalised = dict(values)
    for field in _AGENT_INT_BOUNDS:
        if field in normalised:
            normalised[field] = _bounded_agent_int(field, normalised[field])
    for field in _AGENT_BOOL_DEFAULTS:
        if field in normalised:
            normalised[field] = _agent_bool(field, normalised[field])
    return normalised


def _agent_runtime_config(agent: dict) -> dict:
    return _normalise_agent_config_values({
        "max_response_tokens": agent.get("max_response_tokens", 4096),
        "retrieval_top_k": agent.get("retrieval_top_k", 40),
        "chunk_top_k": agent.get("chunk_top_k", 20),
        "enable_rerank": agent.get("enable_rerank", False),
        "include_references": agent.get("include_references", True),
    })


def _build_agent_system_prompt(agent: dict) -> str:
    system_prompt = (agent.get("system_prompt") or "").strip()
    if agent.get("use_default_prompt", True):
        parts = [part for part in (system_prompt, QUERY_SYSTEM_PROMPT) if part]
        return "\n\n".join(parts).strip()
    return system_prompt


def _build_effective_agent_runtime(agent: dict, req: AgentQueryRequest) -> dict:
    query_mode = req.mode or agent.get("query_mode") or "hybrid"
    agent_mode = req.agent_mode or agent.get("agent_mode", "none")
    runtime_config = _agent_runtime_config(agent)
    runtime_config.update({
        "llm_model": agent.get("llm_model") or LLM_MODEL,
        "temperature": float(agent.get("temperature", 0.0) or 0.0),
        "system_prompt": _build_agent_system_prompt(agent),
        "query_mode": query_mode,
        "agent_mode": agent_mode,
        # Agentic paths should honor the saved/default retrieval mode when available.
        "agentic_query_mode": req.mode or agent.get("query_mode") or "rrf",
    })
    return runtime_config


async def _query_cache_scope(
    kb: str,
    user_id: int,
    settings_fingerprint: str,
    llm_profile_fingerprint: str,
) -> dict[str, str]:
    updates = await pg_get_latest_content_updates_batch([kb])
    corpus_revision = updates.get(kb)
    if not corpus_revision:
        try:
            metadata = (await load_kb_meta()).get(kb, {})
            corpus_revision = str(
                metadata.get("updated_at")
                or metadata.get("created")
                or metadata.get("created_at")
                or "empty"
            )
        except Exception:
            corpus_revision = "unknown"
    return {
        "workspace": kb,
        "permission_scope": f"user:{user_id}",
        "corpus_revision": str(corpus_revision),
        "settings_fingerprint": settings_fingerprint,
        "llm_profile_fingerprint": llm_profile_fingerprint,
    }


def _build_agent_llm(runtime_config: dict, selected_llm=None):
    async def _agent_llm(
        prompt: str,
        system_prompt: Optional[str] = None,
        history_messages: Optional[list[dict]] = None,
        **kwargs,
    ):
        call_kwargs = dict(kwargs)
        max_tokens = call_kwargs.pop("max_tokens", runtime_config["max_response_tokens"])
        call_kwargs.pop("temperature", None)
        stream = call_kwargs.pop("stream", False)
        if selected_llm is not None:
            return await selected_llm(
                prompt,
                system_prompt=runtime_config["system_prompt"] if system_prompt is None else system_prompt,
                history_messages=history_messages or [],
                max_tokens=max_tokens,
                temperature=runtime_config["temperature"],
                stream=stream,
                **call_kwargs,
            )
        return await openai_complete_if_cache(
            runtime_config["llm_model"],
            prompt,
            system_prompt=runtime_config["system_prompt"] if system_prompt is None else system_prompt,
            history_messages=history_messages or [],
            api_key=API_KEY,
            base_url=BASE_URL,
            max_tokens=max_tokens,
            temperature=runtime_config["temperature"],
            stream=stream,
            **call_kwargs,
        )

    return _agent_llm

# Router
# ═══════════════════════════════════════════════════════════

router = APIRouter(tags=["agents"])


# ── 智能体 CRUD ─────────────────────────────────────

@router.get("/agents")
async def list_agents(
    current_user: dict = Depends(get_current_user),
    _perm: None = Depends(require_permission(Permission.AGENT_READ)),
):
    """列出智能体（按用户隔离，管理员看全部）"""
    agents = await pg_list_agents(
        user_id=current_user["id"],
        is_admin=current_user.get("is_admin", False),
    )
    return {
        "agents": agents,
        "total": len(agents),
    }


@router.get("/agents/templates")
async def get_agent_templates(
    current_user: dict = Depends(get_current_user),
    _perm: None = Depends(require_permission(Permission.AGENT_READ)),
):
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
async def create_agent(
    req: AgentCreateRequest,
    current_user: dict = Depends(get_current_user),
    _perm: None = Depends(require_permission(Permission.AGENT_WRITE)),
):
    """创建新智能体"""
    # 验证 KB 访问权限
    await verify_kb_access(kb=req.kb_name, current_user=current_user)
    config = AgentConfig(
        name=req.name,
        icon=req.icon,
        description=req.description,
        welcome_message=req.welcome_message if req.welcome_message is not None else "",
        kb_name=req.kb_name,
        llm_model=req.llm_model,
        temperature=req.temperature,
        max_response_tokens=_bounded_agent_int("max_response_tokens", req.max_response_tokens),
        query_mode=req.query_mode,
        agent_mode=req.agent_mode,
        retrieval_top_k=_bounded_agent_int("retrieval_top_k", req.retrieval_top_k),
        chunk_top_k=_bounded_agent_int("chunk_top_k", req.chunk_top_k),
        enable_rerank=_agent_bool("enable_rerank", req.enable_rerank),
        include_references=_agent_bool("include_references", req.include_references),
        system_prompt=req.system_prompt,
        use_default_prompt=req.use_default_prompt,
        template_id=req.template_id,
    )
    agent = await pg_create_agent(
        config.model_dump(),
        owner_id=current_user["id"],
        owner_username=current_user["username"],
    )
    return {"status": "ok", "agent": agent}


@router.put("/agents/{agent_id}")
async def update_agent(
    agent_id: str, req: AgentUpdateRequest,
    current_user: dict = Depends(get_current_user),
    _perm: None = Depends(require_permission(Permission.AGENT_WRITE)),
):
    """更新智能体配置（仅所有者或管理员）"""
    agent = await pg_get_agent(agent_id)
    if not agent:
        raise HTTPException(404, "智能体不存在")
    is_admin = current_user.get("is_admin", False)
    if agent.get("owner_id", 0) != 0 and agent.get("owner_id") != current_user["id"] and not is_admin:
        raise HTTPException(403, "无权修改该智能体")
    raw_updates = req.model_dump(exclude_unset=True)
    if "kb_name" in raw_updates:
        await verify_kb_access(kb=raw_updates["kb_name"], current_user=current_user)
    updates = _normalise_agent_config_values(
        {k: v for k, v in raw_updates.items() if v is not None}
    )
    agent = await pg_update_agent(agent_id, updates)
    if not agent:
        raise HTTPException(404, "智能体不存在")
    return {"status": "ok", "agent": agent}


@router.delete("/agents/{agent_id}")
async def delete_agent(
    agent_id: str,
    current_user: dict = Depends(get_current_user),
    _perm: None = Depends(require_permission(Permission.AGENT_DELETE)),
):
    """删除智能体（仅所有者或管理员）"""
    agent = await pg_get_agent(agent_id)
    if not agent:
        raise HTTPException(404, "智能体不存在")
    is_admin = current_user.get("is_admin", False)
    if agent.get("owner_id", 0) != 0 and agent.get("owner_id") != current_user["id"] and not is_admin:
        raise HTTPException(403, "无权删除该智能体")
    if not await pg_delete_agent(agent_id):
        raise HTTPException(404, "智能体不存在")
    return {"status": "ok"}


# ── 对话线程 CRUD ──────────────────────────────────

@router.get("/agents/{agent_id}/conversations")
async def list_conversations(agent_id: str, current_user: dict = Depends(get_current_user),
    _perm: None = Depends(require_permission(Permission.AGENT_READ)),
):
    """列出智能体的对话线程（按用户隔离，管理员看全部）"""
    agent = await pg_get_agent(agent_id)
    if not agent:
        raise HTTPException(404, "智能体不存在")
    is_admin = current_user.get("is_admin", False)
    if agent.get("owner_id", 0) != 0 and agent.get("owner_id") != current_user["id"] and not is_admin:
        raise HTTPException(403, "无权访问该智能体")
    threads = await pg_list_conversations(
        agent_id,
        user_id=current_user["id"],
        is_admin=current_user.get("is_admin", False),
    )
    return {
        "threads": threads,
        "total": len(threads),
    }


@router.get("/agents/{agent_id}/conversations/{thread_id}")
async def get_conversation(
    agent_id: str,
    thread_id: str,
    current_user: dict = Depends(get_current_user),
    _perm: None = Depends(require_permission(Permission.AGENT_READ)),
):
    """获取单个对话线程（含完整消息列表，每条消息带 msg_id）"""
    agent = await pg_get_agent(agent_id)
    if not agent:
        raise HTTPException(404, "智能体不存在")
    is_admin = current_user.get("is_admin", False)
    if agent.get("owner_id", 0) != 0 and agent.get("owner_id") != current_user["id"] and not is_admin:
        raise HTTPException(403, "无权访问该智能体")
    thread = await pg_get_conversation(agent_id, thread_id)
    if not thread:
        raise HTTPException(404, "对话线程不存在")
    if thread.get("owner_id", 0) != 0 and thread.get("owner_id") != current_user["id"] and not is_admin:
        raise HTTPException(403, "无权访问该对话")
    return {"thread": thread}


@router.post("/agents/{agent_id}/conversations")
async def create_conversation(agent_id: str, title: str = "新对话", current_user: dict = Depends(get_current_user),
    _perm: None = Depends(require_permission(Permission.AGENT_WRITE)),
):
    """创建新对话线程（注入所有权，需校验 Agent 所有权）"""
    agent = await pg_get_agent(agent_id)
    if not agent:
        raise HTTPException(404, "智能体不存在")
    is_admin = current_user.get("is_admin", False)
    if agent.get("owner_id", 0) != 0 and agent.get("owner_id") != current_user["id"] and not is_admin:
        raise HTTPException(403, "无权使用该智能体")
    thread = await pg_create_conversation(agent_id, title, owner_id=current_user["id"])
    return {"status": "ok", "thread": thread}


@router.put("/agents/{agent_id}/conversations/{thread_id}")
async def update_conversation(agent_id: str, thread_id: str, title: str = None, current_user: dict = Depends(get_current_user),
    _perm: None = Depends(require_permission(Permission.AGENT_WRITE)),
):
    """更新对话线程（需校验 Agent 所有权 + 对话所有权）"""
    agent = await pg_get_agent(agent_id)
    if not agent:
        raise HTTPException(404, "智能体不存在")
    is_admin = current_user.get("is_admin", False)
    if agent.get("owner_id", 0) != 0 and agent.get("owner_id") != current_user["id"] and not is_admin:
        raise HTTPException(403, "无权访问该智能体")
    thread = await pg_get_conversation(agent_id, thread_id)
    if not thread:
        raise HTTPException(404, "对话线程不存在")
    if thread.get("owner_id", 0) != 0 and thread.get("owner_id") != current_user["id"] and not is_admin:
        raise HTTPException(403, "无权修改该对话")
    thread = await pg_update_conversation(agent_id, thread_id, {"title": title})
    return {"status": "ok", "thread": thread}


@router.delete("/agents/{agent_id}/conversations/{thread_id}")
async def delete_conversation(agent_id: str, thread_id: str, current_user: dict = Depends(get_current_user),
    _perm: None = Depends(require_permission(Permission.AGENT_DELETE)),
):
    """删除对话线程（需校验 Agent 所有权 + 对话所有权）"""
    agent = await pg_get_agent(agent_id)
    if not agent:
        raise HTTPException(404, "智能体不存在")
    is_admin = current_user.get("is_admin", False)
    if agent.get("owner_id", 0) != 0 and agent.get("owner_id") != current_user["id"] and not is_admin:
        raise HTTPException(403, "无权访问该智能体")
    thread = await pg_get_conversation(agent_id, thread_id)
    if not thread:
        raise HTTPException(404, "对话线程不存在")
    if thread.get("owner_id", 0) != 0 and thread.get("owner_id") != current_user["id"] and not is_admin:
        raise HTTPException(403, "无权删除该对话")
    if not await pg_delete_conversation(agent_id, thread_id):
        raise HTTPException(404, "对话线程不存在")
    return {"status": "ok"}


# ── ✏️ 消息编辑 ──────────────────────────────────────


@router.put("/agents/{agent_id}/conversations/{thread_id}/messages/{message_id}")
async def update_message(
    agent_id: str,
    thread_id: str,
    message_id: int,
    req: MessageUpdateRequest,
    current_user: dict = Depends(get_current_user),
    _perm: None = Depends(require_permission(Permission.AGENT_WRITE)),
):
    """编辑对话中的单条消息（仅 conversation owner 或 admin）"""
    # 权限：仅 conversation owner 或 admin 可编辑
    is_admin = current_user.get("is_admin", False)

    # 验证 agent 存在 + 所有权
    agent = await pg_get_agent(agent_id)
    if not agent:
        raise HTTPException(404, "智能体不存在")
    if agent.get("owner_id", 0) != 0 and agent.get("owner_id") != current_user["id"] and not is_admin:
        raise HTTPException(403, "无权修改该智能体的消息")

    # 验证 thread 存在 + 所有权
    thread = await pg_get_conversation(agent_id, thread_id)
    if not thread:
        raise HTTPException(404, "对话线程不存在")
    if thread.get("owner_id", 0) != 0 and thread.get("owner_id") != current_user["id"] and not is_admin:
        raise HTTPException(403, "无权修改该对话的消息")

    # 输入校验
    if not req.content or not req.content.strip():
        raise HTTPException(422, "消息内容不能为空")
    if len(req.content) > 10000:
        raise HTTPException(422, "消息内容不能超过 10000 字符")

    # 更新消息
    try:
        result = await pg_update_message(thread_id, message_id, req.content)
    except ValueError as e:
        raise HTTPException(422, str(e))

    if not result:
        raise HTTPException(404, "消息不存在")

    return {"status": "ok", "message": result}


# ── 🔍 智能查询（智能体增强）─────────────────────────────

@router.post("/agents/{agent_id}/query/stream")
async def agent_query_stream(agent_id: str, req: AgentQueryRequest, request: Request, current_user: dict = Depends(get_current_user),
    _perm: None = Depends(require_permission(Permission.AGENT_READ)),
):
    """智能体流式查询：使用智能体配置执行查询"""
    query_id = str(uuid.uuid4())[:8]
    timing = QueryTiming(query_id)
    timing.start("settings_quota")
    agent = await pg_get_agent(agent_id)
    if not agent:
        timing.total(outcome="error")
        raise HTTPException(404, "智能体不存在")

    # 验证 Agent 所有权（非所有者/管理员不可用）
    is_admin = current_user.get("is_admin", False)
    if agent.get("owner_id", 0) != 0 and agent.get("owner_id") != current_user["id"] and not is_admin:
        timing.total(outcome="error")
        raise HTTPException(403, "无权使用该智能体")
    # 输入校验 — Prompt Injection 防护
    # 当用户仅发送图片而无文字时，自动补全安全占位查询文本，
    # 确保 validate_query_input 始终有内容可校验，同时让下游
    # SSE / VLM / 历史记录等 20+ 处 req.query 引用获得一致的默认值。
    if (not req.query or not req.query.strip()) and req.image:
        req.query = "请分析这张图片"
    try:
        validate_query_input(req.query, user_id=str(current_user.get("id", "anonymous")))
    except Exception:
        timing.total(outcome="error")
        raise
    # 验证 KB 访问权限（可能自动切换到用户的个人 KB）
    try:
        actual_kb = await verify_kb_access(
            kb=agent.get("kb_name", ""), current_user=current_user
        )
    except asyncio.CancelledError:
        timing.total(outcome="cancelled")
        raise
    except Exception:
        timing.total(outcome="error")
        raise

    from raganything.services import vision_models
    try:
        from raganything.services.user_settings import resolve_user_settings_for_task
        resolved_settings = await resolve_user_settings_for_task(
            int(current_user["id"])
        )
        # Text-only questions must not depend on the optional image model.
        # Requiring VLM here made every KB question fail with 503 when only
        # the text model was configured or the image provider was unavailable.
        vlm_snapshot = (
            vision_models.require_available(
                resolved_settings.models.vlm_profile_id, "vlm"
            )
            if req.image
            else None
        )
        llm_snapshot = vision_models.require_available(
            resolved_settings.models.llm_profile_id, "llm"
        )
        query_scope = await _query_cache_scope(
            actual_kb,
            int(current_user["id"]),
            resolved_settings.fingerprint,
            llm_snapshot.fingerprint,
        )
        selected_llm = vision_models.build_llm_callable(
            resolved_settings.models.llm_profile_id,
            cache_scope=json.dumps(
                query_scope, sort_keys=True, separators=(",", ":"), ensure_ascii=True
            ),
            timeout=resolved_settings.runtime.llm_timeout,
        )
    except (KeyError, RuntimeError, ValueError) as exc:
        timing.total(outcome="error")
        raise HTTPException(503, detail={"code": "profile_unavailable", "message": "selected model or personal settings are unavailable"}) from exc
    tag_scope = None
    if req.tag_id is not None:
        tag_scope = await resolve_tag_scope(actual_kb, req.tag_id)
        if tag_scope is None:
            # Do not reveal whether a tag exists in a different knowledge base.
            timing.total(outcome="error")
            raise HTTPException(422, "Selected tag scope is no longer available")
    scope_metadata = {"tag_scope": {"id": tag_scope.tag_id, "name": tag_scope.tag_name}} if tag_scope else {}
    runtime_config = _build_effective_agent_runtime(agent, req)
    if req.retrieval_only and runtime_config["agent_mode"] != "none":
        timing.total(outcome="error")
        raise HTTPException(
            status_code=422,
            detail="retrieval_only only supports the standard RAG query mode",
        )
    from raganything.services.user_settings import (
        acquire_quota_lease,
        get_platform_settings,
        heartbeat_quota_lease,
        release_quota_lease,
    )
    try:
        platform_settings = await get_platform_settings()
        limits = ((platform_settings.get("settings") or {}).get("limits") or {})
        interactive_wait = float(limits.get("interactive_wait_seconds", 0))
        outer_caps = [
            int(limits[name]) for name in ("provider_concurrency", "worker_concurrency")
            if isinstance(limits.get(name), (int, float)) and limits[name] > 0
        ]
        outer_limit = min(outer_caps) if outer_caps else None
    except Exception as exc:
        timing.total(outcome="error")
        raise HTTPException(
            503,
            detail={"code": "quota_settings_unavailable", "message": "runtime limits are unavailable"},
        ) from exc
    retrieval_timeout = max(0.1, float(os.getenv("AGENT_RETRIEVAL_TIMEOUT", "8")))
    retrieval_deadline = time.monotonic() + retrieval_timeout
    lease_owner = f"interactive:{os.getpid()}:{uuid.uuid4()}"
    lease_id = None
    deadline = time.monotonic() + max(0.0, interactive_wait)
    while lease_id is None:
        lease_id = await acquire_quota_lease(
            int(current_user["id"]),
            lease_owner.rsplit(":", 1)[-1],
            lease_owner,
            resolved_settings.runtime.personal_concurrency,
            outer_limit=outer_limit,
        )
        if lease_id is None:
            if time.monotonic() >= deadline:
                timing.total(outcome="timeout")
                raise HTTPException(
                    429,
                    detail={"code": "personal_concurrency_exceeded", "message": "personal concurrency quota is full"},
                )
            await asyncio.sleep(min(0.1, max(0.0, deadline - time.monotonic())))

    timing.finish("settings_quota")
    # The request may have waited for a quota lease while the corpus changed.
    # Refresh the authoritative revision before selecting a query core or cache key.
    try:
        query_scope = await _query_cache_scope(
            actual_kb,
            int(current_user["id"]),
            resolved_settings.fingerprint,
            llm_snapshot.fingerprint,
        )
        selected_llm = vision_models.build_llm_callable(
            resolved_settings.models.llm_profile_id,
            cache_scope=json.dumps(
                query_scope, sort_keys=True, separators=(",", ":"), ensure_ascii=True
            ),
            timeout=resolved_settings.runtime.llm_timeout,
        )
    except (KeyError, RuntimeError, ValueError) as exc:
        await release_quota_lease(lease_id, lease_owner)
        timing.total(outcome="error")
        raise HTTPException(
            503,
            detail={"code": "profile_unavailable", "message": "selected model or personal settings are unavailable"},
        ) from exc

    async def _release_interactive_lease() -> None:
        try:
            await release_quota_lease(lease_id, lease_owner)
        except Exception:
            lightrag_logger.warning("Interactive quota release failed", exc_info=True)

    stream_task: asyncio.Task | None = None

    async def _heartbeat_interactive_lease() -> None:
        while True:
            await asyncio.sleep(15)
            if not await heartbeat_quota_lease(lease_id, lease_owner):
                if stream_task is not None:
                    stream_task.cancel()
                return

    # Start the heartbeat only once Starlette begins consuming the stream.  A
    # response object that is created but never sent must expire naturally,
    # rather than retaining a background heartbeat forever.
    lease_heartbeat_task: asyncio.Task | None = None
    # 检索模式（agentic 路径优先 rrf 轻量模式，可被请求级覆盖；普通路径沿用 agent 配置）
    query_mode = runtime_config["query_mode"]
    # Every search mode receives immutable, user-scoped retrieval options.
    # Hybrid is the normal default, so limiting this to RRF would silently
    # fall back to shared defaults for most requests.
    user_retrieval_options = resolved_settings.retrieval
    # 推理模式：请求级覆盖 > 智能体配置 > 默认 none
    agent_mode = runtime_config["agent_mode"]
    # AgenticRAG 专用检索模式：优先请求级，否则默认 rrf（更快）
    agentic_query_mode = runtime_config["agentic_query_mode"]
    max_response_tokens = runtime_config["max_response_tokens"]
    retrieval_top_k = runtime_config["retrieval_top_k"]
    chunk_top_k = runtime_config["chunk_top_k"]
    enable_rerank = runtime_config["enable_rerank"]
    include_references = runtime_config["include_references"]
    system_prompt = runtime_config["system_prompt"]
    agent_llm = _build_agent_llm(runtime_config, selected_llm)

    # 确保对话线程存在
    thread_id = req.thread_id
    if not thread_id and not req.retrieval_only:
        try:
            thread = await pg_create_conversation(
                agent_id, title="新对话", owner_id=current_user["id"]
            )
        except Exception:
            await _release_interactive_lease()
            timing.total(outcome="error")
            raise
        thread_id = thread["id"]

    # ── 多轮对话上下文提取 ──
    conv_history_text = ""
    max_conv_rounds = int(os.getenv("CONVERSATION_MAX_ROUNDS", "10"))
    max_conv_tokens = int(os.getenv("CONVERSATION_MAX_TOKENS", "2000"))
    conv_thread = None
    if not req.retrieval_only:
        try:
            conv_thread = await pg_get_conversation(agent_id, thread_id)
        except Exception:
            await _release_interactive_lease()
            timing.total(outcome="error")
            raise
    if conv_thread and conv_thread.get("messages"):
        max_msgs = max_conv_rounds * 2
        recent = conv_thread["messages"][-max_msgs:]
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

    instance = None

    async def event_stream():
        nonlocal lease_heartbeat_task, instance, stream_task
        stream_task = asyncio.current_task()
        lease_heartbeat_task = asyncio.create_task(_heartbeat_interactive_lease())
        ctx_task: asyncio.Task | None = None
        vlm_context_token = (
            vision_models.activate_vlm_selection(
                vlm_snapshot,
                cache_scope=json.dumps(query_scope, sort_keys=True, separators=(",", ":"), ensure_ascii=True),
            )
            if vlm_snapshot is not None
            else None
        )
        llm_context_token = vision_models.activate_llm_selection(
            llm_snapshot,
            cache_scope=json.dumps(query_scope, sort_keys=True, separators=(",", ":"), ensure_ascii=True),
            timeout=resolved_settings.runtime.llm_timeout,
            profile_id=resolved_settings.models.llm_profile_id,
        )
        log_queue: queue.Queue = queue.Queue()
        handler = LogCaptureHandler(log_queue)
        lightrag_logger.addHandler(handler)
        query_kb_lease = None
        full_answer = ""
        timing_outcome = "ok"

        try:
            timing.start("query_core_acquire")
            query_kb_lease = await await_before_deadline(
                acquire_query_kb(
                    actual_kb,
                    corpus_revision=query_scope.get("corpus_revision"),
                ),
                retrieval_deadline,
                cancel_on_timeout=False,
            )
            instance = query_kb_lease.instance
            timing.finish(
                "query_core_acquire",
                cache_status=getattr(query_kb_lease, "cache_status", "na"),
            )
            execution_scope = QueryExecutionScope(
                trace_id=query_id,
                workspace=query_scope.get("workspace", actual_kb),
                corpus_revision=(
                    lease_key.corpus_revision
                    if (lease_key := getattr(query_kb_lease, "key", None)) is not None
                    else query_scope.get("corpus_revision", "unknown")
                ),
                permission_scope=query_scope.get("permission_scope", "unknown"),
                settings_fingerprint=query_scope.get("settings_fingerprint", "unknown"),
                llm_profile_fingerprint=query_scope.get("llm_profile_fingerprint", "unknown"),
                deadline_monotonic=retrieval_deadline,
            )
            scope_payload = ({"id": tag_scope.tag_id, "name": tag_scope.tag_name} if tag_scope else None)
            yield f"data: {json.dumps({'type': 'agent_info', 'agent': agent.get('name',''), 'icon': agent.get('icon',''), 'thread_id': thread_id, 'tag_scope': scope_payload}, ensure_ascii=False)}\n\n"
            yield f"data: {json.dumps({'type': 'thinking', 'content': f'🔍 开始查询: {req.query[:80]}...'}, ensure_ascii=False)}\n\n"

            # ── 查询改写：基于对话历史消解指代词 ──
            rewritten_query = req.query
            if conv_history_text and os.getenv("REWRITE_QUERY_ENABLED", "true").lower() == "true":
                try:
                    from raganything.query.utils import rewrite_query
                    _history = [
                        {"role": m.get("role"), "content": m.get("content", "")}
                        for m in (conv_thread["messages"][-6:] if conv_thread and conv_thread.get("messages") else [])
                    ]
                    rewritten = await await_before_deadline(
                        rewrite_query(
                            req.query,
                            selected_llm,
                            history=_history,
                        ),
                        retrieval_deadline,
                    )
                    if rewritten and rewritten != req.query and len(rewritten.strip()) > 2:
                        lightrag_logger.info("[QUERY-REWRITE] trace_id=%s outcome=rewritten", query_id)
                        rewritten_query = rewritten
                        yield f"data: {json.dumps({'type': 'thinking', 'content': f'📝 查询已结合对话历史改写: {rewritten[:100]}'}, ensure_ascii=False)}\n\n"
                except TimeoutError:
                    lightrag_logger.warning(
                        "[QUERY-REWRITE] trace_id=%s phase=rewrite outcome=timeout",
                        query_id,
                    )
                except Exception:
                    lightrag_logger.warning(
                        "[QUERY-REWRITE] trace_id=%s phase=rewrite outcome=error",
                        query_id,
                    )

            # ═══ Image Processing (user-uploaded query image) ═══
            image_description = None
            similar_images = []
            _similar_image_urls: list[dict] = []
            if req.image and tag_scope is None:
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
                    try:
                        _vlm_res, _vis_res = await await_before_deadline(
                            asyncio.gather(vlm_task, vision_task, return_exceptions=True),
                            retrieval_deadline,
                        )
                    except TimeoutError:
                        _cancel_and_observe_task(vlm_task)
                        _cancel_and_observe_task(vision_task)
                        _vlm_res, _vis_res = None, []

                    image_description = _vlm_res if not isinstance(_vlm_res, Exception) else None
                    raw_similar_images = _vis_res if not isinstance(_vis_res, Exception) else []
                    similar_images = await _controlled_similar_media(
                        actual_kb, raw_similar_images
                    )
                    _similar_image_urls = similar_images

                    _status_fields = {"status": "done"}
                    if image_description:
                        _status_fields["description_preview"] = image_description[:100]
                    if similar_images:
                        _status_fields["similar_count"] = len(similar_images)
                    yield f"data: {json.dumps({'type': 'image_analysis', **_status_fields}, ensure_ascii=False)}\n\n"
                    # Emit similar image URLs for frontend rendering
                    if _similar_image_urls:
                        yield f"data: {json.dumps({'type': 'image_results', 'images': _similar_image_urls}, ensure_ascii=False)}\n\n"
            _display_similar_images = _similar_image_urls

            # ═══ AgenticRAG 推理路径（ReAct / CoT） ═══
            if agent_mode in ("react", "cot"):
                start_time = time.time()
                from raganything.agentic_rag import AgenticRAG, SearchTool

                async def _timed_agent_llm(*args, **kwargs):
                    """Observe agentic model calls without retaining their content."""
                    started = time.perf_counter()
                    outcome = "ok"
                    try:
                        response = await agent_llm(*args, **kwargs)
                        if response is None:
                            outcome = "error"
                        else:
                            elapsed = time.perf_counter() - started
                            # AgenticRAG uses non-streaming model calls, so the
                            # response arrival is both the first and last token.
                            timing.record("llm_first_token", elapsed)
                            timing.record("llm_last_token", elapsed)
                        return response
                    except asyncio.CancelledError:
                        outcome = "cancelled"
                        raise
                    except Exception:
                        outcome = "error"
                        raise
                    finally:
                        timing.record(
                            "llm", time.perf_counter() - started, outcome=outcome
                        )

                agentic = AgenticRAG(
                    llm_func=_timed_agent_llm,
                    max_steps=int(os.getenv("AGENT_MAX_STEPS", "5")),
                    mode=agent_mode,
                    max_response_tokens=max_response_tokens,
                    system_prompt_override=system_prompt,
                )
                agentic.register_tool(SearchTool(
                    instance,
                    query_mode=agentic_query_mode,
                    top_k=retrieval_top_k,
                    chunk_top_k=chunk_top_k,
                    enable_rerank=enable_rerank,
                    include_references=include_references,
                    tag_scope=tag_scope,
                    retrieval_options=user_retrieval_options,
                    query_execution_scope=execution_scope,
                ))

                full_answer = ""
                trace_steps = []

                if agent_mode == "react":
                    # ReAct 流式路径 — 通过 PromptBuilder 注入分层上下文
                    react_query = _build_layered_query(
                        rewritten_query,
                        conv_history_text=conv_history_text,
                        image_description=image_description,
                        similar_image_urls=_similar_image_urls,
                    )
                    if tag_scope is not None:
                        react_retrieval_outcome = "ok"
                        timing.start("retrieval")
                        try:
                            scoped_context = await retrieve_tag_scoped_context(
                                instance, tag_scope, rewritten_query,
                                top_k=chunk_top_k, max_total_tokens=8000,
                                deadline_monotonic=retrieval_deadline,
                            )
                        except TimeoutError:
                            react_retrieval_outcome = "timeout"
                            scoped_context = ""
                        except asyncio.CancelledError:
                            react_retrieval_outcome = "cancelled"
                            raise
                        except Exception:
                            react_retrieval_outcome = "error"
                            raise
                        finally:
                            timing.finish(
                                "retrieval", outcome=react_retrieval_outcome
                            )
                        react_query += (
                            f"\n\n## 硬性检索范围\n仅可依据标签“{tag_scope.tag_name}”下的内容回答。"
                            f"\n{scoped_context or '该标签范围内没有可用内容。请明确说明无法在此范围内作答。'}"
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
                            safe_sd = _sanitize_client_trace_step(sd)
                            yield f"data: {json.dumps({'type': 'thinking', **safe_sd}, ensure_ascii=False)}\n\n"
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
                    _cot_search_query = rewritten_query
                    if image_description:
                        _cot_search_query = f"{rewritten_query}\n\n[图片描述]\n{image_description[:500]}"
                    cot_context = ""
                    retrieval_outcome = "ok"
                    timing.start("retrieval")
                    try:
                        if tag_scope is not None:
                            cot_context = await retrieve_tag_scoped_context(
                                instance, tag_scope, _cot_search_query,
                                top_k=chunk_top_k, max_total_tokens=8000,
                                deadline_monotonic=retrieval_deadline,
                            )
                        else:
                            cot_context = await await_before_deadline(
                                instance.aquery(
                                    _cot_search_query, mode=agentic_query_mode, only_need_context=True,
                                    top_k=retrieval_top_k, chunk_top_k=chunk_top_k,
                                    enable_rerank=enable_rerank,
                                    include_references=include_references,
                                    retrieval_options=user_retrieval_options,
                                    query_execution_scope=execution_scope,
                                    max_total_tokens=8000,
                                ),
                                retrieval_deadline,
                            ) or ""
                    except TimeoutError:
                        retrieval_outcome = "timeout"
                    except asyncio.CancelledError:
                        retrieval_outcome = "cancelled"
                        raise
                    except Exception:
                        retrieval_outcome = "error"
                        pass
                    finally:
                        timing.finish("retrieval", outcome=retrieval_outcome)
                    # Build image + history context via unified helpers
                    _img_cot_ctx = _build_image_section(image_description, _similar_image_urls)
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
                        timing.start("persistence")
                        await pg_add_message(agent_id, thread_id, {
                            "role": "user", "content": req.query,
                            "time": datetime.now().isoformat(),
                            **scope_metadata,
                        })
                        await pg_add_message(agent_id, thread_id, {
                            "role": "assistant", "content": full_answer,
                            "elapsed": elapsed, "mode": query_mode,
                            "agent_mode": agent_mode, "trace": [],
                            "fallback": True,
                            "time": datetime.now().isoformat(),
                            **scope_metadata,
                            **_assistant_message_media([], _display_similar_images, image_description),
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
                        timing.finish("persistence")
                        _done_cot_empty = {'type': 'done', 'id': query_id, 'elapsed': elapsed, 'thread_id': thread_id, 'images': [], 'fallback': True}
                        if image_description:
                            _done_cot_empty['image_description'] = image_description
                        if _display_similar_images:
                            _done_cot_empty['similar_images'] = _display_similar_images
                        yield f"data: {json.dumps(_done_cot_empty, ensure_ascii=False)}\n\n"
                        return
                    # 对话历史已在 line 527-530 注入到 _img_cot_ctx，此处不重复注入
                    agent_result = await agentic.run_with_context(rewritten_query, cot_context)
                    full_answer = agent_result.answer
                    for s in agent_result.trace:
                        trace_steps.append({
                            "step": s.step_number,
                            "thought": s.thought,
                            "elapsed_ms": s.elapsed_ms,
                        })
                        safe_step = _sanitize_client_trace_step(trace_steps[-1])
                        yield f"data: {json.dumps({'type': 'thinking', **safe_step}, ensure_ascii=False)}\n\n"
                    yield f"data: {json.dumps({'type': 'token', 'content': full_answer}, ensure_ascii=False)}\n\n"

                elapsed = round(time.time() - start_time, 2)
                lightrag_logger.info(f"[AGENT-STREAM] mode={agent_mode} steps={len(trace_steps)} elapsed={elapsed}s")
                client_trace_steps = [_sanitize_client_trace_step(step) for step in trace_steps]

                # ── 图片匹配（图谱发现 + bigram 兜底）──
                # 从 ReAct search observation 和 CoT 检索上下文中提取图片路径
                all_retrieved_text = ""
                for ts in trace_steps:
                    if ts.get("observation"):
                        all_retrieved_text += ts["observation"] + "\n"
                if agent_mode == "cot" and cot_context:
                    all_retrieved_text += cot_context + "\n"
                all_retrieved_text += " " + rewritten_query
                all_retrieved_text += " " + full_answer

                timing.start("media")
                try:
                    async def _recall_agentic_media():
                        recalled, backfill, source = await recall_query_images(
                            instance, req.query, actual_kb, all_retrieved_text
                        )
                        controlled = await _controlled_recalled_media(
                            actual_kb,
                            recalled[:3],
                            text_chunk_reader=getattr(
                                getattr(instance, "lightrag", None),
                                "text_chunks",
                                None,
                            ),
                        )
                        return controlled, backfill, source

                    agent_images, _backfill_text_react, _img_source = (
                        await await_before_deadline(
                            _recall_agentic_media(), retrieval_deadline
                        )
                    )
                except TimeoutError:
                    agent_images, _backfill_text_react, _img_source = [], "", None
                    timing.finish("media", outcome="timeout")
                except asyncio.CancelledError:
                    timing.finish("media", outcome="cancelled")
                    raise
                except Exception:
                    timing.finish("media", outcome="error")
                    raise
                else:
                    timing.finish("media")
                if _backfill_text_react:
                    all_retrieved_text += "\n" + _backfill_text_react

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
                if include_references and instance.config.enforce_citation and full_answer and _agent_ctx:
                    _cit_block = _build_citation_block(_agent_ctx, full_answer)
                    if _cit_block:
                        full_answer += _cit_block
                        yield f"data: {json.dumps({'type': 'token', 'content': _cit_block}, ensure_ascii=False)}\n\n"

                # 保存到对话线程
                timing.start("persistence")
                await pg_add_message(agent_id, thread_id, {
                    "role": "user", "content": req.query,
                    "time": datetime.now().isoformat(),
                    **scope_metadata,
                })
                await pg_add_message(agent_id, thread_id, {
                    "role": "assistant", "content": full_answer,
                    "elapsed": elapsed, "mode": query_mode,
                    "agent_mode": agent_mode, "trace": client_trace_steps,
                    "time": datetime.now().isoformat(),
                    **scope_metadata,
                    **_assistant_message_media(agent_images, _display_similar_images, image_description),
                })

                # 记录全局查询历史
                record = {
                    "id": query_id, "query": req.query, "mode": query_mode,
                    "agent_mode": agent_mode, "answer": full_answer,
                    "reasoning_trace": {"steps": client_trace_steps, "total_steps": len(client_trace_steps)},
                    "images": agent_images, "time": datetime.now().isoformat(),
                    "elapsed": elapsed, "kb": actual_kb,
                    "agent_id": agent_id, "thread_id": thread_id,
                    "user_id": current_user["id"], "username": current_user["username"],
                }
                await record_query(record, max_history=100)
                timing.finish("persistence")

                # Trigger summary generation (fire-and-forget)
                try:
                    _full_agentic_thread = await pg_get_conversation(agent_id, thread_id)
                    asyncio.create_task(_maybe_generate_summary(agent_id, thread_id, _full_agentic_thread))
                except Exception:
                    pass

                _done_agentic = {'type': 'done', 'id': query_id, 'elapsed': elapsed, 'thread_id': thread_id, 'images': agent_images}
                if image_description:
                    _done_agentic['image_description'] = image_description
                if _display_similar_images:
                    _done_agentic['similar_images'] = _display_similar_images
                yield f"data: {json.dumps(_done_agentic, ensure_ascii=False)}\n\n"
                return

            # ═══ 普通 RAG 流式路径（agent_mode=none） ═══
            start_time = time.time()

            # Step 1: 获取检索上下文
            # 对标 CoT 路径 — 用 VLM 描述 + 视觉相似实体富化检索查询，
            # 确保图片语义能够命中知识库中的相关文本块。
            _search_query = rewritten_query
            _vis_context_parts: list[str] = []
            if image_description:
                _vis_context_parts.append(f"[图片描述]\n{image_description[:500]}")
            if similar_images:
                _en = [si['entity_name'] for si in similar_images if si.get('entity_name')]
                if _en:
                    _vis_context_parts.append(f"[视觉相似实体]\n{' '.join(_en[:5])}")
                # 注入视觉相似图片的描述作为语义锚点（这些描述来自文档处理时的 VLM，
                # 比实体名更精确地表达图片内容，能显著提升文本检索召回率）
                _vis_descs = [si['description'][:200] for si in similar_images if si.get('description')]
                if _vis_descs:
                    _vis_context_parts.append(f"[相似图片描述]\n{' | '.join(_vis_descs[:3])}")
            if _vis_context_parts:
                _search_query = f"{rewritten_query}\n\n" + "\n".join(_vis_context_parts)
            timing.start("retrieval")
            if tag_scope is not None:
                ctx_task = asyncio.ensure_future(
                    retrieve_tag_scoped_context(
                        instance, tag_scope, _search_query,
                        top_k=chunk_top_k, max_total_tokens=16000,
                        deadline_monotonic=retrieval_deadline,
                    )
                )
            else:
                ctx_task = asyncio.ensure_future(
                    instance.aquery(_search_query, mode=query_mode, vlm_enhanced=False,
                                    only_need_context=True, enable_rerank=enable_rerank,
                                    chunk_top_k=chunk_top_k, top_k=retrieval_top_k,
                                    include_references=include_references,
                                    retrieval_options=user_retrieval_options,
                                    query_execution_scope=execution_scope,
                                    max_entity_tokens=3000, max_relation_tokens=2000,
                                    max_total_tokens=16000)
                )
            while not ctx_task.done():
                is_disconnected = getattr(request, "is_disconnected", None)
                if is_disconnected is not None:
                    try:
                        if await is_disconnected():
                            raise asyncio.CancelledError
                    except RuntimeError:
                        # Unit-test and internal Request scopes may not expose
                        # an ASGI receive channel; they are not disconnects.
                        pass
                if asyncio.get_running_loop().time() >= retrieval_deadline:
                    timed_out_task, ctx_task = ctx_task, None
                    _cancel_and_observe_task(timed_out_task)
                    raise TimeoutError("知识库检索超时，请重试。")
                while True:
                    try:
                        msg = log_queue.get_nowait()
                        if _is_thinking_msg(msg):
                            dm = _translate_thinking_msg(msg)
                            if dm:
                                yield f"data: {json.dumps({'type': 'thinking', 'content': dm}, ensure_ascii=False)}\n\n"
                    except queue.Empty:
                        break
                remaining = retrieval_deadline - asyncio.get_running_loop().time()
                await asyncio.sleep(min(0.06, max(0.001, remaining)))

            ctx = ctx_task.result()
            timing.finish("retrieval")

            # ── 快速检测：真正空的上下文（fail_response / None / 空字符串）──
            _is_truly_empty = not ctx or not ctx.strip() or "[no-context]" in ctx

            if req.retrieval_only:
                # Keep the diagnostic contract metadata-only. Retrieval text is never
                # sent to the client, persisted to conversations, or added to history.
                context_chars = len(ctx) if isinstance(ctx, str) else 0
                source_count = ctx.count("[来源 ") if isinstance(ctx, str) else 0
                elapsed = round(time.time() - start_time, 2)
                yield f"data: {json.dumps({'type': 'retrieval', 'context_present': not _is_truly_empty, 'context_chars': context_chars, 'text_source_count': source_count, 'mode': query_mode}, ensure_ascii=False)}\n\n"
                yield f"data: {json.dumps({'type': 'done', 'id': query_id, 'elapsed': elapsed, 'phase': 'retrieval', 'fallback': _is_truly_empty}, ensure_ascii=False)}\n\n"
                return

            if _is_truly_empty:
                # ── 降级路径：无有效检索上下文 → 直接告知用户 ──
                agent_images = []
                yield f"data: {json.dumps({'type': 'thinking', 'content': '⚠️ 知识库中暂无相关数据'}, ensure_ascii=False)}\n\n"
                full_answer = "抱歉，知识库中暂无与您问题相关的数据，无法回答此问题。请尝试上传相关文档或换个问题。"

                # 保存到对话线程
                timing.start("persistence")
                await pg_add_message(agent_id, thread_id, {
                    "role": "user",
                    "content": req.query,
                    "time": datetime.now().isoformat(),
                    **scope_metadata,
                })
                await pg_add_message(agent_id, thread_id, {
                    "role": "assistant",
                    "content": full_answer,
                    "elapsed": round(time.time() - start_time, 2),
                    "mode": query_mode,
                    "fallback": True,
                    "time": datetime.now().isoformat(),
                    **scope_metadata,
                    **_assistant_message_media(agent_images, _display_similar_images, image_description),
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
                timing.finish("persistence")

                yield f"data: {json.dumps({'type': 'token', 'content': full_answer}, ensure_ascii=False)}\n\n"
                _done_data = {
                    'type': 'done', 'id': query_id,
                    'elapsed': round(time.time() - start_time, 2),
                    'thread_id': thread_id, 'images': agent_images,
                    'fallback': True,
                }
                if image_description:
                    _done_data['image_description'] = image_description
                if _display_similar_images:
                    _done_data['similar_images'] = _display_similar_images
                yield f"data: {json.dumps(_done_data, ensure_ascii=False)}\n\n"
                # 提前返回，不走到下方的通用 LLM 调用路径
                return

            # ── 图片提取（所有查询模式统一，三段式）──
            timing.start("media")
            async def _recall_controlled_media():
                recalled, backfill, source = await recall_query_images(
                    instance, req.query, actual_kb, ctx
                )
                controlled = await _controlled_recalled_media(
                    actual_kb, recalled[:3],
                    text_chunk_reader=getattr(getattr(instance, "lightrag", None), "text_chunks", None),
                )
                return controlled, backfill, source

            try:
                agent_images, backfill_text, _img_source = await await_before_deadline(
                    _recall_controlled_media(), retrieval_deadline
                )
            except TimeoutError:
                agent_images, backfill_text, _img_source = [], "", None
                timing.finish("media", outcome="timeout")
            else:
                timing.finish("media")
            if backfill_text:
                ctx = ctx + "\n\n" + backfill_text

            # ── 截断 + 文件存在性校验（安全网）──
            agent_images = agent_images[:3]

            # ── 视觉相似图片上下文注入 ──
            # 将视觉搜索找到的相似图片描述注入 LLM 上下文。
            # 这些描述来自文档处理时的 VLM，语义密度远高于纯文本检索。
            # 独立于三段式图片发现，即使图谱/扫描找到图，视觉描述仍有增量价值。
            if similar_images:
                _vis_snippets: list[str] = []
                for _si in similar_images:
                    _desc = _si.get("description", "")
                    _name = _si.get("entity_name", "")
                    _score = _si.get("score", 0)
                    if _desc:
                        _vis_snippets.append(
                            f"[视觉相似 {_score:.0%}] {_name}: {_desc[:300]}"
                        )
                if _vis_snippets:
                    _vis_ctx = "[视觉增强上下文] 以下来自知识库中视觉相似的图片描述：\n" + "\n".join(_vis_snippets[:5])
                    ctx = _vis_ctx + "\n\n" + (ctx or "")
                    lightrag_logger.info(
                        "[IMG-FUSION] 注入 %d 条视觉相似描述 (共 %d 字符)",
                        len(_vis_snippets[:5]), len(_vis_ctx),
                    )

            # ── 最终空上下文检测（使用富化后的 ctx）──
            is_fallback = _is_empty_context(ctx)

            if is_fallback:
                # ── 回填后仍为空 → 降级告知用户 ──
                yield f"data: {json.dumps({'type': 'thinking', 'content': '⚠️ 知识库中暂无相关数据'}, ensure_ascii=False)}\n\n"
                full_answer = "抱歉，知识库中暂无与您问题相关的数据，无法回答此问题。请尝试上传相关文档或换个问题。"

                # 保存到对话线程
                timing.start("persistence")
                await pg_add_message(agent_id, thread_id, {
                    "role": "user",
                    "content": req.query,
                    "time": datetime.now().isoformat(),
                    **scope_metadata,
                })
                await pg_add_message(agent_id, thread_id, {
                    "role": "assistant",
                    "content": full_answer,
                    "elapsed": round(time.time() - start_time, 2),
                    "mode": query_mode,
                    "fallback": True,
                    "time": datetime.now().isoformat(),
                    **scope_metadata,
                    **_assistant_message_media(agent_images, _display_similar_images, image_description),
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
                timing.finish("persistence")

                yield f"data: {json.dumps({'type': 'token', 'content': full_answer}, ensure_ascii=False)}\n\n"
                _done_data = {
                    'type': 'done', 'id': query_id,
                    'elapsed': round(time.time() - start_time, 2),
                    'thread_id': thread_id, 'images': agent_images,
                    'fallback': True,
                }
                if image_description:
                    _done_data['image_description'] = image_description
                if _display_similar_images:
                    _done_data['similar_images'] = _display_similar_images
                yield f"data: {json.dumps(_done_data, ensure_ascii=False)}\n\n"
                return

            # ── 正常路径：使用富化后的上下文 ──
            _ctx_think_msg = '📋 检索到 {} 字符上下文'.format(len(ctx))
            if agent_images:
                _ctx_think_msg += '，{} 张图片'.format(len(agent_images))
            yield f"data: {json.dumps({'type': 'thinking', 'content': _ctx_think_msg}, ensure_ascii=False)}\n\n"
            yield f"data: {json.dumps({'type': 'thinking', 'content': '💬 正在生成回答...'}, ensure_ascii=False)}\n\n"

            # Step 2: 使用 PromptBuilder 构造分层 prompt
            sp = system_prompt
            # Select citation instruction based on config (same as non-agent endpoints)
            if include_references:
                _cit_inst = (
                    ANSWER_FORMAT_INSTRUCTION if instance.config.enforce_citation
                    else INLINE_QUOTE_INSTRUCTION
                )
            else:
                _cit_inst = ""
            # Detect degraded context (text chunks exist but may be thin).
            _has_chunks = (
                ("[来源 " in ctx and len(ctx.strip()) > 200)          # RRF pipeline
                or bool(backfill_text)                                 # image backfill
                or ('"reference_id"' in ctx and '"content"' in ctx)    # native LightRAG
            )
            if not _has_chunks and ctx.strip():
                lightrag_logger.warning("agent_query_stream: context has no text chunks.")

            # Build RAG-mode image context (uses graph-discovered similar_images, not auth URLs)
            _img_section = ""
            if image_description:
                _img_section += f"## 用户上传图片的视觉分析\n{image_description}\n\n"
            if similar_images:
                _img_section += "## 知识库中视觉相似的图片\n"
                for _si in similar_images[:5]:
                    label = _si.get("entity_name") or _si.get("caption") or "catalog image"
                    _img_section += f"- {label} (相似度: {_si['score']})\n"
                    if _si.get('description'):
                        _img_section += f"  描述: {_si['description'][:200]}\n"
                _img_section += "\n"

            # Use PromptBuilder for layered prompt construction
            _pb = PromptBuilder(max_total_tokens=int(os.getenv("MAX_TOKENS", "8192")))
            if _img_section:
                _pb.add_context_layer(ContextLayer(
                    name="image_context", content=_img_section,
                    priority=25, max_tokens=2000, enabled=True, label="",
                ))
            if conv_history_text:
                _pb.add_recent_history(conv_history_text)
            _pb.retrieval_context(ctx)
            _pb.degraded_hint("" if _has_chunks else _DEGRADED_HINT)
            _pb.user_query(req.query, _cit_inst)
            final_prompt, _final_sp = _pb.build()
            timing.start("llm")
            llm_started = time.perf_counter()
            llm_response = await agent_llm(
                prompt=final_prompt,
                system_prompt=sp,
                max_tokens=max_response_tokens,
                temperature=runtime_config["temperature"],
                stream=True,
            )

            if llm_response is None:
                timing.finish("llm", outcome="error")
                timing_outcome = "error"
                yield f"data: {json.dumps({'type': 'error', 'content': '模型返回空'}, ensure_ascii=False)}\n\n"
                return
            if isinstance(llm_response, str):
                full_answer = llm_response
                timing.record("llm_first_token", time.perf_counter() - llm_started)
                yield f"data: {json.dumps({'type': 'token', 'content': llm_response}, ensure_ascii=False)}\n\n"
            else:
                _stream_tokens = []
                try:
                    async for token in llm_response:
                        if not _stream_tokens:
                            timing.record("llm_first_token", time.perf_counter() - llm_started)
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

            timing.finish("llm")
            timing.record("llm_last_token", time.perf_counter() - llm_started)
            elapsed = round(time.time() - start_time, 2)

            # 保存到对话线程
            timing.start("persistence")
            await pg_add_message(agent_id, thread_id, {
                "role": "user",
                "content": req.query,
                "time": datetime.now().isoformat(),
                **scope_metadata,
            })
            await pg_add_message(agent_id, thread_id, {
                "role": "assistant",
                "content": full_answer,
                "elapsed": elapsed,
                "mode": query_mode,
                "fallback": is_fallback,
                "time": datetime.now().isoformat(),
                **scope_metadata,
                **_assistant_message_media(agent_images, _display_similar_images, image_description),
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
            timing.finish("persistence")

            # Trigger summary generation if threshold met (fire-and-forget)
            # Load full thread for message count check
            try:
                _full_thread = await pg_get_conversation(agent_id, thread_id)
                asyncio.create_task(_maybe_generate_summary(agent_id, thread_id, _full_thread))
            except Exception:
                pass

            _done_data = {
                'type': 'done', 'id': query_id, 'elapsed': elapsed,
                'thread_id': thread_id, 'images': agent_images,
            }
            if is_fallback:
                _done_data['fallback'] = True
            if image_description:
                _done_data['image_description'] = image_description
            if _display_similar_images:
                _done_data['similar_images'] = _display_similar_images
            yield f"data: {json.dumps(_done_data, ensure_ascii=False)}\n\n"

        except asyncio.CancelledError:
            timing_outcome = "cancelled"
            raise
        except TimeoutError as exc:
            timing_outcome = "timeout"
            yield f"data: {json.dumps({'type': 'error', 'content': str(exc)}, ensure_ascii=False)}\n\n"
        except Exception as exc:
            timing_outcome = "error"
            yield f"data: {json.dumps({'type': 'error', 'content': str(exc)}, ensure_ascii=False)}\n\n"
        finally:
            _cancel_and_observe_task(ctx_task)
            if vlm_context_token is not None:
                vision_models.reset_vlm_snapshot(vlm_context_token)
            vision_models.reset_llm_snapshot(llm_context_token)
            lightrag_logger.removeHandler(handler)
            if query_kb_lease is not None:
                await query_kb_lease.release()
            if lease_heartbeat_task is not None:
                lease_heartbeat_task.cancel()
                try:
                    await lease_heartbeat_task
                except asyncio.CancelledError:
                    pass
                except Exception:
                    lightrag_logger.warning("Interactive quota heartbeat failed", exc_info=True)
            await _release_interactive_lease()
            timing.total(outcome=timing_outcome)

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
