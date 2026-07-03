#!/usr/bin/env python3
"""
教材知识点 CSV 导入脚本 — 解析 CSV → 自动对齐赛项能力。

CSV 格式: chapter, knowledge_point, description
用法:
    python scripts/import_textbook_kps.py --csv textbook.csv --track machining
"""

import argparse
import csv
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from raganything.autorepair.knowledge_pipeline.textbook_aligner import TextbookAligner
from raganything.autorepair.knowledge_graph.graph_api import KnowledgeGraphAPI


def main():
    parser = argparse.ArgumentParser(description="教材知识点导入工具")
    parser.add_argument("--csv", required=True, help="CSV 文件路径 (columns: chapter, knowledge_point, description)")
    parser.add_argument("--track", default="machining", help="目标赛项标识")
    parser.add_argument("--output", default="./data/autorepair_kb/textbooks/aligned.json", help="对齐结果输出路径")
    parser.add_argument("--threshold", type=float, default=0.65, help="相似度阈值")
    args = parser.parse_args()

    csv_path = Path(args.csv)
    if not csv_path.exists():
        print(f"错误: 文件不存在: {args.csv}")
        sys.exit(1)

    print("=== 教材知识点导入 ===")
    print(f"CSV: {csv_path}")
    print(f"目标赛项: {args.track}")

    # Step 1: 解析 CSV
    textbook_kps = []
    with open(csv_path, encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for i, row in enumerate(reader):
            textbook_kps.append({
                "id": f"tb_{args.track}_{i:04d}",
                "name": row.get("knowledge_point", row.get("知识点", "")),
                "description": row.get("description", row.get("描述", "")),
                "chapter": row.get("chapter", row.get("章节", "")),
            })

    if not textbook_kps:
        print("错误: CSV 中无有效数据")
        sys.exit(1)

    print(f"解析到 {len(textbook_kps)} 个教材知识点")

    # Step 2: 获取赛项能力列表
    graph_api = KnowledgeGraphAPI()
    nodes = graph_api.get_nodes(competition_track=args.track, limit=500)
    competition_skills = [
        {"id": n["id"], "name": n["name"], "description": n.get("description", "")}
        for n in nodes.get("nodes", [])
    ]

    if not competition_skills:
        print("警告: 目标赛项无知识节点，请先导入赛题数据")
        print("将跳过对齐步骤，仅保存教材知识点")
        Path(args.output).parent.mkdir(parents=True, exist_ok=True)
        Path(args.output).write_text(
            json.dumps({"textbook_kps": textbook_kps, "mappings": []}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return

    print(f"赛项能力节点: {len(competition_skills)} 个")

    # Step 3: 自动对齐
    aligner = TextbookAligner(similarity_threshold=args.threshold)
    mappings = aligner.align(textbook_kps, competition_skills)

    # Step 4: 输出
    Path(args.output).parent.mkdir(parents=True, exist_ok=True)
    output_data = {
        "textbook_knowledge": textbook_kps,
        "competition_skills": competition_skills,
        "mappings": mappings,
    }
    Path(args.output).write_text(
        json.dumps(output_data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    coverage = aligner.get_coverage_stats(textbook_kps)
    print("\n对齐结果:")
    print(f"  教材知识点: {coverage['total_textbook_kps']}")
    print(f"  已映射: {coverage['mapped_count']}")
    print(f"  未映射: {coverage['unmapped_count']}")
    print(f"  覆盖率: {coverage['coverage_rate']}%")
    print(f"  输出: {args.output}")
    print("\n⚠️  映射关系为自动生成，建议人工确认后再正式使用。")


if __name__ == "__main__":
    main()
