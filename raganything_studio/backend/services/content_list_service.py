from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from fastapi import status

from raganything_studio.backend.core.errors import api_error
from raganything_studio.backend.schemas.document import DocumentRecord


class ContentListService:
    """Reads parser output content lists from a document output directory."""

    def get_content_list(self, document: DocumentRecord) -> list[dict[str, Any]]:
        output_dir = Path(document.output_dir)
        candidates = sorted(output_dir.rglob("*_content_list.json"))
        if not candidates:
            return _read_docling_items(output_dir)

        try:
            with candidates[0].open("r", encoding="utf-8") as input_file:
                payload = json.load(input_file)
        except Exception as exc:
            raise api_error(
                "CONTENT_LIST_READ_FAILED",
                f"Failed to read content list: {exc}",
                status.HTTP_500_INTERNAL_SERVER_ERROR,
            ) from exc

        if not isinstance(payload, list):
            raise api_error(
                "CONTENT_LIST_READ_FAILED",
                "Content list file did not contain a JSON array",
                status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

        return [item for item in payload if isinstance(item, dict)]


def _read_docling_items(output_dir: Path) -> list[dict[str, Any]]:
    candidates = [
        path for path in sorted(output_dir.rglob("*.json"))
        if not path.name.endswith("_content_list.json")
    ]
    if not candidates:
        return []

    try:
        payload = json.loads(candidates[0].read_text(encoding="utf-8"))
    except Exception as exc:
        raise api_error(
            "CONTENT_LIST_READ_FAILED",
            f"Failed to read Docling result: {exc}",
            status.HTTP_500_INTERNAL_SERVER_ERROR,
        ) from exc

    if not isinstance(payload, dict):
        return []

    items: list[dict[str, Any]] = []
    for text_item in payload.get("texts") or []:
        if not isinstance(text_item, dict):
            continue
        text = text_item.get("text")
        if not text:
            continue
        items.append(
            {
                "type": "text",
                "text": text,
                "label": text_item.get("label"),
                "page_idx": _page_idx(text_item),
            }
        )

    for picture in payload.get("pictures") or []:
        if isinstance(picture, dict):
            items.append(
                {
                    "type": "image",
                    "text": picture.get("caption") or picture.get("label") or "Image",
                    "label": picture.get("label"),
                    "page_idx": _page_idx(picture),
                }
            )

    for table in payload.get("tables") or []:
        if isinstance(table, dict):
            items.append(
                {
                    "type": "table",
                    "text": table.get("caption") or table.get("label") or "Table",
                    "label": table.get("label"),
                    "page_idx": _page_idx(table),
                }
            )

    return items


def _page_idx(item: dict[str, Any]) -> int | None:
    provenance = item.get("prov")
    if not isinstance(provenance, list) or not provenance:
        return None
    first = provenance[0]
    if not isinstance(first, dict):
        return None
    page_number = first.get("page_no")
    if not isinstance(page_number, int):
        return None
    return max(0, page_number - 1)
