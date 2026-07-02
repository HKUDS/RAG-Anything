# -*- coding: utf-8 -*-
"""
═══════════════════════════════════════════════════════════════════════════════
PostgreSQL 知识图谱编辑仓库 — 用户手动编辑的实体和关系
═══════════════════════════════════════════════════════════════════════════════

【文件作用】
  提供知识图谱编辑层的数据持久化。
  - user_entities: 用户手动创建/重命名的实体（叠加在自动提取实体之上）
  - user_relations: 用户手动创建的实体间关系

【管理的数据库表】
  ┌──────────────────┬──────────────────────────────────────┐
  │ user_entities    │ 用户编辑的实体                         │
  │                  │ name（实体名称，主键/唯一标识）         │
  │                  │ entity_type（类型：自动推断）           │
  │                  │ description（手动描述文本）             │
  │                  │ status（active/renamed/deleted）       │
  │                  │ renamed_from（原始自动提取名称）         │
  │                  │ kb_name（所属知识库）                   │
  │                  │ created_by（创建者 user_id）            │
  │                  │ created_at / updated_at                │
  ├──────────────────┼──────────────────────────────────────┤
  │ user_relations   │ 用户编辑的关系                         │
  │                  │ id（UUID 主键）                        │
  │                  │ source_entity（源实体名称）             │
  │                  │ target_entity（目标实体名称）           │
  │                  │ relation_type（关系类型）               │
  │                  │ description（关系描述）                 │
  │                  │ kb_name（所属知识库）                   │
  │                  │ created_by（创建者 user_id）            │
  │                  │ created_at                            │
  └──────────────────┴──────────────────────────────────────┘

【核心函数】
  ensure_graph_edit_tables()                  → 启动时确保表存在
  list_user_entities(kb_name)                 → 列出 KB 内所有手动实体
  create_user_entity(kb_name, name, ...)      → 创建实体
  rename_user_entity(kb_name, old_name, ...)  → 重命名实体
  delete_user_entity(kb_name, name)           → 软删除实体
  list_user_relations(kb_name)                → 列出 KB 内所有手动关系
  create_user_relation(kb_name, ...)          → 创建关系
  delete_user_relation(relation_id)           → 删除关系
"""

from __future__ import annotations

import logging
from typing import Any, Optional
from datetime import datetime, timezone

import asyncpg

logger = logging.getLogger("rag_server.pg_graph_edit")


def _get_pool() -> asyncpg.Pool:
    from raganything.services.pg_state_repo import get_pg_pool
    return get_pg_pool()


# ═══════════════════════════════════════════════════════════════
# Table creation (called on startup)
# ═══════════════════════════════════════════════════════════════

async def ensure_graph_edit_tables() -> None:
    """Ensure user_entities and user_relations tables exist."""
    pool = _get_pool()
    async with pool.acquire() as conn:
        # ── user_entities ──
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS user_entities (
                name            TEXT NOT NULL,
                kb_name         TEXT NOT NULL,
                entity_type     TEXT DEFAULT '',
                description     TEXT DEFAULT '',
                status          TEXT NOT NULL DEFAULT 'active',
                renamed_from    TEXT DEFAULT '',
                created_by      INTEGER NOT NULL DEFAULT 0,
                updated_by      INTEGER NOT NULL DEFAULT 0,
                created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                PRIMARY KEY (kb_name, name)
            )
        """)
        # Index for listing by kb
        await conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_user_entities_kb_status
            ON user_entities (kb_name, status)
        """)

        # ── user_relations ──
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS user_relations (
                id              UUID NOT NULL DEFAULT gen_random_uuid(),
                source_entity   TEXT NOT NULL,
                target_entity   TEXT NOT NULL,
                relation_type   TEXT DEFAULT 'related_to',
                description     TEXT DEFAULT '',
                kb_name         TEXT NOT NULL,
                created_by      INTEGER NOT NULL DEFAULT 0,
                created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                PRIMARY KEY (id)
            )
        """)
        await conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_user_relations_kb
            ON user_relations (kb_name)
        """)
        await conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_user_relations_source
            ON user_relations (kb_name, source_entity)
        """)
        await conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_user_relations_target
            ON user_relations (kb_name, target_entity)
        """)

    logger.info("Graph edit tables (user_entities, user_relations) verified")


# ═══════════════════════════════════════════════════════════════
# Entity CRUD
# ═══════════════════════════════════════════════════════════════

async def list_user_entities(kb_name: str) -> list[dict[str, Any]]:
    """List all active user-edited entities for a KB."""
    pool = _get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """SELECT name, entity_type, description, status,
                      renamed_from, created_by, updated_by,
                      created_at, updated_at
               FROM user_entities
               WHERE kb_name = $1 AND status = 'active'
               ORDER BY updated_at DESC""",
            kb_name,
        )
    return [dict(row) for row in rows]


async def get_renamed_entities(kb_name: str) -> dict[str, str]:
    """Return {old_name: new_name} mapping for renamed entities in this KB."""
    pool = _get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """SELECT renamed_from, name
               FROM user_entities
               WHERE kb_name = $1 AND status = 'active' AND renamed_from != ''""",
            kb_name,
        )
    return {row["renamed_from"]: row["name"] for row in rows}


async def get_deleted_entity_names(kb_name: str) -> set[str]:
    """Return set of entity names that have been soft-deleted."""
    pool = _get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """SELECT name
               FROM user_entities
               WHERE kb_name = $1 AND status = 'deleted'""",
            kb_name,
        )
    return {row["name"] for row in rows}


async def create_user_entity(
    kb_name: str,
    name: str,
    entity_type: str = "",
    description: str = "",
    created_by: int = 0,
) -> dict[str, Any]:
    """Create a new user entity (or reactivate a deleted one)."""
    pool = _get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """INSERT INTO user_entities (name, kb_name, entity_type, description, status, created_by, updated_by)
               VALUES ($1, $2, $3, $4, 'active', $5, $5)
               ON CONFLICT (kb_name, name) DO UPDATE
               SET status = 'active',
                   entity_type = COALESCE(NULLIF($3, ''), user_entities.entity_type),
                   description = COALESCE(NULLIF($4, ''), user_entities.description),
                   updated_by = $5,
                   updated_at = NOW()
               RETURNING name, entity_type, description, status,
                         renamed_from, created_by, created_at, updated_at""",
            name, kb_name, entity_type, description, created_by,
        )
    return dict(row) if row else {}


async def rename_user_entity(
    kb_name: str,
    old_name: str,
    new_name: str,
    created_by: int = 0,
) -> dict[str, Any]:
    """Rename an entity: record the old name via renamed_from, create new record.

    Uses a transaction to ensure atomicity.
    Returns the new entity record.
    """
    pool = _get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            # Mark old name as renamed (if it exists as a user entity)
            # renamed_from stores $3 (new_name) to track where this entity was renamed to
            await conn.execute(
                """INSERT INTO user_entities (name, kb_name, status, renamed_from, created_by, updated_by)
                   VALUES ($1, $2, 'renamed', $3, $4, $4)
                   ON CONFLICT (kb_name, name) DO UPDATE
                   SET status = 'renamed', renamed_from = $3, updated_by = $4, updated_at = NOW()""",
                old_name, kb_name, new_name, created_by,
            )

            # Also mark old auto-extracted entities as 'renamed' so they're
            # filtered out of the graph (renamed_from tracks the mapping)
            # Create the new entity
            row = await conn.fetchrow(
                """INSERT INTO user_entities (name, kb_name, status, renamed_from, created_by, updated_by)
                   VALUES ($1, $2, 'active', $3, $4, $4)
                   ON CONFLICT (kb_name, name) DO UPDATE
                   SET status = 'active', renamed_from = $3, updated_by = $4, updated_at = NOW()
                   RETURNING name, entity_type, description, status,
                             renamed_from, created_by, created_at, updated_at""",
                new_name, kb_name, old_name, created_by,
            )
    return dict(row) if row else {}


async def delete_user_entity(
    kb_name: str,
    name: str,
    created_by: int = 0,
) -> bool:
    """Soft-delete a user entity."""
    pool = _get_pool()
    async with pool.acquire() as conn:
        result = await conn.execute(
            """UPDATE user_entities
               SET status = 'deleted', updated_by = $3, updated_at = NOW()
               WHERE kb_name = $1 AND name = $2""",
            kb_name, name, created_by,
        )
    # result is a command tag like "UPDATE 1" or "UPDATE 0"
    return result != "UPDATE 0"


# ═══════════════════════════════════════════════════════════════
# Relation CRUD
# ═══════════════════════════════════════════════════════════════

async def list_user_relations(kb_name: str) -> list[dict[str, Any]]:
    """List all user-created relations for a KB."""
    pool = _get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """SELECT id::text, source_entity, target_entity,
                      relation_type, description, kb_name,
                      created_by, created_at
               FROM user_relations
               WHERE kb_name = $1
               ORDER BY created_at DESC""",
            kb_name,
        )
    return [dict(row) for row in rows]


async def get_user_relations_for_entity(
    kb_name: str,
    entity_name: str,
) -> list[dict[str, Any]]:
    """Get all user relations involving a specific entity."""
    pool = _get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """SELECT id::text, source_entity, target_entity,
                      relation_type, description, kb_name,
                      created_by, created_at
               FROM user_relations
               WHERE kb_name = $1
                 AND (source_entity = $2 OR target_entity = $2)
               ORDER BY created_at DESC""",
            kb_name, entity_name,
        )
    return [dict(row) for row in rows]


async def create_user_relation(
    kb_name: str,
    source_entity: str,
    target_entity: str,
    relation_type: str = "related_to",
    description: str = "",
    created_by: int = 0,
) -> dict[str, Any]:
    """Create a user-specified relation between two entities."""
    pool = _get_pool()
    async with pool.acquire() as conn:
        # Check for duplicate (same source/target pair)
        existing = await conn.fetchval(
            """SELECT id FROM user_relations
               WHERE kb_name = $1 AND source_entity = $2 AND target_entity = $3
               LIMIT 1""",
            kb_name, source_entity, target_entity,
        )
        if existing:
            # Update existing relation type instead of creating duplicate
            row = await conn.fetchrow(
                """UPDATE user_relations
                   SET relation_type = $4, description = $5
                   WHERE id = $1
                   RETURNING id::text, source_entity, target_entity,
                             relation_type, description, kb_name,
                             created_by, created_at""",
                existing, relation_type, description,
            )
        else:
            row = await conn.fetchrow(
                """INSERT INTO user_relations
                   (source_entity, target_entity, relation_type, description, kb_name, created_by)
                   VALUES ($1, $2, $3, $4, $5, $6)
                   RETURNING id::text, source_entity, target_entity,
                             relation_type, description, kb_name,
                             created_by, created_at""",
                source_entity, target_entity, relation_type, description, kb_name, created_by,
            )
    return dict(row) if row else {}


async def delete_user_relation(
    relation_id: str,
    kb_name: str,
) -> bool:
    """Delete a user relation by ID."""
    pool = _get_pool()
    async with pool.acquire() as conn:
        result = await conn.execute(
            """DELETE FROM user_relations
               WHERE id = $1::uuid AND kb_name = $2""",
            relation_id, kb_name,
        )
    return result != "DELETE 0"


# ═══════════════════════════════════════════════════════════════
# Graph aggregation helpers
# ═══════════════════════════════════════════════════════════════

async def apply_user_edits_to_graph(
    kb_name: str,
    auto_nodes: list[dict],
    auto_edges: list[dict],
) -> tuple[list[dict], list[dict]]:
    """Merge user edits (renames, new entities, new relations, deletions)
    into the auto-extracted graph data.

    Returns:
        (merged_nodes, merged_edges)
    """
    renamed = await get_renamed_entities(kb_name)
    deleted = await get_deleted_entity_names(kb_name)
    user_entities = await list_user_entities(kb_name)
    user_relations = await list_user_relations(kb_name)

    # Build lookup
    auto_node_set = {n["id"]: n for n in auto_nodes}
    merged_nodes: dict[str, dict] = dict(auto_node_set)
    merged_edges: list[dict] = list(auto_edges)

    # ── Apply renames ──
    rename_targets = set(renamed.values())
    for old_name, new_name in renamed.items():
        if old_name in merged_nodes:
            del merged_nodes[old_name]
        # Rename in edges
        for edge in merged_edges:
            if edge.get("source") == old_name:
                edge["source"] = new_name
            if edge.get("target") == old_name:
                edge["target"] = new_name

    # ── Remove deleted entities ──
    for name in deleted:
        if name in merged_nodes and name not in rename_targets:
            del merged_nodes[name]
        merged_edges = [
            e for e in merged_edges
            if e.get("source") != name and e.get("target") != name
        ]

    # ── Add user-created entities ──
    for ue in user_entities:
        ent_name = ue["name"]
        if ent_name not in merged_nodes:
            merged_nodes[ent_name] = {
                "id": ent_name,
                "label": ent_name[:25],
                "entity_type": ue.get("entity_type", ""),
            }

    # ── Add user-created relations ──
    user_edge_keys = {
        (ur["source_entity"], ur["target_entity"]) for ur in user_relations
    }
    auto_edge_keys = {(e.get("source"), e.get("target")) for e in merged_edges}
    for ur in user_relations:
        key = (ur["source_entity"], ur["target_entity"])
        if key not in auto_edge_keys:
            merged_edges.append({
                "source": ur["source_entity"],
                "target": ur["target_entity"],
                "label": ur.get("relation_type", "related_to"),
                "_user_relation_id": ur.get("id", ""),
            })

    # Ensure all edge endpoints have nodes
    edge_source_set = {e.get("source") for e in merged_edges}
    edge_target_set = {e.get("target") for e in merged_edges}
    all_refs = edge_source_set | edge_target_set
    for ref in all_refs:
        if ref and ref not in merged_nodes:
            merged_nodes[ref] = {"id": ref, "label": ref[:25]}

    nodes_out = list(merged_nodes.values())
    # Filter out deleted
    nodes_out = [n for n in nodes_out if n["id"] not in deleted]

    # Deduplicate edges
    seen_edges = set()
    deduped_edges = []
    for e in merged_edges:
        key = (e.get("source"), e.get("target"))
        if key not in seen_edges and e.get("source") and e.get("target"):
            seen_edges.add(key)
            deduped_edges.append(e)

    return nodes_out, deduped_edges


__all__ = [
    "ensure_graph_edit_tables",
    "list_user_entities",
    "get_renamed_entities",
    "get_deleted_entity_names",
    "create_user_entity",
    "rename_user_entity",
    "delete_user_entity",
    "list_user_relations",
    "get_user_relations_for_entity",
    "create_user_relation",
    "delete_user_relation",
    "apply_user_edits_to_graph",
]
