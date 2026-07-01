"""
故障案例库 — PG-backed.

Uses PostgreSQL ``fault_cases`` table exclusively.
"""

import json
import logging
from pathlib import Path
from typing import Optional

from ..knowledge_graph.models import FaultCase

logger = logging.getLogger(__name__)


async def _pg_pool():
    from raganything.services.pg_state_repo import get_pg_pool
    return get_pg_pool()


_PG_LIST_SQL = """SELECT id, title, equipment_type, fault_category,
    phenomenon, root_cause, severity, occurrence_count, created_at
    FROM fault_cases ORDER BY created_at DESC"""

_PG_INSERT_SQL = """INSERT INTO fault_cases
    (id, title, equipment_type, fault_category, phenomenon, root_cause,
     troubleshooting_steps, preventive_measures, severity, occurrence_count)
    VALUES ($1,$2,$3,$4,$5,$6,$7::jsonb,$8::jsonb,$9,$10) RETURNING *"""

_PG_UPDATE_SQL = """UPDATE fault_cases SET
    title=$1, equipment_type=$2, fault_category=$3, phenomenon=$4,
    root_cause=$5, troubleshooting_steps=$6::jsonb, preventive_measures=$7::jsonb,
    severity=$8, occurrence_count=$9, updated_at=NOW()
    WHERE id=$10 RETURNING *"""


class FaultCaseLibrary:
    """设备故障案例库 — PG-backed."""

    def __init__(self, storage_path: str | Path = "./data/manufacturing_kb/fault_cases",
                 embedding_client=None):
        self.storage_path = Path(storage_path)
        self.storage_path.mkdir(parents=True, exist_ok=True)
        self.embedding_client = embedding_client

    # ── CRUD ──────────────────────────────────────────

    async def add_case(self, case: FaultCase) -> str:
        """添加故障案例。验证必填字段后入库。"""
        if not self._validate_case(case):
            raise ValueError(f"故障案例 {case.title} 缺少必填字段")

        pool = await _pg_pool()
        async with pool.acquire() as conn:
            await conn.execute(
                _PG_INSERT_SQL,
                case.id, case.title, case.equipment_type, case.fault_category,
                case.phenomenon, case.root_cause,
                json.dumps(case.troubleshooting_steps, ensure_ascii=False),
                json.dumps(case.preventive_measures, ensure_ascii=False),
                case.severity, case.occurrence_count,
            )
        return case.id

    async def search(self, query: str, top_k: int = 5) -> list[dict]:
        """检索故障案例 (PG ILIKE text search)。"""
        return await self._pg_text_search(query, top_k)

    async def _pg_text_search(self, query: str, top_k: int) -> list[dict]:
        """PG text search on fault cases (ILIKE)."""
        pool = await _pg_pool()
        q = f"%{query}%"
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                """SELECT id, title, equipment_type, fault_category,
                   phenomenon, root_cause, troubleshooting_steps, severity
                   FROM fault_cases
                   WHERE title ILIKE $1 OR phenomenon ILIKE $1
                      OR root_cause ILIKE $1 OR fault_category ILIKE $1
                   ORDER BY created_at DESC LIMIT $2""",
                q, top_k,
            )
        results = []
        for r in rows:
            steps = r["troubleshooting_steps"]
            if isinstance(steps, str):
                try:
                    steps = json.loads(steps)
                except Exception:
                    steps = []
            results.append({
                "id": r["id"], "title": r["title"],
                "equipment_type": r["equipment_type"],
                "fault_category": r["fault_category"],
                "phenomenon": r["phenomenon"],
                "root_cause": r["root_cause"],
                "troubleshooting_steps": steps,
                "severity": r["severity"],
                "score": 1.0,
            })
        return results

    async def search_by_equipment(self, equipment_type: str) -> list[FaultCase]:
        """按设备类型检索。"""
        pool = await _pg_pool()
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT * FROM fault_cases WHERE equipment_type = $1",
                equipment_type,
            )
        return [self._row_to_case(dict(r)) for r in rows]

    async def search_by_category(self, fault_category: str) -> list[FaultCase]:
        """按故障类别检索。"""
        pool = await _pg_pool()
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT * FROM fault_cases WHERE fault_category = $1",
                fault_category,
            )
        return [self._row_to_case(dict(r)) for r in rows]

    async def get_case(self, case_id: str) -> Optional[FaultCase]:
        pool = await _pg_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT * FROM fault_cases WHERE id = $1", case_id,
            )
        return self._row_to_case(dict(row)) if row else None

    async def update_case(self, case_id: str, updates: dict) -> bool:
        """更新故障案例。返回是否成功。"""
        pool = await _pg_pool()
        async with pool.acquire() as conn:
            existing = await conn.fetchrow(
                "SELECT * FROM fault_cases WHERE id = $1", case_id,
            )
            if not existing:
                return False
            row = await conn.fetchrow(
                _PG_UPDATE_SQL,
                updates.get("title", existing["title"]),
                updates.get("equipment_type", existing["equipment_type"]),
                updates.get("fault_category", existing["fault_category"]),
                updates.get("phenomenon", existing["phenomenon"]),
                updates.get("root_cause", existing["root_cause"]),
                json.dumps(updates.get("troubleshooting_steps",
                            existing["troubleshooting_steps"] or []),
                           ensure_ascii=False),
                json.dumps(updates.get("preventive_measures",
                            existing["preventive_measures"] or []),
                           ensure_ascii=False),
                updates.get("severity", existing["severity"]),
                updates.get("occurrence_count", existing["occurrence_count"]),
                case_id,
            )
        return row is not None

    async def delete_case(self, case_id: str) -> bool:
        """删除故障案例。返回是否成功。"""
        pool = await _pg_pool()
        async with pool.acquire() as conn:
            result = await conn.execute(
                "DELETE FROM fault_cases WHERE id = $1", case_id,
            )
        return result and "DELETE 0" not in result

    async def get_statistics(self) -> dict:
        """获取故障案例库统计信息。"""
        pool = await _pg_pool()
        async with pool.acquire() as conn:
            total = await conn.fetchval("SELECT count(*) FROM fault_cases")
            eq_rows = await conn.fetch(
                "SELECT equipment_type, count(*) as cnt FROM fault_cases "
                "GROUP BY equipment_type"
            )
            cat_rows = await conn.fetch(
                "SELECT fault_category, count(*) as cnt FROM fault_cases "
                "GROUP BY fault_category"
            )
            sev_rows = await conn.fetch(
                "SELECT severity, count(*) as cnt FROM fault_cases "
                "GROUP BY severity"
            )
        return {
            "total_cases": total,
            "equipment_types": {r["equipment_type"]: r["cnt"] for r in eq_rows},
            "fault_categories": {r["fault_category"]: r["cnt"] for r in cat_rows},
            "severity_distribution": {r["severity"]: r["cnt"] for r in sev_rows},
        }

    # ── Internal ──────────────────────────────────────

    def _validate_case(self, case: FaultCase) -> bool:
        return bool(case.phenomenon and case.root_cause and case.troubleshooting_steps)

    def _row_to_case(self, row: dict) -> FaultCase:
        """Convert PG row to FaultCase model."""
        steps = row.get("troubleshooting_steps", [])
        if isinstance(steps, str):
            try:
                steps = json.loads(steps)
            except Exception:
                steps = []
        measures = row.get("preventive_measures", [])
        if isinstance(measures, str):
            try:
                measures = json.loads(measures)
            except Exception:
                measures = []
        return FaultCase(
            id=row["id"], title=row["title"],
            equipment_type=row["equipment_type"],
            fault_category=row["fault_category"],
            phenomenon=row["phenomenon"], root_cause=row["root_cause"],
            troubleshooting_steps=steps,
            preventive_measures=measures,
            severity=row.get("severity", "medium"),
            occurrence_count=row.get("occurrence_count", 0),
        )


    @staticmethod
    def _cosine(a: list[float], b: list[float]) -> float:
        dot = sum(x * y for x, y in zip(a, b))
        na = sum(x ** 2 for x in a) ** 0.5
        nb = sum(y ** 2 for y in b) ** 0.5
        return dot / (na * nb) if na and nb else 0.0
