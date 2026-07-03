"""
统一案例库 — PG-backed.

合并 f故障案例库 + 维修工艺库 为统一的 ``cases`` 表，
通过 ``case_type`` 字段区分案例类型 ('fault' | 'process')。
"""

import json
import logging
import re
from pathlib import Path
from datetime import datetime
from typing import Optional

from ..knowledge_graph.models import Case

logger = logging.getLogger(__name__)

# 工艺类型分类关键词 (from process_library.py)
PROCESS_CATEGORIES = {
    "machining": ["车削", "铣削", "磨削", "钻孔", "镗削", "切削", "加工中心"],
    "welding": ["焊接", "电弧焊", "气焊", "激光焊", "钎焊", "焊缝"],
    "assembly": ["装配", "组装", "配合", "间隙", "过盈", "紧固"],
    "inspection": ["检测", "测量", "检验", "探伤", "三坐标", "公差"],
    "heat_treatment": ["热处理", "淬火", "回火", "退火", "正火", "渗碳"],
    "casting": ["铸造", "浇注", "砂型", "熔模", "压铸"],
    "forming": ["冲压", "锻造", "挤压", "拉拔", "轧制"],
}

# 工艺参数提取模式 (from process_library.py)
PARAM_PATTERNS = [
    re.compile(r"([一-龥]+参数|[A-Za-z]+)\s*[：:]\s*([\d.]+)\s*([一-龥A-Za-z/%℃]+)"),
    re.compile(r"([\d.]+)\s*-\s*([\d.]+)\s*mm"),
    re.compile(r"转速[：:]\s*(\d+)\s*rpm"),
    re.compile(r"进给[：:]\s*([\d.]+)\s*mm"),
]

# ── SQL templates ──────────────────────────────────────

_CASE_INSERT_SQL = """INSERT INTO cases
    (id, title, case_type,
     equipment_type, fault_category, phenomenon, root_cause,
     troubleshooting_steps, preventive_measures, severity, occurrence_count,
     category, parameters, file_path, file_size_bytes, text_preview, full_text)
    VALUES ($1,$2,$3,$4,$5,$6,$7,$8::jsonb,$9::jsonb,$10,$11,$12,$13::jsonb,$14,$15,$16,$17)
    RETURNING *"""

_CASE_UPDATE_SQL = """UPDATE cases SET
    title=$1, equipment_type=$2, fault_category=$3, phenomenon=$4,
    root_cause=$5, troubleshooting_steps=$6::jsonb, preventive_measures=$7::jsonb,
    severity=$8, occurrence_count=$9,
    category=$10, parameters=$11::jsonb, text_preview=$12, full_text=$13,
    updated_at=NOW()
    WHERE id=$14 RETURNING *"""


async def _pg_pool():
    from raganything.services.pg_state_repo import get_pg_pool
    return get_pg_pool()


class CaseLibrary:
    """统一案例库 — PG-backed.

    合并故障案例库 (FaultCaseLibrary) 与维修工艺库 (ProcessLibrary)
    为单一表 ``cases``，通过 ``case_type`` 区分类型。
    """

    def __init__(self, storage_path: str | Path = "./data/autorepair_kb/cases"):
        self.storage_path = Path(storage_path)
        self.storage_path.mkdir(parents=True, exist_ok=True)

    # ── CRUD ──────────────────────────────────────────

    async def add_case(self, case: Case) -> str:
        """添加案例。case_type='fault' 验证必填字段，'process' 自动分类。"""
        if case.case_type == "fault":
            if not case.phenomenon or not case.root_cause or not case.troubleshooting_steps:
                raise ValueError(f"故障案例 {case.title} 缺少必填字段 (phenomenon/root_cause/troubleshooting_steps)")
        elif case.case_type == "process":
            if not case.full_text:
                raise ValueError(f"工艺案例 {case.title} 缺少内容 (full_text)")
            # Auto-classify
            if not case.category:
                case.category = self._classify_process(case.full_text)
            if not case.parameters:
                case.parameters = self._extract_parameters(case.full_text)
            if not case.text_preview:
                case.text_preview = case.full_text[:500]

        pool = await _pg_pool()
        async with pool.acquire() as conn:
            await conn.execute(
                _CASE_INSERT_SQL,
                case.id, case.title, case.case_type,
                case.equipment_type, case.fault_category,
                case.phenomenon, case.root_cause,
                json.dumps(case.troubleshooting_steps, ensure_ascii=False),
                json.dumps(case.preventive_measures, ensure_ascii=False),
                case.severity, case.occurrence_count,
                case.category,
                json.dumps(case.parameters, ensure_ascii=False),
                case.file_path, case.file_size_bytes,
                case.text_preview, case.full_text,
            )
        return case.id

    async def search(self, query: str, case_type: str = "",
                     category: str = "", top_k: int = 20) -> list[dict]:
        """统一检索 — PG ILIKE text search，可按 case_type 过滤。"""
        return await self._pg_text_search(query, case_type, category, top_k)

    async def _pg_text_search(self, query: str, case_type: str,
                               category: str, top_k: int) -> list[dict]:
        pool = await _pg_pool()
        q = f"%{query}%"

        # Build WHERE clauses dynamically
        clauses = []
        params = []
        param_idx = 1

        if query:
            clauses.append(
                f"(title ILIKE ${param_idx} OR phenomenon ILIKE ${param_idx} "
                f"OR root_cause ILIKE ${param_idx} OR fault_category ILIKE ${param_idx} "
                f"OR full_text ILIKE ${param_idx})"
            )
            params.append(q)
            param_idx += 1

        if case_type:
            clauses.append(f"case_type = ${param_idx}")
            params.append(case_type)
            param_idx += 1

        if category:
            clauses.append(f"category = ${param_idx}")
            params.append(category)
            param_idx += 1

        where = "WHERE " + " AND ".join(clauses) if clauses else ""
        sql = f"""SELECT id, title, case_type,
                     equipment_type, fault_category, phenomenon, root_cause,
                     troubleshooting_steps, preventive_measures, severity,
                     category, parameters, text_preview, full_text, file_path,
                     created_at
              FROM cases {where}
              ORDER BY created_at DESC LIMIT ${param_idx}"""
        params.append(top_k)

        async with pool.acquire() as conn:
            rows = await conn.fetch(sql, *params)

        results = []
        for r in rows:
            steps = r["troubleshooting_steps"]
            if isinstance(steps, str):
                try:
                    steps = json.loads(steps)
                except Exception:
                    steps = []
            measures = r["preventive_measures"]
            if isinstance(measures, str):
                try:
                    measures = json.loads(measures)
                except Exception:
                    measures = []
            params_data = r["parameters"]
            if isinstance(params_data, str):
                try:
                    params_data = json.loads(params_data)
                except Exception:
                    params_data = []

            results.append({
                "id": r["id"], "title": r["title"],
                "case_type": r["case_type"],
                "equipment_type": r.get("equipment_type", ""),
                "fault_category": r.get("fault_category", ""),
                "phenomenon": r.get("phenomenon", ""),
                "root_cause": r.get("root_cause", ""),
                "troubleshooting_steps": steps,
                "preventive_measures": measures,
                "severity": r.get("severity", "medium"),
                "category": r.get("category", ""),
                "parameters": params_data,
                "text_preview": r.get("text_preview", ""),
                "full_text": r.get("full_text", ""),
                "file_path": r.get("file_path", ""),
                "created_at": r["created_at"].isoformat()
                    if hasattr(r["created_at"], 'isoformat')
                    else str(r.get("created_at", "")),
                "score": 1.0,
            })
        return results

    async def get_case(self, case_id: str) -> Optional[dict]:
        """获取单个案例。"""
        pool = await _pg_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT * FROM cases WHERE id = $1", case_id,
            )
        if row:
            return self._row_to_dict(dict(row))
        return None

    async def update_case(self, case_id: str, updates: dict) -> bool:
        """更新案例。返回是否成功。"""
        pool = await _pg_pool()
        async with pool.acquire() as conn:
            existing = await conn.fetchrow(
                "SELECT * FROM cases WHERE id = $1", case_id,
            )
            if not existing:
                return False

            # Auto-classify process updates
            new_full_text = updates.get("full_text", existing["full_text"] or "")
            new_category = self._classify_process(new_full_text) \
                if "full_text" in updates else (existing.get("category") or "")
            new_params = self._extract_parameters(new_full_text) \
                if "full_text" in updates else existing.get("parameters", [])
            if isinstance(new_params, list):
                new_params = json.dumps(new_params, ensure_ascii=False)
            new_text_preview = new_full_text[:500] \
                if "full_text" in updates else (existing.get("text_preview") or "")
            new_category = updates.get("category", new_category)

            await conn.execute(
                _CASE_UPDATE_SQL,
                updates.get("title", existing["title"]),
                updates.get("equipment_type", existing.get("equipment_type", "")),
                updates.get("fault_category", existing.get("fault_category", "")),
                updates.get("phenomenon", existing.get("phenomenon", "")),
                updates.get("root_cause", existing.get("root_cause", "")),
                json.dumps(updates.get("troubleshooting_steps",
                            existing.get("troubleshooting_steps") or []),
                           ensure_ascii=False),
                json.dumps(updates.get("preventive_measures",
                            existing.get("preventive_measures") or []),
                           ensure_ascii=False),
                updates.get("severity", existing.get("severity", "medium")),
                updates.get("occurrence_count", existing.get("occurrence_count", 0)),
                new_category,
                json.dumps(new_params, ensure_ascii=False)
                    if isinstance(new_params, list)
                    else (new_params if isinstance(new_params, str) else '[]'),
                new_text_preview,
                new_full_text,
                case_id,
            )
        return True

    async def delete_case(self, case_id: str) -> bool:
        """删除案例。返回是否成功。"""
        pool = await _pg_pool()
        async with pool.acquire() as conn:
            result = await conn.execute(
                "DELETE FROM cases WHERE id = $1", case_id,
            )
        return result and "DELETE 0" not in result

    # ── Statistics ─────────────────────────────────────

    async def get_statistics(self) -> dict:
        """获取统一案例库统计信息。"""
        pool = await _pg_pool()
        async with pool.acquire() as conn:
            # Total counts by case_type
            type_rows = await conn.fetch(
                "SELECT case_type, count(*) as cnt FROM cases GROUP BY case_type"
            )
            # Fault-specific stats
            fault_total = await conn.fetchval(
                "SELECT count(*) FROM cases WHERE case_type = 'fault'"
            )
            eq_rows = await conn.fetch(
                "SELECT equipment_type, count(*) as cnt FROM cases "
                "WHERE case_type = 'fault' AND equipment_type IS NOT NULL "
                "AND equipment_type != '' GROUP BY equipment_type"
            )
            cat_rows = await conn.fetch(
                "SELECT fault_category, count(*) as cnt FROM cases "
                "WHERE case_type = 'fault' AND fault_category IS NOT NULL "
                "AND fault_category != '' GROUP BY fault_category"
            )
            sev_rows = await conn.fetch(
                "SELECT severity, count(*) as cnt FROM cases "
                "WHERE case_type = 'fault' GROUP BY severity"
            )
            # Process-specific stats
            proc_total = await conn.fetchval(
                "SELECT count(*) FROM cases WHERE case_type = 'process'"
            )
            proc_cat_rows = await conn.fetch(
                "SELECT category, count(*) as cnt FROM cases "
                "WHERE case_type = 'process' AND category IS NOT NULL "
                "AND category != '' GROUP BY category"
            )
        return {
            "total_cases": sum(r["cnt"] for r in type_rows),
            "fault_total": fault_total or 0,
            "process_total": proc_total or 0,
            "by_type": {r["case_type"]: r["cnt"] for r in type_rows},
            "equipment_types": {r["equipment_type"]: r["cnt"] for r in eq_rows},
            "fault_categories": {r["fault_category"]: r["cnt"] for r in cat_rows},
            "severity_distribution": {r["severity"]: r["cnt"] for r in sev_rows},
            "process_categories": {r["category"]: r["cnt"] for r in proc_cat_rows},
        }

    async def list_categories(self) -> dict[str, int]:
        """按工艺类别统计案例数量。"""
        pool = await _pg_pool()
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT category, count(*) as cnt FROM cases "
                "WHERE case_type = 'process' AND category IS NOT NULL "
                "AND category != '' GROUP BY category"
            )
        return {r["category"]: r["cnt"] for r in rows}

    # ── Internal ──────────────────────────────────────

    def _classify_process(self, text: str) -> str:
        """自动分类工艺文本。"""
        scores = {}
        for cat, keywords in PROCESS_CATEGORIES.items():
            scores[cat] = sum(1 for kw in keywords if kw in text)
        if not scores or max(scores.values()) == 0:
            return "general"
        return max(scores, key=scores.get)

    def _extract_parameters(self, text: str) -> list[dict]:
        """提取工艺参数。"""
        params = []
        for pattern in PARAM_PATTERNS:
            matches = pattern.findall(text)
            for match in matches:
                if len(match) >= 2:
                    params.append({
                        "name": match[0] if match[0] else "",
                        "value": match[1] if len(match) > 1 else "",
                        "unit": match[2] if len(match) > 2 else "",
                    })
        return params

    def _row_to_dict(self, row: dict) -> dict:
        """Convert PG row to dict (safe JSON parsing)."""
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
        params = row.get("parameters", [])
        if isinstance(params, str):
            try:
                params = json.loads(params)
            except Exception:
                params = []

        result = {
            "id": row["id"], "title": row["title"],
            "case_type": row.get("case_type", "fault"),
            "equipment_type": row.get("equipment_type", ""),
            "fault_category": row.get("fault_category", ""),
            "phenomenon": row.get("phenomenon", ""),
            "root_cause": row.get("root_cause", ""),
            "troubleshooting_steps": steps,
            "preventive_measures": measures,
            "severity": row.get("severity", "medium"),
            "occurrence_count": row.get("occurrence_count", 0),
            "category": row.get("category", ""),
            "parameters": params,
            "file_path": row.get("file_path", ""),
            "file_size_bytes": row.get("file_size_bytes", 0),
            "text_preview": row.get("text_preview", ""),
            "full_text": row.get("full_text", ""),
        }
        if row.get("created_at"):
            result["created_at"] = row["created_at"].isoformat() \
                if hasattr(row["created_at"], 'isoformat') \
                else str(row["created_at"])
        return result
