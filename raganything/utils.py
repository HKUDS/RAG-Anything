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


# Tokens of context decoded around a stride boundary. A multi-byte
# character spans at most 4 bytes and every token covers at least one, so 8
# tokens always contain whatever character a boundary cuts through.
_BOUNDARY_CONTEXT_TOKENS = 8


def _edge_trim_counts(text: str) -> Tuple[int, int]:
    """How many characters whitespace/U+FFFD trimming removes from each end."""
    start, end = 0, len(text)
    while start < end and (text[start].isspace() or text[start] == "\ufffd"):
        start += 1
    while end > start and (text[end - 1].isspace() or text[end - 1] == "\ufffd"):
        end -= 1
    return start, len(text) - end


def _needle_span(raw: str, raw_start: int) -> Optional[Tuple[int, int]]:
    """Span of ``raw`` once edge whitespace and U+FFFD are trimmed."""
    lead, trail = _edge_trim_counts(raw)
    if lead + trail >= len(raw):
        return None
    return raw_start + lead, raw_start + len(raw) - trail


def _token_window_starts(
    tokenizer: Any, text: str, size: int, step: int
) -> Optional[List[Tuple[str, int]]]:
    """Replay LightRAG's token windows over ``text`` with exact positions.

    For each window returns ``(decoded_window, raw_start)``: ``raw_start`` is
    the offset in ``text`` that index 0 of the decoded window lines up with.
    The character offset of token ``t`` is ``len(decode(tokens[:t]))`` —
    a cut multi-byte character decodes to one U+FFFD standing in its slot.
    That is computed incrementally from short overlapping decodes (the
    effect of a cut at ``a`` is identical in ``decode(tokens[a:x])`` for any
    ``x`` past the cut character), so the whole replay is linear. Each window
    is then checked against the source; any mismatch returns ``None``.
    """
    tokens = tokenizer.encode(text)
    context = _BOUNDARY_CONTEXT_TOKENS

    def decoded_length(begin: int, finish: int) -> int:
        return len(tokenizer.decode(tokens[max(begin, 0) : finish]))

    windows: List[Tuple[str, int]] = []
    offset = 0  # len(decode(tokens[:start]))
    previous = 0
    for start in range(0, len(tokens), step):
        if start > previous:
            anchor = max(0, previous - context)
            offset += decoded_length(anchor, start) - decoded_length(anchor, previous)
        previous = start
        raw = tokenizer.decode(tokens[start : start + size])
        # Continuation bytes of a character cut at `start` decode to extra
        # leading U+FFFD that have no slot of their own in the source.
        if start:
            anchor = max(0, start - context)
            stray = (
                decoded_length(anchor, start)
                + decoded_length(start, start + context)
                - decoded_length(anchor, start + context)
            )
        else:
            stray = 0
        raw_start = offset - stray
        # Everything but a possibly cut final character must match exactly.
        body_start = offset
        body = raw[stray : max(stray, len(raw) - 1)]
        if text[body_start : body_start + len(body)] != body:
            return None
        windows.append((raw, raw_start))
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

    Returns, per chunk, a list holding the ``(start, end)`` span of its
    stripped content, or an empty list when the chunk is blank.
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
                replayed.append((piece, [base]))
                continue
            windows = _token_window_starts(tokenizer, piece, chunk_token_size, step)
            if windows is None:
                return None
            replayed.extend((raw, [base + start]) for raw, start in windows)
    else:
        windows = _token_window_starts(tokenizer, content, chunk_token_size, step)
        if windows is None:
            return None
        replayed = [(raw, [start]) for raw, start in windows]

    if len(replayed) != len(chunks):
        return None
    spans: List[List[Tuple[int, int]]] = []
    for chunk, (raw, starts) in zip(chunks, replayed):
        if raw.strip() != chunk.get("content"):
            return None
        candidates = []
        for raw_start in starts:
            span = _needle_span(raw, raw_start)
            if span is not None:
                candidates.append(span)
        spans.append(candidates)
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
    get its ``page_idx``; chunks spanning several get the first page as
    ``page_idx`` and the last as ``page_idx_end``. Returns the same list.
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
