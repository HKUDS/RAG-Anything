"""Server-owned vision model catalog and profile resolution.

The catalog deliberately separates image understanding (VLM) from visual
embeddings.  Only the public projection of a profile is safe to return from
an API; provider credentials and transport settings stay in this module.
"""

from __future__ import annotations

import hashlib
import asyncio
import json
import logging
import os
from contextvars import ContextVar, Token
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, Protocol

from pydantic import BaseModel, Field, field_validator, model_validator

logger = logging.getLogger("rag_server.vision_models")

VisionKind = Literal["vlm", "embedding"]
CATALOG_FILE_ENV = "VISION_MODEL_CATALOG_FILE"
CATALOG_FILE_DEFAULT = "config/vision_models.json"


class VisionModelProfile(BaseModel):
    id: str
    kind: VisionKind
    display_name: str
    provider: str
    model: str
    capabilities: list[str] = Field(default_factory=list)
    embedding_dim: int | None = None
    available: bool = False
    unavailable_reason: str | None = None

    @field_validator("id", "display_name", "provider", "model")
    @classmethod
    def _non_empty(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("vision profile fields cannot be empty")
        return value

    @field_validator("embedding_dim")
    @classmethod
    def _positive_dim(cls, value: int | None) -> int | None:
        if value is not None and value <= 0:
            raise ValueError("embedding_dim must be positive")
        return value

    @model_validator(mode="after")
    def _validate_kind_shape(self) -> "VisionModelProfile":
        # VLMs do not produce a fixed vector space.  Embedding profiles must
        # declare their dimension so repositories can reject mixed vectors
        # before an insert/query reaches the database.
        if self.kind == "embedding" and self.embedding_dim is None:
            raise ValueError("embedding profiles must define embedding_dim")
        if self.kind == "vlm" and self.embedding_dim is not None:
            raise ValueError("vlm profiles must not define embedding_dim")
        if self.unavailable_reason and self.available:
            raise ValueError("available profiles cannot have unavailable_reason")
        return self


@dataclass(frozen=True)
class _CatalogEntry:
    profile: VisionModelProfile
    base_url: str | None = None
    api_key_env: str | None = None
    timeout: float = 60.0
    concurrency: int = 4

    @property
    def fingerprint(self) -> str:
        # Never hash the resolved secret or its environment-variable name.
        # Only canonical, non-secret transport/model settings participate.
        payload = {
            "kind": self.profile.kind,
            "provider": self.profile.provider,
            "model": self.profile.model,
            "base_url": self.base_url,
            "embedding_dim": self.profile.embedding_dim,
            "timeout": self.timeout,
            "concurrency": self.concurrency,
            "adapter_version": 1,
        }
        return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()[:32]

    def public(self) -> VisionModelProfile:
        return self.profile.model_copy(deep=True)


class VisionLanguageProvider(Protocol):
    async def probe(self, profile: _CatalogEntry) -> dict[str, Any]: ...


class VisionEmbeddingProvider(Protocol):
    async def probe(self, profile: _CatalogEntry) -> dict[str, Any]: ...


class _OpenAICompatibleProvider:
    """Registry marker for the existing OpenAI-compatible VLM adapter.

    The actual request function is supplied by the caller (LightRAG); keeping
    the provider registered here prevents catalog availability from depending
    on a process-local environment mutation.
    """

    @staticmethod
    async def probe(profile: _CatalogEntry) -> dict[str, Any]:
        return await _probe_openai_compatible(profile)


class _DoubaoEmbeddingProvider:
    """Registry marker for the existing Doubao embedding adapter."""

    @staticmethod
    async def probe(profile: _CatalogEntry) -> dict[str, Any]:
        return await _probe_openai_compatible(profile)


async def _probe_openai_compatible(profile: _CatalogEntry) -> dict[str, Any]:
    """Use the provider's model-list route without returning upstream data."""
    import httpx

    key = os.getenv(profile.api_key_env or "", "").strip()
    if not key or not profile.base_url:
        return {"available": False, "reason": "provider configuration is incomplete"}
    url = f"{profile.base_url.rstrip('/')}/models"
    try:
        async with httpx.AsyncClient(timeout=min(max(profile.timeout, 1.0), 15.0)) as client:
            response = await client.get(url, headers={"Authorization": f"Bearer {key}"})
        if 200 <= response.status_code < 300:
            return {"available": True, "reason": None}
        if response.status_code in {401, 403}:
            return {"available": False, "reason": "provider authentication failed"}
        return {"available": False, "reason": "provider connectivity check failed"}
    except (httpx.HTTPError, httpx.InvalidURL):
        return {"available": False, "reason": "provider connectivity check failed"}


_PROVIDERS: dict[tuple[str, VisionKind], Any] = {}
_CATALOG: dict[str, _CatalogEntry] | None = None
_PLATFORM_DEFAULTS: dict[str, str | None] = {
    "vision_vlm_profile_id": None,
    "vision_embedding_profile_id": None,
}
_USER_PREFS: dict[int, str | None] = {}
_USER_PREF_TABLE_READY = False
_UNSET = object()
_ACTIVE_VLM_SNAPSHOT: ContextVar[tuple[str, str] | None] = ContextVar(
    "active_vision_vlm_snapshot", default=None
)
_VLM_CALLABLES: dict[tuple[str, str, int], Any] = {}


class _NamespacedCache:
    """Prefix LightRAG cache IDs with the resolved VLM fingerprint."""

    def __init__(self, cache: Any, namespace: str):
        self._cache = cache
        self._prefix = f"vision:{namespace}:"

    def __getattr__(self, name: str):
        return getattr(self._cache, name)

    async def get_by_id(self, key: str):
        return await self._cache.get_by_id(self._prefix + key)

    async def get_by_ids(self, keys: list[str]):
        return await self._cache.get_by_ids([self._prefix + key for key in keys])

    async def upsert(self, data: dict[str, Any]):
        return await self._cache.upsert({self._prefix + key: value for key, value in data.items()})

def register_provider(name: str, kind: VisionKind, factory: Any) -> None:
    """Register a provider factory, primarily for adapters and tests."""
    _PROVIDERS[(name, kind)] = factory


# Built-ins are explicit registry entries.  Catalog availability must never
# be inferred merely from an arbitrary provider string in JSON.
register_provider("openai_compatible", "vlm", _OpenAICompatibleProvider)
register_provider("doubao_multimodal_embedding", "embedding", _DoubaoEmbeddingProvider)


def _env_available(env_name: str | None) -> bool:
    return bool(env_name and os.getenv(env_name, "").strip())


def _legacy_entries() -> list[_CatalogEntry]:
    vlm_model = os.getenv("VISION_MODEL", "qwen-vl-plus").strip() or "qwen-vl-plus"
    vlm_host = os.getenv("LLM_BINDING_HOST", "").strip() or None
    vlm_key_env = "LLM_BINDING_API_KEY"
    vlm_available = bool(vlm_host and _env_available(vlm_key_env))
    vlm_reason = None if vlm_available else "legacy VLM host or credential is not configured"

    emb_model = os.getenv("VISION_EMBEDDING_MODEL", "").strip() or "doubao-embedding-vision-251215"
    emb_host = os.getenv("VISION_EMBEDDING_HOST", "").strip() or "https://ark.cn-beijing.volces.com/api/v3"
    emb_key_env = "VISION_EMBEDDING_API_KEY"
    emb_available = _env_available(emb_key_env) and bool(os.getenv("VISION_SEARCH_ENABLED", "true").lower() == "true")
    emb_reason = None if emb_available else "legacy vision embedding credential is not configured"
    try:
        dim = int(os.getenv("VISION_EMBEDDING_DIM", "2048"))
    except ValueError:
        dim = 2048
    return [
        _CatalogEntry(
            VisionModelProfile(
                id="legacy-vlm",
                kind="vlm",
                display_name=f"Legacy VLM ({vlm_model})",
                provider="openai_compatible",
                model=vlm_model,
                capabilities=["ocr", "image_description", "video_frame", "question_answering"],
                available=vlm_available,
                unavailable_reason=vlm_reason,
            ),
            base_url=vlm_host,
            api_key_env=vlm_key_env,
            timeout=float(os.getenv("LLM_TIMEOUT", "180")),
            concurrency=int(os.getenv("MAX_ASYNC", "4")),
        ),
        _CatalogEntry(
            VisionModelProfile(
                id="legacy-doubao-embedding",
                kind="embedding",
                display_name=f"Legacy Doubao Vision Embedding ({emb_model})",
                provider="doubao_multimodal_embedding",
                model=emb_model,
                capabilities=["image_similarity"],
                embedding_dim=dim,
                available=emb_available,
                unavailable_reason=emb_reason,
            ),
            base_url=emb_host,
            api_key_env=emb_key_env,
            timeout=float(os.getenv("VISION_EMBEDDING_TIMEOUT", "60")),
            concurrency=int(os.getenv("VISION_EMBEDDING_MAX_ASYNC", "4")),
        ),
    ]


def _entry_from_dict(raw: dict[str, Any]) -> _CatalogEntry:
    def expand_private(value: Any) -> Any:
        if isinstance(value, str) and value.startswith("${") and value.endswith("}"):
            return os.getenv(value[2:-1], "")
        return value

    public = {
        key: raw[key]
        for key in ("id", "kind", "display_name", "provider", "model", "capabilities", "embedding_dim")
        if key in raw
    }
    model_value = public.get("model")
    if isinstance(model_value, str) and model_value.startswith("${") and model_value.endswith("}"):
        env_name = model_value[2:-1]
        if env_name not in {"VISION_MODEL", "VISION_EMBEDDING_MODEL"}:
            raise ValueError("public model interpolation is not allowlisted")
        public["model"] = os.getenv(env_name, "")
    kind = public.get("kind")
    if kind not in ("vlm", "embedding"):
        raise ValueError(f"unsupported vision profile kind: {kind!r}")
    if not public.get("model"):
        public["model"] = "qwen-vl-plus" if kind == "vlm" else "doubao-embedding-vision-251215"
    dimension_value = public.get("embedding_dim")
    if isinstance(dimension_value, str) and dimension_value.startswith("${") and dimension_value.endswith("}"):
        env_name = dimension_value[2:-1]
        if env_name != "VISION_EMBEDDING_DIM":
            raise ValueError("public embedding_dim interpolation is not allowlisted")
        raw_dimension = os.getenv(env_name, "2048").strip() or "2048"
        try:
            public["embedding_dim"] = int(raw_dimension)
        except ValueError as exc:
            raise ValueError("VISION_EMBEDDING_DIM must be an integer") from exc
    private = raw.get("private") if isinstance(raw.get("private"), dict) else raw
    api_key_env = private.get("api_key_env")
    base_url = private.get("base_url")
    base_url = expand_private(base_url)
    if not base_url and public.get("provider") == "doubao_multimodal_embedding":
        # Preserve the adapter's historical default for deployments that did
        # not set VISION_EMBEDDING_HOST explicitly.
        base_url = "https://ark.cn-beijing.volces.com/api/v3"
    if not isinstance(api_key_env, str) or not api_key_env:
        raise ValueError(f"profile {public.get('id')!r} must define private.api_key_env")
    profile = VisionModelProfile(**public, available=False)
    provider_registered = (profile.provider, profile.kind) in _PROVIDERS
    reason = None
    if not provider_registered:
        reason = "provider adapter is not installed"
    elif not _env_available(api_key_env):
        reason = "provider credential is not configured"
    elif not base_url:
        reason = "provider base URL is not configured"
    profile = profile.model_copy(update={"available": reason is None, "unavailable_reason": reason})
    return _CatalogEntry(
        profile,
        base_url=str(base_url).strip() if base_url else None,
        api_key_env=api_key_env,
        timeout=float(private.get("timeout", 60)),
        concurrency=max(1, int(private.get("concurrency", 4))),
    )


def load_catalog(*, refresh: bool = False) -> dict[str, _CatalogEntry]:
    global _CATALOG
    if _CATALOG is not None and not refresh:
        return dict(_CATALOG)
    path = Path(os.getenv(CATALOG_FILE_ENV, CATALOG_FILE_DEFAULT))
    entries: list[_CatalogEntry]
    if path.exists():
        try:
            raw = json.loads(path.read_text(encoding="utf-8-sig"))
            rows = raw.get("profiles", raw) if isinstance(raw, dict) else raw
            if not isinstance(rows, list):
                raise ValueError("catalog must contain a profiles array")
            if any(not isinstance(row, dict) for row in rows):
                raise ValueError("every catalog profile must be an object")
            entries = [_entry_from_dict(row) for row in rows]
        except (OSError, json.JSONDecodeError, TypeError, ValueError) as exc:
            raise RuntimeError(f"invalid vision model catalog: {exc}") from exc
    else:
        entries = _legacy_entries()
    ids = [entry.profile.id for entry in entries]
    if len(ids) != len(set(ids)):
        duplicate = next(item for item in ids if ids.count(item) > 1)
        raise RuntimeError(f"duplicate vision profile id: {duplicate}")
    _CATALOG = {entry.profile.id: entry for entry in entries}
    return dict(_CATALOG)


def reset_catalog_cache() -> None:
    global _CATALOG
    _CATALOG = None


def list_profiles(kind: VisionKind | None = None) -> list[VisionModelProfile]:
    profiles = [entry.public() for entry in load_catalog().values()]
    return [profile for profile in profiles if kind is None or profile.kind == kind]


def get_entry(profile_id: str, kind: VisionKind | None = None) -> _CatalogEntry:
    entry = load_catalog().get(profile_id)
    if entry is None or (kind is not None and entry.profile.kind != kind):
        raise KeyError(profile_id)
    return entry


def require_available(profile_id: str, kind: VisionKind) -> _CatalogEntry:
    try:
        entry = get_entry(profile_id, kind)
    except KeyError as exc:
        raise ValueError(f"unknown {kind} vision profile: {profile_id}") from exc
    if not entry.profile.available:
        raise RuntimeError(entry.profile.unavailable_reason or "vision profile unavailable")
    return entry


def build_vlm_callable(profile_id: str, *, completion_func=None, allow_unavailable: bool = False):
    """Build the existing OpenAI-compatible VLM callable for a profile.

    Credentials are resolved only inside the server process and captured by
    the returned callable.  Callers can safely keep one callable per resolved
    request/task snapshot without mutating ``os.environ``.
    """
    entry = get_entry(profile_id, "vlm")
    if not entry.profile.available and not allow_unavailable:
        raise RuntimeError(entry.profile.unavailable_reason or "vision profile unavailable")
    if entry.profile.provider != "openai_compatible":
        raise RuntimeError("selected VLM provider adapter is unavailable")
    api_key = os.getenv(entry.api_key_env or "", "").strip()
    model = entry.profile.model
    base_url = entry.base_url
    timeout = entry.timeout
    cache_namespace = f"[vision-profile:{entry.profile.provider}:{entry.fingerprint}]"

    async def vision_func(
        prompt,
        system_prompt=None,
        history_messages=None,
        image_data=None,
        image_mime_type=None,
        messages=None,
        **kwargs,
    ):
        if not entry.profile.available:
            raise RuntimeError("selected image-understanding profile is unavailable")
        if completion_func is None:
            from lightrag.llm.openai import openai_complete_if_cache as selected_completion
        else:
            selected_completion = completion_func

        kwargs.setdefault("timeout", timeout)
        if messages is not None:
            messages = [{"role": "system", "content": cache_namespace}, *messages]
        elif image_data is not None:
            mime_type = image_mime_type if image_mime_type in {
                "image/gif", "image/jpeg", "image/png", "image/webp"
            } else "image/jpeg"
            messages = [
                {"role": "system", "content": "\n".join(filter(None, [cache_namespace, system_prompt]))},
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {"type": "image_url", "image_url": {"url": f"data:{mime_type};base64,{image_data}"}},
                    ],
                },
            ]
        if messages is not None:
            return await selected_completion(
                model,
                "",
                system_prompt=None,
                history_messages=[],
                messages=messages,
                api_key=api_key,
                base_url=base_url,
                **kwargs,
            )
        return await selected_completion(
            model,
            prompt,
            system_prompt="\n".join(filter(None, [cache_namespace, system_prompt])),
            history_messages=history_messages or [],
            api_key=api_key,
            base_url=base_url,
            **kwargs,
        )

    vision_func.vision_profile_id = profile_id
    vision_func.vision_profile_fingerprint = entry.fingerprint
    vision_func.get_vision_profile_snapshot = lambda: (profile_id, entry.fingerprint)
    return vision_func


def activate_vlm_snapshot(profile_id: str, fingerprint: str | None = None) -> Token:
    """Activate an immutable VLM snapshot in the current async context."""
    entry = require_available(profile_id, "vlm")
    if fingerprint is not None and fingerprint != entry.fingerprint:
        raise RuntimeError("selected VLM profile configuration changed")
    return _ACTIVE_VLM_SNAPSHOT.set((profile_id, entry.fingerprint))


def activate_vlm_selection(entry: _CatalogEntry) -> Token:
    """Activate a resolved selection; availability is checked on invocation."""
    if entry.profile.kind != "vlm":
        raise ValueError("VLM context requires a vlm profile")
    return _ACTIVE_VLM_SNAPSHOT.set((entry.profile.id, entry.fingerprint))


def reset_vlm_snapshot(token: Token) -> None:
    _ACTIVE_VLM_SNAPSHOT.reset(token)


async def activate_user_vlm_snapshot(user_id: int) -> Token:
    """Resolve and activate an immutable VLM snapshot for this request."""
    personal = await get_user_vlm_preference(user_id)
    defaults = await get_platform_defaults()
    profile_id = personal or defaults.get("vision_vlm_profile_id") or "legacy-vlm"
    try:
        fingerprint = get_entry(profile_id, "vlm").fingerprint
    except KeyError:
        fingerprint = "catalog-missing"
    return _ACTIVE_VLM_SNAPSHOT.set((profile_id, fingerprint))


def build_contextual_vlm_callable(default_profile_id: str, *, completion_func=None):
    """Return a shared-instance-safe proxy resolved from request context."""
    default_entry = get_entry(default_profile_id, "vlm")

    async def contextual_vlm(*args, **kwargs):
        profile_id, fingerprint = _ACTIVE_VLM_SNAPSHOT.get() or (
            default_profile_id,
            default_entry.fingerprint,
        )
        entry = get_entry(profile_id, "vlm")
        if entry.fingerprint != fingerprint:
            raise RuntimeError("selected VLM profile configuration changed")
        key = (profile_id, fingerprint, id(completion_func))
        provider = _VLM_CALLABLES.get(key)
        if provider is None:
            provider = build_vlm_callable(
                profile_id,
                completion_func=completion_func,
                allow_unavailable=True,
            )
            _VLM_CALLABLES[key] = provider
        hashing_kv = kwargs.get("hashing_kv")
        if hashing_kv is not None and not isinstance(hashing_kv, _NamespacedCache):
            kwargs["hashing_kv"] = _NamespacedCache(hashing_kv, fingerprint)
        return await provider(*args, **kwargs)

    contextual_vlm.vision_profile_id = default_profile_id
    contextual_vlm.vision_profile_fingerprint = default_entry.fingerprint
    contextual_vlm.get_vision_profile_snapshot = lambda: (
        _ACTIVE_VLM_SNAPSHOT.get()
        or (default_profile_id, default_entry.fingerprint)
    )
    return contextual_vlm


def build_embedding_provider(profile_id: str, *, working_dir: str):
    """Instantiate the configured visual-embedding adapter."""
    entry = require_available(profile_id, "embedding")
    if entry.profile.provider != "doubao_multimodal_embedding":
        raise RuntimeError("selected embedding provider adapter is unavailable")
    from raganything.embedding.doubao_vision import DoubaoEmbeddingAdapter

    adapter = DoubaoEmbeddingAdapter(
        api_key=os.getenv(entry.api_key_env or "", "").strip(),
        base_url=entry.base_url or "",
        model=entry.profile.model,
        dimension=entry.profile.embedding_dim or 0,
        timeout=entry.timeout,
        max_concurrent=entry.concurrency,
    )
    adapter.vision_profile_id = profile_id
    adapter.vision_profile_fingerprint = entry.fingerprint
    adapter.vision_working_dir = working_dir
    return adapter


async def _pg_pool():
    try:
        from raganything.services.pg_state_repo import get_pg_pool
        return get_pg_pool()
    except (RuntimeError, ImportError):
        return None


async def get_platform_defaults() -> dict[str, str | None]:
    pool = await _pg_pool()
    if pool is None:
        return dict(_PLATFORM_DEFAULTS)
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT key, value FROM settings WHERE key IN ('vision_vlm_profile_id','vision_embedding_profile_id')"
        )
    result = dict(_PLATFORM_DEFAULTS)
    for row in rows:
        result[row["key"]] = row["value"] or None
    _PLATFORM_DEFAULTS.update(result)
    return result


async def set_platform_defaults(
    *,
    vlm_profile_id: str | None | object = _UNSET,
    embedding_profile_id: str | None | object = _UNSET,
) -> dict[str, str | None]:
    if vlm_profile_id is not _UNSET and vlm_profile_id is not None:
        require_available(vlm_profile_id, "vlm")
    if embedding_profile_id is not _UNSET and embedding_profile_id is not None:
        require_available(embedding_profile_id, "embedding")
    values = {}
    if vlm_profile_id is not _UNSET:
        values["vision_vlm_profile_id"] = vlm_profile_id
    if embedding_profile_id is not _UNSET:
        values["vision_embedding_profile_id"] = embedding_profile_id
    pool = await _pg_pool()
    if pool is None:
        _PLATFORM_DEFAULTS.update(values)
        return dict(_PLATFORM_DEFAULTS)
    async with pool.acquire() as conn:
        async with conn.transaction():
            for key, value in values.items():
                await conn.execute(
                    "INSERT INTO settings(key,value) VALUES($1,$2) ON CONFLICT(key) DO UPDATE SET value=EXCLUDED.value",
                    key, value or "",
                )
    _PLATFORM_DEFAULTS.update(values)
    return await get_platform_defaults()


async def get_user_vlm_preference(user_id: int) -> str | None:
    pool = await _pg_pool()
    if pool is None:
        return _USER_PREFS.get(int(user_id))
    await _ensure_user_pref_table(pool)
    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT vision_vlm_profile_id FROM user_model_preferences WHERE user_id=$1", int(user_id))
    return row["vision_vlm_profile_id"] if row else None


async def set_user_vlm_preference(user_id: int, profile_id: str | None) -> str | None:
    if profile_id is not None:
        require_available(profile_id, "vlm")
    pool = await _pg_pool()
    if pool is None:
        _USER_PREFS[int(user_id)] = profile_id
        return profile_id
    await _ensure_user_pref_table(pool)
    async with pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO user_model_preferences(user_id,vision_vlm_profile_id,updated_at) VALUES($1,$2,NOW()) "
            "ON CONFLICT(user_id) DO UPDATE SET vision_vlm_profile_id=EXCLUDED.vision_vlm_profile_id,updated_at=NOW()",
            int(user_id), profile_id,
        )
    return profile_id


async def _ensure_user_pref_table(pool) -> None:
    global _USER_PREF_TABLE_READY
    if _USER_PREF_TABLE_READY:
        return
    async with pool.acquire() as conn:
        await conn.execute(
            "CREATE TABLE IF NOT EXISTS user_model_preferences ("
            "user_id BIGINT PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,"
            "vision_vlm_profile_id TEXT NULL, updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW())"
        )
    _USER_PREF_TABLE_READY = True


async def ensure_vision_model_schema(pool) -> None:
    """Apply the idempotent runtime subset of migration 023."""
    pre_backfill = [
        "CREATE TABLE IF NOT EXISTS user_model_preferences ("
        "user_id BIGINT PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,"
        "vision_vlm_profile_id TEXT NULL, updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW())",
        "ALTER TABLE image_vision_vectors ADD COLUMN IF NOT EXISTS profile_id TEXT",
        "ALTER TABLE image_vision_vectors ADD COLUMN IF NOT EXISTS profile_fingerprint TEXT",
        "ALTER TABLE image_vision_vectors ADD COLUMN IF NOT EXISTS embedding_dim INTEGER",
        "ALTER TABLE image_vision_vectors ADD COLUMN IF NOT EXISTS generation BIGINT NOT NULL DEFAULT 0",
    ]
    post_backfill = [
        "CREATE TABLE IF NOT EXISTS vision_vector_migration_issues ("
        "vector_id TEXT PRIMARY KEY, reason TEXT NOT NULL, detected_at TIMESTAMPTZ NOT NULL DEFAULT NOW())",
        "INSERT INTO vision_vector_migration_issues(vector_id,reason) "
        "SELECT id,'missing_workspace' FROM image_vision_vectors WHERE workspace='' "
        "ON CONFLICT(vector_id) DO UPDATE SET reason=EXCLUDED.reason",
        "CREATE INDEX IF NOT EXISTS idx_ivv_workspace_profile "
        "ON image_vision_vectors(workspace,profile_id,profile_fingerprint)",
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_ivv_workspace_profile_hash "
        "ON image_vision_vectors(workspace,COALESCE(profile_id,'legacy-doubao-embedding'),"
        "COALESCE(profile_fingerprint,'legacy-unscoped'),generation,image_hash)",
        "CREATE TABLE IF NOT EXISTS vision_reindex_jobs ("
        "id TEXT PRIMARY KEY,kb TEXT NOT NULL,actor_id BIGINT NULL,"
        "source_profile_id TEXT NOT NULL,source_fingerprint TEXT,source_embedding_dim INTEGER,"
        "target_profile_id TEXT NOT NULL,target_fingerprint TEXT,target_embedding_dim INTEGER,"
        "generation BIGINT NOT NULL DEFAULT 0,"
        "state TEXT NOT NULL CHECK (state IN ('queued','running','succeeded','failed','cancelled')),"
        "completed INTEGER NOT NULL DEFAULT 0,total INTEGER NOT NULL DEFAULT 0,"
        "error_code TEXT NULL,lease_owner TEXT NULL,heartbeat_at TIMESTAMPTZ NULL,"
        "started_at TIMESTAMPTZ NULL,finished_at TIMESTAMPTZ NULL,"
        "created_at TIMESTAMPTZ NOT NULL DEFAULT NOW())",
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_vision_reindex_active_kb "
        "ON vision_reindex_jobs(kb) WHERE state IN ('queued','running')",
    ]
    async with pool.acquire() as conn:
        async with conn.transaction():
            for statement in pre_backfill:
                await conn.execute(statement)
            embedding_udt = await conn.fetchval(
                "SELECT udt_name FROM information_schema.columns "
                "WHERE table_name='image_vision_vectors' AND column_name='embedding'"
            )
            dimension_expression = (
                "vector_dims(embedding)" if embedding_udt == "vector"
                else "array_length(embedding,1)"
            )
            await conn.execute(
                "UPDATE image_vision_vectors SET "
                "profile_id=COALESCE(profile_id,'legacy-doubao-embedding'),"
                "profile_fingerprint=COALESCE(profile_fingerprint,'legacy-unscoped'),"
                f"embedding_dim=COALESCE(embedding_dim,{dimension_expression}) "
                "WHERE workspace<>'' AND (profile_id IS NULL OR profile_fingerprint IS NULL OR embedding_dim IS NULL)"
            )
            for statement in post_backfill:
                await conn.execute(statement)


async def resolve_user_vlm_profile(user_id: int) -> _CatalogEntry:
    selected = await resolve_user_vlm_selection(user_id)
    return require_available(selected.profile.id, "vlm")


async def resolve_user_vlm_selection(user_id: int) -> _CatalogEntry:
    """Resolve preference precedence without invoking or falling back."""
    personal = await get_user_vlm_preference(user_id)
    defaults = await get_platform_defaults()
    selected = personal or defaults.get("vision_vlm_profile_id") or "legacy-vlm"
    return get_entry(selected, "vlm")


async def probe_profile(profile_id: str) -> dict[str, Any]:
    entry = get_entry(profile_id)
    if not entry.profile.available:
        return {"profile_id": profile_id, "available": False, "reason": entry.profile.unavailable_reason}
    # A probe is deliberately lightweight. Adapters can replace this registry
    # entry with a real async probe without changing the API contract.
    factory = _PROVIDERS.get((entry.profile.provider, entry.profile.kind))
    if factory is not None and hasattr(factory, "probe"):
        result = await factory.probe(entry)
        return {"profile_id": profile_id, "available": bool(result.get("available")), "reason": result.get("reason")}
    return {"profile_id": profile_id, "available": True, "reason": None}


async def audit_vision_event(
    actor_id: int,
    action: str,
    *,
    profile_id: str | None = None,
    previous_profile_id: str | None = None,
    kb: str | None = None,
    result: str = "ok",
) -> None:
    try:
        from raganything.services.auth import audit_log
        await audit_log(
            actor_id=actor_id,
            action=action,
            details={
                "previous_profile_id": previous_profile_id,
                "profile_id": profile_id,
                "kb": kb,
                "result": result,
            },
        )
    except Exception:
        logger.debug("vision audit unavailable", exc_info=True)


async def create_reindex_job(
    *,
    task_id: str,
    kb: str,
    actor_id: int,
    source: _CatalogEntry,
    target: _CatalogEntry,
    total: int,
) -> None:
    """Create one durable reindex job and publish its KB state atomically."""
    pool = await _pg_pool()
    if pool is None:
        raise RuntimeError("PostgreSQL is required for vision reindex jobs")
    task = {"id": task_id, "status": "queued", "progress": 0.0, "completed": 0, "total": total}
    state = {
        "profile_id": source.profile.id,
        "profile_fingerprint": source.fingerprint,
        "embedding_dim": source.profile.embedding_dim,
        "target_profile_id": target.profile.id,
        "target_profile_fingerprint": target.fingerprint,
        "target_embedding_dim": target.profile.embedding_dim,
        "index_state": "reindexing",
        "task": task,
    }
    async with pool.acquire() as conn:
        async with conn.transaction():
            row = await conn.fetchrow(
                "SELECT extra FROM kb_metadata WHERE name=$1 FOR UPDATE", kb
            )
            if row is None:
                raise KeyError(kb)
            extra = row["extra"] if isinstance(row["extra"], dict) else {}
            current = extra.get("vision_embedding", {}) if isinstance(extra, dict) else {}
            if isinstance(current, dict) and current.get("index_state") == "reindexing":
                raise RuntimeError("reindex_in_progress")
            mutation_active = await conn.fetchval(
                "SELECT EXISTS(SELECT 1 FROM uploaded_files WHERE kb_name=$1 "
                "AND status IN ('queued','processing'))",
                kb,
            )
            if mutation_active:
                raise RuntimeError("vision_mutation_in_progress")
            await conn.execute(
                "INSERT INTO vision_reindex_jobs("
                "id,kb,actor_id,source_profile_id,source_fingerprint,source_embedding_dim,"
                "target_profile_id,target_fingerprint,target_embedding_dim,state,total) "
                "VALUES($1,$2,$3,$4,$5,$6,$7,$8,$9,'queued',$10)",
                task_id,
                kb,
                actor_id,
                source.profile.id,
                source.fingerprint,
                source.profile.embedding_dim,
                target.profile.id,
                target.fingerprint,
                target.profile.embedding_dim,
                total,
            )
            await conn.execute(
                "UPDATE kb_metadata SET extra=jsonb_set(COALESCE(extra,'{}'::jsonb),"
                "'{vision_embedding}',$2::jsonb,true), updated_at=NOW() WHERE name=$1",
                kb,
                json.dumps(state, ensure_ascii=True),
            )


def _nano_reindex_path(workspace: str, profile_id: str, fingerprint: str) -> Path | None:
    candidates = [Path(workspace) / f"vdb_image_vision.{fingerprint}.json"]
    if profile_id == "legacy-doubao-embedding":
        candidates.append(Path(workspace) / "vdb_image_vision.json")
    return next((path for path in candidates if path.exists()), None)


def _load_nano_reindex_rows(
    workspace: str,
    profile_id: str,
    fingerprint: str,
) -> tuple[list[dict[str, Any]], Path | None]:
    path = _nano_reindex_path(workspace, profile_id, fingerprint)
    if path is None:
        return [], None
    try:
        raw = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError("nano_source_unreadable") from exc
    data = raw.get("data", []) if isinstance(raw, dict) else []
    if not isinstance(data, list):
        raise RuntimeError("nano_source_unreadable")
    rows: list[dict[str, Any]] = []
    for item in data:
        if not isinstance(item, dict):
            continue
        record_id = str(item.get("__id__") or "")
        rows.append({
            "image_hash": str(item.get("image_hash") or record_id.removeprefix("img-")),
            "doc_id": item.get("doc_id", ""),
            "entity_name": item.get("entity_name", ""),
            "entity_type": item.get("entity_type", "image"),
            "image_path": item.get("image_path", ""),
            "file_path": item.get("file_path", ""),
            "description": item.get("description", ""),
            "vision_model": item.get("vision_model", ""),
        })
    return rows, path


async def run_reindex_job(task_id: str) -> None:
    """Claim and execute a durable side-by-side visual reindex job."""
    pool = await _pg_pool()
    if pool is None:
        return
    async with pool.acquire() as conn:
        job = await conn.fetchrow(
            "UPDATE vision_reindex_jobs SET state='running',started_at=COALESCE(started_at,NOW()),"
            "heartbeat_at=NOW() WHERE id=$1 AND state='queued' RETURNING *",
            task_id,
        )
    if job is None:
        return

    kb = job["kb"]
    actor_id = int(job["actor_id"] or 0)
    target_id = job["target_profile_id"]
    target_fingerprint = job["target_fingerprint"]
    from raganything.services.kb_service import kb_dir, kb_instances
    from raganything.embedding.image_vector_repo import ImageVectorRepository

    workspace = str(Path(kb_dir(kb)).resolve())
    try:
        target = require_available(target_id, "embedding")
        if target.fingerprint != target_fingerprint:
            raise RuntimeError("profile_changed")
        provider = build_embedding_provider(target_id, working_dir=workspace)
        repo = ImageVectorRepository(
            workspace,
            profile_id=target_id,
            profile_fingerprint=target_fingerprint,
        )
        await repo.initialize(target.profile.embedding_dim or 0)
        source_id = job["source_profile_id"]
        source_fingerprint = job["source_fingerprint"]
        use_nano = os.getenv("VISION_VECTOR_STORAGE", "").strip().lower() == "nano"
        rows = []
        source_nano_path = None
        if not use_nano:
            async with pool.acquire() as conn:
                if source_id == "legacy-doubao-embedding":
                    rows = await conn.fetch(
                        "SELECT image_hash,doc_id,entity_name,entity_type,image_path,file_path,description,vision_model "
                        "FROM image_vision_vectors WHERE workspace=$1 AND "
                        "((profile_id=$2 AND profile_fingerprint=$3) OR profile_id IS NULL "
                        "OR (profile_id=$2 AND profile_fingerprint='legacy-unscoped'))",
                        workspace,
                        source_id,
                        source_fingerprint,
                    )
                else:
                    rows = await conn.fetch(
                        "SELECT image_hash,doc_id,entity_name,entity_type,image_path,file_path,description,vision_model "
                        "FROM image_vision_vectors WHERE workspace=$1 AND profile_id=$2 AND profile_fingerprint=$3",
                        workspace,
                        source_id,
                        source_fingerprint,
                    )
        if not rows:
            rows, source_nano_path = _load_nano_reindex_rows(
                workspace, source_id, source_fingerprint
            )
        total = len(rows)
        for completed, row in enumerate(rows, start=1):
            file_path = str(row["file_path"] or row["image_path"] or "")
            vector = await provider.embed_image(file_path, str(row["description"] or ""))
            if vector is None:
                raise RuntimeError("embedding_failed")
            await repo.upsert(row["image_hash"], vector, dict(row))
            progress = completed / max(1, total)
            task = {
                "id": task_id,
                "status": "running",
                "progress": progress,
                "completed": completed,
                "total": total,
            }
            async with pool.acquire() as conn:
                async with conn.transaction():
                    await conn.execute(
                        "UPDATE vision_reindex_jobs SET completed=$2,total=$3,heartbeat_at=NOW() WHERE id=$1",
                        task_id,
                        completed,
                        total,
                    )
                    await conn.execute(
                        "UPDATE kb_metadata SET extra=jsonb_set(extra,'{vision_embedding,task}',$2::jsonb,true) "
                        "WHERE name=$1 AND extra #>> '{vision_embedding,task,id}'=$3",
                        kb,
                        json.dumps(task, ensure_ascii=True),
                        task_id,
                    )

        flush = getattr(repo, "flush", None)
        if flush is not None:
            await flush()

        active_state = {
            "profile_id": target_id,
            "profile_fingerprint": target_fingerprint,
            "embedding_dim": target.profile.embedding_dim,
            "target_profile_id": None,
            "index_state": "idle",
            "task": {
                "id": task_id,
                "status": "succeeded",
                "progress": 1.0,
                "completed": total,
                "total": total,
            },
        }
        async with pool.acquire() as conn:
            async with conn.transaction():
                result = await conn.execute(
                    "UPDATE kb_metadata SET extra=jsonb_set(extra,'{vision_embedding}',$2::jsonb,true),updated_at=NOW() "
                    "WHERE name=$1 AND extra #>> '{vision_embedding,task,id}'=$3",
                    kb,
                    json.dumps(active_state, ensure_ascii=True),
                    task_id,
                )
                if result != "UPDATE 1":
                    raise RuntimeError("activation_conflict")
                await conn.execute(
                    "UPDATE vision_reindex_jobs SET state='succeeded',completed=$2,total=$2,finished_at=NOW(),heartbeat_at=NOW() WHERE id=$1",
                    task_id,
                    total,
                )
        if kb in kb_instances:
            del kb_instances[kb]
        # Activation is already committed. Old-partition cleanup is strictly
        # best effort and must never run the pre-activation rollback path.
        try:
            if source_nano_path is not None:
                target_path = _nano_reindex_path(workspace, target_id, target_fingerprint)
                if source_nano_path != target_path:
                    source_nano_path.unlink(missing_ok=True)
                    source_nano_path.with_suffix(source_nano_path.suffix + ".bak").unlink(missing_ok=True)
            else:
                async with pool.acquire() as conn:
                    if source_id == "legacy-doubao-embedding":
                        await conn.execute(
                            "DELETE FROM image_vision_vectors WHERE workspace=$1 AND "
                            "((profile_id=$2 AND profile_fingerprint=$3) OR profile_id IS NULL "
                            "OR (profile_id=$2 AND profile_fingerprint='legacy-unscoped'))",
                            workspace,
                            source_id,
                            source_fingerprint,
                        )
                    else:
                        await conn.execute(
                            "DELETE FROM image_vision_vectors WHERE workspace=$1 AND profile_id=$2 AND profile_fingerprint=$3",
                            workspace,
                            source_id,
                            source_fingerprint,
                        )
        except Exception:
            logger.warning(
                "vision old-index cleanup deferred task=%s kb=%s",
                task_id,
                kb,
            )
        await audit_vision_event(actor_id, "vision.kb_reindex.succeeded", profile_id=target_id, kb=kb)
    except Exception:
        logger.warning("vision reindex failed task=%s kb=%s code=reindex_failed", task_id, kb)
        failed_task = {
            "id": task_id,
            "status": "failed",
            "progress": 0.0,
            "completed": int(job["completed"] or 0),
            "total": int(job["total"] or 0),
            "error_code": "reindex_failed",
        }
        async with pool.acquire() as conn:
            async with conn.transaction():
                await conn.execute(
                    "DELETE FROM image_vision_vectors WHERE workspace=$1 AND profile_id=$2 AND profile_fingerprint=$3",
                    workspace,
                    target_id,
                    target_fingerprint,
                )
                await conn.execute(
                    "UPDATE vision_reindex_jobs SET state='failed',error_code='reindex_failed',finished_at=NOW() WHERE id=$1",
                    task_id,
                )
                await conn.execute(
                    "UPDATE kb_metadata SET extra=jsonb_set(jsonb_set(extra,'{vision_embedding,index_state}','\"failed\"'::jsonb,true),"
                    "'{vision_embedding,task}',$2::jsonb,true) WHERE name=$1 AND extra #>> '{vision_embedding,task,id}'=$3",
                    kb,
                    json.dumps(failed_task, ensure_ascii=True),
                    task_id,
                )
        target_nano_path = _nano_reindex_path(workspace, target_id, target_fingerprint)
        if target_nano_path is not None:
            target_nano_path.unlink(missing_ok=True)
            target_nano_path.with_suffix(target_nano_path.suffix + ".bak").unlink(missing_ok=True)
        await audit_vision_event(actor_id, "vision.kb_reindex.failed", profile_id=target_id, kb=kb, result="failed")


def schedule_reindex_job(task_id: str) -> None:
    task = asyncio.create_task(run_reindex_job(task_id), name=f"vision-reindex-{task_id}")
    task.add_done_callback(lambda done: done.exception() if not done.cancelled() else None)


async def resume_reindex_jobs() -> None:
    pool = await _pg_pool()
    if pool is None:
        return
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "UPDATE vision_reindex_jobs SET state='queued',lease_owner=NULL "
            "WHERE state='running' AND (heartbeat_at IS NULL OR heartbeat_at < NOW()-INTERVAL '5 minutes') "
            "RETURNING id"
        )
        queued = await conn.fetch("SELECT id FROM vision_reindex_jobs WHERE state='queued'")
    for row in [*rows, *queued]:
        schedule_reindex_job(row["id"])


__all__ = [
    "VisionModelProfile", "VisionLanguageProvider", "VisionEmbeddingProvider",
    "load_catalog", "reset_catalog_cache", "list_profiles", "get_entry",
    "require_available", "register_provider", "get_platform_defaults",
    "build_vlm_callable", "build_contextual_vlm_callable",
    "activate_vlm_snapshot", "activate_vlm_selection", "activate_user_vlm_snapshot",
    "reset_vlm_snapshot", "build_embedding_provider",
    "set_platform_defaults", "get_user_vlm_preference", "set_user_vlm_preference",
    "ensure_vision_model_schema",
    "resolve_user_vlm_profile", "resolve_user_vlm_selection", "probe_profile", "audit_vision_event",
    "create_reindex_job",
    "run_reindex_job", "schedule_reindex_job", "resume_reindex_jobs",
]
