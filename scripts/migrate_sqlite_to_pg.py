#!/usr/bin/env python3
"""
RAG-Anything SQLite → PostgreSQL 数据迁移脚本

功能：将 auth.db (SQLite) 和 query_history.json 中的数据迁移到 PostgreSQL。

安全设计：
  - --dry-run: 预览模式，只读不写，显示将要迁移的数据
  - 幂等：所有 INSERT 使用 ON CONFLICT，可重复执行
  - 保留用户 ID：确保外键引用正确
  - 自动修复序列：确保新用户 ID 不冲突

用法:
  python scripts/migrate_sqlite_to_pg.py --dry-run    # 预览
  python scripts/migrate_sqlite_to_pg.py               # 执行迁移
  python scripts/migrate_sqlite_to_pg.py --only users  # 只迁移用户
"""

import argparse
import asyncio
import json
import os
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv
load_dotenv(dotenv_path=ROOT / ".env", override=False)

import asyncpg


# ── Helpers ─────────────────────────────────────────────────

def _parse_dt(value: str | None) -> datetime | None:
    """Parse a SQLite datetime string to a timezone-aware datetime.

    SQLite stores dates as strings like '2026-06-18 17:24:28'.
    PostgreSQL TIMESTAMPTZ needs a proper datetime object.
    """
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    s = str(value).strip()
    if not s:
        return None
    # Try common formats
    for fmt in (
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d %H:%M:%S.%f",
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%dT%H:%M:%S.%f",
        "%Y-%m-%dT%H:%M:%S%z",
        "%Y-%m-%dT%H:%M:%S.%f%z",
    ):
        try:
            return datetime.strptime(s, fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    # ISO format with timezone
    try:
        return datetime.fromisoformat(s)
    except ValueError:
        print(f"  [WARN] 无法解析日期: {s!r}")
        return None


# ── Config ─────────────────────────────────────────────────
AUTH_DB = ROOT / os.getenv("AUTH_DB_PATH", "auth.db")
QUERY_HISTORY_FILE = ROOT / "query_history.json"
CONVERSATIONS_FILE = ROOT / "conversations.json"


def get_dsn() -> str:
    dsn = os.getenv("DATABASE_URL", "")
    if dsn:
        return dsn
    user = os.getenv("POSTGRES_USER", "raganything")
    pw = os.getenv("POSTGRES_PASSWORD", "raganything")
    host = os.getenv("POSTGRES_HOST", "localhost")
    port = os.getenv("POSTGRES_PORT", "5432")
    db = os.getenv("POSTGRES_DATABASE", os.getenv("POSTGRES_DB", "raganything"))
    return f"postgresql://{user}:{pw}@{host}:{port}/{db}"


# ── SQLite read helpers ────────────────────────────────────

def read_users() -> list[dict]:
    if not AUTH_DB.exists():
        print(f"[SKIP] auth.db 不存在: {AUTH_DB}")
        return []
    conn = sqlite3.connect(str(AUTH_DB))
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT id, username, password_hash, role_id, is_admin,"
        "  is_active, failed_login_attempts, locked_until, last_login_at,"
        "  must_change_password, created_at"
        " FROM users ORDER BY id"
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def read_audit_logs() -> list[dict]:
    if not AUTH_DB.exists():
        return []
    conn = sqlite3.connect(str(AUTH_DB))
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT id, actor_id, action, target_user_id, details,"
        "  ip_address, created_at FROM audit_logs ORDER BY id"
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def read_token_revocations() -> list[dict]:
    if not AUTH_DB.exists():
        return []
    conn = sqlite3.connect(str(AUTH_DB))
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT jti, expires_at, revoked_at FROM token_revocations"
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def read_query_history() -> list[dict]:
    if not QUERY_HISTORY_FILE.exists():
        print(f"[SKIP] query_history.json 不存在: {QUERY_HISTORY_FILE}")
        return []
    data = json.loads(QUERY_HISTORY_FILE.read_text(encoding="utf-8"))
    return data if isinstance(data, list) else []


def read_conversations() -> dict:
    if not CONVERSATIONS_FILE.exists():
        return {}
    data = json.loads(CONVERSATIONS_FILE.read_text(encoding="utf-8"))
    if isinstance(data, dict) and "threads" in data:
        return data["threads"]
    return {}


# ── PG helpers ─────────────────────────────────────────────

async def pg_user_exists(conn: asyncpg.Connection, username: str) -> bool:
    row = await conn.fetchrow(
        "SELECT 1 FROM users WHERE username = $1", username
    )
    return row is not None


async def migrate_users(
    conn: asyncpg.Connection, users: list[dict], dry_run: bool
) -> int:
    count = 0
    for u in users:
        if await pg_user_exists(conn, u["username"]):
            print(f"  [SKIP] 用户已存在: {u['username']} (id={u['id']})")
            continue

        if dry_run:
            print(f"  [DRY-RUN] 将创建用户: {u['username']} (id={u['id']}, "
                  f"role_id={u['role_id']}, is_admin={u['is_admin']})")
            count += 1
            continue

        await conn.execute(
            """
            INSERT INTO users (
                id, username, password_hash, role_id, is_admin,
                is_active, failed_login_attempts, locked_until, last_login_at,
                must_change_password, created_at
            ) VALUES (
                $1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11
            )
            ON CONFLICT (id) DO NOTHING
            """,
            u["id"], u["username"], u["password_hash"],
            u["role_id"], u["is_admin"], u["is_active"],
            u["failed_login_attempts"],
            _parse_dt(u["locked_until"]),
            _parse_dt(u["last_login_at"]),
            u["must_change_password"],
            _parse_dt(u["created_at"]),
        )
        print(f"  [OK] 用户已迁移: {u['username']} (id={u['id']})")
        count += 1

    # Fix sequence
    if count > 0 and not dry_run:
        await conn.execute(
            "SELECT setval('users_id_seq', COALESCE((SELECT MAX(id) FROM users), 1))"
        )
        print(f"  [SEQ] users_id_seq 已修复")
    return count


async def migrate_audit_logs(
    conn: asyncpg.Connection, logs: list[dict], dry_run: bool
) -> int:
    count = 0
    for r in logs:
        # Parse details: SQLite stores as TEXT, PG expects JSONB
        details = r["details"]
        if isinstance(details, str):
            try:
                details = json.loads(details)
            except (json.JSONDecodeError, TypeError):
                details = {}
        elif details is None:
            details = {}

        if dry_run:
            print(f"  [DRY-RUN] 将迁移审计日志: id={r['id']} action={r['action']}")
            count += 1
            continue

        try:
            await conn.execute(
                """
                INSERT INTO audit_logs (
                    id, actor_id, action, target_user_id, details,
                    ip_address, created_at
                ) VALUES ($1, $2, $3, $4, $5::jsonb, $6, $7)
                ON CONFLICT (id) DO NOTHING
                """,
                r["id"], r["actor_id"], r["action"], r["target_user_id"],
                json.dumps(details), r["ip_address"],
                _parse_dt(r["created_at"]),
            )
            print(f"  [OK] 审计日志已迁移: id={r['id']}")
            count += 1
        except Exception as exc:
            print(f"  [WARN] 审计日志迁移失败 id={r['id']}: {exc}")

    return count


async def migrate_token_revocations(
    conn: asyncpg.Connection, tokens: list[dict], dry_run: bool
) -> int:
    count = 0
    for r in tokens:
        if dry_run:
            print(f"  [DRY-RUN] 将迁移 Token 撤销: jti={r['jti']}")
            count += 1
            continue

        try:
            await conn.execute(
                """
                INSERT INTO token_revocations (jti, expires_at, revoked_at)
                VALUES ($1, $2, $3)
                ON CONFLICT (jti) DO NOTHING
                """,
                r["jti"],
                _parse_dt(r["expires_at"]),
                _parse_dt(r["revoked_at"]),
            )
            print(f"  [OK] Token 撤销已迁移: {r['jti'][:30]}...")
            count += 1
        except Exception as exc:
            print(f"  [WARN] Token 撤销迁移失败 {r['jti'][:30]}...: {exc}")

    return count


async def migrate_query_history(
    conn: asyncpg.Connection, entries: list[dict], dry_run: bool
) -> int:
    count = 0
    for q in entries:
        entry_id = q.get("id", "")

        # Parse images as JSONB
        images = q.get("images", [])
        if isinstance(images, str):
            try:
                images = json.loads(images)
            except (json.JSONDecodeError, TypeError):
                images = []

        if dry_run:
            print(f"  [DRY-RUN] 将迁移查询历史: id={entry_id} "
                  f"query={q.get('query','')[:40]}...")
            count += 1
            continue

        try:
            await conn.execute(
                """
                INSERT INTO query_history (
                    id, query, mode, agent_mode, answer, reasoning_trace,
                    images, time, elapsed, kb, agent_id, thread_id,
                    user_id, username, fallback
                ) VALUES (
                    $1, $2, $3, $4, $5, $6, $7::jsonb, $8, $9,
                    $10, $11, $12, $13, $14, $15
                )
                ON CONFLICT (id) DO NOTHING
                """,
                entry_id,
                q.get("query", "") or "",
                q.get("mode", "") or "",
                q.get("agent_mode", "none"),
                q.get("answer", "") or "",
                json.dumps(q.get("reasoning_trace", {})),
                json.dumps(images),
                _parse_dt(q.get("time")),
                float(q.get("elapsed", 0) or 0),
                q.get("kb", "") or "",
                q.get("agent_id", "") or "",
                q.get("thread_id", "") or "",
                int(q.get("user_id", 0) or 0),
                q.get("username", "") or "",
                bool(q.get("fallback", False)),
            )
            count += 1
        except Exception as exc:
            print(f"  [WARN] 查询历史迁移失败 {entry_id}: {exc}")

    if count > 0:
        print(f"  [OK] 查询历史已迁移: {count} 条")
    return count


async def migrate_conversations(
    conn: asyncpg.Connection, threads: dict, dry_run: bool
) -> tuple[int, int]:
    """Migrate conversations.json threads to PG conversations + messages tables."""
    conv_count = 0
    msg_count = 0
    if not threads:
        return 0, 0

    for thread_id, tdata in threads.items():
        msgs = tdata.get("messages", [])
        if not msgs:
            continue

        # Use the first message's timestamp as conversation created_at
        first_ts = msgs[0].get("time", "1970-01-01T00:00:00Z") if msgs else None
        title = tdata.get("title", thread_id[:8])

        if dry_run:
            print(f"  [DRY-RUN] 将迁移对话: {thread_id} ({len(msgs)} 条消息)")
            conv_count += 1
            msg_count += len(msgs)
            continue

        try:
            await conn.execute(
                """
                INSERT INTO conversations (id, title, user_id, username, created_at, updated_at)
                VALUES ($1, $2, $3, $4, $5, $5)
                ON CONFLICT (id) DO NOTHING
                """,
                thread_id, title,
                int(tdata.get("user_id", 0) or 0),
                tdata.get("username", "") or "",
                _parse_dt(first_ts),
            )
        except Exception as exc:
            print(f"  [WARN] 对话创建失败 {thread_id}: {exc}")
            continue

        for msg in msgs:
            try:
                await conn.execute(
                    """
                    INSERT INTO messages (conversation_id, role, content, images, time)
                    VALUES ($1, $2, $3, $4::jsonb, $5)
                    ON CONFLICT DO NOTHING
                    """,
                    thread_id,
                    msg.get("role", "user"),
                    msg.get("content", ""),
                    json.dumps(msg.get("images", [])),
                    _parse_dt(msg.get("time", "1970-01-01T00:00:00Z")),
                )
                msg_count += 1
            except Exception as exc:
                print(f"  [WARN] 消息迁移失败 thread={thread_id}: {exc}")

        conv_count += 1

    return conv_count, msg_count


# ── Main ───────────────────────────────────────────────────

async def main():
    parser = argparse.ArgumentParser(
        description="RAG-Anything SQLite → PostgreSQL 数据迁移"
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="预览模式：只读不写，显示将要迁移的数据"
    )
    parser.add_argument(
        "--only", type=str, default="",
        help="只迁移指定类型: users, audit_logs, token_revocations, query_history, conversations"
    )
    args = parser.parse_args()

    if args.dry_run:
        print("=" * 60)
        print("  🔍 DRY-RUN 模式 — 不会修改任何数据")
        print("=" * 60)

    dsn = get_dsn()
    # Mask password for display
    display_dsn = dsn
    if "@" in dsn:
        parts = dsn.split("@")
        if ":" in parts[0]:
            proto_user = parts[0].rsplit(":", 1)[0]
            display_dsn = f"{proto_user}:****@{parts[1]}"
    print(f"\n📡 连接: {display_dsn}")

    conn = await asyncpg.connect(dsn=dsn)
    try:
        await conn.execute("SELECT 1")
        print("✅ 数据库连接成功\n")

        total = {"users": 0, "audit_logs": 0, "token_revocations": 0,
                 "query_history": 0, "conversations": 0, "messages": 0}

        # ── 1. Users ──
        if not args.only or "user" in args.only:
            print("─" * 40)
            print("👤 迁移用户...")
            users = read_users()
            print(f"  SQLite 共 {len(users)} 个用户")
            # Show existing PG users
            pg_users = await conn.fetchval("SELECT count(*) FROM users")
            print(f"  PG 现有 {pg_users} 个用户")
            total["users"] = await migrate_users(conn, users, args.dry_run)
            print(f"  → {'将' if args.dry_run else '已'}迁移 {total['users']} 个用户")

        # ── 2. Audit Logs ──
        if not args.only or "audit" in args.only:
            print("\n" + "─" * 40)
            print("📋 迁移审计日志...")
            logs = read_audit_logs()
            print(f"  SQLite 共 {len(logs)} 条")
            total["audit_logs"] = await migrate_audit_logs(conn, logs, args.dry_run)
            print(f"  → {'将' if args.dry_run else '已'}迁移 {total['audit_logs']} 条")

        # ── 3. Token Revocations ──
        if not args.only or "token" in args.only:
            print("\n" + "─" * 40)
            print("🔑 迁移 Token 撤销记录...")
            tokens = read_token_revocations()
            print(f"  SQLite 共 {len(tokens)} 条")
            total["token_revocations"] = await migrate_token_revocations(
                conn, tokens, args.dry_run
            )
            print(f"  → {'将' if args.dry_run else '已'}迁移 {total['token_revocations']} 条")

        # ── 4. Query History ──
        if not args.only or "query" in args.only:
            print("\n" + "─" * 40)
            print("💬 迁移查询历史...")
            entries = read_query_history()
            print(f"  JSON 共 {len(entries)} 条")
            total["query_history"] = await migrate_query_history(
                conn, entries, args.dry_run
            )
            print(f"  → {'将' if args.dry_run else '已'}迁移 {total['query_history']} 条")

        # ── 5. Conversations ──
        if not args.only or "conversation" in args.only:
            print("\n" + "─" * 40)
            print("📝 迁移多轮对话...")
            threads = read_conversations()
            print(f"  JSON 共 {len(threads)} 个对话线程")
            total["conversations"], total["messages"] = await migrate_conversations(
                conn, threads, args.dry_run
            )
            print(f"  → {'将' if args.dry_run else '已'}迁移 {total['conversations']} 个对话, "
                  f"{total['messages']} 条消息")

        # ── Summary ──
        print("\n" + "=" * 60)
        if args.dry_run:
            total_count = sum(total.values())
            print(f"  🔍 DRY-RUN 完成。将迁移 {total_count} 条记录。")
            print("  执行实际迁移: python scripts/migrate_sqlite_to_pg.py")
        else:
            total_count = sum(total.values())
            print(f"  ✅ 迁移完成！共迁移 {total_count} 条记录。")
        print("=" * 60)

    finally:
        await conn.close()


if __name__ == "__main__":
    asyncio.run(main())
