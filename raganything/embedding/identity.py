"""Canonical, secret-free identity for text embeddings.

The identity is persisted with upload settings and used as the namespace for
LightRAG vector tables and the persistent embedding cache.  Credentials are
never part of the identity.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from urllib.parse import urlsplit
from typing import Any, Mapping

IDENTITY_SCHEMA_VERSION = "text-embedding-v1"
_IDENTITY_KEYS = (
    "schema_version", "provider", "model", "dimension",
    "endpoint_semantics", "endpoint_fingerprint", "identity_hash",
    "table_suffix", "model_name",
)
_SAFE = re.compile(r"[^a-z0-9_]+")


def _endpoint_semantics(value: str | None) -> str:
    """Return a stable, credential-free endpoint token."""
    raw = str(value or "").strip()
    if not raw:
        return "default"
    parsed = urlsplit(raw if "://" in raw else f"https://{raw}")
    host = (parsed.hostname or "").lower()
    path = parsed.path.rstrip("/")
    return f"{host}{path}" if host else raw.lower().split("?", 1)[0].rstrip("/")


def _safe_token(value: str, *, fallback: str = "unknown") -> str:
    token = _SAFE.sub("_", value.lower()).strip("_")
    return token or fallback


def canonical_text_embedding_identity(
    *,
    provider: str,
    model: str,
    dimension: int,
    endpoint_semantics: str | None = None,
) -> dict[str, Any]:
    """Build a deterministic identity and PostgreSQL-safe model namespace."""
    provider_token = _safe_token(str(provider))
    model_token = _safe_token(str(model))
    try:
        dim = int(dimension)
    except (TypeError, ValueError) as exc:
        raise ValueError("embedding dimension must be a positive integer") from exc
    if dim <= 0:
        raise ValueError("embedding dimension must be a positive integer")
    endpoint = _endpoint_semantics(endpoint_semantics)
    canonical = {
        "schema_version": IDENTITY_SCHEMA_VERSION,
        "provider": provider_token,
        "model": str(model).strip(),
        "dimension": dim,
        "endpoint_semantics": endpoint,
        "endpoint_fingerprint": hashlib.sha256(endpoint.encode("utf-8")).hexdigest()[:24],
    }
    payload = json.dumps(canonical, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()
    # LightRAG prefixes this value when naming its three vector tables. Keep a
    # 16-hex digest suffix even when the display tokens are very long.
    readable = f"{provider_token}_{model_token}_{dim}"
    # LightRAG appends ``_{dimension}d`` and a table prefix; keep this model
    # namespace short enough that the final PostgreSQL identifier stays below
    # the 63-byte limit while retaining a collision-resistant digest.
    suffix = f"{readable[:12].rstrip('_')}_{digest[:16]}"
    identity = {
        **canonical,
        "identity_hash": digest,
        "table_suffix": suffix,
        "model_name": suffix,
    }
    return identity


def text_embedding_identity_from_environment() -> dict[str, Any]:
    """Resolve the process configuration once at an enqueue/query boundary."""
    return canonical_text_embedding_identity(
        provider=os.getenv("EMBEDDING_PROVIDER", "openai_compatible"),
        model=os.getenv("EMBEDDING_MODEL", "text-embedding-v3"),
        dimension=os.getenv("EMBEDDING_DIM", "1024"),
        endpoint_semantics=(
            os.getenv("EMBEDDING_ENDPOINT_SEMANTICS")
            or os.getenv("LLM_BINDING_HOST")
        ),
    )


def load_text_embedding_identity(value: Mapping[str, Any] | None) -> dict[str, Any]:
    """Strictly validate a persisted identity before constructing LightRAG."""
    if not isinstance(value, Mapping):
        raise RuntimeError("text_embedding_identity_missing")
    missing = [key for key in _IDENTITY_KEYS if key not in value]
    if missing:
        raise RuntimeError("text_embedding_identity_invalid")
    expected = canonical_text_embedding_identity(
        provider=str(value["provider"]), model=str(value["model"]),
        dimension=value["dimension"], endpoint_semantics=str(value["endpoint_semantics"]),
    )
    if any(value[key] != expected[key] for key in _IDENTITY_KEYS):
        raise RuntimeError("text_embedding_identity_invalid")
    return expected


def embedding_identity_from_settings(settings: Mapping[str, Any] | None) -> dict[str, Any]:
    """Load a snapshot identity, or resolve current process settings for queries."""
    if isinstance(settings, Mapping) and "text_embedding_identity" in settings:
        return load_text_embedding_identity(settings["text_embedding_identity"])
    if settings is not None:
        raise RuntimeError("text_embedding_identity_missing")
    return text_embedding_identity_from_environment()


__all__ = [
    "IDENTITY_SCHEMA_VERSION", "canonical_text_embedding_identity",
    "text_embedding_identity_from_environment", "load_text_embedding_identity",
    "embedding_identity_from_settings",
]
