"""Application-owned, knowledge-base-scoped tags for document chunks."""

from __future__ import annotations

import asyncio
import hashlib
import re
import unicodedata
from typing import Any, Iterable

from raganything.services.pg_state_repo import get_pg_pool

MAX_TAG_NAME_LENGTH = 32
MAX_TAGS_PER_CHUNK = 8
ASSIGNMENT_KIND_MANUAL = "manual"
ASSIGNMENT_KIND_AUTO_DOCUMENT = "auto_document"
ASSIGNMENT_KIND_AUTO_CHUNK = "auto_chunk"
_AUTO_ASSIGNMENT_KINDS = (
    ASSIGNMENT_KIND_AUTO_DOCUMENT,
    ASSIGNMENT_KIND_AUTO_CHUNK,
)
_tag_schema_ready = False
_tag_schema_lock = asyncio.Lock()


class TagValidationError(ValueError):
    """Raised when a tag request is outside the supported product limits."""


class TagDocumentChangedError(RuntimeError):
    """Raised when chunks changed or disappeared before automatic tag commit."""


def document_mutation_lock_key(kb_name: str, document_id: str) -> int:
    """Return the shared PostgreSQL advisory-lock key for one document."""
    return int.from_bytes(
        hashlib.sha256(f"{kb_name}\0{document_id}".encode()).digest()[:8],
        "big",
        signed=True,
    )


def normalize_tag_name(value: object) -> tuple[str, str]:
    display_name = re.sub(r"\s+", " ", unicodedata.normalize("NFKC", str(value or "")).strip())
    if not display_name:
        raise TagValidationError("tag name must not be empty")
    if len(display_name) > MAX_TAG_NAME_LENGTH:
        raise TagValidationError(f"tag name must be at most {MAX_TAG_NAME_LENGTH} characters")
    return display_name, display_name.casefold()


def _unique_tag_names(values: Iterable[object]) -> list[tuple[str, str]]:
    unique: list[tuple[str, str]] = []
    seen: set[str] = set()
    for value in values:
        display_name, normalized_name = normalize_tag_name(value)
        if normalized_name not in seen:
            unique.append((display_name, normalized_name))
            seen.add(normalized_name)
    if len(unique) > MAX_TAGS_PER_CHUNK:
        raise TagValidationError(f"a chunk may have at most {MAX_TAGS_PER_CHUNK} tags")
    return unique


def _tag(row: Any) -> dict[str, Any]:
    tag = {"id": int(row["id"]), "name": row["display_name"]}
    if "assignment_kind" in row:
        tag["assignment_kind"] = row["assignment_kind"]
    return tag


async def ensure_tag_schema() -> None:
    """Create and upgrade tag tables for installations that predate migrations."""
    global _tag_schema_ready
    if _tag_schema_ready:
        return
    async with _tag_schema_lock:
        if _tag_schema_ready:
            return
        pool = get_pg_pool()
        async with pool.acquire() as conn:
            await conn.execute(
                """
                CREATE TABLE IF NOT EXISTS kb_tags (
                    id BIGSERIAL PRIMARY KEY,
                    kb_name TEXT NOT NULL,
                    normalized_name TEXT NOT NULL,
                    display_name TEXT NOT NULL,
                    created_by INTEGER NOT NULL DEFAULT 0,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    CONSTRAINT uq_kb_tags_normalized_name UNIQUE (kb_name, normalized_name)
                )
                """
            )
            await conn.execute(
                """
                CREATE TABLE IF NOT EXISTS chunk_tag_assignments (
                    tag_id BIGINT NOT NULL REFERENCES kb_tags(id) ON DELETE CASCADE,
                    kb_name TEXT NOT NULL,
                    document_id TEXT NOT NULL,
                    chunk_id TEXT NOT NULL,
                    created_by INTEGER NOT NULL DEFAULT 0,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    assignment_kind TEXT NOT NULL DEFAULT 'manual',
                    PRIMARY KEY (tag_id, kb_name, document_id, chunk_id)
                )
                """
            )
            await conn.execute(
                "ALTER TABLE chunk_tag_assignments "
                "ADD COLUMN IF NOT EXISTS assignment_kind TEXT NOT NULL DEFAULT 'manual'"
            )
            await conn.execute(
                """
                DO $$
                BEGIN
                    ALTER TABLE chunk_tag_assignments
                    ADD CONSTRAINT chk_chunk_tag_assignment_kind
                    CHECK (assignment_kind IN ('manual', 'auto_document', 'auto_chunk'));
                EXCEPTION WHEN duplicate_object THEN NULL;
                END $$
                """
            )
            await conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_kb_tags_lookup "
                "ON kb_tags (kb_name, normalized_name)"
            )
            await conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_chunk_tag_assignments_chunk "
                "ON chunk_tag_assignments (kb_name, document_id, chunk_id)"
            )
            await conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_chunk_tag_assignments_tag "
                "ON chunk_tag_assignments (kb_name, tag_id, document_id, chunk_id)"
            )
            await conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_chunk_tag_assignments_kind "
                "ON chunk_tag_assignments (kb_name, document_id, assignment_kind, chunk_id)"
            )
        _tag_schema_ready = True


async def _get_tag_pool() -> Any:
    await ensure_tag_schema()
    return get_pg_pool()


async def list_tags(
    kb_name: str,
    query: str = "",
    limit: int = 100,
    offset: int = 0,
) -> list[dict[str, Any]]:
    query = re.sub(r"\s+", " ", unicodedata.normalize("NFKC", query or "").strip()).casefold()
    pool = await _get_tag_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT t.id, t.display_name,
                   COUNT(DISTINCT a.document_id)::int AS document_count,
                   COUNT(a.chunk_id)::int AS chunk_count
            FROM kb_tags t
            LEFT JOIN chunk_tag_assignments a
              ON a.tag_id = t.id AND a.kb_name = t.kb_name
            WHERE t.kb_name = $1
              AND ($2 = '' OR t.normalized_name LIKE '%' || $2 || '%')
            GROUP BY t.id, t.display_name
            ORDER BY document_count DESC, chunk_count DESC, t.display_name ASC, t.id ASC
            LIMIT $3 OFFSET $4
            """,
            kb_name,
            query,
            max(1, min(int(limit or 100), 200)),
            max(0, min(int(offset or 0), 1_000_000)),
        )
    return [
        {"id": int(row["id"]), "name": row["display_name"], "document_count": row["document_count"], "chunk_count": row["chunk_count"]}
        for row in rows
    ]


async def get_tag(kb_name: str, tag_id: int) -> dict[str, Any] | None:
    pool = await _get_tag_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT id, display_name FROM kb_tags WHERE kb_name = $1 AND id = $2",
            kb_name,
            int(tag_id),
        )
    return _tag(row) if row else None


async def get_chunk_tags(kb_name: str, document_id: str, chunk_id: str) -> list[dict[str, Any]]:
    pool = await _get_tag_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT t.id, t.display_name, a.assignment_kind
            FROM chunk_tag_assignments a
            JOIN kb_tags t ON t.id = a.tag_id
            WHERE a.kb_name = $1 AND a.document_id = $2 AND a.chunk_id = $3
            ORDER BY t.display_name ASC
            """,
            kb_name,
            document_id,
            chunk_id,
        )
    return [_tag(row) for row in rows]


async def get_tags_for_chunks(kb_name: str, document_id: str, chunk_ids: Iterable[str]) -> dict[str, list[dict[str, Any]]]:
    ids = [str(value) for value in chunk_ids if value]
    if not ids:
        return {}
    pool = await _get_tag_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT a.chunk_id, t.id, t.display_name, a.assignment_kind
            FROM chunk_tag_assignments a
            JOIN kb_tags t ON t.id = a.tag_id
            WHERE a.kb_name = $1 AND a.document_id = $2 AND a.chunk_id = ANY($3::text[])
            ORDER BY t.display_name ASC
            """,
            kb_name,
            document_id,
            ids,
        )
    result: dict[str, list[dict[str, Any]]] = {item_id: [] for item_id in ids}
    for row in rows:
        result.setdefault(str(row["chunk_id"]), []).append(_tag(row))
    return result


async def replace_chunk_tags(
    kb_name: str,
    document_id: str,
    chunk_id: str,
    tag_names: Iterable[object],
    *,
    user_id: int,
) -> list[dict[str, Any]]:
    names = _unique_tag_names(tag_names)
    pool = await _get_tag_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            await conn.execute(
                "SELECT pg_advisory_xact_lock($1)",
                document_mutation_lock_key(kb_name, document_id),
            )
            existing_rows = await conn.fetch(
                """
                SELECT a.tag_id, t.normalized_name
                FROM chunk_tag_assignments a
                JOIN kb_tags t ON t.id = a.tag_id
                WHERE a.kb_name = $1 AND a.document_id = $2 AND a.chunk_id = $3
                """,
                kb_name,
                document_id,
                chunk_id,
            )
            requested_names = {normalized_name for _, normalized_name in names}
            removed_ids = [
                int(row["tag_id"])
                for row in existing_rows
                if row["normalized_name"] not in requested_names
            ]
            if removed_ids:
                await conn.execute(
                    """
                    DELETE FROM chunk_tag_assignments
                    WHERE kb_name = $1 AND document_id = $2 AND chunk_id = $3
                      AND tag_id = ANY($4::bigint[])
                    """,
                    kb_name,
                    document_id,
                    chunk_id,
                    removed_ids,
                )
            if requested_names:
                await conn.execute(
                    """
                    UPDATE chunk_tag_assignments a
                    SET assignment_kind = $5, created_by = $6
                    FROM kb_tags t
                    WHERE a.tag_id = t.id
                      AND a.kb_name = $1 AND a.document_id = $2 AND a.chunk_id = $3
                      AND t.normalized_name = ANY($4::text[])
                    """,
                    kb_name,
                    document_id,
                    chunk_id,
                    list(requested_names),
                    ASSIGNMENT_KIND_MANUAL,
                    int(user_id or 0),
                )
            existing_names = {row["normalized_name"] for row in existing_rows}
            tags: list[dict[str, Any]] = []
            for display_name, normalized_name in names:
                if normalized_name in existing_names:
                    continue
                row = await _upsert_tag(
                    conn, kb_name, display_name, normalized_name, user_id
                )
                await conn.execute(
                    """
                    INSERT INTO chunk_tag_assignments
                    (tag_id, kb_name, document_id, chunk_id, created_by, assignment_kind)
                    VALUES ($1, $2, $3, $4, $5, $6)
                    ON CONFLICT DO NOTHING
                    """,
                    int(row["id"]),
                    kb_name,
                    document_id,
                    chunk_id,
                    int(user_id or 0),
                    ASSIGNMENT_KIND_MANUAL,
                )
            rows = await conn.fetch(
                """
                SELECT t.id, t.display_name, a.assignment_kind
                FROM chunk_tag_assignments a
                JOIN kb_tags t ON t.id = a.tag_id
                WHERE a.kb_name = $1 AND a.document_id = $2 AND a.chunk_id = $3
                """,
                kb_name,
                document_id,
                chunk_id,
            )
            tags = [_tag(row) for row in rows]
            if len(tags) > MAX_TAGS_PER_CHUNK:
                raise TagValidationError(
                    f"a chunk may have at most {MAX_TAGS_PER_CHUNK} tags"
                )
            await _delete_orphaned_tags(conn, kb_name)
    return sorted(tags, key=lambda value: value["name"])


async def replace_automatic_document_tags(
    kb_name: str,
    document_id: str,
    document_tag_names: Iterable[object],
    chunk_tag_names: dict[str, Iterable[object]],
    *,
    user_id: int,
    document_tag_names_by_chunk: dict[str, Iterable[object]] | None = None,
) -> dict[str, Any]:
    """Atomically replace generated tags while retaining all manual tag choices."""
    document_names = _unique_tag_names(document_tag_names)
    chunk_names = {
        str(chunk_id): _unique_tag_names(names)
        for chunk_id, names in chunk_tag_names.items()
        if chunk_id
    }
    scoped_document_names = (
        {
            str(chunk_id): _unique_tag_names(names)
            for chunk_id, names in document_tag_names_by_chunk.items()
            if chunk_id
        }
        if document_tag_names_by_chunk is not None
        else {chunk_id: document_names for chunk_id in chunk_names}
    )
    pool = await _get_tag_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            await conn.execute(
                "SELECT pg_advisory_xact_lock($1)",
                document_mutation_lock_key(kb_name, document_id),
            )
            workspace = (
                "./rag_storage" if kb_name == "default" else f"./rag_storage_{kb_name}"
            )
            persisted_rows = await conn.fetch(
                """
                SELECT id FROM LIGHTRAG_DOC_CHUNKS
                WHERE workspace = $1 AND full_doc_id = $2
                """,
                workspace,
                document_id,
            )
            persisted_chunk_ids = {str(row["id"]) for row in persisted_rows}
            planned_chunk_ids = set(chunk_names)
            if persisted_chunk_ids != planned_chunk_ids:
                raise TagDocumentChangedError(
                    "document chunks changed before automatic tags were committed"
                )
            manual_rows = await conn.fetch(
                """
                SELECT a.chunk_id, t.normalized_name
                FROM chunk_tag_assignments a
                JOIN kb_tags t ON t.id = a.tag_id
                WHERE a.kb_name = $1 AND a.document_id = $2
                  AND a.assignment_kind = $3
                """,
                kb_name,
                document_id,
                ASSIGNMENT_KIND_MANUAL,
            )
            manual_names: dict[str, set[str]] = {}
            for row in manual_rows:
                manual_names.setdefault(str(row["chunk_id"]), set()).add(row["normalized_name"])

            await conn.execute(
                """
                DELETE FROM chunk_tag_assignments
                WHERE kb_name = $1 AND document_id = $2
                  AND assignment_kind = ANY($3::text[])
                """,
                kb_name,
                document_id,
                list(_AUTO_ASSIGNMENT_KINDS),
            )

            all_names = {normalized: display for display, normalized in document_names}
            for names in scoped_document_names.values():
                all_names.update({normalized: display for display, normalized in names})
            for names in chunk_names.values():
                all_names.update({normalized: display for display, normalized in names})
            tag_id_by_name: dict[str, int] = {}
            for normalized_name, display_name in all_names.items():
                row = await _upsert_tag(
                    conn, kb_name, display_name, normalized_name, user_id
                )
                tag_id_by_name[normalized_name] = int(row["id"])

            assignment_rows: list[tuple[int, str, str, str, int, str]] = []
            skipped = 0
            for chunk_id, local_names in chunk_names.items():
                selected = set(manual_names.get(chunk_id, set()))
                for display_name, normalized_name in scoped_document_names.get(chunk_id, []):
                    if normalized_name in selected:
                        continue
                    if len(selected) >= MAX_TAGS_PER_CHUNK:
                        skipped += 1
                        continue
                    selected.add(normalized_name)
                    assignment_rows.append((
                        tag_id_by_name[normalized_name], kb_name, document_id,
                        chunk_id, int(user_id or 0), ASSIGNMENT_KIND_AUTO_DOCUMENT,
                    ))
                for display_name, normalized_name in local_names:
                    if normalized_name in selected:
                        continue
                    if len(selected) >= MAX_TAGS_PER_CHUNK:
                        skipped += 1
                        continue
                    selected.add(normalized_name)
                    assignment_rows.append((
                        tag_id_by_name[normalized_name], kb_name, document_id,
                        chunk_id, int(user_id or 0), ASSIGNMENT_KIND_AUTO_CHUNK,
                    ))
            if assignment_rows:
                await conn.executemany(
                    """
                    INSERT INTO chunk_tag_assignments
                    (tag_id, kb_name, document_id, chunk_id, created_by, assignment_kind)
                    VALUES ($1, $2, $3, $4, $5, $6)
                    ON CONFLICT DO NOTHING
                    """,
                    assignment_rows,
                )
            coverage_rows = await conn.fetch(
                """
                SELECT DISTINCT chunk_id
                FROM chunk_tag_assignments
                WHERE kb_name = $1 AND document_id = $2
                  AND chunk_id = ANY($3::text[])
                  AND assignment_kind = ANY($4::text[])
                """,
                kb_name,
                document_id,
                list(chunk_names),
                list(_AUTO_ASSIGNMENT_KINDS),
            )
            await _delete_orphaned_tags(conn, kb_name)
    return {
        "assigned": len(assignment_rows),
        "skipped": skipped,
        "document_tags": len(document_names),
        "chunk_tags": sum(len(value) for value in chunk_names.values()),
        "tagged_chunk_ids": [str(row["chunk_id"]) for row in coverage_rows],
    }


async def move_chunk_tags(kb_name: str, document_id: str, old_chunk_id: str, new_chunk_id: str) -> None:
    if old_chunk_id == new_chunk_id:
        return
    pool = await _get_tag_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            await conn.execute(
                """
                DELETE FROM chunk_tag_assignments old_assignment
                USING chunk_tag_assignments new_assignment
                WHERE old_assignment.kb_name = $1
                  AND old_assignment.document_id = $2
                  AND old_assignment.chunk_id = $3
                  AND new_assignment.kb_name = old_assignment.kb_name
                  AND new_assignment.document_id = old_assignment.document_id
                  AND new_assignment.chunk_id = $4
                  AND new_assignment.tag_id = old_assignment.tag_id
                """,
                kb_name,
                document_id,
                old_chunk_id,
                new_chunk_id,
            )
            await conn.execute(
                """
                UPDATE chunk_tag_assignments
                SET chunk_id = $4
                WHERE kb_name = $1 AND document_id = $2 AND chunk_id = $3
                """,
                kb_name,
                document_id,
                old_chunk_id,
                new_chunk_id,
            )


async def delete_chunk_tags(kb_name: str, document_id: str, chunk_id: str) -> None:
    pool = await _get_tag_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            await conn.execute(
                "DELETE FROM chunk_tag_assignments WHERE kb_name = $1 AND document_id = $2 AND chunk_id = $3",
                kb_name,
                document_id,
                chunk_id,
            )
            await _delete_orphaned_tags(conn, kb_name)


async def delete_document_tags(kb_name: str, document_id: str) -> None:
    pool = await _get_tag_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            await conn.execute(
                "SELECT pg_advisory_xact_lock($1)",
                document_mutation_lock_key(kb_name, document_id),
            )
            await conn.execute(
                "DELETE FROM chunk_tag_assignments WHERE kb_name = $1 AND document_id = $2",
                kb_name,
                document_id,
            )
            await _delete_orphaned_tags(conn, kb_name)


async def delete_kb_tags(kb_name: str) -> None:
    pool = await _get_tag_pool()
    async with pool.acquire() as conn:
        await conn.execute("DELETE FROM kb_tags WHERE kb_name = $1", kb_name)


async def get_tag_assignments(kb_name: str, tag_id: int) -> tuple[dict[str, Any] | None, list[dict[str, Any]]]:
    tag = await get_tag(kb_name, tag_id)
    if not tag:
        return None, []
    pool = await _get_tag_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT document_id, chunk_id
            FROM chunk_tag_assignments
            WHERE kb_name = $1 AND tag_id = $2
            ORDER BY document_id, chunk_id
            """,
            kb_name,
            int(tag_id),
        )
    return tag, [{"document_id": row["document_id"], "chunk_id": row["chunk_id"]} for row in rows]


async def _delete_orphaned_tags(conn: Any, kb_name: str) -> None:
    await conn.execute(
        """
        DELETE FROM kb_tags t
        WHERE t.kb_name = $1
          AND NOT EXISTS (
              SELECT 1 FROM chunk_tag_assignments a
              WHERE a.tag_id = t.id AND a.kb_name = t.kb_name
          )
        """,
        kb_name,
    )


async def _upsert_tag(
    conn: Any,
    kb_name: str,
    display_name: str,
    normalized_name: str,
    user_id: int,
) -> Any:
    return await conn.fetchrow(
        """
        INSERT INTO kb_tags (kb_name, normalized_name, display_name, created_by, updated_at)
        VALUES ($1, $2, $3, $4, NOW())
        ON CONFLICT (kb_name, normalized_name)
        DO UPDATE SET updated_at = NOW()
        RETURNING id, display_name
        """,
        kb_name,
        normalized_name,
        display_name,
        int(user_id or 0),
    )
