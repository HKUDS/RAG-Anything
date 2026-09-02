"""Adapters for MinerU structured content-list output.

MinerU 3.x can emit ``*_content_list_v2.json`` as a list of pages, while
RAG-Anything's processing pipeline consumes a flat list of content blocks.
This module keeps that schema conversion independent from file-system access
so it can be tested without installing or running MinerU.
"""

from __future__ import annotations

import posixpath

import logging
from collections.abc import Mapping
from typing import Any

logger = logging.getLogger(__name__)


class MineruContentListV2Error(ValueError):
    """Raised when a value cannot be interpreted as a MinerU v2 content list."""


MINERU_V2_LAYOUT_TYPES = frozenset(
    {
        "page_header",
        "page_footer",
        "page_number",
        "page_aside_text",
        "page_footnote",
    }
)

_TEXT_TYPES = frozenset(
    {
        "title",
        "paragraph",
        # Keep direct block forms for forward compatibility with backends that
        # expose the pre-normalized layout types instead of paragraph.
        "abstract",
        "phonetic",
        "text",
    }
)
_LIST_TYPES = frozenset({"list", "index"})
_INLINE_EQUATION_TYPES = frozenset({"equation_inline", "inline_equation"})
_REFERENCE_TYPES = frozenset({"ref_text"})

_KNOWN_BLOCK_TYPES = frozenset(
    {
        *_TEXT_TYPES,
        *_LIST_TYPES,
        *_INLINE_EQUATION_TYPES,
        *_REFERENCE_TYPES,
        "image",
        "table",
        "equation_interline",
        "chart",
        "code",
        "algorithm",
        *MINERU_V2_LAYOUT_TYPES,
    }
)


def convert_mineru_content_list_v2(
    payload: Any,
    *,
    include_layout_blocks: bool = False,
) -> list[dict[str, Any]]:
    """Convert MinerU's page-grouped v2 output to RAG-Anything's flat schema.

    Args:
        payload: Parsed JSON value. The v2 schema is ``list[list[dict]]``.
        include_layout_blocks: Keep page headers, footers, page numbers,
            aside text, and page footnotes when ``True``. They are excluded
            by default because they are layout artifacts rather than semantic
            document content.

    Returns:
        A flat list compatible with :func:`raganything.utils.separate_content`.

    Raises:
        MineruContentListV2Error: If the top-level shape is not a valid v2
            content list.
    """
    _validate_payload(payload)

    converted: list[dict[str, Any]] = []
    for page_idx, page in enumerate(payload):
        for block in page:
            item = _convert_block(
                block,
                page_idx,
                include_layout_blocks=include_layout_blocks,
            )
            if item is not None:
                converted.append(item)

    if not converted:
        raise MineruContentListV2Error(
            "MinerU content_list_v2 does not contain any supported content blocks"
        )

    return converted


def _validate_payload(payload: Any) -> None:
    if not isinstance(payload, list) or not payload:
        raise MineruContentListV2Error(
            "MinerU content_list_v2 must be a non-empty list of pages"
        )

    has_block = False
    for page_idx, page in enumerate(payload):
        if not isinstance(page, list):
            raise MineruContentListV2Error(
                f"MinerU content_list_v2 page {page_idx} must be a list"
            )
        for block_idx, block in enumerate(page):
            has_block = True
            if not isinstance(block, Mapping):
                raise MineruContentListV2Error(
                    "MinerU content_list_v2 block "
                    f"{page_idx}:{block_idx} must be an object"
                )

    if not has_block:
        raise MineruContentListV2Error(
            "MinerU content_list_v2 does not contain any content blocks"
        )


def _convert_block(
    block: Mapping[str, Any],
    page_idx: int,
    *,
    include_layout_blocks: bool,
) -> dict[str, Any] | None:
    block_type = block.get("type")
    if not isinstance(block_type, str) or not block_type.strip():
        logger.warning("Skipping MinerU content_list_v2 block without a type")
        return None
    block_type = block_type.strip()

    if block_type not in _KNOWN_BLOCK_TYPES:
        logger.warning(
            "Skipping unsupported MinerU content_list_v2 type: %s", block_type
        )
        return None

    if block_type in MINERU_V2_LAYOUT_TYPES:
        if not include_layout_blocks:
            return None
        content = _block_content(block)
        text = _text_value(
            content.get(f"{block_type}_content", content.get("text", content))
        ).strip()
        if not text:
            return None
        return _finish_item(
            {"type": block_type, "text": text}, block, page_idx, block_type
        )

    content = _block_content(block)

    if block_type in _INLINE_EQUATION_TYPES:
        equation_text = _text_value(
            content.get("math_content", content.get("text", content))
        ).strip()
        if not equation_text:
            return None
        if not equation_text.startswith("$"):
            equation_text = f"${equation_text}$"
        return _finish_item(
            {"type": "text", "text": equation_text},
            block,
            page_idx,
            block_type,
        )

    if block_type in _TEXT_TYPES:
        content_key = f"{block_type}_content"
        text = _text_value(
            content.get(
                content_key, content.get("text", content.get("content", content))
            )
        ).strip()
        if not text:
            return None

        item: dict[str, Any] = {"type": "text", "text": text}
        if block_type == "title":
            level = _positive_int(content.get("level", block.get("level")))
            if level is not None:
                item["text_level"] = level
        return _finish_item(item, block, page_idx, block_type)

    if block_type in _LIST_TYPES:
        list_items = _list_items(content.get("list_items", []))
        if not list_items:
            fallback_text = _text_value(content.get("text", content)).strip()
            if fallback_text:
                list_items = [fallback_text]
        if not list_items:
            return None

        item = {
            "type": "text",
            "text": "\n".join(list_items),
            "list_items": list_items,
        }
        list_type = content.get("list_type")
        if isinstance(list_type, str) and list_type:
            item["list_type"] = list_type
        attribute = content.get("attribute")
        if isinstance(attribute, str) and attribute:
            item["list_attribute"] = attribute
        return _finish_item(item, block, page_idx, block_type)

    if block_type in _REFERENCE_TYPES:
        text = _text_value(
            content.get(
                "ref_text_content", content.get("text", content.get("content", content))
            )
        ).strip()
        if not text:
            return None
        return _finish_item(
            {"type": "text", "text": text, "list_type": "reference_list"},
            block,
            page_idx,
            block_type,
        )

    if block_type == "image":
        item = {"type": "image", "img_path": ""}
        image_path = _source_path(content.get("image_source"))
        if image_path:
            item["img_path"] = image_path
        visual_content = _text_value(content.get("content", "")).strip()
        if visual_content:
            item["content"] = visual_content
        _copy_captions(item, content, "image")
        return _finish_item(item, block, page_idx, block_type)

    if block_type == "table":
        item = {"type": "table"}
        table_path = _source_path(content.get("image_source"))
        if table_path:
            item["img_path"] = table_path
        table_body = content.get("html")
        if table_body in (None, ""):
            table_body = content.get("table_body", content.get("table_data"))
        if table_body not in (None, ""):
            item["table_body"] = table_body
        _copy_captions(item, content, "table")
        for key in ("table_type", "table_nest_level"):
            if key in content:
                item[key] = content[key]
        return _finish_item(item, block, page_idx, block_type)

    if block_type == "equation_interline":
        item = {"type": "equation"}
        equation_text = _text_value(
            content.get("math_content", content.get("text", content.get("latex", "")))
        ).strip()
        if equation_text:
            item["text"] = equation_text
        equation_format = content.get("math_type", content.get("text_format"))
        if isinstance(equation_format, str) and equation_format:
            item["text_format"] = equation_format
        equation_path = _source_path(content.get("image_source"))
        if equation_path:
            item["img_path"] = equation_path
        return _finish_item(item, block, page_idx, block_type)

    if block_type == "chart":
        item = {"type": "chart"}
        chart_path = _source_path(content.get("image_source"))
        if chart_path:
            item["img_path"] = chart_path
        chart_content = _text_value(
            content.get("chart_content", content.get("content", ""))
        ).strip()
        if chart_content:
            item["content"] = chart_content
        _copy_captions(item, content, "chart")
        return _finish_item(item, block, page_idx, block_type)

    if block_type in {"code", "algorithm"}:
        content_key = "code_content" if block_type == "code" else "algorithm_content"
        code_content = _text_value(content.get(content_key, content.get("content", "")))
        item = {
            # The legacy flat contract represents algorithms as code blocks
            # distinguished by sub_type. Keep that contract for downstream
            # processors while retaining the original v2 type in metadata.
            "type": "code",
            "sub_type": block_type,
            "code_body": code_content.strip(),
        }
        if code_content.strip():
            item["content"] = code_content.strip()
        if block_type == "code" and content.get("code_language"):
            item["code_language"] = content["code_language"]
        caption_key = "code_caption" if block_type == "code" else "algorithm_caption"
        captions = _caption_values(content.get(caption_key))
        if captions:
            # Keep the source-specific field as well as the canonical legacy
            # alias so callers can inspect either representation.
            item[caption_key] = captions
            item["code_caption"] = captions
        footnote_key = "code_footnote" if block_type == "code" else "algorithm_footnote"
        footnotes = _caption_values(content.get(footnote_key))
        if footnotes:
            item[footnote_key] = footnotes
            item["code_footnote"] = footnotes
        return _finish_item(item, block, page_idx, block_type)

    raise AssertionError(f"Unhandled known MinerU content_list_v2 type: {block_type}")


def _finish_item(
    item: dict[str, Any],
    block: Mapping[str, Any],
    page_idx: int,
    block_type: str,
) -> dict[str, Any]:
    item["page_idx"] = _page_idx(block.get("page_idx"), page_idx)
    item["_mineru_v2_type"] = block_type

    bbox = block.get("bbox")
    if isinstance(bbox, (list, tuple)) and len(bbox) == 4:
        item["bbox"] = list(bbox)

    anchor = block.get("anchor")
    if isinstance(anchor, str) and anchor.strip():
        item["anchor"] = anchor.strip()

    sub_type = block.get("sub_type")
    if sub_type is None and isinstance(block.get("content"), Mapping):
        sub_type = block["content"].get("sub_type")
    if isinstance(sub_type, str) and sub_type.strip():
        item["sub_type"] = sub_type.strip()

    return item


def _block_content(block: Mapping[str, Any]) -> dict[str, Any]:
    content = block.get("content", {})
    if isinstance(content, Mapping):
        return dict(content)
    if content in (None, ""):
        return {}
    return {"content": content}


def _page_idx(value: Any, fallback: int) -> int:
    try:
        return int(value) if value is not None else fallback
    except (TypeError, ValueError):
        return fallback


def _positive_int(value: Any) -> int | None:
    try:
        value = int(value)
    except (TypeError, ValueError):
        return None
    return value if value > 0 else None


def _text_value(value: Any) -> str:
    """Extract visible text while retaining inline-equation semantics."""
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, (int, float, bool)):
        return str(value)
    if isinstance(value, Mapping):
        span_type = value.get("type")
        if isinstance(span_type, str) and span_type in _INLINE_EQUATION_TYPES:
            equation = _text_value(value.get("content", value.get("text", "")))
            if not equation:
                return ""
            if equation.startswith("$"):
                return equation
            return f"${equation}$"

        content = value.get("content")
        if content not in (None, ""):
            text = _text_value(content)
            if text:
                return text
        children = value.get("children")
        if children:
            return _text_value(children)
        for key in (
            "title_content",
            "paragraph_content",
            "math_content",
            "code_content",
            "algorithm_content",
            "text",
        ):
            if key in value:
                text = _text_value(value[key])
                if text:
                    return text
        return ""
    if isinstance(value, (list, tuple)):
        return _join_text_parts([_text_value(part) for part in value])
    return str(value).strip()


def _join_text_parts(parts: list[str]) -> str:
    """Join v2 spans without merging adjacent Latin words together."""
    result = ""
    for part in parts:
        if not part:
            continue
        if (
            result
            and not result[-1].isspace()
            and not part[0].isspace()
            and _needs_span_separator(result[-1], part[0])
        ):
            result += " "
        result += part
    return result.strip()


def _needs_span_separator(left: str, right: str) -> bool:
    if left.isspace() or right.isspace():
        return False
    if _is_cjk(left) or _is_cjk(right):
        return False
    return not (right in ",.;:!?)]}" or left in "([{")


def _is_cjk(char: str) -> bool:
    return "\u3400" <= char <= "\u9fff"


def _list_items(value: Any) -> list[str]:
    if not isinstance(value, (list, tuple)):
        text = _text_value(value)
        return [text] if text else []

    result: list[str] = []
    for entry in value:
        if isinstance(entry, Mapping):
            entry = entry.get(
                "item_content", entry.get("content", entry.get("text", entry))
            )
        text = _text_value(entry).strip()
        if text:
            result.append(text)
    return result


def _caption_values(value: Any) -> list[str]:
    if value in (None, ""):
        return []
    if isinstance(value, str):
        return [value.strip()] if value.strip() else []
    if isinstance(value, Mapping):
        text = _text_value(value)
        text = text.strip()
        return [text] if text else []
    if isinstance(value, (list, tuple)):
        if any(isinstance(entry, Mapping) and "type" in entry for entry in value):
            text = _text_value(value)
            return [text] if text else []
        result: list[str] = []
        for entry in value:
            result.extend(_caption_values(entry))
        return result
    text = _text_value(value)
    return [text] if text else []


def _copy_captions(
    item: dict[str, Any], content: Mapping[str, Any], prefix: str
) -> None:
    captions = _caption_values(content.get(f"{prefix}_caption"))
    footnotes = _caption_values(content.get(f"{prefix}_footnote"))
    if captions:
        item[f"{prefix}_caption"] = captions
    if footnotes:
        item[f"{prefix}_footnote"] = footnotes


def _source_path(source: Any) -> str:
    if isinstance(source, Mapping):
        source = source.get("path", source.get("source", source.get("url", "")))
    if isinstance(source, str):
        source = source.strip()
        # A path with an empty basename (e.g. "images/") would resolve to a
        # directory downstream and surface as a misleading per-item
        # description error; treat it as no source.
        if posixpath.basename(source.replace("\\", "/")) in ("", ".", ".."):
            return ""
        return source
    return ""


__all__ = [
    "MINERU_V2_LAYOUT_TYPES",
    "MineruContentListV2Error",
    "convert_mineru_content_list_v2",
]
