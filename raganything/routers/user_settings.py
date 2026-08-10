"""Personal and platform settings APIs backed by typed PostgreSQL state."""

from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from raganything.dependencies import get_current_user, require_permission
from raganything.permissions import Permission
from raganything.services import user_settings
from raganything.services.auth import audit_log
from raganything.services.vision_models import list_model_profiles

router = APIRouter(tags=["user-settings"])


class SectionPatch(BaseModel):
    expected_revision: int
    values: dict[str, Any] | None


class PlatformUpdate(BaseModel):
    expected_revision: int
    settings: dict[str, Any]


def _permitted_sections(user: dict) -> tuple[user_settings.Section, ...]:
    permissions = (user.get("role") or {}).get("permissions") or []
    return user_settings.available_sections(permissions)


async def _audit_personal_settings(
    user_id: int,
    section: str,
    revision: int,
    result: str,
    values: dict[str, Any] | None,
) -> None:
    details: dict[str, Any] = {
        "section": section,
        "revision": revision,
        "result": result,
    }
    if section == "models" and isinstance(values, dict):
        profile_ids = [
            str(values[field])
            for field in ("llm_profile_id", "vlm_profile_id")
            if values.get(field)
        ]
        if profile_ids:
            details["profile_id"] = ",".join(profile_ids)
    await audit_log(user_id, "user.settings.updated", details=details)


@router.get("/users/me/settings")
async def get_my_settings(user: dict = Depends(get_current_user)):
    try:
        return await user_settings.get_user_settings(
            int(user["id"]), permitted_sections=_permitted_sections(user),
        )
    except RuntimeError as exc:
        raise HTTPException(503, {"code": "settings_unavailable", "message": "personal settings storage is unavailable"}) from exc


@router.get("/users/me/settings/options")
async def get_my_settings_options(user: dict = Depends(get_current_user)):
    try:
        platform = await user_settings.get_platform_settings()
        sections = _permitted_sections(user)
        options = user_settings.project_settings_options(
            user_settings.settings_options(
                platform["settings"],
                include_ingestion_catalogs=("ingestion" in sections),
            ),
            sections,
        )
        allowed = options["allowed"]
        list_name_for_kind = {
            "llm": "llm_profile_ids",
            "vlm": "vlm_profile_ids",
            "embedding": "embedding_profile_ids",
        }
        options["profiles"] = []
        if "models" in sections:
            options["profiles"] = [
                profile.model_dump()
                for profile in list_model_profiles()
                if profile.kind in {"llm", "vlm"}
                if not allowed.get(list_name_for_kind[profile.kind], [])
                or profile.id in allowed[list_name_for_kind[profile.kind]]
            ]
        # Ingestion catalogs follow the same allow-list semantics as model
        # profiles: a non-empty allow-list restricts the catalog, an empty
        # allow-list means "no restriction" and keeps every supported option.
        if "ingestion" in sections:
            options["parsers"] = [
                item for item in options.get("parsers", [])
                if not allowed.get("parsers", []) or item["id"] in allowed["parsers"]
            ]
            options["chunking_strategies"] = [
                item for item in options.get("chunking_strategies", [])
                if not allowed.get("chunking_strategies", [])
                or item["id"] in allowed["chunking_strategies"]
            ]
        options["available_sections"] = list(sections)
        return options
    except RuntimeError as exc:
        raise HTTPException(503, {"code": "catalog_unavailable", "message": "model catalog unavailable"}) from exc


@router.patch("/users/me/settings/{section}")
async def patch_my_settings(
    section: Literal["models", "ingestion", "retrieval", "runtime"],
    payload: SectionPatch,
    user: dict = Depends(get_current_user),
):
    user_id = int(user["id"])
    if section not in _permitted_sections(user):
        await _audit_personal_settings(user_id, section, payload.expected_revision, "denied", None)
        raise HTTPException(403, {"code": "settings_section_forbidden", "message": "personal settings section is unavailable"})
    try:
        result = await user_settings.patch_user_settings(user_id, section, payload.values, payload.expected_revision)
    except ValueError as exc:
        await _audit_personal_settings(user_id, section, payload.expected_revision, "invalid", payload.values)
        raise HTTPException(422, {"code": "invalid_settings", "message": str(exc)}) from exc
    except user_settings.ProfileUnavailableError as exc:
        await _audit_personal_settings(user_id, section, payload.expected_revision, "unavailable", payload.values)
        raise HTTPException(503, {"code": "profile_unavailable", "message": str(exc)}) from exc
    except RuntimeError as exc:
        await _audit_personal_settings(user_id, section, payload.expected_revision, "storage_unavailable", payload.values)
        raise HTTPException(503, {"code": "settings_unavailable", "message": "personal settings storage is unavailable"}) from exc
    if result is None:
        await _audit_personal_settings(user_id, section, payload.expected_revision, "revision_conflict", payload.values)
        raise HTTPException(409, {"code": "revision_conflict", "message": "settings revision has changed"})
    await _audit_personal_settings(user_id, section, result["revision"], "updated", payload.values)
    return await user_settings.get_user_settings(
        user_id, permitted_sections=_permitted_sections(user),
    )


@router.get("/admin/platform")
async def get_platform_settings(user: dict = Depends(require_permission(Permission.SETTINGS_READ))):
    try:
        return await user_settings.get_platform_settings()
    except RuntimeError as exc:
        raise HTTPException(503, {"code": "platform_settings_unavailable", "message": "platform settings storage is unavailable"}) from exc


@router.put("/admin/platform")
async def update_platform_settings(
    payload: PlatformUpdate,
    user: dict = Depends(require_permission(Permission.SETTINGS_WRITE)),
):
    try:
        result = await user_settings.put_platform_settings(payload.settings, payload.expected_revision)
    except ValueError as exc:
        raise HTTPException(422, {"code": "invalid_platform_policy", "message": str(exc)}) from exc
    except PermissionError as exc:
        raise HTTPException(423, {"code": "platform_read_only", "message": "platform policy is read-only"}) from exc
    except RuntimeError as exc:
        raise HTTPException(503, {"code": "platform_settings_unavailable", "message": "platform settings storage is unavailable"}) from exc
    if result is None:
        raise HTTPException(409, {"code": "revision_conflict", "message": "platform revision has changed"})
    await audit_log(
        int(user["id"]),
        "platform.settings.updated",
        details={
            "section": ",".join(result.get("changed_sections", [])),
            "revision": result["revision"],
            "result": "updated",
        },
    )
    return result
