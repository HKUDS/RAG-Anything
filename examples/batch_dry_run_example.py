"""
Dry-run batch parsing example.

Lists supported files without running any parser.

Usage:
  - pip install:
      python examples/batch_dry_run_example.py examples/sample_docs --parser mineru
      python examples/batch_dry_run_example.py examples/sample_docs/projects examples/sample_docs/web --parser docling
      python examples/batch_dry_run_example.py examples/sample_docs --parser paddleocr
  - uv install:
      uv run python examples/batch_dry_run_example.py examples/sample_docs --parser mineru --recursive
      uv run python examples/batch_dry_run_example.py examples/sample_docs --parser mineru --no-recursive
"""

import argparse

from raganything.batch_parser import BatchParser


def main() -> int:
    parser = argparse.ArgumentParser(description="Dry-run batch parsing example")
    parser.add_argument("paths", nargs="+", help="File paths or directories to scan")
    parser.add_argument(
        "--parser",
        choices=["mineru", "docling", "paddleocr"],
        default="mineru",
        help="Parser to use for file-type support",
    )
    parser.add_argument(
        "--output",
        default="./batch_output",
        help="Output directory (unused in dry-run, but required by API)",
    )
    parser.add_argument(
        "--recursive",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Search directories recursively",
    )
    args = parser.parse_args()

    batch_parser = BatchParser(parser_type=args.parser, show_progress=False)
    result = batch_parser.process_batch(
        file_paths=args.paths,
        output_dir=args.output,
        recursive=args.recursive,
        dry_run=True,
    )

    print(result.summary())
    if result.successful_files:
        print("\nDry run: files that would be processed:")
        for file_path in result.successful_files:
            print(f"  - {file_path}")
    else:
        print("\nDry run: no supported files found.")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
