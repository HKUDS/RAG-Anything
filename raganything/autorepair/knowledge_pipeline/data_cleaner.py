"""
数据清洗流水线 — 自动化数据质量处理。

清洗步骤:
1. 去重 (基于内容哈希)
2. 格式标准化 (编码/换行符/空格)
3. 编码修复 (统一 UTF-8)
4. 关键字段校验 (检查必填字段)
5. 清洗报告生成
"""

import hashlib
import json
import logging
from pathlib import Path
from datetime import datetime

logger = logging.getLogger(__name__)


class DataCleaner:
    """数据清洗流水线。"""

    def __init__(self):
        self.clean_stats = {
            "total": 0, "duplicates_removed": 0,
            "format_fixed": 0, "encoding_fixed": 0,
            "fields_validated": 0, "fields_failed": 0,
        }

    def run_pipeline(self, data: list[dict],
                     required_fields: list[str] | None = None,
                     dedup_key: str = "id") -> dict:
        """执行完整清洗流水线。

        Args:
            data: 待清洗数据列表
            required_fields: 必填字段列表
            dedup_key: 去重依据的键

        Returns:
            {"cleaned_data": list[dict], "stats": dict, "report": str}
        """
        self.clean_stats["total"] = len(data)

        # Step 1: 去重
        data = self._deduplicate(data, key=dedup_key)

        # Step 2: 格式标准化
        data = [self._normalize_format(item) for item in data]

        # Step 3: 编码修复
        data = [self._fix_encoding(item) for item in data]

        # Step 4: 关键字段校验
        if required_fields:
            valid_data, failed_items = self._validate_fields(data, required_fields)
            data = valid_data
        else:
            failed_items = []

        report = self._generate_report(failed_items)
        return {
            "cleaned_data": data,
            "stats": dict(self.clean_stats),
            "report": report,
        }

    def run_on_files(self, input_dir: str | Path,
                     output_dir: str | Path,
                     required_fields: list[str] | None = None,
                     dedup_key: str = "id") -> dict:
        """对目录中的所有 JSON 数据文件执行清洗。

        Returns:
            汇总清洗结果
        """
        input_dir = Path(input_dir)
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)

        overall_stats = {"files_processed": 0, "total_cleaned": 0, "total_removed": 0}

        for json_file in input_dir.glob("*.json"):
            try:
                data = json.loads(json_file.read_text(encoding="utf-8"))
                if isinstance(data, dict):
                    data = [data]
                if not isinstance(data, list):
                    continue

                result = self.run_pipeline(data, required_fields, dedup_key)
                cleaned = result["cleaned_data"]

                out_path = output_dir / json_file.name
                out_path.write_text(
                    json.dumps(cleaned, ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )

                overall_stats["files_processed"] += 1
                overall_stats["total_cleaned"] += len(cleaned)
                overall_stats["total_removed"] += result["stats"]["duplicates_removed"]

            except Exception as e:
                logger.error(f"清洗文件失败 {json_file.name}: {e}")

        return overall_stats

    def _deduplicate(self, data: list[dict], key: str = "id") -> list[dict]:
        seen_ids = set()
        unique = []
        for item in data:
            item_id = item.get(key, self._content_hash(item))
            if item_id not in seen_ids:
                seen_ids.add(item_id)
                unique.append(item)
            else:
                self.clean_stats["duplicates_removed"] += 1
        return unique

    def _normalize_format(self, item: dict) -> dict:
        normalized = {}
        fixed = False
        for k, v in item.items():
            # 标准化键名（去首尾空格）
            clean_key = k.strip()
            if clean_key != k:
                fixed = True

            # 标准化字符串值
            if isinstance(v, str):
                clean_val = v.replace("\r\n", "\n").strip()
                if clean_val != v:
                    fixed = True
                normalized[clean_key] = clean_val
            else:
                normalized[clean_key] = v

        if fixed:
            self.clean_stats["format_fixed"] += 1
        return normalized

    def _fix_encoding(self, item: dict) -> dict:
        fixed = False
        result = {}
        for k, v in item.items():
            if isinstance(v, str):
                try:
                    cleaned = v.encode("utf-8", errors="replace").decode("utf-8")
                    if cleaned != v:
                        fixed = True
                    result[k] = cleaned
                except Exception:
                    result[k] = v
            else:
                result[k] = v
        if fixed:
            self.clean_stats["encoding_fixed"] += 1
        return result

    def _validate_fields(self, data: list[dict],
                         required_fields: list[str]) -> tuple[list[dict], list[dict]]:
        valid = []
        failed = []
        for item in data:
            missing = [f for f in required_fields if not item.get(f)]
            if missing:
                self.clean_stats["fields_failed"] += 1
                failed.append({"item": item, "missing_fields": missing})
            else:
                self.clean_stats["fields_validated"] += 1
                valid.append(item)
        return valid, failed

    def _generate_report(self, failed_items: list[dict]) -> str:
        lines = [
            "# 数据清洗报告",
            f"生成时间: {datetime.now().isoformat()}",
            "",
            "## 统计",
            f"- 总记录: {self.clean_stats['total']}",
            f"- 去重删除: {self.clean_stats['duplicates_removed']}",
            f"- 格式修正: {self.clean_stats['format_fixed']}",
            f"- 编码修复: {self.clean_stats['encoding_fixed']}",
            f"- 字段校验通过: {self.clean_stats['fields_validated']}",
            f"- 字段校验失败: {self.clean_stats['fields_failed']}",
        ]
        if failed_items:
            lines.append("\n## 校验失败详情")
            for i, item in enumerate(failed_items[:20]):  # Top 20
                lines.append(f"- 记录 {i+1}: 缺失字段 {item['missing_fields']}")
        return "\n".join(lines)

    @staticmethod
    def _content_hash(item: dict) -> str:
        return hashlib.md5(
            json.dumps(item, sort_keys=True).encode()
        ).hexdigest()
