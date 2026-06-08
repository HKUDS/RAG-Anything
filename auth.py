"""
RAG-Anything 认证模块
功能：SQLite 用户存储、bcrypt 密码哈希、JWT Token 签发与验证
"""
import os
import sqlite3
import secrets
import hashlib
import time
from datetime import datetime, timedelta
from pathlib import Path

import jwt as pyjwt
from passlib.context import CryptContext

# ── 密码哈希配置 ──────────────────────────────────
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# ── JWT 配置 ──────────────────────────────────────
SECRET_KEY = os.getenv("JWT_SECRET", secrets.token_hex(32))
JWT_EXPIRY_HOURS = int(os.getenv("JWT_EXPIRY_HOURS", "24"))
ALGORITHM = "HS256"

# ── 数据库路径 ────────────────────────────────────
DB_PATH = Path(os.getenv("AUTH_DB_PATH", "./auth.db"))

# ── 默认管理员（首次启动时创建） ─────────────────
DEFAULT_ADMIN_USERNAME = os.getenv("DEFAULT_ADMIN_USERNAME", "admin")
DEFAULT_ADMIN_EMAIL = os.getenv("DEFAULT_ADMIN_EMAIL", "admin@raganything.local")
DEFAULT_ADMIN_PASSWORD = os.getenv("DEFAULT_ADMIN_PASSWORD", "admin123")


def _get_conn() -> sqlite3.Connection:
    """获取 SQLite 连接（非异步，用于简单操作）"""
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=5000")
    return conn


async def init_db():
    """初始化数据库：创建 users 表 + 默认管理员"""
    import aiosqlite

    async with aiosqlite.connect(str(DB_PATH)) as db:
        db.row_factory = aiosqlite.Row
        await db.execute("PRAGMA journal_mode=WAL")
        await db.execute("PRAGMA busy_timeout=5000")
        await db.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                username    TEXT UNIQUE NOT NULL,
                email       TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL,
                is_admin    INTEGER DEFAULT 0,
                is_active   INTEGER DEFAULT 1,
                created_at  TEXT DEFAULT (datetime('now','localtime')),
                updated_at  TEXT DEFAULT (datetime('now','localtime'))
            )
        """)
        await db.commit()

    # 确保默认管理员存在
    admin = await get_user_by_username(DEFAULT_ADMIN_USERNAME)
    if not admin:
        await create_user(DEFAULT_ADMIN_USERNAME, DEFAULT_ADMIN_EMAIL, DEFAULT_ADMIN_PASSWORD, is_admin=True)
        print(f"[AUTH] 默认管理员已创建: {DEFAULT_ADMIN_USERNAME}")
    else:
        print(f"[AUTH] 管理员账号已存在: {DEFAULT_ADMIN_USERNAME}")

    print(f"[AUTH] 数据库已初始化: {DB_PATH}")


# ── 用户 CRUD ─────────────────────────────────────

async def get_user_by_username(username: str) -> dict | None:
    """按用户名查询用户"""
    import aiosqlite
    async with aiosqlite.connect(str(DB_PATH)) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute("SELECT * FROM users WHERE username = ?", (username,))
        row = await cursor.fetchone()
        return dict(row) if row else None


async def get_user_by_id(user_id: int) -> dict | None:
    """按 ID 查询用户"""
    import aiosqlite
    async with aiosqlite.connect(str(DB_PATH)) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute("SELECT * FROM users WHERE id = ?", (user_id,))
        row = await cursor.fetchone()
        return dict(row) if row else None


async def create_user(username: str, email: str, password: str, is_admin: bool = False) -> dict:
    """创建新用户，返回用户字典（不含密码哈希）"""
    import aiosqlite

    # 验证
    if len(password) < 6:
        raise ValueError("密码至少需要 6 位")
    if len(username) < 2:
        raise ValueError("用户名至少需要 2 个字符")

    password_hash = pwd_context.hash(password)

    async with aiosqlite.connect(str(DB_PATH)) as db:
        db.row_factory = aiosqlite.Row
        try:
            cursor = await db.execute(
                "INSERT INTO users (username, email, password_hash, is_admin) VALUES (?, ?, ?, ?)",
                (username.strip(), email.strip(), password_hash, 1 if is_admin else 0),
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
    """更新用户信息（管理员用）"""
    import aiosqlite

    allowed_fields = {"username", "email", "is_admin", "is_active"}
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


async def delete_user(user_id: int) -> bool:
    """删除用户"""
    import aiosqlite
    async with aiosqlite.connect(str(DB_PATH)) as db:
        cursor = await db.execute("DELETE FROM users WHERE id = ?", (user_id,))
        await db.commit()
        return cursor.rowcount > 0


async def list_users() -> list[dict]:
    """列出所有用户（管理员用）"""
    import aiosqlite
    async with aiosqlite.connect(str(DB_PATH)) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute("SELECT * FROM users ORDER BY id")
        rows = await cursor.fetchall()
        return [_sanitize_user(dict(r)) for r in rows]


# ── 密码工具 ──────────────────────────────────────

def verify_password(plain_password: str, hashed_password: str) -> bool:
    """验证密码"""
    return pwd_context.verify(plain_password, hashed_password)


# ── JWT 工具 ──────────────────────────────────────

def create_token(user_id: int, username: str, is_admin: bool) -> str:
    """签发 JWT Token"""
    payload = {
        "user_id": user_id,
        "username": username,
        "is_admin": is_admin,
        "exp": datetime.utcnow() + timedelta(hours=JWT_EXPIRY_HOURS),
        "iat": datetime.utcnow(),
    }
    return pyjwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)


def decode_token(token: str) -> dict | None:
    """验证并解码 JWT Token，失败返回 None"""
    try:
        payload = pyjwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        return payload
    except pyjwt.ExpiredSignatureError:
        return None
    except pyjwt.InvalidTokenError:
        return None


# ── 辅助函数 ──────────────────────────────────────

def _sanitize_user(user: dict | None) -> dict | None:
    """移除 password_hash 字段，安全返回用户信息"""
    if user is None:
        return None
    return {k: v for k, v in user.items() if k != "password_hash"}


# ── 同步辅助（用于简单脚本） ─────────────────────

def init_db_sync():
    """同步版本，用于简单初始化"""
    conn = _get_conn()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            username    TEXT UNIQUE NOT NULL,
            email       TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            is_admin    INTEGER DEFAULT 0,
            is_active   INTEGER DEFAULT 1,
            created_at  TEXT DEFAULT (datetime('now','localtime')),
            updated_at  TEXT DEFAULT (datetime('now','localtime'))
        )
    """)
    conn.commit()
    conn.close()
    print(f"[AUTH] 数据库已初始化: {DB_PATH}")
