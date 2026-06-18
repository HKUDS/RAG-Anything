#!/usr/bin/env python3
"""
赛题批量导入脚本 — 遍历目录解析 PDF/Word → 结构化入库 → 创建知识图谱节点。

用法:
    python scripts/import_exams.py --input ./exams/machining/ --track machining
    python scripts/import_exams.py --input ./exams/ --track all --dry-run
"""

import argparse
import json
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from raganything.manufacturing.knowledge_graph.parser import ExamParser
from raganything.manufacturing.knowledge_pipeline.exam_structurer import ExamStructurer
from raganything.manufacturing.knowledge_graph.graph_api import KnowledgeGraphAPI
from raganything.manufacturing.knowledge_graph.models import KnowledgeNode


def main():
    parser = argparse.ArgumentParser(description="赛题批量导入工具")
    parser.add_argument("--input", required=True, help="赛题文档目录路径")
    parser.add_argument("--track", default="machining", help="赛项标识 (machining/electrical/robot/digital_design/integration)")
    parser.add_argument("--output", default="./data/manufacturing_kb/exams/structured.json", help="结构化输出路径")
    parser.add_argument("--dry-run", action="store_true", help="仅预览，不入库")
    args = parser.parse_args()

    input_dir = Path(args.input)
    if not input_dir.exists():
        print(f"错误: 目录不存在: {args.input}")
        sys.exit(1)

    print("=== 赛题导入 ===")
    print(f"输入目录: {input_dir}")
    print(f"赛项: {args.track}")
    print(f"模式: {'预览 (dry-run)' if args.dry_run else '正式导入'}")

    # Step 1: 结构化提取
    structurer = ExamStructurer(parser=ExamParser())
    result = structurer.structure_batch(
        input_dir=input_dir,
        output_path=args.output,
        competition_track=args.track,
    )

    print("\n结构化结果:")
    print(f"  文件: {result['total_files']} 个 (成功 {result['success']}, 失败 {result['failed']})")
    print(f"  赛题: {result['questions']} 道")
    if result["errors"]:
        print("  错误:")
        for err in result["errors"]:
            print(f"    - {err['file']}: {err['error']}")

    if args.dry_run:
        print("\n[Dry-run] 跳过入库。")
        return

    # Step 2: 知识图谱入库
    graph_api = KnowledgeGraphAPI()
    data = json.loads(Path(args.output).read_text(encoding="utf-8"))

    node_count = 0
    for node_data in data.get("knowledge_nodes", []):
        node = KnowledgeNode(
            id=node_data["id"],
            name=node_data["name"],
            description=node_data.get("description", ""),
            node_type=node_data.get("node_type", "knowledge_point"),
            competition_track=args.track,
            difficulty_level=node_data.get("difficulty_level", 3),
        )
        graph_api.create_node(node)
        node_count += 1

    print(f"\n入库完成: {node_count} 个知识节点已创建")

    # Summary
    summary = graph_api.get_graph_summary()
    print("\n知识图谱状态:")
    print(f"  总节点: {summary['total_nodes']}")
    print(f"  总关系: {summary['total_edges']}")


if __name__ == "__main__":
    main()
