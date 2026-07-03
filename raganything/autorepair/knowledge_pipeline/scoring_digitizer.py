"""
评分标准数字化模块 — 将评分标准转化为可机读的判定条件。

解析大赛评分细则，输出标准化的评分规则 JSON。
"""

import json
import re
import logging
from pathlib import Path
from typing import Optional

from ..knowledge_graph.models import ScoringRule

logger = logging.getLogger(__name__)


class ScoringDigitizer:
    """评分标准数字化引擎。"""

    # 评分规则识别模式
    SCORE_PATTERN = re.compile(r"(\d+)\s*分")
    WEIGHT_PATTERN = re.compile(r"权重[：:]\s*(\d+\.?\d*)")

    def digitize(self, scoring_text: str) -> list[ScoringRule]:
        """解析评分标准文本为结构化规则。

        Args:
            scoring_text: 评分标准文档文本

        Returns:
            评分规则列表
        """
        rules = []
        lines = scoring_text.strip().split("\n")
        current_rule: Optional[dict] = None

        for line in lines:
            line = line.strip()
            if not line:
                if current_rule:
                    rules.append(self._build_rule(current_rule))
                    current_rule = None
                continue

            # 检测新规则项
            if self._is_new_rule(line):
                if current_rule:
                    rules.append(self._build_rule(current_rule))
                current_rule = self._parse_rule_line(line)
            elif current_rule:
                current_rule["criteria"] += " " + line

        if current_rule:
            rules.append(self._build_rule(current_rule))

        return rules

    def digitize_file(self, file_path: str | Path) -> dict:
        """从文件数字化评分标准。"""
        file_path = Path(file_path)
        text = file_path.read_text(encoding="utf-8")
        rules = self.digitize(text)

        return {
            "source_file": str(file_path),
            "rule_count": len(rules),
            "max_total_score": sum(r.max_score for r in rules),
            "rules": [self._rule_to_dict(r) for r in rules],
        }

    def export_rules(self, rules: list[ScoringRule],
                     output_path: str | Path) -> None:
        """导出评分规则为 JSON。"""
        output_path = Path(output_path)
        data = {
            "version": "1.0",
            "rules": [self._rule_to_dict(r) for r in rules],
        }
        output_path.write_text(
            json.dumps(data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def validate_rules(self, rules: list[ScoringRule]) -> dict:
        """验证评分规则的完整性与一致性。"""
        issues = []
        total_weight = sum(r.weight for r in rules)

        if not rules:
            issues.append("评分规则列表为空")
        if abs(total_weight - 1.0) > 0.01 and total_weight > 0:
            issues.append(f"权重总和 ({total_weight}) 不等于 1.0")
        for i, rule in enumerate(rules):
            if not rule.description:
                issues.append(f"规则 {i+1} 缺少描述")
            if rule.max_score <= 0:
                issues.append(f"规则 {i+1} 分值 <= 0")

        return {
            "valid": len(issues) == 0,
            "issues": issues,
            "rule_count": len(rules),
            "total_weight": total_weight,
        }

    # --- 私有方法 ---

    def _is_new_rule(self, line: str) -> bool:
        return bool(self.SCORE_PATTERN.search(line)) or line.startswith(("1.", "一、", "（"))

    def _parse_rule_line(self, line: str) -> dict:
        score_match = self.SCORE_PATTERN.search(line)
        weight_match = self.WEIGHT_PATTERN.search(line)
        return {
            "description": line,
            "max_score": int(score_match.group(1)) if score_match else 0,
            "weight": float(weight_match.group(1)) if weight_match else 1.0,
            "criteria": "",
            "deduction_rules": [],
        }

    def _build_rule(self, raw: dict) -> ScoringRule:
        import uuid
        return ScoringRule(
            id=str(uuid.uuid4())[:8],
            description=raw["description"],
            max_score=raw["max_score"],
            weight=raw["weight"],
            criteria=raw.get("criteria", ""),
            deduction_rules=raw.get("deduction_rules", []),
        )

    @staticmethod
    def _rule_to_dict(r: ScoringRule) -> dict:
        return {
            "id": r.id, "description": r.description,
            "max_score": r.max_score, "weight": r.weight,
            "criteria": r.criteria, "deduction_rules": r.deduction_rules,
        }
