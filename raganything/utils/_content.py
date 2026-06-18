# -*- coding: utf-8 -*-
"""
Content Separation & Formatting Utilities.

Layer: Core
Primary Responsibility: MinerU content list processing — text/multimodal separation,
    table/equation formatting, caption normalization, section path extraction.
Key Dependencies: lightrag.utils (logger), stdlib only

Functions:
    normalize_caption_list()            — clean caption/footnote lists
    get_table_body()                    — read table content across alias fields
    format_table_body()                 — serialize table body for prompts
    simplify_table_body()               — strip bbox noise, keep text
    get_equation_text_and_format()      — read equation preserving LaTeX aliases
    extract_section_path_from_content_list() — build hierarchical heading path
    extract_neighbor_text_from_content_list() — collect nearby text blocks
    separate_content()                  — split text from multimodal items
"""

from __future__ import annotations

from typing import Any, Dict, List, Tuple
from lightrag.utils import logger


def normalize_caption_list(value: Any) -> List[str]:
    """Return captions and footnotes as a clean list of strings."""
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, str) and value.strip():
        return [value.strip()]
    return []


def get_table_body(item: Dict[str, Any]) -> Any:
    """Read table content across common content-list alias fields."""
    if item.get("table_body") not in (None, ""):
        return item.get("table_body")
    if item.get("table_data") not in (None, ""):
        return item.get("table_data")
    return item.get("text", "")


def format_table_body(table_body: Any) -> str:
    """Serialize table content for prompts and chunks without dropping aliases.

    Strings are passed through unchanged. List-of-lists (the common
    ``table_data`` shape from non-MinerU parsers) are rendered as a simple
    Markdown table so the LLM sees structured rows instead of a Python repr.
    Other shapes fall back to a newline-joined string of ``str(...)`` items.
    """
    if isinstance(table_body, str):
        return table_body
    if isinstance(table_body, list):
        if not table_body:
            return ""
        if all(isinstance(row, (list, tuple)) for row in table_body):
            rendered_rows = [
                "| " + " | ".join(str(cell) for cell in row) + " |"
                for row in table_body
            ]
            if len(rendered_rows) >= 1:
                column_count = max(len(row) for row in table_body)
                separator = "| " + " | ".join(["---"] * column_count) + " |"
                rendered_rows.insert(1, separator)
            return "\n".join(rendered_rows)
        return "\n".join(str(row) for row in table_body)
    return str(table_body)


def simplify_table_body(table_body: Any, max_chars: int = 2000) -> str:
    """Simplify table body for chunk storage — strip bbox noise, keep text.

    For cell-dict format (MinerU/docling), extracts ``{text}`` from each cell
    with positional index, dropping bbox/header/fillable metadata.
    For list-of-lists, renders as compact markdown. Falls back to formatted body.
    """

    if isinstance(table_body, list) and table_body:
        # Cell dict format (MinerU/docling): [{text, bbox, start_row_offset_idx, ...}, ...]
        if all(isinstance(c, dict) and "text" in c for c in table_body):
            rows = {}
            for cell in table_body:
                row_idx = cell.get("start_row_offset_idx", 0)
                col_idx = cell.get("start_col_offset_idx", 0)
                text = cell.get("text", "").strip()
                if row_idx not in rows:
                    rows[row_idx] = []
                rows[row_idx].append((col_idx, text))
            lines = []
            for row_idx in sorted(rows.keys()):
                cells = [t for _, t in sorted(rows[row_idx])]
                lines.append("| " + " | ".join(cells) + " |")
            result = "\n".join(lines)
            if len(result) > max_chars:
                result = result[:max_chars] + "\n...（表格数据过长，已截断）"
            return result

        # List-of-lists format: render compact markdown
        if all(isinstance(row, (list, tuple)) for row in table_body):
            lines = []
            for row in table_body[:50]:  # cap at 50 rows
                lines.append(
                    "| " + " | ".join(str(cell)[:80] for cell in row[:20]) + " |"
                )
            result = "\n".join(lines)
            if len(result) > max_chars:
                result = result[:max_chars] + "\n...（表格数据过长，已截断）"
            return result

    # Fallback: use existing formatter
    result = format_table_body(table_body)
    if len(result) > max_chars:
        result = result[:max_chars] + "\n...（已截断）"
    return result


def get_equation_text_and_format(item: Dict[str, Any]) -> Tuple[str, str]:
    """Read equation content while preserving LaTeX aliases from content lists.

    Field priority follows MinerU first (``text`` + ``text_format``), then
    falls back to ``latex`` and ``equation`` aliases used by other parsers.
    The textual description is intentionally NOT concatenated into the
    equation body: the ``equation_chunk`` template has a separate
    ``enhanced_caption`` slot for that.
    """
    text = str(item.get("text", "") or "").strip()
    latex = str(item.get("latex", "") or "").strip()
    equation = str(item.get("equation", "") or "").strip()
    equation_format = str(item.get("text_format", "") or "").strip()

    if text:
        equation_text = text
    elif latex:
        equation_text = latex
        if not equation_format:
            equation_format = "latex"
    elif equation:
        equation_text = equation
    else:
        equation_text = ""

    return equation_text, equation_format


def extract_section_path_from_content_list(
    content_list: List[Dict[str, Any]], current_index: int
) -> str:
    """Build a hierarchical section path from preceding heading blocks.

    MinerU content lists keep document order, and heading blocks are exposed as
    text items with a positive ``text_level``.  For a given item index, we walk
    the preceding items and keep the latest heading at each level to reconstruct
    a stable chapter/section path such as ``Introduction > Method > Ablation``.
    """
    if not content_list or current_index is None:
        return ""

    try:
        limit = max(0, int(current_index))
    except (TypeError, ValueError):
        return ""

    heading_chain: List[Tuple[int, str]] = []

    for item in content_list[:limit]:
        if not isinstance(item, dict):
            continue

        if item.get("type", "text") != "text":
            continue

        text = str(item.get("text", "") or "").strip()
        if not text:
            continue

        try:
            level = int(item.get("text_level", 0) or 0)
        except (TypeError, ValueError):
            continue

        if level <= 0:
            continue

        while heading_chain and heading_chain[-1][0] >= level:
            heading_chain.pop()
        heading_chain.append((level, text))

    return " > ".join(text for _, text in heading_chain)


def extract_neighbor_text_from_content_list(
    content_list: List[Dict[str, Any]], current_index: int, window_size: int = 3
) -> str:
    """Collect nearby text blocks around an item index from MinerU content list."""
    if not content_list or current_index is None:
        return ""

    try:
        idx = int(current_index)
    except (TypeError, ValueError):
        return ""

    if idx < 0 or idx >= len(content_list):
        return ""

    start_idx = max(0, idx - window_size)
    end_idx = min(len(content_list), idx + window_size + 1)

    parts: List[str] = []
    for pos in range(start_idx, end_idx):
        if pos == idx:
            continue
        item = content_list[pos]
        if not isinstance(item, dict):
            continue
        if item.get("type", "text") != "text":
            continue

        text = str(item.get("text", "") or "").strip()
        if text:
            parts.append(text)

    return " ".join(parts)


def separate_content(
    content_list: List[Dict[str, Any]],
) -> Tuple[str, List[Dict[str, Any]]]:
    """
    Separate text content and multimodal content

    Args:
        content_list: Content list from MinerU parsing

    Returns:
        (text_content, multimodal_items): Pure text content and multimodal items list
    """
    text_parts = []
    multimodal_items = []

    for index, item in enumerate(content_list):
        content_type = item.get("type", "text")

        if content_type == "text":
            text = item.get("text", "")
            if text.strip():
                text_parts.append(text)
        else:
            multimodal_item = dict(item)
            multimodal_item.setdefault("_content_list_index", index)
            if content_type == "image":
                multimodal_item.setdefault(
                    "_section_path",
                    extract_section_path_from_content_list(content_list, index),
                )
                multimodal_item.setdefault(
                    "_neighbor_text",
                    extract_neighbor_text_from_content_list(content_list, index),
                )
            elif content_type == "video":
                multimodal_item.setdefault("_content_list_index", index)
            multimodal_items.append(multimodal_item)

    text_content = "\n\n".join(text_parts)

    logger.info("Content separation complete:")
    logger.info(f"  - Text content length: {len(text_content)} characters")
    logger.info(f"  - Multimodal items count: {len(multimodal_items)}")

    modal_types = {}
    for item in multimodal_items:
        modal_type = item.get("type", "unknown")
        modal_types[modal_type] = modal_types.get(modal_type, 0) + 1

    if modal_types:
        logger.info(f"  - Multimodal type distribution: {modal_types}")

    return text_content, multimodal_items
