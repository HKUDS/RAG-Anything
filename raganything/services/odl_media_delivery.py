"""Fail-closed delivery references for OpenDataLoader media.

This module is deliberately independent of router state.  It recognises only
operator-controlled ODL roots and never accepts a caller-provided filesystem
path at the HTTP boundary.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import mimetypes
import os
import secrets
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlencode


_IMAGE_SUFFIXES = frozenset({
    ".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp", ".tiff", ".tif",
})
_MANIFEST_SCHEMA = "odl-media-manifest-v1"
_CATALOG_FIELD = "odl_media_catalog"
_GRANT_TTL_SECONDS = min(max(int(os.getenv("ODL_LEGACY_MEDIA_GRANT_TTL", "300")), 30), 900)
_legacy_grants: dict[str, tuple[float, str, str, str, str, str]] = {}
_legacy_grants_lock = threading.Lock()


@dataclass(frozen=True)
class ResolvedMedia:
    """A server-side media value; it must not cross an API boundary as a path."""

    media_id: str
    path: Path
    mime: str
    caption: str = ""
    page: int | None = None


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _grant_secret() -> bytes:
    """Use the existing process secret only to authenticate opaque grants."""
    configured = os.getenv("JWT_SECRET") or os.getenv("SECRET_KEY")
    if configured:
        return configured.encode("utf-8")
    try:
        from raganything.services.auth import SECRET_KEY

        return str(SECRET_KEY).encode("utf-8")
    except Exception:
        return b""


def _controlled_roots() -> tuple[Path, ...]:
    configured: list[str] = []
    for raw in (os.getenv("ODL_ARTIFACT_ROOT", ""), os.getenv("ODL_LEGACY_MEDIA_ROOTS", "")):
        if raw:
            configured.extend(part.strip() for part in raw.split(os.pathsep) if part.strip())
    project_root = Path(__file__).resolve().parents[2]
    project_artifacts = project_root / "odl-artifacts"
    if project_artifacts.is_dir():
        configured.append(str(project_artifacts))

    roots: list[Path] = []
    for raw in configured:
        try:
            root = Path(raw)
            if not root.is_absolute() or root.is_symlink() or not root.is_dir():
                continue
            resolved = root.resolve(strict=True)
        except (OSError, RuntimeError, ValueError):
            continue
        if resolved not in roots:
            roots.append(resolved)
    return tuple(roots)


def _contains_link(path: Path, root: Path) -> bool:
    try:
        relative = path.relative_to(root)
    except ValueError:
        return True
    current = root
    for component in relative.parts:
        current /= component
        if current.is_symlink():
            return True
    return False


def validate_legacy_media_path(candidate: str | os.PathLike[str]) -> tuple[Path | None, str | None]:
    """Validate an existing ODL artifact path without logging or exposing it."""
    try:
        supplied = Path(candidate)
    except (TypeError, ValueError, OSError):
        return None, "invalid_path"
    if not supplied.is_absolute():
        return None, "relative_path"
    if supplied.suffix.lower() not in _IMAGE_SUFFIXES:
        return None, "unsupported_extension"
    try:
        resolved = supplied.resolve(strict=True)
    except (OSError, RuntimeError, ValueError):
        return None, "missing"
    for root in _controlled_roots():
        try:
            resolved.relative_to(root)
        except ValueError:
            continue
        if _contains_link(supplied, root):
            return None, "symlink"
        if not resolved.is_file():
            return None, "not_regular_file"
        mime, _ = mimetypes.guess_type(resolved.name)
        if not mime or not mime.startswith("image/"):
            return None, "unsupported_mime"
        return resolved, None
    return None, "outside_controlled_root"


def _root_relative(path: Path) -> tuple[Path, str] | None:
    resolved = path.resolve(strict=True)
    for root in _controlled_roots():
        try:
            return root, resolved.relative_to(root).as_posix()
        except ValueError:
            continue
    return None


def _safe_relative_path(value: object) -> Path | None:
    """Accept a non-empty relative component without traversal semantics."""
    if not isinstance(value, str) or not value:
        return None
    path = Path(value)
    if path.is_absolute() or ".." in path.parts:
        return None
    return path


def _declared_media_path(
    manifest: Path,
    *,
    media_root_relative_path: object,
    relative_path: object,
) -> Path | None:
    """Resolve a manifest entry only inside its declared document media root."""
    media_root_relative = _safe_relative_path(media_root_relative_path)
    media_relative = _safe_relative_path(relative_path)
    if media_root_relative is None or media_relative is None:
        return None
    try:
        media_root = manifest.parent / media_root_relative
        if media_root.is_symlink() or not media_root.is_dir():
            return None
        candidate = media_root / media_relative
        resolved_root = media_root.resolve(strict=True)
        resolved_candidate = candidate.resolve(strict=True)
        resolved_candidate.relative_to(resolved_root)
        return candidate
    except (OSError, RuntimeError, ValueError):
        return None


def build_persisted_media_catalog(
    manifest_paths: set[str], *, kb_name: str, document_id: str, workspace: str | None = None,
) -> list[dict[str, Any]] | None:
    """Read persisted manifests into path-free document-status catalog entries."""
    catalog: list[dict[str, Any]] = []
    seen: set[str] = set()
    try:
        for raw_manifest in manifest_paths:
            manifest = Path(raw_manifest)
            if manifest.is_symlink() or not manifest.is_file():
                return None
            manifest_ref = _root_relative(manifest)
            if manifest_ref is None:
                return None
            root, manifest_relative_path = manifest_ref
            payload = json.loads(manifest.read_text(encoding="utf-8"))
            if payload.get("schema") != _MANIFEST_SCHEMA or not isinstance(payload.get("entries"), list):
                return None
            manifest_sha256 = _sha256(manifest)
            for entry in payload["entries"]:
                if not isinstance(entry, dict):
                    return None
                media_id = entry.get("media_id")
                chunk_id = entry.get("chunk_id")
                relative_path = entry.get("relative_path")
                media_root_relative_path = entry.get("media_root_relative_path", ".")
                if (
                    not isinstance(media_id, str) or media_id in seen
                    or entry.get("status") != "persisted"
                    or entry.get("document_id") != document_id
                    or not isinstance(chunk_id, str)
                    or not isinstance(relative_path, str)
                    or not isinstance(media_root_relative_path, str)
                    or not isinstance(entry.get("sha256"), str)
                    or not isinstance(entry.get("mime"), str)
                ):
                    return None
                media_path = _declared_media_path(
                    manifest,
                    media_root_relative_path=media_root_relative_path,
                    relative_path=relative_path,
                )
                if media_path is None:
                    return None
                validated, _reason = validate_legacy_media_path(media_path)
                if validated is None or _sha256(validated) != entry["sha256"]:
                    return None
                actual_mime, _ = mimetypes.guess_type(validated.name)
                if actual_mime != entry["mime"]:
                    return None
                media_ref = _root_relative(validated)
                if media_ref is None or media_ref[0] != root:
                    return None
                seen.add(media_id)
                catalog.append({
                    "media_id": media_id,
                    "kb": kb_name,
                    "workspace": workspace or kb_name,
                    "document_id": document_id,
                    "chunk_id": chunk_id,
                    "manifest_relative_path": manifest_relative_path,
                    "manifest_sha256": manifest_sha256,
                    "media_root_relative_path": media_root_relative_path,
                    "root_relative_path": media_ref[1],
                    "sha256": entry["sha256"],
                    "mime": entry["mime"],
                    "page": entry.get("page"),
                    "caption": entry.get("caption") or "",
                    "status": "persisted",
                })
    except (OSError, RuntimeError, TypeError, ValueError, json.JSONDecodeError):
        return None
    return catalog


def resolve_catalog_media(
    catalog: object, *, kb_name: str, media_id: str,
) -> ResolvedMedia | None:
    """Resolve one catalog media ID and revalidate its manifest and bytes."""
    if not isinstance(catalog, list) or not isinstance(media_id, str):
        return None
    matches = [entry for entry in catalog if isinstance(entry, dict) and entry.get("media_id") == media_id]
    if len(matches) != 1:
        return None
    entry = matches[0]
    # The catalog is read from the already-authorised KB's document status.
    # Its stored workspace identity is evidence for audit, not a user supplied
    # routing key that can replace the enclosing KB access check.
    if entry.get("kb") != kb_name or entry.get("status") != "persisted":
        return None
    manifest_relative_path = entry.get("manifest_relative_path")
    media_relative_path = entry.get("root_relative_path")
    media_root_relative_path = entry.get("media_root_relative_path", ".")
    if (
        not isinstance(manifest_relative_path, str)
        or not isinstance(media_relative_path, str)
        or not isinstance(media_root_relative_path, str)
    ):
        return None
    manifest_parts = Path(manifest_relative_path).parts
    media_parts = Path(media_relative_path).parts
    if (
        Path(manifest_relative_path).is_absolute()
        or Path(media_relative_path).is_absolute()
        or ".." in manifest_parts
        or ".." in media_parts
        or Path(media_root_relative_path).is_absolute()
        or ".." in Path(media_root_relative_path).parts
    ):
        return None
    for root in _controlled_roots():
        manifest = root / manifest_relative_path
        media = root / media_relative_path
        try:
            if _contains_link(manifest, root) or _contains_link(media, root):
                continue
            manifest.resolve(strict=True).relative_to(root)
            media.resolve(strict=True).relative_to(root)
            if not manifest.is_file() or _sha256(manifest) != entry.get("manifest_sha256"):
                continue
            payload = json.loads(manifest.read_text(encoding="utf-8"))
            matches_in_manifest = [
                item for item in payload.get("entries", [])
                if isinstance(item, dict) and item.get("media_id") == media_id
            ]
            if len(matches_in_manifest) != 1:
                continue
            item = matches_in_manifest[0]
            declared_media = _declared_media_path(
                manifest,
                media_root_relative_path=item.get("media_root_relative_path", "."),
                relative_path=item.get("relative_path"),
            )
            if (
                declared_media is None
                or
                payload.get("schema") != _MANIFEST_SCHEMA
                or item.get("status") != "persisted"
                or item.get("document_id") != entry.get("document_id")
                or item.get("chunk_id") != entry.get("chunk_id")
                or item.get("sha256") != entry.get("sha256")
                or item.get("mime") != entry.get("mime")
                or item.get("media_root_relative_path", ".") != media_root_relative_path
            ):
                continue
            if declared_media.resolve(strict=True) != media.resolve(strict=True):
                continue
            validated, _reason = validate_legacy_media_path(media)
            if validated is None or _sha256(validated) != entry.get("sha256"):
                continue
            actual_mime, _ = mimetypes.guess_type(validated.name)
            if actual_mime != entry.get("mime"):
                continue
            return ResolvedMedia(
                media_id=media_id, path=validated, mime=entry["mime"],
                caption=str(entry.get("caption") or ""), page=entry.get("page"),
            )
        except (OSError, RuntimeError, TypeError, ValueError, json.JSONDecodeError):
            continue
    return None


def issue_legacy_media_grant(kb_name: str, path: str | os.PathLike[str]) -> str | None:
    """Compatibility shim that refuses grants without persisted ownership."""
    del kb_name, path
    return None


def issue_owned_legacy_media_grant(
    *,
    kb_name: str,
    path: str | os.PathLike[str],
    document_id: str,
    chunk_id: str,
) -> str | None:
    """Issue a KB/document/chunk-bound grant after a persisted marker match."""
    if not all(isinstance(value, str) and value for value in (kb_name, document_id, chunk_id)):
        return None
    validated, _reason = validate_legacy_media_path(path)
    if validated is None:
        return None
    secret = _grant_secret()
    if not secret:
        return None
    nonce = secrets.token_urlsafe(32)
    signature = hmac.new(secret, nonce.encode("ascii"), hashlib.sha256).hexdigest()
    grant = f"{nonce}.{signature}"
    with _legacy_grants_lock:
        now = time.monotonic()
        for key, value in list(_legacy_grants.items()):
            if value[0] <= now:
                _legacy_grants.pop(key, None)
        _legacy_grants[nonce] = (
            now + _GRANT_TTL_SECONDS,
            kb_name,
            str(validated),
            _sha256(validated),
            document_id,
            chunk_id,
        )
    return grant


def resolve_legacy_media_grant(kb_name: str, grant: str) -> ResolvedMedia | None:
    """Resolve an opaque grant after KB authorization and ownership binding."""
    try:
        nonce, signature = grant.split(".", 1)
    except ValueError:
        return None
    secret = _grant_secret()
    expected = hmac.new(secret, nonce.encode("ascii"), hashlib.sha256).hexdigest() if secret else ""
    if not hmac.compare_digest(signature, expected):
        return None
    with _legacy_grants_lock:
        value = _legacy_grants.get(nonce)
    if value is None:
        return None
    expires_at, expected_kb, raw_path, expected_digest, document_id, chunk_id = value
    if (
        expires_at <= time.monotonic()
        or expected_kb != kb_name
        or not document_id
        or not chunk_id
    ):
        return None
    validated, _reason = validate_legacy_media_path(raw_path)
    if validated is None or _sha256(validated) != expected_digest:
        return None
    return ResolvedMedia(
        media_id=f"legacy:{nonce}",
        path=validated,
        mime=mimetypes.guess_type(validated.name)[0] or "image/png",
    )


def _media_endpoint_url(prefix: str, media_ref: str, kb_name: str) -> str:
    """Build a controlled media URL without treating a KB name as query syntax."""
    return f"{prefix}/{quote(media_ref, safe='')}?{urlencode({'kb': kb_name})}"


def catalog_media_payload(catalog: object, *, kb_name: str, path: str) -> dict[str, Any] | None:
    """Convert a recalled server-side path into a path-free client payload."""
    if isinstance(catalog, list):
        for entry in catalog:
            if not isinstance(entry, dict):
                continue
            resolved = resolve_catalog_media(catalog, kb_name=kb_name, media_id=str(entry.get("media_id") or ""))
            try:
                same_media = resolved is not None and os.path.samefile(resolved.path, path)
            except OSError:
                # A recalled candidate can disappear between validation and
                # delivery conversion. Treat that race as unavailable media.
                same_media = False
            if same_media:
                return {
                    "media_id": resolved.media_id,
                    "kb": kb_name,
                    "url": _media_endpoint_url(
                        "/api/knowledge/media", resolved.media_id, kb_name
                    ),
                    "caption": resolved.caption,
                    "page": resolved.page,
                }
    return None
