"""
赛题结构化引擎 — 批量处理赛题文档，输出结构化 JSON。

支持增量处理、异常隔离（单文件失败不影响整体）。
"""

import json
import logging
from pathlib import Path
from datetime import datetime
from typing import Optional

from ..knowledge_graph.parser import ExamParser
from ..knowledge_graph.models import ExamQuestion

logger = logging.getLogger(__name__)


class ExamStructurer:
    """赛题批量结构化引擎。"""

    def __init__(self, parser: Optional[ExamParser] = None):
        self.parser = parser or ExamParser()

    def structure_batch(self, input_dir: str | Path,
                        output_path: str | Path,
                        competition_track: str = "") -> dict:
        """批量结构化赛题文档。

        Args:
            input_dir: 赛题文档目录
            output_path: 结构化 JSON 输出路径
            competition_track: 赛项标识

        Returns:
            {"total_files": int, "success": int, "failed": int,
             "questions": int, "errors": list, "output_path": str}
        """
        input_dir = Path(input_dir)
        output_path = Path(output_path)
        results = {"total_files": 0, "success": 0, "failed": 0,
                   "questions": 0, "errors": [], "output_path": str(output_path)}

        supported_exts = {".pdf", ".docx", ".doc", ".txt"}
        files = [f for f in input_dir.glob("*") if f.suffix.lower() in supported_exts]
        results["total_files"] = len(files)

        all_questions: list[dict] = []
        all_nodes: list[dict] = []

        for fp in files:
            try:
                parsed = self.parser.parse_document(str(fp), competition_track)
                all_questions.extend([self._question_to_dict(q) for q in parsed["questions"]])
                all_nodes.extend([self._node_to_dict(n) for n in parsed["knowledge_nodes"]])
                results["success"] += 1
            except Exception as e:
                logger.error(f"结构化失败 {fp.name}: {e}")
                results["errors"].append({"file": fp.name, "error": str(e)})
                results["failed"] += 1

        results["questions"] = len(all_questions)

        output_data = {
            "metadata": {
                "competition_track": competition_track,
                "processed_at": datetime.now().isoformat(),
                "source_files": len(files),
                "total_questions": len(all_questions),
                "total_knowledge_nodes": len(all_nodes),
            },
            "questions": all_questions,
            "knowledge_nodes": all_nodes,
        }

        output_path.write_text(
            json.dumps(output_data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        return results

    def validate_structure(self, data: dict) -> dict:
        """验证结构化数据的完整性。

        Returns:
            {"valid": bool, "issues": list[str]}
        """
        issues = []
        questions = data.get("questions", [])

        if not questions:
            issues.append("未检测到任何赛题")

        for i, q in enumerate(questions):
            if not q.get("content"):
                issues.append(f"第 {i+1} 题缺少 content 字段")
            if not q.get("question_type"):
                issues.append(f"第 {i+1} 题缺少 question_type 字段")

        return {"valid": len(issues) == 0, "issues": issues}

    @staticmethod
    def _question_to_dict(q: ExamQuestion) -> dict:
        return {
            "id": q.id, "competition_track": q.competition_track,
            "question_number": q.question_number, "question_type": q.question_type,
            "content": q.content, "options": q.options,
            "correct_answer": q.correct_answer, "explanation": q.explanation,
            "skill_requirements": q.skill_requirements,
            "difficulty": q.difficulty,
            "estimated_time_minutes": q.estimated_time_minutes,
        }

    @staticmethod
    def _node_to_dict(node) -> dict:
        return {
            "id": node.id, "name": node.name,
            "description": node.description, "node_type": node.node_type,
            "competition_track": node.competition_track,
            "difficulty_level": node.difficulty_level,
        }
