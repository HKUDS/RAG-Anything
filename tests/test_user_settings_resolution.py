import asyncio
import json
from dataclasses import replace
from types import SimpleNamespace

import pytest

from raganything.services import vision_models
from raganything.services.user_settings import (
    _json_object,
    get_task_settings_snapshot,
    resolve_settings,
    settings_options,
    validate_platform_policy,
    with_task_ingestion_overrides,
)
from raganything.services import user_settings


class _SnapshotConnection:
    async def fetchrow(self, _sql, _task_id):
        return {
            "user_id": 9,
            "revision": 4,
            "fingerprint": "snapshot-fingerprint",
            "profile_ids": '{"llm":"llm-a","vlm":"vlm-a"}',
            "settings": '{"ingestion":{"chunking_strategy":"sentence"}}',
        }


class _SnapshotAcquire:
    async def __aenter__(self):
        return _SnapshotConnection()

    async def __aexit__(self, *_args):
        return None


class _SnapshotPool:
    def acquire(self):
        return _SnapshotAcquire()


def test_postgres_jsonb_text_is_normalized_before_settings_resolution():
    assert _json_object('{"runtime": {"personal_concurrency": 7}}') == {
        "runtime": {"personal_concurrency": 7},
    }
    assert _json_object('not-json') == {}


@pytest.mark.asyncio
async def test_task_snapshot_decodes_asyncpg_jsonb_text(monkeypatch):
    monkeypatch.setattr(
        "raganything.services.user_settings.get_pg_pool",
        lambda: _SnapshotPool(),
    )

    snapshot = await get_task_settings_snapshot("task-a")

    assert snapshot["profile_ids"] == {"llm": "llm-a", "vlm": "vlm-a"}
    assert snapshot["settings"] == {
        "ingestion": {"chunking_strategy": "sentence"},
    }


def test_user_override_is_constrained_without_losing_stored_value():
    resolved, sources, constraints = resolve_settings(
        stored={"runtime": {"personal_concurrency": 20}},
        platform={"limits": {"personal_concurrency": 4}},
        revision=7,
    )

    assert resolved.runtime.personal_concurrency == 4
    assert sources["runtime"]["personal_concurrency"] == "platform_limit"
    assert constraints["runtime"]["personal_concurrency"] == {"requested": 20, "maximum": 4}
    assert resolved.revision == 7
    assert resolved.fingerprint


def test_provider_and_worker_caps_constrain_personal_concurrency():
    resolved, sources, constraints = resolve_settings(
        stored={"runtime": {"personal_concurrency": 12}},
        platform={"limits": {"provider_concurrency": 8, "worker_concurrency": 3}},
        revision=1,
    )

    assert resolved.runtime.personal_concurrency == 3
    assert sources["runtime"]["personal_concurrency"] == "platform_limit"
    assert constraints["runtime"]["personal_concurrency"] == {
        "requested": 12, "maximum": 3,
    }


def test_named_retrieval_preset_resolves_to_its_executable_fields():
    resolved, sources, _ = resolve_settings(
        stored={"retrieval": {"preset": "precise"}},
        platform=None,
        revision=1,
    )

    assert resolved.retrieval.preset == "precise"
    assert resolved.retrieval.vector_top_k == 60
    assert resolved.retrieval.channels == ("bm25", "vector")
    assert sources["retrieval"]["vector_top_k"] == "user_setting"


def test_full_precedence_applies_request_then_index_and_hard_limits(monkeypatch):
    monkeypatch.setenv("MAX_ASYNC", "9")
    resolved, sources, constraints = resolve_settings(
        stored={
            "runtime": {"personal_concurrency": 6},
            "retrieval": {"bm25_tokenizer": "stored"},
        },
        platform={
            "defaults": {"runtime": {"personal_concurrency": 8}},
            "limits": {"personal_concurrency": 4},
        },
        resource_settings={
            "runtime": {"personal_concurrency": 7},
            "retrieval": {"bm25_tokenizer": "resource"},
        },
        request_overrides={
            "runtime": {"personal_concurrency": 5},
            "retrieval": {"bm25_tokenizer": "request"},
        },
        index_constraints={"retrieval": {"bm25_tokenizer": "index-compatible"}},
        revision=2,
    )

    assert resolved.runtime.personal_concurrency == 4
    assert sources["runtime"]["personal_concurrency"] == "platform_limit"
    assert constraints["runtime"]["personal_concurrency"] == {
        "requested": 5,
        "maximum": 4,
    }
    assert resolved.retrieval.bm25_tokenizer == "index-compatible"
    assert sources["retrieval"]["bm25_tokenizer"] == "index_compatibility"
    assert constraints["retrieval"]["bm25_tokenizer"] == {
        "requested": "request",
        "required": "index-compatible",
    }


def test_retrieval_presets_expand_per_layer_before_explicit_fields_and_limits():
    resolved, sources, constraints = resolve_settings(
        stored={"retrieval": {"preset": "precise", "vector_top_k": 71}},
        platform={
            "defaults": {"retrieval": {"preset": "balanced", "graph_depth": 3}},
            "limits": {"bm25_top_k": 15, "vector_top_k": 20},
        },
        resource_settings={"retrieval": {"preset": "broad", "bm25_top_k": 77}},
        request_overrides={"retrieval": {"preset": "balanced", "bm25_top_k": 88}},
        revision=3,
    )

    assert resolved.retrieval.preset == "balanced"
    assert resolved.retrieval.channels == ("bm25", "vector", "graph")
    assert resolved.retrieval.graph_depth == 2
    assert resolved.retrieval.bm25_top_k == 15
    assert resolved.retrieval.vector_top_k == 20
    assert sources["retrieval"]["channels"] == "request_selection"
    assert sources["retrieval"]["bm25_top_k"] == "platform_limit"
    assert constraints["retrieval"]["bm25_top_k"] == {"requested": 88, "maximum": 15}
    assert constraints["retrieval"]["vector_top_k"] == {"requested": 100, "maximum": 20}


def test_legacy_environment_is_the_lowest_precedence_layer(monkeypatch):
    monkeypatch.setenv("MAX_ASYNC", "9")

    legacy, legacy_sources, _ = resolve_settings(
        stored=None,
        platform=None,
        revision=0,
    )
    platform, platform_sources, _ = resolve_settings(
        stored=None,
        platform={"defaults": {"runtime": {"personal_concurrency": 8}}},
        revision=0,
    )

    assert legacy.runtime.personal_concurrency == 9
    assert legacy_sources["runtime"]["personal_concurrency"] == "legacy_environment"
    assert platform.runtime.personal_concurrency == 8
    assert platform_sources["runtime"]["personal_concurrency"] == "platform_default"


def test_options_expose_fields_but_no_deployment_secrets():
    options = settings_options()

    assert set(options["sections"]) == {"models", "ingestion", "retrieval", "runtime"}
    assert options["preset_values"]["precise"]["vector_top_k"] == 60
    rendered = str(options)
    assert "api_key" not in rendered
    assert "base_url" not in rendered


def test_upload_overrides_are_captured_in_an_immutable_task_snapshot():
    resolved, _, _ = resolve_settings(stored=None, platform=None, revision=3)

    task_settings = with_task_ingestion_overrides(
        resolved,
        chunking_strategy="sentence",
        enable_image=False,
        enable_video=True,
    )

    assert resolved.ingestion.chunking_strategy == "recursive"
    assert resolved.ingestion.enable_image is True
    assert task_settings.ingestion.chunking_strategy == "sentence"
    assert task_settings.ingestion.enable_image is False
    assert task_settings.ingestion.enable_video is True
    assert task_settings.revision == 3
    assert task_settings.fingerprint != resolved.fingerprint
    assert with_task_ingestion_overrides(
        task_settings,
        chunking_strategy="sentence",
        enable_image=False,
        enable_video=True,
    ).fingerprint == task_settings.fingerprint


def test_resolved_task_snapshot_includes_public_model_fingerprints():
    resolved, _, _ = resolve_settings(stored=None, platform=None, revision=3)
    resolved = replace(
        resolved,
        profile_fingerprints=user_settings.ModelProfileFingerprints(
            llm="llm-public-fingerprint",
            vlm="vlm-public-fingerprint",
        ),
    )

    snapshot = resolved.snapshot()

    assert snapshot["profile_fingerprints"] == {
        "llm": "llm-public-fingerprint",
        "vlm": "vlm-public-fingerprint",
    }


def test_regular_settings_snapshot_omits_unresolved_profile_fingerprints():
    resolved, _, _ = resolve_settings(stored=None, platform=None, revision=3)

    assert "profile_fingerprints" not in resolved.snapshot()


def test_platform_policy_rejects_secret_shaped_and_unknown_fields():
    with pytest.raises(ValueError, match="credentials or endpoints"):
        validate_platform_policy({"defaults": {}, "base_url": "https://provider.invalid"})

    with pytest.raises(ValueError, match="invalid platform policy fields"):
        validate_platform_policy({"unexpected": {}})


def test_platform_policy_validates_allowed_model_ids(monkeypatch):
    monkeypatch.setattr(
        vision_models,
        "list_model_profiles",
        lambda: [SimpleNamespace(id="configured-llm", kind="llm")],
    )
    validate_platform_policy({"allowed": {"llm_profile_ids": ["configured-llm"]}})

    with pytest.raises(ValueError, match="unknown llm profile"):
        validate_platform_policy({"allowed": {"llm_profile_ids": ["not-configured"]}})


def test_platform_options_drop_legacy_secret_fields():
    options = settings_options({
        "defaults": {"runtime": {"personal_concurrency": 7, "base_url": "https://provider.invalid"}},
        "limits": {"personal_concurrency": 7},
        "api_key_env": "SHOULD_NOT_LEAK",
    })

    assert options["limits"] == {"personal_concurrency": 7}
    assert "provider.invalid" not in str(options)
    assert "SHOULD_NOT_LEAK" not in str(options)


@pytest.mark.asyncio
async def test_first_user_settings_writes_are_serialized_by_user(monkeypatch):
    state = {"settings": None, "revision": 0}
    advisory_lock = asyncio.Lock()

    class Transaction:
        def __init__(self, conn):
            self.conn = conn

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            if self.conn.holds_advisory_lock:
                self.conn.holds_advisory_lock = False
                advisory_lock.release()

    class Connection:
        def __init__(self):
            self.holds_advisory_lock = False

        def transaction(self):
            return Transaction(self)

        async def execute(self, sql, *args):
            if "pg_advisory_xact_lock" in sql:
                await advisory_lock.acquire()
                self.holds_advisory_lock = True
                return "SELECT 1"
            if sql.startswith("INSERT INTO user_settings"):
                state["settings"] = json.loads(args[1])
                state["revision"] = args[2]
                return "INSERT 0 1"
            raise AssertionError(sql)

        async def fetchrow(self, sql, *_args):
            if sql.startswith("SELECT settings, revision FROM user_settings"):
                if state["settings"] is None:
                    return None
                return {
                    "settings": json.dumps(state["settings"]),
                    "revision": state["revision"],
                }
            raise AssertionError(sql)

    class Acquire:
        async def __aenter__(self):
            return Connection()

        async def __aexit__(self, *_args):
            return None

    class Pool:
        def acquire(self):
            return Acquire()

    async def current_settings(_user_id):
        return {"revision": state["revision"], "stored": state["settings"]}

    monkeypatch.setattr(user_settings, "get_pg_pool", lambda: Pool())
    monkeypatch.setattr(user_settings, "_platform_row", lambda: _resolved(({}, 0)))
    monkeypatch.setattr(user_settings, "get_user_settings", current_settings)

    first, second = await asyncio.gather(
        user_settings.patch_user_settings(7, "runtime", {"llm_timeout": 30}, 0),
        user_settings.patch_user_settings(7, "retrieval", {"rrf_k": 20}, 0),
    )

    assert sum(result is not None for result in (first, second)) == 1
    assert state["revision"] == 1
    assert len(state["settings"]) == 1


async def _resolved(value):
    return value
