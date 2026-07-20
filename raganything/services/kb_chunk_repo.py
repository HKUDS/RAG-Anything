"""Shared persisted-chunk reads for knowledge-base services and routes."""

from __future__ import annotations

import json
from typing import Any


class PersistedChunkQueryError(RuntimeError):
    """Raised when the durable chunk fallback cannot be queried."""


async def query_chunks_by_document_id(lightrag: Any, document_id: str) -> list[dict[str, Any]]:
    """Read a document's persisted chunks by ``full_doc_id`` from PostgreSQL.

    ``doc_status.chunks_list`` is a convenient index, but older and freshly
    persisted documents can temporarily have an empty list. The text-chunk
    store is the durable source of truth for that case.
    """
    try:
        from lightrag.kg.postgres_impl import PGKVStorage, namespace_to_table_name

        store = lightrag.text_chunks
        if not isinstance(store, PGKVStorage):
            return []
        table_name = namespace_to_table_name(store.namespace)
        sql = (
            f"SELECT id, content, tokens, chunk_order_index, file_path,"
            f" full_doc_id, llm_cache_list"
            f" FROM {table_name}"
            f" WHERE workspace = $1 AND full_doc_id = $2"
            f" ORDER BY chunk_order_index"
        )
        rows = await store.db.query(sql, [store.workspace, document_id], multirows=True)
        chunks: list[dict[str, Any]] = []
        for row in rows or []:
            if not isinstance(row, dict):
                continue
            chunk = dict(row)
            cache = chunk.get("llm_cache_list")
            if isinstance(cache, str):
                try:
                    chunk["llm_cache_list"] = json.loads(cache)
                except json.JSONDecodeError:
                    chunk["llm_cache_list"] = []
            chunks.append(chunk)
        return chunks
    except Exception as exc:
        raise PersistedChunkQueryError(
            f"Unable to query persisted chunks for document {document_id}"
        ) from exc
