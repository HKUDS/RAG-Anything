"""
Optional mapping of local absolute media paths to public URLs (HTTPS, CDN, S3, etc.).

Implements the environment-variable contract described in docs and README:
when ingestion runs on a server but retrieval/UI runs elsewhere, stored paths
must remain valid locally while a parallel public URL can be shown to clients.

NOTE: ``attach_public_media_urls`` is currently invoked from the MinerU
parser path only. Other parsers (e.g. Docling) will not yield
``*_public_url`` fields until this helper is wired into their content_list
post-processing too.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

logger = logging.getLogger(__name__)

# content_list fields that hold filesystem paths to raster or figure assets
MEDIA_PATH_FIELDS: tuple[str, ...] = (
    "img_path",
    "table_img_path",
    "equation_img_path",
)

# Track which misconfiguration shape we have already warned about so we don't
# spam the log once per content_list item. Reset whenever the env state goes
# back to either "fully unset" or "fully set".
_MISCONFIG_WARNED: set[str] = set()


def _resolve_strip_prefix(strip_prefix: str) -> Path | None:
    try:
        return Path(strip_prefix).expanduser().resolve()
    except (OSError, RuntimeError):
        return None


def public_url_for_local_path(
    local_abs: str,
    *,
    base_url: str,
    strip_prefix: str,
) -> str | None:
    """
    Build ``https://.../relative/path`` from a local absolute path by stripping
    a known filesystem root and appending the remainder to ``base_url``.
    """
    if not local_abs or not base_url or not strip_prefix:
        return None
    root = _resolve_strip_prefix(strip_prefix)
    if root is None:
        return None
    try:
        abs_path = Path(local_abs).resolve()
        rel = abs_path.relative_to(root)
    except (ValueError, OSError, RuntimeError):
        return None
    return f"{base_url.rstrip('/')}/{rel.as_posix()}"


def attach_public_media_urls(item: dict) -> None:
    """
    If ``RAGANYTHING_PUBLIC_ASSET_BASE_URL`` and
    ``RAGANYTHING_PUBLIC_ASSET_STRIP_PREFIX`` are both set, add
    ``<field>_public_url`` for each non-empty media path field.

    Existing ``img_path`` / ``table_img_path`` / ``equation_img_path`` values
    are left unchanged so local file-based pipelines keep working.

    If only one of the two env vars is set, the function logs a single
    warning and returns without mutating ``item``.
    """
    base = os.environ.get("RAGANYTHING_PUBLIC_ASSET_BASE_URL", "").strip()
    strip = os.environ.get("RAGANYTHING_PUBLIC_ASSET_STRIP_PREFIX", "").strip()

    if not base and not strip:
        _MISCONFIG_WARNED.clear()
        return
    if base and not strip:
        if "base_only" not in _MISCONFIG_WARNED:
            logger.warning(
                "RAGANYTHING_PUBLIC_ASSET_BASE_URL is set but "
                "RAGANYTHING_PUBLIC_ASSET_STRIP_PREFIX is not; "
                "skipping public URL attachment."
            )
            _MISCONFIG_WARNED.add("base_only")
        return
    if strip and not base:
        if "strip_only" not in _MISCONFIG_WARNED:
            logger.warning(
                "RAGANYTHING_PUBLIC_ASSET_STRIP_PREFIX is set but "
                "RAGANYTHING_PUBLIC_ASSET_BASE_URL is not; "
                "skipping public URL attachment."
            )
            _MISCONFIG_WARNED.add("strip_only")
        return
    _MISCONFIG_WARNED.clear()

    if not isinstance(item, dict):
        return

    for field in MEDIA_PATH_FIELDS:
        raw = item.get(field)
        if not raw or not isinstance(raw, str):
            continue
        s = raw.strip()
        if not s:
            continue
        if s.startswith(("http://", "https://", "s3://")):
            continue
        url = public_url_for_local_path(s, base_url=base, strip_prefix=strip)
        if url:
            item[f"{field}_public_url"] = url
