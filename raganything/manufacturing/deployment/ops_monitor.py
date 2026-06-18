"""
运维监控体系 — 可用性告警、响应时间监控、月度巡检。
"""

import json
import logging
import time
from pathlib import Path
from datetime import datetime
from typing import Optional

logger = logging.getLogger(__name__)


class OpsMonitor:
    """运维监控器。"""

    def __init__(self, metrics_dir: str | Path = "./data/manufacturing_kb/metrics"):
        self.metrics_dir = Path(metrics_dir)
        self.metrics_dir.mkdir(parents=True, exist_ok=True)
        self._current_window: list[dict] = []
        self._alerts: list[dict] = []

    # --- 指标收集 ---

    def record_request(self, endpoint: str, response_ms: float,
                       status_code: int = 200) -> None:
        """记录单次请求指标。"""
        self._current_window.append({
            "endpoint": endpoint,
            "response_ms": response_ms,
            "status_code": status_code,
            "timestamp": time.time(),
        })

        # 检查 SLA 违规
        if response_ms > 2000:
            self._alert("high_latency", f"{endpoint} 响应时间 {response_ms:.0f}ms 超过 P95 阈值 2000ms")
        if status_code >= 500:
            self._alert("server_error", f"{endpoint} 返回 {status_code}")

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

    def get_alerts(self, active_only: bool = True) -> list[dict]:
        """获取告警列表。"""
        if active_only:
            return [a for a in self._alerts if not a.get("resolved_at")]
        return list(self._alerts)

    def resolve_alert(self, alert_index: int) -> bool:
        """解决告警。"""
        if 0 <= alert_index < len(self._alerts):
            self._alerts[alert_index]["resolved_at"] = datetime.now().isoformat()
            return True
        return False

    # --- 月度报告 ---

    def generate_monthly_report(self, month: str = "") -> dict:
        """生成月度运维报告。"""
        if not month:
            month = datetime.now().strftime("%Y-%m")

        # 从持久化指标加载
        metrics_file = self.metrics_dir / f"metrics_{month}.json"
        if not metrics_file.exists():
            return {"error": f"未找到 {month} 的指标数据"}

        data = json.loads(metrics_file.read_text(encoding="utf-8"))

        # 计算月度统计
        all_times = []
        error_count = 0
        endpoint_counts: dict[str, int] = {}

        for record in data:
            all_times.append(record["response_ms"])
            if record["status_code"] >= 400:
                error_count += 1
            endpoint_counts[record["endpoint"]] = (
                endpoint_counts.get(record["endpoint"], 0) + 1
            )

        all_times.sort()
        total = len(all_times)

        # 计算可用性
        total_minutes = 30 * 24 * 60  # 月
        downtime_minutes = self._estimate_downtime(data)
        availability = (total_minutes - downtime_minutes) / total_minutes * 100

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
            "alerts_this_month": len(self._alerts),
            "generated_at": datetime.now().isoformat(),
        }

    def save_metrics_snapshot(self) -> str:
        """保存当前窗口指标到磁盘。"""
        month = datetime.now().strftime("%Y-%m")
        metrics_file = self.metrics_dir / f"metrics_{month}.json"

        existing = []
        if metrics_file.exists():
            existing = json.loads(metrics_file.read_text(encoding="utf-8"))

        existing.extend(self._current_window)
        metrics_file.write_text(
            json.dumps(existing, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        self._current_window = []
        return str(metrics_file)

    # --- 健康检查 ---

    def health_check(self, checks: Optional[dict] = None) -> dict:
        """综合健康检查。

        Args:
            checks: 各组件状态 {"qa": bool, "video": bool, ...}

        Returns:
            健康状态报告
        """
        checks = checks or {}
        all_healthy = all(checks.values()) if checks else True

        return {
            "status": "healthy" if all_healthy else "degraded",
            "checks": checks,
            "uptime_seconds": time.time() - self._current_window[0]["timestamp"]
                if self._current_window else 0,
            "active_alerts": len(self.get_alerts(active_only=True)),
            "timestamp": time.time(),
        }

    def _alert(self, alert_type: str, message: str) -> None:
        self._alerts.append({
            "type": alert_type,
            "message": message,
            "created_at": datetime.now().isoformat(),
            "resolved_at": None,
        })
        logger.warning(f"[ALERT] {alert_type}: {message}")

    def _estimate_downtime(self, records: list[dict]) -> int:
        """从记录中估算停机时间（分钟）。"""
        if not records:
            return 0

        downtime = 0
        sorted_records = sorted(records, key=lambda r: r["timestamp"])
        gap_threshold = 60  # 60 秒无记录视为可能停机

        for i in range(1, len(sorted_records)):
            gap = sorted_records[i]["timestamp"] - sorted_records[i - 1]["timestamp"]
            if gap > gap_threshold:
                downtime += gap / 60  # 转为分钟

        return int(downtime)
