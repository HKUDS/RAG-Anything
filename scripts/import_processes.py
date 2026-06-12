#!/usr/bin/env python3
"""
工艺文档导入脚本 — 遍历目录，自动分类入库。

用法:
    python scripts/import_processes.py --input ./data/manufacturing_kb/processes/
    python scripts/import_processes.py --file process_001.docx
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from raganything.manufacturing.knowledge_pipeline.process_library import ProcessLibrary


def main():
    parser = argparse.ArgumentParser(description="工艺文档导入工具")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--input", help="工艺文档目录路径")
    group.add_argument("--file", help="单个工艺文档路径")
    parser.add_argument("--storage", default="./data/manufacturing_kb/processes", help="工艺库存储路径")
    args = parser.parse_args()

    library = ProcessLibrary(storage_path=args.storage)
    stats = {"total": 0, "imported": 0, "failed": 0, "categories": {}}

    files = []
    if args.file:
        fp = Path(args.file)
        if not fp.exists():
            print(f"错误: 文件不存在: {args.file}")
            sys.exit(1)
        files = [fp]
    else:
        input_dir = Path(args.input)
        if not input_dir.exists():
            print(f"错误: 目录不存在: {args.input}")
            sys.exit(1)
        files = list(input_dir.glob("*"))

    print(f"=== 工艺文档导入 ===")
    print(f"文件数: {len(files)}")
    stats["total"] = len(files)

    for fp in files:
        if fp.suffix.lower() not in (".txt", ".md", ".docx", ".doc", ".pdf"):
            print(f"  跳过 (不支持格式): {fp.name}")
            stats["failed"] += 1
            continue

        try:
            entry = library.ingest_document(fp)
            cat = entry["category"]
            stats["imported"] += 1
            stats["categories"][cat] = stats["categories"].get(cat, 0) + 1
            print(f"  ✓ {fp.name} → {cat}")
        except Exception as e:
            stats["failed"] += 1
            print(f"  ✗ {fp.name}: {e}")

    print(f"\n导入结果:")
    print(f"  成功: {stats['imported']}")
    print(f"  失败: {stats['failed']}")
    print(f"  分类统计: {stats['categories']}")

    all_cats = library.list_by_category()
    print(f"\n工艺库状态:")
    for cat, count in all_cats.items():
        print(f"  {cat}: {count} 份")


if __name__ == "__main__":
    main()
