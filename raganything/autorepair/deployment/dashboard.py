"""
数据看板 — PG-backed.

Uses PostgreSQL ``dashboard_query_log`` table exclusively.
"""

import json
import logging
from pathlib import Path
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)


async def _pg_pool():
    from raganything.services.pg_state_repo import get_pg_pool
    return get_pg_pool()


class Dashboard:
    """运维数据看板 — PG-backed."""

    def __init__(self, storage_path: str | Path = "./data/autorepair_kb/dashboard"):
        self.storage_path = Path(storage_path)
        self.storage_path.mkdir(parents=True, exist_ok=True)
        self._start_date = datetime.now()

    # ── Data Collection ───────────────────────────────

    async def log_query(self, user_id: str, institution_id: str,
                        query: str, query_type: str = "qa",
                        response_ms: float = 0,
                        kb_name: str = "default") -> None:
        """记录一次查询到 PG。"""
        pool = await _pg_pool()
        async with pool.acquire() as conn:
            await conn.execute(
                """INSERT INTO dashboard_query_log
                   (user_id, institution_id, query, query_type, response_ms, kb_name)
                   VALUES ($1,$2,$3,$4,$5,$6)""",
                user_id, institution_id, query, query_type, response_ms, kb_name,
            )

    # ── Snapshot ──────────────────────────────────────

    async def get_snapshot(self, knowledge_graph_api=None,
                           case_library=None,
                           kb_name: str = None) -> dict:
        """获取当前数据看板快照。"""
        return {
            "kb_stats": await self._get_kb_stats(
                knowledge_graph_api, case_library
            ),
            "usage_stats": await self._get_usage_stats(kb_name=kb_name),
            "top_queries": await self._get_top_queries(10, kb_name=kb_name),
            "user_activity": await self._get_user_activity(kb_name=kb_name),
            "query_trend": await self._get_query_trend(kb_name=kb_name),
            "timestamp": datetime.now().isoformat(),
        }

    # ── Metrics ───────────────────────────────────────

    async def _get_kb_stats(self, graph_api=None, case_lib=None) -> dict:
        stats = {}
        if graph_api:
            summary = graph_api.get_graph_summary()
            stats["knowledge_graph"] = {
                "total_nodes": summary.get("total_nodes", 0),
                "total_edges": summary.get("total_edges", 0),
            }
        if case_lib:
            all_stats = await case_lib.get_statistics()
            stats["process_documents"] = all_stats.get("process_categories", {})
            stats["fault_cases"] = {
                "total_cases": all_stats.get("fault_total", 0),
                "equipment_types": all_stats.get("equipment_types", {}),
                "fault_categories": all_stats.get("fault_categories", {}),
                "severity_distribution": all_stats.get("severity_distribution", {}),
            }
        return stats

    async def _get_usage_stats(self, kb_name: str = None) -> dict:
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

    async def _get_top_queries(self, n: int = 10, kb_name: str = None) -> list[dict]:
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

    async def _get_user_activity(self, kb_name: str = None) -> dict:
        pool = await _pg_pool()
        async with pool.acquire() as conn:
            where = "WHERE kb_name = $1" if kb_name else ""
            params = [kb_name] if kb_name else []

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

    async def _get_query_trend(self, days: int = 7, kb_name: str = None) -> list[dict]:
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
