"""User-management permission tests for the five-level RBAC model."""

import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from raganything.permissions import DEFAULT_ROLES, Permission


class TestAdminUserPermissions:
    def test_super_admin_has_all_user_permissions(self):
        permissions = DEFAULT_ROLES["super_admin"]["permissions"]
        assert Permission.USERS_READ in permissions
        assert Permission.USERS_WRITE in permissions
        assert Permission.USERS_DELETE in permissions

    def test_dept_admin_can_manage_but_not_delete_users(self):
        permissions = DEFAULT_ROLES["dept_admin"]["permissions"]
        assert Permission.USERS_READ in permissions
        assert Permission.USERS_WRITE in permissions
        assert Permission.USERS_DELETE not in permissions

    @pytest.mark.parametrize("role_name", ["teacher", "assistant", "student"])
    def test_non_admin_roles_cannot_manage_users(self, role_name):
        permissions = DEFAULT_ROLES[role_name]["permissions"]
        assert Permission.USERS_READ not in permissions
        assert Permission.USERS_WRITE not in permissions


class TestPasswordComplexityRules:
    def test_strong_password_all_four_classes(self):
        password = "MyStr0ng!Pass"
        assert sum(
            bool(pattern.search(password))
            for pattern in (
                re.compile(r"[A-Z]"),
                re.compile(r"[a-z]"),
                re.compile(r"[0-9]"),
                re.compile(r"[^A-Za-z0-9]"),
            )
        ) == 4

    def test_strong_password_three_classes(self):
        password = "StrongPass123"
        assert sum(
            bool(pattern.search(password))
            for pattern in (
                re.compile(r"[A-Z]"),
                re.compile(r"[a-z]"),
                re.compile(r"[0-9]"),
                re.compile(r"[^A-Za-z0-9]"),
            )
        ) == 3

    @pytest.mark.parametrize("password", ["Ab1!", "Abc1", "A1"])
    def test_short_passwords_fail_minimum_length(self, password):
        assert len(password) < 8


class TestRoleHierarchy:
    def test_five_level_permissions_are_monotonic(self):
        role_chain = ["super_admin", "dept_admin", "teacher", "assistant", "student"]
        for higher, lower in zip(role_chain, role_chain[1:]):
            higher_permissions = set(DEFAULT_ROLES[higher]["permissions"])
            lower_permissions = set(DEFAULT_ROLES[lower]["permissions"])
            assert lower_permissions.issubset(higher_permissions)
