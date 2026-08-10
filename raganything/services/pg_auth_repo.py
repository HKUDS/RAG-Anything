# -*- coding: utf-8 -*-
"""
═══════════════════════════════════════════════════════════════════════════════
PostgreSQL 用户认证仓库
═══════════════════════════════════════════════════════════════════════════════

【文件作用】
  系统的用户注册、登录、Token 管理、角色权限查询。
  通过 pg_state_repo.get_pg_pool() 复用全局连接池。

【管理的数据库表】
  ┌──────────────────┬──────────────────────────────────────┐
  │ users            │ 用户表                                │
  │                  │ id, username, password_hash            │
  │                  │ role（admin/editor/viewer/student/    │
  │                  │ guest）, is_active, created_at        │
  ├──────────────────┼──────────────────────────────────────┤
  │ roles            │ 5 级角色定义表                        │
  │                  │ 1=admin(管理员), 2=editor(编辑),      │
  │                  │ 3=viewer(只读), 4=student(学生),      │
  │                  │ 5=guest(访客)                         │
  │                  │ 每个角色关联一组权限(permissions JSON) │
  ├──────────────────┼──────────────────────────────────────┤
  │ token_revocations│ JWT Token 撤销记录                    │
  │                  │ 用于登出/密码修改后使 Token 失效       │
  │                  │ family_id 支持 Refresh Token 链撤销   │
  └──────────────────┴──────────────────────────────────────┘

【核心函数】
  ── 用户管理 ──
  pg_create_user(username, password, role) → 创建用户
  pg_authenticate(username, password)              → 验证用户名密码
  pg_get_user_by_id(user_id)                       → 按 ID 查用户
  pg_get_user_by_username(username)                → 按用户名查用户
  pg_list_users(is_active_only)                    → 列出所有用户
  pg_update_user_role(user_id, new_role)           → 修改用户角色
  pg_delete_user(user_id)                          → 软删除用户（设 is_active=false）

  ── JWT Token ──
  create_token(user_id, username, role)            → 签发 Access Token
  create_refresh_token(user_id, username, role)    → 签发 Refresh Token
  decode_token(token)                              → 验证并解码 Token
  revoke_token(jti, family_id, user_id)            → 撤销 Token

  ── 权限查询 ──
  pg_get_user_roles(user_id)                       → 获取用户角色列表
  pg_get_user_permissions(user_id)                 → 获取用户所有权限（展开角色）
  pg_get_all_roles()                               → 列出所有角色定义

【替换了什么】
  - raganything/services/auth.py（SQLite / aiosqlite 后端）
  - 旧 auth.db 中的 users 表

【与其他文件的关系】
  使用 pg_state_repo.get_pg_pool() 获取连接
  被 raganything/services/auth.py 的 dispatch 层调用（PG优先→SQLite回退）
  被 raganything/dependencies.py 的 get_current_user / require_permission 调用
  对应迁移：migrations/002_pg_3to5_roles.sql, migrations/004_token_blacklist_pg.sql

【角色权限模型（RBAC v2）】
  5 级角色，权限格式 resource:action（如 kb:write, users:read）
  详见 raganything/permissions.py 中的 Permission 类

English:
  PostgreSQL-backed auth repository for RAG-Anything.

  Replaces: raganything/services/auth.py (SQLite/aiosqlite backend)
  Activated: When DATABASE_URL or POSTGRES_HOST env var is set.

  Uses the same connection pool as pg_state_repo.py via get_pg_pool().
"""

from __future__ import annotations

import json
import logging
import os
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

import asyncpg
import jwt as pyjwt
from passlib.context import CryptContext

from raganything.permissions import (
    DEFAULT_ROLE_NAME,
    DEFAULT_ROLES,
    can_assign_role,
)

logger = logging.getLogger("rag_server.pg_auth")


class AccountLifecycleConflict(ValueError):
    """A lifecycle mutation would violate an account safety invariant."""

# ── Password Hashing ───────────────────────────────────────
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# ── JWT Configuration ──────────────────────────────────────
SECRET_KEY = os.getenv("JWT_SECRET", "development-jwt-secret-not-for-production").strip()
REFRESH_SECRET_KEY = os.getenv(
    "JWT_REFRESH_SECRET", "development-refresh-secret-not-for-production"
).strip()
JWT_EXPIRY_HOURS = int(os.getenv("JWT_EXPIRY_HOURS", "1"))
REFRESH_EXPIRY_DAYS = int(os.getenv("REFRESH_EXPIRY_DAYS", "7"))
ALGORITHM = "HS256"
SERVER_START_ID = uuid.uuid4().hex

# ── Brute-Force Protection ─────────────────────────────────
MAX_FAILED_ATTEMPTS = int(os.getenv("MAX_FAILED_LOGIN_ATTEMPTS", "5"))
LOCKOUT_DURATION_MINUTES = int(os.getenv("LOGIN_LOCKOUT_MINUTES", "15"))

# ── Default Admin ──────────────────────────────────────────
DEFAULT_ADMIN_USERNAME = os.getenv("DEFAULT_ADMIN_USERNAME", "admin").strip() or "admin"
DEFAULT_ADMIN_PASSWORD = os.getenv("DEFAULT_ADMIN_PASSWORD", "").strip()


def _is_production(environment: dict[str, str] | None = None) -> bool:
    values = environment if environment is not None else os.environ
    return values.get("RAGANYTHING_ENV", "development").strip().lower() == "production"


def production_configuration_errors(
    environment: dict[str, str] | None = None,
) -> tuple[str, ...]:
    """Return missing production configuration names without revealing values."""
    values = environment if environment is not None else os.environ
    missing = [
        name for name in ("JWT_SECRET", "JWT_REFRESH_SECRET", "DEFAULT_ADMIN_PASSWORD")
        if not values.get(name, "").strip()
    ]
    if not values.get("DATABASE_URL", "").strip():
        structured = ("POSTGRES_USER", "POSTGRES_PASSWORD", "POSTGRES_HOST", "POSTGRES_PORT")
        missing.extend(name for name in structured if not values.get(name, "").strip())
        if not (values.get("POSTGRES_DATABASE", "").strip() or values.get("POSTGRES_DB", "").strip()):
            missing.append("POSTGRES_DATABASE")
    if values.get("ALLOW_PUBLIC_REGISTRATION", "false").strip().lower() in {"1", "true", "yes", "on"}:
        missing.append("ALLOW_PUBLIC_REGISTRATION")
    try:
        from raganything.services.vision_models import load_catalog
        for entry in load_catalog().values():
            if entry.api_key_env and not values.get(entry.api_key_env, "").strip():
                missing.append(entry.api_key_env)
    except Exception:
        pass
    return tuple(dict.fromkeys(missing))


def validate_production_configuration() -> None:
    if _is_production():
        missing = production_configuration_errors()
        if missing:
            raise RuntimeError("missing required production configuration: " + ", ".join(missing))


def public_registration_enabled() -> bool:
    return not _is_production() and os.getenv("ALLOW_PUBLIC_REGISTRATION", "false").strip().lower() in {"1", "true", "yes", "on"}


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
    if _pool_ref is None or _pool_ref.is_closing():
        # A closed pool is stale (e.g. an integration suite re-created the
        # state-repo pool after a teardown).  Re-sync from pg_state_repo so
        # callers never acquire from a dead pool.
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

def build_default_role_rows() -> dict[str, dict[str, object]]:
    """Build the runtime role seed from permissions.py DEFAULT_ROLES.

    Single source of truth: init_db writes exactly these rows and tests
    assert the result stays equal to DEFAULT_ROLES, preventing drift
    between the runtime seed and the permission constants.
    """
    return {
        role_name: {
            "description": role_cfg["description"],
            "permissions": list(role_cfg["permissions"]),
        }
        for role_name, role_cfg in DEFAULT_ROLES.items()
    }


async def init_db() -> None:
    """Initialize PostgreSQL: idempotent schema + default admin + key persistence.

    Schema DDL is handled by migrations/001_pg_schema.sql. This function
    handles runtime initialization: default 5-level RBAC v2 roles,
    admin user, and key persistence.

    Uses ON CONFLICT DO UPDATE to refresh permissions on every startup,
    preventing stale permissions when new resources (e.g. autorepair)
    are added to role definitions after initial role creation.
    """
    validate_production_configuration()
    pool = _get_pool()
    async with pool.acquire() as conn:
        # Default roles (ON CONFLICT DO UPDATE ensures idempotence + permission refresh)
        # The runtime seed is built from permissions.py's DEFAULT_ROLES so there
        # is exactly one source of truth (see build_default_role_rows()).
        default_roles = {
            role_name: {
                "desc": role_cfg["description"],
                "perms": role_cfg["permissions"],
            }
            for role_name, role_cfg in build_default_role_rows().items()
        }
        for role_name, role_cfg in default_roles.items():
            await conn.execute(
                """
                INSERT INTO roles (name, description, permissions)
                VALUES ($1, $2, $3::jsonb)
                ON CONFLICT (name) DO UPDATE SET
                    description = EXCLUDED.description,
                    permissions = EXCLUDED.permissions
                """,
                role_name, role_cfg["desc"], json.dumps(role_cfg["perms"]),
            )

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

        # Changes only when all application data is intentionally reset.
        # Frontends use this epoch to discard stale browser-owned state.
        await conn.execute(
            "INSERT INTO settings (key, value) VALUES ('system_data_epoch', $1)"
            " ON CONFLICT (key) DO NOTHING",
            uuid.uuid4().hex,
        )

    # Ensure default admin exists
    admin = await get_user_by_username(DEFAULT_ADMIN_USERNAME)
    if not admin:
        if not DEFAULT_ADMIN_PASSWORD:
            raise RuntimeError("DEFAULT_ADMIN_PASSWORD is required to bootstrap an administrator")
        super_admin_role = await get_role_by_name("super_admin")
        await create_user(DEFAULT_ADMIN_USERNAME, DEFAULT_ADMIN_PASSWORD,
                          role_id=super_admin_role["id"] if super_admin_role else None,
                          must_change_password=True,
                          actor_role_name="super_admin")
    logger.info("PostgreSQL authentication initialized")


# ═══════════════════════════════════════════════════════════════
# User CRUD
# ═══════════════════════════════════════════════════════════════

async def get_user_by_username(username: str) -> dict | None:
    pool = _get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT * FROM users WHERE username = $1", username
        )
        return await _attach_allowed_kbs(conn, dict(row)) if row else None


async def get_user_by_id(user_id: int) -> dict | None:
    pool = _get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT * FROM users WHERE id = $1", user_id
        )
        return await _attach_allowed_kbs(conn, dict(row)) if row else None


async def _attach_allowed_kbs(conn: asyncpg.Connection, user: dict) -> dict:
    """Project durable KB scope into the sanitized user representation."""
    rows = await conn.fetch(
        "SELECT kb_name, access_level FROM kb_access_grants WHERE user_id = $1 ORDER BY kb_name",
        user["id"],
    )
    user["allowed_kbs"] = [row["kb_name"] for row in rows]
    user["kb_access_levels"] = {
        row["kb_name"]: row.get("access_level") or "read" for row in rows
    }
    return user


_KB_MEMBER_ACCESS_LEVELS = {"read", "operate"}


def _role_has_permission(role: dict, permission: str) -> bool:
    """Check a locked role record without opening another connection."""
    if role.get("role_name") == "super_admin" or role.get("name") == "super_admin":
        return True
    permissions = role.get("permissions") or []
    if isinstance(permissions, str):
        try:
            permissions = json.loads(permissions)
        except (json.JSONDecodeError, TypeError):
            permissions = []
    return permission in permissions if isinstance(permissions, list) else False


def _normalize_member_access_level(access_level: str) -> str:
    if not isinstance(access_level, str):
        raise ValueError("knowledge-base member access level must be read or operate")
    normalized = access_level.strip().lower()
    if normalized not in _KB_MEMBER_ACCESS_LEVELS:
        raise ValueError("knowledge-base member access level must be read or operate")
    return normalized


async def pg_list_kb_members(kb_name: str) -> list[dict[str, Any]]:
    """Return KB member grants with their current account state."""
    pool = _get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT g.user_id AS id, u.username, r.name AS role_name,
                   u.is_active, u.archived_at, u.session_generation,
                   g.access_level, g.granted_by, g.granted_at,
                   grantor.username AS granted_by_username
            FROM kb_access_grants g
            JOIN users u ON u.id = g.user_id
            JOIN roles r ON r.id = u.role_id
            LEFT JOIN users grantor ON grantor.id = g.granted_by
            WHERE g.kb_name = $1
            ORDER BY g.granted_at ASC, u.id ASC
            """,
            kb_name,
        )
    members: list[dict[str, Any]] = []
    for row in rows:
        member = dict(row)
        if isinstance(member.get("granted_at"), datetime):
            member["granted_at"] = member["granted_at"].isoformat()
        member["effective_access"] = member.get("access_level", "read")
        member["is_owner"] = False
        member["removable"] = True
        member["revision"] = int(member.get("session_generation", 0) or 0)
        members.append(member)
    return members


async def _member_actor_role(conn: asyncpg.Connection, actor_id: int) -> dict:
    actor = await conn.fetchrow(
        """
        SELECT u.id, u.is_active, u.archived_at, r.name AS role_name, r.permissions
        FROM users u
        JOIN roles r ON r.id = u.role_id
        WHERE u.id = $1
        FOR UPDATE
        """,
        actor_id,
    )
    if actor is None or not actor["is_active"] or actor["archived_at"] is not None:
        raise ValueError("member manager account is unavailable")
    return dict(actor)


async def _lock_member_mutation_context(
    conn: asyncpg.Connection,
    *,
    kb_name: str,
    actor_id: int,
    target_user_id: int,
) -> tuple[dict, dict, dict]:
    """Serialize same-KB mutations before locking the actor and target."""
    kb = await conn.fetchrow(
        "SELECT name, owner_id FROM kb_metadata WHERE name = $1 FOR UPDATE",
        kb_name,
    )
    if kb is None:
        raise KeyError(kb_name)
    actor = await _member_actor_role(conn, actor_id)
    target = await conn.fetchrow(
        """
        SELECT u.id, u.username, u.is_active, u.archived_at, u.session_generation,
               r.name AS role_name, r.permissions
        FROM users u
        JOIN roles r ON r.id = u.role_id
        WHERE u.id = $1
        FOR UPDATE
        """,
        target_user_id,
    )
    if target is None:
        raise ValueError("knowledge-base member target does not exist")
    target_data = dict(target)
    if not target_data["is_active"] or target_data["archived_at"] is not None:
        raise ValueError("knowledge-base member target is unavailable")
    if target_data["id"] == kb["owner_id"]:
        raise ValueError("knowledge-base owner cannot receive a member grant")
    if target_data["role_name"] == "super_admin":
        raise ValueError("super_admin cannot receive a redundant member grant")
    if not can_assign_role(actor["role_name"], target_data["role_name"]):
        raise PermissionError("cannot grant knowledge-base access to a more privileged user")
    return dict(kb), actor, target_data


async def pg_search_kb_member_candidates(
    kb_name: str,
    query: str,
    *,
    actor_id: int,
    page: int = 1,
    page_size: int = 20,
) -> dict[str, Any]:
    """Search eligible users without exposing an unbounded user directory."""
    normalized_query = query.strip() if isinstance(query, str) else ""
    if len(normalized_query) < 2:
        raise ValueError("member search query must contain at least two characters")
    if page < 1 or page_size < 1 or page_size > 50:
        raise ValueError("invalid member search pagination")

    pool = _get_pool()
    async with pool.acquire() as conn:
        actor = await _member_actor_role(conn, actor_id)
        eligible_roles = [
            role_name for role_name in DEFAULT_ROLES
            if role_name != "super_admin" and can_assign_role(actor["role_name"], role_name)
        ]
        if not eligible_roles:
            return {"items": [], "total": 0, "page": page, "page_size": page_size, "total_pages": 1}
        base_query = """
            FROM users u
            JOIN roles r ON r.id = u.role_id
            WHERE u.is_active = 1
              AND u.archived_at IS NULL
              AND r.name = ANY($1::text[])
              AND u.username ILIKE '%' || $2 || '%'
              AND u.id <> (SELECT owner_id FROM kb_metadata WHERE name = $3)
              AND NOT EXISTS (
                  SELECT 1 FROM kb_access_grants g
                  WHERE g.kb_name = $3 AND g.user_id = u.id
              )
        """
        total = await conn.fetchval("SELECT COUNT(*) " + base_query, eligible_roles, normalized_query, kb_name)
        offset = (page - 1) * page_size
        rows = await conn.fetch(
            "SELECT u.id, u.username, r.name AS role_name " + base_query
            + " ORDER BY u.username ASC, u.id ASC LIMIT $4 OFFSET $5",
            eligible_roles,
            normalized_query,
            kb_name,
            page_size,
            offset,
        )
    total = int(total or 0)
    return {
        "items": [dict(row) for row in rows],
        "total": total,
        "page": page,
        "page_size": page_size,
        "total_pages": max(1, (total + page_size - 1) // page_size),
    }


async def pg_upsert_kb_member_grant(
    kb_name: str,
    target_user_id: int,
    access_level: str,
    *,
    actor_id: int,
) -> dict[str, Any]:
    """Create or change one grant, audit it, and invalidate the target session."""
    normalized_level = _normalize_member_access_level(access_level)
    pool = _get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            _kb, actor, target = await _lock_member_mutation_context(
                conn, kb_name=kb_name, actor_id=actor_id, target_user_id=target_user_id,
            )
            if normalized_level == "operate" and not _role_has_permission(target, "kb:write"):
                raise ValueError("operate access requires the target role to have kb:write")
            existing = await conn.fetchrow(
                """SELECT access_level FROM kb_access_grants
                   WHERE kb_name = $1 AND user_id = $2 FOR UPDATE""",
                kb_name,
                target_user_id,
            )
            if existing is not None and existing["access_level"] == normalized_level:
                raise ValueError("knowledge-base member already has this access level")
            result = await conn.fetchrow(
                """
                INSERT INTO kb_access_grants (kb_name, user_id, access_level, granted_by)
                VALUES ($1, $2, $3, $4)
                ON CONFLICT (kb_name, user_id) DO UPDATE SET
                    access_level = EXCLUDED.access_level,
                    granted_by = EXCLUDED.granted_by,
                    granted_at = NOW()
                RETURNING access_level, granted_by, granted_at
                """,
                kb_name,
                target_user_id,
                normalized_level,
                actor_id,
            )
            await conn.execute(
                """UPDATE users SET session_generation = session_generation + 1,
                   updated_at = NOW() WHERE id = $1""",
                target_user_id,
            )
            await conn.execute(
                """INSERT INTO audit_logs (actor_id, action, target_user_id, details)
                   VALUES ($1, $2, $3, $4::jsonb)""",
                actor_id,
                "kb.member_grant.upserted",
                target_user_id,
                json.dumps({
                    "kb": kb_name,
                    "access_level": normalized_level,
                    "previous_access_level": existing["access_level"] if existing else None,
                    "actor_role": actor["role_name"],
                }, ensure_ascii=False),
            )
    grant = dict(result)
    if isinstance(grant.get("granted_at"), datetime):
        grant["granted_at"] = grant["granted_at"].isoformat()
    return {
        "id": target["id"],
        "username": target["username"],
        "role_name": target["role_name"],
        "is_active": bool(target["is_active"]),
        "archived_at": target["archived_at"],
        "session_generation": int(target["session_generation"]) + 1,
        "revision": int(target["session_generation"]) + 1,
        "access_level": grant["access_level"],
        "effective_access": grant["access_level"],
        "granted_by": grant["granted_by"],
        "granted_at": grant["granted_at"],
        "is_owner": False,
        "removable": True,
    }


async def pg_revoke_kb_member_grant(
    kb_name: str,
    target_user_id: int,
    *,
    actor_id: int,
) -> None:
    """Revoke one grant, audit it, and invalidate the target session."""
    pool = _get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            _kb, actor, _target = await _lock_member_mutation_context(
                conn, kb_name=kb_name, actor_id=actor_id, target_user_id=target_user_id,
            )
            existing = await conn.fetchrow(
                """SELECT access_level FROM kb_access_grants
                   WHERE kb_name = $1 AND user_id = $2 FOR UPDATE""",
                kb_name,
                target_user_id,
            )
            if existing is None:
                raise ValueError("knowledge-base member grant does not exist")
            removed = await conn.fetchrow(
                """DELETE FROM kb_access_grants
                   WHERE kb_name = $1 AND user_id = $2
                   RETURNING access_level""",
                kb_name,
                target_user_id,
            )
            await conn.execute(
                """UPDATE users SET session_generation = session_generation + 1,
                   updated_at = NOW() WHERE id = $1""",
                target_user_id,
            )
            await conn.execute(
                """INSERT INTO audit_logs (actor_id, action, target_user_id, details)
                   VALUES ($1, $2, $3, $4::jsonb)""",
                actor_id,
                "kb.member_grant.revoked",
                target_user_id,
                json.dumps({
                    "kb": kb_name,
                    "access_level": removed["access_level"],
                    "actor_role": actor["role_name"],
                }, ensure_ascii=False),
            )


async def create_user(username: str, password: str, role_id: int | None = None,
                      must_change_password: bool = False,
                      actor_role_name: str | None = None) -> dict:
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

    # Default role: student; an explicit role assignment must be authorized
    # by the acting role.  Internal flows that only create default students
    # pass no role_id and are unaffected (actor_role_name may stay None).
    if role_id is not None and actor_role_name is None:
        raise ValueError("显式指定 role_id 时必须提供 actor_role_name")

    pool = _get_pool()
    async with pool.acquire() as conn:
        if role_id is None:
            role_name = DEFAULT_ROLE_NAME
            role_row = await conn.fetchrow(
                "SELECT id, name FROM roles WHERE name = $1", role_name
            )
            if not role_row:
                raise ValueError(f"角色 '{role_name}' 不存在，请先初始化默认角色")
            role_id = role_row["id"]
        else:
            # Legacy admin/editor/viewer rows remain for historical data only.
            # They must not be assigned through current user-management APIs.
            role_row = await conn.fetchrow(
                "SELECT id, name FROM roles WHERE id = $1 AND name = ANY($2::text[])",
                role_id,
                list(DEFAULT_ROLES),
            )
            if not role_row:
                raise ValueError(f"角色 ID {role_id} 不存在或不可分配")
            if not can_assign_role(actor_role_name, role_row["name"]):
                raise PermissionError(
                    f"无权分配角色 '{role_row['name']}': 目标角色等级高于操作者"
                )

        try:
            row = await conn.fetchrow(
                """
                INSERT INTO users (username, password_hash, role_id, must_change_password)
                VALUES ($1, $2, $3, $4)
                RETURNING *
                """,
                username.strip(), password_hash, role_id,
                1 if must_change_password else 0,
            )
        except asyncpg.UniqueViolationError:
            raise ValueError("用户名已被占用")

    return _sanitize_user(dict(row))


async def update_user(
    user_id: int,
    data: dict,
    actor_role_name: str | None = None,
    actor_id: int | None = None,
) -> dict | None:
    allowed_fields = {"username", "role_id", "is_active", "must_change_password"}
    protected_fields = {"password_hash", "failed_login_attempts", "locked_until", "created_at", "updated_at"}
    rejected = {key for key in data if key in protected_fields}
    if rejected:
        raise ValueError("direct mutation of protected account fields is not allowed")
    if "allowed_kbs" in data:
        raise ValueError("knowledge-base grants must be managed through the knowledge-base member APIs")
    updates = {key: value for key, value in data.items() if key in allowed_fields}
    if data.get("password"):
        updates["password_hash"] = pwd_context.hash(data["password"])
    if not updates:
        return await get_user_by_id(user_id)

    pool = _get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            await conn.execute("SELECT pg_advisory_xact_lock(hashtext($1))", "users:super-admin-quorum")
            target = await conn.fetchrow(
                """SELECT u.is_active, u.archived_at, r.name AS role_name
                   FROM users u JOIN roles r ON r.id = u.role_id
                   WHERE u.id = $1 FOR UPDATE""", user_id,
            )
            if not target:
                return None
            requested_role_name = target["role_name"]
            if "role_id" in updates:
                if actor_role_name is None:
                    raise ValueError("actor_role_name is required for role changes")
                role_row = await conn.fetchrow(
                    "SELECT id, name FROM roles WHERE id = $1 AND name = ANY($2::text[])",
                    updates["role_id"], list(DEFAULT_ROLES),
                )
                if not role_row:
                    raise ValueError("requested role is not assignable")
                requested_role_name = role_row["name"]
                if not can_assign_role(actor_role_name, requested_role_name):
                    raise PermissionError("cannot assign a role more privileged than the actor")
            removes_final_admin = (
                target["role_name"] == "super_admin" and target["is_active"]
                and target["archived_at"] is None
                and (updates.get("is_active") in (0, False) or requested_role_name != "super_admin")
            )
            if removes_final_admin:
                active_admins = await conn.fetchval(
                    """SELECT count(*) FROM users u JOIN roles r ON r.id = u.role_id
                       WHERE r.name = 'super_admin' AND u.is_active = 1 AND u.archived_at IS NULL"""
                )
                if int(active_admins or 0) <= 1:
                    raise AccountLifecycleConflict("the final active super_admin cannot be disabled or demoted")

            if {"password_hash", "is_active", "role_id"}.intersection(updates):
                updates["session_generation"] = True
            updates["updated_at"] = datetime.utcnow()
            assignments, values = [], []
            for key, value in updates.items():
                if key == "session_generation":
                    assignments.append("session_generation = session_generation + 1")
                else:
                    values.append(value)
                    assignments.append(f"{key} = ${len(values)}")
            values.append(user_id)
            if assignments:
                try:
                    await conn.execute(
                        f"UPDATE users SET {', '.join(assignments)} WHERE id = ${len(values)}", *values
                    )
                except asyncpg.UniqueViolationError as exc:
                    raise ValueError("username is already in use") from exc
    return await get_user_by_id(user_id)


async def delete_user(
    user_id: int, *, archived_by: int | None = None, archive_reason: str | None = None
) -> bool:
    """Archive an account; this name remains for DELETE-route compatibility."""
    pool = _get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            await conn.execute("SELECT pg_advisory_xact_lock(hashtext($1))", "users:super-admin-quorum")
            target = await conn.fetchrow(
                """SELECT u.is_active, u.archived_at, r.name AS role_name
                   FROM users u JOIN roles r ON r.id = u.role_id
                   WHERE u.id = $1 FOR UPDATE""", user_id,
            )
            if not target:
                return False
            if target["archived_at"] is not None:
                return True
            if target["role_name"] == "super_admin" and target["is_active"]:
                active_admins = await conn.fetchval(
                    """SELECT count(*) FROM users u JOIN roles r ON r.id = u.role_id
                       WHERE r.name = 'super_admin' AND u.is_active = 1 AND u.archived_at IS NULL"""
                )
                if int(active_admins or 0) <= 1:
                    raise AccountLifecycleConflict("the final active super_admin cannot be archived")
            await conn.execute(
                """UPDATE users SET is_active = 0, archived_at = NOW(), archived_by = $1,
                   archive_reason = $2, session_generation = session_generation + 1,
                   updated_at = NOW() WHERE id = $3""", archived_by, archive_reason, user_id,
            )
    return True


async def list_users() -> list[dict]:
    pool = _get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch("SELECT * FROM users ORDER BY id")
        grants = await conn.fetch(
            "SELECT user_id, array_agg(kb_name ORDER BY kb_name) AS kb_names "
            "FROM kb_access_grants GROUP BY user_id"
        )
    grants_by_user = {row["user_id"]: list(row["kb_names"]) for row in grants}
    users = []
    for row in rows:
        user = dict(row)
        user["allowed_kbs"] = grants_by_user.get(user["id"], [])
        users.append(_sanitize_user(user))
    return users


async def update_last_login_at(user_id: int) -> None:
    """Update the last_login_at timestamp for a user."""
    pool = _get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE users SET last_login_at = NOW() WHERE id = $1",
            user_id,
        )


async def get_role_by_name(role_name: str) -> dict | None:
    """Look up a role by its name."""
    pool = _get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT * FROM roles WHERE name = $1", role_name
        )
        return dict(row) if row else None


async def list_roles() -> list[dict]:
    """List all roles."""
    import json as _json
    pool = _get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch("SELECT * FROM roles ORDER BY id")
        roles = []
        for r in rows:
            role = dict(r)
            try:
                if isinstance(role.get("permissions"), str):
                    role["permissions"] = _json.loads(role["permissions"])
            except (_json.JSONDecodeError, TypeError):
                role["permissions"] = []
            if role.get("name") in DEFAULT_ROLES:
                roles.append(role)
        return roles


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
        if not row:
            return None

        role = dict(row)
        try:
            if isinstance(role.get("permissions"), str):
                role["permissions"] = json.loads(role["permissions"])
        except (json.JSONDecodeError, TypeError):
            role["permissions"] = []

        return role


async def has_permission(user_id: int, permission: str) -> bool:
    role = await get_user_role(user_id)
    if not role:
        return False
    # super_admin 动态拥有全部权限 — 即使 roles 表 JSON 是旧版本，
    # 新增权限也自动生效，无需迁移数据库
    if role.get("name") == "super_admin":
        return True
    try:
        perms = role.get("permissions", [])
        if isinstance(perms, str):
            perms = json.loads(perms or "[]")
        return permission in perms
    except (json.JSONDecodeError, TypeError):
        return False


async def user_is_admin(user_id: int) -> bool:
    role = await get_user_role(user_id)
    return role is not None and role.get("name") == "super_admin"


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


def create_token(user_id: int, username: str, is_admin: bool, role: dict | None = None, session_generation: int = 0) -> str:
    payload = {
        "user_id": user_id,
        "username": username,
        "role": role.get("name") if role else ("super_admin" if is_admin else DEFAULT_ROLE_NAME),
        "permissions": role.get("permissions") if role else [],
        "sid": SERVER_START_ID,
        "sg": int(session_generation),
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


def create_refresh_token(
    user_id: int,
    username: str,
    is_admin: bool,
    role: dict | None = None,
    session_generation: int = 0,
    family_id: str | None = None,
) -> str:
    payload = {
        "user_id": user_id,
        "username": username,
        "role": role.get("name") if role else ("super_admin" if is_admin else DEFAULT_ROLE_NAME),
        "permissions": role.get("permissions") if role else [],
        "type": "refresh",
        "sid": SERVER_START_ID,
        "sg": int(session_generation),
        "jti": uuid.uuid4().hex,
        "rfam": family_id or uuid.uuid4().hex,
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
# Token Blacklist (PG-backed — replaces token_blacklist.py SQLite)
# ═══════════════════════════════════════════════════════════════

async def pg_revoke_token(
    jti: str,
    expires_at: datetime,
    family_id: str | None = None,
) -> None:
    """Revoke a token by JTI. Replaces TokenBlacklist.revoke().

    Uses INSERT ... ON CONFLICT DO UPDATE for idempotent upsert.
    Includes optional family_id for refresh token family tracking.
    """
    pool = _get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO token_revocations (jti, expires_at, family_id, revoked_at)
            VALUES ($1, $2, $3, NOW())
            ON CONFLICT (jti) DO UPDATE SET
                expires_at = EXCLUDED.expires_at,
                family_id = COALESCE(EXCLUDED.family_id, token_revocations.family_id),
                revoked_at = NOW()
            """,
            jti, expires_at, family_id,
        )


async def pg_is_token_revoked(jti: str) -> bool:
    """Check if a token has been revoked. Replaces TokenBlacklist.is_revoked().

    Returns True if the token JTI exists in the revocations table
    and has not yet expired.
    """
    pool = _get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT 1 FROM token_revocations
            WHERE jti = $1 AND expires_at > NOW() AND revoked_at IS NOT NULL
            """,
            jti,
        )
        return row is not None


async def pg_revoke_refresh_family(family_id: str) -> int:
    """Revoke all tokens in a refresh token family. Replaces TokenBlacklist.revoke_refresh_family().

    Marks every currently active token in the family as revoked. The
    ``revoked_at`` predicate keeps this operation idempotent while the
    family-level advisory lock serializes it with refresh rotation.

    Returns the count of tokens revoked.
    """
    if not family_id:
        return 0
    pool = _get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            await conn.execute(
                "SELECT pg_advisory_xact_lock(hashtext($1))", family_id,
            )
            result = await conn.execute(
                """
                UPDATE token_revocations
                SET revoked_at = NOW()
                WHERE family_id = $1 AND revoked_at IS NULL
                """,
                family_id,
            )
        # Also mark all tokens with this family_id that aren't yet in the table
        revoked_count = int(result.split()[-1]) if result else 0
        return revoked_count


async def pg_register_refresh_family(
    family_id: str,
    jti: str,
    expires_at: datetime | None = None,
) -> None:
    """Register an active refresh JTI without marking it revoked."""
    if not family_id or not jti:
        return
    expires_at = expires_at or (
        datetime.now(timezone.utc) + timedelta(days=REFRESH_EXPIRY_DAYS)
    )
    pool = _get_pool()
    async with pool.acquire() as conn:
        inserted = await conn.fetchrow(
            """
            INSERT INTO token_revocations (jti, expires_at, family_id, revoked_at)
            VALUES ($1, $2, $3, NULL)
            ON CONFLICT (jti) DO NOTHING
            RETURNING jti
            """,
            jti, expires_at, family_id,
        )
        if not inserted:
            raise RuntimeError("refresh token JTI collision")


async def pg_rotate_refresh_token(
    family_id: str,
    old_jti: str,
    new_jti: str,
    new_expires_at: datetime,
) -> bool:
    """Atomically consume one refresh token and register its successor.

    A family-level advisory lock makes concurrent refresh requests deterministic:
    the first request rotates successfully, while a replay revokes the complete
    family before returning failure.
    """
    if not family_id or not old_jti or not new_jti:
        return False
    pool = _get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            await conn.execute(
                "SELECT pg_advisory_xact_lock(hashtext($1))", family_id,
            )
            consumed = await conn.fetchrow(
                """
                UPDATE token_revocations
                SET revoked_at = NOW()
                WHERE jti = $1 AND family_id = $2
                  AND revoked_at IS NULL AND expires_at > NOW()
                RETURNING jti
                """,
                old_jti, family_id,
            )
            if not consumed:
                await conn.execute(
                    "UPDATE token_revocations SET revoked_at = NOW() "
                    "WHERE family_id = $1 AND revoked_at IS NULL",
                    family_id,
                )
                return False
            inserted = await conn.fetchrow(
                """
                INSERT INTO token_revocations (jti, expires_at, family_id, revoked_at)
                VALUES ($1, $2, $3, NULL)
                ON CONFLICT (jti) DO NOTHING
                RETURNING jti
                """,
                new_jti, new_expires_at, family_id,
            )
            if not inserted:
                await conn.execute(
                    "UPDATE token_revocations SET revoked_at = NOW() "
                    "WHERE family_id = $1 AND revoked_at IS NULL",
                    family_id,
                )
                return False
            return True


async def pg_cleanup_expired_tokens() -> int:
    """Remove expired token revocations from the table.

    Returns the count of rows deleted.
    """
    pool = _get_pool()
    async with pool.acquire() as conn:
        result = await conn.execute(
            "DELETE FROM token_revocations WHERE expires_at < NOW()"
        )
        deleted = int(result.split()[-1]) if result else 0
        return deleted


# ═══════════════════════════════════════════════════════════════
# Audit Log (PG-backed — replaces audit.py SQLite AuditLogger)
# ═══════════════════════════════════════════════════════════════

async def pg_audit_log(
    actor_id: int,
    action: str,
    target_user_id: int | None = None,
    details: dict | None = None,
    ip_address: str | None = None,
) -> None:
    """Write an audit log entry directly to PostgreSQL.

    Replaces AuditLogger.log() when PG is available.
    No background thread needed — asyncpg handles connection pooling.

    Args:
        actor_id: User ID performing the action
        action: Action type (e.g. 'user.create', 'permission.denied')
        target_user_id: User ID affected by the action
        details: Arbitrary JSON-serializable detail dict
        ip_address: Client IP address
    """
    import json as _json
    pool = _get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO audit_logs (actor_id, action, target_user_id, details, ip_address)
            VALUES ($1, $2, $3, $4::jsonb, $5)
            """,
            actor_id,
            action,
            target_user_id,
            _json.dumps(details or {}, ensure_ascii=False),
            ip_address,
        )


async def pg_query_audit_logs(
    page: int = 1,
    page_size: int = 20,
    actor_id: int | None = None,
    action: str | None = None,
) -> dict:
    """Paginated query of audit logs from PostgreSQL.

    Replaces audit.query_audit_logs() when PG is available.

    Returns:
        {"logs": [...], "total": N, "page": N, "page_size": N, "total_pages": N}
    """
    import json as _json

    where_clauses: list[str] = []
    params: list = []

    if actor_id is not None:
        where_clauses.append(f"actor_id = ${len(params) + 1}")
        params.append(actor_id)
    if action:
        where_clauses.append(f"action = ${len(params) + 1}")
        params.append(action)

    where_sql = " AND ".join(where_clauses)
    if where_sql:
        where_sql = " WHERE " + where_sql

    pool = _get_pool()
    async with pool.acquire() as conn:
        # Count
        count_sql = f"SELECT COUNT(*) as cnt FROM audit_logs {where_sql}"
        total = await conn.fetchval(count_sql, *params)

        # Page query (newest first)
        offset = (page - 1) * page_size
        query_sql = f"""
            SELECT * FROM audit_logs
            {where_sql}
            ORDER BY created_at DESC
            LIMIT ${len(params) + 1} OFFSET ${len(params) + 2}
        """
        rows = await conn.fetch(query_sql, *params, page_size, offset)

        logs = []
        for r in rows:
            log = dict(r)
            # Parse details from JSONB (may already be a dict from asyncpg)
            if isinstance(log.get("details"), str):
                try:
                    log["details"] = _json.loads(log["details"])
                except (_json.JSONDecodeError, TypeError):
                    log["details"] = {}
            elif log.get("details") is None:
                log["details"] = {}
            # Convert datetime objects to ISO strings for JSON serialization
            for key in ("created_at",):
                val = log.get(key)
                if isinstance(val, datetime):
                    log[key] = val.isoformat()
            logs.append(log)

    total_pages = max(1, (total + page_size - 1) // page_size)
    return {
        "logs": logs,
        "total": total,
        "page": page,
        "page_size": page_size,
        "total_pages": total_pages,
    }


# ═══════════════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════════════

def _sanitize_user(user: dict | None) -> dict | None:
    if user is None:
        return None
    return {k: v for k, v in user.items() if k != "password_hash"}
