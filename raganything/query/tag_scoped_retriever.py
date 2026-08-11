"""Strict retrieval restricted to the chunks assigned to one KB tag."""

from __future__ import annotations

import asyncio
import math
import os
from dataclasses import dataclass
from typing import Any

import jieba

from raganything.services.kb_tag_repo import get_tag_assignments
from raganything.services.query_execution import await_before_deadline
from raganything.utils import display_document_name

_SEMANTIC_CANDIDATE_LIMIT = int(os.getenv("TAG_SCOPE_SEMANTIC_CANDIDATES", "48"))


@dataclass(frozen=True)
class TagScope:
    tag_id: int
    tag_name: str
    chunk_ids: tuple[str, ...]

    @property
    def label(self) -> str:
        return f"标签范围：{self.tag_name}"


async def resolve_tag_scope(kb_name: str, tag_id: int) -> TagScope | None:
    tag, assignments = await get_tag_assignments(kb_name, tag_id)
    if not tag:
        return None
    chunk_ids = tuple(dict.fromkeys(item["chunk_id"] for item in assignments if item.get("chunk_id")))
    return TagScope(tag_id=int(tag["id"]), tag_name=tag["name"], chunk_ids=chunk_ids)


async def retrieve_tag_scoped_context(
    instance: Any,
    scope: TagScope,
    query: str,
    *,
    top_k: int = 20,
    max_total_tokens: int = 8000,
    deadline_monotonic: float | None = None,
) -> str:
    """Retrieve tagged context without exceeding the request-wide deadline."""
    try:
        return await await_before_deadline(
            _retrieve_tag_scoped_context_unbounded(
                instance,
                scope,
                query,
                top_k=top_k,
                max_total_tokens=max_total_tokens,
            ),
            deadline_monotonic,
        )
    except TimeoutError:
        return ""


async def _retrieve_tag_scoped_context_unbounded(
    instance: Any,
    scope: TagScope,
    query: str,
    *,
    top_k: int = 20,
    max_total_tokens: int = 8000,
) -> str:
    """Rank only tagged chunks, then build citation-friendly RAG context.

    LightRAG's vector storage does not expose a stable metadata predicate across
    all configured backends. Fetching the tag-owned candidate set first makes
    the scope strict; lexical ranking is always available, and semantic rerank
    improves ordering when the configured embedding function is available.
    """
    if not scope.chunk_ids:
        return ""

    records = await instance.lightrag.text_chunks.get_by_ids(list(scope.chunk_ids))
    chunks = [dict(value) for value in (records or []) if isinstance(value, dict) and value.get("content")]
    if not chunks:
        return ""

    ranked = await _rank_chunks(instance, chunks, query, max(1, min(int(top_k or 20), 100)))
    token_budget = max(1000, int(max_total_tokens or 8000))
    used_tokens = 0
    sections = [f"[检索范围仅限标签：{scope.tag_name}]" ]
    for chunk in ranked:
        content = str(chunk.get("content") or "").strip()
        if not content:
            continue
        tokens = int(chunk.get("tokens") or max(1, len(content) // 2))
        if len(sections) > 1 and used_tokens + tokens > token_budget:
            break
        filename = display_document_name(chunk.get("file_path"), default="未命名文档")
        order = chunk.get("chunk_order_index")
        position = f"，切块 {int(order) + 1}" if isinstance(order, int) or str(order).isdigit() else ""
        sections.append(f"[来源：{filename}{position}]\n{content}")
        used_tokens += tokens
    return "\n\n".join(sections) if len(sections) > 1 else ""


async def _rank_chunks(instance: Any, chunks: list[dict[str, Any]], query: str, top_k: int) -> list[dict[str, Any]]:
    lexical_scores = _lexical_scores(query, chunks)
    ranked_indices = sorted(range(len(chunks)), key=lambda index: lexical_scores[index], reverse=True)
    semantic_limit = max(top_k, min(len(chunks), _SEMANTIC_CANDIDATE_LIMIT))
    candidate_indices = ranked_indices[:semantic_limit]
    semantic_scores = await _semantic_scores(instance, query, [chunks[index] for index in candidate_indices])

    lexical_max = max((lexical_scores[index] for index in candidate_indices), default=0.0)
    combined: list[tuple[float, int]] = []
    for position, index in enumerate(candidate_indices):
        lexical = lexical_scores[index] / lexical_max if lexical_max > 0 else 0.0
        semantic = semantic_scores[position] if semantic_scores else 0.0
        # Semantic scores are cosine similarities in [-1, 1]. Map to [0, 1].
        semantic = (semantic + 1.0) / 2.0 if semantic_scores else 0.0
        score = (0.65 * semantic + 0.35 * lexical) if semantic_scores else lexical
        combined.append((score, index))
    combined.sort(key=lambda value: value[0], reverse=True)
    return [chunks[index] for _, index in combined[:top_k]]


def _lexical_scores(query: str, chunks: list[dict[str, Any]]) -> list[float]:
    query_terms = [item for item in jieba.cut(query or "") if item.strip()]
    if not query_terms:
        return [0.0] * len(chunks)
    try:
        from rank_bm25 import BM25Okapi

        corpus = [list(jieba.cut(str(chunk.get("content") or ""))) for chunk in chunks]
        return [float(value) for value in BM25Okapi(corpus).get_scores(query_terms)]
    except Exception:
        normalized = " ".join(query_terms).casefold()
        return [float(str(chunk.get("content") or "").casefold().count(normalized)) for chunk in chunks]


async def _semantic_scores(instance: Any, query: str, chunks: list[dict[str, Any]]) -> list[float]:
    embedding = getattr(instance, "embedding_func", None) or getattr(instance.lightrag, "embedding_func", None)
    embedding = getattr(embedding, "func", embedding)
    if embedding is None or not chunks:
        return []
    try:
        vectors = await embedding([query, *[str(chunk.get("content") or "") for chunk in chunks]])
        values = list(vectors)
        if len(values) != len(chunks) + 1:
            return []
        query_vector = _as_vector(values[0])
        return [_cosine(query_vector, _as_vector(value)) for value in values[1:]]
    except Exception:
        return []


def _as_vector(value: Any) -> list[float]:
    if hasattr(value, "tolist"):
        value = value.tolist()
    return [float(item) for item in value]


def _cosine(left: list[float], right: list[float]) -> float:
    if not left or len(left) != len(right):
        return 0.0
    numerator = sum(a * b for a, b in zip(left, right))
    left_norm = math.sqrt(sum(a * a for a in left))
    right_norm = math.sqrt(sum(b * b for b in right))
    return numerator / (left_norm * right_norm) if left_norm and right_norm else 0.0
