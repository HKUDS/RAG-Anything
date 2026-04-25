from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path
from threading import RLock
from typing import Any

from fastapi import status

from raganything_studio.backend.config import StudioSettings
from raganything_studio.backend.config import ModelChannelConfig, ModelProviderProfile
from raganything_studio.backend.core.errors import api_error
from raganything_studio.backend.schemas.settings import StudioSettingsUpdate


PATH_FIELDS = {
    "data_dir",
    "upload_dir",
    "output_dir",
    "working_dir",
    "static_dir",
    "settings_file",
}

SECRET_FIELDS = {"llm_api_key", "embedding_api_key", "vision_api_key"}
PROFILE_CHANNELS = ("llm", "embedding", "vision")


class SettingsStore:
    """Local JSON-backed settings store for Studio runtime configuration."""

    def __init__(self, settings: StudioSettings):
        self._settings = settings
        self._lock = RLock()
        self._load_from_disk()

    def get(self) -> StudioSettings:
        with self._lock:
            return self._settings

    def update(self, payload: StudioSettingsUpdate) -> StudioSettings:
        with self._lock:
            updates = payload.model_dump(exclude_unset=True)

            for key, value in updates.items():
                if key == "profiles":
                    self._settings.profiles = _merge_profiles(
                        self._settings.profiles, value
                    )
                    _sync_legacy_model_fields(self._settings)
                    continue
                if key.endswith("_api_key") and value == "":
                    continue
                if value is None and key in SECRET_FIELDS:
                    continue
                if value is None:
                    setattr(self._settings, key, None)
                    continue
                setattr(self._settings, key, _coerce_value(key, value))

            if not self._settings.profiles:
                self._settings.profiles = [_profile_from_legacy(self._settings)]
            if not _profile_by_id(self._settings.profiles, self._settings.active_profile_id):
                self._settings.active_profile_id = self._settings.profiles[0].id
            _sync_legacy_model_fields(self._settings)
            self._ensure_directories()
            self._write_to_disk()
            return self._settings

    def _load_from_disk(self) -> None:
        path = self._settings.settings_file
        if not path.exists():
            self._ensure_directories()
            return

        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:
            raise api_error(
                "SETTINGS_INVALID",
                f"Failed to read Studio settings: {exc}",
                status.HTTP_500_INTERNAL_SERVER_ERROR,
            ) from exc

        if not isinstance(payload, dict):
            raise api_error(
                "SETTINGS_INVALID",
                "Studio settings file must contain a JSON object",
                status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

        has_profiles = "profiles" in payload
        for key, value in payload.items():
            if hasattr(self._settings, key):
                setattr(self._settings, key, _coerce_value(key, value))
        if not has_profiles or not self._settings.profiles:
            self._settings.profiles = [_profile_from_legacy(self._settings)]
        if not _profile_by_id(self._settings.profiles, self._settings.active_profile_id):
            self._settings.active_profile_id = self._settings.profiles[0].id
        _sync_legacy_model_fields(self._settings)
        self._ensure_directories()

    def _write_to_disk(self) -> None:
        path = self._settings.settings_file
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(_serialize_settings(self._settings), indent=2, sort_keys=True),
            encoding="utf-8",
        )

    def _ensure_directories(self) -> None:
        for directory in (
            self._settings.data_dir,
            self._settings.upload_dir,
            self._settings.output_dir,
            self._settings.working_dir,
            self._settings.static_dir,
            self._settings.settings_file.parent,
        ):
            directory.mkdir(parents=True, exist_ok=True)


def _coerce_value(key: str, value: Any) -> Any:
    if key in PATH_FIELDS:
        return Path(str(value)).expanduser().resolve()
    if key in {"embedding_dim", "embedding_max_token_size", "max_concurrent_files"}:
        return max(1, int(value))
    if key == "default_enable_vlm_enhancement":
        if isinstance(value, str):
            return value.strip().lower() in {"1", "true", "yes", "on"}
        return bool(value)
    if key == "profiles":
        return _coerce_profiles(value)
    return value


def _serialize_settings(settings: StudioSettings) -> dict[str, Any]:
    payload = asdict(settings)
    for key in PATH_FIELDS:
        payload[key] = str(payload[key])
    return payload


def _coerce_profiles(value: Any) -> list[ModelProviderProfile]:
    if not isinstance(value, list):
        return []
    profiles: list[ModelProviderProfile] = []
    for raw_profile in value:
        if not isinstance(raw_profile, dict):
            continue
        profile_id = str(raw_profile.get("id") or "").strip()
        if not profile_id:
            continue
        profiles.append(
            ModelProviderProfile(
                id=profile_id,
                name=str(raw_profile.get("name") or profile_id),
                llm=_coerce_channel(raw_profile.get("llm"), embedding=False),
                embedding=_coerce_channel(raw_profile.get("embedding"), embedding=True),
                vision=_coerce_channel(raw_profile.get("vision"), embedding=False),
            )
        )
    return profiles


def _coerce_channel(value: Any, *, embedding: bool) -> ModelChannelConfig:
    raw = value if isinstance(value, dict) else {}
    return ModelChannelConfig(
        provider=str(raw.get("provider") or "openai-compatible"),
        model=str(
            raw.get("model")
            or ("text-embedding-3-large" if embedding else "gpt-4o-mini")
        ),
        base_url=raw.get("base_url") or None,
        api_key=raw.get("api_key") or None,
        embedding_dim=int(raw.get("embedding_dim") or 3072) if embedding else None,
        embedding_max_token_size=int(raw.get("embedding_max_token_size") or 8192)
        if embedding
        else None,
    )


def _merge_profiles(
    existing: list[ModelProviderProfile], incoming: Any
) -> list[ModelProviderProfile]:
    existing_by_id = {profile.id: profile for profile in existing}
    merged: list[ModelProviderProfile] = []
    for profile in _coerce_profiles(incoming):
        saved = existing_by_id.get(profile.id)
        if saved is not None:
            for channel_name in PROFILE_CHANNELS:
                incoming_channel = getattr(profile, channel_name)
                saved_channel = getattr(saved, channel_name)
                if not incoming_channel.api_key:
                    incoming_channel.api_key = saved_channel.api_key
        merged.append(profile)
    return merged


def _profile_by_id(
    profiles: list[ModelProviderProfile], profile_id: str | None
) -> ModelProviderProfile | None:
    return next((profile for profile in profiles if profile.id == profile_id), None)


def _profile_from_legacy(settings: StudioSettings) -> ModelProviderProfile:
    return ModelProviderProfile(
        id=settings.active_profile_id or "default",
        name="Default RAG Profile",
        llm=ModelChannelConfig(
            provider=settings.llm_provider,
            model=settings.llm_model,
            base_url=settings.llm_base_url,
            api_key=settings.llm_api_key,
        ),
        embedding=ModelChannelConfig(
            provider=settings.embedding_provider,
            model=settings.embedding_model,
            base_url=settings.embedding_base_url,
            api_key=settings.embedding_api_key,
            embedding_dim=settings.embedding_dim,
            embedding_max_token_size=settings.embedding_max_token_size,
        ),
        vision=ModelChannelConfig(
            provider=settings.vision_provider,
            model=settings.vision_model,
            base_url=settings.vision_base_url,
            api_key=settings.vision_api_key,
        ),
    )


def _sync_legacy_model_fields(settings: StudioSettings) -> None:
    profile = _profile_by_id(settings.profiles, settings.active_profile_id)
    if profile is None and settings.profiles:
        profile = settings.profiles[0]
        settings.active_profile_id = profile.id
    if profile is None:
        return

    settings.llm_provider = profile.llm.provider
    settings.llm_model = profile.llm.model
    settings.llm_base_url = profile.llm.base_url
    settings.llm_api_key = profile.llm.api_key
    settings.embedding_provider = profile.embedding.provider
    settings.embedding_model = profile.embedding.model
    settings.embedding_base_url = profile.embedding.base_url
    settings.embedding_api_key = profile.embedding.api_key
    settings.embedding_dim = profile.embedding.embedding_dim or settings.embedding_dim
    settings.embedding_max_token_size = (
        profile.embedding.embedding_max_token_size
        or settings.embedding_max_token_size
    )
    settings.vision_provider = profile.vision.provider
    settings.vision_model = profile.vision.model
    settings.vision_base_url = profile.vision.base_url
    settings.vision_api_key = profile.vision.api_key
