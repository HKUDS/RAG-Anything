"""
数据看板 — PG-backed (Phase 3 migration).

Primary: PostgreSQL ``dashboard_query_log`` table for query logging
          with SQL aggregation for trend/activity/stats calculations.
Fallback: JSON file (``query_log.json``) when PG not configured.
"""

import json
import logging
from pathlib import Path
from datetime import datetime, timedelta
from collections import Counter

logger = logging.getLogger(__name__)


def _pg_available() -> bool:
    try:
        from raganything.services.pg_state_repo import get_pg_pool
        get_pg_pool()
        return True
    except RuntimeError:
        return False


async def _pg_pool():
    from raganything.services.pg_state_repo import get_pg_pool
    return get_pg_pool()


class Dashboard:
    """运维数据看板 — PG-first with JSON file fallback."""

    def __init__(self, storage_path: str | Path = "./data/manufacturing_kb/dashboard"):
        self.storage_path = Path(storage_path)
        self.storage_path.mkdir(parents=True, exist_ok=True)
        self._query_log: list[dict] = []
        self._start_date = datetime.now()
        self._use_pg: bool | None = None
        if not _pg_available():
            self._load_query_log()

    # ── Data Collection ───────────────────────────────

    async def log_query(self, user_id: str, institution_id: str,
                        query: str, query_type: str = "qa",
                        response_ms: float = 0,
                        kb_name: str = "default") -> None:
        """记录一次查询 — PG direct or file append."""
        if _pg_available():
            pool = await _pg_pool()
            async with pool.acquire() as conn:
                await conn.execute(
                    """INSERT INTO dashboard_query_log
                       (user_id, institution_id, query, query_type, response_ms, kb_name)
                       VALUES ($1,$2,$3,$4,$5,$6)""",
                    user_id, institution_id, query, query_type, response_ms, kb_name,
                )
            return

        self._query_log.append({
            "user_id": user_id, "institution_id": institution_id,
            "query": query, "query_type": query_type,
            "response_ms": response_ms, "kb_name": kb_name,
            "timestamp": datetime.now(),
        })
        self._save_query_log()

    # ── Snapshot ──────────────────────────────────────

    async def get_snapshot(self, knowledge_graph_api=None,
                           process_library=None,
                           fault_case_library=None,
                           kb_name: str = None) -> dict:
        """获取当前数据看板快照。"""
        return {
            "kb_stats": await self._get_kb_stats(
                knowledge_graph_api, process_library, fault_case_library
            ),
            "usage_stats": await self._get_usage_stats(kb_name=kb_name),
            "top_queries": await self._get_top_queries(10, kb_name=kb_name),
            "user_activity": await self._get_user_activity(kb_name=kb_name),
            "query_trend": await self._get_query_trend(kb_name=kb_name),
            "timestamp": datetime.now().isoformat(),
        }

    # ── Metrics ───────────────────────────────────────

    async def _get_kb_stats(self, graph_api=None, process_lib=None, fault_lib=None) -> dict:
        stats = {}
        if graph_api:
            summary = graph_api.get_graph_summary()
            stats["knowledge_graph"] = {
                "total_nodes": summary.get("total_nodes", 0),
                "total_edges": summary.get("total_edges", 0),
            }
        if process_lib:
            stats["process_documents"] = await process_lib.list_by_category()
        if fault_lib:
            stats["fault_cases"] = await fault_lib.get_statistics()
        return stats

    async def _get_usage_stats(self, kb_name: str = None) -> dict:
        if _pg_available():
            pool = await _pg_pool()
            async with pool.acquire() as conn:
                where = "WHERE kb_name = $1" if kb_name else ""
                params = [kb_name] if kb_name else []

                total = await conn.fetchval(
                    f"SELECT count(*) FROM dashboard_query_log {where}", *params)
                today = await conn.fetchval(
                    f"SELECT count(*) FROM dashboard_query_log {where} "
                    f"{'AND' if kb_name else 'WHERE'} created_at::date = CURRENT_DATE",
                    *params)
                week = await conn.fetchval(
                    f"SELECT count(*) FROM dashboard_query_log {where} "
                    f"{'AND' if kb_name else 'WHERE'} created_at >= NOW() - INTERVAL '7 days'",
                    *params)
                month = await conn.fetchval(
                    f"SELECT count(*) FROM dashboard_query_log {where} "
                    f"{'AND' if kb_name else 'WHERE'} created_at >= NOW() - INTERVAL '30 days'",
                    *params)
                avg_ms = await conn.fetchval(
                    f"SELECT coalesce(avg(response_ms), 0) FROM dashboard_query_log {where}",
                    *params)

                type_rows = await conn.fetch(
                    f"SELECT query_type, count(*) as cnt FROM dashboard_query_log {where} "
                    f"GROUP BY query_type", *params)
            return {
                "total_queries": total,
                "today": today, "this_week": week, "this_month": month,
                "by_type": {r["query_type"]: r["cnt"] for r in type_rows},
                "avg_response_ms": round(float(avg_ms), 1),
            }

        # File fallback
        now = datetime.now()
        logs = self._query_log
        if kb_name:
            logs = [q for q in logs if q.get("kb_name", "default") == kb_name]
        today = [q for q in logs if q["timestamp"].date() == now.date()]
        this_week = [q for q in logs if q["timestamp"] >= now - timedelta(days=7)]
        this_month = [q for q in logs if q["timestamp"] >= now - timedelta(days=30)]
        type_counts = Counter(q["query_type"] for q in logs)
        return {
            "total_queries": len(logs),
            "today": len(today), "this_week": len(this_week), "this_month": len(this_month),
            "by_type": dict(type_counts),
            "avg_response_ms": round(
                sum(q.get("response_ms", 0) for q in logs) / max(len(logs), 1), 1
            ),
        }

    async def _get_top_queries(self, n: int = 10, kb_name: str = None) -> list[dict]:
        if _pg_available():
            pool = await _pg_pool()
            async with pool.acquire() as conn:
                where = "WHERE kb_name = $1" if kb_name else ""
                params = [kb_name] if kb_name else []
                rows = await conn.fetch(
                    f"SELECT query, count(*) as cnt FROM dashboard_query_log {where} "
                    f"GROUP BY query ORDER BY cnt DESC LIMIT {n}",
                    *params,
                )
            return [{"query": r["query"], "count": r["cnt"]} for r in rows]

        logs = self._query_log
        if kb_name:
            logs = [q for q in logs if q.get("kb_name", "default") == kb_name]
        query_counter = Counter(q["query"] for q in logs)
        return [{"query": q, "count": c} for q, c in query_counter.most_common(n)]

    async def _get_user_activity(self, kb_name: str = None) -> dict:
        if _pg_available():
            pool = await _pg_pool()
            async with pool.acquire() as conn:
                where = "WHERE kb_name = $1" if kb_name else ""
                params = [kb_name] if kb_name else []

                def _extend_where(base, extra):
                    return f"{base} {'AND' if kb_name else 'WHERE'} {extra}"

                dau = await conn.fetchval(
                    f"SELECT count(DISTINCT user_id) FROM dashboard_query_log {where} "
                    f"{'AND' if kb_name else 'WHERE'} created_at::date = CURRENT_DATE",
                    *params)
                wau = await conn.fetchval(
                    f"SELECT count(DISTINCT user_id) FROM dashboard_query_log {where} "
                    f"{'AND' if kb_name else 'WHERE'} created_at >= NOW() - INTERVAL '7 days'",
                    *params)
                mau = await conn.fetchval(
                    f"SELECT count(DISTINCT user_id) FROM dashboard_query_log {where} "
                    f"{'AND' if kb_name else 'WHERE'} created_at >= NOW() - INTERVAL '30 days'",
                    *params)
                inst = await conn.fetchval(
                    f"SELECT count(DISTINCT institution_id) FROM dashboard_query_log {where} "
                    f"{'AND' if kb_name else 'WHERE'} created_at::date = CURRENT_DATE",
                    *params)
            return {
                "dau": dau, "wau": wau, "mau": mau,
                "active_institutions_today": inst or 0,
                "stickiness": round(dau / mau * 100, 1) if mau else 0,
            }

        # File fallback
        now = datetime.now()
        logs = self._query_log
        if kb_name:
            logs = [q for q in logs if q.get("kb_name", "default") == kb_name]
        active_users_today = set()
        active_institutions_today = set()
        for q in logs:
            if q["timestamp"].date() == now.date():
                active_users_today.add(q["user_id"])
                active_institutions_today.add(q["institution_id"])
        dau = len(active_users_today)
        week_ago = now - timedelta(days=7)
        wau = len(set(q["user_id"] for q in logs if q["timestamp"] >= week_ago))
        month_ago = now - timedelta(days=30)
        mau = len(set(q["user_id"] for q in logs if q["timestamp"] >= month_ago))
        return {
            "dau": dau, "wau": wau, "mau": mau,
            "active_institutions_today": len(active_institutions_today),
            "stickiness": round(dau / mau * 100, 1) if mau else 0,
        }

    async def _get_query_trend(self, days: int = 7, kb_name: str = None) -> list[dict]:
        if _pg_available():
            pool = await _pg_pool()
            async with pool.acquire() as conn:
                where = "WHERE kb_name = $1"
                params = [kb_name] if kb_name else ["default"]
                rows = await conn.fetch(
                    f"""SELECT created_at::date as day, count(*) as cnt
                        FROM dashboard_query_log {where}
                          AND created_at >= CURRENT_DATE - ($2::int || ' days')::INTERVAL
                        GROUP BY day ORDER BY day""",
                    *params, days,
                )
            trend_map = {r["day"].isoformat(): r["cnt"] for r in rows}
            result = []
            for i in range(days):
                day = datetime.now().date() - timedelta(days=days - 1 - i)
                result.append({"date": day.isoformat(), "count": trend_map.get(day.isoformat(), 0)})
            return result

        # File fallback
        now = datetime.now()
        logs = self._query_log
        if kb_name:
            logs = [q for q in logs if q.get("kb_name", "default") == kb_name]
        trend = []
        for i in range(days - 1, -1, -1):
            day = (now - timedelta(days=i)).date()
            count = sum(1 for q in logs if q["timestamp"].date() == day)
            trend.append({"date": day.isoformat(), "count": count})
        return trend

    # ── Export ────────────────────────────────────────

    def export_snapshot(self) -> str:
        """导出看板快照为 JSON 文件。

        Note: When called from an async context, use ``await get_snapshot()``
        directly instead of this synchronous wrapper.
        """
        import asyncio
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None

        if loop is not None:
            # Running inside async context — cannot block. Return empty snapshot.
            logger.warning("export_snapshot called from async context, returning empty snapshot")
            snapshot = {}
        else:
            # No running loop — safe to block
            snapshot = asyncio.run(self.get_snapshot())
        filename = f"dashboard_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        filepath = self.storage_path / filename
        filepath.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2), encoding="utf-8")
        return str(filepath)

    # ── File Fallback ─────────────────────────────────

    def _load_query_log(self) -> None:
        log_path = self.storage_path / "query_log.json"
        if log_path.exists():
            try:
                raw = json.loads(log_path.read_text(encoding="utf-8"))
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
        log_path = self.storage_path / "query_log.json"
        try:
            serializable = []
            for entry in self._query_log[-1000:]:
                item = dict(entry)
                if isinstance(item.get("timestamp"), datetime):
                    item["timestamp"] = item["timestamp"].isoformat()
                serializable.append(item)
            log_path.write_text(
                json.dumps(serializable, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception as e:
            logger.warning(f"Failed to save query log: {e}")
