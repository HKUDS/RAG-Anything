"""
故障案例库 — 案例录入模板、向量化检索、关联标签推荐。
"""

import json
import logging
from pathlib import Path
from typing import Optional

from ..knowledge_graph.models import FaultCase

logger = logging.getLogger(__name__)


class FaultCaseLibrary:
    """设备故障案例库。"""

    def __init__(self, storage_path: str | Path = "./data/manufacturing_kb/fault_cases",
                 embedding_client=None):
        self.storage_path = Path(storage_path)
        self.storage_path.mkdir(parents=True, exist_ok=True)
        self.embedding_client = embedding_client
        self._cases: dict[str, FaultCase] = {}
        self._load_index()

    def add_case(self, case: FaultCase) -> str:
        """添加故障案例。验证必填字段后入库。"""
        if not self._validate_case(case):
            raise ValueError(f"故障案例 {case.title} 缺少必填字段")
        self._cases[case.id] = case
        self._persist()
        return case.id

    def search(self, query: str, top_k: int = 5) -> list[dict]:
        """基于向量相似度检索故障案例。

        降级方案：关键词匹配。
        空查询时返回全部案例。
        """
        if not query.strip():
            cases = list(self._cases.values())
            cases.sort(key=lambda c: c.created_at, reverse=True)
            return [self._case_to_result(c, 1.0) for c in cases[:top_k]]
        if self.embedding_client:
            return self._vector_search(query, top_k)
        return self._keyword_search(query, top_k)

    def search_by_equipment(self, equipment_type: str) -> list[FaultCase]:
        """按设备类型检索。"""
        return [
            c for c in self._cases.values()
            if c.equipment_type == equipment_type
        ]

    def search_by_category(self, fault_category: str) -> list[FaultCase]:
        """按故障类别检索。"""
        return [
            c for c in self._cases.values()
            if c.fault_category == fault_category
        ]

    def get_case(self, case_id: str) -> Optional[FaultCase]:
        return self._cases.get(case_id)

    def update_case(self, case_id: str, updates: dict) -> bool:
        """更新故障案例。返回是否成功。

        ``updates`` 可以包含 FaultCase 中除 ``id`` 外的任意字段。
        """
        case = self._cases.get(case_id)
        if not case:
            return False
        # Allowed update fields (id is immutable)
        for field in ("title", "equipment_type", "fault_category",
                      "phenomenon", "root_cause", "severity",
                      "occurrence_count"):
            if field in updates and updates[field] is not None:
                setattr(case, field, updates[field])
        # List fields — replace entirely if provided
        for list_field in ("troubleshooting_steps", "preventive_measures",
                           "related_tags"):
            if list_field in updates and updates[list_field] is not None:
                setattr(case, list_field, updates[list_field])
        self._persist()
        return True

    def delete_case(self, case_id: str) -> bool:
        """删除故障案例。返回是否成功。"""
        if case_id not in self._cases:
            return False
        del self._cases[case_id]
        self._persist()
        return True

    def get_statistics(self) -> dict:
        """获取故障案例库统计信息。"""
        cases = list(self._cases.values())
        return {
            "total_cases": len(cases),
            "equipment_types": self._count_by(cases, "equipment_type"),
            "fault_categories": self._count_by(cases, "fault_category"),
            "severity_distribution": self._count_by(cases, "severity"),
        }

    def _validate_case(self, case: FaultCase) -> bool:
        return bool(case.phenomenon and case.root_cause and case.troubleshooting_steps)

    def _vector_search(self, query: str, top_k: int) -> list[dict]:
        """向量相似度检索。"""
        try:
            query_vec = self.embedding_client.embed(query)
            scored = []
            for case in self._cases.values():
                case_text = f"{case.phenomenon} {case.root_cause} {case.title}"
                case_vec = self.embedding_client.embed(case_text)
                score = self._cosine(query_vec, case_vec)
                scored.append((case, score))
            scored.sort(key=lambda x: x[1], reverse=True)
            return [self._case_to_result(c, s) for c, s in scored[:top_k]]
        except Exception as e:
            logger.warning(f"向量检索失败，降级: {e}")
            return self._keyword_search(query, top_k)

    def _keyword_search(self, query: str, top_k: int) -> list[dict]:
        """关键词检索。"""
        query_lower = query.lower()
        scored = []
        for case in self._cases.values():
            text = f"{case.title} {case.phenomenon} {case.root_cause} {case.fault_category}"
            score = sum(1 for word in query_lower.split() if word in text.lower())
            if score > 0:
                scored.append((case, score))
        scored.sort(key=lambda x: x[1], reverse=True)
        return [self._case_to_result(c, s) for c, s in scored[:top_k]]

    def _case_to_result(self, case: FaultCase, score: float) -> dict:
        return {
            "id": case.id, "title": case.title,
            "equipment_type": case.equipment_type,
            "fault_category": case.fault_category,
            "phenomenon": case.phenomenon,
            "root_cause": case.root_cause,
            "troubleshooting_steps": case.troubleshooting_steps,
            "severity": case.severity,
            "score": round(score, 4),
        }

    def _persist(self) -> None:
        data_path = self.storage_path / "cases.json"
        cases_data = {
            cid: {
                "id": c.id, "title": c.title,
                "equipment_type": c.equipment_type,
                "fault_category": c.fault_category,
                "phenomenon": c.phenomenon,
                "root_cause": c.root_cause,
                "troubleshooting_steps": c.troubleshooting_steps,
                "preventive_measures": c.preventive_measures,
                "severity": c.severity,
                "occurrence_count": c.occurrence_count,
                "created_at": c.created_at.isoformat(),
            }
            for cid, c in self._cases.items()
        }
        data_path.write_text(json.dumps(cases_data, ensure_ascii=False, indent=2), encoding="utf-8")

    def _load_index(self) -> None:
        data_path = self.storage_path / "cases.json"
        if data_path.exists():
            data = json.loads(data_path.read_text(encoding="utf-8"))
            for cid, cdata in data.items():
                self._cases[cid] = FaultCase(
                    id=cdata["id"], title=cdata["title"],
                    equipment_type=cdata["equipment_type"],
                    fault_category=cdata["fault_category"],
                    phenomenon=cdata["phenomenon"],
                    root_cause=cdata["root_cause"],
                    troubleshooting_steps=cdata.get("troubleshooting_steps", []),
                    preventive_measures=cdata.get("preventive_measures", []),
                    severity=cdata.get("severity", "medium"),
                    occurrence_count=cdata.get("occurrence_count", 0),
                )

    @staticmethod
    def _count_by(items: list, attr: str) -> dict:
        counts: dict = {}
        for item in items:
            val = getattr(item, attr, "unknown")
            counts[val] = counts.get(val, 0) + 1
        return counts

    @staticmethod
    def _cosine(a: list[float], b: list[float]) -> float:
        dot = sum(x * y for x, y in zip(a, b))
        na = sum(x ** 2 for x in a) ** 0.5
        nb = sum(y ** 2 for y in b) ** 0.5
        return dot / (na * nb) if na and nb else 0.0
