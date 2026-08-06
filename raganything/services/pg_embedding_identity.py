"""Atomic PostgreSQL registration and preflight for LightRAG text vectors."""

from __future__ import annotations

import json
import os
from typing import Any, Mapping

from raganything.services.pg_state_repo import get_pg_pool

VECTOR_TABLES = (
    "LIGHTRAG_VDB_CHUNKS",
    "LIGHTRAG_VDB_ENTITY",
    "LIGHTRAG_VDB_RELATION",
)


def assert_workspace_override(workspace: str) -> None:
    override = str(os.getenv("PG_WORKSPACE") or "").strip()
    if override and override != workspace:
        raise RuntimeError("embedding_workspace_override_rejected")


async def _legacy_rows(conn, table: str, workspace: str) -> int:
    actual = await conn.fetchrow(
        "SELECT t.table_name FROM information_schema.tables t "
        "WHERE t.table_schema='public' AND lower(t.table_name)=lower($1) "
        "AND EXISTS (SELECT 1 FROM information_schema.columns c "
        "WHERE c.table_schema='public' AND c.table_name=t.table_name "
        "AND c.column_name='workspace') "
        "LIMIT 1",
        table,
    )
    if actual is None:
        return 0
    actual_name = str(actual["table_name"])
    return int(
        await conn.fetchval(
            f'SELECT COUNT(*) FROM "{actual_name}" WHERE workspace=$1', workspace
        ) or 0
    )


async def ensure_kb_embedding_identity(
    workspace: str, identity: Mapping[str, Any], *, pool=None
) -> None:
    """Register one identity per workspace before LightRAG initializes."""
    assert_workspace_override(workspace)
    pool = pool or get_pg_pool()
    identity_hash = str(identity.get("identity_hash") or "")
    if not identity_hash:
        raise RuntimeError("text_embedding_identity_invalid")
    async with pool.acquire() as conn:
        async with conn.transaction():
            await conn.execute("SELECT pg_advisory_xact_lock(hashtext($1))", workspace)
            for table in VECTOR_TABLES:
                if await _legacy_rows(conn, table, workspace):
                    raise RuntimeError("embedding_legacy_storage_incompatible")
            row = await conn.fetchrow(
                "SELECT identity_hash, identity FROM kb_text_embedding_identities WHERE workspace=$1 FOR UPDATE",
                workspace,
            )
            if row is None:
                await conn.execute(
                    "INSERT INTO kb_text_embedding_identities(workspace,identity_hash,identity) VALUES($1,$2,$3::jsonb)",
                    workspace, identity_hash, json.dumps(dict(identity), sort_keys=True),
                )
                return
            stored_identity = row["identity"]
            if isinstance(stored_identity, str):
                try:
                    stored_identity = json.loads(stored_identity)
                except (TypeError, ValueError):
                    stored_identity = None
            if (
                str(row["identity_hash"]) != identity_hash
                or stored_identity != dict(identity)
            ):
                raise RuntimeError("embedding_identity_conflict")


async def read_embedding_identity_diagnostics(*, pool=None) -> dict[str, Any]:
    """Read-only, credential-safe inventory of registrations and vector tables."""
    pool = pool or get_pg_pool()
    lowercase_vector_tables = {t.lower() for t in VECTOR_TABLES}
    async with pool.acquire() as conn:
        async with conn.transaction(readonly=True):
            rows = await conn.fetch(
                "SELECT workspace, identity_hash, identity, updated_at FROM kb_text_embedding_identities ORDER BY workspace"
            )
            tables = []
            discovered = await conn.fetch(
                "SELECT c.relname AS table_name FROM pg_catalog.pg_class c "
                "JOIN pg_catalog.pg_namespace n ON n.oid=c.relnamespace "
                "WHERE n.nspname='public' AND c.relname ILIKE 'LIGHTRAG_VDB_%' "
                "AND c.relkind='r' ORDER BY c.relname"
            )
            for row in discovered:
                table = str(row["table_name"])
                count = int(await conn.fetchval(f'SELECT COUNT(*) FROM "{table}"') or 0)
                tables.append(
                    {
                        "table": table,
                        "rows": count,
                        "legacy": table.lower() in lowercase_vector_tables,
                    }
                )
    return {
        "registrations": [
            {"workspace": str(row["workspace"]), "identity_hash": str(row["identity_hash"]),
             "identity": row["identity"], "updated_at": row["updated_at"].isoformat() if hasattr(row["updated_at"], "isoformat") else str(row["updated_at"])}
            for row in rows
        ],
        "vector_tables": tables,
    }


__all__ = ["assert_workspace_override", "ensure_kb_embedding_identity", "read_embedding_identity_diagnostics"]