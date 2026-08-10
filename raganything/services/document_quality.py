"""Shared document content-readiness checks."""

from __future__ import annotations

import logging
import os
import json
import re
from pathlib import Path
from typing import Any

_logger = logging.getLogger(__name__)

_PATH_SUFFIXES = {
    ".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".tif", ".tiff",
    ".pdf", ".doc", ".docx", ".ppt", ".pptx", ".xls", ".xlsx",
}
_WINDOWS_PATH = re.compile(r"^[a-zA-Z]:[\\/]")
_PLACEHOLDER_LINE = re.compile(
    r"^(?:\[第\s*\d+\s*页\]|\[(?:📷\s*)?图片\]|"
    r"\[(?:图片路径|image path)\s*[:：].+\])$",
    re.IGNORECASE,
)
_MEDIA_REFERENCE_LINE = re.compile(
    r"^\[?\s*(?:image\s+path|image)\s*[:：]\s*.+?\]?$",
    re.IGNORECASE,
)


def is_path_placeholder(content: object) -> bool:
    text = str(content or "").strip().strip("`\"'")
    if not text:
        return False
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if lines and all(
        _PLACEHOLDER_LINE.match(line) or _MEDIA_REFERENCE_LINE.match(line)
        for line in lines
    ):
        return True
    if "\n" in text or "\r" in text:
        return False
    normalized = text.replace("\\", "/")
    suffix = Path(normalized).suffix.lower()
    looks_path = (
        _WINDOWS_PATH.match(text) is not None
        or normalized.startswith(("./", "../", "/"))
        or "/output" in normalized.casefold()
        or "/uploads/" in normalized.casefold()
    )
    return looks_path and suffix in _PATH_SUFFIXES


def chunk_content(row: Any) -> str:
    if not isinstance(row, dict):
        return ""
    for key in ("content", "text", "chunk_content"):
        value = row.get(key)
        if value:
            return str(value)
    return ""


def _nanovector_workspace_dir(kb_name: str) -> Path:
    """Return the NanoVectorDB directory for the requested knowledge base."""
    default_dir = Path(os.getenv("WORKING_DIR", "./rag_storage"))
    if kb_name == "default":
        return default_dir
    return default_dir.with_name(f"{default_dir.name}_{kb_name}")


def _nanovector_vector_paths(kb_name: str) -> tuple[Path, ...]:
    """Return compatible NanoVectorDB paths, including LightRAG's nested form.

    LightRAG appends its non-empty ``workspace`` to ``working_dir`` for the
    file-backed vector store.  Existing deployments therefore have either
    ``<kb>/vdb_chunks.json`` or ``<kb>/<kb>/vdb_chunks.json`` depending on the
    initialization version.
    """
    workspace_dir = _nanovector_workspace_dir(kb_name)
    return (
        workspace_dir / "vdb_chunks.json",
        workspace_dir / workspace_dir.name / "vdb_chunks.json",
    )


async def evaluate_content_readiness(
    kb_name: str,
    chunk_ids: list[str],
    text_chunks: dict[str, Any],
) -> dict[str, Any]:
    expected = {str(value) for value in chunk_ids if value}
    present = {chunk_id for chunk_id in expected if chunk_id in text_chunks}
    invalid = {
        chunk_id for chunk_id in present
        if not chunk_content(text_chunks[chunk_id]).strip()
        or is_path_placeholder(chunk_content(text_chunks[chunk_id]))
    }
    vector_ids: set[str] = set()
    if expected:
        # PostgreSQL is authoritative when the application has initialized a
        # PG pool.  JSON/NanoVectorDB deployments use the local vector file.
        pg_checked = False
        try:
            from raganything.services.pg_embedding_identity import resolve_vector_chunk_table
            from raganything.services.pg_state_repo import get_pg_pool

            pool = get_pg_pool()
            workspace = "./rag_storage" if kb_name == "default" else f"./rag_storage_{kb_name}"
            chunk_table = await resolve_vector_chunk_table(pool, workspace)
            if chunk_table is None:
                _logger.warning(
                    "vector chunk table not found: kb=%s workspace=%s",
                    kb_name, workspace,
                )
            else:
                rows = await pool.fetch(
                    f'SELECT id FROM "{chunk_table}" WHERE workspace=$1 AND id=ANY($2::text[])',
                    workspace, list(expected),
                )
                vector_ids = {str(row["id"]) for row in rows}
                pg_checked = True
        except Exception:
            pg_checked = False

        if not pg_checked:
            for vector_path in _nanovector_vector_paths(kb_name):
                try:
                    payload = json.loads(vector_path.read_text(encoding="utf-8"))
                    rows = payload.get("data", []) if isinstance(payload, dict) else payload
                    if isinstance(rows, list):
                        vector_ids.update(
                            str(row.get("__id__") or row.get("id"))
                            for row in rows
                            if isinstance(row, dict)
                            and (row.get("__id__") or row.get("id")) in expected
                        )
                except (OSError, TypeError, ValueError, json.JSONDecodeError):
                    continue
    ready = bool(expected) and present == expected and vector_ids == expected and not invalid
    return {
        "ready": ready,
        "expected_count": len(expected),
        "text_count": len(present),
        "vector_count": len(vector_ids),
        "missing_text_ids": sorted(expected - present),
        "missing_vector_ids": sorted(expected - vector_ids),
        "invalid_content_ids": sorted(invalid),
    }


async def cleanup_failed_invalid_residue(
    workspace: str,
    doc_id: str,
    *,
    expected_filename: str = "",
    allow_task_id: str = "",
    require_zero_vectors: bool = True,
    require_path_placeholders: bool = True,
) -> dict[str, Any]:
    """Delete only a verified zero-vector, path-placeholder failed document."""
    from raganything.services.pg_state_repo import get_pg_pool

    pool = get_pg_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            await conn.execute(
                "SELECT pg_advisory_xact_lock(hashtextextended($1, 0))",
                f"kb:{workspace}",
            )
            await conn.execute(
                "SELECT pg_advisory_xact_lock(hashtextextended($1, 0))",
                f"doc:{workspace}:{doc_id}",
            )
            status = await conn.fetchrow(
                "SELECT id,file_path,status,chunks_count FROM LIGHTRAG_DOC_STATUS "
                "WHERE workspace=$1 AND id=$2 FOR UPDATE",
                workspace, doc_id,
            )
            if not status:
                raise ValueError("document status does not exist")
            if str(status["status"]).lower() != "failed":
                raise ValueError("document is not explicitly failed")
            stored_filename = os.path.basename(str(status["file_path"] or ""))
            if expected_filename and stored_filename != expected_filename:
                raise ValueError("document filename does not match cleanup request")
            kb_name = "default" if workspace == "./rag_storage" else workspace.removeprefix("./rag_storage_")
            active_upload = await conn.fetchval(
                "SELECT EXISTS(SELECT 1 FROM uploaded_files WHERE kb_name=$1 AND filename=$2 "
                "AND status IN ('queued','processing','retry_wait') AND task_id IS DISTINCT FROM $3)",
                kb_name, stored_filename, allow_task_id or None,
            )
            active_retry = await conn.fetchval(
                "SELECT EXISTS(SELECT 1 FROM upload_retry_jobs r JOIN uploaded_files u ON u.id=r.upload_id "
                "WHERE u.kb_name=$1 AND u.filename=$2 AND r.status='running' AND r.lease_until>NOW() "
                "AND r.task_id IS DISTINCT FROM $3)",
                kb_name, stored_filename, allow_task_id or None,
            )
            if active_upload or active_retry:
                raise ValueError("document has an active upload or retry lease")
            chunks = await conn.fetch(
                "SELECT id,content FROM LIGHTRAG_DOC_CHUNKS WHERE workspace=$1 AND full_doc_id=$2 FOR UPDATE",
                workspace, doc_id,
            )
            chunk_ids = [str(row["id"]) for row in chunks]
            from raganything.services.pg_embedding_identity import resolve_vector_chunk_table
            chunk_table = await resolve_vector_chunk_table(conn, workspace)
            vector_count = 0
            if chunk_table is not None:
                vector_count = await conn.fetchval(
                    f'SELECT COUNT(*) FROM "{chunk_table}" WHERE workspace=$1 AND full_doc_id=$2',
                    workspace, doc_id,
                )
            actual_vectors = int(vector_count or 0)
            if require_zero_vectors and actual_vectors != 0:
                raise ValueError("document has chunk vectors and is not invalid residue")
            if not require_zero_vectors and chunks and actual_vectors >= len(chunks):
                raise ValueError("document has complete chunk vector coverage")
            if require_path_placeholders and (
                not chunks or not all(is_path_placeholder(row["content"]) for row in chunks)
            ):
                raise ValueError("document content is not entirely path placeholders")

            counts: dict[str, int] = {}
            delete_operations = [
                ("chunk_tag_assignments", "DELETE FROM chunk_tag_assignments WHERE kb_name=$1 AND document_id=$2", (kb_name, doc_id)),
                ("document_tag_jobs", "DELETE FROM document_tag_jobs WHERE kb_name=$1 AND doc_id=$2", (kb_name, doc_id)),
                ("document_repair_jobs", "DELETE FROM document_repair_jobs WHERE kb_name=$1 AND doc_id=$2", (kb_name, doc_id)),
                ("doc_chunks", "DELETE FROM LIGHTRAG_DOC_CHUNKS WHERE workspace=$1 AND full_doc_id=$2", (workspace, doc_id)),
                ("doc_full", "DELETE FROM LIGHTRAG_DOC_FULL WHERE workspace=$1 AND id=$2", (workspace, doc_id)),
                ("doc_status", "DELETE FROM LIGHTRAG_DOC_STATUS WHERE workspace=$1 AND id=$2", (workspace, doc_id)),
            ]
            if chunk_table is not None:
                delete_operations.append(
                    ("vdb_chunks", f'DELETE FROM "{chunk_table}" WHERE workspace=$1 AND full_doc_id=$2', (workspace, doc_id))
                )
            for table, sql, args in delete_operations:
                result = await conn.execute(sql, *args)
                counts[table] = int(result.split()[-1])

            if chunk_ids:
                for table in ("LIGHTRAG_ENTITY_CHUNKS", "LIGHTRAG_RELATION_CHUNKS"):
                    await conn.execute(
                        f"""
                        UPDATE {table} SET chunk_ids=(
                            SELECT COALESCE(jsonb_agg(value), '[]'::jsonb)
                            FROM jsonb_array_elements_text(chunk_ids) value
                            WHERE NOT (value = ANY($2::text[]))
                        ), update_time=NOW()
                        WHERE workspace=$1 AND chunk_ids ?| $2::text[]
                        """,
                        workspace, chunk_ids,
                    )
                    await conn.execute(
                        f"DELETE FROM {table} WHERE workspace=$1 AND jsonb_array_length(chunk_ids)=0",
                        workspace,
                    )
            await conn.execute(
                "DELETE FROM kb_tags t WHERE t.kb_name=$1 AND NOT EXISTS "
                "(SELECT 1 FROM chunk_tag_assignments a WHERE a.kb_name=t.kb_name AND a.tag_id=t.id)",
                kb_name,
            )
            return {
                "workspace": workspace,
                "doc_id": doc_id,
                "filename": stored_filename,
                "preserved_upload": True,
                "counts": counts,
            }
