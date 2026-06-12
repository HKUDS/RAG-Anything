"""
文本问答引擎 — 基于 AgenticRAG 多步推理 + RAG-Anything 检索。

核心流程:
1. 用户输入查询
2. AgenticRAG ReAct 循环：自主检索 → 推理 → 检索 → ... → 最终回答
3. 后处理：三级图片匹配 + 引用溯源 + 置信度评估
4. 返回 AgentResponse（含推理轨迹 trace）
"""

import inspect
import logging
import re
import time
import asyncio
from typing import Callable, Optional

import jieba

from .source_tracer import SourceTracer
from ..knowledge_graph.models import AgentResponse

logger = logging.getLogger(__name__)


def _encode_image_data_url(image_path: str) -> str | None:
    """将图片文件编码为 base64 data URL。"""
    import base64
    import os
    if not image_path or not os.path.isfile(image_path):
        return None
    try:
        ext = os.path.splitext(image_path)[1].lower()
        mime_map = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
                    ".gif": "image/gif", ".webp": "image/webp", ".bmp": "image/bmp"}
        mime = mime_map.get(ext, "image/png")
        with open(image_path, "rb") as f:
            b64 = base64.b64encode(f.read()).decode("utf-8")
        # 限制大小：超过 2MB 的图片跳过
        if len(b64) > 2 * 1024 * 1024:
            logger.warning(f"Image too large ({len(b64)} bytes), skipping: {image_path}")
            return None
        return f"data:{mime};base64,{b64}"
    except Exception as e:
        logger.warning(f"Failed to encode image {image_path}: {e}")
        return None


# 制造领域专用 ReAct system prompt
MFG_SYSTEM_PROMPT = (
    "你是一位智能制造领域的教学专家，具备多步推理能力。"
    "你可以使用工具来获取知识库中的工艺参数、故障案例、赛题标准等信息，然后逐步推理得出最终答案。"
    "回答必须基于工具返回的实际文档内容，不要编造制造参数和工艺信息。"
    "每个关键陈述需要标注来源编号，如 [来源 1]。"
)


class QAEngine:
    """智能制造领域文本问答引擎 — 基于 AgenticRAG 多步推理。"""

    def __init__(self, rag_client=None, llm_client=None,
                 top_k: int = 10, citation_required: bool = True,
                 image_paths: list = None,
                 query_mode: str = "rrf",
                 max_steps: int = 3):
        """
        Args:
            rag_client: RAG-Anything 检索客户端（用于 SearchTool）
            llm_client: LLM 生成客户端（兼容旧接口，用于构建 llm_func）
            top_k: 检索返回数量
            citation_required: 是否强制要求引用来源
            image_paths: 文档中提取的图片路径列表
                         [(path, page_idx), ...] 或 [(path, page_idx, caption), ...]
            query_mode: SearchTool 检索模式，默认 "rrf"
            max_steps: AgenticRAG 最大推理步数，默认 3
        """
        self.rag_client = rag_client
        self.llm_client = llm_client
        self.top_k = top_k
        self.citation_required = citation_required
        self.source_tracer = SourceTracer()
        self._llm_adapter = self._resolve_llm_adapter(llm_client)
        self.image_paths = image_paths or []  # [(path, page_idx, caption?), ...]
        self._query_mode = query_mode
        self._max_steps = max_steps

        # Build caption lookup map for keyword matching
        self._image_captions: dict[str, str] = {}
        for item in self.image_paths:
            if len(item) >= 3 and item[2]:
                self._image_captions[item[0]] = str(item[2])

        # ── 构建 AgenticRAG 实例 ──
        self._agentic_rag = None
        if llm_client is not None:
            self._init_agentic_rag()

    def _init_agentic_rag(self):
        """初始化 AgenticRAG 实例并注册 SearchTool。"""
        from raganything.agentic_rag import AgenticRAG, SearchTool

        # 用 llm_adapter 包装为 AgenticRAG 需要的 async llm_func
        llm_adapter = self._llm_adapter

        async def llm_func(prompt, system_prompt=None, history_messages=None, **kw):
            # AgenticRAG 传入的是 ReAct 格式的消息列表
            if history_messages:
                conversation = (
                    [{"role": "system", "content": system_prompt}] if system_prompt else []
                ) + history_messages + [{"role": "user", "content": prompt}]

                # 拼接为单个 prompt 调用兼容的 adapter
                full_prompt = "\n\n".join(
                    f"[{m['role']}]: {m['content']}" for m in conversation
                )
                result = llm_adapter(full_prompt)
                if inspect.isawaitable(result):
                    result = await result
                return result if isinstance(result, str) else str(result)

            # 简单调用
            full = f"System: {system_prompt}\n\nUser: {prompt}" if system_prompt else prompt
            result = llm_adapter(full)
            if inspect.isawaitable(result):
                result = await result
            return result if isinstance(result, str) else str(result)

        self._agentic_rag = AgenticRAG(
            llm_func=llm_func,
            max_steps=self._max_steps,
            mode="react",
            system_prompt_override=MFG_SYSTEM_PROMPT,
        )

        # 注册 SearchTool
        if self.rag_client is not None:
            search_tool = SearchTool(
                rag_instance=self.rag_client,
                query_mode=self._query_mode,
            )
            self._agentic_rag.register_tool(search_tool)

    @staticmethod
    def _resolve_llm_adapter(client) -> Optional[Callable]:
        """解析 LLM 客户端接口，返回统一的 `generate(prompt) -> str` 可调用对象。"""
        if client is None:
            return None
        # Anthropic SDK
        if hasattr(client, 'messages') and hasattr(client.messages, 'create'):
            def adapter(prompt: str) -> str:
                resp = client.messages.create(
                    model=getattr(client, 'model', 'claude-sonnet-4-6'),
                    max_tokens=4096,
                    messages=[{"role": "user", "content": prompt}],
                )
                return resp.content[0].text
            return adapter
        # OpenAI SDK
        if hasattr(client, 'chat') and hasattr(client.chat, 'completions'):
            def adapter(prompt: str) -> str:
                resp = client.chat.completions.create(
                    model=getattr(client, 'model_name', 'gpt-4'),
                    messages=[{"role": "user", "content": prompt}],
                )
                return resp.choices[0].message.content
            return adapter
        # Generic: has generate method
        if hasattr(client, 'generate') and callable(client.generate):
            return client.generate
        # Generic: callable itself
        if callable(client):
            return client
        raise TypeError(
            f"llm_client 类型 {type(client)} 不支持。"
            "请传入 Anthropic SDK、OpenAI SDK、或实现了 generate(prompt) -> str 的对象"
        )

    async def answer(self, query: str,
                     context: Optional[dict] = None) -> AgentResponse:
        """执行文本问答（异步）— AgenticRAG 多步推理。

        Args:
            query: 用户问题
            context: 上下文限定（如赛项 track、知识库范围）

        Returns:
            AgentResponse with answer, citations, related_images, trace, confidence
        """
        start_time = time.time()
        context = context or {}

        # Step 1: AgenticRAG 多步推理
        if self._agentic_rag is not None:
            try:
                agent_result = await self._agentic_rag.run(query)
                answer_text = agent_result.answer
                # 转换推理轨迹
                trace = [
                    {
                        "step": s.step_number,
                        "thought": s.thought,
                        "action": s.action,
                        "observation": s.observation,
                        "elapsed_ms": s.elapsed_ms,
                    }
                    for s in agent_result.trace
                ]
                total_steps = agent_result.total_steps
            except Exception as e:
                logger.error(f"AgenticRAG 推理失败: {e}")
                return AgentResponse(
                    query=query,
                    answer=f"推理过程出错: {e}",
                    citations=[],
                    confidence=0.0,
                    processing_time_ms=round((time.time() - start_time) * 1000, 2),
                )
        else:
            # 降级：无 LLM 时返回提示
            return AgentResponse(
                query=query,
                answer="LLM 服务未配置，无法执行推理。",
                citations=[],
                confidence=0.0,
                processing_time_ms=round((time.time() - start_time) * 1000, 2),
                needs_human_review=True,
            )

        # Step 2: 后处理 — 三级图片匹配
        # 从 trace 的 observation 中收集检索到的文档上下文
        retrieved_contexts = []
        for s in (agent_result.trace if agent_result else []):
            if s.observation and s.action == "search":
                retrieved_contexts.append(s.observation)

        # 构造伪 docs 列表用于图片匹配和引用提取
        docs_for_postprocess = [
            {"content": ctx, "score": 0.8} for ctx in retrieved_contexts
        ]
        # 也加入最终回答用于图片匹配
        if answer_text:
            docs_for_postprocess.insert(0, {"content": answer_text, "score": 0.9})

        relevant_images = self._match_relevant_images(query, docs_for_postprocess)

        # Step 3: 引用溯源
        citations = self.source_tracer.extract_citations(answer_text, docs_for_postprocess)

        # Step 4: 置信度评估
        confidence = self._estimate_confidence(docs_for_postprocess)

        processing_time = (time.time() - start_time) * 1000

        return AgentResponse(
            query=query,
            answer=answer_text,
            citations=citations,
            related_images=relevant_images,
            trace=trace if 'trace' in dir() else [],
            confidence=confidence,
            processing_time_ms=round(processing_time, 2),
        )

    # ------------------------------------------------------------------
    # 三级图片匹配策略（保持不变）
    # ------------------------------------------------------------------

    @staticmethod
    def _extract_figure_numbers(text: str) -> set[int]:
        """从文本中提取图号引用（图1-99, Figure 1-99, Fig.1-99）。"""
        fig_patterns = [
            r'图\s*(\d{1,2})',           # 图12, 图 12
            r'Figure\s*(\d{1,2})',       # Figure 12
            r'Fig\.?\s*(\d{1,2})',       # Fig.12, Fig 12
        ]
        numbers: set[int] = set()
        for pattern in fig_patterns:
            for m in re.findall(pattern, text, re.IGNORECASE):
                num = int(m)
                if 1 <= num <= 99:
                    numbers.add(num)
        return numbers

    def _match_by_caption_keywords(
        self, query: str, sorted_images: list[tuple]
    ) -> list[dict]:
        """Tier 2: 基于图片 caption 与 query 的 jieba 关键字交集匹配。"""
        if not self._image_captions:
            return []

        query_keywords = set(jieba.cut(query.lower()))
        if not query_keywords:
            return []

        scored: list[tuple[int, int, str]] = []
        for img_path, page, *_ in sorted_images:
            caption = self._image_captions.get(img_path, "")
            if not caption:
                continue
            caption_keywords = set(jieba.cut(caption.lower()))
            intersection = query_keywords & caption_keywords
            if intersection:
                scored.append((len(intersection), page, img_path))

        scored.sort(key=lambda x: x[0], reverse=True)
        return self._encode_matched_images(scored[:2])

    def _match_by_path_keywords(
        self, query: str, sorted_images: list[tuple]
    ) -> list[dict]:
        """Tier 3: 基于图片文件路径/文件名与 query 的 jieba 关键字交集匹配。"""
        query_keywords = set(jieba.cut(query.lower()))
        if not query_keywords:
            return []

        scored: list[tuple[int, int, str]] = []
        for img_path, page, *_ in sorted_images:
            import os as _os
            fname = _os.path.splitext(_os.path.basename(img_path))[0]
            dirname = _os.path.basename(_os.path.dirname(img_path))
            path_text = f"{dirname} {fname}"
            path_keywords = set(jieba.cut(path_text.lower()))
            intersection = query_keywords & path_keywords
            if intersection:
                scored.append((len(intersection), page, img_path))

        scored.sort(key=lambda x: x[0], reverse=True)
        return self._encode_matched_images(scored[:2])

    def _encode_matched_images(
        self, candidates: list[tuple[int, int, str]]
    ) -> list[dict]:
        """将候选图片列表编码为 base64 data URL 的结果格式。"""
        result = []
        for kw_count, page, img_path in candidates:
            data_url = _encode_image_data_url(img_path)
            if data_url:
                caption_text = self._image_captions.get(img_path, "")
                result.append({
                    "data_url": data_url,
                    "caption": caption_text or "相关图片",
                    "page": page,
                    "relevance": min(0.5 + kw_count * 0.15, 0.95),
                })
        return result

    def _match_relevant_images(self, query: str, docs: list[dict]) -> list[dict]:
        """从检索到的文本中匹配最相关的图片（三级策略）。

        策略（按优先级）:
        1. 图号精确匹配 — 从检索文本+query中提取"图N"引用，按序映射
        2. Caption 关键字匹配 — jieba 分词后取交集
        3. 路径关键字匹配 — 从图片文件名/路径提取关键字匹配
        全部失败时返回空列表（不再无条件返回首图）。
        """
        if not self.image_paths:
            return []

        # 合并所有检索文本
        all_text = " ".join([
            d.get("content", d.get("text", "")) for d in docs[:10]
        ])
        all_text += " " + query

        # 图片按 page_idx 排序（图1对应 index 0）
        sorted_images = sorted(self.image_paths, key=lambda x: x[1] if len(x) >= 2 else 0)

        # ── Tier 1: 图号精确匹配 ──
        matched_fig_numbers = self._extract_figure_numbers(all_text)
        if matched_fig_numbers:
            result_images = []
            for fig_num in sorted(matched_fig_numbers)[:3]:
                idx = fig_num - 1  # 图1 -> index 0
                if 0 <= idx < len(sorted_images):
                    item = sorted_images[idx]
                    img_path = item[0]
                    page = item[1] if len(item) >= 2 else 0
                    data_url = _encode_image_data_url(img_path)
                    if data_url:
                        caption_text = self._image_captions.get(img_path, f"图{fig_num}")
                        result_images.append({
                            "data_url": data_url,
                            "caption": caption_text or f"图{fig_num}",
                            "page": page,
                            "relevance": 0.9 - (idx * 0.05),
                        })
            if result_images:
                return result_images[:2]

        # ── Tier 2: Caption 关键字匹配 ──
        result = self._match_by_caption_keywords(query, sorted_images)
        if result:
            return result[:2]

        # ── Tier 3: 路径关键字匹配 ──
        result = self._match_by_path_keywords(query, sorted_images)
        if result:
            return result[:2]

        # ── 全部失败：不返回图片 ──
        logger.info(
            "No relevant images found for query (tried figure-number, caption, path matching)"
        )
        return []

    def _estimate_confidence(self, docs: list[dict]) -> float:
        """基于检索结果质量估算回答置信度。"""
        if not docs:
            return 0.0
        scores = [d.get("score", d.get("relevance", 0.5)) for d in docs]
        avg_score = sum(scores) / len(scores)
        count_bonus = min(len(docs) / max(self.top_k, 1), 1.0) * 0.2
        return min(avg_score + count_bonus, 1.0)
