"""Unit tests for RBAC v2 permission constants, default roles, and helpers."""

import asyncio
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from raganything.permissions import (  # noqa: E402
    DEFAULT_ROLE_NAME,
    DEFAULT_ROLES,
    Permission,
    get_role_permissions,
    has_permission_from_role,
)


EXPECTED_ROLE_NAMES = {
    "super_admin",
    "dept_admin",
    "teacher",
    "assistant",
    "student",
}


EXPECTED_ROLE_PERMISSIONS = {
    "dept_admin": {
        Permission.USERS_READ,
        Permission.USERS_WRITE,
        Permission.KB_READ,
        Permission.KB_WRITE,
        Permission.KB_DELETE,
        Permission.AGENT_READ,
        Permission.AGENT_WRITE,
        Permission.AGENT_DELETE,
        Permission.SETTINGS_READ,
        Permission.AUDIT_READ,
        Permission.MONITOR_READ,
        Permission.ANALYTICS_READ,
        Permission.WORKFLOW_READ,
        Permission.WORKFLOW_WRITE,
        Permission.AUTOREPAIR_READ,
        Permission.AUTOREPAIR_WRITE,
        Permission.GRAPH_READ,
        Permission.GRAPH_WRITE,
    },
    "teacher": {
        Permission.KB_READ,
        Permission.KB_WRITE,
        Permission.AGENT_READ,
        Permission.AGENT_WRITE,
        Permission.MONITOR_READ,
        Permission.ANALYTICS_READ,
        Permission.WORKFLOW_READ,
        Permission.AUTOREPAIR_READ,
        Permission.AUTOREPAIR_WRITE,
        Permission.GRAPH_READ,
        Permission.GRAPH_WRITE,
    },
    "assistant": {
        Permission.KB_READ,
        Permission.KB_WRITE,
        Permission.AGENT_READ,
        Permission.MONITOR_READ,
        Permission.AUTOREPAIR_READ,
        Permission.GRAPH_READ,
        Permission.GRAPH_WRITE,
    },
    "student": {
        Permission.KB_READ,
        Permission.AGENT_READ,
        Permission.AUTOREPAIR_READ,
        Permission.GRAPH_READ,
    },
}


class TestPermissionConstants:
    """Permission constant definitions."""

    def test_all_permissions_defined(self):
        """All permission constants should be non-empty resource:action strings."""
        perms = Permission.all_permissions()
        assert len(perms) >= 10
        for permission in perms:
            assert ":" in permission, f"Permission '{permission}' should contain ':'"
            resource, action = permission.split(":", 1)
            assert resource
            assert action

    def test_permission_format(self):
        """Selected Permission constants should use resource:action format."""
        assert Permission.USERS_READ == "users:read"
        assert Permission.USERS_WRITE == "users:write"
        assert Permission.KB_READ == "kb:read"
        assert Permission.AGENT_READ == "agent:read"
        assert Permission.AUDIT_READ == "audit:read"


class TestDefaultRoles:
    """Built-in RBAC v2 role definitions."""

    def test_five_default_roles(self):
        """RBAC v2 should expose the five current built-in roles."""
        assert set(DEFAULT_ROLES) == EXPECTED_ROLE_NAMES

    def test_student_is_the_default_new_user_role(self):
        assert DEFAULT_ROLE_NAME == "student"

    def test_roles_have_descriptions(self):
        """Each built-in role should have a non-empty description."""
        for role_name in EXPECTED_ROLE_NAMES:
            assert DEFAULT_ROLES[role_name]["description"]

    def test_super_admin_has_all_permissions(self):
        """Super admins should have every declared permission."""
        super_admin_perms = set(DEFAULT_ROLES["super_admin"]["permissions"])
        assert super_admin_perms == set(Permission.all_permissions())

    @pytest.mark.parametrize("role_name", ["dept_admin", "teacher", "assistant", "student"])
    def test_role_permissions_match_rbac_v2_matrix(self, role_name):
        """Non-super-admin roles should match the RBAC v2 permission matrix."""
        assert set(DEFAULT_ROLES[role_name]["permissions"]) == EXPECTED_ROLE_PERMISSIONS[role_name]

    def test_dept_admin_cannot_delete_users_or_write_settings(self):
        """Department admins manage users but do not get destructive user or settings write powers."""
        dept_admin_perms = set(DEFAULT_ROLES["dept_admin"]["permissions"])
        assert Permission.USERS_READ in dept_admin_perms
        assert Permission.USERS_WRITE in dept_admin_perms
        assert Permission.USERS_DELETE not in dept_admin_perms
        assert Permission.SETTINGS_WRITE not in dept_admin_perms

    def test_student_is_read_only(self):
        """Students should only have read-style access to learning resources."""
        student_perms = set(DEFAULT_ROLES["student"]["permissions"])
        assert Permission.KB_READ in student_perms
        assert Permission.AGENT_READ in student_perms
        assert Permission.KB_WRITE not in student_perms
        assert Permission.USERS_WRITE not in student_perms
        assert Permission.SETTINGS_WRITE not in student_perms


class TestPermissionUtilities:
    """Permission helper functions."""

    def test_get_role_permissions_valid_json(self):
        """Valid JSON permissions should be parsed into a list."""
        perms_json = json.dumps(["kb:read", "kb:write"])
        result = get_role_permissions(perms_json)
        assert result == ["kb:read", "kb:write"]

    def test_get_role_permissions_empty(self):
        """An empty JSON list should return an empty list."""
        assert get_role_permissions("[]") == []

    def test_get_role_permissions_invalid_json(self):
        """Invalid JSON should return an empty list."""
        assert get_role_permissions("not-json") == []

    def test_has_permission_from_role_found(self):
        """A required permission should match when present."""
        assert has_permission_from_role('["kb:read", "kb:write"]', "kb:read")

    def test_has_permission_from_role_not_found(self):
        """A required permission should not match when absent."""
        assert not has_permission_from_role('["kb:read"]', "users:delete")


class TestFiveLevelRestoreMigration:
    def test_migration_upserts_current_five_role_matrix(self):
        migration = (Path(__file__).parent.parent / "migrations" / "015_restore_5level_rbac.sql").read_text(encoding="utf-8")
        assert "ON CONFLICT (name) DO UPDATE" in migration
        for role_name in EXPECTED_ROLE_NAMES:
            assert f"('{role_name}'" in migration

    def test_migration_remaps_temporary_three_role_accounts_without_deleting_rows(self):
        migration = (Path(__file__).parent.parent / "migrations" / "015_restore_5level_rbac.sql").read_text(encoding="utf-8")
        assert "('admin', 'super_admin')" in migration
        assert "('editor', 'teacher')" in migration
        assert "('viewer', 'student')" in migration
        assert "DELETE FROM ROLES" not in migration.upper()

    def test_role_catalog_hides_temporary_three_role_rows(self, monkeypatch):
        monkeypatch.setenv("DEFAULT_ADMIN_PASSWORD", "TestPass!123")
        from raganything.services import pg_auth_repo

        class FakeConnection:
            async def fetch(self, _query):
                return [
                    {"id": 1, "name": "admin", "permissions": "[]"},
                    {"id": 2, "name": "editor", "permissions": "[]"},
                    {"id": 3, "name": "viewer", "permissions": "[]"},
                    *[
                        {"id": index + 4, "name": name, "permissions": "[]"}
                        for index, name in enumerate(DEFAULT_ROLES)
                    ],
                ]

        class FakeAcquire:
            async def __aenter__(self):
                return FakeConnection()

            async def __aexit__(self, *_args):
                return False

        class FakePool:
            def acquire(self):
                return FakeAcquire()

        monkeypatch.setattr(pg_auth_repo, "_pool_ref", FakePool())
        roles = asyncio.run(pg_auth_repo.list_roles())
        assert [role["name"] for role in roles] == list(DEFAULT_ROLES)
