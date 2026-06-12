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
    "你是智能制造教学专家，擅长设备操作、PLC编程、数控加工、故障诊断。"
    "用 search 工具检索知识库获取准确信息。"
    "回答要求：基于检索到的实际文档内容，引用具体参数和数据，标注来源编号 [来源 N]。"
    "没有检索到的信息不要编造，直接说未找到。"
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
            # Forward stream/temperature/max_tokens etc. to underlying adapter
            extra_kw = {k: v for k, v in kw.items() if k not in ("prompt", "system_prompt", "history_messages")}

            if history_messages:
                conversation = (
                    [{"role": "system", "content": system_prompt}] if system_prompt else []
                ) + history_messages + [{"role": "user", "content": prompt}]

                full_prompt = "\n\n".join(
                    f"[{m['role']}]: {m['content']}" for m in conversation
                )
                result = llm_adapter(full_prompt, **extra_kw)
                if inspect.isawaitable(result):
                    result = await result
                # 流式调用返回 async generator，直接透传
                if hasattr(result, '__aiter__'):
                    return result
                return result if isinstance(result, str) else str(result)

            full = f"System: {system_prompt}\n\nUser: {prompt}" if system_prompt else prompt
            result = llm_adapter(full, **extra_kw)
            if inspect.isawaitable(result):
                result = await result
            if hasattr(result, '__aiter__'):
                return result
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

    async def _direct_retrieve(self, query: str, timeout: float = 10.0) -> str:
        """Tier 1 直接 RRF 检索，返回上下文字符串。"""
        if self.rag_client is None or not hasattr(self.rag_client, 'aquery'):
            return ""
        try:
            return await asyncio.wait_for(
                self.rag_client.aquery(query, mode="rrf", only_need_context=True, top_k=self.top_k),
                timeout=timeout,
            ) or ""
        except asyncio.TimeoutError:
            logger.warning(f"直接检索超时 ({timeout}s)")
            return ""
        except Exception as e:
            logger.warning(f"直接检索失败: {e}")
            return ""

    def _post_process(self, query: str, answer_text: str, retrieved_texts: list[str],
                      start_time: float, trace: list[dict] | None = None) -> AgentResponse:
        """后处理：图片匹配 + 引用溯源 + 置信度。"""
        docs = [{"content": t, "score": 0.8} for t in retrieved_texts]
        if answer_text:
            docs.insert(0, {"content": answer_text, "score": 0.9})

        images = self._match_relevant_images(query, docs)
        citations = self.source_tracer.extract_citations(answer_text, docs)
        confidence = self._estimate_confidence(docs)
        ms = round((time.time() - start_time) * 1000, 2)

        return AgentResponse(
            query=query, answer=answer_text, citations=citations,
            related_images=images, trace=trace or [],
            confidence=confidence, processing_time_ms=ms,
        )

    async def answer(self, query: str,
                     context: Optional[dict] = None) -> AgentResponse:
        """两级问答 — Tier 1 直接检索 → Tier 2 AgenticRAG 兜底。"""
        start_time = time.time()

        if self._llm_adapter is None:
            return AgentResponse(query=query, answer="LLM 服务未配置。",
                                 citations=[], confidence=0.0, processing_time_ms=0)

        # ═══ Tier 1: 直接 RRF 检索 ═══
        ctx = await self._direct_retrieve(query)

        if len(ctx) >= 200:
            # 上下文充分 → 直接 prompt+LLM（与通用智能体一致）
            prompt = (
                f"你是智能制造教学专家。基于以下检索内容回答用户问题。\n\n"
                f"## 检索内容\n{ctx}\n\n"
                f"## 问题\n{query}\n\n"
                f"## 要求\n"
                f"从检索内容提取事实和数据。有数字必须引用 [来源 1]。"
                f"没有就说未找到。不编造。用 markdown 格式回答。"
            )
            result = self._llm_adapter(prompt)
            if inspect.isawaitable(result):
                result = await result
            answer_text = result if isinstance(result, str) else str(result)
            return self._post_process(query, answer_text, [ctx], start_time)

        if len(ctx) < 50:
            # 无有效内容 → 直接走 AgenticRAG
            return await self._agentic_answer(query, start_time)

        # 50-200 字符 → 生成后评估
        prompt = (
            f"你是智能制造教学专家。基于以下检索内容回答。\n\n"
            f"## 检索内容\n{ctx}\n\n## 问题\n{query}\n\n"
            f"从检索内容提取事实。不编造。用 markdown 格式。"
        )
        result = self._llm_adapter(prompt)
        if inspect.isawaitable(result):
            result = await result
        answer_text = result if isinstance(result, str) else str(result)

        response = self._post_process(query, answer_text, [ctx], start_time)
        if response.confidence < 0.3:
            logger.info(f"Tier 1 置信度过低 ({response.confidence:.2f})，回退 AgenticRAG")
            return await self._agentic_answer(query, start_time)
        return response

    async def _agentic_answer(self, query: str, start_time: float) -> AgentResponse:
        """Tier 2: AgenticRAG 多步推理兜底。"""
        if self._agentic_rag is None:
            return AgentResponse(query=query, answer="推理引擎未配置。",
                                 citations=[], confidence=0.0, processing_time_ms=0)

        try:
            agent_result = await self._agentic_rag.run(query)
        except Exception as e:
            logger.error(f"AgenticRAG 失败: {e}")
            return AgentResponse(query=query, answer=f"推理出错: {e}",
                                 citations=[], confidence=0.0,
                                 processing_time_ms=round((time.time() - start_time) * 1000, 2))

        trace = [{"step": s.step_number, "thought": s.thought,
                  "action": s.action, "observation": s.observation,
                  "elapsed_ms": s.elapsed_ms} for s in agent_result.trace]
        contexts = [s.observation for s in agent_result.trace
                    if s.observation and s.action == "search"]
        return self._post_process(query, agent_result.answer, contexts, start_time, trace)

    async def answer_stream(self, query: str) -> "AsyncIterator[dict]":
        """两级流式问答 — Tier 1 直接检索+流式LLM → Tier 2 AgenticRAG 兜底。

        Yields:
            {"type": "thinking", "step": N, ...}  — 仅 AgenticRAG 路径
            {"type": "token", "content": "<token>"}
            {"type": "done", "images": [...], "citations": [...], "confidence": ...}
        """
        start_time = time.time()

        if self._llm_adapter is None:
            yield {"type": "done", "content": "LLM 服务未配置。", "images": [], "citations": [], "confidence": 0.0}
            return

        # ═══ Tier 1: 直接 RRF 检索 ═══
        ctx = await self._direct_retrieve(query)
        yield {"type": "thinking", "step": 0, "thought": f"检索到 {len(ctx)} 字符上下文", "action": "retrieve"}

        if len(ctx) < 50 and self._agentic_rag is not None:
            # 无有效内容 → 走 AgenticRAG 流式
            full_answer = ""
            trace_steps = []
            retrieved_contexts = []
            try:
                async for event in self._agentic_rag.run_stream(query):
                    if event.type == "thinking":
                        sd = {"step": event.step or 0, "thought": event.thought or "",
                              "action": event.action or "", "observation": event.observation or "",
                              "elapsed_ms": event.elapsed_ms}
                        trace_steps.append(sd)
                        if event.action == "search" and event.observation:
                            retrieved_contexts.append(event.observation)
                        yield {"type": "thinking", **sd}
                    elif event.type == "token":
                        full_answer += (event.content or "")
                        yield {"type": "token", "content": event.content or ""}
                    elif event.type == "done":
                        if event.answer and len(event.answer) > len(full_answer):
                            full_answer = event.answer
                        break
            except Exception as e:
                logger.error(f"AgenticRAG stream 失败: {e}")
                yield {"type": "done", "content": str(e), "images": [], "citations": [], "confidence": 0.0}
                return

            docs = [{"content": c, "score": 0.8} for c in retrieved_contexts]
            if full_answer:
                docs.insert(0, {"content": full_answer, "score": 0.9})
            yield {
                "type": "done",
                "answer": full_answer,
                "images": self._match_relevant_images(query, docs),
                "citations": self.source_tracer.extract_citations(full_answer, docs),
                "confidence": self._estimate_confidence(docs),
                "elapsed_ms": round((time.time() - start_time) * 1000, 2),
                "trace": trace_steps,
            }
            return

        # ═══ Tier 1 快速路径：直接 LLM stream ═══
        prompt = (
            f"你是智能制造教学专家。基于以下检索内容回答。\n\n"
            f"## 检索内容\n{ctx}\n\n## 问题\n{query}\n\n"
            f"从检索内容提取事实和数据。有数字必须引用 [来源 1]。"
            f"没有就说未找到。不编造。用 markdown 格式。"
        )
        full_answer = ""
        try:
            result = self._llm_adapter(prompt, stream=True)
            if inspect.isawaitable(result):
                result = await result
            if hasattr(result, '__aiter__'):
                async for token in result:
                    full_answer += token
                    yield {"type": "token", "content": token}
            elif isinstance(result, str):
                full_answer = result
                yield {"type": "token", "content": result}
            else:
                full_answer = str(result) if result else ""
                yield {"type": "token", "content": full_answer}
        except Exception as e:
            logger.error(f"Tier 1 LLM stream 失败: {e}")
            full_answer = ctx[:500]

        docs = [{"content": ctx, "score": 0.8}]
        if full_answer:
            docs.insert(0, {"content": full_answer, "score": 0.9})
        yield {
            "type": "done",
            "answer": full_answer,
            "images": self._match_relevant_images(query, docs),
            "citations": self.source_tracer.extract_citations(full_answer, docs),
            "confidence": self._estimate_confidence(docs),
            "elapsed_ms": round((time.time() - start_time) * 1000, 2),
        }

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
        """基于检索上下文质量估算置信度。

        信号: 上下文长度(信息量) + 来源数量(覆盖面) + 答案长度(完整性)
        """
        if not docs:
            return 0.0

        total_chars = sum(len(d.get("content", "")) for d in docs)
        # 来源去重（从 content 中提取文档来源标记）
        sources = set()
        for d in docs:
            import re as _re
            for m in _re.findall(r'\[Doc \d+\]|sources:\s*(\w+)', d.get("content", "")):
                sources.add(m)

        # 上下文长度分数: 0-2000+ chars → 0.0-1.0
        length_score = min(total_chars / 2000.0, 1.0)
        # 来源丰富度: 1-5+
        source_score = min(len(sources) / 3.0, 1.0) if sources else 0.3
        # 加权综合
        return round(length_score * 0.6 + source_score * 0.4, 2)
