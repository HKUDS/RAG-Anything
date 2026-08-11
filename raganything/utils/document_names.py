"""Presentation-only helpers for uploaded document names."""

from __future__ import annotations

import os
import re


_STAGED_UPLOAD_PREFIX_RE = re.compile(
    r"^(?:[0-9a-f]{8}|[0-9a-f]{32})_(.+)$", re.IGNORECASE
)
_CITATION_LABEL_RE = re.compile(r"(\[来源\s*[：:]?\s*)([^\]]+)(\])")


def display_document_name(value: object, default: str = "") -> str:
    """Return a display name without changing its storage identity."""
    raw = str(value or "")
    if not raw:
        return default
    name = os.path.basename(raw.replace("\\", "/"))
    match = _STAGED_UPLOAD_PREFIX_RE.match(name)
    return match.group(1) if match else name


def normalize_citation_document_names(text: str) -> str:
    """Remove staged prefixes from document labels inside citation markers."""
    if not isinstance(text, str) or not text:
        return text
    return _CITATION_LABEL_RE.sub(
        lambda match: f"{match.group(1)}{display_document_name(match.group(2))}{match.group(3)}",
        text,
    )
