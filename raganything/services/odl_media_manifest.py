"""Auditable, fail-closed manifests for OpenDataLoader raster media.

The manifest stays beneath a server-created parser output directory.  It is
not a public API and never authorises a caller supplied filesystem path.
"""

from __future__ import annotations

import hashlib
import json
import mimetypes
import os
import tempfile
from pathlib import Path
from typing import Any


_IMAGE_SUFFIXES = frozenset({
    ".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp", ".tiff", ".tif",
})
_MANIFEST_SCHEMA = "odl-media-manifest-v1"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def build_media_entry(
    *,
    path: Path,
    output_root: Path,
    page: int,
    element_id: str,
    caption: str,
    provenance: str = "odl-parser",
) -> dict[str, Any]:
    """Build a pending entry after containment has already been proven."""
    resolved_root = output_root.resolve(strict=True)
    resolved_path = path.resolve(strict=True)
    relative = resolved_path.relative_to(resolved_root)
    if path.is_symlink() or not resolved_path.is_file():
        raise ValueError("ODL media must be a non-symlink regular file")
    if resolved_path.suffix.lower() not in _IMAGE_SUFFIXES:
        raise ValueError("ODL media must use a supported image extension")
    mime, _ = mimetypes.guess_type(resolved_path.name)
    if not mime or not mime.startswith("image/"):
        raise ValueError("ODL media MIME could not be established")
    digest = _sha256(resolved_path)
    stable_id = hashlib.sha256(
        # The output root is a server-created unique parser run. Hashing its
        # canonical identity keeps opaque IDs distinct for repeated uploads
        # of identical PDFs without exposing that path in any persisted API.
        f"{resolved_root}:{int(page)}:{relative.as_posix()}:{digest}:{element_id}".encode("utf-8")
    ).hexdigest()[:32]
    return {
        "media_id": stable_id,
        "relative_path": relative.as_posix(),
        "sha256": digest,
        "mime": mime,
        "page": int(page),
        "element_id": str(element_id),
        "caption": str(caption or ""),
        "provenance": str(provenance),
        "status": "pending_chunk",
        "document_id": None,
        "chunk_id": None,
    }


def _atomic_write(path: Path, payload: dict[str, Any]) -> None:
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as target:
            json.dump(payload, target, ensure_ascii=False, indent=2, sort_keys=True)
            target.flush()
            os.fsync(target.fileno())
        os.replace(temporary, path)
    except Exception:
        try:
            Path(temporary).unlink(missing_ok=True)
        except OSError:
            pass
        raise


def write_pending_manifest(path: Path, entries: list[dict[str, Any]]) -> str:
    """Create a new manifest and return its content digest."""
    if path.exists() or path.parent.is_symlink():
        raise ValueError("refusing to overwrite or link-write an ODL media manifest")
    payload = {"schema": _MANIFEST_SCHEMA, "entries": entries}
    _atomic_write(path, payload)
    return _sha256(path)


def bind_persisted_image_chunk(
    manifest_path: str | os.PathLike[str],
    *,
    media_id: str,
    document_id: str,
    chunk_id: str,
) -> bool:
    """Bind one pending entry after its image chunk has been persisted.

    Returns ``False`` rather than making an optimistic completion claim when a
    manifest is malformed, missing, or has no matching pending entry.
    """
    try:
        path = Path(manifest_path)
        if path.is_symlink() or not path.is_file():
            return False
        payload = json.loads(path.read_text(encoding="utf-8"))
        if payload.get("schema") != _MANIFEST_SCHEMA:
            return False
        entries = payload.get("entries")
        if not isinstance(entries, list):
            return False
        for entry in entries:
            if not isinstance(entry, dict) or entry.get("media_id") != media_id:
                continue
            if entry.get("status") not in {"pending_chunk", "persisted"}:
                return False
            entry.update({
                "document_id": document_id,
                "chunk_id": chunk_id,
                "status": "persisted",
            })
            _atomic_write(path, payload)
            return True
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        return False
    return False


def audit_persisted_entries(
    manifest_paths: set[str],
    *,
    document_id: str,
    expected_media_ids: set[str],
    persisted_chunk_ids: set[str],
) -> tuple[bool, dict[str, int]]:
    """Verify every eligible image is bound to one persisted chunk exactly once."""
    bound: dict[str, str] = {}
    try:
        for raw_path in manifest_paths:
            path = Path(raw_path)
            if path.is_symlink() or not path.is_file():
                return False, {"expected": len(expected_media_ids), "valid": 0, "chunks": 0}
            payload = json.loads(path.read_text(encoding="utf-8"))
            if payload.get("schema") != _MANIFEST_SCHEMA:
                return False, {"expected": len(expected_media_ids), "valid": 0, "chunks": 0}
            for entry in payload.get("entries", []):
                if not isinstance(entry, dict) or entry.get("media_id") not in expected_media_ids:
                    continue
                if entry.get("document_id") != document_id or entry.get("status") != "persisted":
                    return False, {"expected": len(expected_media_ids), "valid": len(bound), "chunks": len(set(bound.values()))}
                chunk_id = entry.get("chunk_id")
                if not isinstance(chunk_id, str) or chunk_id not in persisted_chunk_ids:
                    return False, {"expected": len(expected_media_ids), "valid": len(bound), "chunks": len(set(bound.values()))}
                if entry["media_id"] in bound or chunk_id in bound.values():
                    return False, {"expected": len(expected_media_ids), "valid": len(bound), "chunks": len(set(bound.values()))}
                bound[entry["media_id"]] = chunk_id
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        return False, {"expected": len(expected_media_ids), "valid": len(bound), "chunks": len(set(bound.values()))}
    counts = {"expected": len(expected_media_ids), "valid": len(bound), "chunks": len(set(bound.values()))}
    return set(bound) == expected_media_ids and counts["chunks"] == counts["expected"], counts
