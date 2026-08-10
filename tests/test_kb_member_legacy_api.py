import pytest
from fastapi import HTTPException

from raganything.routers.auth import AdminUpdateUserRequest, admin_update_user


@pytest.mark.asyncio
async def test_admin_user_update_rejects_legacy_allowed_kbs_before_mutation():
    request = AdminUpdateUserRequest(allowed_kbs=["team-kb"])

    with pytest.raises(HTTPException) as exc:
        await admin_update_user(
            user_id=7,
            req=request,
            request=None,
            user={"id": 1, "role": {"name": "super_admin"}},
        )

    assert exc.value.status_code == 422
    assert "成员" in str(exc.value.detail)
