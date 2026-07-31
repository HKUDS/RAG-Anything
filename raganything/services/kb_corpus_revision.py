"""Durable, replayable KB corpus revision mutations."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
import os
from typing import TypeVar

from raganything.services.pg_state_repo import get_pg_pool

_Result = TypeVar("_Result")


async def begin_corpus_mutation(kb: str, mutation_id: str, mutation_kind: str) -> None:
    async with get_pg_pool().acquire() as conn:
        async with conn.transaction():
            await conn.execute(
                "SELECT pg_advisory_xact_lock(hashtext($1))", f"kb-corpus:{kb}"
            )
            await conn.execute(
                "INSERT INTO kb_corpus_mutations(id,kb,mutation_kind,state) "
                "VALUES($1,$2,$3,'pending') ON CONFLICT (id) DO NOTHING",
                mutation_id,
                kb,
                mutation_kind,
            )


async def commit_corpus_mutation(kb: str, mutation_id: str) -> int:
    async with get_pg_pool().acquire() as conn:
        async with conn.transaction():
            await conn.execute(
                "SELECT pg_advisory_xact_lock(hashtext($1))", f"kb-corpus:{kb}"
            )
            changed = await conn.execute(
                "UPDATE kb_corpus_mutations SET state='committed',committed_at=NOW() "
                "WHERE id=$1 AND kb=$2 AND state='pending'",
                mutation_id,
                kb,
            )
            if changed == "UPDATE 1":
                row = await conn.fetchrow(
                    "UPDATE kb_metadata SET corpus_revision=corpus_revision+1,updated_at=NOW() "
                    "WHERE name=$1 RETURNING corpus_revision",
                    kb,
                )
            else:
                row = await conn.fetchrow(
                    "SELECT corpus_revision FROM kb_metadata WHERE name=$1", kb
                )
            if row is None:
                raise RuntimeError("knowledge base metadata is unavailable")
            return int(row["corpus_revision"])


async def run_corpus_mutation(
    kb: str,
    mutation_id: str,
    mutation_kind: str,
    operation: Callable[[], Awaitable[_Result]],
) -> _Result:
    try:
        await begin_corpus_mutation(kb, mutation_id, mutation_kind)
    except RuntimeError as exc:
        pg_unavailable = "PG pool not initialized" in str(exc)
        is_production = os.getenv("RAGANYTHING_ENV", "development").strip().lower() == "production"
        if is_production or not pg_unavailable:
            raise
        return await operation()
    try:
        result = await operation()
    except BaseException:
        # The operation may span several stores. Keep the durable marker
        # pending so reconciliation conservatively invalidates caches even
        # when a later store failed after an earlier one committed.
        raise
    await commit_corpus_mutation(kb, mutation_id)
    return result


async def reconcile_pending_corpus_mutations() -> int:
    """Conservatively invalidate caches for mutations interrupted by a crash."""
    pool = get_pg_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT id,kb FROM kb_corpus_mutations WHERE state='pending' "
            "AND created_at < NOW()-INTERVAL '5 minutes' ORDER BY created_at"
        )
    for row in rows:
        await commit_corpus_mutation(str(row["kb"]), str(row["id"]))
    return len(rows)
