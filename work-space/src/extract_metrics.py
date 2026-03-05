import hashlib
import re
from typing import Dict, Any, List


def _count_tokens(text: str) -> int:
    if not text:
        return 0
    try:
        import tiktoken

        encoding = tiktoken.get_encoding("cl100k_base")
        return len(encoding.encode(str(text)))
    except Exception:
        return 0


def _parse_markdown_table(table_str: str) -> Dict[str, int]:
    rows = 0
    cols = 0
    cells = 0
    if not table_str:
        return {"rows": 0, "cols": 0, "cells": 0}

    lines = [l.strip() for l in str(table_str).splitlines() if l.strip()]
    for line in lines:
        if "|" not in line:
            continue
        # skip separator line like |---|---|
        if set(line.replace("|", "").replace(":", "").replace("-", "").replace(" ", "")) == set():
            continue
        parts = [p.strip() for p in line.split("|") if p.strip()]
        if not parts:
            continue
        rows += 1
        cols = max(cols, len(parts))
        cells += len(parts)

    return {"rows": rows, "cols": cols, "cells": cells}


def _parse_html_table(table_str: str) -> Dict[str, int]:
    rows = 0
    cols = 0
    cells = 0
    if not table_str:
        return {"rows": 0, "cols": 0, "cells": 0}

    tr_blocks = re.findall(r"<tr[^>]*>(.*?)</tr>", str(table_str), flags=re.IGNORECASE | re.DOTALL)
    for tr in tr_blocks:
        cell_blocks = re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", tr, flags=re.IGNORECASE | re.DOTALL)
        cleaned_cells = [
            re.sub(r"<[^>]+>", "", c).strip() for c in cell_blocks
            if re.sub(r"<[^>]+>", "", c).strip()
        ]
        if not cleaned_cells:
            continue
        rows += 1
        cols = max(cols, len(cleaned_cells))
        cells += len(cleaned_cells)

    return {"rows": rows, "cols": cols, "cells": cells}


def _parse_table_body(table_body: Any) -> Dict[str, int]:
    if table_body is None:
        return {"rows": 0, "cols": 0, "cells": 0}

    # list-of-lists or list-of-dicts
    if isinstance(table_body, list):
        rows = len(table_body)
        cols = 0
        cells = 0
        for row in table_body:
            if isinstance(row, list):
                cols = max(cols, len(row))
                cells += len(row)
            elif isinstance(row, dict):
                cols = max(cols, len(row))
                cells += len(row)
            else:
                cells += 1
        return {"rows": rows, "cols": cols, "cells": cells}

    # dict structure (e.g., docling: {num_rows, num_cols, grid, table_cells})
    if isinstance(table_body, dict):
        num_rows = int(table_body.get("num_rows", 0) or 0)
        num_cols = int(table_body.get("num_cols", 0) or 0)
        grid = table_body.get("grid")

        if isinstance(grid, list) and grid:
            rows = 0
            cols = 0
            cells = 0
            for row in grid:
                if not isinstance(row, list):
                    continue
                non_empty = 0
                for cell in row:
                    if isinstance(cell, dict):
                        text = str(cell.get("text", "")).strip()
                    else:
                        text = str(cell).strip()
                    if text:
                        non_empty += 1
                if non_empty > 0:
                    rows += 1
                    cols = max(cols, len(row))
                    cells += non_empty
            if rows > 0:
                return {"rows": rows, "cols": cols, "cells": cells}

        table_cells = table_body.get("table_cells")
        if isinstance(table_cells, list) and table_cells:
            if num_rows > 0 and num_cols > 0:
                return {"rows": num_rows, "cols": num_cols, "cells": len(table_cells)}
            return {"rows": 0, "cols": 0, "cells": len(table_cells)}

        if num_rows > 0 or num_cols > 0:
            return {"rows": num_rows, "cols": num_cols, "cells": max(num_rows * num_cols, 0)}

        return {"rows": 0, "cols": 0, "cells": 0}

    # string markdown table
    if isinstance(table_body, str):
        if "<table" in table_body.lower():
            return _parse_html_table(table_body)
        return _parse_markdown_table(table_body)

    return {"rows": 0, "cols": 0, "cells": 0}


def _is_valid_image_file(path: str) -> bool:
    try:
        with open(path, "rb") as f:
            head = f.read(16)
    except Exception:
        return False

    known = [
        b"\x89PNG\r\n\x1a\n",
        b"\xff\xd8\xff",
        b"GIF87a",
        b"GIF89a",
        b"BM",
        b"II*\x00",
        b"MM\x00*",
    ]
    if any(head.startswith(sig) for sig in known):
        return True
    if head.startswith(b"RIFF") and head[8:12] == b"WEBP":
        return True

    # Fallback to PIL verification when available.
    try:
        from PIL import Image

        with Image.open(path) as img:
            img.verify()
        return True
    except Exception:
        return False


def compute_extract_metrics(content_list: List[Dict[str, Any]]) -> Dict[str, Any]:
    metrics = {
        "total_blocks": 0,
        "text_blocks": 0,
        "empty_text_blocks": 0,
        "text_chars": 0,
        "text_tokens": 0,
        "avg_text_block_len": 0.0,
        "image_blocks": 0,
        "image_files_exist": 0,
        "image_files_missing": 0,
        "table_blocks": 0,
        "table_rows": 0,
        "table_cells": 0,
        "equation_blocks": 0,
        "text_md5": "",
    }

    text_parts = []

    metrics["total_blocks"] = len(content_list)

    for item in content_list:
        if not isinstance(item, dict):
            continue

        item_type = item.get("type", "text")

        if item_type == "text":
            metrics["text_blocks"] += 1
            text = item.get("text", "") or ""
            if not str(text).strip():
                metrics["empty_text_blocks"] += 1
            else:
                text_parts.append(str(text))
                metrics["text_chars"] += len(str(text))
        elif item_type == "image":
            metrics["image_blocks"] += 1
            img_path = item.get("img_path")
            if img_path:
                try:
                    import os

                    if os.path.exists(img_path) and _is_valid_image_file(img_path):
                        metrics["image_files_exist"] += 1
                    else:
                        metrics["image_files_missing"] += 1
                except Exception:
                    metrics["image_files_missing"] += 1
            else:
                metrics["image_files_missing"] += 1
        elif item_type == "table":
            metrics["table_blocks"] += 1
            table_body = item.get("table_body")
            tb = _parse_table_body(table_body)
            metrics["table_rows"] += tb["rows"]
            metrics["table_cells"] += tb["cells"]
        elif item_type == "equation":
            metrics["equation_blocks"] += 1

    # Token count + avg len
    joined_text = "\n\n".join(text_parts)
    metrics["text_tokens"] = _count_tokens(joined_text)
    if metrics["text_blocks"] > 0:
        metrics["avg_text_block_len"] = metrics["text_chars"] / metrics["text_blocks"]

    # Hash of text for quick comparison across parsers
    metrics["text_md5"] = hashlib.md5(joined_text.encode("utf-8", errors="ignore")).hexdigest()

    return metrics
