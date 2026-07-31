"""Contracts for the sanitized unified model-profile catalog."""

import json

import pytest

from raganything.services import vision_models


def test_public_catalog_includes_llm_and_never_private_transport(monkeypatch):
    monkeypatch.setenv("LLM_BINDING_HOST", "https://provider.invalid/v1")
    monkeypatch.setenv("LLM_BINDING_API_KEY", "super-secret")
    monkeypatch.setenv("VISION_MODEL_CATALOG_FILE", "config/vision_models.json")
    vision_models.reset_catalog_cache()

    profiles = [profile.model_dump() for profile in vision_models.list_model_profiles()]

    assert {profile["kind"] for profile in profiles} == {"llm", "vlm", "embedding"}
    encoded = json.dumps(profiles)
    for private_value in ("base_url", "api_key_env", "timeout", "concurrency", "super-secret", "provider.invalid"):
        assert private_value not in encoded


def test_legacy_llm_uses_binding_model_when_llm_model_is_unset(monkeypatch):
    monkeypatch.delenv("LLM_MODEL", raising=False)
    monkeypatch.setenv("LLM_BINDING_MODEL", "qwen-plus")
    monkeypatch.setenv("LLM_BINDING_HOST", "https://provider.invalid/v1")
    monkeypatch.setenv("LLM_BINDING_API_KEY", "configured")
    vision_models.reset_catalog_cache()

    profile = next(
        profile for profile in vision_models.list_model_profiles("llm")
        if profile.id == "legacy-llm"
    )

    assert profile.model == "qwen-plus"
    assert profile.display_name == "默认文本模型 (qwen-plus)"
    vision_models.reset_catalog_cache()


def test_configured_vlm_profile_displays_its_actual_model(monkeypatch):
    monkeypatch.setenv("VISION_MODEL", "qwen-vl-plus")
    monkeypatch.setenv("VISION_MODEL_CATALOG_FILE", "config/vision_models.json")
    vision_models.reset_catalog_cache()

    profile = next(
        profile for profile in vision_models.list_model_profiles("vlm")
        if profile.id == "legacy-vlm"
    )

    assert profile.model == "qwen-vl-plus"
    assert profile.display_name == "默认图片理解模型 (qwen-vl-plus)"
    vision_models.reset_catalog_cache()


def test_vlm_display_name_uses_model_fallback_when_environment_is_unset(monkeypatch):
    monkeypatch.delenv("VISION_MODEL", raising=False)
    monkeypatch.setenv("VISION_MODEL_CATALOG_FILE", "config/vision_models.json")
    vision_models.reset_catalog_cache()

    profile = next(
        profile for profile in vision_models.list_model_profiles("vlm")
        if profile.id == "legacy-vlm"
    )

    assert profile.model == "qwen-vl-plus"
    assert profile.display_name == "默认图片理解模型 (qwen-vl-plus)"
    vision_models.reset_catalog_cache()


def test_unified_catalog_environment_takes_precedence(tmp_path, monkeypatch):
    catalog = tmp_path / "profiles.json"
    catalog.write_text(
        json.dumps({"profiles": [{
            "id": "custom-vlm", "kind": "vlm", "display_name": "Custom",
            "provider": "openai_compatible", "model": "custom-vl",
            "private": {"base_url": "https://example.invalid", "api_key_env": "CUSTOM_KEY"},
        }]}),
        encoding="utf-8",
    )
    monkeypatch.setenv("MODEL_PROFILE_CATALOG_FILE", str(catalog))
    monkeypatch.setenv("VISION_MODEL_CATALOG_FILE", "missing-legacy-catalog.json")
    monkeypatch.setenv("CUSTOM_KEY", "configured")
    vision_models.reset_catalog_cache()

    profiles = vision_models.list_model_profiles("vlm")

    assert profiles[0].id == "custom-vlm"
    assert "legacy-vlm" in {profile.id for profile in profiles}
    vision_models.reset_catalog_cache()


def test_unified_catalog_can_contain_llm_and_visual_profiles(tmp_path, monkeypatch):
    catalog = tmp_path / "profiles.json"
    catalog.write_text(
        json.dumps({"profiles": [
            {
                "id": "custom-llm", "kind": "llm", "display_name": "Text",
                "provider": "openai_compatible", "model": "text-model",
                "private": {"base_url": "https://example.invalid", "api_key_env": "TEXT_KEY"},
            },
            {
                "id": "custom-vlm", "kind": "vlm", "display_name": "Vision",
                "provider": "openai_compatible", "model": "vision-model",
                "private": {"base_url": "https://example.invalid", "api_key_env": "VISION_KEY"},
            },
        ]}),
        encoding="utf-8",
    )
    monkeypatch.setenv("MODEL_PROFILE_CATALOG_FILE", str(catalog))
    monkeypatch.setenv("TEXT_KEY", "configured")
    monkeypatch.setenv("VISION_KEY", "configured")
    vision_models.reset_catalog_cache()

    profiles = vision_models.list_model_profiles()

    identities = {(profile.id, profile.kind) for profile in profiles}
    assert {("custom-llm", "llm"), ("custom-vlm", "vlm")}.issubset(identities)
    assert ("legacy-doubao-embedding", "embedding") in identities
    vision_models.reset_catalog_cache()


def test_catalog_composes_unified_vision_and_legacy_sources(tmp_path, monkeypatch):
    unified = tmp_path / "unified.json"
    vision = tmp_path / "vision.json"
    unified.write_text(json.dumps({"profiles": [{
        "id": "custom-llm", "kind": "llm", "display_name": "Text",
        "provider": "openai_compatible", "model": "text-model",
        "private": {"base_url": "https://text.invalid", "api_key_env": "TEXT_KEY"},
    }]}), encoding="utf-8")
    vision.write_text(json.dumps({"profiles": [{
        "id": "custom-vlm", "kind": "vlm", "display_name": "Vision",
        "provider": "openai_compatible", "model": "vision-model",
        "private": {"base_url": "https://vision.invalid", "api_key_env": "VISION_KEY"},
    }]}), encoding="utf-8")
    monkeypatch.setenv("MODEL_PROFILE_CATALOG_FILE", str(unified))
    monkeypatch.setenv("VISION_MODEL_CATALOG_FILE", str(vision))
    monkeypatch.setenv("TEXT_KEY", "configured")
    monkeypatch.setenv("VISION_KEY", "configured")
    vision_models.reset_catalog_cache()

    identities = {
        (profile.id, profile.kind) for profile in vision_models.list_model_profiles()
    }

    assert ("custom-llm", "llm") in identities
    assert ("custom-vlm", "vlm") in identities
    assert ("legacy-doubao-embedding", "embedding") in identities
    vision_models.reset_catalog_cache()


@pytest.mark.asyncio
async def test_production_user_preference_has_no_process_local_fallback(monkeypatch):
    monkeypatch.setenv("RAGANYTHING_ENV", "production")
    monkeypatch.setattr(vision_models, "_pg_pool", lambda: _resolved(None))

    with pytest.raises(RuntimeError, match="PostgreSQL"):
        await vision_models.get_user_vlm_preference(7)


@pytest.mark.asyncio
async def test_legacy_vlm_preference_delegates_to_revisioned_user_settings(monkeypatch):
    from raganything.services import user_settings

    captured = {}

    async def current(_user_id):
        return {
            "revision": 4,
            "stored": {"models": {"llm_profile_id": "llm-a"}},
            "effective": {"models": {"vlm_profile_id": "vlm-old"}},
        }

    async def patch(user_id, section, values, expected_revision):
        captured.update(
            user_id=user_id,
            section=section,
            values=values,
            expected_revision=expected_revision,
        )
        return {"revision": 5}

    monkeypatch.setattr(vision_models, "_pg_pool", lambda: _resolved(object()))
    monkeypatch.setattr(vision_models, "require_available", lambda *_args: object())
    monkeypatch.setattr(user_settings, "get_user_settings", current)
    monkeypatch.setattr(user_settings, "patch_user_settings", patch)

    assert await vision_models.get_user_vlm_preference(7) == "vlm-old"
    assert await vision_models.set_user_vlm_preference(7, "vlm-new") == "vlm-new"
    assert captured == {
        "user_id": 7,
        "section": "models",
        "values": {"llm_profile_id": "llm-a", "vlm_profile_id": "vlm-new"},
        "expected_revision": 4,
    }


async def _resolved(value):
    return value


def test_unavailable_profile_remains_visible_but_cannot_be_selected(tmp_path, monkeypatch):
    catalog = tmp_path / "profiles.json"
    catalog.write_text(json.dumps({"profiles": [{
        "id": "offline-llm", "kind": "llm", "display_name": "Offline",
        "provider": "openai_compatible", "model": "offline",
        "private": {"base_url": "https://provider.invalid", "api_key_env": "MISSING_KEY"},
    }]}), encoding="utf-8")
    monkeypatch.setenv("MODEL_PROFILE_CATALOG_FILE", str(catalog))
    monkeypatch.delenv("MISSING_KEY", raising=False)
    vision_models.reset_catalog_cache()

    profile = vision_models.list_model_profiles("llm")[0]

    assert not profile.available
    assert profile.unavailable_reason
    with pytest.raises(RuntimeError):
        vision_models.require_available("offline-llm", "llm")
    vision_models.reset_catalog_cache()
