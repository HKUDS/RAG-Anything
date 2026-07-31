"""Authenticated vision-model catalog and personal VLM preference APIs."""

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import BaseModel

from raganything.dependencies import get_current_user, require_permission
from raganything.permissions import Permission
from raganything.services import vision_models

router = APIRouter(tags=["vision-models"])


class ModelPreferenceUpdate(BaseModel):
    vision_vlm_profile_id: str | None = None


def _profile_or_missing(profile_id: str | None):
    if profile_id is None:
        return None
    try:
        return vision_models.get_entry(profile_id, "vlm").public().model_dump()
    except KeyError:
        # Persisted legacy IDs stay visible so users can explicitly replace
        # them; provider configuration is never included in this projection.
        return {
            "id": profile_id,
            "kind": "vlm",
            "display_name": f"Unknown stored VLM profile ({profile_id})",
            "provider": "unknown",
            "model": "unknown",
            "capabilities": [],
            "embedding_dim": None,
            "available": False,
            "unavailable_reason": "catalog_missing",
        }


@router.get("/vision-models")
async def list_vision_models(
    kind: Literal["vlm", "embedding"] | None = Query(default=None),
    response: Response = None,
    _user: dict = Depends(get_current_user),
):
    try:
        if response is not None:
            response.headers["Deprecation"] = "true"
            response.headers["Sunset"] = "legacy-vision-models"
        return {"profiles": [profile.model_dump() for profile in vision_models.list_profiles(kind)]}
    except RuntimeError as exc:
        raise HTTPException(503, {"code": "catalog_unavailable", "message": "vision model catalog unavailable"}) from exc


@router.get("/model-profiles")
async def list_model_profiles(
    kind: Literal["llm", "vlm", "embedding"] | None = Query(default=None),
    _user: dict = Depends(get_current_user),
):
    try:
        return {"profiles": [profile.model_dump() for profile in vision_models.list_model_profiles(kind)]}
    except RuntimeError as exc:
        raise HTTPException(503, {"code": "catalog_unavailable", "message": "model catalog unavailable"}) from exc


@router.post("/admin/model-profiles/{profile_id}/probe")
async def probe_model_profile(
    profile_id: str,
    user: dict = Depends(require_permission(Permission.SETTINGS_WRITE)),
):
    try:
        result = await vision_models.probe_model_profile(profile_id)
    except KeyError as exc:
        raise HTTPException(422, {"code": "invalid_profile", "message": "unknown model profile"}) from exc
    await vision_models.audit_vision_event(
        int(user["id"]), "model.profile.probed", profile_id=profile_id,
        result="available" if result.get("available") else "unavailable",
    )
    return result


@router.get("/users/me/model-preferences")
async def get_model_preferences(user: dict = Depends(get_current_user)):
    profile_id = await vision_models.get_user_vlm_preference(int(user["id"]))
    return {"vision_vlm_profile_id": profile_id, "profile": _profile_or_missing(profile_id)}


@router.put("/users/me/model-preferences")
async def update_model_preferences(
    payload: ModelPreferenceUpdate,
    user: dict = Depends(get_current_user),
):
    previous = await vision_models.get_user_vlm_preference(int(user["id"]))
    try:
        profile_id = await vision_models.set_user_vlm_preference(
            int(user["id"]), payload.vision_vlm_profile_id
        )
    except RuntimeError as exc:
        await vision_models.audit_vision_event(
            int(user["id"]), "vision.preference.updated", profile_id=payload.vision_vlm_profile_id,
            previous_profile_id=previous, result="unavailable",
        )
        raise HTTPException(503, {"code": "profile_unavailable", "message": "selected vision profile is unavailable"}) from exc
    except (KeyError, ValueError) as exc:
        await vision_models.audit_vision_event(
            int(user["id"]), "vision.preference.updated", profile_id=payload.vision_vlm_profile_id,
            previous_profile_id=previous, result="invalid",
        )
        raise HTTPException(422, {"code": "invalid_profile", "message": "invalid vision profile"}) from exc

    await vision_models.audit_vision_event(
        int(user["id"]), "vision.preference.updated", profile_id=profile_id,
        previous_profile_id=previous,
    )
    return {"vision_vlm_profile_id": profile_id, "profile": _profile_or_missing(profile_id)}
