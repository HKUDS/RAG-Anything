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
            return []

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

