"""Read-only pgvector/HNSW capacity inspection without credential output."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
from pathlib import Path
from typing import Any


def _cgroup_memory() -> dict[str, str]:
    result: dict[str, str] = {}
    for name in ("memory.current", "memory.max", "memory.events"):
        path = Path("/sys/fs/cgroup") / name
        try:
            result[name] = path.read_text(encoding="utf-8").strip()
        except OSError:
            result[name] = "unavailable"
    return result


def _database_url() -> str:
    url = os.getenv("DATABASE_URL", "").strip()
    if not url:
        raise RuntimeError("DATABASE_URL is required; it is never printed")
    return url.replace("postgresql+asyncpg://", "postgresql://", 1)


async def collect_hnsw_health(database_url: str) -> dict[str, Any]:
    import asyncpg

    connection = await asyncpg.connect(database_url, timeout=10)
    try:
        vector_version = await connection.fetchval(
            "SELECT extversion FROM pg_extension WHERE extname='vector'"
        )
        settings = await connection.fetch(
            "SELECT name, setting, unit FROM pg_settings "
            "WHERE name = ANY($1::text[]) ORDER BY name",
            ["shared_buffers", "work_mem", "maintenance_work_mem", "max_connections"],
        )
        indexes = await connection.fetch(
            """
            SELECT ns.nspname AS schema_name, tbl.relname AS table_name,
                   idx.relname AS index_name, ind.indisvalid, ind.indisready,
                   pg_get_indexdef(ind.indexrelid) AS definition,
                   pg_relation_size(ind.indexrelid) AS bytes
            FROM pg_index ind
            JOIN pg_class idx ON idx.oid=ind.indexrelid
            JOIN pg_class tbl ON tbl.oid=ind.indrelid
            JOIN pg_namespace ns ON ns.oid=tbl.relnamespace
            JOIN pg_am am ON am.oid=idx.relam
            WHERE am.amname='hnsw'
            ORDER BY ns.nspname, tbl.relname, idx.relname
            """
        )
        tables = await connection.fetch(
            """
            SELECT schemaname AS schema_name, relname AS table_name,
                   n_live_tup, n_dead_tup, pg_total_relation_size(relid) AS bytes
            FROM pg_stat_user_tables
            WHERE lower(relname) IN ('lightrag_vdb_chunks', 'lightrag_vdb_entity',
                                     'lightrag_vdb_relation')
            ORDER BY schemaname, relname
            """
        )
        active_connections = await connection.fetchval(
            "SELECT count(*) FROM pg_stat_activity WHERE datname=current_database()"
        )
        database_bytes = await connection.fetchval(
            "SELECT pg_database_size(current_database())"
        )
        return {
            "pgvector_version": vector_version or "not_installed",
            "hnsw_indexes": [dict(row) for row in indexes],
            "vdb_tables": [dict(row) for row in tables],
            "settings": {row["name"]: f"{row['setting']}{row['unit'] or ''}" for row in settings},
            "active_connections": active_connections,
            "database_bytes": database_bytes,
            "cgroup_memory": _cgroup_memory(),
        }
    finally:
        await connection.close()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true", help="emit JSON (the default)")
    parser.parse_args()
    try:
        report = asyncio.run(collect_hnsw_health(_database_url()))
    except Exception as exc:
        message = str(exc)[:500] if isinstance(exc, RuntimeError) else "PostgreSQL health check failed"
        print(json.dumps({"status": "error", "message": message}))
        return 2
    print(json.dumps({"status": "ok", **report}, ensure_ascii=True, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
