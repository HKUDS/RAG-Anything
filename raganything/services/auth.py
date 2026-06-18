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
SERVER_START_ID = uuid.uuid4().hex  # Regenerated on each process start for restart-invalidation

# ── Database Path ──────────────────────────────────────────
DB_PATH = Path(os.getenv("AUTH_DB_PATH", "./auth.db"))

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

    async with aiosqlite.connect(str(DB_PATH)) as db:
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
            "admin": {
                "desc": "系统管理员，拥有全部权限",
                "perms": [
                    "users:read", "users:write", "users:delete",
                    "kb:read", "kb:write", "kb:delete",
                    "agent:read", "agent:write", "agent:delete",
                    "settings:read", "settings:write",
                    "audit:read", "monitor:read",
                ],
            },
            "editor": {
                "desc": "内容编辑，可读写知识库和智能体",
                "perms": ["kb:read", "kb:write", "agent:read", "agent:write", "monitor:read"],
            },
            "viewer": {
                "desc": "只读用户，仅可查看知识库和智能体",
                "perms": ["kb:read", "agent:read", "monitor:read"],
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

        await db.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                username    TEXT UNIQUE NOT NULL,
                email       TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL,
                role_id     INTEGER REFERENCES roles(id) DEFAULT NULL,
                is_admin    INTEGER DEFAULT 0,
                is_active   INTEGER DEFAULT 1,
                failed_login_attempts INTEGER DEFAULT 0,
                locked_until TEXT DEFAULT NULL,
                last_login_at TEXT DEFAULT NULL,
                must_change_password INTEGER DEFAULT 0,
                created_at  TEXT DEFAULT (datetime('now','localtime')),
                updated_at  TEXT DEFAULT (datetime('now','localtime'))
            )
        """)
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
            except Exception:
                pass
        await db.commit()

        # Migrate existing users: if role_id is NULL, assign from is_admin
        admin_role = await (await db.execute(
            "SELECT id FROM roles WHERE name = 'admin'"
        )).fetchone()
        viewer_role = await (await db.execute(
            "SELECT id FROM roles WHERE name = 'viewer'"
        )).fetchone()
        if admin_role and viewer_role:
            admin_id = admin_role[0]
            viewer_id = viewer_role[0]
            # Assign role to users with NULL role_id based on legacy is_admin flag
            await db.execute(
                "UPDATE users SET role_id = ? WHERE role_id IS NULL AND is_admin = 1",
                (admin_id,),
            )
            await db.execute(
                "UPDATE users SET role_id = ? WHERE role_id IS NULL AND is_admin = 0",
                (viewer_id,),
            )
            await db.commit()

        # Load or persist JWT keys (env var takes priority)
        global SECRET_KEY, REFRESH_SECRET_KEY
        if not os.getenv("JWT_SECRET"):
            row = await (await db.execute("SELECT value FROM settings WHERE key = 'jwt_secret'")).fetchone()
            if row:
                SECRET_KEY = row[0]
                print("[AUTH] JWT 密钥已从数据库加载")
            else:
                await db.execute("INSERT INTO settings (key, value) VALUES ('jwt_secret', ?)", (SECRET_KEY,))
                await db.commit()
                print("[AUTH] JWT 密钥已生成并持久化到数据库")
        else:
            print("[AUTH] JWT 密钥从环境变量加载")

        if not os.getenv("JWT_REFRESH_SECRET"):
            row = await (await db.execute("SELECT value FROM settings WHERE key = 'jwt_refresh_secret'")).fetchone()
            if row:
                REFRESH_SECRET_KEY = row[0]
                print("[AUTH] Refresh 密钥已从数据库加载")
            else:
                await db.execute("INSERT INTO settings (key, value) VALUES ('jwt_refresh_secret', ?)", (REFRESH_SECRET_KEY,))
                await db.commit()
                print("[AUTH] Refresh 密钥已生成并持久化到数据库")
        else:
            print("[AUTH] Refresh 密钥从环境变量加载")

    # Ensure default admin exists
    admin = await get_user_by_username(DEFAULT_ADMIN_USERNAME)
    if not admin:
        await create_user(DEFAULT_ADMIN_USERNAME, DEFAULT_ADMIN_EMAIL, DEFAULT_ADMIN_PASSWORD, is_admin=True)
        # Force password change on first login for auto-created default admin
        async with aiosqlite.connect(str(DB_PATH)) as db:
            await db.execute(
                "UPDATE users SET must_change_password = 1 WHERE username = ?",
                (DEFAULT_ADMIN_USERNAME,),
            )
            await db.commit()
        print(f"[AUTH] 默认管理员已创建: {DEFAULT_ADMIN_USERNAME} (首次登录需修改密码)")
    else:
        print(f"[AUTH] 管理员账号已存在: {DEFAULT_ADMIN_USERNAME}")

    print(f"[AUTH] 数据库已初始化: {DB_PATH}")


# ── User CRUD ──────────────────────────────────────────────

async def get_user_by_username(username: str) -> dict | None:
    """Query user by username."""
    import aiosqlite
    async with aiosqlite.connect(str(DB_PATH)) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute("SELECT * FROM users WHERE username = ?", (username,))
        row = await cursor.fetchone()
        return dict(row) if row else None


async def get_user_by_id(user_id: int) -> dict | None:
    """Query user by ID."""
    import aiosqlite
    async with aiosqlite.connect(str(DB_PATH)) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute("SELECT * FROM users WHERE id = ?", (user_id,))
        row = await cursor.fetchone()
        return dict(row) if row else None


async def create_user(username: str, email: str, password: str, is_admin: bool = False) -> dict:
    """Create a new user. Returns user dict without password hash.

    .. deprecated::
        `is_admin` 参数已弃用，请使用 `role_id` 代替。
        此处保留仅为向后兼容。
    """
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

    async with aiosqlite.connect(str(DB_PATH)) as db:
        db.row_factory = aiosqlite.Row
        # Resolve role_id from is_admin parameter (backward-compatible)
        role_name = "admin" if is_admin else "viewer"
        role_row = await (await db.execute(
            "SELECT id FROM roles WHERE name = ?", (role_name,)
        )).fetchone()
        if not role_row:
            raise ValueError(f"角色 '{role_name}' 不存在，请先初始化默认角色")
        role_id = role_row[0]

        try:
            cursor = await db.execute(
                "INSERT INTO users (username, email, password_hash, role_id, is_admin) VALUES (?, ?, ?, ?, ?)",
                (username.strip(), email.strip(), password_hash, role_id, 1 if is_admin else 0),
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
    allowed_fields = {"username", "email", "role_id", "is_active"}
    security_sensitive_fields = {"is_admin", "password_hash", "failed_login_attempts",
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

    async with aiosqlite.connect(str(DB_PATH)) as db:
        db.row_factory = aiosqlite.Row
        try:
            await db.execute(f"UPDATE users SET {set_clause} WHERE id = ?", values)
            await db.commit()
        except sqlite3.IntegrityError as e:
            raise ValueError(f"更新失败: {e}")

    return await get_user_by_id(user_id)


# ── Role & Permission Helpers ────────────────────────────────

async def get_user_role(user_id: int) -> dict | None:
    """Get the role assigned to a user. Returns role dict or None."""
    import aiosqlite
    async with aiosqlite.connect(str(DB_PATH)) as db:
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
    """Backward-compatible: check if user role is 'admin'."""
    role = await get_user_role(user_id)
    return role is not None and role.get("name") == "admin"


async def delete_user(user_id: int) -> bool:
    """Delete a user."""
    import aiosqlite
    async with aiosqlite.connect(str(DB_PATH)) as db:
        cursor = await db.execute("DELETE FROM users WHERE id = ?", (user_id,))
        await db.commit()
        return cursor.rowcount > 0


async def list_users() -> list[dict]:
    """List all users (admin only)."""
    import aiosqlite
    async with aiosqlite.connect(str(DB_PATH)) as db:
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
    async with aiosqlite.connect(str(DB_PATH)) as db:
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
    async with aiosqlite.connect(str(DB_PATH)) as db:
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
    async with aiosqlite.connect(str(DB_PATH)) as db:
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
        "role": role.get("name") if role else ("admin" if is_admin else "viewer"),
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
        "role": role.get("name") if role else ("admin" if is_admin else "viewer"),
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
