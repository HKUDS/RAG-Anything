import pytest
from fastapi import HTTPException, Response
from starlette.requests import Request


@pytest.mark.asyncio
async def test_legacy_settings_read_is_deprecated_and_writes_are_disabled():
    from raganything.routers import admin

    response = Response()
    await admin.get_settings(response, _perm=None, current_user={"id": 1})

    assert response.headers["Deprecation"] == "true"
    assert response.headers["Sunset"] == "personal-platform-settings-v1"
    with pytest.raises(HTTPException) as write_error:
        await admin.update_settings(admin.SettingsUpdate(), current_user={"id": 1})
    assert write_error.value.status_code == 410
    assert write_error.value.detail["code"] == "settings_write_deprecated"


@pytest.mark.asyncio
async def test_profile_update_audit_never_records_current_password(monkeypatch):
    from raganything.routers import auth

    events = []

    async def current_user(_user_id):
        return {"id": 7, "password_hash": "hash"}

    async def update_user(_user_id, values):
        return {"username": values["username"]}

    async def audit(**kwargs):
        events.append(kwargs)

    monkeypatch.setattr(auth, "get_user_by_id", current_user)
    monkeypatch.setattr(auth, "verify_password", lambda value, _hash: value == "current-password")
    monkeypatch.setattr(auth, "update_user", update_user)
    monkeypatch.setattr(auth, "audit_log", audit)

    result = await auth.update_my_profile(
        request=Request({"type": "http", "method": "PUT", "path": "/api/auth/me/profile", "client": ("127.0.0.1", 0), "headers": []}),
        payload=auth.ProfileUpdateRequest(
            username="new-name", current_password="current-password",
        ),
        current_user={"id": 7, "username": "old-name"},
    )

    assert "email" not in result["user"]
    assert events == [{
        "actor_id": 7, "action": "user.profile.updated", "target_user_id": 7,
        "details": {"fields": ["username"], "result": "updated"},
        "ip_address": "127.0.0.1",
    }]
    assert "current-password" not in repr(events)


@pytest.mark.asyncio
async def test_model_probe_permission_dependency_rejects_unprivileged_user(monkeypatch):
    from raganything import dependencies
    from raganything.permissions import Permission

    async def no_permission(*_args):
        return False

    monkeypatch.setattr(dependencies, "_auth_has_permission", no_permission)
    checker = dependencies.require_permission(Permission.SETTINGS_WRITE)

    with pytest.raises(HTTPException) as denied:
        await checker(
            request=Request({"type": "http", "method": "POST", "path": "/api/admin/model-profiles/x/probe", "client": ("127.0.0.1", 0), "headers": []}),
            current_user={"id": 3, "username": "viewer", "role": {"name": "viewer"}},
        )

    assert denied.value.status_code == 403
