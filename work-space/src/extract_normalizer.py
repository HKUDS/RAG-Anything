import json
from typing import Any, Dict, List, Tuple


def _to_list(value: Any) -> List[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(v).strip() for v in value if str(v).strip()]
    if isinstance(value, str):
        value = value.strip()
        return [value] if value else []
    value_str = str(value).strip()
    return [value_str] if value_str else []


def _to_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    return str(value)


def _to_page_idx(value: Any) -> int:
    try:
        page = int(value)
        return page if page >= 0 else 0
    except Exception:
        return 0


def _rows_to_markdown(rows: List[List[str]]) -> str:
    if not rows:
        return ""

    width = max(len(row) for row in rows) if rows else 0
    if width == 0:
        return ""

    norm_rows: List[List[str]] = []
    for row in rows:
        padded = list(row) + [""] * (width - len(row))
        escaped = [cell.replace("|", "\\|").replace("\n", " ").strip() for cell in padded]
        norm_rows.append(escaped)

    header = norm_rows[0]
    body = norm_rows[1:]

    lines = [
        "| " + " | ".join(header) + " |",
        "| " + " | ".join(["---"] * width) + " |",
    ]
    for row in body:
        lines.append("| " + " | ".join(row) + " |")
    return "\n".join(lines)


def _extract_rows_from_table_dict(table_body: Dict[str, Any]) -> List[List[str]]:
    grid = table_body.get("grid")
    if isinstance(grid, list) and grid:
        rows: List[List[str]] = []
        for row in grid:
            if not isinstance(row, list):
                continue
            out_row = []
            for cell in row:
                if isinstance(cell, dict):
                    out_row.append(_to_text(cell.get("text", "")).strip())
                else:
                    out_row.append(_to_text(cell).strip())
            rows.append(out_row)
        if rows:
            return rows

    # Fallback for Docling-like `table_cells` structure.
    table_cells = table_body.get("table_cells")
    num_rows = int(table_body.get("num_rows", 0) or 0)
    num_cols = int(table_body.get("num_cols", 0) or 0)
    if not isinstance(table_cells, list) or not table_cells:
        return []
    if num_rows <= 0 or num_cols <= 0:
        return []

    matrix: List[List[str]] = [["" for _ in range(num_cols)] for _ in range(num_rows)]
    for cell in table_cells:
        if not isinstance(cell, dict):
            continue
        r = int(cell.get("start_row_offset_idx", 0) or 0)
        c = int(cell.get("start_col_offset_idx", 0) or 0)
        if 0 <= r < num_rows and 0 <= c < num_cols:
            matrix[r][c] = _to_text(cell.get("text", "")).strip()
    return matrix


def _normalize_table_body(table_body: Any) -> str:
    if table_body is None:
        return ""
    if isinstance(table_body, str):
        return table_body
    if isinstance(table_body, dict):
        rows = _extract_rows_from_table_dict(table_body)
        if rows:
            return _rows_to_markdown(rows)
        return json.dumps(table_body, ensure_ascii=False)
    if isinstance(table_body, list):
        rows: List[List[str]] = []
        for row in table_body:
            if isinstance(row, list):
                rows.append([_to_text(cell).strip() for cell in row])
            elif isinstance(row, dict):
                rows.append([_to_text(v).strip() for _, v in sorted(row.items())])
            else:
                rows.append([_to_text(row).strip()])
        if rows:
            return _rows_to_markdown(rows)
        return ""
    return _to_text(table_body)


def normalize_content_list_for_pipeline(
    content_list: List[Dict[str, Any]],
    drop_discarded: bool = True,
) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """
    Normalize parser outputs into a consistent schema expected by downstream RAGAnything steps.

    Returns:
        (normalized_content_list, report)
    """
    normalized: List[Dict[str, Any]] = []
    raw_type_counts: Dict[str, int] = {}
    normalized_type_counts: Dict[str, int] = {}
    dropped_blocks = 0

    for item in content_list:
        if not isinstance(item, dict):
            item = {"type": "text", "text": _to_text(item), "page_idx": 0}

        raw_type = _to_text(item.get("type", "text")).strip().lower() or "text"
        raw_type_counts[raw_type] = raw_type_counts.get(raw_type, 0) + 1

        page_idx = _to_page_idx(
            item.get("page_idx", item.get("page", item.get("page_number", 0)))
        )

        if raw_type == "discarded" and drop_discarded:
            dropped_blocks += 1
            continue

        if raw_type in {"text", "title", "paragraph", "caption", "discarded"}:
            normalized_item = {
                "type": "text",
                "text": _to_text(item.get("text", item.get("content", ""))),
                "page_idx": page_idx,
            }
        elif raw_type in {"image", "picture", "figure"}:
            normalized_item = {
                "type": "image",
                "img_path": _to_text(item.get("img_path", item.get("image_path", ""))),
                "image_caption": _to_list(
                    item.get("image_caption", item.get("img_caption", item.get("caption")))
                ),
                "image_footnote": _to_list(
                    item.get("image_footnote", item.get("img_footnote", item.get("footnote")))
                ),
                "page_idx": page_idx,
            }
        elif raw_type == "table":
            normalized_item = {
                "type": "table",
                "img_path": _to_text(item.get("img_path", item.get("table_img_path", ""))),
                "table_caption": _to_list(item.get("table_caption", item.get("caption"))),
                "table_footnote": _to_list(item.get("table_footnote", item.get("footnote"))),
                "table_body": _normalize_table_body(
                    item.get("table_body", item.get("table_data", item.get("data")))
                ),
                "page_idx": page_idx,
            }
        elif raw_type in {"equation", "formula", "math"}:
            normalized_item = {
                "type": "equation",
                "text": _to_text(item.get("text", item.get("latex", item.get("equation", "")))),
                "text_format": _to_text(item.get("text_format", item.get("format", ""))),
                "equation_img_path": _to_text(
                    item.get("equation_img_path", item.get("img_path", ""))
                ),
                "page_idx": page_idx,
            }
        else:
            # Convert unknown parser-specific block types to text for deterministic downstream behavior.
            normalized_item = {
                "type": "text",
                "text": _to_text(item.get("text", item.get("content", item))),
                "page_idx": page_idx,
            }

        out_type = normalized_item["type"]
        normalized_type_counts[out_type] = normalized_type_counts.get(out_type, 0) + 1
        normalized.append(normalized_item)

    report = {
        "input_blocks": len(content_list),
        "output_blocks": len(normalized),
        "dropped_blocks": dropped_blocks,
        "raw_type_counts": raw_type_counts,
        "normalized_type_counts": normalized_type_counts,
    }
    return normalized, report

