from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from raganything.permissions import DEFAULT_ROLES
from raganything.routers import user_settings as settings_router
from raganything.services import user_settings


def _user(*permissions):
    return {"id": 7, "role": {"name": "custom", "permissions": list(permissions)}}


def test_section_policy_matches_builtin_and_custom_capabilities():
    expected_builtin_sections = {
        "student": (),
        "assistant": ("ingestion", "retrieval", "runtime"),
        "teacher": user_settings.SECTIONS,
        "dept_admin": user_settings.SECTIONS,
        "super_admin": user_settings.SECTIONS,
    }
    for role, expected in expected_builtin_sections.items():
        assert user_settings.available_sections(DEFAULT_ROLES[role]["permissions"]) == expected

    assert user_settings.available_sections(["kb:write"]) == (
        "ingestion", "retrieval", "runtime",
    )
    assert user_settings.available_sections(["agent:write"]) == ("models",)
    assert user_settings.available_sections(["agent:write", "kb:write"]) == user_settings.SECTIONS



def _fake_parser_catalog():
    return [
        {"id": "mineru", "name": "mineru", "available": True, "supported_types": ["pdf", "office", "image"]},
        {"id": "docling", "name": "docling", "available": True, "supported_types": ["pdf", "office"]},
        {"id": "paddleocr", "name": "paddleocr", "available": False, "supported_types": ["pdf", "office", "image"]},
        {"id": "marker", "name": "marker", "available": False, "supported_types": ["pdf", "office", "image"]},
        {"id": "opendataloader", "name": "opendataloader", "available": False, "supported_types": ["pdf"]},
    ]


def _fake_strategy_catalog():
    return [
        {"id": "fixed_size", "name": "fixed_size", "description": "", "cost": "", "cost_level": "free"},
        {"id": "recursive", "name": "recursive", "description": "", "cost": "", "cost_level": "free"},
        {"id": "sentence", "name": "sentence", "description": "", "cost": "", "cost_level": "free"},
        {"id": "structure", "name": "structure", "description": "", "cost": "", "cost_level": "free"},
        {"id": "semantic", "name": "semantic", "description": "", "cost": "", "cost_level": "medium"},
        {"id": "agentic", "name": "agentic", "description": "", "cost": "", "cost_level": "high"},
    ]


def test_options_parsers_carry_supported_types(monkeypatch):
    monkeypatch.setattr(user_settings, "_parser_catalog", _fake_parser_catalog)
    monkeypatch.setattr(user_settings, "_chunking_strategy_catalog", _fake_strategy_catalog)
    options = user_settings.settings_options({})

    by_id = {item["id"]: item for item in options["parsers"]}
    assert by_id["docling"]["supported_types"] == ["pdf", "office"]
    assert by_id["mineru"]["supported_types"] == ["pdf", "office", "image"]
    assert by_id["marker"]["supported_types"] == ["pdf", "office", "image"]
    assert by_id["paddleocr"]["supported_types"] == ["pdf", "office", "image"]
    assert by_id["opendataloader"]["supported_types"] == ["pdf"]
    assert all(isinstance(item["supported_types"], list) for item in options["parsers"])


def test_options_projection_does_not_leak_denied_section_data(monkeypatch):
    monkeypatch.setattr(user_settings, "_parser_catalog", _fake_parser_catalog)
    monkeypatch.setattr(user_settings, "_chunking_strategy_catalog", _fake_strategy_catalog)
    projected = user_settings.project_settings_options(
        user_settings.settings_options({
            "allowed": {
                "llm_profile_ids": ["llm-a"],
                "vlm_profile_ids": ["vlm-a"],
                "parsers": ["docling"],
                "bm25_tokenizers": ["jieba"],
            },
            "limits": {"llm_timeout": 60, "vector_top_k": 20},
        }),
        (),
    )
    assert projected["sections"] == {}
    assert projected["allowed"] == {}
    assert projected["limits"] == {}
    assert "preset_values" not in projected
    assert "parsers" not in projected
    assert "chunking_strategies" not in projected


def test_downgraded_stored_sections_inherit_platform_values_for_new_resolution():
    stored = {
        "models": {"llm_profile_id": "stored-llm", "vlm_profile_id": "stored-vlm"},
        "runtime": {"llm_timeout": 9},
    }
    before_downgrade, _, _ = user_settings.resolve_settings(
        stored=stored,
        platform={"defaults": {"models": {"llm_profile_id": "platform-llm", "vlm_profile_id": "platform-vlm"}}},
        revision=1,
    )
    queued_snapshot = before_downgrade.snapshot()
    filtered = user_settings._project_sections(stored, user_settings.available_sections(["kb:write"]))
    resolved, _, _ = user_settings.resolve_settings(
        stored=filtered,
        platform={"defaults": {"models": {"llm_profile_id": "platform-llm", "vlm_profile_id": "platform-vlm"}}},
        revision=2,
    )
    assert stored["models"]["llm_profile_id"] == "stored-llm"
    assert resolved.models.llm_profile_id == "platform-llm"
    assert resolved.runtime.llm_timeout == 9
    assert queued_snapshot["models"]["llm_profile_id"] == "stored-llm"


@pytest.mark.asyncio
async def test_settings_read_projects_only_authorized_sections(monkeypatch):
    captured = {}

    async def get_settings(_user_id, *, permitted_sections):
        captured["sections"] = permitted_sections
        return {"available_sections": list(permitted_sections)}

    monkeypatch.setattr(settings_router.user_settings, "get_user_settings", get_settings)
    result = await settings_router.get_my_settings(_user("kb:write"))
    assert result == {"available_sections": ["ingestion", "retrieval", "runtime"]}
    assert captured["sections"] == ("ingestion", "retrieval", "runtime")


@pytest.mark.asyncio
async def test_denied_patch_never_calls_persistence_or_records_profile_ids(monkeypatch):
    calls = []

    async def audit(*args, **kwargs):
        calls.append((args, kwargs))

    async def fail_patch(*_args, **_kwargs):
        raise AssertionError("persistence must not be called")

    monkeypatch.setattr(settings_router, "_audit_personal_settings", audit)
    monkeypatch.setattr(settings_router.user_settings, "patch_user_settings", fail_patch)
    with pytest.raises(HTTPException) as exc:
        await settings_router.patch_my_settings(
            "models", settings_router.SectionPatch(expected_revision=3, values={"llm_profile_id": "secret-profile"}), _user("kb:write"),
        )
    assert exc.value.status_code == 403
    assert calls[0][0][-1] is None


def test_legacy_model_preference_routes_require_agent_write():
    def dependency_names(path, method):
        from raganything.routers import vision
        for route in vision.router.routes:
            if route.path == path and method in route.methods:
                return [getattr(dep.call, "__name__", "") for dep in route.dependant.dependencies]
        raise AssertionError(path)

    assert "require_agent_write" in dependency_names("/users/me/model-preferences", "GET")
    assert "require_agent_write" in dependency_names("/users/me/model-preferences", "PUT")


def test_resolved_sections_accepts_section_names_not_permissions():
    assert user_settings.resolved_sections(None) == user_settings.SECTIONS
    assert user_settings.resolved_sections(()) == ()
    assert user_settings.resolved_sections(("ingestion", "retrieval", "runtime")) == (
        "ingestion", "retrieval", "runtime",
    )
    assert user_settings.resolved_sections(("models", "ingestion")) == ("models", "ingestion")
    assert user_settings.resolved_sections(("models", "unknown")) == ("models",)


@pytest.mark.asyncio
async def test_settings_read_uses_permitted_sections_directly(monkeypatch):
    from contextlib import asynccontextmanager

    class FakeConn:
        async def fetchrow(self, *args, **kwargs):
            return None

    class FakePool:
        @asynccontextmanager
        async def acquire(self):
            yield FakeConn()

    monkeypatch.setattr(user_settings, "get_pg_pool", lambda: FakePool())

    result = await user_settings.get_user_settings(
        7, permitted_sections=("ingestion", "retrieval", "runtime"),
    )
    assert result["available_sections"] == ["ingestion", "retrieval", "runtime"]
    for key in ("stored", "effective", "sources", "constraints"):
        assert set(result[key]).issubset({"ingestion", "retrieval", "runtime"})

    unrestricted = await user_settings.get_user_settings(7)
    assert unrestricted["available_sections"] == list(user_settings.SECTIONS)


def test_options_projection_keeps_catalogs_for_ingestion_users(monkeypatch):
    monkeypatch.setattr(user_settings, "_parser_catalog", _fake_parser_catalog)
    monkeypatch.setattr(user_settings, "_chunking_strategy_catalog", _fake_strategy_catalog)
    projected = user_settings.project_settings_options(
        user_settings.settings_options({}),
        ("ingestion",),
    )
    assert {item["id"] for item in projected["parsers"]} == {
        "mineru", "docling", "paddleocr", "marker", "opendataloader",
    }
    assert {item["id"] for item in projected["chunking_strategies"]} == {
        "fixed_size", "recursive", "sentence", "structure", "semantic", "agentic",
    }


@pytest.mark.asyncio
async def test_options_catalogs_are_filtered_by_platform_allow_list(monkeypatch):
    async def fake_get_platform_settings():
        return {"settings": {
            "defaults": {},
            "allowed": {
                "parsers": ["docling"],
                "chunking_strategies": ["recursive", "fixed_size"],
            },
            "limits": {},
            "state": {"read_only": False},
        }}

    monkeypatch.setattr(settings_router.user_settings, "get_platform_settings", fake_get_platform_settings)
    monkeypatch.setattr(settings_router, "list_model_profiles", lambda: [])
    monkeypatch.setattr(settings_router.user_settings, "_parser_catalog", _fake_parser_catalog)
    monkeypatch.setattr(settings_router.user_settings, "_chunking_strategy_catalog", _fake_strategy_catalog)

    result = await settings_router.get_my_settings_options(_user("kb:write"))

    assert [item["id"] for item in result["parsers"]] == ["docling"]
    assert {item["id"] for item in result["chunking_strategies"]} == {"recursive", "fixed_size"}


@pytest.mark.asyncio
async def test_options_omit_catalogs_for_non_ingestion_users(monkeypatch):
    async def fake_get_platform_settings():
        return {"settings": {
            "defaults": {},
            "allowed": {"parsers": ["docling"], "chunking_strategies": ["recursive"]},
            "limits": {},
            "state": {"read_only": False},
        }}

    monkeypatch.setattr(settings_router.user_settings, "get_platform_settings", fake_get_platform_settings)
    monkeypatch.setattr(settings_router, "list_model_profiles", lambda: [])
    monkeypatch.setattr(settings_router.user_settings, "_parser_catalog", _fake_parser_catalog)
    monkeypatch.setattr(settings_router.user_settings, "_chunking_strategy_catalog", _fake_strategy_catalog)

    result = await settings_router.get_my_settings_options(_user())

    assert "parsers" not in result
    assert "chunking_strategies" not in result


@pytest.mark.asyncio
async def test_options_catalogs_are_not_filtered_when_allow_lists_are_empty(monkeypatch):
    async def fake_get_platform_settings():
        return {"settings": {
            "defaults": {},
            "allowed": {"parsers": [], "chunking_strategies": []},
            "limits": {},
            "state": {"read_only": False},
        }}

    monkeypatch.setattr(settings_router.user_settings, "get_platform_settings", fake_get_platform_settings)
    monkeypatch.setattr(settings_router, "list_model_profiles", lambda: [])
    monkeypatch.setattr(settings_router.user_settings, "_parser_catalog", _fake_parser_catalog)
    monkeypatch.setattr(settings_router.user_settings, "_chunking_strategy_catalog", _fake_strategy_catalog)

    result = await settings_router.get_my_settings_options(_user("kb:write"))

    assert {item["id"] for item in result["parsers"]} == {
        "mineru", "docling", "paddleocr", "marker", "opendataloader",
    }
    assert {item["id"] for item in result["chunking_strategies"]} == {
        "fixed_size", "recursive", "sentence", "structure", "semantic", "agentic",
    }
