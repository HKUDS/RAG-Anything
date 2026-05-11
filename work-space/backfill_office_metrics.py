"""Recompute Source_Pages + per-page metrics + Multimodal_Retention_Profile
for office (.docx/.pptx) rows in pipeline_benchmark.csv after fixing
``get_source_page_count`` and ``compute_extract_metrics``.

Run once after the metric fix; safe to re-run (idempotent: it only
touches rows whose Source_Pages currently parse to 0).
"""

from __future__ import annotations

import argparse
import csv
import json
import shutil
import sys
from pathlib import Path

from _bootstrap import bootstrap_project_root

bootstrap_project_root()

from src.config import ENV
from src.extraction import compute_extract_metrics, get_source_page_count

OFFICE_SUFFIXES = {".docx", ".pptx", ".doc", ".ppt"}


def _find_content_list(parser_output_dir: Path, file_name: str) -> Path | None:
    stem = Path(file_name).stem
    candidate_root = parser_output_dir / stem / "mineru_cloud" / "result"
    if not candidate_root.exists():
        return None
    matches = list(candidate_root.glob("*_content_list.json"))
    if not matches:
        return None
    # Prefer the canonical content_list.json over content_list_v2.json
    matches.sort(key=lambda p: ("_v2" in p.name, p.name))
    return matches[0]


def _retention_profile(metrics: dict) -> str:
    return (
        f"img={metrics['figures_per_100_pages']:.1f}/100p | "
        f"table={metrics['tables_per_100_pages']:.1f}/100p | "
        f"eq={metrics['equations_per_100_pages']:.1f}/100p"
    )


def backfill(csv_path: Path, raw_docs_dir: Path, output_base_dir: Path, dry_run: bool) -> int:
    if not csv_path.exists():
        print(f"[skip] No CSV at {csv_path}", file=sys.stderr)
        return 0

    with open(csv_path, "r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        fieldnames = reader.fieldnames or []
        rows = list(reader)

    updated_rows = 0
    for row in rows:
        file_name = row.get("File_Name", "")
        suffix = Path(file_name).suffix.lower()
        if suffix not in OFFICE_SUFFIXES:
            continue
        if row.get("Status") != "Success":
            continue
        try:
            existing_pages = int(row.get("Source_Pages") or 0)
        except ValueError:
            existing_pages = 0
        if existing_pages > 0:
            continue

        file_path = raw_docs_dir / file_name
        if not file_path.exists():
            print(f"[skip] Source file missing: {file_path}", file=sys.stderr)
            continue

        new_pages = get_source_page_count(file_path)
        if new_pages <= 0:
            print(f"[skip] Could not determine page count for {file_name}", file=sys.stderr)
            continue

        exp_id = row.get("Experiment_ID") or ""
        parser_output_dir = output_base_dir / exp_id / "parser_output"
        content_list_path = _find_content_list(parser_output_dir, file_name)
        if content_list_path is None:
            print(
                f"[warn] No content_list.json for {file_name} under {parser_output_dir}; "
                "updating page count + per-page rates only.",
                file=sys.stderr,
            )
            content_list = []
        else:
            with open(content_list_path, "r", encoding="utf-8") as f:
                content_list = json.load(f)

        metrics = compute_extract_metrics(content_list, source_pages_override=new_pages)

        try:
            total_seconds = float(row.get("Total_Time(s)") or 0.0)
        except ValueError:
            total_seconds = 0.0
        try:
            output_tokens = float(row.get("Output_Tokens") or 0.0)
        except ValueError:
            output_tokens = 0.0

        row["Source_Pages"] = str(new_pages)
        row["End_to_End_Sec_Per_Page"] = f"{total_seconds / new_pages:.2f}"
        row["Output_Tokens_Per_Page"] = f"{output_tokens / new_pages:.2f}"
        if content_list:
            row["Multimodal_Retention_Profile"] = _retention_profile(metrics)

        print(
            f"[update] {exp_id}/{file_name}: "
            f"Source_Pages -> {new_pages}, "
            f"Sec_Per_Page -> {row['End_to_End_Sec_Per_Page']}, "
            f"Retention -> {row.get('Multimodal_Retention_Profile')}"
        )
        updated_rows += 1

    if updated_rows == 0:
        print("[done] Nothing to backfill.")
        return 0

    if dry_run:
        print(f"[dry-run] Would update {updated_rows} rows.")
        return updated_rows

    backup_path = csv_path.with_suffix(csv_path.suffix + ".bak")
    shutil.copyfile(csv_path, backup_path)
    print(f"[backup] Original saved to {backup_path}")

    with open(csv_path, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    print(f"[done] Updated {updated_rows} rows in {csv_path}.")
    return updated_rows


def main() -> None:
    parser = argparse.ArgumentParser(description="Backfill office metrics in pipeline_benchmark.csv")
    parser.add_argument(
        "--csv",
        type=Path,
        default=Path(ENV.report_file),
        help="Path to pipeline_benchmark.csv (defaults to ENV.report_file).",
    )
    parser.add_argument(
        "--raw-docs",
        type=Path,
        default=Path(ENV.parser_benchmark_input_dir or ENV.input_dir),
        help="Directory containing the source .docx/.pptx files.",
    )
    parser.add_argument(
        "--output-base-dir",
        type=Path,
        default=Path(ENV.output_base_dir),
        help="Directory containing per-experiment outputs (parser_output etc.).",
    )
    parser.add_argument("--dry-run", action="store_true", help="Preview without writing.")
    args = parser.parse_args()

    backfill(
        csv_path=args.csv,
        raw_docs_dir=args.raw_docs,
        output_base_dir=args.output_base_dir,
        dry_run=args.dry_run,
    )


if __name__ == "__main__":
    main()
