"""
Utility functions for RAGAnything

Contains helper functions for content separation, text insertion, and other utilities
"""

from __future__ import annotations

import bisect
import base64
import inspect
import re
from typing import Dict, List, Any, Optional, Tuple
from pathlib import Path
from lightrag.utils import logger

from raganything.image_signature import SIGNATURE_BYTES, looks_like_image


def normalize_caption_list(value: Any) -> List[str]:
    """Return captions and footnotes as a clean list of strings."""
    if value is None:
        return []
    if isinstance(value, list):
        return [
            str(item).strip()
            for item in value
            if item is not None and str(item).strip()
        ]
    if isinstance(value, str) and value.strip():
        return [value.strip()]
    return []


def normalize_chart_item(item: Dict[str, Any]) -> Dict[str, Any]:
    """Use the image pipeline for charts with a rendered figure.

    Keep the parsed item unchanged: document IDs and parse caches use that
    original representation. Text-only charts continue through the generic
    processor.
    """
    if item.get("type") != "chart" or not item.get("img_path"):
        return item
    return {
        **item,
        "type": "image",
        "image_caption": normalize_caption_list(item.get("chart_caption"))
        + normalize_caption_list(item.get("content")),
        "image_footnote": normalize_caption_list(item.get("chart_footnote")),
    }


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
    Docling's ``TableData`` dict is rendered the same way from its ``grid``.
    Other shapes fall back to a newline-joined string of ``str(...)`` items.
    """
    if isinstance(table_body, str):
        return table_body
    grid = table_body.get("grid") if isinstance(table_body, dict) else None
    if isinstance(grid, list) and all(isinstance(row, list) for row in grid):
        # Docling's cells also carry a bounding box, offsets and header flags;
        # the table needs only their text. The grid repeats a spanning cell in
        # every position it covers.
        return format_table_body(
            [
                [cell.get("text") if isinstance(cell, dict) else cell for cell in row]
                for row in grid
            ]
        )
    if isinstance(table_body, list):
        if not table_body:
            return ""
        if all(isinstance(row, (list, tuple)) for row in table_body):
            column_count = max(len(row) for row in table_body)
            # Every row gets every column, so a short row cannot shift the ones
            # after it, and each cell stays one cell (see _table_cell).
            rendered_rows = [
                "| "
                + " | ".join(
                    _table_cell(row[i] if i < len(row) else None)
                    for i in range(column_count)
                )
                + " |"
                for row in table_body
            ]
            separator = "| " + " | ".join(["---"] * column_count) + " |"
            rendered_rows.insert(1, separator)
            return "\n".join(rendered_rows)
        return "\n".join(str(row) for row in table_body)
    return str(table_body)


def _table_cell(cell: Any) -> str:
    """One cell of a Markdown table row.

    An empty cell (``None``) stays empty instead of reading "None"; a pipe is
    escaped and a line break becomes a space, since either would otherwise end
    the cell or the row early.
    """
    if cell is None:
        return ""
    text = str(cell).replace("\r\n", " ").replace("\r", " ").replace("\n", " ")
    return text.replace("|", "\\|")


_CONTINUATION_MARKER_RE = re.compile(
    r"(?i)^(?:"
    r"table\s*\d*.*\(?\bcont(?:inued|\.)?\b\)?"
    r"|.*\bcont(?:inued|\.)\b.*"
    r"|continued(?:\s+from\s+previous\s+page|\s+on\s+next\s+page)?"
    r"|续表.*"
    r"|.*\(续\).*"
    r"|表\s*\d+.*续.*"
    r")$"
)

_MD_SEPARATOR_CELL_RE = re.compile(r"^:?-{2,}:?$")
_HTML_TR_RE = re.compile(r"<tr\b[^>]*>.*?</tr>", flags=re.IGNORECASE | re.DOTALL)
_HTML_CELL_RE = re.compile(
    r"<t[dh]\b([^>]*)>(.*?)</t[dh]>", flags=re.IGNORECASE | re.DOTALL
)
_HTML_COLSPAN_RE = re.compile(r"\bcolspan\s*=\s*['\"]?(\d+)", flags=re.IGNORECASE)
_HTML_TAG_STRIP_RE = re.compile(r"<[^>]+>")


def _is_continuation_caption(text: str) -> bool:
    """Return True if a short caption/text line marks a continued table."""
    cleaned = str(text or "").strip()
    if not cleaned or len(cleaned) > 100:
        return False
    return bool(_CONTINUATION_MARKER_RE.match(cleaned))


def _is_ignorable_intervening_block(item: Dict[str, Any]) -> bool:
    """Return True if an item between two page-boundary tables is empty or a continuation label."""
    if not isinstance(item, dict):
        return False
    if item.get("type", "text") != "text":
        return False
    text = str(item.get("text", "") or "").strip()
    if not text:
        return True
    return _is_continuation_caption(text)


def _split_md_row(line: str) -> Optional[List[str]]:
    """Parse a single Markdown pipe-table row into cell strings, or None if not a pipe row."""
    stripped = line.strip()
    if "|" not in stripped:
        return None
    if stripped.startswith("|"):
        stripped = stripped[1:]
    if stripped.endswith("|") and not stripped.endswith("\\|"):
        stripped = stripped[:-1]
    cells = [cell.strip() for cell in re.split(r"(?<!\\)\|", stripped)]
    return cells if cells else None


def _is_md_separator_row(cells: List[str]) -> bool:
    """Return True if all cells in a parsed Markdown row are alignment/separator dashes."""
    return bool(cells) and all(
        bool(_MD_SEPARATOR_CELL_RE.match(c.strip())) for c in cells
    )


def _try_merge_markdown_tables(prev_body: str, curr_body: str) -> Optional[str]:
    """Merge two Markdown pipe tables if their column counts match."""
    prev_lines = [ln.strip() for ln in prev_body.strip().splitlines() if ln.strip()]
    curr_lines = [ln.strip() for ln in curr_body.strip().splitlines() if ln.strip()]
    if not prev_lines or not curr_lines:
        return None

    prev_rows = [_split_md_row(ln) for ln in prev_lines]
    curr_rows = [_split_md_row(ln) for ln in curr_lines]
    if any(r is None for r in prev_rows) or any(r is None for r in curr_rows):
        return None

    prev_col_counts = {
        len(r) for r in prev_rows if r is not None and not _is_md_separator_row(r)
    }
    curr_col_counts = {
        len(r) for r in curr_rows if r is not None and not _is_md_separator_row(r)
    }
    if (
        len(prev_col_counts) != 1
        or len(curr_col_counts) != 1
        or prev_col_counts != curr_col_counts
    ):
        return None

    n_cols = next(iter(prev_col_counts))
    if n_cols < 1:
        return None

    prev_header_norm = [c.lower() for c in prev_rows[0]]

    # Filter curr_lines: drop separator lines and drop repeated header row if it matches prev_rows[0]
    appended_lines: List[str] = []
    checked_first_non_sep = False
    for line, cells in zip(curr_lines, curr_rows):
        if _is_md_separator_row(cells):
            continue
        if not checked_first_non_sep:
            checked_first_non_sep = True
            if [c.lower() for c in cells] == prev_header_norm:
                continue
        appended_lines.append(line)

    if not appended_lines:
        return prev_body.strip()

    # Ensure prev_lines has a separator row if it only had 1 line
    merged_lines = list(prev_lines)
    if not any(_is_md_separator_row(r) for r in prev_rows if r is not None):
        sep = "| " + " | ".join(["---"] * n_cols) + " |"
        merged_lines.insert(1, sep)

    merged_lines.extend(appended_lines)
    return "\n".join(merged_lines)


def _html_row_signature(tr_html: str) -> Tuple[int, List[str]]:
    """Return (effective_column_count, normalized_cell_texts) for an HTML <tr> block."""
    cells = _HTML_CELL_RE.findall(tr_html)
    if not cells:
        return 0, []
    col_count = 0
    norm_texts: List[str] = []
    for attrs, inner in cells:
        m = _HTML_COLSPAN_RE.search(attrs or "")
        span = int(m.group(1)) if m else 1
        col_count += max(1, span)
        text = _HTML_TAG_STRIP_RE.sub("", inner or "").strip().lower()
        text = re.sub(r"\s+", " ", text)
        norm_texts.append(text)
    return col_count, norm_texts


def _try_merge_html_tables(prev_body: str, curr_body: str) -> Optional[str]:
    """Merge two HTML <table> blocks if their column counts match."""
    if "<table" not in prev_body.lower() or "<table" not in curr_body.lower():
        return None

    prev_trs = _HTML_TR_RE.findall(prev_body)
    curr_trs = _HTML_TR_RE.findall(curr_body)
    if not prev_trs or not curr_trs:
        return None

    prev_sigs = [_html_row_signature(tr) for tr in prev_trs]
    curr_sigs = [_html_row_signature(tr) for tr in curr_trs]

    prev_cols = prev_sigs[0][0]
    curr_cols = curr_sigs[0][0]
    if prev_cols <= 0 or prev_cols != curr_cols:
        return None

    # Deduplicate repeated header row(s) at the start of curr_trs
    start_idx = 0
    while (
        start_idx < len(curr_trs)
        and start_idx < len(prev_trs)
        and curr_sigs[start_idx][1] == prev_sigs[start_idx][1]
    ):
        start_idx += 1

    remaining_trs = curr_trs[start_idx:]
    if not remaining_trs:
        return prev_body

    insertion = "\n".join(remaining_trs)
    close_tbody = re.search(r"</tbody\s*>", prev_body, flags=re.IGNORECASE)
    if close_tbody:
        pos = close_tbody.start()
        return f"{prev_body[:pos]}{insertion}\n{prev_body[pos:]}"

    close_table = re.search(r"</table\s*>", prev_body, flags=re.IGNORECASE)
    if close_table:
        pos = close_table.start()
        return f"{prev_body[:pos]}{insertion}\n{prev_body[pos:]}"

    return None


def _can_merge_table_captions(
    prev_captions: List[str], curr_captions: List[str]
) -> bool:
    """Return False if curr_captions introduces a different explicit table title."""
    if not curr_captions:
        return True
    if all(_is_continuation_caption(c) for c in curr_captions):
        return True
    prev_norm = {c.strip().lower() for c in prev_captions if c.strip()}
    curr_norm = {
        c.strip().lower()
        for c in curr_captions
        if c.strip() and not _is_continuation_caption(c)
    }
    if not curr_norm:
        return True
    return bool(prev_norm and curr_norm.issubset(prev_norm))


def merge_continued_tables(content_list: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Merge multi-page continued tables across consecutive pages into a single table item.

    Two ``type == "table"`` blocks are merged when:
    1. They appear on consecutive pages (``curr_page in (prev_end_page, prev_end_page + 1)``).
    2. All intervening items in ``content_list`` are empty text blocks or continuation
       markers (e.g. ``"Table 1 (continued)"``, ``"续表"``).
    3. The second table does not carry a conflicting table caption (e.g. ``"Table 2"``).
    4. Their table bodies (HTML ``<table>`` or Markdown pipe tables) have matching
       column counts. Repeated header rows at the top of the continuation table
       are automatically deduplicated.

    Returns a new list without mutating the input dictionaries.
    """
    if not content_list or len(content_list) < 2:
        return list(content_list) if content_list else []

    result: List[Dict[str, Any]] = [
        dict(item) if isinstance(item, dict) else item for item in content_list
    ]

    i = 0
    while i < len(result):
        item = result[i]
        if not isinstance(item, dict) or item.get("type") != "table":
            i += 1
            continue

        prev_page = item.get("page_idx")
        if not isinstance(prev_page, int) or isinstance(prev_page, bool):
            i += 1
            continue

        # Look ahead across ignorable intervening blocks for the next table
        j = i + 1
        while j < len(result) and _is_ignorable_intervening_block(result[j]):
            j += 1

        if j >= len(result):
            i += 1
            continue

        next_item = result[j]
        if not isinstance(next_item, dict) or next_item.get("type") != "table":
            i += 1
            continue

        curr_page = next_item.get("page_idx")
        if not isinstance(curr_page, int) or isinstance(curr_page, bool):
            i += 1
            continue

        prev_end_page = item.get("page_idx_end", prev_page)
        if not isinstance(prev_end_page, int) or isinstance(prev_end_page, bool):
            prev_end_page = prev_page

        if curr_page not in (prev_end_page, prev_end_page + 1):
            i += 1
            continue

        prev_captions = normalize_caption_list(item.get("table_caption"))
        curr_captions = normalize_caption_list(next_item.get("table_caption"))
        if not _can_merge_table_captions(prev_captions, curr_captions):
            i += 1
            continue

        prev_body_str = format_table_body(get_table_body(item))
        curr_body_str = format_table_body(get_table_body(next_item))

        merged_body = _try_merge_html_tables(prev_body_str, curr_body_str)
        if merged_body is None:
            merged_body = _try_merge_markdown_tables(prev_body_str, curr_body_str)

        if merged_body is None:
            i += 1
            continue

        # Merge succeeded: update item in place (already a shallow copy) and remove i+1..j
        item["table_body"] = merged_body
        if "table_data" in item:
            item.pop("table_data", None)

        combined_captions = list(prev_captions)
        for cap in curr_captions:
            if cap not in combined_captions and not _is_continuation_caption(cap):
                combined_captions.append(cap)
        if combined_captions or "table_caption" in item or "table_caption" in next_item:
            item["table_caption"] = combined_captions

        prev_footnotes = normalize_caption_list(item.get("table_footnote"))
        curr_footnotes = normalize_caption_list(next_item.get("table_footnote"))
        combined_footnotes = list(prev_footnotes)
        for fn in curr_footnotes:
            if fn not in combined_footnotes:
                combined_footnotes.append(fn)
        if (
            combined_footnotes
            or "table_footnote" in item
            or "table_footnote" in next_item
        ):
            item["table_footnote"] = combined_footnotes

        next_end_page = next_item.get("page_idx_end", curr_page)
        if not isinstance(next_end_page, int) or isinstance(next_end_page, bool):
            next_end_page = curr_page
        if next_end_page > prev_page:
            item["page_idx_end"] = next_end_page

        # Remove the ignorable intervening blocks and the merged continuation table,
        # then stay at index i so 3+ page tables continue merging seamlessly.
        del result[i + 1 : j + 1]

    return result


def get_equation_text_and_format(item: Dict[str, Any]) -> Tuple[str, str]:
    """Read equation content while preserving LaTeX aliases from content lists.

    An explicit ``latex`` formula comes first: in the documented content-list
    format (``{"type": "equation", "latex": ..., "text": "<description>"}``)
    ``text`` is a description, not the formula. Otherwise MinerU's ``text``
    (+ ``text_format``) is the formula, then the ``equation`` alias used by
    other parsers. A textual description is intentionally NOT concatenated
    into the equation body (the ``equation_chunk`` template has a separate
    ``enhanced_caption`` slot); :func:`get_equation_description` reads it.
    """
    text = str(item.get("text", "") or "").strip()
    latex = str(item.get("latex", "") or "").strip()
    equation = str(item.get("equation", "") or "").strip()
    equation_format = str(item.get("text_format", "") or "").strip()

    if latex:
        equation_text = latex
        if not equation_format:
            equation_format = "latex"
    elif text:
        equation_text = text
    elif equation:
        equation_text = equation
    else:
        equation_text = ""

    return equation_text, equation_format


def get_equation_description(item: Dict[str, Any]) -> str:
    """The description an equation item gives next to its ``latex`` formula.

    Only the documented content-list format has one (``text`` beside
    ``latex``); in MinerU items ``text`` is the formula itself, so this
    returns ``""`` for them.
    """
    latex = str(item.get("latex", "") or "").strip()
    text = str(item.get("text", "") or "").strip()
    return text if latex and text != latex else ""


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
        _update_heading_chain(item, heading_chain)

    return " > ".join(text for _, text in heading_chain)


def _update_heading_chain(
    item: Dict[str, Any], heading_chain: List[Tuple[int, str]]
) -> None:
    """Advance the heading hierarchy by one content block."""
    if not isinstance(item, dict):
        return

    if item.get("type", "text") != "text":
        return

    text = str(item.get("text", "") or "").strip()
    if not text:
        return

    try:
        level = int(item.get("text_level", 0) or 0)
    except (TypeError, ValueError):
        return

    if level <= 0:
        return

    while heading_chain and heading_chain[-1][0] >= level:
        heading_chain.pop()
    heading_chain.append((level, text))


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


def separate_content_with_page_map(
    content_list: List[Dict[str, Any]],
) -> Tuple[str, List[Dict[str, Any]], List[Tuple[int, int, Optional[int]]]]:
    """
    Separate text content, multimodal content, and per-block page provenance.

    Behaves exactly like :func:`separate_content` but additionally returns
    non-overlapping ``(start, end, page_idx)`` character intervals (into the
    returned ``text_content``) for every non-empty text block, in document
    order. ``page_idx`` is ``None`` for blocks without a usable int page, so
    later stages can step over them instead of guessing.

    Returns:
        (text_content, multimodal_items, page_intervals)
    """
    text_parts = []
    multimodal_items = []
    page_intervals: List[Tuple[int, int, Optional[int]]] = []
    text_length = 0
    heading_chain: List[Tuple[int, str]] = []

    for index, item in enumerate(content_list):
        _update_heading_chain(item, heading_chain)
        content_type = item.get("type", "text")

        if content_type == "text":
            # Text content
            text = str(item.get("text", "") or "")
            if text.strip():
                start = text_length + (2 if text_parts else 0)
                text_parts.append(text)
                end = start + len(text)
                text_length = end
                page_idx = item.get("page_idx")
                if not isinstance(page_idx, int) or isinstance(page_idx, bool):
                    page_idx = None
                page_intervals.append((start, end, page_idx))
        else:
            # Multimodal content (image, table, equation, etc.)
            multimodal_item = dict(normalize_chart_item(item))
            multimodal_item.setdefault("_content_list_index", index)
            if multimodal_item.get("type") == "image":
                multimodal_item.setdefault(
                    "_section_path",
                    " > ".join(text for _, text in heading_chain),
                )
                multimodal_item.setdefault(
                    "_neighbor_text",
                    extract_neighbor_text_from_content_list(content_list, index),
                )
            multimodal_items.append(multimodal_item)

    # Merge all text content
    text_content = "\n\n".join(text_parts)

    logger.info("Content separation complete:")
    logger.info(f"  - Text content length: {len(text_content)} characters")
    logger.info(f"  - Multimodal items count: {len(multimodal_items)}")

    # Count multimodal types
    modal_types = {}
    for item in multimodal_items:
        modal_type = item.get("type", "unknown")
        modal_types[modal_type] = modal_types.get(modal_type, 0) + 1

    if modal_types:
        logger.info(f"  - Multimodal type distribution: {modal_types}")

    return text_content, multimodal_items, page_intervals


def build_sanitized_page_map(
    text_content: str,
    page_intervals: List[Tuple[int, int, Optional[int]]],
) -> Tuple[str, List[Tuple[int, int, int]]]:
    """
    Re-express page intervals in the coordinates LightRAG actually chunks.

    LightRAG stores and chunks ``sanitize_text_for_encoding(text)``, not the
    raw text: it strips the ends, unescapes HTML entities and removes control
    and surrogate characters, all of which shift character offsets. Each
    block's own sanitized text is a contiguous substring of the sanitized
    document (the transformations never cross the ``"\n\n"`` separators), so
    blocks are located in document order with a forward cursor — repeated
    text such as a per-page footer maps to its own occurrence, not the first.

    Returns ``(sanitized_text, intervals)`` with intervals into
    ``sanitized_text``. Blocks that cannot be located are skipped rather than
    guessed.
    """
    from lightrag.utils import sanitize_text_for_encoding

    sanitized = sanitize_text_for_encoding(text_content)
    intervals: List[Tuple[int, int, int]] = []
    cursor = 0
    for start, end, page_idx in page_intervals:
        core = sanitize_text_for_encoding(text_content[start:end])
        if not core:
            continue
        position = sanitized.find(core, cursor)
        if position < 0:
            continue
        # Unpaginated blocks still advance the cursor, so a later block whose
        # text also occurs inside them cannot be placed there.
        cursor = position + len(core)
        if page_idx is not None:
            intervals.append((position, position + len(core), page_idx))
    return sanitized, intervals


# Tokens of context decoded around a stride boundary. A multi-byte
# character spans at most 4 bytes and every token covers at least one, so 8
# tokens always contain whatever character a boundary cuts through.
_BOUNDARY_CONTEXT_TOKENS = 8


def _stripped_span(text: str, offset: int) -> Optional[Tuple[int, int]]:
    """Span of ``text`` (found at ``offset``) without its edge whitespace."""
    lead = len(text) - len(text.lstrip())
    end = len(text.rstrip())
    if lead >= end:
        return None
    return offset + lead, offset + end


def _token_window_spans(
    tokenizer: Any, text: str, size: int, step: int
) -> Optional[List[Tuple[str, Optional[Tuple[int, int]]]]]:
    """Replay LightRAG's token windows over ``text`` with exact positions.

    For each window returns ``(decoded_window, span)``: ``span`` is where
    the window's text sits in ``text``, without edge whitespace and without
    the fragments of multi-byte characters cut at either end (``None`` if
    nothing is left). The character offset of token ``t`` is
    ``len(decode(tokens[:t]))`` — a cut multi-byte character decodes to one
    U+FFFD standing in its slot. That is computed incrementally from short
    overlapping decodes (the effect of a cut at ``a`` is identical in
    ``decode(tokens[a:x])`` for any ``x`` past the cut character), so the
    whole replay is linear.

    Exact for byte-level tokenizers whose decoder is local (tiktoken, byte
    BPE). A decoder that normalises text or adds or drops characters between
    tokens fails the round-trip, cut or per-window checks and returns
    ``None``. One that replaces a whole invalid byte run (HF ``ByteFallback``)
    can pass them where the text itself holds U+FFFD; the span may then take
    in neighbouring U+FFFD, which never crosses into another block because
    the ``"\n\n"`` between blocks cannot match them.
    """
    tokens = tokenizer.encode(text)
    full = tokenizer.decode(tokens)
    if full != text:
        return None
    context = _BOUNDARY_CONTEXT_TOKENS
    total = len(tokens)
    decode = tokenizer.decode
    # Boundaries recur (a window end can be a later window start), so each
    # one is probed once per call. ``heads`` keeps the length of the decode
    # just before each probed boundary, which is also the second term of the
    # offset update once that boundary is the previous window start.
    fragments: Dict[int, int] = {}
    heads: Dict[int, int] = {}

    def cut_fragments(boundary: int) -> int:
        """Extra characters decoding splits at ``boundary`` creates: 0 when
        it falls between characters, else the U+FFFD standing in for the
        cut character's continuation bytes."""
        if boundary <= 0 or boundary >= total:
            return 0
        count = fragments.get(boundary)
        if count is None:
            head = boundary - context if boundary > context else 0
            tail = boundary + context
            head_length = heads[boundary] = len(decode(tokens[head:boundary]))
            count = fragments[boundary] = (
                head_length
                + len(decode(tokens[boundary:tail]))
                - len(decode(tokens[head:tail]))
            )
        return count

    windows: List[Tuple[str, Optional[Tuple[int, int]]]] = []
    append = windows.append
    offset = 0  # len(decode(tokens[:start]))
    previous = 0
    for start in range(0, total, step):
        if start > previous:
            # Every window start but 0 was probed as a boundary.
            anchor = previous - context if previous > context else 0
            head_length = heads.get(previous)
            if head_length is None:
                head_length = len(decode(tokens[anchor:previous]))
            offset += len(decode(tokens[anchor:start])) - head_length
        previous = start
        end = start + size
        raw = full if start == 0 and end >= total else decode(tokens[start:end])
        # A character cut at the start leaves leading U+FFFD (its
        # continuation bytes) with no slot of their own in the source; one
        # cut at the end leaves a single U+FFFD (its leading bytes) in its
        # slot. Neither is text the chunk actually covers.
        stray = cut_fragments(start)
        end_fragments = cut_fragments(end)
        if stray < 0 or end_fragments < 0:
            return None
        # An empty prefix of a str always matches; skip building it.
        if (stray or type(raw) is not str) and raw[:stray] != "\ufffd" * min(
            stray, len(raw)
        ):
            return None
        length = len(raw)
        cut_end = 1 if end_fragments else 0
        if stray >= length:
            body = ""  # the window lies inside the one character cut at start
        else:
            if cut_end and not raw.endswith("\ufffd"):
                return None
            body = raw[stray : length - cut_end]
            if not text.startswith(body, offset):
                return None
        append((raw, _stripped_span(body, offset)))
    return windows


def replay_chunk_spans(
    tokenizer: Any,
    content: str,
    chunks: List[Dict[str, Any]],
    split_by_character: Optional[str],
    split_by_character_only: bool,
    chunk_overlap_token_size: int,
    chunk_token_size: int,
) -> Optional[List[List[Tuple[int, int]]]]:
    """
    Positions of the chunks LightRAG's ``chunking_by_token_size`` produced.

    The chunker is deterministic, so instead of searching for chunk text
    (which is ambiguous wherever text repeats) its geometry is replayed:
    ``split_by_character`` pieces sit at exact offsets in ``content``, and
    token windows — the whole text, or a piece too long for one chunk —
    start every ``chunk_token_size - chunk_overlap_token_size`` tokens.
    Positions are computed, never searched for, and the replay is checked
    against both the source text and what the chunker returned; any
    disagreement returns ``None`` and nothing is annotated.

    Returns, per chunk, a list holding the ``(start, end)`` span of the
    source text it covers (edge whitespace and fragments of cut multi-byte
    characters excluded), or an empty list when nothing is left.
    """
    step = chunk_token_size - chunk_overlap_token_size
    if step <= 0:
        return None
    replayed: List[Tuple[str, List[int]]] = []
    if split_by_character:
        offset = 0
        for piece in content.split(split_by_character):
            base = offset
            offset += len(piece) + len(split_by_character)
            if split_by_character_only or (
                len(tokenizer.encode(piece)) <= chunk_token_size
            ):
                replayed.append((piece, _stripped_span(piece, base)))
                continue
            windows = _token_window_spans(tokenizer, piece, chunk_token_size, step)
            if windows is None:
                return None
            replayed.extend(
                (raw, span and (base + span[0], base + span[1]))
                for raw, span in windows
            )
    else:
        windows = _token_window_spans(tokenizer, content, chunk_token_size, step)
        if windows is None:
            return None
        replayed = windows

    if len(replayed) != len(chunks):
        return None
    spans: List[List[Tuple[int, int]]] = []
    for chunk, (raw, span) in zip(chunks, replayed):
        if raw.strip() != chunk.get("content"):
            return None
        spans.append([span] if span is not None else [])
    return spans


def annotate_chunks_with_page_idx(
    chunks: List[Dict[str, Any]],
    chunk_spans: List[List[Tuple[int, int]]],
    page_intervals: List[Tuple[int, int, int]],
) -> List[Dict[str, Any]]:
    """
    Annotate chunks with the pages their spans overlap.

    ``chunk_spans`` holds candidate spans per chunk (see
    :func:`replay_chunk_spans`), in the same coordinates as
    ``page_intervals`` (see :func:`build_sanitized_page_map`). A chunk is
    annotated only when every candidate yields the same pages — so an
    ambiguous position never produces a guess. Chunks inside one interval
    get its ``page_idx``; chunks spanning several get the lowest page as
    ``page_idx`` and the highest as ``page_idx_end``. Returns the same list.
    """
    if not page_intervals:
        return chunks
    interval_ends = [end for _, end, _ in page_intervals]

    def pages_for(span: Tuple[int, int]) -> Optional[Tuple[int, int]]:
        start, end = span
        pages = []
        index = bisect.bisect_right(interval_ends, start)
        while index < len(page_intervals) and page_intervals[index][0] < end:
            pages.append(page_intervals[index][2])
            index += 1
        return (min(pages), max(pages)) if pages else None

    for chunk, candidates in zip(chunks, chunk_spans):
        labels = {pages_for(span) for span in candidates}
        if len(labels) != 1:
            continue
        label = labels.pop()
        if label is None:
            continue
        first, last = label
        chunk["page_idx"] = first
        if last != first:
            chunk["page_idx_end"] = last
    return chunks


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
    text_content, multimodal_items, _ = separate_content_with_page_map(content_list)
    return text_content, multimodal_items


def encode_image_to_base64(image_path: str) -> str:
    """
    Encode image file to base64 string

    Args:
        image_path: Path to the image file

    Returns:
        str: Base64 encoded string, empty string if encoding fails
    """
    try:
        with open(image_path, "rb") as image_file:
            data = image_file.read()
    except Exception as e:
        logger.error(f"Failed to encode image {image_path}: {e}")
        return ""
    # Check the bytes actually being sent, not an earlier look at the path.
    if not looks_like_image(data[:SIGNATURE_BYTES]):
        logger.warning(f"Not sending {image_path} to the vision model: not an image")
        return ""
    return base64.b64encode(data).decode("utf-8")


def validate_image_file(image_path: str, max_size_mb: int = 50) -> bool:
    """
    Validate if a file is a valid image file

    Args:
        image_path: Path to the image file
        max_size_mb: Maximum file size in MB

    Returns:
        bool: True if valid, False otherwise
    """
    try:
        path = Path(image_path)

        logger.debug(f"Validating image path: {image_path}")
        logger.debug(f"Resolved path object: {path}")
        logger.debug(f"Path exists check: {path.exists()}")

        # Check if file exists and is not a symlink (for security)
        if not path.exists():
            logger.warning(f"Image file not found: {image_path}")
            return False

        if path.is_symlink():
            logger.warning(f"Blocking symlink for security: {image_path}")
            return False

        # Check file extension
        image_extensions = [
            ".jpg",
            ".jpeg",
            ".png",
            ".gif",
            ".bmp",
            ".webp",
            ".tiff",
            ".tif",
        ]

        path_lower = str(path).lower()
        has_valid_extension = any(path_lower.endswith(ext) for ext in image_extensions)
        logger.debug(
            f"File extension check - path: {path_lower}, valid: {has_valid_extension}"
        )

        if not has_valid_extension:
            logger.warning(f"File does not appear to be an image: {image_path}")
            return False

        # Check file size
        file_size = path.stat().st_size
        max_size = max_size_mb * 1024 * 1024
        logger.debug(
            f"File size check - size: {file_size} bytes, max: {max_size} bytes"
        )

        if file_size > max_size:
            logger.warning(f"Image file too large ({file_size} bytes): {image_path}")
            return False

        with open(path, "rb") as image_file:
            if not looks_like_image(image_file.read(SIGNATURE_BYTES)):
                logger.warning(f"File content is not an image: {image_path}")
                return False

        logger.debug(f"Image validation successful: {image_path}")
        return True

    except Exception as e:
        logger.error(f"Error validating image file {image_path}: {e}")
        return False


async def insert_text_content(
    lightrag,
    input: str | list[str],
    split_by_character: str | None = None,
    split_by_character_only: bool = False,
    ids: str | list[str] | None = None,
    file_paths: str | list[str] | None = None,
):
    """
    Insert pure text content into LightRAG

    Args:
        lightrag: LightRAG instance
        input: Single document string or list of document strings
        split_by_character: if split_by_character is not None, split the string by character, if chunk longer than
        chunk_token_size, it will be split again by token size.
        split_by_character_only: if split_by_character_only is True, split the string by character only, when
        split_by_character is None, this parameter is ignored.
        ids: single string of the document ID or list of unique document IDs, if not provided, MD5 hash IDs will be generated
        file_paths: single string of the file path or list of file paths, used for citation

    Returns:
        Whatever ``ainsert`` returns: the insert's track_id on LightRAG 1.4.x.
    """
    logger.info("Starting text content insertion into LightRAG...")

    # Use LightRAG's insert method with all parameters
    track_id = await lightrag.ainsert(
        input=input,
        file_paths=file_paths,
        split_by_character=split_by_character,
        split_by_character_only=split_by_character_only,
        ids=ids,
    )

    logger.info("Text content insertion complete")
    return track_id


async def insert_text_content_with_multimodal_content(
    lightrag,
    input: str | list[str],
    multimodal_content: list[dict[str, any]] | None = None,
    split_by_character: str | None = None,
    split_by_character_only: bool = False,
    ids: str | list[str] | None = None,
    file_paths: str | list[str] | None = None,
    scheme_name: str | None = None,
):
    """
    Insert pure text content into LightRAG

    Args:
        lightrag: LightRAG instance
        input: Single document string or list of document strings
        multimodal_content: Multimodal content list (optional)
        split_by_character: if split_by_character is not None, split the string by character, if chunk longer than
        chunk_token_size, it will be split again by token size.
        split_by_character_only: if split_by_character_only is True, split the string by character only, when
        split_by_character is None, this parameter is ignored.
        ids: single string of the document ID or list of unique document IDs, if not provided, MD5 hash IDs will be generated
        file_paths: single string of the file path or list of file paths, used for citation
        scheme_name: scheme name (optional)
    """
    logger.info("Starting text content insertion into LightRAG...")

    insert_kwargs = {
        "input": input,
        "file_paths": file_paths,
        "split_by_character": split_by_character,
        "split_by_character_only": split_by_character_only,
        "ids": ids,
    }

    try:
        insert_signature = inspect.signature(lightrag.ainsert)
        supported_params = insert_signature.parameters
        accepts_any_kwargs = any(
            parameter.kind == inspect.Parameter.VAR_KEYWORD
            for parameter in supported_params.values()
        )
    except (TypeError, ValueError):
        supported_params = {}
        accepts_any_kwargs = True

    if multimodal_content is not None and (
        accepts_any_kwargs or "multimodal_content" in supported_params
    ):
        insert_kwargs["multimodal_content"] = multimodal_content
    elif multimodal_content is not None:
        logger.warning(
            "LightRAG ainsert() does not accept multimodal_content; "
            "retrying with text-only insertion so doc_status is still created"
        )

    if scheme_name is not None and (
        accepts_any_kwargs or "scheme_name" in supported_params
    ):
        insert_kwargs["scheme_name"] = scheme_name
    elif scheme_name is not None:
        logger.warning(
            "LightRAG ainsert() does not accept scheme_name; "
            "continuing without it for compatibility"
        )

    track_id = await lightrag.ainsert(**insert_kwargs)

    logger.info("Text content insertion complete")
    return track_id


def get_processor_for_type(modal_processors: Dict[str, Any], content_type: str):
    """
    Get appropriate processor based on content type

    Args:
        modal_processors: Dictionary of available processors
        content_type: Content type

    Returns:
        Corresponding processor instance
    """
    # Direct mapping to corresponding processor
    if content_type == "image":
        return modal_processors.get("image")
    elif content_type == "table":
        return modal_processors.get("table")
    elif content_type == "equation":
        return modal_processors.get("equation")
    elif content_type == "audio":
        # Fall back to generic when audio processing is disabled / deps missing
        return modal_processors.get("audio") or modal_processors.get("generic")
    elif content_type == "video":
        # Fall back to generic when video processing is disabled / deps missing
        return modal_processors.get("video") or modal_processors.get("generic")
    else:
        # For other types, use generic processor
        return modal_processors.get("generic")


def get_processor_supports(proc_type: str) -> List[str]:
    """Get processor supported features"""
    supports_map = {
        "image": [
            "Image content analysis",
            "Visual understanding",
            "Image description generation",
            "Image entity extraction",
        ],
        "table": [
            "Table structure analysis",
            "Data statistics",
            "Trend identification",
            "Table entity extraction",
        ],
        "equation": [
            "Mathematical formula parsing",
            "Variable identification",
            "Formula meaning explanation",
            "Formula entity extraction",
        ],
        "audio": [
            "Speech-to-text transcription",
            "Timestamped segment extraction",
            "Audio entity extraction",
        ],
        "video": [
            "Scene detection and keyframe analysis",
            "Visual + audio dual-channel understanding",
            "Video entity extraction",
        ],
        "generic": [
            "General content analysis",
            "Structured processing",
            "Entity extraction",
        ],
    }
    return supports_map.get(proc_type, ["Basic processing"])
