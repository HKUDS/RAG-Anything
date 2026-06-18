# -*- coding: utf-8 -*-
"""
RAG-Anything 审计日志服务。

提供管理员用户管理操作的审计日志记录与查询。
日志以后台线程异步写入，不阻塞主请求。
"""

from __future__ import annotations

import json
import sqlite3
import threading
from datetime import datetime
from pathlib import Path
from typing import Optional, Dict, Any, List


class AuditLogger:
    """审计日志记录器 — 后台线程异步写入 SQLite。

    用法:
        audit = AuditLogger("auth.db")
        await audit.log(
            actor_id=1,
            action="user.create",
            target_user_id=2,
            details={"username": "new_user", "role": "editor"},
            ip_address="127.0.0.1",
        )
    """

    def __init__(self, db_path: str = "./auth.db"):
        self._db_path = Path(db_path)
        self._queue: list[Dict[str, Any]] = []
        self._lock = threading.Lock()
        self._flush_interval = 2.0  # 每 2 秒批量写入
        self._running = True
        self._consecutive_failures = 0
        self._max_queue_size = 10000
        self._thread = threading.Thread(target=self._flush_loop, daemon=True)
        self._thread.start()

    def _get_conn(self) -> sqlite3.Connection:
        """获取同步 SQLite 连接（后台线程使用）。"""
        conn = sqlite3.connect(str(self._db_path))
        conn.row_factory = sqlite3.Row
        return conn

    def _flush_loop(self):
        """后台刷新循环。"""
        import time
        while self._running:
            time.sleep(self._flush_interval)
            self._flush()

    def _flush(self):
        """将队列中的日志批量写入数据库。失败时保留条目并记录错误。"""
        with self._lock:
            if not self._queue:
                return
            batch = self._queue[:]
            # NOTE: queue is NOT cleared here — only cleared after successful write

        try:
            conn = self._get_conn()
            for entry in batch:
                conn.execute(
                    """INSERT INTO audit_logs (actor_id, action, target_user_id, details, ip_address)
                       VALUES (?, ?, ?, ?, ?)""",
                    (
                        entry["actor_id"],
                        entry["action"],
                        entry.get("target_user_id"),
                        json.dumps(entry.get("details", {}), ensure_ascii=False),
                        entry.get("ip_address"),
                    ),
                )
            conn.commit()
            conn.close()
            # Only remove successfully flushed entries from queue
            with self._lock:
                for entry in batch:
                    try:
                        self._queue.remove(entry)
                    except ValueError:
                        pass  # already removed by concurrent operation
            self._consecutive_failures = 0
        except Exception as e:
            import sys
            self._consecutive_failures += 1
            print(
                f"[AUDIT] 审计日志写入失败 ({self._consecutive_failures} 次连续失败)，"
                f"将重试 {len(batch)} 条记录: {e}",
                file=sys.stderr,
            )
            if self._consecutive_failures >= 5:
                print(
                    f"[AUDIT] CRITICAL: 审计日志已连续失败 {self._consecutive_failures} 次，"
                    f"审计追踪已中断。请检查数据库状态。",
                    file=sys.stderr,
                )
            try:
                conn.close()
            except Exception:
                pass

    def health_check(self) -> dict:
        """返回审计日志子系统健康状态。"""
        with self._lock:
            queue_depth = len(self._queue)
        return {
            "audit_logger": "healthy" if self._consecutive_failures == 0 else "degraded",
            "queue_depth": queue_depth,
            "consecutive_failures": self._consecutive_failures,
            "max_queue_size": self._max_queue_size,
        }

    async def log(
        self,
        actor_id: int,
        action: str,
        target_user_id: Optional[int] = None,
        details: Optional[Dict[str, Any]] = None,
        ip_address: Optional[str] = None,
    ):
        """记录一条审计日志（非阻塞）。"""
        entry = {
            "actor_id": actor_id,
            "action": action,
            "target_user_id": target_user_id,
            "details": details or {},
            "ip_address": ip_address,
        }
        with self._lock:
            self._queue.append(entry)

    def shutdown(self):
        """关闭审计日志服务，等待队列刷新完成。"""
        self._running = False
        self._flush()
        if self._thread.is_alive():
            self._thread.join(timeout=5.0)


# ── 查询辅助 ────────────────────────────────────────────────

async def query_audit_logs(
    db_path: str,
    page: int = 1,
    page_size: int = 20,
    actor_id: Optional[int] = None,
    action: Optional[str] = None,
) -> Dict[str, Any]:
    """分页查询审计日志。

    Returns:
        {"logs": [...], "total": N, "page": N, "page_size": N, "total_pages": N}
    """
    import aiosqlite

    where_clauses: List[str] = []
    params: list = []

    if actor_id is not None:
        where_clauses.append("actor_id = ?")
        params.append(actor_id)
    if action:
        where_clauses.append("action = ?")
        params.append(action)

    where_sql = " AND ".join(where_clauses)
    if where_sql:
        where_sql = " WHERE " + where_sql

    async with aiosqlite.connect(db_path) as db:
        db.row_factory = aiosqlite.Row

        # 总数
        count_sql = f"SELECT COUNT(*) as cnt FROM audit_logs {where_sql}"
        cursor = await db.execute(count_sql, params)
        total = (await cursor.fetchone())["cnt"]

        # 分页查询（倒序）
        offset = (page - 1) * page_size
        query_sql = f"""
            SELECT * FROM audit_logs
            {where_sql}
            ORDER BY created_at DESC
            LIMIT ? OFFSET ?
        """
        cursor = await db.execute(query_sql, params + [page_size, offset])
        rows = await cursor.fetchall()
        logs = []
        for r in rows:
            log = dict(r)
            try:
                log["details"] = json.loads(log.get("details", "{}"))
            except (json.JSONDecodeError, TypeError):
                log["details"] = {}
            logs.append(log)

    total_pages = max(1, (total + page_size - 1) // page_size)
    return {
        "logs": logs,
        "total": total,
        "page": page,
        "page_size": page_size,
        "total_pages": total_pages,
    }


# ── 全局审计日志实例 ────────────────────────────────────────

_audit_logger: Optional[AuditLogger] = None


def get_audit_logger(db_path: str = "./auth.db") -> AuditLogger:
    """获取或创建全局审计日志实例。"""
    global _audit_logger
    if _audit_logger is None:
        _audit_logger = AuditLogger(db_path)
    return _audit_logger
