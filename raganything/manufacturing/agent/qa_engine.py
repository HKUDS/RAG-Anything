"""
文本问答引擎 — 基于 RAG-Anything 检索 + LLM 生成。

核心流程:
1. 用户输入查询
2. RAG-Anything 多模态检索 (向量 + BM25)
3. LLM 基于检索结果生成回答
4. 附加来源引用
"""

import logging
import time
from typing import Callable, Optional

from .source_tracer import SourceTracer
from ..knowledge_graph.models import AgentResponse

logger = logging.getLogger(__name__)


class QAEngine:
    """智能制造领域文本问答引擎。"""

    def __init__(self, rag_client=None, llm_client=None,
                 top_k: int = 10, citation_required: bool = True):
        """
        Args:
            rag_client: RAG-Anything 检索客户端
            llm_client: LLM 生成客户端
            top_k: 检索返回数量
            citation_required: 是否强制要求引用来源
        """
        self.rag_client = rag_client
        self.llm_client = llm_client
        self.top_k = top_k
        self.citation_required = citation_required
        self.source_tracer = SourceTracer()
        self._llm_adapter = self._resolve_llm_adapter(llm_client)

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

    def answer(self, query: str,
               context: Optional[dict] = None) -> AgentResponse:
        """执行文本问答。

        Args:
            query: 用户问题
            context: 上下文限定（如赛项 track、知识库范围）

        Returns:
            AgentResponse with answer, citations, confidence
        """
        start_time = time.time()
        context = context or {}

        # Step 1: 检索相关文档
        docs = self._retrieve(query, context)

        # Step 2: 如果无结果，返回降级回答
        if not docs:
            return self._fallback_response(query, start_time)

        # Step 3: LLM 生成回答
        answer_text, citations = self._generate(query, docs, context)

        # Step 4: 构造回答
        processing_time = (time.time() - start_time) * 1000
        confidence = self._estimate_confidence(docs)

        return AgentResponse(
            query=query,
            answer=answer_text,
            citations=citations,
            confidence=confidence,
            processing_time_ms=round(processing_time, 2),
        )

    def _retrieve(self, query: str, context: dict,
                  timeout: float = 3.0) -> list[dict]:
        """执行检索，超时自动降级。

        Args:
            query: 查询文本
            context: 上下文限定
            timeout: 检索超时秒数（默认 3s），超时后降级为无检索模式
        """
        if not self.rag_client:
            return []

        from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeout

        def _do_search():
            try:
                search_params = {"query": query, "top_k": self.top_k}
                if "knowledge_base_scope" in context:
                    search_params["filter"] = context["knowledge_base_scope"]
                if "competition_track" in context:
                    search_params["track"] = context["competition_track"]
                results = self.rag_client.search(**search_params)
                return results if isinstance(results, list) else []
            except Exception as e:
                logger.error(f"检索失败: {e}")
                return None  # None = 检索异常, 区别于空列表

        try:
            with ThreadPoolExecutor(max_workers=1) as executor:
                future = executor.submit(_do_search)
                results = future.result(timeout=timeout)
        except FuturesTimeout:
            logger.warning(f"检索超时 ({timeout}s)，降级为无检索模式: {query[:50]}...")
            return []
        except Exception as e:
            logger.error(f"检索线程异常: {e}")
            return []

        return results if results is not None else []

    def _generate(self, query: str, docs: list[dict],
                  context: dict) -> tuple[str, list[dict]]:
        """基于检索结果生成回答。"""
        if not self.llm_client or not self._llm_adapter:
            return self._no_llm_response(docs)

        # 构建 prompt
        doc_texts = []
        for i, doc in enumerate(docs[:self.top_k]):
            content = doc.get("content", doc.get("text", ""))
            source = doc.get("source", doc.get("title", f"文档 {i+1}"))
            doc_texts.append(f"[来源 {i+1}] {source}\n{content[:1000]}")

        prompt = f"""你是一位智能制造领域的教学专家。基于以下参考资料回答用户问题。

规则：
- 仅基于提供的参考资料回答，不要编造信息
- 如果参考资料不足以回答问题，明确说明
- 每个关键陈述标注来源编号，如 [来源 1]

参考资料：
{chr(10).join(doc_texts)}

用户问题：{query}

请回答："""

        try:
            response = self._llm_adapter(prompt)
            citations = self.source_tracer.extract_citations(response, docs)
            return response, citations
        except Exception as e:
            logger.error(f"LLM 生成失败: {e}")
            return self._no_llm_response(docs)

    def _no_llm_response(self, docs: list[dict]) -> tuple[str, list[dict]]:
        """无 LLM 时的降级回答：直接返回检索摘要。"""
        if not docs:
            return "未找到相关内容。", []

        lines = ["找到以下相关内容：\n"]
        for i, doc in enumerate(docs[:5]):
            title = doc.get("title", doc.get("source", f"结果 {i+1}"))
            snippet = doc.get("content", doc.get("text", ""))[:200]
            lines.append(f"{i+1}. **{title}**: {snippet}...")

        citations = [{
            "source_title": d.get("title", d.get("source", "")),
            "page": d.get("page"),
            "excerpt": d.get("content", d.get("text", ""))[:300],
        } for d in docs[:5]]

        return "\n".join(lines), citations

    def _fallback_response(self, query: str, start_time: float) -> AgentResponse:
        return AgentResponse(
            query=query,
            answer="当前知识库未覆盖该问题，建议联系专业教师获取帮助。",
            citations=[],
            confidence=0.0,
            processing_time_ms=round((time.time() - start_time) * 1000, 2),
            needs_human_review=True,
        )

    def _estimate_confidence(self, docs: list[dict]) -> float:
        """基于检索结果质量估算回答置信度。"""
        if not docs:
            return 0.0
        scores = [d.get("score", d.get("relevance", 0.5)) for d in docs]
        avg_score = sum(scores) / len(scores)
        count_bonus = min(len(docs) / self.top_k, 1.0) * 0.2
        return min(avg_score + count_bonus, 1.0)
