"""
Utility functions for RAGAnything

Contains helper functions for content separation, text insertion, and other utilities
"""

from __future__ import annotations

import bisect
import base64
import inspect
from typing import Dict, List, Any, Optional, Tuple
from pathlib import Path
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

    for index, item in enumerate(content_list):
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


# Extra room around a chunk's expected position: separators, stripped
# whitespace and U+FFFD edges between consecutive chunks.
_CHUNK_SEARCH_SLACK = 64
# A chunker whose output is not verbatim source text would otherwise be
# searched for on every chunk; give up after this many misses in a row.
_MAX_CONSECUTIVE_CHUNK_MISSES = 3
_MAX_CANDIDATES = 64


def _trim_edges(text: str) -> str:
    """Strip whitespace and U+FFFD from both ends until neither remains."""
    while True:
        trimmed = text.strip().strip("\ufffd")
        if trimmed == text:
            return text
        text = trimmed


def _chunk_needle(chunk: Dict[str, Any]) -> str:
    content = chunk.get("content")
    if not isinstance(content, str):
        return ""
    return _trim_edges(content)


def _occurrences(text: str, needle: str, low: int, high: int) -> List[int]:
    """Start offsets of ``needle`` lying entirely within ``text[low:high]``."""
    found: List[int] = []
    position = text.find(needle, max(low, 0), high)
    while position >= 0 and len(found) < _MAX_CANDIDATES:
        found.append(position)
        position = text.find(needle, position + 1, high)
    return found


def locate_chunk_spans(
    chunks: List[Dict[str, Any]],
    text: str,
    *,
    mode: str = "unknown",
    overlap_ratio: float = 0.0,
) -> List[Optional[Tuple[int, int]]]:
    """
    Locate each chunk of ``text`` as a ``(start, end)`` span, or ``None``.

    Chunks are expected in document order. ``mode`` describes how they were
    produced so that repeated text resolves to the right occurrence:

    - ``"token"``: LightRAG's token chunker — consecutive chunks overlap by
      ``overlap_ratio`` of a chunk, so a chunk starts near
      ``prev_start + (prev_end - prev_start) * (1 - overlap_ratio)``; the
      occurrence nearest that point is chosen, and the final chunk is
      anchored to the end of the text (a short tail would otherwise match an
      earlier copy of itself).
    - ``"split"``: LightRAG's ``split_by_character`` chunker — pieces do not
      overlap, so the first occurrence at or after the previous chunk's end
      is chosen.
    - ``"unknown"``: any other chunker — a chunk is located only when exactly
      one candidate exists; ambiguity yields ``None`` rather than a guess.

    Every search is confined to a window around the previous chunk, so the
    cost is linear in the text length.
    """
    spans: List[Optional[Tuple[int, int]]] = []
    previous: Optional[Tuple[int, int]] = None
    misses = 0
    last_index = len(chunks) - 1
    text_tail = _trim_edges(text)
    tail_end = text.find(text_tail) + len(text_tail) if text_tail else 0
    for index, chunk in enumerate(chunks):
        needle = _chunk_needle(chunk)
        if not needle or misses >= _MAX_CONSECUTIVE_CHUNK_MISSES:
            spans.append(None)
            continue
        if (
            mode == "token"
            and index == last_index
            and text.endswith(needle, 0, tail_end)
        ):
            # The token chunker's final window always runs to the end of the
            # text, so a short tail cannot sit anywhere else.
            spans.append((tail_end - len(needle), tail_end))
            continue
        if previous is None:
            low, expected = 0, 0
            high = len(needle) + _CHUNK_SEARCH_SLACK
        else:
            prev_start, prev_end = previous
            low = prev_start + 1
            high = prev_end + len(needle) + _CHUNK_SEARCH_SLACK
            expected = prev_start + round((prev_end - prev_start) * (1 - overlap_ratio))
        high = min(high, len(text))

        position: Optional[int] = None
        if mode == "split" and previous is not None:
            found = text.find(needle, max(low, previous[1]), high)
            position = found if found >= 0 else None
        if position is None:
            candidates = _occurrences(text, needle, low, high)
            if mode in ("token", "split") and candidates:
                position = min(candidates, key=lambda c: (abs(c - expected), c))
            elif len(candidates) == 1:
                position = candidates[0]

        if position is None:
            misses += 1
            spans.append(None)
            if mode == "token" and previous is not None:
                # keep the window moving with the chunker's stride
                previous = (expected, expected + len(needle))
            continue
        misses = 0
        previous = (position, position + len(needle))
        spans.append(previous)
    return spans


def annotate_chunks_with_page_idx(
    chunks: List[Dict[str, Any]],
    sanitized_text: str,
    page_intervals: List[Tuple[int, int, int]],
    logger: Any = None,
    *,
    mode: str = "unknown",
    overlap_ratio: float = 0.0,
) -> List[Dict[str, Any]]:
    """
    Annotate chunks produced from ``sanitized_text`` with their source page.

    ``page_intervals`` must be in ``sanitized_text`` coordinates (see
    :func:`build_sanitized_page_map`); chunks are located with
    :func:`locate_chunk_spans`. Chunks inside one interval get its
    ``page_idx``; chunks spanning several get the first page as ``page_idx``
    and the last as ``page_idx_end``. Chunks that cannot be located with
    confidence are left untouched — annotation must never break or mislabel
    ingestion. Returns the same list (mutated in place).
    """
    if not page_intervals:
        return chunks

    spans = locate_chunk_spans(
        chunks, sanitized_text, mode=mode, overlap_ratio=overlap_ratio
    )
    interval_ends = [end for _, end, _ in page_intervals]
    missed = 0
    for chunk, span in zip(chunks, spans):
        if span is None:
            if _chunk_needle(chunk):
                missed += 1
            continue
        offset, chunk_end = span
        pages = []
        index = bisect.bisect_right(interval_ends, offset)
        while index < len(page_intervals) and page_intervals[index][0] < chunk_end:
            pages.append(page_intervals[index][2])
            index += 1
        if pages:
            chunk["page_idx"] = min(pages)
            if max(pages) != min(pages):
                chunk["page_idx_end"] = max(pages)
    if missed and logger is not None:
        logger.warning(
            f"page_idx annotation: {missed} chunk(s) could not be located with "
            "confidence and carry no page_idx"
        )
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
            encoded_string = base64.b64encode(image_file.read()).decode("utf-8")
        return encoded_string
    except Exception as e:
        logger.error(f"Failed to encode image {image_path}: {e}")
        return ""


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
    """
    logger.info("Starting text content insertion into LightRAG...")

    # Use LightRAG's insert method with all parameters
    await lightrag.ainsert(
        input=input,
        file_paths=file_paths,
        split_by_character=split_by_character,
        split_by_character_only=split_by_character_only,
        ids=ids,
    )

    logger.info("Text content insertion complete")


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

    await lightrag.ainsert(**insert_kwargs)

    logger.info("Text content insertion complete")


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
