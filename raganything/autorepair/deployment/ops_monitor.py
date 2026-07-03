"""
运维监控体系 — 可用性告警、响应时间监控、月度巡检。

数据存储: PostgreSQL ``ops_metrics`` + ``ops_alerts`` 表（唯一后端）
"""

import logging
import time
from datetime import datetime
from typing import Optional

logger = logging.getLogger(__name__)


async def _pg_pool():
    from raganything.services.pg_state_repo import get_pg_pool
    return get_pg_pool()


class OpsMonitor:
    """运维监控器 — PG-backed."""

    def __init__(self):
        self._current_window: list[dict] = []

    # --- 指标收集 ---

    def record_request(self, endpoint: str, response_ms: float,
                       status_code: int = 200) -> None:
        """记录单次请求指标到内存窗口。"""
        self._current_window.append({
            "endpoint": endpoint,
            "response_ms": response_ms,
            "status_code": status_code,
            "timestamp": time.time(),
        })

        # 检查 SLA 违规 — 内存告警列表
        if response_ms > 2000:
            self._alert_sync("high_latency", f"{endpoint} 响应时间 {response_ms:.0f}ms 超过 P95 阈值 2000ms")
        if status_code >= 500:
            self._alert_sync("server_error", f"{endpoint} 返回 {status_code}")

    def get_current_metrics(self) -> dict:
        """获取当前窗口的性能指标。"""
        if not self._current_window:
            return {"status": "no_data"}

        times = sorted(r["response_ms"] for r in self._current_window)
        total = len(times)
        errors = sum(1 for r in self._current_window if r["status_code"] >= 400)

        return {
            "total_requests": total,
            "error_count": errors,
            "error_rate": round(errors / total * 100, 2) if total else 0,
            "p50_ms": round(times[total // 2], 2) if total else 0,
            "p95_ms": round(times[int(total * 0.95)], 2) if total else 0,
            "p99_ms": round(times[int(total * 0.99)], 2) if total else 0,
            "min_ms": round(times[0], 2) if total else 0,
            "max_ms": round(times[-1], 2) if total else 0,
            "window_seconds": round(time.time() - self._current_window[0]["timestamp"], 0) if total else 0,
        }

    async def get_alerts(self, active_only: bool = True) -> list[dict]:
        """获取告警列表 from PG。"""
        pool = await _pg_pool()
        async with pool.acquire() as conn:
            if active_only:
                rows = await conn.fetch(
                    """SELECT id, alert_type, message, created_at, resolved_at
                       FROM ops_alerts WHERE resolved_at IS NULL
                       ORDER BY created_at DESC""",
                )
            else:
                rows = await conn.fetch(
                    """SELECT id, alert_type, message, created_at, resolved_at
                       FROM ops_alerts ORDER BY created_at DESC""",
                )
        return [dict(r) for r in rows]

    async def resolve_alert(self, alert_id: int) -> bool:
        """解决告警（更新 PG）。"""
        pool = await _pg_pool()
        async with pool.acquire() as conn:
            result = await conn.execute(
                "UPDATE ops_alerts SET resolved_at = $2 WHERE id = $1 AND resolved_at IS NULL",
                alert_id, datetime.now(),
            )
        return "UPDATE 1" in result

    # --- 月度报告 ---

    async def generate_monthly_report(self, month: str = "") -> dict:
        """生成月度运维报告 from PG ops_metrics。"""
        if not month:
            month = datetime.now().strftime("%Y-%m")

        pool = await _pg_pool()
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                """SELECT endpoint, response_ms, status_code
                   FROM ops_metrics WHERE month = $1""",
                month,
            )

        if not rows:
            return {"error": f"未找到 {month} 的指标数据"}

        # 计算月度统计
        all_times = []
        error_count = 0
        endpoint_counts: dict[str, int] = {}

        for r in rows:
            all_times.append(r["response_ms"])
            if r["status_code"] >= 400:
                error_count += 1
            endpoint_counts[r["endpoint"]] = (
                endpoint_counts.get(r["endpoint"], 0) + 1
            )

        all_times.sort()
        total = len(all_times)

        # 计算可用性
        total_minutes = 30 * 24 * 60  # 月
        downtime_minutes = self._estimate_downtime(rows)
        availability = (total_minutes - downtime_minutes) / total_minutes * 100

        # 当月告警数
        alert_count = await conn.fetchval(
            """SELECT count(*) FROM ops_alerts
               WHERE created_at::date >= $1 AND created_at::date < $2""",
            f"{month}-01", f"{month}-31",
        )

        return {
            "month": month,
            "availability_pct": round(availability, 2),
            "sla_compliant": availability >= 99.5,
            "total_requests": total,
            "error_count": error_count,
            "error_rate_pct": round(error_count / total * 100, 2) if total else 0,
            "p50_ms": round(all_times[total // 2], 2) if total else 0,
            "p95_ms": round(all_times[int(total * 0.95)], 2) if total else 0,
            "top_endpoints": sorted(
                endpoint_counts.items(), key=lambda x: x[1], reverse=True
            )[:5],
            "alerts_this_month": alert_count or 0,
            "generated_at": datetime.now().isoformat(),
        }

    async def save_metrics_snapshot(self) -> str:
        """保存当前窗口指标到 PG。"""
        month = datetime.now().strftime("%Y-%m")

        if not self._current_window:
            return month

        pool = await _pg_pool()
        async with pool.acquire() as conn:
            # Batch insert all metrics in current window
            await conn.executemany(
                """INSERT INTO ops_metrics (endpoint, response_ms, status_code, month)
                   VALUES ($1, $2, $3, $4)""",
                [(r["endpoint"], r["response_ms"], r["status_code"], month)
                 for r in self._current_window],
            )

        count = len(self._current_window)
        self._current_window = []
        logger.info("保存 %d 条指标到 PG (月份 %s)", count, month)
        return month

    # --- 健康检查 ---

    async def health_check(self, checks: Optional[dict] = None) -> dict:
        """综合健康检查。

        Args:
            checks: 各组件状态 {"qa": bool, "video": bool, ...}

        Returns:
            健康状态报告
        """
        checks = checks or {}
        all_healthy = all(checks.values()) if checks else True

        active_alerts = await self.get_alerts(active_only=True)

        return {
            "status": "healthy" if all_healthy else "degraded",
            "checks": checks,
            "uptime_seconds": time.time() - self._current_window[0]["timestamp"]
                if self._current_window else 0,
            "active_alerts": len(active_alerts),
            "timestamp": time.time(),
        }

    async def _alert_async(self, alert_type: str, message: str) -> None:
        """写入告警到 PG。"""
        pool = await _pg_pool()
        async with pool.acquire() as conn:
            await conn.execute(
                """INSERT INTO ops_alerts (alert_type, message)
                   VALUES ($1, $2)""",
                alert_type, message,
            )
        logger.warning(f"[ALERT] {alert_type}: {message}")

    def _alert_sync(self, alert_type: str, message: str) -> None:
        """同步告警 — 仅追加到日志，PG 写入需显式调用 _alert_async。"""
        logger.warning(f"[ALERT] {alert_type}: {message}")

    @staticmethod
    def _estimate_downtime(records: list) -> int:
        """从记录中估算停机时间（分钟）。"""
        if not records:
            return 0

        downtime = 0
        sorted_records = sorted(records, key=lambda r: r["timestamp"] if isinstance(r, dict) else r["created_at"])
        gap_threshold = 60  # 60 秒无记录视为可能停机

        for i in range(1, len(sorted_records)):
            r1 = sorted_records[i - 1]
            r2 = sorted_records[i]
            t1 = r1["timestamp"] if isinstance(r1, dict) else r1["created_at"].timestamp()
            t2 = r2["timestamp"] if isinstance(r2, dict) else r2["created_at"].timestamp()
            gap = t2 - t1
            if gap > gap_threshold:
                downtime += gap / 60  # 转为分钟

        return int(downtime)
