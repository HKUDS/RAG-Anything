from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path
from threading import RLock
from typing import Any

from fastapi import status

from raganything_studio.backend.config import StudioSettings
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
                if key.endswith("_api_key") and value == "":
                    continue
                if value is None and key in SECRET_FIELDS:
                    continue
                if value is None:
                    setattr(self._settings, key, None)
                    continue
                setattr(self._settings, key, _coerce_value(key, value))

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

        for key, value in payload.items():
            if hasattr(self._settings, key):
                setattr(self._settings, key, _coerce_value(key, value))
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
    if key in {"embedding_dim", "embedding_max_token_size"}:
        return int(value)
    return value


def _serialize_settings(settings: StudioSettings) -> dict[str, Any]:
    payload = asdict(settings)
    for key in PATH_FIELDS:
        payload[key] = str(payload[key])
    return payload

