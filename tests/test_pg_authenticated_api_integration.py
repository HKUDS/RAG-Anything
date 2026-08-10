"""Real-PostgreSQL HTTP authentication and permission contract.

The release workflow supplies ``DATABASE_URL`` after applying the canonical
migrations. This fixture uses the production auth router and dependencies with
an ASGI transport, while keeping all test rows uniquely named and disposable.
"""

from __future__ import annotations

import os
import uuid

import pytest

try:
    import pytest_asyncio
except ImportError:  # pragma: no cover - the frozen CI dev group includes it
    pytest_asyncio = None
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient


pytestmark = pytest.mark.skipif(
    not os.getenv("DATABASE_URL"),
    reason="DATABASE_URL is required for authenticated PostgreSQL API integration",
)


@((pytest_asyncio.fixture) if pytest_asyncio else pytest.fixture)
async def authenticated_api_client():
    from raganything.routers.auth import router as auth_router
    from raganything.dependencies import limiter
    from raganything.services.pg_auth_repo import create_user
    from raganything.services.pg_state_repo import close_pg_pool, init_pg_pool

    pool = await init_pg_pool()
    username = f"ci_api_{uuid.uuid4().hex[:20]}"
    password = "CiRelease!Api2026"
    user = await create_user(username, password)
    app = FastAPI()
    app.state.limiter = limiter
    app.include_router(auth_router, prefix="/api")

    try:
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://release-gate"
        ) as client:
            yield client, username, password, int(user["id"])
    finally:
        async with pool.acquire() as conn:
            await conn.execute(
                "DELETE FROM audit_logs WHERE actor_id = $1 OR target_user_id = $1",
                int(user["id"]),
            )
            await conn.execute("DELETE FROM users WHERE id = $1", int(user["id"]))
        await close_pg_pool()


@pytest.mark.asyncio
async def test_authenticated_postgres_api_contract(authenticated_api_client):
    client, username, password, _user_id = authenticated_api_client

    login = await client.post(
        "/api/auth/login", json={"username": username, "password": password}
    )
    assert login.status_code == 200, login.text
    access_token = login.json()["access_token"]
    refresh_token = login.json()["refresh_token"]
    headers = {"Authorization": f"Bearer {access_token}"}

    rotated = await client.post(
        "/api/auth/refresh", json={"refresh_token": refresh_token}
    )
    assert rotated.status_code == 200, rotated.text
    rotated_token = rotated.json()["refresh_token"]
    rotated_again = await client.post(
        "/api/auth/refresh", json={"refresh_token": rotated_token}
    )
    assert rotated_again.status_code == 200, rotated_again.text

    replay = await client.post(
        "/api/auth/refresh", json={"refresh_token": refresh_token}
    )
    assert replay.status_code == 401, replay.text
    family_revoked = await client.post(
        "/api/auth/refresh", json={"refresh_token": rotated_again.json()["refresh_token"]}
    )
    assert family_revoked.status_code == 401, family_revoked.text

    me = await client.get("/api/auth/me", headers=headers)
    assert me.status_code == 200, me.text
    assert me.json()["user"]["username"] == username

    forbidden = await client.get("/api/admin/users", headers=headers)
    assert forbidden.status_code == 403, forbidden.text


@pytest.mark.asyncio
async def test_password_change_returns_a_current_session(authenticated_api_client):
    client, username, password, _user_id = authenticated_api_client

    login = await client.post(
        "/api/auth/login", json={"username": username, "password": password}
    )
    assert login.status_code == 200, login.text
    old_access = login.json()["access_token"]
    old_refresh = login.json()["refresh_token"]

    changed_password = "CiRelease!Api2026-Changed"
    changed = await client.put(
        "/api/auth/me/password",
        headers={"Authorization": f"Bearer {old_access}"},
        json={"old_password": password, "new_password": changed_password},
    )
    assert changed.status_code == 200, changed.text
    new_tokens = changed.json()
    assert new_tokens["user"]["username"] == username

    current = await client.get(
        "/api/auth/me",
        headers={"Authorization": f"Bearer {new_tokens['access_token']}"},
    )
    assert current.status_code == 200, current.text

    stale_access = await client.get(
        "/api/auth/me", headers={"Authorization": f"Bearer {old_access}"}
    )
    assert stale_access.status_code == 401, stale_access.text

    stale_refresh = await client.post(
        "/api/auth/refresh", json={"refresh_token": old_refresh}
    )
    assert stale_refresh.status_code == 401, stale_refresh.text

    refreshed = await client.post(
        "/api/auth/refresh", json={"refresh_token": new_tokens["refresh_token"]}
    )
    assert refreshed.status_code == 200, refreshed.text
