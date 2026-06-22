# -*- coding: utf-8 -*-
"""
RAG-Anything Token 黑名单服务。

内存缓存 + SQLite 持久化，用于 Logout 时撤销 Access Token 和 Refresh Token。
重启后通过 SQLite 恢复撤销状态，多 Worker 共享同一 DB 保证一致性。
"""

from __future__ import annotations

import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Set

# ── DB Path ──────────────────────────────────────────────────

import os as _os

_DB_PATH = Path(_os.getenv("AUTH_DB_PATH", "auth.db"))


def set_blacklist_db_path(db_path: str):
    """Set the database path for persistent token blacklist storage."""
    global _DB_PATH
    _DB_PATH = Path(db_path)


class TokenBlacklist:
    """Token 黑名单 — 内存缓存 + SQLite 持久化，线程安全。

    存储 JWT ID (jti) 及其过期时间。每次操作时惰性清理已过期条目。
    撤销操作同时写入内存和 SQLite；启动时从 SQLite 恢复。

    用法:
        blacklist = TokenBlacklist()
        blacklist.revoke("jti-abc123", expires_at=datetime(...))
        if blacklist.is_revoked("jti-abc123"):
            raise HTTPException(401)
    """

    def __init__(self):
        self._entries: dict[str, datetime] = {}  # jti -> expiry_time (memory cache)
        self._refresh_family: dict[str, set[str]] = {}  # family_id -> set of jtis
        self._lock = threading.Lock()
        self._load_persisted()

    def _get_conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(_DB_PATH))
        conn.row_factory = sqlite3.Row
        return conn

    def _load_persisted(self):
        """从 SQLite 加载未过期的撤销条目到内存缓存。"""
        try:
            conn = self._get_conn()
            rows = conn.execute(
                "SELECT jti, expires_at FROM token_revocations WHERE expires_at > ?",
                (datetime.now(timezone.utc).isoformat(),),
            ).fetchall()
            for row in rows:
                try:
                    exp = datetime.fromisoformat(row["expires_at"])
                    self._entries[row["jti"]] = exp
                except ValueError:
                    pass
            conn.close()
        except sqlite3.OperationalError:
            # Table may not exist yet (first startup before init_db)
            pass

    def _persist_revoke(self, jti: str, expires_at: datetime):
        """Write revocation to SQLite synchronously (ensures durability before return)."""
        try:
            conn = self._get_conn()
            conn.execute(
                "INSERT OR REPLACE INTO token_revocations (jti, expires_at) VALUES (?, ?)",
                (jti, expires_at.isoformat()),
            )
            conn.commit()
            conn.close()
        except Exception:
            pass

    def revoke(self, jti: str, expires_at: datetime):
        """撤销一个 Token（内存 + 持久化）。

        Args:
            jti: Token 的唯一 ID
            expires_at: Token 的过期时间（过期后自动从黑名单移除）
        """
        with self._lock:
            self._entries[jti] = expires_at
            self._cleanup()
        self._persist_revoke(jti, expires_at)

    def revoke_refresh_family(self, family_id: str):
        """撤销与某个 refresh token family 关联的所有 token（防重放攻击）。

        Args:
            family_id: 用户关联的 refresh family ID
        """
        with self._lock:
            jtis = self._refresh_family.pop(family_id, set())
            for jti in jtis:
                # 保留在 entries 中直到过期
                if jti not in self._entries:
                    self._entries[jti] = datetime.max.replace(tzinfo=timezone.utc)
                    self._persist_revoke(jti, datetime.max.replace(tzinfo=timezone.utc))

    def register_refresh_family(self, family_id: str, jti: str):
        """注册一个 refresh token 到 family。"""
        with self._lock:
            if family_id not in self._refresh_family:
                self._refresh_family[family_id] = set()
            self._refresh_family[family_id].add(jti)

    def is_revoked(self, jti: str) -> bool:
        """检查 Token 是否已被撤销。"""
        with self._lock:
            self._cleanup()
            if jti in self._entries:
                return True
        # Fallback: check SQLite directly (for cross-worker consistency)
        try:
            conn = self._get_conn()
            row = conn.execute(
                "SELECT 1 FROM token_revocations WHERE jti = ? AND expires_at > ?",
                (jti, datetime.now(timezone.utc).isoformat()),
            ).fetchone()
            conn.close()
            if row:
                with self._lock:
                    self._entries[jti] = datetime.max.replace(tzinfo=timezone.utc)
                return True
        except sqlite3.OperationalError:
            pass
        return False

    def _cleanup(self):
        """惰性清理：移除已过期的黑名单条目（内存 + SQLite）。"""
        now = datetime.now(timezone.utc)
        expired = [
            jti for jti, exp in self._entries.items()
            if exp.replace(tzinfo=timezone.utc) < now
        ]
        for jti in expired:
            del self._entries[jti]
        # Clean SQLite expired entries periodically
        if expired:
            try:
                conn = self._get_conn()
                conn.execute(
                    "DELETE FROM token_revocations WHERE expires_at < ?",
                    (now.isoformat(),),
                )
                conn.commit()
                conn.close()
            except sqlite3.OperationalError:
                pass


# ── 全局实例 ────────────────────────────────────────────────

_token_blacklist: TokenBlacklist | None = None


def get_token_blacklist() -> TokenBlacklist:
    """获取或创建全局 Token 黑名单实例。"""
    global _token_blacklist
    if _token_blacklist is None:
        _token_blacklist = TokenBlacklist()
    return _token_blacklist
