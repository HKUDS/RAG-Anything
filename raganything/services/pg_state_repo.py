# -*- coding: utf-8 -*-
"""
═══════════════════════════════════════════════════════════════════════════════
PostgreSQL 连接池 + 基础状态表 仓库
═══════════════════════════════════════════════════════════════════════════════

【文件作用】
  整个系统 PG 数据库的"总入口"。
  - 管理全局 asyncpg 连接池（进程级单例，所有模块共享）
  - 提供 query_history / conversations / messages 三张基础表的 CRUD
  - 其他所有 pg_*_repo.py 都通过本文件的 get_pg_pool() 获取连接

【管理的数据库表】
  ┌──────────────────┬──────────────────────────────────────┐
  │ query_history    │ 查询历史（用户提问 + AI 回答）        │
  │                  │ 不可变审计日志，只 INSERT 不 UPDATE   │
  │                  │ 按 user_id + 时间排序查询             │
  ├──────────────────┼──────────────────────────────────────┤
  │ conversations    │ 多轮对话会话                          │
  │                  │ 记录 conversation_id、标题、创建者    │
  ├──────────────────┼──────────────────────────────────────┤
  │ messages         │ 对话中的每条消息                      │
  │                  │ 角色（user/assistant/system）、内容   │
  │                  │ 按 conversation_id 关联，按时间排序   │
  └──────────────────┴──────────────────────────────────────┘

【核心函数】
  init_pg_pool(dsn, min_size=2, max_size=10)  → 启动时创建连接池（幂等）
  close_pg_pool()                              → 关闭时释放连接池
  get_pg_pool()                                → 获取连接池（其他模块调用此函数）
  insert_query_history(record)                  → 写查询历史
  get_query_history(limit, user_id)             → 读查询历史（支持用户过滤）
  get_or_create_conversation(...)               → 获取或创建对话
  add_message(conversation_id, role, content)   → 添加消息
  get_messages(conversation_id, limit)          → 获取消息列表
  list_conversations(user_id)                   → 列出用户的所有对话
  delete_conversation(conversation_id)          → 删除对话及其消息
  embedding_cache_upsert(key, model, embedding) → 嵌入向量缓存 upsert（PG 函数）

【替换了什么】
  - raganything/services/state_service.py（内存 list + JSON 文件）
  - raganything/query/conversation.py（内存 dict + JSON 文件）

【与其他文件的关系】
  被依赖方 — 所有 pg_*.py 都 import get_pg_pool
  server.py 在 startup/shutdown 时调用 init_pg_pool / close_pg_pool
  对应迁移：migrations/001_shared_state_tables.sql

【初始化方式】
  server.py 启动时自动调用:
    await init_pg_pool(dsn=os.getenv("DATABASE_URL"))
  连接参数从环境变量读取:
    DATABASE_URL 或 POSTGRES_USER/PASSWORD/HOST/PORT/DATABASE

English:
  PostgreSQL-backed state repository for RAG-Anything shared-state.

  Replaces:
    - raganything/services/state_service.py (query_history in-memory list + JSON)
    - raganything/query/conversation.py (ConversationManager in-memory dict + JSON)

  Connection management:
    Uses a single asyncpg connection pool. The pool is created at FastAPI startup
    and closed at shutdown. One pool with min_size=2, max_size=10 is ample for
    the write-light workload (1 INSERT/query, 1 INSERT/message).

  Usage at app startup (main.py or equivalent):
      from raganything.services.pg_state_repo import init_pg_pool, close_pg_pool

      @app.on_event("startup")
      async def startup():
          await init_pg_pool(dsn="postgresql://...")

      @app.on_event("shutdown")
      async def shutdown():
          await close_pg_pool()

  Usage in existing code:
      # Instead of state_service.record_query(entry):
      from raganything.services.pg_state_repo import insert_query_history
      await insert_query_history(record)

      # Instead of state_service.get_query_history(limit=50, user_id=uid):
      from raganything.services.pg_state_repo import get_query_history
      rows = await get_query_history(limit=50, user_id=uid)

      # Instead of ConversationManager:
      from raganything.services.pg_state_repo import (
        get_or_create_thread,
        add_message,
        get_context,
        list_threads,
        delete_thread,
    )
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from typing import Any, Optional

import asyncpg

logger = logging.getLogger("rag_server.pg_state")
MONITOR_EVENTS_MAX_ROWS = int(os.getenv("MONITOR_EVENTS_MAX_ROWS", "5000"))

# ── Global pool ──────────────────────────────────────────────

_pool: Optional[asyncpg.Pool] = None


async def init_pg_pool(
    dsn: str = "",
    *,
    min_size: int = 2,
    max_size: int = 10,
    command_timeout: int = 30,
) -> asyncpg.Pool:
    """Initialize the asyncpg connection pool. Idempotent.

    If dsn is empty, constructs it from POSTGRES_* environment variables
    (matching docker-compose.yml conventions).
    """
    global _pool
    if _pool is not None:
        logger.info("PG pool already initialized, returning existing pool")
        return _pool

    if not dsn:
        # Prefer DATABASE_URL (standard format), fall back to POSTGRES_* env vars
        dsn = os.getenv("DATABASE_URL", "")
    if not dsn:
        user = os.getenv("POSTGRES_USER", "raganything")
        password = os.getenv("POSTGRES_PASSWORD", "raganything")
        host = os.getenv("POSTGRES_HOST", "localhost")
        port = os.getenv("POSTGRES_PORT", "5432")
        database = os.getenv("POSTGRES_DATABASE", os.getenv("POSTGRES_DB", "raganything"))
        dsn = f"postgresql://{user}:{password}@{host}:{port}/{database}"
    else:
        # Parse host/port/database from DSN for logging
        import re
        _m = re.match(r'postgresql://[^@]*@([^:/]+)(?::(\d+))?/([^?]+)', dsn)
        host = _m.group(1) if _m else '?'
        port = _m.group(2) if _m and _m.group(2) else '5432'
        database = _m.group(3) if _m else '?'

    _pool = await asyncpg.create_pool(
        dsn=dsn,
        min_size=min_size,
        max_size=max_size,
        command_timeout=command_timeout,
    )
    logger.info(f"PG pool initialized: min={min_size}, max={max_size}, dsn=***@{host}:{port}/{database}")

    # Verify tables exist (lightweight health check)
    async with _pool.acquire() as conn:
        tables = await conn.fetchval(
            "SELECT count(*) FROM information_schema.tables "
            "WHERE table_schema = 'public' AND table_name = ANY($1)",
            ["query_history", "conversations", "messages"],
        )
        logger.info(f"PG state tables present: {tables}/3")

    return _pool


async def close_pg_pool() -> None:
    """Close the connection pool. Safe to call multiple times."""
    global _pool
    if _pool is not None:
        await _pool.close()
        _pool = None
        logger.info("PG pool closed")


def _get_pool() -> asyncpg.Pool:
    """Get the pool, raising if not initialized."""
    if _pool is None:
        raise RuntimeError(
            "PG pool not initialized. Call init_pg_pool() at app startup."
        )
    return _pool


def get_pg_pool() -> asyncpg.Pool:
    """Public accessor for the shared PG connection pool.

    Used by pg_auth_repo.py and other modules that need database access.
    """
    return _get_pool()


# ═══════════════════════════════════════════════════════════════
# monitor_events
# ═══════════════════════════════════════════════════════════════

async def ensure_monitor_event_table() -> None:
    """Ensure the persistent monitor event table exists."""
    pool = _get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """
            CREATE TABLE IF NOT EXISTS monitor_events (
                id          BIGSERIAL PRIMARY KEY,
                created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                event       TEXT NOT NULL,
                user_id     INTEGER NOT NULL DEFAULT 0,
                payload     JSONB NOT NULL DEFAULT '{}'::jsonb
            )
            """
        )
        await conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_monitor_events_created "
            "ON monitor_events(created_at DESC, id DESC)"
        )
        await conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_monitor_events_user_created "
            "ON monitor_events(user_id, created_at DESC, id DESC)"
        )


async def insert_monitor_event(
    record: dict[str, Any],
    *,
    max_rows: int = MONITOR_EVENTS_MAX_ROWS,
) -> None:
    """Persist one monitor event and prune old rows if needed."""
    import json as _json
    from datetime import datetime as _datetime

    event_time = record.get("time")
    if isinstance(event_time, str):
        event_time = _datetime.fromisoformat(event_time)

    payload = {
        key: value
        for key, value in record.items()
        if key not in {"time", "event", "user_id"}
    }
    payload_str = _json.dumps(payload, ensure_ascii=False, default=str)

    pool = _get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            await conn.execute(
                """
                INSERT INTO monitor_events (created_at, event, user_id, payload)
                VALUES ($1::timestamptz, $2, $3, $4::jsonb)
                """,
                event_time,
                record.get("event", ""),
                int(record.get("user_id", 0) or 0),
                payload_str,
            )
            if max_rows > 0:
                await conn.execute(
                    """
                    DELETE FROM monitor_events
                    WHERE id IN (
                        SELECT id
                        FROM monitor_events
                        ORDER BY created_at DESC, id DESC
                        OFFSET $1
                    )
                    """,
                    max_rows,
                )


async def get_monitor_events(
    limit: int = 50,
    user_id: Optional[int] = None,
    *,
    include_global: bool = True,
) -> list[dict[str, Any]]:
    """Get recent persistent monitor events in chronological order."""
    pool = _get_pool()
    async with pool.acquire() as conn:
        if user_id is None:
            rows = await conn.fetch(
                """
                SELECT created_at, event, user_id, payload
                FROM monitor_events
                ORDER BY created_at DESC, id DESC
                LIMIT $1
                """,
                limit,
            )
        elif include_global:
            rows = await conn.fetch(
                """
                SELECT created_at, event, user_id, payload
                FROM monitor_events
                WHERE user_id IN (0, $1)
                ORDER BY created_at DESC, id DESC
                LIMIT $2
                """,
                user_id,
                limit,
            )
        else:
            rows = await conn.fetch(
                """
                SELECT created_at, event, user_id, payload
                FROM monitor_events
                WHERE user_id = $1
                ORDER BY created_at DESC, id DESC
                LIMIT $2
                """,
                user_id,
                limit,
            )

    events: list[dict[str, Any]] = []
    for row in reversed(rows):
        payload = row["payload"] or {}
        event = {
            "time": row["created_at"].isoformat(),
            "event": row["event"],
            "user_id": row["user_id"],
        }
        if isinstance(payload, dict):
            event.update(payload)
        events.append(event)
    return events


# ═══════════════════════════════════════════════════════════════
# query_history
# ═══════════════════════════════════════════════════════════════

async def insert_query_history(record: dict[str, Any]) -> None:
    """Insert a query history record.

    Args:
        record: Full record dict matching the agent.py:583-592 structure.
                Required keys: id, query, mode, agent_mode, answer,
                reasoning_trace, images, time, elapsed, kb, agent_id,
                thread_id, user_id, username, fallback.

    Raises:
        asyncpg.IntegrityConstraintViolationError: if id already exists.
    """
    # asyncpg requires explicit JSON strings for JSONB columns
    # (matching pg_agent_repo.py:pg_add_message pattern)
    import json as _json
    from datetime import datetime as _datetime
    reasoning_trace = record.get("reasoning_trace", {})
    reasoning_trace_str = _json.dumps(reasoning_trace, ensure_ascii=False) if isinstance(reasoning_trace, (dict, list)) else str(reasoning_trace)
    images = record.get("images", [])
    images_str = _json.dumps(images, ensure_ascii=False) if isinstance(images, (dict, list)) else str(images)
    # asyncpg needs a datetime object for timestamptz, not an ISO string
    _time = record.get("time")
    if isinstance(_time, str):
        _time = _datetime.fromisoformat(_time)

    pool = _get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO query_history (
                id, query, mode, agent_mode, answer,
                reasoning_trace, images, time, elapsed, kb,
                agent_id, thread_id, user_id, username, fallback
            ) VALUES (
                $1, $2, $3, $4, $5,
                $6::jsonb, $7::jsonb, $8::timestamptz, $9, $10,
                $11, $12, $13, $14, $15
            )
            """,
            record.get("id", ""),
            record.get("query", ""),
            record.get("mode", "text"),
            record.get("agent_mode", "none"),
            record.get("answer", ""),
            reasoning_trace_str,
            images_str,
            _time,
            record.get("elapsed", 0.0),
            record.get("kb", ""),
            record.get("agent_id", ""),
            record.get("thread_id", ""),
            record.get("user_id", 0),
            record.get("username", ""),
            record.get("fallback", False),
        )


async def get_query_history(
    limit: int = 50,
    user_id: Optional[int] = None,
) -> list[dict[str, Any]]:
    """Get recent query history, optionally filtered by user.

    Replaces: state_service.get_query_history()

    Uses the composite index idx_query_history_user_time when user_id
    is provided, or idx_query_history_time for unfiltered admin queries.
    Both produce an Index Scan + Limit with no sort step.
    """
    pool = _get_pool()
    async with pool.acquire() as conn:
        if user_id is not None:
            rows = await conn.fetch(
                """
                SELECT id, query, mode, agent_mode, answer,
                       reasoning_trace, images, time, elapsed, kb,
                       agent_id, thread_id, user_id, username, fallback
                FROM query_history
                WHERE user_id = $1
                ORDER BY time DESC
                LIMIT $2
                """,
                user_id, limit,
            )
        else:
            rows = await conn.fetch(
                """
                SELECT id, query, mode, agent_mode, answer,
                       reasoning_trace, images, time, elapsed, kb,
                       agent_id, thread_id, user_id, username, fallback
                FROM query_history
                ORDER BY time DESC
                LIMIT $1
                """,
                limit,
            )
    return [dict(row) for row in rows]


async def prune_query_history(max_rows: int = 100) -> int:
    """Delete oldest records exceeding max_rows, keeping the most recent.

    Call this after each insert (or periodically) to replace the old
    in-memory cap of 100 entries. Returns number of rows deleted.
    """
    pool = _get_pool()
    async with pool.acquire() as conn:
        count = await conn.fetchval(
            "SELECT count(*) FROM query_history"
        )
        if count <= max_rows:
            return 0
        excess = count - max_rows
        await conn.execute(
            """
            DELETE FROM query_history
            WHERE id IN (
                SELECT id FROM query_history
                ORDER BY time ASC
                LIMIT $1
            )
            """,
            excess,
        )
        logger.info(f"Pruned {excess} old query_history records (kept {max_rows})")
        return excess


# ═══════════════════════════════════════════════════════════════
# conversations + messages
# ═══════════════════════════════════════════════════════════════

# Internal cap constants (mirrors old ConversationManager defaults)
MAX_THREADS_PER_USER = 50
MAX_MESSAGE_LENGTH = 10000


async def get_or_create_thread(
    user_id: int,
    thread_id: str = "",
    title: str = "新对话",
) -> dict[str, Any]:
    """Get an existing thread or create a new one.

    Replaces: ConversationManager.get_or_create_thread()

    Returns:
        Thread dict with keys: id, user_id, title, created_at, updated_at
        If user has >= MAX_THREADS_PER_USER, returns {"error": "..."}
    """
    pool = _get_pool()

    # Check existing thread
    if thread_id:
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT id, user_id, title, created_at, updated_at "
                "FROM conversations WHERE id = $1",
                thread_id,
            )
            if row is not None:
                thread = dict(row)
                if thread["user_id"] == user_id:
                    return thread
                return {}  # thread exists but belongs to different user

    # Enforce per-user cap
    async with pool.acquire() as conn:
        user_count = await conn.fetchval(
            "SELECT count(*) FROM conversations WHERE user_id = $1",
            user_id,
        )
        if user_count >= MAX_THREADS_PER_USER:
            return {"error": f"已达到最大会话数限制（{MAX_THREADS_PER_USER}）"}

        # Create new thread
        new_id = thread_id or f"th_{os.urandom(6).hex()}"  # 12-char hex
        title = title[:50] if title else "新对话"
        row = await conn.fetchrow(
            """
            INSERT INTO conversations (id, user_id, title)
            VALUES ($1, $2, $3)
            ON CONFLICT (id) DO NOTHING
            RETURNING id, user_id, title, created_at, updated_at
            """,
            new_id, user_id, title,
        )
        if row is None:
            # Race: another request created it between our count check and insert
            row = await conn.fetchrow(
                "SELECT id, user_id, title, created_at, updated_at "
                "FROM conversations WHERE id = $1",
                new_id,
            )
        logger.info(f"Created thread {new_id} for user {user_id}")
        return dict(row) if row else {}


async def add_message(
    thread_id: str,
    role: str,
    content: str,
) -> None:
    """Append a message to a conversation thread.

    Replaces: ConversationManager.add_message()

    Truncates content to MAX_MESSAGE_LENGTH chars. Updates the thread's
    updated_at via the trigger trg_conversations_updated_at.
    """
    if role not in ("user", "assistant", "system"):
        logger.warning(f"Invalid message role: {role}")
        return
    content = content[:MAX_MESSAGE_LENGTH] if len(content) > MAX_MESSAGE_LENGTH else content

    pool = _get_pool()
    async with pool.acquire() as conn:
        # Verify thread exists
        exists = await conn.fetchval(
            "SELECT 1 FROM conversations WHERE id = $1", thread_id
        )
        if not exists:
            logger.warning(f"Thread {thread_id} not found for add_message")
            return

        async with conn.transaction():
            await conn.execute(
                """
                INSERT INTO messages (thread_id, role, content)
                VALUES ($1, $2, $3)
                """,
                thread_id, role, content,
            )
            # Touch updated_at (trigger handles this, but explicit UPDATE
            # ensures it even if the trigger is dropped)
            await conn.execute(
                "UPDATE conversations SET updated_at = NOW() WHERE id = $1",
                thread_id,
            )


async def _estimate_tokens(text: str) -> int:
    """Rough token estimate: chars / 2 (Chinese-friendly)."""
    return max(1, len(text) // 2)


async def get_context(
    thread_id: str,
    current_query: str = "",
    max_rounds: int = 10,
    max_tokens: int = 2000,
) -> dict[str, Any]:
    """Extract conversation context for LLM prompt injection.

    Replaces: ConversationManager.get_context()

    Fetches the last N messages from the thread, applies token-budget
    truncation (oldest-first eviction), and returns formatted history.

    Returns dict with keys: history_text, messages, round_count, estimated_tokens
    """
    pool = _get_pool()

    async with pool.acquire() as conn:
        # Verify thread exists
        exists = await conn.fetchval(
            "SELECT 1 FROM conversations WHERE id = $1", thread_id
        )
        if not exists:
            return {
                "history_text": "",
                "messages": [],
                "round_count": 0,
                "estimated_tokens": 0,
            }

        # Fetch last N*2 messages (N rounds of user+assistant)
        max_msgs = max_rounds * 2
        rows = await conn.fetch(
            """
            SELECT role, content, created_at
            FROM messages
            WHERE thread_id = $1
            ORDER BY created_at DESC
            LIMIT $2
            """,
            thread_id, max_msgs,
        )

    if not rows:
        return {
            "history_text": "",
            "messages": [],
            "round_count": 0,
            "estimated_tokens": 0,
        }

    # Reconstruct message list (chronological order) and apply token budget
    all_msgs = [dict(row) for row in reversed(rows)]

    lines = []
    token_count = 0
    selected = []
    for msg in reversed(all_msgs):
        label = "用户" if msg["role"] == "user" else "助手"
        line = f"{label}: {msg['content']}"
        est = await _estimate_tokens(line)
        if token_count + est > max_tokens:
            break
        lines.insert(0, line)
        selected.insert(0, msg)
        token_count += est

    return {
        "history_text": "\n".join(lines),
        "messages": selected,
        "round_count": len(selected) // 2,
        "estimated_tokens": token_count,
    }


async def get_context_for_rewrite(
    thread_id: str,
    max_rounds: int = 3,
) -> list[dict[str, Any]]:
    """Get last N rounds for query rewriting context.

    Replaces: ConversationManager.get_context_for_rewrite()
    """
    pool = _get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT role, content
            FROM messages
            WHERE thread_id = $1
            ORDER BY created_at DESC
            LIMIT $2
            """,
            thread_id, max_rounds * 2,
        )
    return [{"role": row["role"], "content": row["content"]} for row in reversed(rows)]


async def list_threads(user_id: int) -> list[dict[str, Any]]:
    """List all threads for a user, newest first.

    Replaces: ConversationManager.list_threads()

    Uses idx_conversations_user_updated for Index Scan + no sort.
    """
    pool = _get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT
                c.id, c.title, c.created_at, c.updated_at,
                count(m.id) AS message_count
            FROM conversations c
            LEFT JOIN messages m ON m.thread_id = c.id
            WHERE c.user_id = $1
            GROUP BY c.id
            ORDER BY c.updated_at DESC
            """,
            user_id,
        )
    return [dict(row) for row in rows]


async def delete_thread(thread_id: str) -> bool:
    """Delete a conversation thread and all its messages (CASCADE).

    Replaces: ConversationManager.delete_thread()
    """
    pool = _get_pool()
    async with pool.acquire() as conn:
        result = await conn.execute(
            "DELETE FROM conversations WHERE id = $1", thread_id
        )
    # asyncpg returns the command tag, e.g. "DELETE 1" or "DELETE 0"
    deleted = result != "DELETE 0"
    if deleted:
        logger.info(f"Deleted thread {thread_id} (messages cascade-deleted)")
    return deleted


async def thread_exists(thread_id: str, user_id: int = 0) -> bool:
    """Check if a thread exists, optionally scoped to a user.

    Replaces: ConversationManager.thread_exists()
    """
    pool = _get_pool()
    async with pool.acquire() as conn:
        if user_id:
            return await conn.fetchval(
                "SELECT EXISTS(SELECT 1 FROM conversations WHERE id = $1 AND user_id = $2)",
                thread_id, user_id,
            )
        return await conn.fetchval(
            "SELECT EXISTS(SELECT 1 FROM conversations WHERE id = $1)",
            thread_id,
        )


async def get_stats() -> dict[str, Any]:
    """Get storage statistics.

    Replaces: ConversationManager.get_stats()
    """
    pool = _get_pool()
    async with pool.acquire() as conn:
        thread_count = await conn.fetchval("SELECT count(*) FROM conversations")
        msg_count = await conn.fetchval("SELECT count(*) FROM messages")
        history_count = await conn.fetchval("SELECT count(*) FROM query_history")
    return {
        "total_threads": thread_count,
        "total_messages": msg_count,
        "total_history_records": history_count,
        "storage_backend": "postgresql",
    }
