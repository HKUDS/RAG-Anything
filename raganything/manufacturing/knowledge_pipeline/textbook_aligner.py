"""
教材知识点对齐工具 — 计算教材知识点与赛项能力的语义相似度，建立映射。
"""

import json
import logging
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


class TextbookAligner:
    """教材知识点 ↔ 赛项能力要求 对齐映射工具。"""

    def __init__(self, embedding_client=None,
                 similarity_threshold: float = 0.65):
        self.embedding_client = embedding_client
        self.similarity_threshold = similarity_threshold
        self._mappings: list[dict] = []

    def align(self, textbook_knowledge: list[dict],
              competition_skills: list[dict]) -> list[dict]:
        """计算教材知识点与赛项能力的对齐映射。

        Args:
            textbook_knowledge: [{"id", "name", "description", "chapter"}, ...]
            competition_skills: [{"id", "name", "description", "track"}, ...]

        Returns:
            [{"textbook_kp": dict, "competition_skill": dict, "score": float, "confirmed": bool}, ...]
        """
        mappings = []

        for tk in textbook_knowledge:
            best_match = None
            best_score = 0.0

            for cs in competition_skills:
                score = self._calculate_similarity(tk, cs)
                if score > best_score and score >= self.similarity_threshold:
                    best_score = score
                    best_match = cs

            if best_match:
                mappings.append({
                    "textbook_knowledge": tk,
                    "competition_skill": best_match,
                    "similarity_score": round(best_score, 4),
                    "confirmed": False,
                })

        self._mappings = mappings
        return mappings

    def confirm_mapping(self, index: int, confirmed: bool = True) -> bool:
        """人工确认/拒绝映射关系。"""
        if 0 <= index < len(self._mappings):
            self._mappings[index]["confirmed"] = confirmed
            return True
        return False

    def get_unconfirmed(self) -> list[dict]:
        """获取待确认的映射列表。"""
        return [m for m in self._mappings if not m["confirmed"]]

    def get_confirmed_mappings(self) -> list[dict]:
        """获取已确认的映射列表。"""
        return [m for m in self._mappings if m["confirmed"]]

    def export_mappings(self, output_path: str | Path) -> None:
        """导出对齐映射为 JSON。"""
        output_path = Path(output_path)
        output_path.write_text(
            json.dumps(self._mappings, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def get_coverage_stats(self, textbook_knowledge: list[dict]) -> dict:
        """计算教材知识点的赛项覆盖率。"""
        mapped_ids = {
            m["textbook_knowledge"]["id"] for m in self._mappings if m["confirmed"]
        }
        total = len(textbook_knowledge)
        mapped = len(mapped_ids)
        return {
            "total_textbook_kps": total,
            "mapped_count": mapped,
            "unmapped_count": total - mapped,
            "coverage_rate": round(mapped / total * 100, 1) if total > 0 else 0,
        }

    def _calculate_similarity(self, tk: dict, cs: dict) -> float:
        """计算两个知识点的相似度。"""
        if self.embedding_client:
            return self._semantic_similarity(tk, cs)
        return self._keyword_similarity(tk, cs)

    def _semantic_similarity(self, tk: dict, cs: dict) -> float:
        tk_text = f"{tk.get('name', '')} {tk.get('description', '')}"
        cs_text = f"{cs.get('name', '')} {cs.get('description', '')}"
        try:
            tk_vec = self.embedding_client.embed(tk_text)
            cs_vec = self.embedding_client.embed(cs_text)
            dot = sum(a * b for a, b in zip(tk_vec, cs_vec))
            na = sum(a ** 2 for a in tk_vec) ** 0.5
            nb = sum(b ** 2 for b in cs_vec) ** 0.5
            return dot / (na * nb) if na and nb else 0.0
        except Exception as e:
            logger.warning(f"语义相似度计算失败: {e}")
            return self._keyword_similarity(tk, cs)

    def _keyword_similarity(self, tk: dict, cs: dict) -> float:
        tk_words = set(
            f"{tk.get('name', '')} {tk.get('description', '')}".lower().split()
        )
        cs_words = set(
            f"{cs.get('name', '')} {cs.get('description', '')}".lower().split()
        )
        if not tk_words or not cs_words:
            return 0.0
        intersection = tk_words & cs_words
        return len(intersection) / min(len(tk_words), len(cs_words))
