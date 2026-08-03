"""Role-assignment hierarchy guards for the five-level RBAC model.

Covers permissions.py can_assign_role(), runtime role seed consistency with
DEFAULT_ROLES, and repository/router-layer enforcement of the rule that a
role may only assign another role whose privilege level is not higher than
its own (super_admin > dept_admin > teacher > assistant > student).
"""

import sys
from pathlib import Path

import pytest
from fastapi import HTTPException, Request

sys.path.insert(0, str(Path(__file__).parent.parent))

from raganything.permissions import (  # noqa: E402
    DEFAULT_ROLE_NAME,
    DEFAULT_ROLES,
    ROLE_ORDER,
    ROLE_RANK,
    can_assign_role,
)
from raganything.services.pg_auth_repo import (  # noqa: E402
    build_default_role_rows,
    create_user,
    update_user,
)

STRONG_PW = "Strong!Pass1"


class TestCanAssignRole:
    """can_assign_role() hierarchy rules."""

    def test_role_order_and_rank(self):
        assert ROLE_ORDER == [
            "super_admin", "dept_admin", "teacher", "assistant", "student",
        ]
        for higher, lower in zip(ROLE_ORDER, ROLE_ORDER[1:]):
            assert ROLE_RANK[higher] < ROLE_RANK[lower]

    def test_super_admin_can_assign_any_role(self):
        for target in ROLE_ORDER:
            assert can_assign_role("super_admin", target)

    def test_dept_admin_cannot_assign_super_admin(self):
        assert not can_assign_role("dept_admin", "super_admin")
        assert can_assign_role("dept_admin", "dept_admin")
        assert can_assign_role("dept_admin", "teacher")
        assert can_assign_role("dept_admin", "student")

    def test_teacher_cannot_assign_admin_roles(self):
        assert not can_assign_role("teacher", "super_admin")
        assert not can_assign_role("teacher", "dept_admin")
        assert can_assign_role("teacher", "teacher")
        assert can_assign_role("teacher", "assistant")
        assert can_assign_role("teacher", "student")

    def test_assistant_cannot_assign_teacher_or_above(self):
        assert not can_assign_role("assistant", "teacher")
        assert not can_assign_role("assistant", "dept_admin")
        assert can_assign_role("assistant", "assistant")
        assert can_assign_role("assistant", "student")

    def test_student_can_only_assign_student(self):
        for target in ROLE_ORDER:
            if target == "student":
                assert can_assign_role("student", target)
            else:
                assert not can_assign_role("student", target)

    def test_unknown_roles_rejected(self):
        assert not can_assign_role("super_admin", "unknown")
        assert not can_assign_role("unknown", "student")
        assert not can_assign_role(None, "student")
        assert not can_assign_role("student", None)

    def test_default_role_assignable_by_everyone(self):
        assert DEFAULT_ROLE_NAME == "student"
        assert all(can_assign_role(role, "student") for role in ROLE_ORDER)


class TestRuntimeSeedConsistency:
    """Runtime role seed must not drift from permissions.py DEFAULT_ROLES."""

    def test_build_default_role_rows_matches_default_roles(self):
        assert build_default_role_rows() == DEFAULT_ROLES

    def test_seed_rows_are_isolated_copies(self):
        rows = build_default_role_rows()
        rows["student"]["permissions"].append("users:read")
        assert "users:read" not in DEFAULT_ROLES["student"]["permissions"]

    def test_seed_covers_all_five_roles(self):
        assert set(build_default_role_rows()) == set(ROLE_ORDER)


class _FakeConn:
    def __init__(self, role_row, user_row=None):
        self.role_row = role_row
        self.user_row = user_row

    async def fetchrow(self, sql, *args):
        if "INSERT INTO users" in sql or "UPDATE users" in sql:
            return self.user_row
        if "SELECT * FROM users" in sql:
            return self.user_row
        return self.role_row

    async def execute(self, sql, *args):
        return "UPDATE 1"


class _FakePool:
    def __init__(self, role_row, user_row=None):
        self.conn = _FakeConn(role_row, user_row)

    def acquire(self):
        """Mimic asyncpg's pool.acquire() async context manager."""
        return self

    async def __aenter__(self):
        return self.conn

    async def __aexit__(self, *exc_info):
        return False


@pytest.fixture
def fake_pool(monkeypatch):
    import raganything.services.pg_auth_repo as repo

    pool = _FakePool({"id": 1, "name": "super_admin"})
    monkeypatch.setattr(repo, "_get_pool", lambda: pool)
    return pool


class TestRepoLayerRoleGuard:
    """pg_auth_repo.create_user/update_user enforce the assignment rule."""

    @pytest.mark.asyncio
    async def test_create_user_rejects_higher_target_role(self, fake_pool):
        with pytest.raises(PermissionError):
            await create_user("alice", STRONG_PW, role_id=1, actor_role_name="dept_admin")

    @pytest.mark.asyncio
    async def test_create_user_rejects_missing_actor_with_explicit_role(self, fake_pool):
        with pytest.raises(ValueError):
            await create_user("alice", STRONG_PW, role_id=1)

    @pytest.mark.asyncio
    async def test_create_user_allows_same_level_role(self, fake_pool):
        fake_pool.conn.role_row = {"id": 2, "name": "dept_admin"}
        fake_pool.conn.user_row = {
            "id": 9, "username": "alice", "role_id": 2, "must_change_password": 1,
        }
        user = await create_user("alice", STRONG_PW, role_id=2, actor_role_name="dept_admin")
        assert user["role_id"] == 2

    @pytest.mark.asyncio
    async def test_create_user_defaults_to_student_without_actor(self, fake_pool):
        fake_pool.conn.role_row = {"id": 5, "name": "student"}
        fake_pool.conn.user_row = {
            "id": 10, "username": "bob", "role_id": 5, "must_change_password": 0,
        }
        user = await create_user("bob", STRONG_PW)
        assert user["role_id"] == 5

    @pytest.mark.asyncio
    async def test_update_user_rejects_higher_target_role(self, fake_pool):
        with pytest.raises(PermissionError):
            await update_user(5, {"role_id": 1}, actor_role_name="teacher")

    @pytest.mark.asyncio
    async def test_update_user_rejects_missing_actor_with_role_change(self, fake_pool):
        with pytest.raises(ValueError):
            await update_user(5, {"role_id": 1})

    @pytest.mark.asyncio
    async def test_update_user_allows_same_level_role(self, fake_pool):
        fake_pool.conn.role_row = {"id": 3, "name": "teacher"}
        fake_pool.conn.user_row = {"id": 5, "username": "carol", "role_id": 3}
        updated = await update_user(5, {"role_id": 3}, actor_role_name="teacher")
        assert updated["role_id"] == 3

    @pytest.mark.asyncio
    async def test_update_user_non_role_update_needs_no_actor(self, fake_pool):
        fake_pool.conn.user_row = {"id": 5, "username": "carol", "role_id": 4}
        updated = await update_user(5, {"username": "carol2"})
        assert updated["username"] == "carol"


class TestAdminUserPermissionErrorMapping:
    """Router layer maps repo PermissionError to HTTP 403."""

    @pytest.mark.asyncio
    async def test_admin_create_user_maps_permission_error_to_403(self, monkeypatch):
        from raganything.routers import auth as auth_router

        async def denied(*args, **kwargs):
            raise PermissionError("无权分配角色 'super_admin': 目标角色等级高于操作者")

        monkeypatch.setattr(auth_router, "create_user", denied)
        request = Request({
            "type": "http", "method": "POST", "path": "/api/admin/users",
            "client": ("127.0.0.1", 0), "headers": [],
        })
        req = auth_router.AdminCreateUserRequest(
            username="alice", password=STRONG_PW, role_id=1,
        )
        with pytest.raises(HTTPException) as exc:
            await auth_router.admin_create_user(
                request=request, req=req,
                user={"id": 2, "username": "da", "is_admin": False, "role": {"name": "dept_admin"}},
            )
        assert exc.value.status_code == 403

    @pytest.mark.asyncio
    async def test_admin_update_user_maps_permission_error_to_403(self, monkeypatch):
        from raganything.routers import auth as auth_router

        async def denied(*args, **kwargs):
            raise PermissionError("无权将角色修改为 'super_admin': 目标角色等级高于操作者")

        async def fake_get_user_by_id(user_id):
            return {"id": 5, "username": "bob", "role_id": 1}

        async def fake_get_user_role(user_id):
            return {"id": 1, "name": "super_admin"}

        async def fake_audit(*args, **kwargs):
            return None

        monkeypatch.setattr(auth_router, "update_user", denied)
        monkeypatch.setattr(auth_router, "get_user_by_id", fake_get_user_by_id)
        monkeypatch.setattr(auth_router, "_auth_get_user_role", fake_get_user_role)
        monkeypatch.setattr(auth_router, "audit_log", fake_audit)
        request = Request({
            "type": "http", "method": "PUT", "path": "/api/admin/users/5",
            "client": ("127.0.0.1", 0), "headers": [],
        })
        req = auth_router.AdminUpdateUserRequest(role_id=1)
        with pytest.raises(HTTPException) as exc:
            await auth_router.admin_update_user(
                user_id=5, req=req, request=request,
                user={"id": 2, "username": "da", "is_admin": False, "role": {"name": "dept_admin"}},
            )
        assert exc.value.status_code == 403

    @pytest.mark.asyncio
    async def test_admin_update_user_passes_actor_role_to_repo(self, monkeypatch):
        from raganything.routers import auth as auth_router

        captured = {}

        async def recording_update_user(user_id, data, actor_role_name=None):
            captured["actor_role_name"] = actor_role_name
            captured["data"] = data
            return {"id": 5, "username": "bob", "role_id": 4}

        async def fake_get_user_by_id(user_id):
            return {"id": 5, "username": "bob", "role_id": 1}

        async def fake_get_user_role(user_id):
            return {"id": 1, "name": "super_admin"}

        async def fake_audit(*args, **kwargs):
            return None

        monkeypatch.setattr(auth_router, "update_user", recording_update_user)
        monkeypatch.setattr(auth_router, "get_user_by_id", fake_get_user_by_id)
        monkeypatch.setattr(auth_router, "_auth_get_user_role", fake_get_user_role)
        monkeypatch.setattr(auth_router, "audit_log", fake_audit)
        request = Request({
            "type": "http", "method": "PUT", "path": "/api/admin/users/5",
            "client": ("127.0.0.1", 0), "headers": [],
        })
        req = auth_router.AdminUpdateUserRequest(role_id=4)
        await auth_router.admin_update_user(
            user_id=5, req=req, request=request,
            user={"id": 1, "username": "sa", "is_admin": True, "role": {"name": "super_admin"}},
        )
        assert captured["actor_role_name"] == "super_admin"
        assert captured["data"]["role_id"] == 4
