"""PostgreSQL-backed personal/platform settings and immutable resolution.

This module deliberately does not mutate environment variables.  Callers pass
the resolved value objects into request, queue, and worker boundaries.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import time
import uuid
from dataclasses import asdict, dataclass, field, replace
from typing import Any, Awaitable, Callable, Collection, Literal, TypeVar

from raganything.services.pg_state_repo import get_pg_pool

logger = logging.getLogger(__name__)

Section = Literal["models", "ingestion", "retrieval", "runtime"]
SECTIONS: tuple[Section, ...] = ("models", "ingestion", "retrieval", "runtime")
SECTION_PERMISSIONS: dict[Section, str] = {
    "models": "agent:write",
    "ingestion": "kb:write",
    "retrieval": "kb:write",
    "runtime": "kb:write",
}
_Result = TypeVar("_Result")

DEFAULT_SETTINGS: dict[str, dict[str, Any]] = {
    "models": {"llm_profile_id": "legacy-llm", "vlm_profile_id": "legacy-vlm"},
    "ingestion": {
        "parser": "docling", "chunking_strategy": "recursive", "chunk_size": 800,
        "enable_image": True, "enable_table": True, "enable_equation": True,
        "enable_video": False, "entity_types": [], "minimum_relation_degree": 0,
        "parsers_by_type": {},
    },
    "retrieval": {
        "preset": "balanced", "rrf_k": 60, "bm25_top_k": 50, "vector_top_k": 100,
        "graph_top_k": 30, "graph_depth": 2, "channels": ["bm25", "vector", "graph"],
        "bm25_tokenizer": "jieba", "bm25_k1": 1.5, "bm25_b": 0.75,
    },
    "runtime": {"llm_timeout": 180, "personal_concurrency": 7},
}

# Named modes resolve into fixed retrieval parameters. This keeps the API
# executable and auditable even when a client submits only the preset name.
RETRIEVAL_PRESETS: dict[str, dict[str, Any]] = {
    "balanced": {"rrf_k": 60, "bm25_top_k": 50, "vector_top_k": 100, "graph_top_k": 30, "graph_depth": 2, "channels": ["bm25", "vector", "graph"], "bm25_tokenizer": "jieba", "bm25_k1": 1.5, "bm25_b": 0.75},
    "precise": {"rrf_k": 60, "bm25_top_k": 30, "vector_top_k": 60, "graph_top_k": 15, "graph_depth": 1, "channels": ["bm25", "vector"], "bm25_tokenizer": "jieba", "bm25_k1": 1.5, "bm25_b": 0.75},
    "broad": {"rrf_k": 60, "bm25_top_k": 100, "vector_top_k": 200, "graph_top_k": 60, "graph_depth": 3, "channels": ["bm25", "vector", "graph"], "bm25_tokenizer": "jieba", "bm25_k1": 1.5, "bm25_b": 0.75},
}

ALLOWED_FIELDS: dict[str, set[str]] = {key: set(value) for key, value in DEFAULT_SETTINGS.items()}

# Per-file-type parser override keys and the genuine capability matrix for
# every bundled parser.  Ids outside the matrix are custom parsers: they are
# allowed for every type so PATCH validation never blocks extensions.
PARSER_TYPES: tuple[str, ...] = ("pdf", "office", "image")
PARSER_SUPPORTED_TYPES: dict[str, tuple[str, ...]] = {
    "docling": ("pdf", "office"),
    "mineru": ("pdf", "office", "image"),
    "marker": ("pdf", "office", "image"),
    "paddleocr": ("pdf", "office", "image"),
    "opendataloader": ("pdf",),
}


def _parser_supported_types(parser_id: str) -> tuple[str, ...]:
    """Return the file types a parser supports; unknown ids pass all types."""
    return PARSER_SUPPORTED_TYPES.get(parser_id, PARSER_TYPES)


# Platform policy deliberately uses a small, closed JSON schema.  Keeping this
# separate from the generic ``settings`` table prevents deployment credentials
# from becoming an accidentally serializable administration value.
PLATFORM_POLICY_KEYS = frozenset({"defaults", "allowed", "limits", "state"})
PLATFORM_ALLOWED_KEYS = frozenset({
    "llm_profile_ids", "vlm_profile_ids", "embedding_profile_ids",
    "parsers", "chunking_strategies", "bm25_tokenizers",
})
PLATFORM_LIMIT_RANGES: dict[str, tuple[int, int]] = {
    "worker_concurrency": (1, 1024),
    "provider_concurrency": (1, 1024),
    "personal_concurrency": (1, 1024),
    "llm_timeout": (1, 3600),
    "bm25_top_k": (1, 10000),
    "vector_top_k": (1, 10000),
    "graph_top_k": (1, 10000),
    "graph_depth": (0, 64),
    "cache_capacity": (1, 1_000_000),
    "interactive_wait_seconds": (0, 300),
}
PLATFORM_STATE_KEYS = frozenset({"retrieval_preset_version", "read_only"})
_FORBIDDEN_POLICY_KEY_PARTS = ("api_key", "apikey", "secret", "password", "base_url", "host", "endpoint", "env")


class ProfileUnavailableError(RuntimeError):
    """The stored catalog knows the selected profile, but it cannot run."""


@dataclass(frozen=True)
class ModelSelection:
    llm_profile_id: str
    vlm_profile_id: str


@dataclass(frozen=True)
class ProcessingTaskSettings:
    parser: str
    chunking_strategy: str
    chunk_size: int
    enable_image: bool
    enable_table: bool
    enable_equation: bool
    enable_video: bool
    entity_types: tuple[str, ...]
    minimum_relation_degree: int
    parsers_by_type: dict[str, str] = field(default_factory=dict)
    video_index_profile_version: str = "v2"


@dataclass(frozen=True)
class RetrievalOptions:
    preset: str
    rrf_k: int
    bm25_top_k: int
    vector_top_k: int
    graph_top_k: int
    graph_depth: int
    channels: tuple[str, ...]
    bm25_tokenizer: str
    bm25_k1: float
    bm25_b: float


@dataclass(frozen=True)
class QuotaOptions:
    llm_timeout: int
    personal_concurrency: int


@dataclass(frozen=True)
class ModelProfileFingerprints:
    llm: str
    vlm: str


@dataclass(frozen=True)
class ResolvedUserSettings:
    models: ModelSelection
    ingestion: ProcessingTaskSettings
    retrieval: RetrievalOptions
    runtime: QuotaOptions
    revision: int
    fingerprint: str
    profile_fingerprints: ModelProfileFingerprints | None = None

    def snapshot(self) -> dict[str, Any]:
        payload = asdict(self)
        if self.profile_fingerprints is None:
            payload.pop("profile_fingerprints", None)
        # Keep the durable task body self-describing.  This is a public hash
        # of resolved values, never a credential or endpoint.
        payload["fingerprint"] = self.fingerprint
        return payload


def _copy(value: Any) -> Any:
    return json.loads(json.dumps(value))


def available_sections(permissions: Collection[str] | None = None) -> tuple[Section, ...]:
    """Return task-setting sections permitted by a live permission set.

    ``None`` preserves the unrestricted service behavior used by internal
    maintenance callers; authenticated HTTP/request boundaries pass a concrete
    set so permission loss masks only the user-stored layer.
    """
    if permissions is None:
        return SECTIONS
    granted = set(permissions)
    return tuple(section for section in SECTIONS if SECTION_PERMISSIONS[section] in granted)


async def available_sections_for_user(user_id: int) -> tuple[Section, ...]:
    """Resolve setting capabilities from the current authoritative role."""
    from raganything.services.auth import has_permission

    permissions = [
        permission for permission in set(SECTION_PERMISSIONS.values())
        if await has_permission(int(user_id), permission)
    ]
    return available_sections(permissions)


def resolved_sections(permitted_sections: Collection[str] | None) -> tuple[Section, ...]:
    """Return the known task sections from an already-resolved projection.

    Callers resolve capabilities once (``available_sections`` / the router
    helper) and pass the resulting section names downstream; re-running
    ``available_sections`` here would misinterpret section names as
    permission strings and silently drop every section.  ``None`` preserves
    the unrestricted service behavior used by internal maintenance callers.
    """
    if permitted_sections is None:
        return SECTIONS
    allowed = set(permitted_sections)
    return tuple(section for section in SECTIONS if section in allowed)


def _project_sections(values: dict[str, Any], sections: Collection[str]) -> dict[str, Any]:
    allowed = set(sections)
    return {section: _copy(value) for section, value in values.items() if section in allowed}


def project_settings_options(options: dict[str, Any], sections: Collection[str]) -> dict[str, Any]:
    """Remove settings choices that belong to sections the caller cannot use."""
    allowed_sections = tuple(section for section in SECTIONS if section in set(sections))
    result = _copy(options)
    result["sections"] = {
        section: result.get("sections", {}).get(section, [])
        for section in allowed_sections
    }
    allowed = result.get("allowed", {})
    limits = result.get("limits", {})
    permitted_allowed = set()
    permitted_limits = set()
    if "models" in allowed_sections:
        permitted_allowed.update(("llm_profile_ids", "vlm_profile_ids"))
    if "ingestion" in allowed_sections:
        permitted_allowed.update(("parsers", "chunking_strategies"))
    if "retrieval" in allowed_sections:
        permitted_allowed.add("bm25_tokenizers")
        permitted_limits.update(("bm25_top_k", "vector_top_k", "graph_top_k", "graph_depth"))
    if "runtime" in allowed_sections:
        permitted_limits.update(("personal_concurrency", "llm_timeout"))
    result["allowed"] = {key: value for key, value in allowed.items() if key in permitted_allowed}
    result["limits"] = {key: value for key, value in limits.items() if key in permitted_limits}
    if "retrieval" not in allowed_sections:
        result.pop("presets", None)
        result.pop("preset_values", None)
        result.pop("channels", None)
    if "ingestion" not in allowed_sections:
        result.pop("parsers", None)
        result.pop("chunking_strategies", None)
    return result


def _json_object(value: Any) -> dict[str, Any]:
    """Normalize asyncpg JSONB values to an object before resolving settings.

    asyncpg returns JSON/JSONB columns as strings unless a connection codec is
    registered.  Settings rows can therefore originate as either a mapping
    (tests and alternate drivers) or a serialized object (the production PG
    pool).  Invalid legacy values safely inherit instead of breaking every
    settings read for that user.
    """
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            decoded = json.loads(value)
        except json.JSONDecodeError:
            return {}
        return decoded if isinstance(decoded, dict) else {}
    return {}


def _merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    result = _copy(base)
    for section in SECTIONS:
        if isinstance(override.get(section), dict):
            result[section].update(override[section])
    return result


def _legacy_environment_settings() -> dict[str, dict[str, Any]]:
    """Build the lowest-precedence compatibility layer once per resolution."""
    legacy = _copy(DEFAULT_SETTINGS)
    mappings: dict[str, dict[str, tuple[str, Any]]] = {
        "models": {
            "llm_profile_id": ("LLM_PROFILE_ID", str),
            "vlm_profile_id": ("VISION_VLM_PROFILE_ID", str),
        },
        "ingestion": {
            "parser": ("PARSER", str),
            "chunking_strategy": ("CHUNKING_STRATEGY", str),
            "chunk_size": ("CHUNK_SIZE", int),
        },
        "retrieval": {
            "rrf_k": ("RRF_K", int),
            "bm25_top_k": ("BM25_TOP_K", int),
            "vector_top_k": ("VECTOR_TOP_K", int),
            "graph_top_k": ("GRAPH_TOP_K", int),
            "graph_depth": ("GRAPH_DEPTH", int),
            "bm25_tokenizer": ("BM25_TOKENIZER", str),
            "bm25_k1": ("BM25_K1", float),
            "bm25_b": ("BM25_B", float),
        },
        "runtime": {
            "llm_timeout": ("LLM_TIMEOUT", int),
            "personal_concurrency": ("MAX_ASYNC", int),
        },
    }
    for section, fields in mappings.items():
        for field, (env_name, converter) in fields.items():
            raw = os.getenv(env_name)
            if raw is None or not raw.strip():
                continue
            try:
                legacy[section][field] = converter(raw.strip())
            except (TypeError, ValueError):
                continue
    for field, env_name in (
        ("enable_image", "ENABLE_IMAGE_PROCESSING"),
        ("enable_table", "ENABLE_TABLE_PROCESSING"),
        ("enable_equation", "ENABLE_EQUATION_PROCESSING"),
        ("enable_video", "ENABLE_VIDEO_PROCESSING"),
    ):
        raw = os.getenv(env_name)
        if raw is not None and raw.strip().lower() in {"true", "false"}:
            legacy["ingestion"][field] = raw.strip().lower() == "true"
    return legacy


def _normalize_parsers_by_type(parsers_by_type: Any) -> dict[str, Any]:
    """Return the per-type parser map without empty-string override keys.

    Empty-string values mean 'follow the global parser' and must never be
    persisted or resolved; a non-object legacy value safely falls back to an
    empty map so a corrupt row cannot break every settings read.
    """
    if not isinstance(parsers_by_type, dict):
        return {}
    return {
        key: value.strip()
        for key, value in parsers_by_type.items()
        if isinstance(value, str) and value.strip()
    }


def _normalize_section_values(section: str, values: dict[str, Any]) -> dict[str, Any]:
    """Return normalized values for persistence without mutating the input."""
    if section != "ingestion" or "parsers_by_type" not in values:
        return values
    normalized = dict(values)
    normalized["parsers_by_type"] = _normalize_parsers_by_type(normalized["parsers_by_type"])
    return normalized


def _validate_section(section: str, values: dict[str, Any] | None) -> None:
    if section not in SECTIONS:
        raise ValueError("unknown settings section")
    if values is None:
        return
    if not isinstance(values, dict) or not set(values).issubset(ALLOWED_FIELDS[section]):
        raise ValueError("invalid settings fields")
    text_fields = {
        "models": {"llm_profile_id", "vlm_profile_id"},
        "ingestion": {"parser", "chunking_strategy"},
        "retrieval": {"preset", "bm25_tokenizer"},
        "runtime": set(),
    }
    for key in text_fields[section].intersection(values):
        if not isinstance(values[key], str) or not values[key].strip():
            raise ValueError(f"{key} must be a non-empty string")
    bool_fields = {"enable_image", "enable_table", "enable_equation", "enable_video"}
    for key in bool_fields.intersection(values):
        if not isinstance(values[key], bool):
            raise ValueError(f"{key} must be a boolean")
    if "entity_types" in values and (
        not isinstance(values["entity_types"], list)
        or any(not isinstance(value, str) or not value.strip() for value in values["entity_types"])
    ):
        raise ValueError("entity_types must be a list of non-empty strings")
    if "chunk_size" in values and (not _is_int(values["chunk_size"]) or values["chunk_size"] < 64):
        raise ValueError("chunk_size must be an integer >= 64")
    if "parsers_by_type" in values:
        parsers_by_type = values["parsers_by_type"]
        if not isinstance(parsers_by_type, dict):
            raise ValueError("parsers_by_type must be an object")
        for type_key, parser_id in parsers_by_type.items():
            if type_key not in PARSER_TYPES:
                raise ValueError(f"unknown parser type: {type_key}")
            if not isinstance(parser_id, str):
                raise ValueError("parsers_by_type values must be strings")
            if parser_id and not parser_id.strip():
                raise ValueError("parsers_by_type values must be a parser id")
            if parser_id and type_key not in _parser_supported_types(parser_id.strip()):
                raise ValueError(f"parser {parser_id} does not support type {type_key}")
    for key in ("rrf_k", "bm25_top_k", "vector_top_k", "graph_top_k", "graph_depth", "llm_timeout", "personal_concurrency", "minimum_relation_degree"):
        if key in values and (not _is_int(values[key]) or values[key] < 0):
            raise ValueError(f"{key} must be a non-negative integer")
    if "channels" in values and (not isinstance(values["channels"], list) or not set(values["channels"]).issubset({"bm25", "vector", "graph"})):
        raise ValueError("invalid retrieval channels")
    for key, upper in (("bm25_k1", 10.0), ("bm25_b", 1.0)):
        if key in values and (
            isinstance(values[key], bool)
            or not isinstance(values[key], (int, float))
            or not 0.0 <= float(values[key]) <= upper
        ):
            raise ValueError(f"{key} must be a number between 0 and {upper}")


def _is_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _has_forbidden_policy_key(value: Any) -> bool:
    if not isinstance(value, dict):
        return False
    for key, nested in value.items():
        normalized = str(key).lower().replace("-", "_")
        if any(part in normalized for part in _FORBIDDEN_POLICY_KEY_PARTS):
            return True
        if _has_forbidden_policy_key(nested):
            return True
    return False


def deployment_platform_read_only() -> bool:
    """Return the deployment-level write lock without exposing its env name."""
    return os.getenv("PLATFORM_SETTINGS_READ_ONLY", "false").strip().lower() in {"1", "true", "yes", "on"}


def _validate_model_allow_lists(allowed: dict[str, Any]) -> None:
    try:
        from raganything.services.vision_models import list_model_profiles
        profiles = {profile.id: profile.kind for profile in list_model_profiles()}
    except Exception as exc:
        raise ValueError("model catalog unavailable") from exc
    expected_kind = {
        "llm_profile_ids": "llm",
        "vlm_profile_ids": "vlm",
        "embedding_profile_ids": "embedding",
    }
    for field, kind in expected_kind.items():
        ids = allowed.get(field, [])
        for profile_id in ids:
            if profiles.get(profile_id) != kind:
                raise ValueError(f"{field} contains an unknown {kind} profile")


def validate_platform_policy(settings: dict[str, Any]) -> None:
    """Validate a credential-free, typed platform policy before persistence."""
    if not isinstance(settings, dict):
        raise ValueError("invalid platform policy fields")
    if _has_forbidden_policy_key(settings):
        raise ValueError("platform policy cannot contain deployment credentials or endpoints")
    if not set(settings).issubset(PLATFORM_POLICY_KEYS):
        raise ValueError("invalid platform policy fields")

    defaults = settings.get("defaults", {})
    if not isinstance(defaults, dict) or not set(defaults).issubset(SECTIONS):
        raise ValueError("invalid platform defaults")
    for section, values in defaults.items():
        _validate_section(section, values)

    allowed = settings.get("allowed", {})
    if not isinstance(allowed, dict) or not set(allowed).issubset(PLATFORM_ALLOWED_KEYS):
        raise ValueError("invalid platform allowed values")
    for field, values in allowed.items():
        if not isinstance(values, list) or any(not isinstance(value, str) or not value.strip() for value in values):
            raise ValueError(f"{field} must be a list of non-empty strings")
        if len(set(values)) != len(values):
            raise ValueError(f"{field} must not contain duplicates")
    _validate_model_allow_lists(allowed)

    limits = settings.get("limits", {})
    if not isinstance(limits, dict) or not set(limits).issubset(PLATFORM_LIMIT_RANGES):
        raise ValueError("invalid platform limits")
    for field, value in limits.items():
        minimum, maximum = PLATFORM_LIMIT_RANGES[field]
        if not _is_int(value) or not minimum <= value <= maximum:
            raise ValueError(f"{field} must be an integer between {minimum} and {maximum}")

    state = settings.get("state", {})
    if not isinstance(state, dict) or not set(state).issubset(PLATFORM_STATE_KEYS):
        raise ValueError("invalid platform state")
    if "retrieval_preset_version" in state and (
        not isinstance(state["retrieval_preset_version"], str) or not state["retrieval_preset_version"].strip()
    ):
        raise ValueError("retrieval_preset_version must be a non-empty string")
    if "read_only" in state and not isinstance(state["read_only"], bool):
        raise ValueError("read_only must be a boolean")


def _safe_platform_policy(settings: dict[str, Any] | None) -> dict[str, Any]:
    """Project stored data to the public policy schema, dropping legacy keys.

    This is intentionally defensive: an old/corrupt row must cause neither a
    provider endpoint nor a credential-shaped key to be returned from the new
    administration API.
    """
    raw = settings if isinstance(settings, dict) else {}
    result: dict[str, Any] = {}
    defaults = raw.get("defaults", raw if set(raw).intersection(SECTIONS) else {})
    if isinstance(defaults, dict):
        result["defaults"] = {
            section: {
                key: _copy(value)
                for key, value in values.items()
                if key in ALLOWED_FIELDS[section]
            }
            for section, values in defaults.items()
            if section in SECTIONS and isinstance(values, dict)
        }
    for group, allowed_keys in (("allowed", PLATFORM_ALLOWED_KEYS), ("limits", frozenset(PLATFORM_LIMIT_RANGES)), ("state", PLATFORM_STATE_KEYS)):
        values = raw.get(group, {})
        if isinstance(values, dict):
            result[group] = {key: _copy(value) for key, value in values.items() if key in allowed_keys}
    result.setdefault("defaults", {})
    result.setdefault("allowed", {})
    result.setdefault("limits", {})
    result.setdefault("state", {})
    result["state"]["read_only"] = bool(result["state"].get("read_only", False) or deployment_platform_read_only())
    result["state"].setdefault("retrieval_preset_version", "v1")
    return result


def _validate_section_against_platform_policy(
    section: str,
    values: dict[str, Any] | None,
    policy: dict[str, Any],
) -> None:
    """Reject choices that are outside a non-empty platform allow-list."""
    if values is None:
        return
    allowed = _safe_platform_policy(policy)["allowed"]
    field_to_allow_list = {
        "llm_profile_id": "llm_profile_ids",
        "vlm_profile_id": "vlm_profile_ids",
        "parser": "parsers",
        "chunking_strategy": "chunking_strategies",
        "bm25_tokenizer": "bm25_tokenizers",
    }
    for field, allow_list in field_to_allow_list.items():
        if field not in values:
            continue
        permitted = allowed.get(allow_list, [])
        if permitted and values[field] not in permitted:
            raise ValueError(f"{field} is not permitted by platform policy")

    if section == "ingestion" and "parsers_by_type" in values:
        permitted = allowed.get("parsers", [])
        if permitted:
            for type_key, parser_id in values["parsers_by_type"].items():
                if parser_id and parser_id not in permitted:
                    raise ValueError(f"parsers_by_type.{type_key} is not permitted by platform policy")

    if section != "models":
        return
    try:
        from raganything.services.vision_models import list_model_profiles
        profiles = {profile.id: profile for profile in list_model_profiles()}
    except Exception as exc:
        raise ProfileUnavailableError("model catalog unavailable") from exc
    for field, kind in (("llm_profile_id", "llm"), ("vlm_profile_id", "vlm")):
        if field not in values:
            continue
        profile = profiles.get(values[field])
        if profile is None or profile.kind != kind:
            raise ValueError(f"{field} must reference a configured {kind} profile")
        if not profile.available:
            raise ProfileUnavailableError(f"{field} is currently unavailable")


def resolve_settings(
    *,
    stored: dict[str, Any] | None,
    platform: dict[str, Any] | None,
    revision: int,
    resource_settings: dict[str, Any] | None = None,
    knowledge_base_settings: dict[str, Any] | None = None,
    request_overrides: dict[str, Any] | None = None,
    index_constraints: dict[str, Any] | None = None,
) -> tuple[ResolvedUserSettings, dict[str, dict[str, str]], dict[str, dict[str, Any]]]:
    """Resolve every settings layer into one immutable effective value."""
    platform = platform or {}
    effective = _legacy_environment_settings()
    sources = {
        section: {key: "legacy_environment" for key in values}
        for section, values in effective.items()
    }

    for layer, source in (
        (platform.get("defaults", {}), "platform_default"),
        (resource_settings or {}, "resource_setting"),
        (stored or {}, "user_setting"),
        (knowledge_base_settings or {}, "knowledge_base_setting"),
        (request_overrides or {}, "request_selection"),
    ):
        for section in SECTIONS:
            values = layer.get(section) if isinstance(layer, dict) else None
            if not isinstance(values, dict):
                continue
            # A named preset establishes its field set at this precedence
            # layer. Explicit fields in the same layer intentionally follow
            # it so request/task overrides continue to win.
            preset = values.get("preset") if section == "retrieval" else None
            if preset in RETRIEVAL_PRESETS:
                for key, value in RETRIEVAL_PRESETS[preset].items():
                    effective[section][key] = value
                    sources[section][key] = source
            for key, value in values.items():
                if section == "ingestion" and key == "parsers_by_type":
                    value = _normalize_parsers_by_type(value)
                    merged = dict(effective[section].get(key) or {})
                    merged.update(value)
                    effective[section][key] = merged
                    sources[section][key] = source
                    continue
                effective[section][key] = value
                sources[section][key] = source

    constraints: dict[str, dict[str, Any]] = {}
    allowed = _safe_platform_policy(platform)["allowed"]
    ingestion_allowed = {
        "parser": allowed.get("parsers", []),
        "chunking_strategy": allowed.get("chunking_strategies", []),
    }
    for field, permitted in ingestion_allowed.items():
        selected = effective["ingestion"].get(field)
        if permitted and selected not in permitted:
            platform_default = ((platform.get("defaults") or {}).get("ingestion") or {}).get(field)
            fallback = platform_default if platform_default in permitted else permitted[0]
            constraints.setdefault("ingestion", {})[field] = {
                "requested": selected,
                "allowed": permitted,
            }
            effective["ingestion"][field] = fallback
            sources["ingestion"][field] = "platform_allow_list"
    permitted_parsers = allowed.get("parsers", [])
    if permitted_parsers:
        parser_overrides = effective["ingestion"].get("parsers_by_type") or {}
        invalid_overrides = {
            type_key: parser_id
            for type_key, parser_id in parser_overrides.items()
            if parser_id not in permitted_parsers
        }
        if invalid_overrides:
            constraints.setdefault("ingestion", {})["parsers_by_type"] = {
                "requested": invalid_overrides,
                "allowed": permitted_parsers,
            }
            effective["ingestion"]["parsers_by_type"] = {
                type_key: parser_id
                for type_key, parser_id in parser_overrides.items()
                if parser_id in permitted_parsers
            }
            sources["ingestion"]["parsers_by_type"] = "platform_allow_list"
    for section in SECTIONS:
        values = (index_constraints or {}).get(section)
        if not isinstance(values, dict):
            continue
        for field, required in values.items():
            if effective[section].get(field) != required:
                constraints.setdefault(section, {})[field] = {
                    "requested": effective[section].get(field),
                    "required": required,
                }
                effective[section][field] = required
                sources[section][field] = "index_compatibility"

    limits = platform.get("limits", {}) if isinstance(platform.get("limits"), dict) else {}
    for section, field in (("runtime", "personal_concurrency"), ("runtime", "llm_timeout"), ("retrieval", "bm25_top_k"), ("retrieval", "vector_top_k"), ("retrieval", "graph_top_k"), ("retrieval", "graph_depth")):
        cap = limits.get(field)
        if isinstance(cap, (int, float)) and effective[section].get(field, 0) > cap:
            constraints.setdefault(section, {})[field] = {"requested": effective[section][field], "maximum": cap}
            effective[section][field] = cap
            sources[section][field] = "platform_limit"

    # Provider and worker ceilings are outer limits.  A user can save a
    # larger personal preference, but its effective concurrency must never
    # exceed either shared capacity.
    if effective["runtime"]["personal_concurrency"]:
        outer_caps = [
            int(limits[field]) for field in ("provider_concurrency", "worker_concurrency")
            if isinstance(limits.get(field), (int, float)) and limits[field] > 0
        ]
        if outer_caps:
            cap = min(outer_caps)
            if effective["runtime"]["personal_concurrency"] > cap:
                constraints.setdefault("runtime", {})["personal_concurrency"] = {
                    "requested": effective["runtime"]["personal_concurrency"],
                    "maximum": cap,
                }
                effective["runtime"]["personal_concurrency"] = cap
                sources["runtime"]["personal_concurrency"] = "platform_limit"

    canonical = json.dumps(effective, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
    fingerprint = hashlib.sha256(canonical.encode()).hexdigest()[:32]
    resolved = ResolvedUserSettings(
        models=ModelSelection(**effective["models"]),
        ingestion=ProcessingTaskSettings(
            **{**effective["ingestion"], "entity_types": tuple(effective["ingestion"]["entity_types"])}
        ),
        retrieval=RetrievalOptions(
            **{**effective["retrieval"], "channels": tuple(effective["retrieval"]["channels"])}
        ),
        runtime=QuotaOptions(**effective["runtime"]), revision=revision, fingerprint=fingerprint,
    )
    return resolved, sources, constraints


async def _platform_row() -> tuple[dict[str, Any], int]:
    pool = get_pg_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT settings, revision FROM platform_settings WHERE id=1")
    return (_safe_platform_policy(_json_object(row["settings"]) if row else {}), int(row["revision"] if row else 0))


async def get_user_settings(user_id: int, *, permitted_sections: Collection[str] | None = None) -> dict[str, Any]:
    pool = get_pg_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT settings, revision FROM user_settings WHERE user_id=$1", user_id)
    stored, revision = ((_json_object(row["settings"]) if row else {}), int(row["revision"] if row else 0))
    platform, _ = await _platform_row()
    resolved, sources, constraints = resolve_settings(stored=stored, platform=platform, revision=revision)
    sections = resolved_sections(permitted_sections)
    return {
        "revision": revision,
        "stored": _project_sections(stored, sections),
        "effective": _project_sections(resolved.snapshot(), sections),
        "sources": _project_sections(sources, sections),
        "constraints": _project_sections(constraints, sections),
        "fingerprint": resolved.fingerprint,
        "available_sections": list(sections),
    }


async def resolve_user_settings_for_task(
    user_id: int,
    *,
    resource_settings: dict[str, Any] | None = None,
    knowledge_base_settings: dict[str, Any] | None = None,
    request_overrides: dict[str, Any] | None = None,
    index_constraints: dict[str, Any] | None = None,
    permitted_sections: Collection[str] | None = None,
) -> ResolvedUserSettings:
    """Resolve once for enqueue boundaries; workers subsequently use snapshots."""
    pool = get_pg_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT settings, revision FROM user_settings WHERE user_id=$1", user_id)
    stored, revision = ((_json_object(row["settings"]) if row else {}), int(row["revision"] if row else 0))
    platform, _ = await _platform_row()
    stored = _project_sections(stored, resolved_sections(permitted_sections))
    for section, values in (request_overrides or {}).items():
        _validate_section(section, values)
        _validate_section_against_platform_policy(section, values, platform)
    resolved, _, _ = resolve_settings(
        stored=stored,
        platform=platform,
        revision=revision,
        resource_settings=resource_settings,
        knowledge_base_settings=knowledge_base_settings,
        request_overrides=request_overrides,
        index_constraints=index_constraints,
    )
    # Freeze the public model configuration identities at the same boundary
    # as the rest of the task settings. Availability is checked by the caller
    # according to the workload: text queries require only the LLM, while
    # ingestion and image queries also require the VLM.
    from raganything.services.vision_models import get_entry

    return replace(
        resolved,
        profile_fingerprints=ModelProfileFingerprints(
            llm=get_entry(resolved.models.llm_profile_id, "llm").fingerprint,
            vlm=get_entry(resolved.models.vlm_profile_id, "vlm").fingerprint,
        ),
    )


def with_task_ingestion_overrides(
    resolved: ResolvedUserSettings,
    *,
    chunking_strategy: str | None = None,
    enable_image: bool | None = None,
    enable_table: bool | None = None,
    enable_equation: bool | None = None,
    enable_video: bool | None = None,
) -> ResolvedUserSettings:
    """Return a new, fingerprinted snapshot with explicit upload overrides.

    Upload form values are part of a task's effective configuration, rather
    than transient queue metadata.  Keep the resolved object immutable and
    recompute its fingerprint whenever one of those values is supplied.
    """
    ingestion_values = asdict(resolved.ingestion)
    if chunking_strategy:
        ingestion_values["chunking_strategy"] = chunking_strategy
    for field, value in (
        ("enable_image", enable_image),
        ("enable_table", enable_table),
        ("enable_equation", enable_equation),
        ("enable_video", enable_video),
    ):
        if value is not None:
            ingestion_values[field] = bool(value)

    # This marker is persisted on every new task snapshot.  The Worker accepts
    # only an explicit v2 marker for a video, so old/malformed snapshots never
    # silently run under a different processor.
    ingestion_values["video_index_profile_version"] = "v2"

    ingestion_values["entity_types"] = tuple(ingestion_values["entity_types"])
    ingestion = ProcessingTaskSettings(**ingestion_values)
    effective = {
        "models": asdict(resolved.models),
        "ingestion": asdict(ingestion),
        "retrieval": asdict(resolved.retrieval),
        "runtime": asdict(resolved.runtime),
    }
    canonical = json.dumps(effective, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
    return replace(
        resolved,
        ingestion=ingestion,
        fingerprint=hashlib.sha256(canonical.encode()).hexdigest()[:32],
    )


async def patch_user_settings(user_id: int, section: Section, values: dict[str, Any] | None, expected_revision: int) -> dict[str, Any] | None:
    _validate_section(section, values)
    platform, _ = await _platform_row()
    _validate_section_against_platform_policy(section, values, platform)
    pool = get_pg_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            # A missing row cannot be protected by SELECT ... FOR UPDATE.
            # Serialize the first insert and all later updates by user so two
            # revision-0 PATCH requests cannot both succeed.
            await conn.execute(
                "SELECT pg_advisory_xact_lock(hashtext($1))",
                f"user-settings:{user_id}",
            )
            row = await conn.fetchrow("SELECT settings, revision FROM user_settings WHERE user_id=$1 FOR UPDATE", user_id)
            current, revision = ((_json_object(row["settings"]) if row else {}), int(row["revision"] if row else 0))
            if revision != expected_revision:
                return None
            next_settings = _copy(current)
            if values is None:
                next_settings.pop(section, None)
            else:
                next_settings[section] = _normalize_section_values(section, values)
            next_revision = revision + 1
            await conn.execute(
                "INSERT INTO user_settings(user_id,settings,revision) VALUES($1,$2::jsonb,$3) "
                "ON CONFLICT(user_id) DO UPDATE SET settings=EXCLUDED.settings,revision=EXCLUDED.revision,updated_at=NOW()",
                user_id, json.dumps(next_settings), next_revision,
            )
    return await get_user_settings(user_id)


async def get_platform_settings() -> dict[str, Any]:
    settings, revision = await _platform_row()
    return {"revision": revision, "settings": settings}


async def put_platform_settings(settings: dict[str, Any], expected_revision: int) -> dict[str, Any] | None:
    if deployment_platform_read_only():
        raise PermissionError("platform policy is read-only in this deployment")
    validate_platform_policy(settings)
    pool = get_pg_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            current = await conn.fetchrow(
                "SELECT settings,revision FROM platform_settings WHERE id=1 FOR UPDATE"
            )
            if current is None:
                raise RuntimeError("platform policy migration is not applied")
            if int(current["revision"]) != expected_revision:
                return None
            current_settings = _safe_platform_policy(_json_object(current["settings"]))
            if bool(current_settings.get("state", {}).get("read_only", False)):
                raise PermissionError("platform policy is read-only")
            result = await conn.fetchrow(
                "UPDATE platform_settings SET settings=$1::jsonb,revision=revision+1,updated_at=NOW() "
                "WHERE id=1 RETURNING revision,settings",
                json.dumps(settings),
            )
    changed_sections = sorted(
        key for key in PLATFORM_POLICY_KEYS
        if current_settings.get(key) != _safe_platform_policy(settings).get(key)
    )
    return {
        "revision": int(result["revision"]),
        "settings": _safe_platform_policy(result["settings"]),
        "changed_sections": changed_sections,
    }


# In-process TTL cache for parser installation probes.  Probing can spawn a
# subprocess or re-import heavy libraries, so avoid re-running it on every
# options request; failures are recorded as unavailable instead of 500s.
_PARSER_PROBE_TTL_SECONDS = 60.0
_parser_availability_cache: dict[str, tuple[float, bool]] = {}


def _probe_parser_available(parser_id: str) -> bool:
    """Return whether a parser is installed, never raising for the caller."""
    from raganything.parser import get_parser

    try:
        return bool(get_parser(parser_id).check_installation())
    except Exception:
        logger.exception("parser installation probe failed for %s", parser_id)
        return False


def _parser_catalog() -> list[dict[str, Any]]:
    """Return the supported parser catalog with installation availability."""
    from raganything.parser import SUPPORTED_PARSERS

    now = time.monotonic()
    result = []
    for parser_id in SUPPORTED_PARSERS:
        cached = _parser_availability_cache.get(parser_id)
        if cached is not None and now - cached[0] < _PARSER_PROBE_TTL_SECONDS:
            available = cached[1]
        else:
            available = _probe_parser_available(parser_id)
            _parser_availability_cache[parser_id] = (now, available)
        result.append({
            "id": parser_id,
            "name": parser_id,
            "available": available,
            "supported_types": list(_parser_supported_types(parser_id)),
        })
    return result


def _chunking_strategy_catalog() -> list[dict[str, Any]]:
    """Return the supported chunking strategy catalog with metadata."""
    from raganything.chunking import STRATEGY_META

    return [
        {
            "id": strategy_id,
            "name": meta.get("name", strategy_id),
            "description": meta.get("description", ""),
            "cost": meta.get("cost", ""),
            "cost_level": meta.get("cost_level", ""),
        }
        for strategy_id, meta in STRATEGY_META.items()
    ]


def settings_options(
    platform: dict[str, Any] | None = None,
    *,
    include_ingestion_catalogs: bool = True,
) -> dict[str, Any]:
    policy = _safe_platform_policy(platform)
    result = {
        "sections": {section: sorted(fields) for section, fields in ALLOWED_FIELDS.items()},
        "presets": ["balanced", "precise", "broad", "custom"],
        "preset_values": RETRIEVAL_PRESETS,
        "channels": ["bm25", "vector", "graph"],
        "allowed": policy["allowed"],
        "limits": policy["limits"],
    }
    if include_ingestion_catalogs:
        result["parsers"] = _parser_catalog()
        result["chunking_strategies"] = _chunking_strategy_catalog()
    return result


async def create_task_settings_snapshot(task_id: str, user_id: int, resolved: ResolvedUserSettings) -> None:
    """Persist the complete resolved configuration before a task becomes runnable."""
    from raganything.services.vision_models import require_available

    pool = get_pg_pool()
    payload = resolved.snapshot()
    from raganything.embedding.identity import text_embedding_identity_from_environment

    # The text embedding provider is not part of user-editable model settings,
    # but it must be frozen at the same enqueue boundary as every other
    # processing dependency.  The identity contains no credential or full URL.
    payload["text_embedding_identity"] = text_embedding_identity_from_environment()
    llm_entry = require_available(resolved.models.llm_profile_id, "llm")
    vlm_entry = require_available(resolved.models.vlm_profile_id, "vlm")
    profile_ids = {
        "llm": {"id": resolved.models.llm_profile_id, "fingerprint": llm_entry.fingerprint},
        "vlm": {"id": resolved.models.vlm_profile_id, "fingerprint": vlm_entry.fingerprint},
    }
    payload["profile_fingerprints"] = {
        "llm": llm_entry.fingerprint,
        "vlm": vlm_entry.fingerprint,
    }
    async with pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO task_settings_snapshots(task_id,user_id,revision,fingerprint,profile_ids,settings) "
            "VALUES($1,$2,$3,$4,$5::jsonb,$6::jsonb) "
            "ON CONFLICT(task_id) DO NOTHING",
            task_id, user_id, resolved.revision, resolved.fingerprint,
            json.dumps(profile_ids), json.dumps(payload),
        )


async def delete_task_settings_snapshot(task_id: str) -> None:
    """Remove an unqueued snapshot after a later enqueue prerequisite fails."""
    pool = get_pg_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            "DELETE FROM task_settings_snapshots WHERE task_id=$1", task_id
        )


async def get_task_settings_snapshot(task_id: str) -> dict[str, Any]:
    pool = get_pg_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT user_id,revision,fingerprint,profile_ids,settings FROM task_settings_snapshots WHERE task_id=$1", task_id
        )
    if row is None:
        raise RuntimeError("settings_snapshot_missing")
    settings = _json_object(row["settings"])
    return {
        "user_id": int(row["user_id"]),
        "revision": int(row["revision"]),
        "fingerprint": row["fingerprint"],
        "profile_ids": _json_object(row["profile_ids"]),
        "settings": settings,
    }


def load_task_text_embedding_identity(snapshot: dict[str, Any]) -> dict[str, Any]:
    """Return the strict text identity from a durable task snapshot."""
    if not isinstance(snapshot, dict):
        raise RuntimeError("settings_snapshot_invalid")
    from raganything.embedding.identity import load_text_embedding_identity

    return load_text_embedding_identity(
        (snapshot.get("settings") or {}).get("text_embedding_identity")
        if isinstance(snapshot.get("settings"), dict)
        else None
    )


async def acquire_quota_lease(
    user_id: int,
    task_id: str,
    owner: str,
    limit: int,
    ttl_seconds: int = 30,
    *,
    outer_limit: int | None = None,
) -> str | None:
    """Acquire a durable personal lease subject to the shared worker/provider cap.

    PostgreSQL advisory locks serialize the count-and-insert operation even
    when a scope has no active rows yet.  Row locks alone cannot protect that
    empty-set case, which would otherwise allow two workers to exceed a cap.
    ``outer_limit`` is the effective global capacity (the lower of the
    provider and worker caps); it is intentionally checked separately from
    the user's saved personal limit.
    """
    if limit <= 0:
        return None
    if outer_limit is not None and outer_limit <= 0:
        return None
    lease_id = str(uuid.uuid4())
    pool = get_pg_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            # Lock in a stable order: all acquisitions take the global lock
            # before their user-specific lock, avoiding empty-set races and
            # lock-order deadlocks between concurrent workers.
            await conn.execute("SELECT pg_advisory_xact_lock(hashtext($1))", "quota:global")
            await conn.execute("SELECT pg_advisory_xact_lock(hashtext($1))", f"quota:user:{user_id}")
            await conn.execute("DELETE FROM user_quota_leases WHERE expires_at <= NOW()")
            active = await conn.fetch("SELECT id FROM user_quota_leases WHERE user_id=$1 AND expires_at > NOW() FOR UPDATE", user_id)
            if len(active) >= limit:
                return None
            if outer_limit is not None:
                active_global = await conn.fetch(
                    "SELECT id FROM user_quota_leases WHERE expires_at > NOW() FOR UPDATE"
                )
                if len(active_global) >= outer_limit:
                    return None
            await conn.execute(
                "INSERT INTO user_quota_leases(id,user_id,task_id,lease_owner,expires_at) "
                "VALUES($1::uuid,$2,$3,$4,NOW()+$5 * INTERVAL '1 second')",
                lease_id, user_id, task_id, owner, ttl_seconds,
            )
    return lease_id


async def heartbeat_quota_lease(lease_id: str, owner: str, ttl_seconds: int = 30) -> bool:
    pool = get_pg_pool()
    async with pool.acquire() as conn:
        result = await conn.execute(
            "UPDATE user_quota_leases SET heartbeat_at=NOW(),expires_at=NOW()+$3 * INTERVAL '1 second' "
            # Acquisition deletes expired rows before creating a replacement.
            # Therefore an owner may renew a briefly expired lease only while no
            # replacement has claimed it; the immutable ID and owner still fence
            # a worker that has actually lost its slot.
            "WHERE id=$1::uuid AND lease_owner=$2",
            lease_id, owner, ttl_seconds,
        )
    return result == "UPDATE 1"


async def release_quota_lease(lease_id: str, owner: str) -> None:
    pool = get_pg_pool()
    async with pool.acquire() as conn:
        await conn.execute("DELETE FROM user_quota_leases WHERE id=$1::uuid AND lease_owner=$2", lease_id, owner)


async def run_ingestion_with_quota(
    task_id: str,
    operation: Callable[[], Awaitable[_Result]],
) -> _Result:
    """Run snapshot-bound ingestion under durable personal and outer limits."""
    snapshot = await get_task_settings_snapshot(task_id)
    runtime = (snapshot.get("settings") or {}).get("runtime") or {}
    personal_limit = int(runtime.get("personal_concurrency") or 1)
    try:
        platform = await get_platform_settings()
    except RuntimeError:
        if os.getenv("RAGANYTHING_ENV", "development").strip().lower() == "production":
            raise
        # Local compatibility mode can still execute the already-snapshotted
        # task, but production never silently bypasses durable quotas.
        return await operation()
    limits = ((platform.get("settings") or {}).get("limits") or {})
    outer_caps = [
        int(limits[name])
        for name in ("provider_concurrency", "worker_concurrency")
        if isinstance(limits.get(name), (int, float)) and limits[name] > 0
    ]
    outer_limit = min(outer_caps) if outer_caps else None
    owner = f"ingestion:{os.getpid()}:{uuid.uuid4()}"
    lease_id = None
    while lease_id is None:
        lease_id = await acquire_quota_lease(
            int(snapshot["user_id"]),
            task_id,
            owner,
            personal_limit,
            outer_limit=outer_limit,
        )
        if lease_id is None:
            await asyncio.sleep(1)

    operation_task = asyncio.create_task(operation(), name=f"ingestion-operation-{task_id}")
    lease_lost = asyncio.Event()

    async def heartbeat() -> None:
        try:
            while True:
                await asyncio.sleep(15)
                if not await heartbeat_quota_lease(lease_id, owner):
                    lease_lost.set()
                    operation_task.cancel()
                    return
        except asyncio.CancelledError:
            raise
        except Exception:
            lease_lost.set()
            operation_task.cancel()
            logger.warning("Ingestion quota heartbeat failed for task=%s", task_id, exc_info=True)

    heartbeat_task = asyncio.create_task(heartbeat(), name=f"ingestion-quota-{task_id}")
    try:
        try:
            return await operation_task
        except asyncio.CancelledError as exc:
            if lease_lost.is_set():
                raise RuntimeError("quota_lease_lost") from exc
            raise
    finally:
        heartbeat_task.cancel()
        await asyncio.gather(heartbeat_task, return_exceptions=True)
        try:
            await release_quota_lease(lease_id, owner)
        except Exception:
            logger.warning("Ingestion quota release failed for task=%s", task_id, exc_info=True)
