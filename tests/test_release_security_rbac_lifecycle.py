"""Release-blocking auth configuration and lifecycle source contracts."""

from pathlib import Path

import pytest
from fastapi import HTTPException
from fastapi.security import HTTPAuthorizationCredentials

from raganything.services.pg_auth_repo import (
    AccountLifecycleConflict,
    production_configuration_errors,
    public_registration_enabled,
    validate_production_configuration,
)


def test_production_missing_configuration_reports_names_not_values():
    supplied_secret = "not-a-real-secret-for-test"
    errors = production_configuration_errors({
        "RAGANYTHING_ENV": "production",
        "JWT_SECRET": supplied_secret,
        "JWT_REFRESH_SECRET": "",
        "DEFAULT_ADMIN_PASSWORD": "",
        "DATABASE_URL": "",
    })
    assert "JWT_REFRESH_SECRET" in errors
    assert "DEFAULT_ADMIN_PASSWORD" in errors
    assert "POSTGRES_PASSWORD" in errors
    assert supplied_secret not in errors


def test_public_registration_is_default_closed_and_production_closed(monkeypatch):
    monkeypatch.delenv("ALLOW_PUBLIC_REGISTRATION", raising=False)
    monkeypatch.delenv("RAGANYTHING_ENV", raising=False)
    assert not public_registration_enabled()
    monkeypatch.setenv("ALLOW_PUBLIC_REGISTRATION", "true")
    assert public_registration_enabled()
    monkeypatch.setenv("RAGANYTHING_ENV", "production")
    assert not public_registration_enabled()


def test_production_validator_fails_closed_without_echoing_a_supplied_secret(monkeypatch):
    supplied_secret = "not-a-real-secret-for-test"
    monkeypatch.setenv("RAGANYTHING_ENV", "production")
    monkeypatch.setenv("JWT_SECRET", supplied_secret)
    monkeypatch.delenv("JWT_REFRESH_SECRET", raising=False)
    monkeypatch.delenv("DEFAULT_ADMIN_PASSWORD", raising=False)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    import pytest
    with pytest.raises(RuntimeError) as raised:
        validate_production_configuration()
    assert "JWT_REFRESH_SECRET" in str(raised.value)
    assert supplied_secret not in str(raised.value)


def test_auth_sources_have_no_random_secret_or_password_output():
    root = Path(__file__).resolve().parents[1]
    source = (root / "raganything" / "services" / "pg_auth_repo.py").read_text(encoding="utf-8")
    assert "secrets.token_hex" not in source
    assert "secrets.token_urlsafe" not in source
    assert "jwt_secret'" not in source
    assert "jwt_refresh_secret'" not in source


@pytest.mark.asyncio
async def test_http_dependency_rejects_a_generation_stale_token(monkeypatch):
    from raganything import dependencies

    monkeypatch.setattr(dependencies, "decode_token", lambda _token: {"user_id": 7, "jti": "j", "sg": 2})

    async def active_user(_user_id):
        return {"id": 7, "username": "user", "is_active": 1, "session_generation": 3}

    async def not_revoked(_jti):
        return False

    monkeypatch.setattr(dependencies, "get_user_by_id", active_user)
    monkeypatch.setattr(dependencies, "_auth_is_token_revoked", not_revoked)
    with pytest.raises(HTTPException) as rejected:
        await dependencies.get_current_user(HTTPAuthorizationCredentials(scheme="Bearer", credentials="old"))
    assert rejected.value.status_code == 401


@pytest.mark.parametrize(
    ("account", "revoked"),
    [
        (None, False),
        ({"id": 7, "is_active": 0, "archived_at": None, "session_generation": 3}, False),
        ({"id": 7, "is_active": 1, "archived_at": "2026-08-04T00:00:00Z", "session_generation": 3}, False),
        ({"id": 7, "is_active": 1, "archived_at": None, "session_generation": 4}, False),
        ({"id": 7, "is_active": 1, "archived_at": None, "session_generation": 3}, True),
    ],
)
@pytest.mark.asyncio
async def test_sse_wrapper_stops_before_delivery_for_invalid_sessions(monkeypatch, account, revoked):
    from raganything import dependencies

    async def events():
        yield "data: protected\n\n"

    async def current_account(_user_id):
        return account

    async def not_revoked(_jti):
        return revoked

    monkeypatch.setattr(dependencies, "get_user_by_id", current_account)
    monkeypatch.setattr(dependencies, "_auth_is_token_revoked", not_revoked)

    received = [
        event async for event in dependencies.authenticated_sse_events(
            events(), {"id": 7, "session_generation": 3, "token_jti": "jti"}
        )
    ]
    assert received == []


@pytest.mark.asyncio
async def test_closed_registration_never_calls_account_creation(monkeypatch):
    from raganything.routers import auth

    async def unexpected_create(*_args, **_kwargs):
        raise AssertionError("closed registration must not create an account")

    monkeypatch.setattr(auth, "public_registration_enabled", lambda: False)
    monkeypatch.setattr(auth, "create_user", unexpected_create)
    with pytest.raises(HTTPException) as rejected:
        await auth.register.__wrapped__(
            None, auth.AuthRegisterRequest(username="new-user", password="StrongP@ss123")
        )
    assert rejected.value.status_code == 404


@pytest.mark.asyncio
async def test_refresh_rejects_an_archived_or_stale_session_before_issuing_tokens(monkeypatch):
    from raganything.routers import auth

    monkeypatch.setattr(auth, "decode_refresh_token", lambda _token: {"user_id": 7, "sg": 2})

    async def archived_user(_user_id):
        return {"id": 7, "is_active": 1, "archived_at": "2026-08-04T00:00:00Z", "session_generation": 2}

    monkeypatch.setattr(auth, "get_user_by_id", archived_user)
    with pytest.raises(HTTPException) as rejected:
        await auth.refresh.__wrapped__(None, auth.RefreshRequest(refresh_token="old"))
    assert rejected.value.status_code == 401


@pytest.mark.asyncio
async def test_refresh_rotation_keeps_family_and_consumes_once(monkeypatch):
    from raganything.routers import auth

    old_payload = {
        "user_id": 7, "jti": "old-jti", "rfam": "family-1", "sg": 2,
    }
    new_payload = {
        "user_id": 7, "jti": "new-jti", "rfam": "family-1", "sg": 2,
        "exp": 4_102_444_800,
    }

    monkeypatch.setattr(
        auth, "decode_refresh_token",
        lambda value: old_payload if value == "old" else new_payload,
    )
    async def active_user(_user_id):
        return _active_user()

    async def user_role(_user_id):
        return _role()

    monkeypatch.setattr(auth, "get_user_by_id", active_user)
    monkeypatch.setattr(auth, "_auth_get_user_role", user_role)
    monkeypatch.setattr(auth, "create_token", lambda *_args, **_kwargs: "access")

    created = {}

    def create_refresh(*_args, **kwargs):
        created["family_id"] = kwargs.get("family_id")
        return "new"

    monkeypatch.setattr(auth, "create_refresh_token", create_refresh)
    rotated = []

    async def rotate(family_id, old_jti, new_jti, expires_at):
        rotated.append((family_id, old_jti, new_jti, expires_at))
        return True

    monkeypatch.setattr(auth, "rotate_refresh_token", rotate)
    result = await auth.refresh.__wrapped__(None, auth.RefreshRequest(refresh_token="old"))

    assert result["access_token"] == "access"
    assert result["refresh_token"] == "new"
    assert created["family_id"] == "family-1"
    assert rotated[0][:3] == ("family-1", "old-jti", "new-jti")


@pytest.mark.asyncio
async def test_refresh_replay_rejects_and_revokes_family(monkeypatch):
    from raganything.routers import auth

    monkeypatch.setattr(
        auth, "decode_refresh_token",
        lambda _value: {
            "user_id": 7, "jti": "old-jti", "rfam": "family-1", "sg": 2,
            "exp": 4_102_444_800,
        },
    )
    async def active_user(_user_id):
        return _active_user()

    async def user_role(_user_id):
        return _role()

    monkeypatch.setattr(auth, "get_user_by_id", active_user)
    monkeypatch.setattr(auth, "_auth_get_user_role", user_role)
    monkeypatch.setattr(auth, "create_token", lambda *_args, **_kwargs: "access")
    monkeypatch.setattr(auth, "create_refresh_token", lambda *_args, **_kwargs: "new")
    monkeypatch.setattr(auth, "rotate_refresh_token", lambda *_args, **_kwargs: _false_async())

    revoked = []

    async def revoke(family_id):
        revoked.append(family_id)

    monkeypatch.setattr(auth, "revoke_refresh_family", revoke)
    with pytest.raises(HTTPException) as rejected:
        await auth.refresh.__wrapped__(None, auth.RefreshRequest(refresh_token="old"))
    assert rejected.value.status_code == 401
    assert revoked == ["family-1"]


def _role():
    return {"name": "student", "permissions": ["kb:read"]}


def _active_user():
    return {
        "id": 7, "username": "user", "is_active": 1,
        "archived_at": None, "session_generation": 2,
    }


async def _false_async():
    return False


@pytest.mark.asyncio
async def test_websocket_handshake_rejects_generation_stale_token(monkeypatch):
    from raganything.routers import admin

    calls = []

    class FakeWebSocket:
        query_params = {"token": "old"}

        async def close(self, code, reason):
            calls.append((code, reason))

    monkeypatch.setattr(admin, "decode_token", lambda _token: {"user_id": 7, "sg": 1})

    async def stale_user(_user_id):
        return {"id": 7, "username": "user", "is_active": 1, "archived_at": None, "session_generation": 2}

    async def not_revoked(_jti):
        return False

    monkeypatch.setattr(admin, "get_user_by_id", stale_user)
    monkeypatch.setattr(admin, "_auth_is_token_revoked", not_revoked)
    user = await admin._authenticate_ws(FakeWebSocket())
    assert user is None
    assert calls == [(4001, "Account session is no longer valid")]


@pytest.mark.parametrize(
    ("payload", "account", "revoked", "reason"),
    [
        ({}, None, False, "Token missing user identity"),
        ({"user_id": 7, "jti": "j", "sg": 2}, None, True, "Token has been revoked"),
        ({"user_id": 7, "sg": 2}, {"id": 7, "username": "u", "is_active": 0, "archived_at": None, "session_generation": 2}, False, "Account disabled"),
        ({"user_id": 7, "sg": 2}, {"id": 7, "username": "u", "is_active": 1, "archived_at": "2026-08-04T00:00:00Z", "session_generation": 2}, False, "Account session is no longer valid"),
    ],
)
@pytest.mark.asyncio
async def test_websocket_handshake_rejects_missing_revoked_or_archived_account(
    monkeypatch, payload, account, revoked, reason
):
    from raganything.routers import admin

    calls = []

    class FakeWebSocket:
        query_params = {"token": "old"}

        async def close(self, code, reason):
            calls.append((code, reason))

    async def current_account(_user_id):
        return account

    async def is_revoked(_jti):
        return revoked

    monkeypatch.setattr(admin, "decode_token", lambda _token: dict(payload))
    monkeypatch.setattr(admin, "get_user_by_id", current_account)
    monkeypatch.setattr(admin, "_auth_is_token_revoked", is_revoked)
    assert await admin._authenticate_ws(FakeWebSocket()) is None
    assert calls == [(4001, reason)]


@pytest.mark.asyncio
async def test_websocket_broadcast_closes_stale_session_before_delivery(monkeypatch):
    from raganything.services import ws_service

    calls = []

    class FakeWebSocket:
        async def close(self, code, reason):
            calls.append(("close", code, reason))

        async def send_json(self, _data):
            calls.append(("send", _data))

    ws = FakeWebSocket()

    async def stale_session(_session):
        return False

    ws_service.ws_clients[:] = []
    ws_service._ws_sessions.clear()
    monkeypatch.setattr(ws_service, "_session_is_current", stale_session)
    ws_service.register_general_ws(ws, {"id": 7, "session_generation": 1})

    await ws_service.ws_broadcast({"type": "protected-progress"})
    assert calls == [("close", 4001, "Account session is no longer valid")]
    assert ws not in ws_service.ws_clients


class _Transaction:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return False


class _LifecycleConnection:
    def __init__(self, *, active_super_admins):
        self.active_super_admins = active_super_admins
        self.executed = []

    def transaction(self):
        return _Transaction()

    async def execute(self, sql, *args):
        self.executed.append((sql, args))

    async def fetchrow(self, sql, *_args):
        if "FOR UPDATE" in sql:
            return {"is_active": 1, "archived_at": None, "role_name": "super_admin"}
        raise AssertionError(f"unexpected query: {sql}")

    async def fetchval(self, _sql, *_args):
        return self.active_super_admins


class _LifecyclePool:
    def __init__(self, connection):
        self.connection = connection

    def acquire(self):
        return self

    async def __aenter__(self):
        return self.connection

    async def __aexit__(self, *_args):
        return False


@pytest.mark.asyncio
async def test_repository_transaction_preserves_final_super_admin(monkeypatch):
    from raganything.services import pg_auth_repo

    connection = _LifecycleConnection(active_super_admins=1)
    monkeypatch.setattr(pg_auth_repo, "_get_pool", lambda: _LifecyclePool(connection))

    with pytest.raises(AccountLifecycleConflict):
        await pg_auth_repo.update_user(7, {"is_active": 0}, actor_role_name="super_admin")
    with pytest.raises(AccountLifecycleConflict):
        await pg_auth_repo.delete_user(7, archived_by=1, archive_reason="offboarding")

    assert all("UPDATE users SET" not in sql for sql, _args in connection.executed)
    assert any("pg_advisory_xact_lock" in sql for sql, _args in connection.executed)


@pytest.mark.asyncio
async def test_repository_archives_nonfinal_admin_with_generation_increment(monkeypatch):
    from raganything.services import pg_auth_repo

    connection = _LifecycleConnection(active_super_admins=2)
    monkeypatch.setattr(pg_auth_repo, "_get_pool", lambda: _LifecyclePool(connection))

    assert await pg_auth_repo.delete_user(7, archived_by=1, archive_reason="offboarding")
    mutation_sql, mutation_args = connection.executed[-1]
    assert "archived_at = NOW()" in mutation_sql
    assert "session_generation = session_generation + 1" in mutation_sql
    assert mutation_args == (1, "offboarding", 7)


@pytest.mark.asyncio
async def test_archive_router_records_actor_and_reason_without_credentials(monkeypatch):
    from raganything.routers import auth

    recorded = {}

    async def archive_user(user_id, **kwargs):
        recorded["archive"] = (user_id, kwargs)
        return True

    async def audit(**kwargs):
        recorded["audit"] = kwargs

    async def target_user(_user_id):
        return {"id": 8, "username": "target", "role_id": 5}

    monkeypatch.setattr(auth, "delete_user", archive_user)
    monkeypatch.setattr(auth, "audit_log", audit)
    monkeypatch.setattr(auth, "get_user_by_id", target_user)
    request = type("Request", (), {"client": None})()
    response = await auth.admin_delete_user(
        8,
        request,
        archive_reason="offboarding",
        user={"id": 1, "role": {"name": "super_admin"}},
    )
    assert response == {"status": "ok", "lifecycle": "archived"}
    assert recorded["archive"] == (8, {"archived_by": 1, "archive_reason": "offboarding"})
    assert recorded["audit"]["action"] == "user.archive"
    assert recorded["audit"]["details"]["archive_reason"] == "offboarding"
