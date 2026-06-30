# -*- coding: utf-8 -*-
"""
RAG-Anything Authentication Service.

Layer: Service
Primary Responsibility: SQLite user storage, bcrypt password hashing,
    JWT token issuance and verification, account lockout protection.
Key Dependencies: aiosqlite, passlib (bcrypt), PyJWT, stdlib

Migrated from root-level auth.py. All original function signatures preserved.
"""

import os
import sqlite3
import secrets
import uuid
from datetime import datetime, timedelta
from pathlib import Path

import jwt as pyjwt
from passlib.context import CryptContext

# ── Password Hashing ───────────────────────────────────────
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# ── JWT Configuration ──────────────────────────────────────
SECRET_KEY = os.getenv("JWT_SECRET") or secrets.token_hex(32)
REFRESH_SECRET_KEY = os.getenv("JWT_REFRESH_SECRET") or secrets.token_hex(32)
JWT_EXPIRY_HOURS = int(os.getenv("JWT_EXPIRY_HOURS", "1"))
REFRESH_EXPIRY_DAYS = int(os.getenv("REFRESH_EXPIRY_DAYS", "7"))
ALGORITHM = "HS256"
SERVER_START_ID = uuid.uuid4().hex  # Regenerated on each process start; persisted to settings for multi-worker consistency

# ── Database Path ──────────────────────────────────────────
DB_PATH = Path(os.getenv("AUTH_DB_PATH", "./auth.db"))

def get_db_path() -> Path:
    """Return the current database path, respecting AUTH_DB_PATH env var.

    Unlike the module-level DB_PATH constant (set at import time),
    this function re-reads the environment variable on each call,
    allowing tests to switch databases via AUTH_DB_PATH.
    """
    return Path(os.getenv("AUTH_DB_PATH", "./auth.db"))

# ── Default Admin ──────────────────────────────────────────
DEFAULT_ADMIN_USERNAME = os.getenv("DEFAULT_ADMIN_USERNAME", "admin")
DEFAULT_ADMIN_EMAIL = os.getenv("DEFAULT_ADMIN_EMAIL", "admin@raganything.local")
_raw_admin_pw = os.getenv("DEFAULT_ADMIN_PASSWORD")
if not _raw_admin_pw:
    import secrets
    _raw_admin_pw = secrets.token_urlsafe(16)
    import sys
    print("=" * 60, file=sys.stderr)
    print("[AUTH] DEFAULT_ADMIN_PASSWORD 环境变量未设置。", file=sys.stderr)
    print(f"[AUTH] 已生成随机管理员密码（仅显示一次）: {_raw_admin_pw}", file=sys.stderr)
    print("[AUTH] 请立即修改此密码或设置 DEFAULT_ADMIN_PASSWORD 环境变量", file=sys.stderr)
    print("=" * 60, file=sys.stderr)
DEFAULT_ADMIN_PASSWORD = _raw_admin_pw


async def init_db():
    """Initialize database: create users + settings tables, default admin, persist keys."""
    import aiosqlite

    async with aiosqlite.connect(str(get_db_path())) as db:
        db.row_factory = aiosqlite.Row
        await db.execute("PRAGMA journal_mode=WAL")
        await db.execute("PRAGMA busy_timeout=5000")
        # ── Roles table (created before users to satisfy FK reference) ──
        await db.execute("""
            CREATE TABLE IF NOT EXISTS roles (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                name        TEXT UNIQUE NOT NULL,
                description TEXT NOT NULL DEFAULT '',
                permissions TEXT NOT NULL DEFAULT '[]',
                created_at  TEXT DEFAULT (datetime('now','localtime'))
            )
        """)
        # Insert default roles if missing
        import json as _json_rbac
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
            existing = await (await db.execute(
                "SELECT id FROM roles WHERE name = ?", (role_name,)
            )).fetchone()
            if not existing:
                await db.execute(
                    "INSERT INTO roles (name, description, permissions) VALUES (?, ?, ?)",
                    (role_name, role_cfg["desc"], _json_rbac.dumps(role_cfg["perms"])),
                )
            else:
                # UPDATE existing role to pick up new permissions (e.g. manufacturing:read)
                await db.execute(
                    "UPDATE roles SET description = ?, permissions = ? WHERE name = ?",
                    (role_cfg["desc"], _json_rbac.dumps(role_cfg["perms"]), role_name),
                )

        await db.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                username    TEXT UNIQUE NOT NULL,
                email       TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL,
                role_id     INTEGER REFERENCES roles(id) DEFAULT NULL,
                is_active   INTEGER DEFAULT 1,
                failed_login_attempts INTEGER DEFAULT 0,
                locked_until TEXT DEFAULT NULL,
                last_login_at TEXT DEFAULT NULL,
                must_change_password INTEGER DEFAULT 0,
                created_at  TEXT DEFAULT (datetime('now','localtime')),
                updated_at  TEXT DEFAULT (datetime('now','localtime'))
            )
        """)
        await db.execute(
            "CREATE INDEX IF NOT EXISTS idx_users_role_id ON users(role_id)"
        )
        await db.execute("""
            CREATE TABLE IF NOT EXISTS settings (
                key   TEXT PRIMARY KEY,
                value TEXT NOT NULL
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS audit_logs (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                actor_id        INTEGER NOT NULL,
                action          TEXT NOT NULL,
                target_user_id  INTEGER,
                details         TEXT DEFAULT '{}',
                ip_address      TEXT,
                created_at      TEXT DEFAULT (datetime('now','localtime'))
            )
        """)
        await db.execute("CREATE INDEX IF NOT EXISTS idx_audit_actor ON audit_logs(actor_id)")
        await db.execute("CREATE INDEX IF NOT EXISTS idx_audit_action ON audit_logs(action)")
        await db.execute("CREATE INDEX IF NOT EXISTS idx_audit_created ON audit_logs(created_at)")
        await db.execute("""
            CREATE TABLE IF NOT EXISTS token_revocations (
                jti         TEXT PRIMARY KEY,
                expires_at  TEXT NOT NULL,
                revoked_at  TEXT DEFAULT (datetime('now','localtime'))
            )
        """)
        await db.execute("CREATE INDEX IF NOT EXISTS idx_token_revocations_expires ON token_revocations(expires_at)")
        await db.commit()
        # Migrate: add columns to existing tables (idempotent)
        _migration_columns = [
            ("failed_login_attempts", "INTEGER DEFAULT 0"),
            ("locked_until", "TEXT DEFAULT NULL"),
            ("role_id", "INTEGER REFERENCES roles(id) DEFAULT NULL"),
            ("last_login_at", "TEXT DEFAULT NULL"),
            ("must_change_password", "INTEGER DEFAULT 0"),
        ]
        for col_name, col_def in _migration_columns:
            try:
                await db.execute(f"ALTER TABLE users ADD COLUMN {col_name} {col_def}")
            except aiosqlite.OperationalError as e:
                if "duplicate column" not in str(e).lower():
                    raise
        await db.commit()

        # Load or persist JWT keys (env var takes priority; serialized via SQLite lock)
        # In multi-worker deployments, the first worker persists its key; subsequent
        # workers load the persisted key to ensure consistency across workers.
        global SECRET_KEY, REFRESH_SECRET_KEY
        if not os.getenv("JWT_SECRET"):
            row = await (await db.execute(
                "SELECT value FROM settings WHERE key = 'jwt_secret'"
            )).fetchone()
            if row:
                SECRET_KEY = row[0]  # Use persisted key for cross-worker consistency
            else:
                # Persist current module-level key for other workers
                await db.execute(
                    "INSERT INTO settings (key, value) VALUES ('jwt_secret', ?)",
                    (SECRET_KEY,)
                )
                await db.commit()

        if not os.getenv("JWT_REFRESH_SECRET"):
            row = await (await db.execute(
                "SELECT value FROM settings WHERE key = 'jwt_refresh_secret'"
            )).fetchone()
            if row:
                REFRESH_SECRET_KEY = row[0]
            else:
                await db.execute(
                    "INSERT INTO settings (key, value) VALUES ('jwt_refresh_secret', ?)",
                    (REFRESH_SECRET_KEY,)
                )
                await db.commit()

        # ── Persist/load SERVER_START_ID for cross-worker JWT consistency ──
        # In multi-worker deployments (gunicorn --workers N), each worker must
        # share the same SERVER_START_ID so tokens issued by one worker are
        # accepted by all.  The first worker persists its ID; subsequent workers
        # load the persisted value from the settings table.
        global SERVER_START_ID
        row = await (await db.execute(
            "SELECT value FROM settings WHERE key = 'server_start_id'"
        )).fetchone()
        if row:
            SERVER_START_ID = row[0]
        else:
            await db.execute(
                "INSERT INTO settings (key, value) VALUES ('server_start_id', ?)",
                (SERVER_START_ID,)
            )
            await db.commit()

    # Ensure default admin exists
    admin = await get_user_by_username(DEFAULT_ADMIN_USERNAME)
    if not admin:
        super_admin_role = await get_role_by_name("super_admin")
        await create_user(DEFAULT_ADMIN_USERNAME, DEFAULT_ADMIN_EMAIL, DEFAULT_ADMIN_PASSWORD,
                          role_id=super_admin_role["id"] if super_admin_role else None, must_change_password=True)
        # Force password change on first login for auto-created default admin
        async with aiosqlite.connect(str(get_db_path())) as db:
            await db.execute(
                "UPDATE users SET must_change_password = 1 WHERE username = ?",
                (DEFAULT_ADMIN_USERNAME,),
            )
            await db.commit()
        print(f"[AUTH] 默认管理员已创建: {DEFAULT_ADMIN_USERNAME} (首次登录需修改密码)")
    else:
        print(f"[AUTH] 管理员账号已存在: {DEFAULT_ADMIN_USERNAME}")

    print(f"[AUTH] 数据库已初始化: {get_db_path()}")


# ── User CRUD ──────────────────────────────────────────────

async def get_user_by_username(username: str) -> dict | None:
    """Query user by username."""
    import aiosqlite
    async with aiosqlite.connect(str(get_db_path())) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute("SELECT * FROM users WHERE username = ?", (username,))
        row = await cursor.fetchone()
        return dict(row) if row else None


async def get_user_by_id(user_id: int) -> dict | None:
    """Query user by ID."""
    import aiosqlite
    async with aiosqlite.connect(str(get_db_path())) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute("SELECT * FROM users WHERE id = ?", (user_id,))
        row = await cursor.fetchone()
        return dict(row) if row else None


async def create_user(username: str, email: str, password: str, role_id: int | None = None, must_change_password: bool = False) -> dict:
    """Create a new user. Returns user dict without password hash."""
    import aiosqlite, re as _re_pw

    if len(password) < 8:
        raise ValueError("密码至少需要 8 位")
    if len(password) > 128:
        raise ValueError("密码不能超过 128 位")
    if len(username) < 2:
        raise ValueError("用户名至少需要 2 个字符")
    # Password complexity: at least 3 of 4 character classes
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

    async with aiosqlite.connect(str(get_db_path())) as db:
        db.row_factory = aiosqlite.Row
        # Default role: student
        if role_id is None:
            role_name = "student"
            role_row = await (await db.execute(
                "SELECT id FROM roles WHERE name = ?", (role_name,)
            )).fetchone()
            if not role_row:
                raise ValueError(f"角色 '{role_name}' 不存在，请先初始化默认角色")
            role_id = role_row[0]
        else:
            # Validate the explicit role_id exists
            role_row = await (await db.execute(
                "SELECT id FROM roles WHERE id = ?", (role_id,)
            )).fetchone()
            if not role_row:
                raise ValueError(f"角色 ID {role_id} 不存在")

        try:
            cursor = await db.execute(
                "INSERT INTO users (username, email, password_hash, role_id, must_change_password) VALUES (?, ?, ?, ?, ?)",
                (username.strip(), email.strip(), password_hash, role_id, 1 if must_change_password else 0),
            )
            await db.commit()
            user_id = cursor.lastrowid
        except sqlite3.IntegrityError as e:
            msg = str(e).lower()
            if "username" in msg:
                raise ValueError("用户名已被占用")
            elif "email" in msg:
                raise ValueError("邮箱已被占用")
            else:
                raise ValueError("注册失败，请重试")

    user = await get_user_by_id(user_id)
    return _sanitize_user(user)


async def update_user(user_id: int, data: dict) -> dict | None:
    """Update user info (admin only).

    Security note: ``is_admin`` is NOT directly updatable. The caller
    (router layer) must translate ``is_admin`` to ``role_id`` before
    invoking this function. ``role_id`` is the canonical field.
    """
    import aiosqlite
    import logging as _logging

    _logger = _logging.getLogger("rag_server.auth")

    # role_id is canonical; is_admin is rejected (must be translated upstream)
    allowed_fields = {"username", "email", "role_id", "is_active", "must_change_password"}
    security_sensitive_fields = {"password_hash", "failed_login_attempts",
                                  "locked_until", "created_at", "updated_at"}

    # Log + reject security-sensitive fields that bypass the allowlist
    rejected = {k for k in data if k in security_sensitive_fields}
    if rejected:
        _logger.warning(
            "[SECURITY] update_user(id=%d) received rejected security-sensitive fields: %s",
            user_id, rejected,
        )
        raise ValueError(f"不允许直接修改以下字段: {', '.join(sorted(rejected))}")

    # Warn about unrecognized fields (potential typos or silent drops)
    unrecognized = {k for k in data if k not in allowed_fields
                    and k not in security_sensitive_fields
                    and k != "password"}
    if unrecognized:
        _logger.warning(
            "[SECURITY] update_user(id=%d) ignoring unrecognized fields: %s",
            user_id, unrecognized,
        )

    updates = {k: v for k, v in data.items() if k in allowed_fields}

    if "password" in data and data["password"]:
        updates["password_hash"] = pwd_context.hash(data["password"])

    if not updates:
        return await get_user_by_id(user_id)

    updates["updated_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    set_clause = ", ".join(f"{k} = ?" for k in updates)
    values = list(updates.values()) + [user_id]

    async with aiosqlite.connect(str(get_db_path())) as db:
        db.row_factory = aiosqlite.Row
        try:
            await db.execute(f"UPDATE users SET {set_clause} WHERE id = ?", values)
            await db.commit()
        except sqlite3.IntegrityError as e:
            raise ValueError(f"更新失败: {e}")

    return await get_user_by_id(user_id)


# ── Role & Permission Helpers ────────────────────────────────

async def get_role_by_name(role_name: str) -> dict | None:
    """Look up a role by its name."""
    import aiosqlite
    async with aiosqlite.connect(str(get_db_path())) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT * FROM roles WHERE name = ?", (role_name,)
        )
        row = await cursor.fetchone()
        return dict(row) if row else None


async def list_roles() -> list[dict]:
    """List all roles."""
    import aiosqlite, json as _json
    async with aiosqlite.connect(str(get_db_path())) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute("SELECT * FROM roles ORDER BY id")
        rows = await cursor.fetchall()
        roles = []
        for r in rows:
            role = dict(r)
            try:
                role["permissions"] = _json.loads(role.get("permissions", "[]"))
            except (_json.JSONDecodeError, TypeError):
                role["permissions"] = []
            roles.append(role)
        return roles


async def get_user_role(user_id: int) -> dict | None:
    """Get the role assigned to a user. Returns role dict or None."""
    import aiosqlite
    async with aiosqlite.connect(str(get_db_path())) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute("""
            SELECT r.* FROM roles r
            JOIN users u ON u.role_id = r.id
            WHERE u.id = ?
        """, (user_id,))
        row = await cursor.fetchone()
        return dict(row) if row else None


async def has_permission(user_id: int, permission: str) -> bool:
    """Check if a user has a specific permission via their role."""
    role = await get_user_role(user_id)
    if not role:
        return False
    try:
        import json
        perms = json.loads(role.get("permissions", "[]"))
        return permission in perms
    except (json.JSONDecodeError, TypeError):
        return False


async def user_is_admin(user_id: int) -> bool:
    """Backward-compatible: check if user role is 'super_admin'."""
    role = await get_user_role(user_id)
    return role is not None and role.get("name") == "super_admin"


async def update_last_login_at(user_id: int) -> None:
    """Update the last_login_at timestamp for a user."""
    import aiosqlite
    from datetime import datetime
    async with aiosqlite.connect(str(get_db_path())) as db:
        await db.execute(
            "UPDATE users SET last_login_at = ? WHERE id = ?",
            (datetime.now().strftime("%Y-%m-%d %H:%M:%S"), user_id),
        )
        await db.commit()


async def delete_user(user_id: int) -> bool:
    """Delete a user."""
    import aiosqlite
    async with aiosqlite.connect(str(get_db_path())) as db:
        cursor = await db.execute("DELETE FROM users WHERE id = ?", (user_id,))
        await db.commit()
        return cursor.rowcount > 0


async def list_users() -> list[dict]:
    """List all users (admin only)."""
    import aiosqlite
    async with aiosqlite.connect(str(get_db_path())) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute("SELECT * FROM users ORDER BY id")
        rows = await cursor.fetchall()
        return [_sanitize_user(dict(r)) for r in rows]


# ── Password Utilities ─────────────────────────────────────

def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify a plaintext password against a bcrypt hash."""
    return pwd_context.verify(plain_password, hashed_password)


# ── Brute-Force Protection ─────────────────────────────────

MAX_FAILED_ATTEMPTS = int(os.getenv("MAX_FAILED_LOGIN_ATTEMPTS", "5"))
LOCKOUT_DURATION_MINUTES = int(os.getenv("LOGIN_LOCKOUT_MINUTES", "15"))


async def check_account_locked(user_id: int) -> str | None:
    """Check if account is locked by user ID. Returns error message or None."""
    import aiosqlite
    async with aiosqlite.connect(str(get_db_path())) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT locked_until, failed_login_attempts FROM users WHERE id = ?",
            (user_id,),
        )
        row = await cursor.fetchone()
        if not row:
            return None
        locked_until = row["locked_until"]
        if locked_until:
            try:
                lock_time = datetime.fromisoformat(locked_until)
                if lock_time > datetime.utcnow():
                    remaining = int((lock_time - datetime.utcnow()).total_seconds() / 60) + 1
                    return f"账号已被锁定，请 {remaining} 分钟后重试"
                else:
                    await db.execute(
                        "UPDATE users SET locked_until = NULL, failed_login_attempts = 0 WHERE id = ?",
                        (user_id,),
                    )
                    await db.commit()
            except ValueError:
                pass
    return None


async def record_failed_login(user_id: int):
    """Record a failed login attempt. Locks account when threshold reached."""
    import aiosqlite
    async with aiosqlite.connect(str(get_db_path())) as db:
        db.row_factory = aiosqlite.Row
        await db.execute(
            "UPDATE users SET failed_login_attempts = failed_login_attempts + 1 WHERE id = ?",
            (user_id,),
        )
        cursor = await db.execute(
            "SELECT failed_login_attempts FROM users WHERE id = ?", (user_id,)
        )
        row = await cursor.fetchone()
        if row and row["failed_login_attempts"] >= MAX_FAILED_ATTEMPTS:
            lock_time = datetime.utcnow() + timedelta(minutes=LOCKOUT_DURATION_MINUTES)
            await db.execute(
                "UPDATE users SET locked_until = ? WHERE id = ?",
                (lock_time.isoformat(), user_id),
            )
        await db.commit()


async def reset_failed_logins(user_id: int):
    """Reset failed login counter after successful login."""
    import aiosqlite
    async with aiosqlite.connect(str(get_db_path())) as db:
        await db.execute(
            "UPDATE users SET failed_login_attempts = 0, locked_until = NULL WHERE id = ?",
            (user_id,),
        )
        await db.commit()


# ── JWT Utilities ──────────────────────────────────────────

def create_token(user_id: int, username: str, is_admin: bool, role: dict | None = None) -> str:
    """Issue a JWT access token. Authority (is_admin) is NOT embedded —
    it is derived server-side from the RBAC role on every request.
    Role information (name + permissions) is embedded for client-side display only.

    The is_admin parameter is accepted for backward compatibility but is not
    placed in the token payload."""
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
    """Verify and decode a JWT access token. Returns None if invalid or expired."""
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
    """Issue a JWT refresh token (7-day expiry). Authority is NOT embedded."""
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
    """Verify and decode a JWT refresh token. Returns None if invalid."""
    try:
        payload = pyjwt.decode(token, REFRESH_SECRET_KEY, algorithms=[ALGORITHM])
        if payload.get("type") != "refresh":
            return None
        if payload.get("sid") != SERVER_START_ID:
            return None
        return payload
    except (pyjwt.ExpiredSignatureError, pyjwt.InvalidTokenError):
        return None


# ── Helpers ────────────────────────────────────────────────

def _sanitize_user(user: dict | None) -> dict | None:
    """Remove password_hash from user dict for safe serialization."""
    if user is None:
        return None
    return {k: v for k, v in user.items() if k != "password_hash"}


# ═══════════════════════════════════════════════════════════════
# PostgreSQL Backend Override (当 DATABASE_URL 或 POSTGRES_HOST 存在时激活)
# ═══════════════════════════════════════════════════════════════

_USE_PG = bool(os.getenv("DATABASE_URL") or os.getenv("POSTGRES_HOST"))

if _USE_PG:
    import logging as _logging
    _pg_logger = _logging.getLogger("rag_server.auth")
    _pg_logger.info("检测到 PostgreSQL 配置，激活 PG 后端（带 SQLite 回退）")

    # Lazy imports for fallback paths (avoid circular import at module level)
    from raganything.services.token_blacklist import get_token_blacklist
    from raganything.services.audit import get_audit_logger

    # Save original SQLite implementations for fallback
    _sqlite_init_db = init_db
    _sqlite_get_user_by_username = get_user_by_username
    _sqlite_get_user_by_id = get_user_by_id
    _sqlite_create_user = create_user
    _sqlite_update_user = update_user
    _sqlite_delete_user = delete_user
    _sqlite_list_users = list_users
    _sqlite_get_user_role = get_user_role
    _sqlite_get_role_by_name = get_role_by_name
    _sqlite_list_roles = list_roles
    _sqlite_has_permission = has_permission
    _sqlite_user_is_admin = user_is_admin
    _sqlite_check_account_locked = check_account_locked
    _sqlite_record_failed_login = record_failed_login
    _sqlite_reset_failed_logins = reset_failed_logins
    _sqlite_update_last_login_at = update_last_login_at

    from raganything.services.pg_auth_repo import (
        init_db as _pg_init_db,
        get_user_by_username as _pg_get_user_by_username,
        get_user_by_id as _pg_get_user_by_id,
        create_user as _pg_create_user,
        update_user as _pg_update_user,
        delete_user as _pg_delete_user,
        list_users as _pg_list_users,
        get_user_role as _pg_get_user_role,
        has_permission as _pg_has_permission,
        user_is_admin as _pg_user_is_admin,
        check_account_locked as _pg_check_account_locked,
        record_failed_login as _pg_record_failed_login,
        reset_failed_logins as _pg_reset_failed_logins,
        update_last_login_at as _pg_update_last_login_at,
        get_role_by_name as _pg_get_role_by_name,
        list_roles as _pg_list_roles,
        # Token blacklist (PG-backed)
        pg_revoke_token as _pg_revoke_token,
        pg_is_token_revoked as _pg_is_token_revoked,
        pg_revoke_refresh_family as _pg_revoke_refresh_family,
        pg_register_refresh_family as _pg_register_refresh_family,
        # Audit log (PG-backed)
        pg_audit_log as _pg_audit_log,
        pg_query_audit_logs as _pg_query_audit_logs,
        # Constants
        SECRET_KEY as _PG_SECRET_KEY,
        REFRESH_SECRET_KEY as _PG_REFRESH_SECRET_KEY,
        SERVER_START_ID as _PG_SERVER_START_ID,
        DEFAULT_ADMIN_USERNAME as _PG_DEFAULT_ADMIN_USERNAME,
        DEFAULT_ADMIN_EMAIL as _PG_DEFAULT_ADMIN_EMAIL,
        DEFAULT_ADMIN_PASSWORD as _PG_DEFAULT_ADMIN_PASSWORD,
    )

    # Helper: returns True if PG pool is ready
    def _pg_ready() -> bool:
        try:
            from raganything.services.pg_state_repo import get_pg_pool
            get_pg_pool()
            return True
        except RuntimeError:
            return False

    def _sync_pg_constants():
        """Re-sync auth.py module-level constants from pg_auth_repo.

        pg_auth_repo.init_db() updates its own globals (e.g. SECRET_KEY,
        SERVER_START_ID) from the settings table. We must mirror those
        updates back to auth.py's globals so JWT sign/verify functions
        (defined in this module) use the correct, persisted values.
        """
        import raganything.services.pg_auth_repo as _pg_mod
        globals()["SECRET_KEY"] = _pg_mod.SECRET_KEY
        globals()["REFRESH_SECRET_KEY"] = _pg_mod.REFRESH_SECRET_KEY
        globals()["SERVER_START_ID"] = _pg_mod.SERVER_START_ID

    # Wrapper: PG with SQLite fallback
    async def init_db():
        if _pg_ready():
            await _pg_init_db()
            _sync_pg_constants()  # pick up settings-persisted values
        else:
            await _sqlite_init_db()

    async def get_user_by_username(username: str):
        return await _pg_get_user_by_username(username) if _pg_ready() else await _sqlite_get_user_by_username(username)

    async def get_user_by_id(user_id: int):
        return await _pg_get_user_by_id(user_id) if _pg_ready() else await _sqlite_get_user_by_id(user_id)

    async def create_user(username: str, email: str, password: str, role_id: int | None = None, must_change_password: bool = False):
        return await _pg_create_user(username, email, password, role_id, must_change_password) if _pg_ready() else await _sqlite_create_user(username, email, password, role_id, must_change_password)

    async def update_user(user_id: int, data: dict):
        return await _pg_update_user(user_id, data) if _pg_ready() else await _sqlite_update_user(user_id, data)

    async def delete_user(user_id: int):
        return await _pg_delete_user(user_id) if _pg_ready() else await _sqlite_delete_user(user_id)

    async def list_users():
        return await _pg_list_users() if _pg_ready() else await _sqlite_list_users()

    async def get_user_role(user_id: int):
        return await _pg_get_user_role(user_id) if _pg_ready() else await _sqlite_get_user_role(user_id)

    async def get_role_by_name(role_name: str):
        return await _pg_get_role_by_name(role_name) if _pg_ready() else await _sqlite_get_role_by_name(role_name)

    async def list_roles():
        return await _pg_list_roles() if _pg_ready() else await _sqlite_list_roles()

    async def has_permission(user_id: int, permission: str):
        return await _pg_has_permission(user_id, permission) if _pg_ready() else await _sqlite_has_permission(user_id, permission)

    async def user_is_admin(user_id: int):
        return await _pg_user_is_admin(user_id) if _pg_ready() else await _sqlite_user_is_admin(user_id)

    async def check_account_locked(user_id: int):
        return await _pg_check_account_locked(user_id) if _pg_ready() else await _sqlite_check_account_locked(user_id)

    async def record_failed_login(user_id: int):
        return await _pg_record_failed_login(user_id) if _pg_ready() else await _sqlite_record_failed_login(user_id)

    async def reset_failed_logins(user_id: int):
        return await _pg_reset_failed_logins(user_id) if _pg_ready() else await _sqlite_reset_failed_logins(user_id)

    async def update_last_login_at(user_id: int):
        if _pg_ready():
            await _pg_update_last_login_at(user_id)
        else:
            await _sqlite_update_last_login_at(user_id)

    # ── Token Blacklist Dispatch (Phase 1 PG migration) ──────

    async def is_token_revoked(jti: str) -> bool:
        """Check if a token JTI is revoked. PG-first with SQLite fallback."""
        if _pg_ready():
            return await _pg_is_token_revoked(jti)
        return get_token_blacklist().is_revoked(jti)

    async def revoke_token(jti: str, expires_at, family_id: str | None = None):
        """Revoke a token. PG-first with SQLite fallback."""
        if _pg_ready():
            await _pg_revoke_token(jti, expires_at, family_id)
        else:
            get_token_blacklist().revoke(jti, expires_at)

    async def revoke_refresh_family(family_id: str):
        """Revoke all tokens in a refresh family. PG-first with SQLite fallback."""
        if _pg_ready():
            await _pg_revoke_refresh_family(family_id)
        else:
            get_token_blacklist().revoke_refresh_family(family_id)

    async def register_refresh_family(family_id: str, jti: str):
        """Register a JTI into a refresh family. PG-first with SQLite fallback."""
        if _pg_ready():
            await _pg_register_refresh_family(family_id, jti)
        else:
            get_token_blacklist().register_refresh_family(family_id, jti)

    # ── Audit Log Dispatch (Phase 1 PG migration) ─────────────

    async def audit_log(
        actor_id: int,
        action: str,
        target_user_id: int | None = None,
        details: dict | None = None,
        ip_address: str | None = None,
    ):
        """Write audit log. PG-first (direct write) with SQLite fallback."""
        if _pg_ready():
            await _pg_audit_log(actor_id, action, target_user_id, details, ip_address)
        else:
            audit = get_audit_logger()
            await audit.log(actor_id, action, target_user_id, details, ip_address)

    async def query_audit_logs(
        page: int = 1,
        page_size: int = 20,
        actor_id: int | None = None,
        action: str | None = None,
    ):
        """Query audit logs with pagination. PG-first with SQLite fallback."""
        if _pg_ready():
            return await _pg_query_audit_logs(page, page_size, actor_id, action)
        from raganything.services.audit import query_audit_logs as _sqlite_query
        return await _sqlite_query(str(DB_PATH), page, page_size, actor_id, action)

    # Sync module-level constants so JWT functions use the PG-backed values
    SECRET_KEY = _PG_SECRET_KEY
    REFRESH_SECRET_KEY = _PG_REFRESH_SECRET_KEY
    SERVER_START_ID = _PG_SERVER_START_ID
    DEFAULT_ADMIN_USERNAME = _PG_DEFAULT_ADMIN_USERNAME
    DEFAULT_ADMIN_EMAIL = _PG_DEFAULT_ADMIN_EMAIL
    DEFAULT_ADMIN_PASSWORD = _PG_DEFAULT_ADMIN_PASSWORD
    _pg_logger.info("PG 后端已激活（带 SQLite 运行时回退）")

else:
    # ── No PG configured — define direct SQLite dispatch functions ──
    # These have the same names/signatures as the PG dispatch wrappers above,
    # so callers can import them unconditionally regardless of PG availability.

    from raganything.services.token_blacklist import get_token_blacklist

    async def is_token_revoked(jti: str) -> bool:
        return get_token_blacklist().is_revoked(jti)

    async def revoke_token(jti: str, expires_at, family_id: str | None = None):
        get_token_blacklist().revoke(jti, expires_at)

    async def revoke_refresh_family(family_id: str):
        get_token_blacklist().revoke_refresh_family(family_id)

    async def register_refresh_family(family_id: str, jti: str):
        get_token_blacklist().register_refresh_family(family_id, jti)

    async def audit_log(
        actor_id: int,
        action: str,
        target_user_id: int | None = None,
        details: dict | None = None,
        ip_address: str | None = None,
    ):
        from raganything.services.audit import get_audit_logger as _audit
        audit = _audit()
        await audit.log(actor_id, action, target_user_id, details, ip_address)

    async def query_audit_logs(
        page: int = 1,
        page_size: int = 20,
        actor_id: int | None = None,
        action: str | None = None,
    ):
        from raganything.services.audit import query_audit_logs as _sqlite_query
        return await _sqlite_query(str(DB_PATH), page, page_size, actor_id, action)
