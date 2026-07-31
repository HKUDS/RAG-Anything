import pytest
from fastapi import HTTPException

from raganything.dependencies import verify_kb_access


@pytest.mark.asyncio
async def test_verify_kb_access_allows_owner_without_allowed_kbs(monkeypatch):
    async def fake_load_kb_meta():
        return {
            "owner-kb": {
                "owner_id": 7,
                "owner_username": "alice",
            }
        }

    monkeypatch.setattr(
        "raganything.services.kb_service.load_kb_meta",
        fake_load_kb_meta,
    )

    current_user = {
        "id": 7,
        "username": "alice",
        "is_admin": False,
        "allowed_kbs": [],
    }

    result = await verify_kb_access(kb="owner-kb", current_user=current_user)

    assert result == "owner-kb"


@pytest.mark.asyncio
async def test_verify_kb_access_rejects_non_owner_without_allowed_kbs(monkeypatch):
    async def fake_load_kb_meta():
        return {
            "owner-kb": {
                "owner_id": 7,
                "owner_username": "alice",
            }
        }

    monkeypatch.setattr(
        "raganything.services.kb_service.load_kb_meta",
        fake_load_kb_meta,
    )

    current_user = {
        "id": 9,
        "username": "bob",
        "is_admin": False,
        "allowed_kbs": [],
    }

    with pytest.raises(HTTPException) as exc:
        await verify_kb_access(kb="owner-kb", current_user=current_user)

    assert exc.value.status_code == 403
