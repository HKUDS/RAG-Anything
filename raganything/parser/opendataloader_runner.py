"""Controlled local runner for one-page OpenDataLoader conversions.

This module is intentionally executed in a separate Python process.  The SDK
starts Java itself, so the parent adapter can terminate this process group on a
timeout instead of leaving an orphaned JVM in a document worker.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
from pathlib import Path
from typing import Any


_REQUEST_SCHEMA = "opendataloader-runner-request-v1"
_RESULT_SCHEMA = "opendataloader-runner-result-v1"
_HEAP_RE = re.compile(r"-Xmx[1-9][0-9]*[mMgG]")


def _atomic_json(path: Path, data: dict[str, Any]) -> None:
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(data, ensure_ascii=True), encoding="utf-8")
    os.replace(temp, path)


def _contained(path: Path, root: Path) -> Path:
    resolved = path.resolve(strict=False)
    root_resolved = root.resolve(strict=False)
    try:
        resolved.relative_to(root_resolved)
    except ValueError as exc:
        raise ValueError("runner artifact path escapes output root") from exc
    return resolved


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _find_single_artifact(directory: Path, suffix: str) -> Path:
    candidates = [
        _contained(candidate, directory)
        for candidate in directory.rglob(f"*{suffix}")
        if candidate.is_file() and not candidate.name.startswith("runner-")
    ]
    if len(candidates) != 1:
        raise ValueError(f"expected one {suffix} artifact, found {len(candidates)}")
    return candidates[0]


def _page_numbers(elements: list[Any]) -> set[int]:
    seen: set[int] = set()
    stack = list(reversed(elements))
    while stack:
        element = stack.pop()
        if not isinstance(element, dict):
            continue
        page = element.get("page number")
        if isinstance(page, int):
            seen.add(page)
        for key in ("kids", "children", "list items"):
            children = element.get(key)
            if isinstance(children, list):
                stack.extend(reversed(children))
    return seen


def _validate_page_json(json_path: Path, page: int) -> tuple[dict[str, Any], int]:
    try:
        data = json.loads(json_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError("page JSON is unreadable") from exc
    if not isinstance(data, dict) or not isinstance(data.get("kids"), list):
        raise ValueError("page JSON has no valid kids array")
    if not isinstance(data.get("number of pages"), int) or data["number of pages"] < 1:
        raise ValueError("page JSON has invalid page count")
    numbers = _page_numbers(data["kids"])
    if numbers and numbers != {page}:
        raise ValueError("page JSON contains elements from another page")
    return data, len(data["kids"])


def _run(request_path: Path) -> int:
    request = json.loads(request_path.read_text(encoding="utf-8"))
    if request.get("schema_version") != _REQUEST_SCHEMA:
        raise ValueError("unsupported runner request schema")

    output_root = Path(request["output_root"]).resolve()
    request_path = _contained(request_path, output_root)
    source_pdf = Path(request["source_pdf"]).resolve()
    if not source_pdf.is_file() or source_pdf.suffix.lower() != ".pdf":
        raise ValueError("source PDF is unavailable")

    total_pages = request.get("source_total_pages")
    page = request.get("page")
    if not isinstance(total_pages, int) or total_pages < 1:
        raise ValueError("source_total_pages must be positive")
    if not isinstance(page, int) or not 1 <= page <= total_pages:
        raise ValueError("page must be within source_total_pages")
    java_heap = request.get("java_heap")
    if not isinstance(java_heap, str) or not _HEAP_RE.fullmatch(java_heap):
        raise ValueError("invalid Java heap limit")

    env = os.environ.copy()
    env["JAVA_TOOL_OPTIONS"] = java_heap
    os.environ["JAVA_TOOL_OPTIONS"] = java_heap
    result: dict[str, Any] = {
        "schema_version": _RESULT_SCHEMA,
        "source_total_pages": total_pages,
        "pages": [],
    }
    result_path = output_root / "runner-result.json"

    from opendataloader_pdf import convert

    try:
        convert(
            input_path=str(source_pdf),
            output_dir=str(output_root),
            format=["json", "markdown"],
            quiet=True,
            use_struct_tree=True,
            image_output="external",
            image_format="png",
            table_method="default",
            reading_order="xycut",
            pages=str(page),
            threads="1",
        )
        json_path = _find_single_artifact(output_root, ".json")
        markdown_path = _find_single_artifact(output_root, ".md")
        _, top_level_elements = _validate_page_json(json_path, page)
        # A dedicated official pages=<n> conversion plus a valid contained
        # artifact is the proof for an empty page; batch omission is never used.
        state = "blank" if top_level_elements == 0 else "success"
        result["pages"].append(
            {
                "page": page,
                "state": state,
                "json_relpath": json_path.relative_to(output_root).as_posix(),
                "json_sha256": _sha256(json_path),
                "markdown_relpath": markdown_path.relative_to(output_root).as_posix(),
                "markdown_sha256": _sha256(markdown_path),
            }
        )
    except Exception as exc:
        result["pages"].append(
            {"page": page, "state": "failed", "failure": type(exc).__name__}
        )
        _atomic_json(result_path, result)
        return 1

    _atomic_json(result_path, result)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--request", required=True)
    args = parser.parse_args()
    try:
        return _run(Path(args.request))
    except Exception as exc:
        # Keep stdout/stderr bounded and free of source content or paths.
        print(f"OpenDataLoader runner failed: {type(exc).__name__}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
