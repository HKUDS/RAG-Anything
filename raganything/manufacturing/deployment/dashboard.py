"""
数据看板 — 知识库规模统计、智能体使用次数、热门查询、用户活跃度。
"""

import json
import logging
from pathlib import Path
from datetime import datetime, timedelta
from collections import Counter
from typing import Optional

logger = logging.getLogger(__name__)


class Dashboard:
    """运维数据看板。"""

    def __init__(self, storage_path: str | Path = "./data/manufacturing_kb/dashboard"):
        self.storage_path = Path(storage_path)
        self.storage_path.mkdir(parents=True, exist_ok=True)
        self._query_log: list[dict] = []
        self._start_date = datetime.now()
        self._load_query_log()

    # --- 数据收集 ---

    def log_query(self, user_id: str, institution_id: str,
                  query: str, query_type: str = "qa",
                  response_ms: float = 0) -> None:
        """记录一次查询。"""
        self._query_log.append({
            "user_id": user_id,
            "institution_id": institution_id,
            "query": query,
            "query_type": query_type,
            "response_ms": response_ms,
            "timestamp": datetime.now(),
        })
        self._save_query_log()

    def _load_query_log(self) -> None:
        """从磁盘加载查询日志。"""
        log_path = self.storage_path / "query_log.json"
        if log_path.exists():
            try:
                raw = json.loads(log_path.read_text(encoding="utf-8"))
                # 将 timestamp 字符串转回 datetime 用于后续计算
                for entry in raw:
                    if isinstance(entry.get("timestamp"), str):
                        try:
                            entry["timestamp"] = datetime.fromisoformat(entry["timestamp"])
                        except ValueError:
                            entry["timestamp"] = datetime.now()
                self._query_log = raw
                logger.info(f"Loaded {len(self._query_log)} query log entries")
            except Exception as e:
                logger.warning(f"Failed to load query log: {e}")

    def _save_query_log(self) -> None:
        """持久化查询日志到磁盘。"""
        log_path = self.storage_path / "query_log.json"
        try:
            # 序列化 datetime 为 ISO 字符串
            serializable = []
            for entry in self._query_log[-1000:]:
                item = dict(entry)
                if isinstance(item.get("timestamp"), datetime):
                    item["timestamp"] = item["timestamp"].isoformat()
                serializable.append(item)
            log_path.write_text(
                json.dumps(serializable, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except Exception as e:
            logger.warning(f"Failed to save query log: {e}")

    def get_snapshot(self,
                     knowledge_graph_api=None,
                     process_library=None,
                     fault_case_library=None) -> dict:
        """获取当前数据看板快照。

        Returns:
            看板数据结构 (供前端渲染):
            {
                "kb_stats": {...},
                "usage_stats": {...},
                "top_queries": [...],
                "user_activity": {...},
                "timestamp": "..."
            }
        """
        return {
            "kb_stats": self._get_kb_stats(
                knowledge_graph_api, process_library, fault_case_library
            ),
            "usage_stats": self._get_usage_stats(),
            "top_queries": self._get_top_queries(10),
            "user_activity": self._get_user_activity(),
            "query_trend": self._get_query_trend(),
            "timestamp": datetime.now().isoformat(),
        }

    # --- 各指标获取 ---

    def _get_kb_stats(self, graph_api=None,
                      process_lib=None,
                      fault_lib=None) -> dict:
        """知识库规模统计。"""
        stats = {}

        if graph_api:
            summary = graph_api.get_graph_summary()
            stats["knowledge_graph"] = {
                "total_nodes": summary.get("total_nodes", 0),
                "total_edges": summary.get("total_edges", 0),
            }

        if process_lib:
            stats["process_documents"] = process_lib.list_by_category()

        if fault_lib:
            stats["fault_cases"] = fault_lib.get_statistics()

        return stats

    def _get_usage_stats(self) -> dict:
        """使用统计。"""
        now = datetime.now()

        # 按时间范围分类
        today = [q for q in self._query_log
                 if q["timestamp"].date() == now.date()]
        this_week = [q for q in self._query_log
                     if q["timestamp"] >= now - timedelta(days=7)]
        this_month = [q for q in self._query_log
                      if q["timestamp"] >= now - timedelta(days=30)]

        # 按类型统计
        type_counts = Counter(q["query_type"] for q in self._query_log)

        return {
            "total_queries": len(self._query_log),
            "today": len(today),
            "this_week": len(this_week),
            "this_month": len(this_month),
            "by_type": dict(type_counts),
            "avg_response_ms": round(
                sum(q.get("response_ms", 0) for q in self._query_log)
                / max(len(self._query_log), 1), 1
            ),
        }

    def _get_top_queries(self, n: int = 10) -> list[dict]:
        """热门查询 Top-N。"""
        query_counter = Counter(q["query"] for q in self._query_log)
        return [
            {"query": q, "count": c}
            for q, c in query_counter.most_common(n)
        ]

    def _get_user_activity(self) -> dict:
        """用户活跃度。"""
        now = datetime.now()
        active_users_today = set()
        active_institutions_today = set()

        for q in self._query_log:
            if q["timestamp"].date() == now.date():
                active_users_today.add(q["user_id"])
                active_institutions_today.add(q["institution_id"])

        # 日活/周活/月活
        dau = len(active_users_today)

        week_ago = now - timedelta(days=7)
        wau = len(set(
            q["user_id"] for q in self._query_log
            if q["timestamp"] >= week_ago
        ))

        month_ago = now - timedelta(days=30)
        mau = len(set(
            q["user_id"] for q in self._query_log
            if q["timestamp"] >= month_ago
        ))

        return {
            "dau": dau,
            "wau": wau,
            "mau": mau,
            "active_institutions_today": len(active_institutions_today),
            "stickiness": round(dau / mau * 100, 1) if mau else 0,
        }

    def _get_query_trend(self, days: int = 7) -> list[dict]:
        """最近 N 天的查询趋势。"""
        now = datetime.now()
        trend = []

        for i in range(days - 1, -1, -1):
            day = (now - timedelta(days=i)).date()
            count = sum(
                1 for q in self._query_log
                if q["timestamp"].date() == day
            )
            trend.append({"date": day.isoformat(), "count": count})

        return trend

    def export_snapshot(self) -> str:
        """导出看板快照为 JSON 文件。"""
        snapshot = self.get_snapshot()
        filename = f"dashboard_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        filepath = self.storage_path / filename
        filepath.write_text(
            json.dumps(snapshot, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return str(filepath)
