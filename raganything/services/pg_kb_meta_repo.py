# -*- coding: utf-8 -*-
"""
═══════════════════════════════════════════════════════════════════════════════
PostgreSQL 知识库元数据仓库
═══════════════════════════════════════════════════════════════════════════════

【文件作用】
  知识库元数据的持久化存储。
  记录每个知识库的名称、标签、领域、创建者等基本信息。
  通过 pg_state_repo.get_pg_pool() 复用全局连接池。
  同时写入 JSON 镜像文件（rag_storage_kb_meta.json）作为回退。

【管理的数据库表】
  ┌──────────────────┬──────────────────────────────────────┐
  │ kb_metadata      │ 知识库元数据                          │
  │                  │ name（知识库名称，唯一标识）           │
  │                  │ label（显示标签/中文名）               │
  │                  │ domain（领域：general/autorepair/  │
  │                  │   education/legal/medical/...）       │
  │                  │ description（描述文本）               │
  │                  │ created_by（创建者 username）          │
  │                  │ created_at（创建时间 UTC）             │
  │                  │ updated_at（最后更新时间 UTC）         │
  └──────────────────┴──────────────────────────────────────┘

【核心函数】
  pg_load_kb_meta()                              → 加载所有 KB 元数据（字典）
  pg_save_kb_meta(name, label, domain, ...)      → 保存/更新单个 KB 元数据（upsert）
  pg_delete_kb_meta(name)                        → 删除单个 KB 元数据
  pg_list_kbs()                                  → 列出所有 KB（简化列表）
  pg_get_kb_meta(name)                           → 获取单个 KB 详细信息

【特殊逻辑】
  - pg_save_kb_meta() 使用 INSERT ON CONFLICT UPDATE（upsert），不删除已有记录
  - pg_delete_kb_meta() 只被 cleanup_kb_resources() 调用
  - kb_service.py 的 load_kb_meta() 先查 PG，查不到回退 JSON 文件
  - kb_service.py 的 save_kb_meta() 同时写入 PG 和 JSON 镜像

【替换了什么】
  - raganything/services/kb_service.py 中的 load_kb_meta() / save_kb_meta()
  - 旧 rag_storage_kb_meta.json（纯 JSON 文件存储）

【与其他文件的关系】
  使用 pg_state_repo.get_pg_pool() 获取连接
  被 raganything/services/kb_service.py 的 load_kb_meta/save_kb_meta 调用
  被 raganything/routers/knowledge.py 的 KB 列表/创建/删除端点调用
  对应迁移：migrations/003_p0_agent_kb_meta.sql

English:
  PostgreSQL-backed KB Metadata Repository.

  Replaces: raganything/services/kb_service.py load_kb_meta() / save_kb_meta()
            (JSON file: rag_storage_kb_meta.json)

  Uses the same shared connection pool as pg_state_repo.py and pg_auth_repo.py.

  Usage:
      from raganything.services.pg_kb_meta_repo import (
          pg_load_kb_meta, pg_save_kb_meta, pg_delete_kb_meta,
          pg_list_kbs, pg_get_kb_meta,
      )
"""

from __future__ import annotations

import logging
from typing import Any, Optional
from datetime import datetime, timezone

logger = logging.getLogger("rag_server.pg_kb_meta")


def _get_pool():
    """Get the shared PG pool. Raises RuntimeError if not initialized."""
    from raganything.services.pg_state_repo import get_pg_pool
    return get_pg_pool()


def _as_utc(value: datetime) -> datetime:
    """Return a timezone-aware UTC datetime; naive values are treated as UTC."""
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


# ═══════════════════════════════════════════════════════════════
# KB Metadata CRUD
# ═══════════════════════════════════════════════════════════════

async def pg_load_kb_meta() -> dict[str, Any]:
    """Load all KB metadata from PG.

    Returns:
        Dict keyed by KB name, matching the JSON format:
        {name: {name, display_name, domain, description, owner_id,
                owner_username, status, document_count, extra,
                created_at, updated_at}, ...}
    """
    pool = _get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT name, display_name, domain, description,
                   owner_id, owner_username, status, document_count,
                   extra, created_at, updated_at
            FROM kb_metadata
            ORDER BY updated_at DESC
            """
        )

    result = {}
    for row in rows:
        d = dict(row)
        # Convert timestamps to ISO strings for JSON compatibility
        for ts_field in ("created_at", "updated_at"):
            if isinstance(d.get(ts_field), datetime):
                d[ts_field] = d[ts_field].isoformat()
        # extra is already a dict from JSONB
        if isinstance(d.get("extra"), str):
            import json
            d["extra"] = json.loads(d["extra"])
        # Map column names back to legacy JSON keys
        name = d.pop("name")
        result[name] = {
            "name": d.pop("display_name", name),
            "created": d.pop("created_at", ""),
            "domain": d.pop("domain", "general"),
            "description": d.pop("description", ""),
            "owner_id": d.pop("owner_id", 0),
            "owner_username": d.pop("owner_username", ""),
            "status": d.pop("status", "ready"),
            "document_count": d.pop("document_count", 0),
            "updated_at": d.pop("updated_at", ""),
            "extra": d.pop("extra", {}),
            # Merge any remaining fields
            **d,
        }

    # If empty and no PG entries, return minimal default
    if not result:
        return {}

    return result


async def pg_get_kb_meta(name: str) -> Optional[dict[str, Any]]:
    """Get metadata for a single KB.

    Returns:
        KB meta dict or None if not found.
    """
    pool = _get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT name, display_name, domain, description,
                   owner_id, owner_username, status, document_count,
                   extra, created_at, updated_at
            FROM kb_metadata
            WHERE name = $1
            """,
            name,
        )

    if not row:
        return None

    d = dict(row)
    for ts_field in ("created_at", "updated_at"):
        if isinstance(d.get(ts_field), datetime):
            d[ts_field] = d[ts_field].isoformat()

    return {
        "name": d.get("display_name", name),
        "created": d.get("created_at", ""),
        "domain": d.get("domain", "general"),
        "description": d.get("description", ""),
        "owner_id": d.get("owner_id", 0),
        "owner_username": d.get("owner_username", ""),
        "status": d.get("status", "ready"),
        "document_count": d.get("document_count", 0),
        "updated_at": d.get("updated_at", ""),
        "extra": d.get("extra", {}),
    }


async def pg_save_kb_meta(name: str, meta: dict[str, Any]) -> None:
    """Save or update metadata for a single KB (upsert).

    Args:
        name: KB identifier (e.g. "default", "autorepair")
        meta: KB metadata dict with legacy JSON keys:
              {name, created, domain, description, owner_id,
               owner_username, status, document_count, extra, ...}
    """
    pool = _get_pool()
    now = datetime.now(timezone.utc)
    extra = meta.get("extra", {})
    if isinstance(extra, str):
        pass  # already a JSON string
    elif isinstance(extra, dict):
        import json as _json
        extra = _json.dumps(extra, ensure_ascii=False)
    else:
        extra = "{}"

    # Parse created_at from ISO string to datetime, or use now.
    # Naive strings are treated as UTC so TIMESTAMPTZ storage is unambiguous.
    created_str = meta.get("created", "")
    created_at = now
    if created_str:
        try:
            created_at = _as_utc(datetime.fromisoformat(created_str))
        except (ValueError, TypeError):
            created_at = now

    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO kb_metadata (
                name, display_name, domain, description,
                owner_id, owner_username, status, document_count,
                extra, created_at, updated_at
            ) VALUES (
                $1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11
            )
            ON CONFLICT (name) DO UPDATE SET
                display_name = EXCLUDED.display_name,
                domain = EXCLUDED.domain,
                description = EXCLUDED.description,
                owner_id = EXCLUDED.owner_id,
                owner_username = EXCLUDED.owner_username,
                status = EXCLUDED.status,
                document_count = EXCLUDED.document_count,
                extra = EXCLUDED.extra,
                updated_at = $12
            """,
            name,
            meta.get("name", name),
            meta.get("domain", "general"),
            meta.get("description", ""),
            meta.get("owner_id", 0),
            meta.get("owner_username", ""),
            meta.get("status", "ready"),
            meta.get("document_count", 0),
            extra,
            created_at,
            created_at,
            now,
        )


async def pg_save_all_kb_meta(meta: dict[str, Any]) -> None:
    """Save the entire KB metadata dict to PG (full replace).

    This matches the save_kb_meta() signature which takes the full dict
    and writes it atomically. In PG, we upsert each entry individually
    within a transaction.

    Args:
        meta: Full KB metadata dict: {name: {name, created, ...}, ...}
    """
    pool = _get_pool()
    now = datetime.now(timezone.utc)

    async with pool.acquire() as conn:
        async with conn.transaction():
            for kb_name, kb_info in meta.items():
                extra = kb_info.get("extra", {})
                if isinstance(extra, str):
                    pass  # already a JSON string
                elif isinstance(extra, dict):
                    import json as _json
                    extra = _json.dumps(extra, ensure_ascii=False)
                else:
                    extra = "{}"

                # Parse created_at from ISO string to datetime, or use now.
                # Naive strings are treated as UTC so TIMESTAMPTZ storage is unambiguous.
                created_str = kb_info.get("created", "")
                created_at = now
                if created_str:
                    try:
                        created_at = _as_utc(datetime.fromisoformat(created_str))
                    except (ValueError, TypeError):
                        created_at = now

                await conn.execute(
                    """
                    INSERT INTO kb_metadata (
                        name, display_name, domain, description,
                        owner_id, owner_username, status, document_count,
                        extra, created_at, updated_at
                    ) VALUES (
                        $1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11
                    )
                    ON CONFLICT (name) DO UPDATE SET
                        display_name = EXCLUDED.display_name,
                        domain = EXCLUDED.domain,
                        description = EXCLUDED.description,
                        owner_id = EXCLUDED.owner_id,
                        owner_username = EXCLUDED.owner_username,
                        status = EXCLUDED.status,
                        document_count = EXCLUDED.document_count,
                        extra = EXCLUDED.extra
                    """,
                    kb_name,
                    kb_info.get("name", kb_name),
                    kb_info.get("domain", "general"),
                    kb_info.get("description", ""),
                    kb_info.get("owner_id", 0),
                    kb_info.get("owner_username", ""),
                    kb_info.get("status", "ready"),
                    kb_info.get("document_count", 0),
                    extra,
                    created_at,
                    created_at,
                )


async def pg_delete_kb_meta(name: str) -> bool:
    """Delete a KB metadata entry from PG.

    Returns:
        True if the KB was found and deleted, False otherwise.
    """
    pool = _get_pool()
    async with pool.acquire() as conn:
        result = await conn.execute(
            "DELETE FROM kb_metadata WHERE name = $1",
            name,
        )
    # asyncpg returns "DELETE N" — parse the count
    deleted = int(result.split()[-1]) if result else 0
    return deleted > 0


async def pg_list_kbs_by_domain(domain: str = "general") -> list[dict[str, Any]]:
    """List KBs filtered by domain (used by autorepair KB discovery)."""
    pool = _get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT name, display_name, domain, description,
                   owner_id, owner_username, status, document_count,
                   extra, created_at, updated_at
            FROM kb_metadata
            WHERE domain = $1
            ORDER BY updated_at DESC
            """,
            domain,
        )

    result = []
    for row in rows:
        d = dict(row)
        for ts_field in ("created_at", "updated_at"):
            if isinstance(d.get(ts_field), datetime):
                d[ts_field] = d[ts_field].isoformat()
        result.append({
            "name": d["name"],
            "display_name": d.get("display_name", ""),
            "domain": d.get("domain", "general"),
            "description": d.get("description", ""),
            "owner_id": d.get("owner_id", 0),
            "owner_username": d.get("owner_username", ""),
            "status": d.get("status", "ready"),
            "document_count": d.get("document_count", 0),
            "created_at": d.get("created_at", ""),
            "updated_at": d.get("updated_at", ""),
        })
    return result


async def pg_ensure_kb_tables() -> None:
    """Ensure kb_metadata table exists (run at startup)."""
    pool = _get_pool()
    async with pool.acquire() as conn:
        exists = await conn.fetchval(
            "SELECT EXISTS (SELECT 1 FROM information_schema.tables "
            "WHERE table_schema = 'public' AND table_name = 'kb_metadata')"
        )
        if not exists:
            logger.warning(
                "kb_metadata table does not exist in PG. "
                "Run migrations/003_p0_agent_kb_meta.sql to create it."
            )
        else:
            logger.info("kb_metadata table verified")


# ═══════════════════════════════════════════════════════════════
# PG availability check (matches auth.py pattern)
# ═══════════════════════════════════════════════════════════════

def _pg_kb_meta_ready() -> bool:
    """Check if PG is available for KB metadata operations."""
    try:
        from raganything.services.pg_state_repo import get_pg_pool
        get_pg_pool()
        return True
    except (RuntimeError, ImportError):
        return False


__all__ = [
    "pg_load_kb_meta",
    "pg_get_kb_meta",
    "pg_save_kb_meta",
    "pg_save_all_kb_meta",
    "pg_delete_kb_meta",
    "pg_list_kbs_by_domain",
    "pg_ensure_kb_tables",
    "_pg_kb_meta_ready",
]
