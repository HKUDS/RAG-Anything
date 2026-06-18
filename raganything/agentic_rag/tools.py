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

import json
import math as _math
import os
import time
from pathlib import Path
from typing import Any

from raganything.agentic_rag.tool_base import Tool


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

    def __init__(self, rag_instance=None, query_mode: str = "rrf"):
        """
        Args:
            rag_instance: RAGAnything instance (provides aquery method)
            query_mode: Search mode "rrf" | "hybrid" | "local" | "global" | "naive"
                       Default "rrf" (three-channel fusion)
        """
        self.rag = rag_instance
        self.query_mode = query_mode

    async def execute(self, input: dict) -> str:
        query = input.get("query", "")
        if not query:
            return "搜索失败：查询词不能为空"

        if self.rag is None:
            return "搜索失败：知识库未初始化"

        try:
            result = await self.rag.aquery(
                query,
                mode=self.query_mode,
                only_need_context=True,
                enable_rerank=False,
                chunk_top_k=20,
                top_k=30,
                max_entity_tokens=2000,
                max_relation_tokens=1000,
                max_total_tokens=8000,
            )
            if not result or not result.strip():
                return "知识库中未找到相关信息"
            if len(result) > 8000:
                result = result[:8000] + "\n...(内容过长，已截断)"
            return result
        except Exception as e:
            return f"搜索出错: {str(e)}"


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
            return self._query_stats(query_text)
        except Exception as e:
            return f"数据库查询出错: {str(e)}"

    def _query_stats(self, query: str) -> str:
        results: list[str] = []
        if any(kw in query for kw in ("文档", "doc", "全部", "总览", "存储")):
            results.append(self._doc_stats())
        if any(kw in query for kw in ("知识库", "kb", "全部", "总览", "存储")):
            results.append(self._kb_list())
        if any(kw in query for kw in ("实体", "关系", "块", "entity", "relation", "chunk", "全部", "总览", "存储")):
            results.append(self._entity_stats())
        if any(kw in query for kw in ("智能体", "agent", "全部", "总览", "存储")):
            results.append(self._agent_stats())
        if not results:
            results = [self._doc_stats(), self._kb_list(), self._agent_stats()]
        return "\n\n".join(results)

    def _safe_read_json(self, path: str) -> dict:
        try:
            p = Path(path)
            if p.exists():
                return json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            pass
        return {}

    def _doc_stats(self) -> str:
        lines = ["## 文档统计"]
        ds = self._safe_read_json(f"{self.kb_dir}/kv_store_doc_status.json")
        if ds:
            total = len(ds)
            by_status: dict[str, int] = {}
            total_chunks = 0
            for info in ds.values():
                st = info.get("status", "unknown")
                by_status[st] = by_status.get(st, 0) + 1
                total_chunks += info.get("chunks_count", 0)
            lines.append(f"- 总文档数: {total}")
            lines.append(f"- 总块数: {total_chunks}")
            for st, cnt in by_status.items():
                lines.append(f"  - {st}: {cnt} 个")
            sorted_docs = sorted(
                ds.items(),
                key=lambda x: x[1].get("updated_at", ""),
                reverse=True,
            )
            lines.append("- 最近文档:")
            for doc_id, info in sorted_docs[:5]:
                fname = info.get("file_path", "?")
                st = info.get("status", "?")
                chunks = info.get("chunks_count", 0)
                lines.append(f"  - {fname} [{st}, {chunks} chunks]")
        fd = self._safe_read_json(f"{self.kb_dir}/kv_store_full_docs.json")
        if fd:
            lines.append(f"- 全量文档记录: {len(fd)} 条")
        return "\n".join(lines)

    def _kb_list(self) -> str:
        lines = ["## 知识库列表"]
        kb_meta = self._safe_read_json("rag_storage_kb_meta.json")
        if kb_meta:
            lines.append(f"- 总数: {len(kb_meta)}")
            for name, info in kb_meta.items():
                created = info.get("created", "")[:10]
                display = info.get("name", name)
                lines.append(f"  - {name}: {display} (创建于 {created})")
        return "\n".join(lines)

    def _entity_stats(self) -> str:
        lines = ["## 实体与关系统计"]
        entities = self._safe_read_json(f"{self.kb_dir}/kv_store_full_entities.json")
        relations = self._safe_read_json(f"{self.kb_dir}/kv_store_full_relations.json")
        chunks = self._safe_read_json(f"{self.kb_dir}/vdb_chunks.json")
        if entities:
            total_names = sum(
                len(v.get("entity_names", [])) for v in entities.values()
            )
            lines.append(f"- 实体类型数: {len(entities)}, 实体名称数: {total_names}")
        if relations:
            total_pairs = sum(
                len(v.get("relation_pairs", [])) for v in relations.values()
            )
            lines.append(f"- 关系类型数: {len(relations)}, 关系对数: {total_pairs}")
        if chunks:
            lines.append(f"- 向量块数: {len(chunks)}")
        return "\n".join(lines)

    def _agent_stats(self) -> str:
        lines = ["## 智能体统计"]
        agent_meta = self._safe_read_json("agent_meta.json")
        if agent_meta:
            agents = agent_meta.get("agents", [])
            lines.append(f"- 总数: {len(agents)}")
            for a in agents[:10]:
                lines.append(f"  - {a.get('name','?')} (模型: {a.get('llm_model','?')}, KB: {a.get('kb_name','?')})")
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
