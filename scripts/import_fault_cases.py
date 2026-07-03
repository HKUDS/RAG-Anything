#!/usr/bin/env python3
"""
故障案例批量导入脚本 — 从 JSON 文件批量导入故障案例。

用法:
    python scripts/import_fault_cases.py --input ./data/autorepair_kb/fault_cases/sample.json
    python scripts/import_fault_cases.py --input ./faults/batch1.json --dry-run
"""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from raganything.autorepair.knowledge_pipeline.fault_case_library import FaultCaseLibrary
from raganything.autorepair.knowledge_graph.models import FaultCase


def validate_case(case_data: dict) -> list[str]:
    """校验必填字段，返回缺失字段列表。"""
    required = ["title", "phenomenon", "root_cause", "troubleshooting_steps"]
    return [f for f in required if not case_data.get(f)]


def main():
    parser = argparse.ArgumentParser(description="故障案例批量导入工具")
    parser.add_argument("--input", required=True, help="JSON 文件路径（包含案例数组）")
    parser.add_argument("--storage", default="./data/autorepair_kb/fault_cases", help="案例库存储路径")
    parser.add_argument("--dry-run", action="store_true", help="仅校验，不入库")
    args = parser.parse_args()

    input_path = Path(args.input)
    if not input_path.exists():
        print(f"错误: 文件不存在: {args.input}")
        sys.exit(1)

    print("=== 故障案例导入 ===")
    print(f"输入文件: {input_path}")
    print(f"模式: {'预览 (dry-run)' if args.dry_run else '正式导入'}")

    data = json.loads(input_path.read_text(encoding="utf-8"))
    cases = data if isinstance(data, list) else data.get("cases", [])

    if not cases:
        print("错误: 未找到案例数据（JSON 应为数组或包含 'cases' 键）")
        sys.exit(1)

    library = FaultCaseLibrary(storage_path=args.storage)
    stats = {"total": len(cases), "imported": 0, "skipped": 0, "errors": []}

    for i, case_data in enumerate(cases):
        missing = validate_case(case_data)
        if missing:
            stats["skipped"] += 1
            stats["errors"].append({
                "index": i,
                "title": case_data.get("title", f"案例 {i+1}"),
                "missing_fields": missing,
            })
            continue

        if args.dry_run:
            stats["imported"] += 1
            continue

        try:
            case = FaultCase(
                id=case_data.get("id", f"case_{i:04d}"),
                title=case_data["title"],
                equipment_type=case_data.get("equipment_type", "通用"),
                fault_category=case_data.get("fault_category", "机械"),
                phenomenon=case_data["phenomenon"],
                root_cause=case_data["root_cause"],
                troubleshooting_steps=case_data.get("troubleshooting_steps", []),
                preventive_measures=case_data.get("preventive_measures", []),
                severity=case_data.get("severity", "medium"),
            )
            library.add_case(case)
            stats["imported"] += 1
        except Exception as e:
            stats["skipped"] += 1
            stats["errors"].append({
                "index": i,
                "title": case_data.get("title", f"案例 {i+1}"),
                "error": str(e),
            })

    print("\n导入结果:")
    print(f"  总数: {stats['total']}")
    print(f"  已导入: {stats['imported']}")
    print(f"  已跳过: {stats['skipped']}")

    if stats["errors"]:
        print("\n跳过详情:")
        for err in stats["errors"]:
            print(f"  - #{err['index']} {err.get('title', '')}: {err.get('missing_fields', err.get('error', ''))}")

    # 最终统计
    all_stats = library.get_statistics()
    print("\n案例库状态:")
    print(f"  总案例: {all_stats['total_cases']}")
    print(f"  设备类型: {all_stats.get('equipment_types', {})}")
    print(f"  故障类别: {all_stats.get('fault_categories', {})}")


if __name__ == "__main__":
    main()
