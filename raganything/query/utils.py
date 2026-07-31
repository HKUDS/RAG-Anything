"""
Query functionality for RAGAnything

Contains all query-related methods for both text and multimodal queries
"""

import asyncio
import json
import hashlib
import logging
import re
import time
import uuid
from dataclasses import dataclass, field

import jieba
from datetime import datetime, timezone
from typing import Dict, List, Any
from pathlib import Path
from lightrag import QueryParam
from lightrag.utils import always_get_an_event_loop
from raganything.prompt import PROMPTS, INLINE_QUOTE_INSTRUCTION, ANSWER_FORMAT_INSTRUCTION

# Hint appended to LLM prompt when text chunk resolution fails (chunks=0)
DEGRADED_CONTEXT_HINT = (
    "\n\n⚠️ 注意：本次检索未能获取到关联的文档文本内容（仅获取到实体名称和关系路径），"
    "以下回答可能不够详细。请优先引用实体关系信息，并明确告知用户哪些信息来源自实体名而非原文。"
    "如果信息不足以回答问题，请如实说明。"
)
from raganything.citation_parser import has_citations
from raganything.utils import (
    get_processor_for_type,
    encode_image_to_base64,
    validate_image_file,
)

logger = logging.getLogger(__name__)

async def rerank_chunks(
    query: str,
    chunks: list[str],
    api_key: str = "",
    top_n: int = 10,
    model: str = "qwen3-rerank",
    base_url: str = "https://dashscope.aliyuncs.com/api/v1/services/rerank/text-rerank/text-rerank",
) -> list[tuple[int, str]]:
    """
    使用 DashScope Rerank API 对检索结果进行精排。

    默认使用 qwen3-rerank 模型，通过阿里云 DashScope 原生 rerank API。
    失败时返回原始顺序，不影响主流程。

    Returns:
        [(原始索引, chunk内容), ...] 按相关性降序
    """
    if not chunks or len(chunks) <= 1:
        return [(i, c) for i, c in enumerate(chunks)]

    import aiohttp

    payload = {
        "model": model,
        "input": {
            "query": query,
            "documents": [c[:500] for c in chunks],  # 截断避免超长
        },
        "parameters": {"top_n": min(top_n, len(chunks)), "return_documents": False},
    }

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                base_url,
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                json=payload,
                timeout=aiohttp.ClientTimeout(total=10),
            ) as resp:
                if resp.status != 200:
                    text = await resp.text()
                    raise RuntimeError(f"Rerank API error {resp.status}: {text[:200]}")

                data = await resp.json()
                results = data.get("output", {}).get("results", [])

                # results = [{"index": 2, "relevance_score": 0.77}, ...]
                ranked = []
                seen = set()
                for item in sorted(results, key=lambda x: x.get("relevance_score", 0), reverse=True):
                    idx = item["index"]
                    if idx < len(chunks) and idx not in seen:
                        ranked.append((idx, chunks[idx]))
                        seen.add(idx)

                # 追加未被 rerank 返回的 chunk（排最后）
                for i, c in enumerate(chunks):
                    if i not in seen:
                        ranked.append((i, c))

                return ranked[:top_n]
    except Exception as e:
        logging.getLogger("raganything").warning(f"Rerank failed, using original order: {e}")
        return [(i, c) for i, c in enumerate(chunks)][:top_n]


async def rewrite_query(
    query: str,
    llm_model_func,
    history: list[dict] = None,
    api_key: str = "",
    base_url: str = "",
) -> str:
    """
    查询改写：使用 LLM 将自然语言查询优化为更适合检索的表述。
    支持基于对话历史的上下文改写。

    Returns:
        改写后的查询字符串
    """
    history_context = ""
    if history:
        recent = history[-3:]  # 最近 3 轮
        history_context = "\n".join(
            f"用户: {h.get('content', '')[:100]}" for h in recent if h.get("role") == "user"
        )

    prompt = f"""你是查询优化助手。将用户的自然语言查询改写为更适合文档检索的表述。
规则：
1. 补充省略的上下文（如指代词"这个""它"替换为具体名词）
2. 扩展缩写和专业术语
3. 保持原意，不添加新信息
4. 只输出改写后的查询，不要解释

{"对话历史: " + history_context if history_context else ""}
原始查询: {query}

改写后的查询:"""

    try:
        response = await llm_model_func(
            prompt,
            system_prompt="你是查询优化助手。",
            max_tokens=200,
            temperature=0.3,
        )
        if response and isinstance(response, str) and len(response.strip()) > 2:
            return response.strip()
    except Exception:
        pass
    return query  # 改写失败时返回原查询
