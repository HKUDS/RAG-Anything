# -*- coding: utf-8 -*-
"""
Agentic RAG Built-in Tools.

Layer: Core
Primary Responsibility: Built-in Tool implementations for AgenticRAG —
    SearchTool, CalculatorTool, DatabaseQueryTool, WebSearchTool.
Key Dependencies: raganything (RAGAnything.aquery), lightrag, stdlib

Extracted from engine.py. Each tool extends Tool(ABC) and implements
async execute(input) -> str.
"""

from __future__ import annotations

import asyncio
import math as _math
import time
from typing import Any

from raganything.agentic_rag.tool_base import Tool
from raganything.query.tag_scoped_retriever import TagScope, retrieve_tag_scoped_context
from raganything.services.query_execution import await_before_deadline
from raganything.services.query_timing import QueryTiming


class SearchTool(Tool):
    """Knowledge base retrieval tool — wraps RAG search capability."""

    name = "search"
    description = "在知识库中检索相关文档内容。当需要查找具体信息、数据或政策时使用此工具。"
    parameters = {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "搜索查询词，应具体明确",
            },
        },
        "required": ["query"],
    }

    def __init__(
        self,
        rag_instance=None,
        query_mode: str = "rrf",
        top_k: int = 30,
        chunk_top_k: int = 20,
        enable_rerank: bool = False,
        include_references: bool = True,
        tag_scope: TagScope | None = None,
        retrieval_options: Any = None,
        query_execution_scope: Any = None,
    ):
        """
        Args:
            rag_instance: RAGAnything instance (provides aquery method)
            query_mode: Search mode "rrf" | "hybrid" | "local" | "global" | "naive"
                       Default "rrf" (three-channel fusion)
        """
        self.rag = rag_instance
        self.query_mode = query_mode
        try:
            parsed_top_k = int(top_k)
        except (TypeError, ValueError):
            parsed_top_k = 30
        try:
            parsed_chunk_top_k = int(chunk_top_k)
        except (TypeError, ValueError):
            parsed_chunk_top_k = 20
        self.top_k = max(5, min(200, parsed_top_k))
        self.chunk_top_k = max(1, min(100, parsed_chunk_top_k))
        self.enable_rerank = bool(enable_rerank)
        self.include_references = bool(include_references)
        self.tag_scope = tag_scope
        self.retrieval_options = retrieval_options
        self.query_execution_scope = query_execution_scope

    def _deadline(self) -> float | None:
        scope = self.query_execution_scope
        if hasattr(scope, "deadline_monotonic"):
            return scope.deadline_monotonic
        if isinstance(scope, dict):
            return scope.get("deadline_monotonic")
        return None

    async def execute(self, input: dict) -> str:
        query = input.get("query", "")
        if not query:
            return "搜索失败：查询词不能为空"

        if self.rag is None:
            return "搜索失败：知识库未初始化"

        trace_id = getattr(self.query_execution_scope, "trace_id", None)
        if trace_id is None and isinstance(self.query_execution_scope, dict):
            trace_id = self.query_execution_scope.get("trace_id")
        timing = QueryTiming(trace_id) if isinstance(trace_id, str) else None
        started = time.perf_counter()
        outcome = "ok"
        try:
            if self.tag_scope is not None:
                result = await retrieve_tag_scoped_context(
                    self.rag,
                    self.tag_scope,
                    query,
                    top_k=self.chunk_top_k,
                    max_total_tokens=8000,
                    deadline_monotonic=self._deadline(),
                )
                if not result:
                    return f"标签“{self.tag_scope.tag_name}”范围内没有与问题相关的内容"
                return result[:8000] if len(result) > 8000 else result
            result = await await_before_deadline(
                self.rag.aquery(
                    query,
                    mode=self.query_mode,
                    only_need_context=True,
                    enable_rerank=self.enable_rerank,
                    chunk_top_k=self.chunk_top_k,
                    top_k=self.top_k,
                    include_references=self.include_references,
                    max_entity_tokens=2000,
                    max_relation_tokens=1000,
                    max_total_tokens=8000,
                    retrieval_options=self.retrieval_options,
                    query_execution_scope=self.query_execution_scope,
                ),
                self._deadline(),
            )
            if not result or not result.strip():
                return "知识库中未找到相关信息"
            if len(result) > 8000:
                result = result[:8000] + "\n...(内容过长，已截断)"
            return result
        except TimeoutError:
            outcome = "timeout"
            return "Search timed out; continuing with available results."
        except asyncio.CancelledError:
            outcome = "cancelled"
            raise
        except Exception as e:
            outcome = "error"
            return f"搜索出错: {str(e)}"
        finally:
            if timing is not None:
                timing.record(
                    "retrieval",
                    time.perf_counter() - started,
                    outcome=outcome,
                )


class CalculatorTool(Tool):
    """Safe arithmetic evaluation tool."""

    name = "calculator"
    description = "执行数学计算（四则运算、幂运算、平方根等）。支持运算符: + - * / ** // %。支持函数: sqrt, pow, abs, round, min, max, sum。"
    parameters = {
        "type": "object",
        "properties": {
            "expression": {
                "type": "string",
                "description": "要计算的数学表达式，例如 '123 * 456 + 789' 或 'sqrt(144) + pow(2, 10)'",
            },
        },
        "required": ["expression"],
    }

    # Safe globals whitelist
    _SAFE_GLOBALS: dict[str, Any] = {
        "__builtins__": {},
        "abs": abs, "round": round, "min": min, "max": max, "sum": sum,
        "pow": pow, "sqrt": _math.sqrt, "sin": _math.sin, "cos": _math.cos,
        "tan": _math.tan, "log": _math.log, "log10": _math.log10,
        "pi": _math.pi, "e": _math.e, "ceil": _math.ceil, "floor": _math.floor,
        "int": int, "float": float,
    }

    # Forbidden keywords
    _FORBIDDEN = [
        "__", "import", "exec", "eval", "open", "compile",
        "globals", "locals", "getattr", "setattr", "delattr",
        "os.", "sys.", "subprocess", "socket", "http",
        "class", "lambda", "yield", "async", "await",
    ]

    async def execute(self, input: dict) -> str:
        expression = input.get("expression", "").strip()
        if not expression:
            return "计算错误：表达式为空"

        # Security check
        expr_lower = expression.lower()
        for forbidden in self._FORBIDDEN:
            if forbidden in expr_lower:
                return f"表达式包含不允许的操作: {forbidden}"

        # Only allow safe characters
        safe_chars = set(
            "0123456789+-*/.() **//% <>=!&|^~," +
            "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ_"
        )
        for ch in expression:
            if ch not in safe_chars and not ch.isspace():
                return f"表达式包含不允许的字符: '{ch}'"

        try:
            result = eval(expression, self._SAFE_GLOBALS, {})
            if isinstance(result, float):
                if abs(result - round(result, 0)) < 1e-10:
                    result = int(round(result, 0))
                else:
                    result = round(result, 6)
            return str(result)
        except ZeroDivisionError:
            return "计算错误: 除以零"
        except Exception as e:
            return f"计算错误: {str(e)}"


class DatabaseQueryTool(Tool):
    """Internal data statistics query tool — read-only JSON data store queries."""

    name = "database_query"
    description = (
        "查询 RAG 系统内部统计信息。支持: "
        "(1) 文档统计: 总数、按状态分组(processed/failed/handling)、按知识库分组; "
        "(2) 知识库列表: 所有 KB 名称、创建时间; "
        "(3) 实体/关系/块数量; "
        "(4) 智能体统计: 数量、名称列表; "
        "(5) 存储总览: 综合统计。"
        "使用中文关键词查询，例如 query='文档统计' 或 query='知识库列表'。"
    )
    parameters = {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": (
                    "要查询的统计类型。可选值: 文档统计, 知识库列表, "
                    "实体统计, 智能体统计, 存储总览, 全部"
                ),
            },
        },
        "required": ["query"],
    }

    def __init__(self, kb_dir: str = "./rag_storage"):
        self.kb_dir = kb_dir
        self.project_dir = "."

    async def execute(self, input: dict) -> str:
        query_text = input.get("query", "").strip()
        try:
            return await self._query_stats_async(query_text)
        except Exception as e:
            return f"数据库查询出错: {str(e)}"

    @staticmethod
    def _pg_available() -> bool:
        try:
            from raganything.services.pg_state_repo import get_pg_pool
            get_pg_pool()
            return True
        except RuntimeError:
            return False

    async def _query_stats_async(self, query: str) -> str:
        if not self._pg_available():
            return "数据库不可用：PostgreSQL 连接池未初始化，请在服务器启动后重试。"
        results: list[str] = []
        if any(kw in query for kw in ("文档", "doc", "全部", "总览", "存储")):
            results.append(await self._doc_stats_async())
        if any(kw in query for kw in ("知识库", "kb", "全部", "总览", "存储")):
            results.append(await self._kb_list_async())
        if any(kw in query for kw in ("实体", "关系", "块", "entity", "relation", "chunk", "全部", "总览", "存储")):
            results.append(await self._entity_stats_async())
        if any(kw in query for kw in ("智能体", "agent", "全部", "总览", "存储")):
            results.append(await self._agent_stats_async())
        if not results:
            results = [await self._doc_stats_async(), await self._kb_list_async(), await self._agent_stats_async()]
        return "\n\n".join(results)

    # ── PG-backed stat methods ──────────────────────────

    async def _doc_stats_async(self) -> str:
        from raganything.services.pg_state_repo import get_pg_pool
        workspace = self.kb_dir
        lines = ["## 文档统计"]
        pool = get_pg_pool()
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                """SELECT id, file_path, status, chunks_count, updated_at
                   FROM LIGHTRAG_DOC_STATUS WHERE workspace=$1""",
                workspace,
            )
        if rows:
            total = len(rows)
            by_status: dict[str, int] = {}
            total_chunks = 0
            for r in rows:
                st = r.get("status", "unknown") or "unknown"
                by_status[st] = by_status.get(st, 0) + 1
                total_chunks += r.get("chunks_count", 0) or 0
            lines.append(f"- 总文档数: {total}")
            lines.append(f"- 总块数: {total_chunks}")
            for st, cnt in by_status.items():
                lines.append(f"  - {st}: {cnt} 个")
            sorted_docs = sorted(rows, key=lambda r: r.get("updated_at") or "", reverse=True)
            lines.append("- 最近文档:")
            for r in sorted_docs[:5]:
                fname = r.get("file_path", "?") or "?"
                st = r.get("status", "?") or "?"
                chunks = r.get("chunks_count", 0) or 0
                lines.append(f"  - {fname} [{st}, {chunks} chunks]")
        else:
            lines.append("- 无文档记录")
        return "\n".join(lines)

    async def _kb_list_async(self) -> str:
        from raganything.services.pg_kb_meta_repo import pg_load_kb_meta
        lines = ["## 知识库列表"]
        kb_meta = await pg_load_kb_meta()
        if kb_meta:
            lines.append(f"- 总数: {len(kb_meta)}")
            for name, info in kb_meta.items():
                created = (info.get("created") or "")[:10]
                display = info.get("name", name)
                lines.append(f"  - {name}: {display} (创建于 {created})")
        else:
            lines.append("- 无知识库记录")
        return "\n".join(lines)

    async def _entity_stats_async(self) -> str:
        from raganything.services.pg_state_repo import get_pg_pool
        import json as _json
        workspace = self.kb_dir
        lines = ["## 实体与关系统计"]
        pool = get_pg_pool()
        async with pool.acquire() as conn:
            ent_rows = await conn.fetch(
                """SELECT entity_names FROM LIGHTRAG_FULL_ENTITIES
                   WHERE workspace=$1""",
                workspace,
            )
            rel_rows = await conn.fetch(
                """SELECT relation_pairs FROM LIGHTRAG_FULL_RELATIONS
                   WHERE workspace=$1""",
                workspace,
            )
            chunk_count = await conn.fetchval(
                """SELECT coalesce(sum(chunks_count), 0)
                   FROM LIGHTRAG_DOC_STATUS WHERE workspace=$1""",
                workspace,
            )
        total_entities = 0
        for row in ent_rows:
            entity_names = row["entity_names"]
            if isinstance(entity_names, str):
                try:
                    entity_names = _json.loads(entity_names)
                except Exception:
                    entity_names = []
            total_entities += len(entity_names) if entity_names else 0
        total_relations = 0
        for row in rel_rows:
            relation_pairs = row["relation_pairs"]
            if isinstance(relation_pairs, str):
                try:
                    relation_pairs = _json.loads(relation_pairs)
                except Exception:
                    relation_pairs = []
            total_relations += len(relation_pairs) if relation_pairs else 0
        lines.append(f"- 实体名称总数: {total_entities}")
        lines.append(f"- 关系对总数: {total_relations}")
        lines.append(f"- 向量块数: {chunk_count or 0}")
        return "\n".join(lines)

    async def _agent_stats_async(self) -> str:
        from raganything.services.pg_agent_repo import pg_list_agents
        lines = ["## 智能体统计"]
        agents = await pg_list_agents(is_admin=True)
        if agents:
            lines.append(f"- 总数: {len(agents)}")
            for a in agents[:10]:
                lines.append(
                    f"  - {a.get('name','?')} (模型: {a.get('llm_model','?')}, KB: {a.get('kb_name','?')})"
                )
        else:
            lines.append("- 无智能体记录")
        return "\n".join(lines)


class WebSearchTool(Tool):
    """External web search tool using DuckDuckGo API."""

    name = "web_search"
    description = "搜索互联网上的公开信息。当知识库中没有相关信息时使用。"
    parameters = {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "搜索关键词",
            },
        },
        "required": ["query"],
    }

    def __init__(self):
        self._request_count = 0
        self._window_start = time.time()

    async def execute(self, input: dict) -> str:
        query = input.get("query", "")
        if not query:
            return "搜索失败：查询词不能为空"

        # Rate limit: 10 requests / 60 seconds
        now = time.time()
        if now - self._window_start > 60:
            self._request_count = 0
            self._window_start = now
        if self._request_count >= 10:
            return "搜索请求过于频繁，请稍后再试"
        self._request_count += 1

        try:
            import httpx
            async with httpx.AsyncClient(timeout=15, follow_redirects=True) as client:
                resp = await client.get(
                    "https://api.duckduckgo.com/",
                    params={
                        "q": query,
                        "format": "json",
                        "no_html": "1",
                        "skip_disambig": "1",
                    },
                    headers={"User-Agent": "RAGAnything/1.0"},
                )
                if resp.status_code == 200:
                    data = resp.json()
                    results = []
                    if data.get("AbstractText"):
                        results.append(f"摘要: {data['AbstractText']}")
                    for topic in data.get("RelatedTopics", [])[:5]:
                        if isinstance(topic, dict) and topic.get("Text"):
                            results.append(f"- {topic['Text']}")
                    if results:
                        return "\n".join(results[:5])
                    return "未找到相关搜索结果"
                return f"搜索服务返回异常: HTTP {resp.status_code}"
        except ImportError:
            return "搜索失败：httpx 未安装"
        except Exception as e:
            return f"搜索服务暂时不可用: {str(e)}"


__all__ = ["SearchTool", "CalculatorTool", "DatabaseQueryTool", "WebSearchTool"]
