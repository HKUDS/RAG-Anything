# -*- coding: utf-8 -*-
"""
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
from typing import Any, Optional

logger = logging.getLogger("rag_server.pg_agent")


def _get_pool():
    """Get the shared PG pool. Raises RuntimeError if not initialized."""
    from raganything.services.pg_state_repo import get_pg_pool
    return get_pg_pool()


# ═══════════════════════════════════════════════════════════════
# Agent CRUD
# ═══════════════════════════════════════════════════════════════

async def pg_list_agents(
    user_id: Optional[int] = None,
    is_admin: bool = False,
) -> list[dict[str, Any]]:
    """List agents with user isolation (admin sees all).

    Replaces: AgentManager.list_agents()

    Returns:
        List of agent dicts sorted by updated_at DESC.
    """
    pool = _get_pool()
    if is_admin or user_id is None:
        rows = await pool.fetch(
            "SELECT * FROM agents ORDER BY updated_at DESC"
        )
    else:
        rows = await pool.fetch(
            "SELECT * FROM agents WHERE owner_id = $1 OR owner_id = 0 "
            "ORDER BY updated_at DESC",
            user_id,
        )
    return [_agent_row_to_dict(r) for r in rows]


async def pg_get_agent(agent_id: str) -> Optional[dict[str, Any]]:
    """Get a single agent by ID.

    Replaces: AgentManager.get_agent()
    """
    pool = _get_pool()
    row = await pool.fetchrow(
        "SELECT * FROM agents WHERE id = $1",
        agent_id,
    )
    return _agent_row_to_dict(row) if row else None


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
    # Build SET clause from non-None updates
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

    # updated_at is auto-set by trigger, but we update it explicitly
    # in case the trigger isn't present
    now = datetime.now(timezone.utc)
    set_parts.append(f"updated_at = ${idx}")
    values.append(now)
    idx += 1

    values.append(agent_id)
    sql = (
        f"UPDATE agents SET {', '.join(set_parts)} "
        f"WHERE id = ${idx} "
        f"RETURNING *"
    )

    pool = _get_pool()
    row = await pool.fetchrow(sql, *values)
    return _agent_row_to_dict(row) if row else None


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

    # Fetch messages
    msg_rows = await pool.fetch(
        "SELECT role, content, metadata, created_at "
        "FROM agent_messages "
        "WHERE thread_id = $1 "
        "ORDER BY created_at ASC",
        thread_id,
    )
    thread["messages"] = [
        {
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
    for ts_field in ("created_at", "updated_at"):
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
    "pg_update_conversation",
    "pg_delete_conversation",
    # Setup
    "pg_ensure_agent_tables",
    "_pg_agent_ready",
]
