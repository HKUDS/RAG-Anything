# -*- coding: utf-8 -*-
"""
═══════════════════════════════════════════════════════════════════════════════
PostgreSQL AI 智能体仓库
═══════════════════════════════════════════════════════════════════════════════

【文件作用】
  AI 智能体（Agent）的完整生命周期管理，包括智能体 CRUD 和多轮对话会话管理。
  通过 pg_state_repo.get_pg_pool() 复用全局连接池。
  PG 查询失败时自动回退 JSON 文件（兼容旧数据）。

【管理的数据库表】
  ┌─────────────────────┬───────────────────────────────────┐
  │ agents              │ 智能体定义                         │
  │                     │ id, name, system_prompt（系统提示词）│
  │                     │ llm_config（JSON: 模型/温度等配置） │
  │                     │ kb_names（关联的知识库列表）        │
  │                     │ created_by（创建者 user_id）        │
  │                     │ is_public（是否公开）               │
  ├─────────────────────┼───────────────────────────────────┤
  │ agent_conversations │ 智能体会话线程                     │
  │                     │ agent_id（关联智能体）              │
  │                     │ thread_id（会话标识）               │
  │                     │ title（会话标题）                   │
  │                     │ created_by（创建者）                │
  ├─────────────────────┼───────────────────────────────────┤
  │ agent_messages      │ 会话中的每条消息                   │
  │                     │ conversation_id（关联会话）         │
  │                     │ role（user/assistant/system/tool） │
  │                     │ content（消息内容）                 │
  │                     │ created_at（时间戳）                │
  └─────────────────────┴───────────────────────────────────┘

【核心函数】
  ── 智能体 CRUD ──
  pg_create_agent(data)                              → 创建智能体
  pg_get_agent(agent_id)                             → 获取单个智能体（PG→JSON回退）
  pg_list_agents(user_id, is_admin)                  → 列出智能体（PG→JSON合并去重）
  pg_update_agent(agent_id, data)                    → 更新智能体
  pg_delete_agent(agent_id)                          → 删除智能体及关联数据

  ── 会话管理 ──
  pg_list_conversations(agent_id, user_id)           → 列出智能体的所有会话
  pg_get_conversation(agent_id, thread_id)           → 获取单个会话（含消息）
  pg_create_conversation(agent_id, data)             → 创建新会话
  pg_add_message(agent_id, thread_id, data)          → 添加消息到会话
  pg_update_conversation(agent_id, thread_id, data)  → 更新会话（如重命名）
  pg_delete_conversation(agent_id, thread_id)        → 删除会话及关联消息

【特殊逻辑】
  - _load_json_agents()      → 读取 agent_meta.json（旧数据回退）
  - _json_get_agent(id)      → 从 JSON 按 ID 查找
  - _json_list_agents(...)   → 从 JSON 列出智能体
  - pg_get_agent() 先查 PG，查不到自动回退 JSON
  - pg_list_agents() 查 PG + JSON 合并（按 id 去重）

【替换了什么】
  - raganything/services/agent_manager.py 的 JSON 持久化层
  - agent_meta.json（智能体元数据）
  - agent_conversations/<agent_id>/<thread_id>.json（会话消息）

【与其他文件的关系】
  使用 pg_state_repo.get_pg_pool() 获取连接
  被 raganything/services/agent_manager.py 调用（dispatch 层）
  被 raganything/routers/agent.py 调用（REST API 端点）
  对应迁移：migrations/003_p0_agent_kb_meta.sql

English:
  PostgreSQL-backed Agent Repository.

  Replaces: raganything/services/agent_manager.py AgentManager JSON persistence
            (agent_meta.json + agent_conversations/<agent_id>/<thread_id>.json)

  Uses the same shared connection pool as pg_state_repo.py and pg_auth_repo.py.

  Usage (async, direct):
      from raganything.services.pg_agent_repo import (
          pg_list_agents, pg_get_agent, pg_create_agent,
          pg_update_agent, pg_delete_agent,
          pg_list_conversations, pg_get_conversation,
          pg_create_conversation, pg_add_message,
          pg_update_conversation, pg_delete_conversation,
      )

  Middleware layer (in agent_manager.py):
      Uses _pg_agent_ready() to auto-dispatch between PG and file-based
      AgentManager, matching the auth.py dispatch pattern.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import asyncpg

logger = logging.getLogger("rag_server.pg_agent")


def _get_pool():
    """Get the shared PG pool. Raises RuntimeError if not initialized."""
    from raganything.services.pg_state_repo import get_pg_pool
    return get_pg_pool()


# ── JSON file fallback (agents created before PG migration) ──

_AGENT_META_PATH = Path("agent_meta.json")


def _load_json_agents() -> list[dict[str, Any]]:
    """Load agents from the JSON fallback file.

    Returns an empty list if the file doesn't exist or is unreadable.
    """
    try:
        if not _AGENT_META_PATH.exists():
            return []
        data = json.loads(_AGENT_META_PATH.read_text(encoding="utf-8"))
        return data.get("agents", []) if isinstance(data, dict) else []
    except (json.JSONDecodeError, OSError):
        return []


def _json_get_agent(agent_id: str) -> Optional[dict[str, Any]]:
    """Look up a single agent in the JSON fallback file."""
    for agent in _load_json_agents():
        if agent.get("id") == agent_id:
            return agent
    return None


def _json_list_agents(
    user_id: Optional[int] = None,
    is_admin: bool = False,
) -> list[dict[str, Any]]:
    """List agents from the JSON fallback file (user-isolated)."""
    agents = _load_json_agents()
    if is_admin or user_id is None:
        return agents
    return [
        a for a in agents
        if a.get("owner_id", 0) in (0, user_id)
    ]


def _coerce_timestamp(value: Any) -> datetime:
    if isinstance(value, datetime):
        dt = value
    elif isinstance(value, str) and value:
        try:
            dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            dt = datetime.now(timezone.utc)
    else:
        dt = datetime.now(timezone.utc)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def _coerce_bool(value: Any, default: bool) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return bool(value)


async def _promote_legacy_json_agent(
    agent_id: str,
    legacy_agent: Optional[dict[str, Any]] = None,
) -> Optional[dict[str, Any]]:
    """Promote a JSON-only legacy agent into PG and return the PG row."""
    legacy_agent = legacy_agent or _json_get_agent(agent_id)
    if not legacy_agent:
        return None

    created_at = _coerce_timestamp(legacy_agent.get("created_at"))
    updated_at = _coerce_timestamp(legacy_agent.get("updated_at"))
    owner_id = legacy_agent.get("owner_id", 0)
    try:
        owner_id = int(owner_id)
    except (TypeError, ValueError):
        owner_id = 0

    pool = _get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO agents (
                id, name, icon, description, welcome_message,
                kb_name, llm_model, temperature, max_response_tokens,
                query_mode, agent_mode, retrieval_top_k, chunk_top_k,
                enable_rerank, include_references,
                system_prompt, use_default_prompt,
                owner_id, owner_username, template_id,
                created_at, updated_at
            ) VALUES (
                $1, $2, $3, $4, $5,
                $6, $7, $8, $9,
                $10, $11, $12, $13,
                $14, $15,
                $16, $17,
                $18, $19, $20,
                $21, $22
            )
            ON CONFLICT (id) DO NOTHING
            """,
            legacy_agent.get("id") or agent_id,
            legacy_agent.get("name") or "新智能体",
            legacy_agent.get("icon") or "🤖",
            legacy_agent.get("description") or "",
            legacy_agent.get("welcome_message") or "",
            legacy_agent.get("kb_name") or "default",
            legacy_agent.get("llm_model") or "qwen-plus",
            legacy_agent.get("temperature", 0.0) or 0.0,
            legacy_agent.get("max_response_tokens", 4096) or 4096,
            legacy_agent.get("query_mode") or "hybrid",
            legacy_agent.get("agent_mode") or "none",
            legacy_agent.get("retrieval_top_k", 40) or 40,
            legacy_agent.get("chunk_top_k", 20) or 20,
            _coerce_bool(legacy_agent.get("enable_rerank"), False),
            _coerce_bool(legacy_agent.get("include_references"), True),
            legacy_agent.get("system_prompt") or "",
            _coerce_bool(legacy_agent.get("use_default_prompt"), True),
            owner_id,
            legacy_agent.get("owner_username") or "",
            legacy_agent.get("template_id") or "",
            created_at,
            updated_at,
        )
        row = await conn.fetchrow(
            "SELECT * FROM agents WHERE id = $1",
            legacy_agent.get("id") or agent_id,
        )

    if row:
        logger.info("Promoted legacy JSON agent %s into PostgreSQL", agent_id)
        return _agent_row_to_dict(row)
    return None


# ═══════════════════════════════════════════════════════════════
# Agent CRUD
# ═══════════════════════════════════════════════════════════════

async def pg_list_agents(
    user_id: Optional[int] = None,
    is_admin: bool = False,
) -> list[dict[str, Any]]:
    """List agents with user isolation and conversation activity.

    Replaces: AgentManager.list_agents()

    PostgreSQL is authoritative. Legacy JSON is deliberately not merged,
    because migrated data must never reappear after a system reset.

    Returns:
        List of agent dicts sorted by updated_at DESC. Regular users receive
        activity for conversations they own; administrators receive all usage.
    """
    result: list[dict[str, Any]] = []
    try:
        pool = _get_pool()
        activity_available = True
        if is_admin or user_id is None:
            try:
                rows = await pool.fetch(
                    """
                    SELECT a.*, activity.conversation_count, activity.last_conversation_at
                    FROM agents AS a
                    LEFT JOIN LATERAL (
                        SELECT COUNT(*)::integer AS conversation_count,
                               MAX(updated_at) AS last_conversation_at
                        FROM agent_conversations
                        WHERE agent_id = a.id
                    ) AS activity ON TRUE
                    ORDER BY a.updated_at DESC
                    """
                )
            except Exception:
                logger.debug("Agent activity aggregation failed, listing agents without activity")
                activity_available = False
                rows = await pool.fetch("SELECT * FROM agents ORDER BY updated_at DESC")
        else:
            try:
                rows = await pool.fetch(
                    """
                    SELECT a.*, activity.conversation_count, activity.last_conversation_at
                    FROM agents AS a
                    LEFT JOIN LATERAL (
                        SELECT COUNT(*)::integer AS conversation_count,
                               MAX(updated_at) AS last_conversation_at
                        FROM agent_conversations
                        WHERE agent_id = a.id AND owner_id = $1
                    ) AS activity ON TRUE
                    WHERE a.owner_id = $1 OR a.owner_id = 0
                    ORDER BY a.updated_at DESC
                    """,
                    user_id,
                )
            except Exception:
                logger.debug("Agent activity aggregation failed, listing agents without activity")
                activity_available = False
                rows = await pool.fetch(
                    "SELECT * FROM agents WHERE owner_id = $1 OR owner_id = 0 ORDER BY updated_at DESC",
                    user_id,
                )
        result = [_agent_row_to_dict(r) for r in rows]
        if not activity_available:
            for agent in result:
                agent["conversation_count"] = None
                agent["last_conversation_at"] = None
    except Exception:
        logger.exception("PG list_agents failed")
        raise

    result.sort(key=lambda a: a.get("updated_at", ""), reverse=True)
    return result


async def pg_get_agent(agent_id: str) -> Optional[dict[str, Any]]:
    """Get a single agent by ID.

    Replaces: AgentManager.get_agent()

    PostgreSQL is the only runtime source of truth.
    """
    try:
        pool = _get_pool()
        row = await pool.fetchrow(
            "SELECT * FROM agents WHERE id = $1",
            agent_id,
        )
        if row:
            return _agent_row_to_dict(row)
    except Exception:
        logger.exception("PG get_agent failed for %s", agent_id)
    return None


async def pg_create_agent(
    config: dict[str, Any],
    owner_id: int = 0,
    owner_username: str = "",
) -> dict[str, Any]:
    """Create a new agent.

    Replaces: AgentManager.create_agent()

    Args:
        config: Agent configuration dict (AgentConfig.model_dump() compatible)
        owner_id: Owner user ID
        owner_username: Owner username

    Returns:
        Created agent dict.
    """
    import uuid as _uuid

    agent_id = config.get("id") or str(_uuid.uuid4())[:8]
    now = datetime.now(timezone.utc)

    pool = _get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO agents (
                id, name, icon, description, welcome_message,
                kb_name, llm_model, temperature, max_response_tokens,
                query_mode, agent_mode, retrieval_top_k, chunk_top_k,
                enable_rerank, include_references,
                system_prompt, use_default_prompt,
                owner_id, owner_username, template_id,
                created_at, updated_at
            ) VALUES (
                $1, $2, $3, $4, $5,
                $6, $7, $8, $9,
                $10, $11, $12, $13,
                $14, $15,
                $16, $17,
                $18, $19, $20,
                $21, $21
            )
            """,
            agent_id,
            config.get("name", "新智能体"),
            config.get("icon", "🤖"),
            config.get("description", ""),
            config.get("welcome_message", ""),
            config.get("kb_name", "default"),
            config.get("llm_model", "qwen-plus"),
            config.get("temperature", 0.0),
            config.get("max_response_tokens", 4096),
            config.get("query_mode", "hybrid"),
            config.get("agent_mode", "none"),
            config.get("retrieval_top_k", 40),
            config.get("chunk_top_k", 20),
            config.get("enable_rerank", False),
            config.get("include_references", True),
            config.get("system_prompt", ""),
            config.get("use_default_prompt", True),
            owner_id,
            owner_username,
            config.get("template_id", ""),
            now,
        )

    # Fetch the created agent to return full data
    return await pg_get_agent(agent_id)


async def pg_update_agent(
    agent_id: str,
    updates: dict[str, Any],
) -> Optional[dict[str, Any]]:
    """Update an agent (partial update).

    Replaces: AgentManager.update_agent()

    Args:
        agent_id: Agent identifier
        updates: Dict of fields to update (only non-None fields are updated)

    Returns:
        Updated agent dict or None if not found.
    """
    allowed_fields = {
        "name", "icon", "description", "welcome_message",
        "kb_name", "llm_model", "temperature", "max_response_tokens",
        "query_mode", "agent_mode", "retrieval_top_k", "chunk_top_k",
        "enable_rerank", "include_references",
        "system_prompt", "use_default_prompt",
        "owner_id", "owner_username", "template_id",
    }

    set_parts = []
    values = []
    idx = 1
    for key, value in updates.items():
        if key in allowed_fields and value is not None:
            set_parts.append(f"{key} = ${idx}")
            values.append(value)
            idx += 1

    if not set_parts:
        # No valid fields to update — still return current agent
        return await pg_get_agent(agent_id)

    pool = _get_pool()

    async def _run_update() -> Optional[dict[str, Any]]:
        update_values = list(values)
        update_parts = list(set_parts)
        update_idx = idx
        now = datetime.now(timezone.utc)
        update_parts.append(f"updated_at = ${update_idx}")
        update_values.append(now)
        update_idx += 1
        update_values.append(agent_id)
        sql = (
            f"UPDATE agents SET {', '.join(update_parts)} "
            f"WHERE id = ${update_idx} "
            f"RETURNING *"
        )
        row = await pool.fetchrow(sql, *update_values)
        return _agent_row_to_dict(row) if row else None

    updated_agent = await _run_update()
    if updated_agent:
        return updated_agent

    return None


async def pg_delete_agent(agent_id: str) -> bool:
    """Delete an agent and all its conversations (CASCADE).

    Replaces: AgentManager.delete_agent()

    Returns:
        True if found and deleted, False otherwise.
    """
    pool = _get_pool()
    result = await pool.execute(
        "DELETE FROM agents WHERE id = $1",
        agent_id,
    )
    deleted = int(result.split()[-1]) if result else 0
    return deleted > 0


# ═══════════════════════════════════════════════════════════════
# Conversation Thread CRUD
# ═══════════════════════════════════════════════════════════════

async def pg_list_conversations(
    agent_id: str,
    user_id: Optional[int] = None,
    is_admin: bool = False,
) -> list[dict[str, Any]]:
    """List conversation threads for an agent (user-isolated).

    Replaces: AgentManager.list_conversations()

    Returns:
        List of thread dicts sorted by updated_at DESC.
        Each dict has: id, agent_id, owner_id, title, kb_name,
        llm_model, system_prompt, created_at, updated_at, message_count
    """
    pool = _get_pool()
    if is_admin or user_id is None:
        rows = await pool.fetch(
            """
            SELECT ac.*, COUNT(am.id) as message_count
            FROM agent_conversations ac
            LEFT JOIN agent_messages am ON am.thread_id = ac.id
            WHERE ac.agent_id = $1
            GROUP BY ac.id
            ORDER BY ac.updated_at DESC
            """,
            agent_id,
        )
    else:
        rows = await pool.fetch(
            """
            SELECT ac.*, COUNT(am.id) as message_count
            FROM agent_conversations ac
            LEFT JOIN agent_messages am ON am.thread_id = ac.id
            WHERE ac.agent_id = $1
              AND (ac.owner_id = $2 OR ac.owner_id = 0)
            GROUP BY ac.id
            ORDER BY ac.updated_at DESC
            """,
            agent_id, user_id,
        )
    return [_thread_row_to_dict(r) for r in rows]


async def pg_get_conversation(
    agent_id: str,
    thread_id: str,
) -> Optional[dict[str, Any]]:
    """Get a single conversation thread with messages.

    Replaces: AgentManager.get_conversation()

    Returns:
        Thread dict with .messages list, or None if not found.
    """
    pool = _get_pool()
    thread_row = await pool.fetchrow(
        "SELECT * FROM agent_conversations WHERE id = $1 AND agent_id = $2",
        thread_id, agent_id,
    )
    if not thread_row:
        return None

    thread = _thread_row_to_dict(thread_row)

    # Fetch messages (including DB id for per-message edit support)
    msg_rows = await pool.fetch(
        "SELECT id, role, content, metadata, created_at "
        "FROM agent_messages "
        "WHERE thread_id = $1 "
        "ORDER BY created_at ASC",
        thread_id,
    )
    thread["messages"] = [
        {
            "msg_id": r["id"],
            "role": r["role"],
            "content": r["content"],
            **(json.loads(r["metadata"]) if isinstance(r["metadata"], str) else r["metadata"]),
        }
        for r in msg_rows
    ]
    return thread


async def pg_create_conversation(
    agent_id: str,
    title: str = "新对话",
    owner_id: int = 0,
) -> dict[str, Any]:
    """Create a new conversation thread.

    Replaces: AgentManager.create_conversation()

    Returns:
        Created thread dict.
    """
    import uuid as _uuid

    thread_id = str(_uuid.uuid4())[:8]
    now = datetime.now(timezone.utc)

    pool = _get_pool()
    await pool.execute(
        """
        INSERT INTO agent_conversations (
            id, agent_id, owner_id, title, created_at, updated_at
        ) VALUES ($1, $2, $3, $4, $5, $5)
        """,
        thread_id, agent_id, owner_id, title, now,
    )

    return await pg_get_conversation(agent_id, thread_id)


async def pg_add_message(
    agent_id: str,
    thread_id: str,
    message: dict[str, Any],
) -> bool:
    """Add a message to a conversation thread.

    Replaces: AgentManager.add_message()

    Also updates the thread title if it's the first user message
    (matching legacy behavior).

    Args:
        agent_id: Agent identifier
        thread_id: Thread identifier
        message: Message dict with at least {role, content}.
                 Extra keys (elapsed, kb, mode, time, etc.) go to metadata.

    Returns:
        True if thread found and message added, False otherwise.
    """
    pool = _get_pool()
    now = datetime.now(timezone.utc)

    # Separate core fields from metadata
    role = message.get("role", "user")
    content = message.get("content", "")
    metadata = {
        k: v for k, v in message.items()
        if k not in ("role", "content")
    }
    # asyncpg requires JSON strings for JSONB columns
    metadata_str = json.dumps(metadata, ensure_ascii=False)

    async with pool.acquire() as conn:
        async with conn.transaction():
            # Verify thread exists and belongs to agent
            thread = await conn.fetchrow(
                "SELECT id, title FROM agent_conversations "
                "WHERE id = $1 AND agent_id = $2",
                thread_id, agent_id,
            )
            if not thread:
                return False

            # Insert message
            await conn.execute(
                """
                INSERT INTO agent_messages (thread_id, role, content, metadata, created_at)
                VALUES ($1, $2, $3, $4, $5)
                """,
                thread_id, role, content, metadata_str, now,
            )

            # Update thread title if first user message
            if thread["title"] == "新对话" and role == "user":
                new_title = content[:30] + ("..." if len(content) > 30 else "")
                await conn.execute(
                    "UPDATE agent_conversations SET title = $1, updated_at = $2 "
                    "WHERE id = $3",
                    new_title, now, thread_id,
                )
            else:
                # Still bump updated_at
                await conn.execute(
                    "UPDATE agent_conversations SET updated_at = $1 WHERE id = $2",
                    now, thread_id,
                )

    return True


async def pg_update_message(
    thread_id: str,
    message_id: int,
    content: str,
) -> Optional[dict[str, Any]]:
    """Update a single message's content within a conversation thread.

    This is the core data access function for the "edit agent answer"
    feature.  It replaces the message content in-place and records
    an ``edited_at`` timestamp inside the message's metadata JSONB
    column so the frontend can display an "(已编辑)" indicator.

    Args:
        thread_id: Conversation thread identifier (double-validation).
        message_id: The agent_messages.id (BIGSERIAL primary key).
        content: New message text.  Must be ≤ 10000 chars (DB constraint).

    Returns:
        Updated message dict with ``msg_id``, or None if not found.
    """
    if len(content) > 10000:
        raise ValueError("消息内容不能超过 10000 字符")

    pool = _get_pool()
    now = datetime.now(timezone.utc)

    row = await pool.fetchrow(
        """
        UPDATE agent_messages
        SET content = $1,
            metadata = jsonb_set(
                COALESCE(metadata, '{}'),
                '{edited_at}',
                to_jsonb($2::text),
                true
            )
        WHERE id = $3 AND thread_id = $4
        RETURNING id, role, content, metadata, created_at
        """,
        content, now.isoformat(), message_id, thread_id,
    )

    if not row:
        return None

    return {
        "msg_id": row["id"],
        "role": row["role"],
        "content": row["content"],
        **(json.loads(row["metadata"]) if isinstance(row["metadata"], str) else row["metadata"]),
    }


async def pg_update_conversation(
    agent_id: str,
    thread_id: str,
    updates: dict[str, Any],
) -> Optional[dict[str, Any]]:
    """Update a conversation thread (rename, etc.).

    Replaces: AgentManager.update_conversation()
    """
    allowed_fields = {"title"}

    set_parts = []
    values = []
    idx = 1
    for key, value in updates.items():
        if key in allowed_fields and value is not None:
            set_parts.append(f"{key} = ${idx}")
            values.append(value)
            idx += 1

    if not set_parts:
        return await pg_get_conversation(agent_id, thread_id)

    # Add updated_at
    now = datetime.now(timezone.utc)
    set_parts.append(f"updated_at = ${idx}")
    values.append(now)
    idx += 1

    values.extend([thread_id, agent_id])
    sql = (
        f"UPDATE agent_conversations SET {', '.join(set_parts)} "
        f"WHERE id = ${idx} AND agent_id = ${idx + 1} "
        f"RETURNING *"
    )

    pool = _get_pool()
    row = await pool.fetchrow(sql, *values)
    return _thread_row_to_dict(row) if row else None


async def pg_delete_conversation(agent_id: str, thread_id: str) -> bool:
    """Delete a conversation thread (messages auto-deleted via CASCADE).

    Replaces: AgentManager.delete_conversation()

    Returns:
        True if found and deleted, False otherwise.
    """
    pool = _get_pool()
    result = await pool.execute(
        "DELETE FROM agent_conversations WHERE id = $1 AND agent_id = $2",
        thread_id, agent_id,
    )
    deleted = int(result.split()[-1]) if result else 0
    return deleted > 0


# ═══════════════════════════════════════════════════════════════
# Row Serialization Helpers
# ═══════════════════════════════════════════════════════════════

def _agent_row_to_dict(row: Any) -> dict[str, Any]:
    """Convert an agents table row to a dict matching AgentConfig schema."""
    d = dict(row)
    for ts_field in ("created_at", "updated_at", "last_conversation_at"):
        if isinstance(d.get(ts_field), datetime):
            d[ts_field] = d[ts_field].isoformat()
    # Map boolean fields
    for bool_field in ("enable_rerank", "include_references", "use_default_prompt"):
        if d.get(bool_field) is not None:
            d[bool_field] = bool(d[bool_field])
    return d


def _thread_row_to_dict(row: Any) -> dict[str, Any]:
    """Convert an agent_conversations row to a dict."""
    d = dict(row)
    for ts_field in ("created_at", "updated_at"):
        if isinstance(d.get(ts_field), datetime):
            d[ts_field] = d[ts_field].isoformat()
    return d


# ═══════════════════════════════════════════════════════════════
# PG Table Setup
# ═══════════════════════════════════════════════════════════════

async def pg_ensure_agent_tables() -> None:
    """Ensure agent-related tables exist (run at startup)."""
    pool = _get_pool()
    async with pool.acquire() as conn:
        for table in ("agents", "agent_conversations", "agent_messages"):
            exists = await conn.fetchval(
                "SELECT EXISTS (SELECT 1 FROM information_schema.tables "
                "WHERE table_schema = 'public' AND table_name = $1)",
                table,
            )
            if not exists:
                logger.warning(
                    f"{table} table does not exist in PG. "
                    f"Run migrations/003_p0_agent_kb_meta.sql to create it."
                )
            else:
                logger.info(f"{table} table verified")


# ═══════════════════════════════════════════════════════════════
# Conversation Summary (Phase 3)
# ═══════════════════════════════════════════════════════════════

async def pg_get_summary(thread_id: str) -> Optional[str]:
    """Get the conversation summary for a thread.

    Returns:
        Summary text or None if no summary exists.
    """
    pool = _get_pool()
    row = await pool.fetchrow(
        "SELECT summary FROM agent_conversations WHERE id = $1",
        thread_id,
    )
    if row and row["summary"]:
        return row["summary"]
    return None


async def pg_update_summary(thread_id: str, summary_text: str) -> bool:
    """Update the conversation summary for a thread.

    Updates both ``summary`` and ``summary_updated_at`` in a single query.

    Args:
        thread_id: The conversation thread ID.
        summary_text: The new (or updated) summary text.

    Returns:
        True if the thread was found and updated, False otherwise.
    """
    pool = _get_pool()
    now = datetime.now(timezone.utc)
    result = await pool.execute(
        "UPDATE agent_conversations "
        "SET summary = $1, summary_updated_at = $2, updated_at = $2 "
        "WHERE id = $3",
        summary_text, now, thread_id,
    )
    updated = int(result.split()[-1]) if result else 0
    return updated > 0


async def pg_get_messages_since(thread_id: str, since: datetime | None) -> list[dict[str, Any]]:
    """Get messages added after a given timestamp.

    Used by the summary pipeline to identify new messages since the last summary.

    Args:
        thread_id: The conversation thread ID.
        since: Timestamp to filter by. If None, returns all messages.

    Returns:
        List of message dicts with role, content, and created_at.
    """
    pool = _get_pool()
    if since is not None:
        rows = await pool.fetch(
            "SELECT role, content, created_at FROM agent_messages "
            "WHERE thread_id = $1 AND created_at > $2 "
            "ORDER BY created_at ASC",
            thread_id, since,
        )
    else:
        rows = await pool.fetch(
            "SELECT role, content, created_at FROM agent_messages "
            "WHERE thread_id = $1 "
            "ORDER BY created_at ASC",
            thread_id,
        )
    return [
        {
            "role": r["role"],
            "content": r["content"],
            "created_at": r["created_at"].isoformat() if isinstance(r["created_at"], datetime) else r["created_at"],
        }
        for r in rows
    ]


async def pg_get_summary_updated_at(thread_id: str) -> Optional[datetime]:
    """Get the timestamp of the last summary update.

    Returns:
        Datetime or None if no summary has been generated.
    """
    pool = _get_pool()
    row = await pool.fetchrow(
        "SELECT summary_updated_at FROM agent_conversations WHERE id = $1",
        thread_id,
    )
    if row and row["summary_updated_at"]:
        return row["summary_updated_at"]
    return None


# ═══════════════════════════════════════════════════════════════
# Migration Helpers (PG equivalents of AgentManager migration methods)
# ═══════════════════════════════════════════════════════════════

async def pg_ensure_default_agent(
    llm_model: str = "qwen-plus",
    query_history: list[dict] | None = None,
    *,
    owner_id: int | None = None,
    owner_username: str = "admin",
) -> tuple[Optional[dict], Optional[dict]]:
    """Ensure a default agent exists; optionally migrate legacy query_history.

    Replaces: AgentManager.ensure_default_agent()

    Returns:
        (agent_dict, thread_dict) if a new default agent was created,
        (None, None) if one already existed.
    """
    pool = _get_pool()
    if owner_id is None:
        admin = await pool.fetchrow(
            "SELECT id, username FROM users WHERE username = $1",
            owner_username,
        )
        if not admin:
            raise RuntimeError(f"Administrator not found: {owner_username}")
        owner_id = int(admin["id"])
        owner_username = str(admin["username"])
    existing = await pool.fetchval(
        "SELECT count(*) FROM agents WHERE kb_name = 'default' AND name IN ('通用助手', 'default')",
    )
    if existing:
        return None, None

    try:
        agent = await pg_create_agent(
            config={
                "id": "default",
                "name": "通用助手",
                "icon": "🤖",
                "description": "默认智能体，关联默认知识库",
                "welcome_message": "你好！我是通用助手，可以回答知识库中的任何问题。",
                "kb_name": "default",
                "llm_model": llm_model,
                "system_prompt": "",
                "use_default_prompt": True,
            },
            owner_id=owner_id,
            owner_username=owner_username,
        )
    except asyncpg.UniqueViolationError:
        # Concurrent startup workers use the same deterministic ID. The
        # winner owns the row; the loser observes an already-complete baseline.
        return None, None
    agent_id = agent["id"]

    if query_history:
        thread = await pg_create_conversation(
            agent_id, title="旧查询记录", owner_id=owner_id
        )
        thread_id = thread["id"]
        for record in reversed(query_history):
            await pg_add_message(agent_id, thread_id, {
                "role": "user",
                "content": record.get("query", ""),
                "time": record.get("time", ""),
            })
            await pg_add_message(agent_id, thread_id, {
                "role": "assistant",
                "content": record.get("answer", ""),
                "elapsed": record.get("elapsed", 0),
                "kb": record.get("kb", ""),
                "mode": record.get("mode", ""),
            })
        thread = await pg_get_conversation(agent_id, thread_id)
        return agent, thread

    return agent, None


async def pg_migrate_agents(
    owner_id: int | None = None,
    owner_username: str = "admin",
) -> int:
    """Migrate ownerless agents and conversations to the current admin.

    Replaces: AgentManager.migrate_agents()

    Returns:
        Number of agents migrated.
    """
    pool = _get_pool()
    now = datetime.now(timezone.utc)

    if owner_id is None:
        admin = await pool.fetchrow(
            "SELECT id, username FROM users WHERE username = $1",
            owner_username,
        )
        if not admin:
            raise RuntimeError(f"Administrator not found: {owner_username}")
        owner_id = int(admin["id"])
        owner_username = str(admin["username"])

    async with pool.acquire() as conn:
        async with conn.transaction():
            # Migrate agents
            agent_result = await conn.execute(
                "UPDATE agents SET owner_id = $2, owner_username = $3, updated_at = $1 "
                "WHERE owner_id = 0",
                now,
                owner_id,
                owner_username,
            )
            agent_count = int(agent_result.split()[-1]) if agent_result else 0

            # Migrate conversations
            await conn.execute(
                "UPDATE agent_conversations SET owner_id = $2, updated_at = $1 "
                "WHERE owner_id = 0",
                now,
                owner_id,
            )

    if agent_count:
        logger.info("已将 %d 个智能体及其对话分配给管理员", agent_count)

    return agent_count


# ═══════════════════════════════════════════════════════════════
# PG availability check (matches auth.py pattern)
# ═══════════════════════════════════════════════════════════════

def _pg_agent_ready() -> bool:
    """Check if PG is available for agent operations."""
    try:
        from raganything.services.pg_state_repo import get_pg_pool
        get_pg_pool()
        return True
    except (RuntimeError, ImportError):
        return False


__all__ = [
    # Agent CRUD
    "pg_list_agents",
    "pg_get_agent",
    "pg_create_agent",
    "pg_update_agent",
    "pg_delete_agent",
    # Conversation CRUD
    "pg_list_conversations",
    "pg_get_conversation",
    "pg_create_conversation",
    "pg_add_message",
    "pg_update_message",
    "pg_update_conversation",
    "pg_delete_conversation",
    # Summary
    "pg_get_summary",
    "pg_update_summary",
    "pg_get_messages_since",
    "pg_get_summary_updated_at",
    # Migration
    "pg_ensure_default_agent",
    "pg_migrate_agents",
    # Setup
    "pg_ensure_agent_tables",
    "_pg_agent_ready",
]
