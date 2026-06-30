# -*- coding: utf-8 -*-
"""
PostgreSQL-backed auth repository for RAG-Anything.

Replaces: raganything/services/auth.py (SQLite/aiosqlite backend)
Activated: When DATABASE_URL or POSTGRES_HOST env var is set.

Uses the same connection pool as pg_state_repo.py via get_pg_pool().
"""

from __future__ import annotations

import json
import logging
import os
import secrets
import uuid
from datetime import datetime, timedelta
from typing import Any, Optional

import asyncpg
import jwt as pyjwt
from passlib.context import CryptContext

logger = logging.getLogger("rag_server.pg_auth")

# ── Password Hashing ───────────────────────────────────────
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# ── JWT Configuration ──────────────────────────────────────
SECRET_KEY = os.getenv("JWT_SECRET") or secrets.token_hex(32)
REFRESH_SECRET_KEY = os.getenv("JWT_REFRESH_SECRET") or secrets.token_hex(32)
JWT_EXPIRY_HOURS = int(os.getenv("JWT_EXPIRY_HOURS", "1"))
REFRESH_EXPIRY_DAYS = int(os.getenv("REFRESH_EXPIRY_DAYS", "7"))
ALGORITHM = "HS256"
SERVER_START_ID = uuid.uuid4().hex

# ── Brute-Force Protection ─────────────────────────────────
MAX_FAILED_ATTEMPTS = int(os.getenv("MAX_FAILED_LOGIN_ATTEMPTS", "5"))
LOCKOUT_DURATION_MINUTES = int(os.getenv("LOGIN_LOCKOUT_MINUTES", "15"))

# ── Default Admin ──────────────────────────────────────────
DEFAULT_ADMIN_USERNAME = os.getenv("DEFAULT_ADMIN_USERNAME", "admin")
DEFAULT_ADMIN_EMAIL = os.getenv("DEFAULT_ADMIN_EMAIL", "admin@raganything.local")
_raw_admin_pw = os.getenv("DEFAULT_ADMIN_PASSWORD")
if not _raw_admin_pw:
    _raw_admin_pw = secrets.token_urlsafe(16)
    import sys
    print("=" * 60, file=sys.stderr)
    print("[PG-AUTH] DEFAULT_ADMIN_PASSWORD 环境变量未设置。", file=sys.stderr)
    print(f"[PG-AUTH] 已生成随机管理员密码（仅显示一次）: {_raw_admin_pw}", file=sys.stderr)
    print("[PG-AUTH] 请立即修改此密码或设置 DEFAULT_ADMIN_PASSWORD 环境变量", file=sys.stderr)
    print("=" * 60, file=sys.stderr)
DEFAULT_ADMIN_PASSWORD = _raw_admin_pw


# ═══════════════════════════════════════════════════════════════
# Pool access (shared with pg_state_repo)
# ═══════════════════════════════════════════════════════════════

# Reference to the shared pool — set by init_pg_pool() or imported from pg_state_repo
_pool_ref: Optional[asyncpg.Pool] = None


def _set_pool(pool: asyncpg.Pool) -> None:
    """Set the shared connection pool (called by server startup)."""
    global _pool_ref
    _pool_ref = pool


def _get_pool() -> asyncpg.Pool:
    """Get the shared pool, raising if not initialized."""
    if _pool_ref is None:
        # Fallback: try importing from pg_state_repo
        try:
            from raganything.services.pg_state_repo import get_pg_pool
            _set_pool(get_pg_pool())
        except (ImportError, RuntimeError):
            raise RuntimeError(
                "PG pool not initialized. Set DATABASE_URL and call init_pg_pool() at startup."
            )
    if _pool_ref is None:
        raise RuntimeError("PG pool not initialized.")
    return _pool_ref


# ═══════════════════════════════════════════════════════════════
# Database initialization
# ═══════════════════════════════════════════════════════════════

async def init_db() -> None:
    """Initialize PostgreSQL: idempotent schema + default admin + key persistence.

    Schema DDL is handled by migrations/001_pg_schema.sql. This function
    handles runtime initialization: default roles, admin user, and key persistence.
    """
    pool = _get_pool()
    async with pool.acquire() as conn:
        # Default roles (ON CONFLICT DO NOTHING ensures idempotence)
        default_roles = {
            "super_admin": {
                "desc": "超级管理员，拥有全部权限（信息中心/IT运维）",
                "perms": [
                    "users:read", "users:write", "users:delete",
                    "kb:read", "kb:write", "kb:delete",
                    "agent:read", "agent:write", "agent:delete",
                    "settings:read", "settings:write",
                    "audit:read", "monitor:read",
                    "analytics:read",
                    "workflow:read", "workflow:write",
                    "manufacturing:read", "manufacturing:write",
                ],
            },
            "dept_admin": {
                "desc": "系部管理员，管理系统内知识库、智能体和用户（系主任/实训中心主任）",
                "perms": [
                    "users:read", "users:write",
                    "kb:read", "kb:write", "kb:delete",
                    "agent:read", "agent:write", "agent:delete",
                    "settings:read", "audit:read", "monitor:read",
                    "analytics:read",
                    "workflow:read", "workflow:write",
                    "manufacturing:read", "manufacturing:write",
                ],
            },
            "teacher": {
                "desc": "主讲教师，可创建管理自有知识库和智能体（任课教师）",
                "perms": [
                    "kb:read", "kb:write",
                    "agent:read", "agent:write",
                    "monitor:read", "analytics:read",
                    "workflow:read",
                    "manufacturing:read", "manufacturing:write",
                ],
            },
            "assistant": {
                "desc": "助理教师，可编辑知识库内容、使用智能体（实训指导教师/助教）",
                "perms": [
                    "kb:read", "kb:write",
                    "agent:read",
                    "monitor:read",
                    "manufacturing:read",
                ],
            },
            "student": {
                "desc": "学生，可查看知识库并使用智能体问答（各年级学生）",
                "perms": ["kb:read", "agent:read", "manufacturing:read"],
            },
        }
        for role_name, role_cfg in default_roles.items():
            await conn.execute(
                """
                INSERT INTO roles (name, description, permissions)
                VALUES ($1, $2, $3::jsonb)
                ON CONFLICT (name) DO NOTHING
                """,
                role_name, role_cfg["desc"], json.dumps(role_cfg["perms"]),
            )

        # Persist/load JWT keys
        global SECRET_KEY, REFRESH_SECRET_KEY
        if not os.getenv("JWT_SECRET"):
            row = await conn.fetchrow(
                "SELECT value FROM settings WHERE key = 'jwt_secret'"
            )
            if row:
                SECRET_KEY = row["value"]
            else:
                await conn.execute(
                    "INSERT INTO settings (key, value) VALUES ('jwt_secret', $1)"
                    " ON CONFLICT (key) DO NOTHING",
                    SECRET_KEY,
                )
                # Re-read for multi-worker consistency
                row = await conn.fetchrow(
                    "SELECT value FROM settings WHERE key = 'jwt_secret'"
                )
                if row:
                    SECRET_KEY = row["value"]

        if not os.getenv("JWT_REFRESH_SECRET"):
            row = await conn.fetchrow(
                "SELECT value FROM settings WHERE key = 'jwt_refresh_secret'"
            )
            if row:
                REFRESH_SECRET_KEY = row["value"]
            else:
                await conn.execute(
                    "INSERT INTO settings (key, value) VALUES ('jwt_refresh_secret', $1)"
                    " ON CONFLICT (key) DO NOTHING",
                    REFRESH_SECRET_KEY,
                )
                # Re-read for multi-worker consistency
                row = await conn.fetchrow(
                    "SELECT value FROM settings WHERE key = 'jwt_refresh_secret'"
                )
                if row:
                    REFRESH_SECRET_KEY = row["value"]

        # Persist/load SERVER_START_ID
        global SERVER_START_ID
        row = await conn.fetchrow(
            "SELECT value FROM settings WHERE key = 'server_start_id'"
        )
        if row:
            SERVER_START_ID = row["value"]
        else:
            await conn.execute(
                "INSERT INTO settings (key, value) VALUES ('server_start_id', $1)"
                " ON CONFLICT (key) DO NOTHING",
                SERVER_START_ID,
            )
            # Re-read to handle multi-worker race: another worker may have
            # inserted first; we must use the winning value so all workers
            # share the same sid for JWT validation.
            row = await conn.fetchrow(
                "SELECT value FROM settings WHERE key = 'server_start_id'"
            )
            if row:
                SERVER_START_ID = row["value"]

    # Ensure default admin exists
    admin = await get_user_by_username(DEFAULT_ADMIN_USERNAME)
    if not admin:
        await create_user(DEFAULT_ADMIN_USERNAME, DEFAULT_ADMIN_EMAIL, DEFAULT_ADMIN_PASSWORD, is_admin=True)
        async with pool.acquire() as conn:
            await conn.execute(
                "UPDATE users SET must_change_password = 1 WHERE username = $1",
                DEFAULT_ADMIN_USERNAME,
            )
        print(f"[PG-AUTH] 默认管理员已创建: {DEFAULT_ADMIN_USERNAME} (首次登录需修改密码)")
    else:
        print(f"[PG-AUTH] 管理员账号已存在: {DEFAULT_ADMIN_USERNAME}")

    logger.info("PostgreSQL auth initialized")


# ═══════════════════════════════════════════════════════════════
# User CRUD
# ═══════════════════════════════════════════════════════════════

async def get_user_by_username(username: str) -> dict | None:
    pool = _get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT * FROM users WHERE username = $1", username
        )
        return dict(row) if row else None


async def get_user_by_id(user_id: int) -> dict | None:
    pool = _get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT * FROM users WHERE id = $1", user_id
        )
        return dict(row) if row else None


async def create_user(username: str, email: str, password: str, is_admin: bool = False) -> dict:
    import re as _re_pw

    if len(password) < 8:
        raise ValueError("密码至少需要 8 位")
    if len(password) > 128:
        raise ValueError("密码不能超过 128 位")
    if len(username) < 2:
        raise ValueError("用户名至少需要 2 个字符")
    complexity = 0
    if _re_pw.search(r'[A-Z]', password):
        complexity += 1
    if _re_pw.search(r'[a-z]', password):
        complexity += 1
    if _re_pw.search(r'[0-9]', password):
        complexity += 1
    if _re_pw.search(r'[^A-Za-z0-9]', password):
        complexity += 1
    if complexity < 3:
        raise ValueError("密码需包含大写字母、小写字母、数字、特殊字符中的至少三类")

    password_hash = pwd_context.hash(password)
    role_name = "super_admin" if is_admin else "student"

    pool = _get_pool()
    async with pool.acquire() as conn:
        role_row = await conn.fetchrow(
            "SELECT id FROM roles WHERE name = $1", role_name
        )
        if not role_row:
            raise ValueError(f"角色 '{role_name}' 不存在，请先初始化默认角色")
        role_id = role_row["id"]

        try:
            row = await conn.fetchrow(
                """
                INSERT INTO users (username, email, password_hash, role_id)
                VALUES ($1, $2, $3, $4)
                RETURNING *
                """,
                username.strip(), email.strip(), password_hash, role_id,
            )
        except asyncpg.UniqueViolationError:
            # Check which field caused the conflict
            existing = await conn.fetchrow(
                "SELECT username, email FROM users WHERE username = $1 OR email = $2",
                username.strip(), email.strip(),
            )
            if existing and existing["username"] == username.strip():
                raise ValueError("用户名已被占用")
            elif existing and existing["email"] == email.strip():
                raise ValueError("邮箱已被占用")
            raise ValueError("注册失败，请重试")

    return _sanitize_user(dict(row))


async def update_user(user_id: int, data: dict) -> dict | None:
    allowed_fields = {"username", "email", "role_id", "is_active"}
    security_sensitive_fields = {"is_admin", "password_hash", "failed_login_attempts",
                                  "locked_until", "created_at", "updated_at"}

    rejected = {k for k in data if k in security_sensitive_fields}
    if rejected:
        logger.warning(
            "[SECURITY] update_user(id=%d) received rejected fields: %s",
            user_id, rejected,
        )
        raise ValueError(f"不允许直接修改以下字段: {', '.join(sorted(rejected))}")

    unrecognized = {k for k in data if k not in allowed_fields
                    and k not in security_sensitive_fields
                    and k != "password"}
    if unrecognized:
        logger.warning(
            "[SECURITY] update_user(id=%d) ignoring unrecognized fields: %s",
            user_id, unrecognized,
        )

    updates = {k: v for k, v in data.items() if k in allowed_fields}

    if "password" in data and data["password"]:
        updates["password_hash"] = pwd_context.hash(data["password"])

    if not updates:
        return await get_user_by_id(user_id)

    updates["updated_at"] = datetime.utcnow()

    set_clause = ", ".join(f"{k} = ${i+1}" for i, k in enumerate(updates))
    values = list(updates.values()) + [user_id]

    pool = _get_pool()
    async with pool.acquire() as conn:
        try:
            await conn.execute(
                f"UPDATE users SET {set_clause} WHERE id = ${len(values)}",
                *values,
            )
        except asyncpg.UniqueViolationError as e:
            raise ValueError(f"更新失败: {e}")

    return await get_user_by_id(user_id)


async def delete_user(user_id: int) -> bool:
    pool = _get_pool()
    async with pool.acquire() as conn:
        result = await conn.execute(
            "DELETE FROM users WHERE id = $1", user_id
        )
    deleted = result != "DELETE 0"
    return deleted


async def list_users() -> list[dict]:
    pool = _get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch("SELECT * FROM users ORDER BY id")
    return [_sanitize_user(dict(r)) for r in rows]


# ═══════════════════════════════════════════════════════════════
# Role & Permission Helpers
# ═══════════════════════════════════════════════════════════════

async def get_user_role(user_id: int) -> dict | None:
    pool = _get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT r.* FROM roles r
            JOIN users u ON u.role_id = r.id
            WHERE u.id = $1
            """, user_id,
        )
        return dict(row) if row else None


async def has_permission(user_id: int, permission: str) -> bool:
    role = await get_user_role(user_id)
    if not role:
        return False
    try:
        perms = json.loads(role.get("permissions", "[]"))
        return permission in perms
    except (json.JSONDecodeError, TypeError):
        return False


async def user_is_admin(user_id: int) -> bool:
    role = await get_user_role(user_id)
    return role is not None and role.get("name") in ("super_admin", "admin")


# ═══════════════════════════════════════════════════════════════
# Brute-Force Protection
# ═══════════════════════════════════════════════════════════════

async def check_account_locked(user_id: int) -> str | None:
    pool = _get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT locked_until, failed_login_attempts FROM users WHERE id = $1",
            user_id,
        )
        if not row:
            return None
        locked_until = row["locked_until"]
        if locked_until:
            if locked_until > datetime.utcnow():
                remaining = int((locked_until - datetime.utcnow()).total_seconds() / 60) + 1
                return f"账号已被锁定，请 {remaining} 分钟后重试"
            else:
                await conn.execute(
                    "UPDATE users SET locked_until = NULL, failed_login_attempts = 0 WHERE id = $1",
                    user_id,
                )
    return None


async def record_failed_login(user_id: int):
    pool = _get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE users SET failed_login_attempts = failed_login_attempts + 1 WHERE id = $1",
            user_id,
        )
        row = await conn.fetchrow(
            "SELECT failed_login_attempts FROM users WHERE id = $1", user_id,
        )
        if row and row["failed_login_attempts"] >= MAX_FAILED_ATTEMPTS:
            lock_time = datetime.utcnow() + timedelta(minutes=LOCKOUT_DURATION_MINUTES)
            await conn.execute(
                "UPDATE users SET locked_until = $1 WHERE id = $2",
                lock_time, user_id,
            )


async def reset_failed_logins(user_id: int):
    pool = _get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE users SET failed_login_attempts = 0, locked_until = NULL WHERE id = $1",
            user_id,
        )


# ═══════════════════════════════════════════════════════════════
# JWT Utilities (module-level, no DB access needed)
# ═══════════════════════════════════════════════════════════════

def verify_password(plain_password: str, hashed_password: str) -> bool:
    return pwd_context.verify(plain_password, hashed_password)


def create_token(user_id: int, username: str, is_admin: bool, role: dict | None = None) -> str:
    payload = {
        "user_id": user_id,
        "username": username,
        "role": role.get("name") if role else ("super_admin" if is_admin else "student"),
        "permissions": role.get("permissions") if role else [],
        "sid": SERVER_START_ID,
        "jti": uuid.uuid4().hex,
        "type": "access",
        "exp": datetime.utcnow() + timedelta(hours=JWT_EXPIRY_HOURS),
        "iat": datetime.utcnow(),
    }
    return pyjwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)


def decode_token(token: str) -> dict | None:
    try:
        payload = pyjwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        if payload.get("sid") != SERVER_START_ID:
            return None
        return payload
    except pyjwt.ExpiredSignatureError:
        return None
    except pyjwt.InvalidTokenError:
        return None


def create_refresh_token(user_id: int, username: str, is_admin: bool, role: dict | None = None) -> str:
    payload = {
        "user_id": user_id,
        "username": username,
        "role": role.get("name") if role else ("super_admin" if is_admin else "student"),
        "permissions": role.get("permissions") if role else [],
        "type": "refresh",
        "sid": SERVER_START_ID,
        "jti": uuid.uuid4().hex,
        "rfam": uuid.uuid4().hex,
        "exp": datetime.utcnow() + timedelta(days=REFRESH_EXPIRY_DAYS),
        "iat": datetime.utcnow(),
    }
    return pyjwt.encode(payload, REFRESH_SECRET_KEY, algorithm=ALGORITHM)


def decode_refresh_token(token: str) -> dict | None:
    try:
        payload = pyjwt.decode(token, REFRESH_SECRET_KEY, algorithms=[ALGORITHM])
        if payload.get("type") != "refresh":
            return None
        if payload.get("sid") != SERVER_START_ID:
            return None
        return payload
    except (pyjwt.ExpiredSignatureError, pyjwt.InvalidTokenError):
        return None


# ═══════════════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════════════

def _sanitize_user(user: dict | None) -> dict | None:
    if user is None:
        return None
    return {k: v for k, v in user.items() if k != "password_hash"}
