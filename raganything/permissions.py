# -*- coding: utf-8 -*-
"""RBAC permission constants and built-in role definitions."""

from __future__ import annotations

import json
from typing import Dict, List


class Permission:
    """Permission constants in `resource:action` format."""

    USERS_READ = "users:read"
    USERS_WRITE = "users:write"
    USERS_DELETE = "users:delete"

    KB_READ = "kb:read"
    KB_WRITE = "kb:write"
    KB_DELETE = "kb:delete"

    AGENT_READ = "agent:read"
    AGENT_WRITE = "agent:write"
    AGENT_DELETE = "agent:delete"

    SETTINGS_READ = "settings:read"
    SETTINGS_WRITE = "settings:write"

    AUDIT_READ = "audit:read"
    MONITOR_READ = "monitor:read"
    ANALYTICS_READ = "analytics:read"

    WORKFLOW_READ = "workflow:read"
    WORKFLOW_WRITE = "workflow:write"

    GRAPH_READ = "graph:read"
    GRAPH_WRITE = "graph:write"

    AUTOREPAIR_READ = "autorepair:read"
    AUTOREPAIR_WRITE = "autorepair:write"

    @classmethod
    def all_permissions(cls) -> List[str]:
        return [
            value
            for key, value in vars(cls).items()
            if not key.startswith("_") and isinstance(value, str) and ":" in value
        ]


DEFAULT_ROLE_NAME = "student"

# Role hierarchy: index 0 is the most privileged.  A role may only assign
# another role whose privilege level is not higher than its own.
ROLE_ORDER = ["super_admin", "dept_admin", "teacher", "assistant", "student"]
ROLE_RANK: Dict[str, int] = {
    role_name: rank for rank, role_name in enumerate(ROLE_ORDER)
}


def can_assign_role(actor_role_name: str, target_role_name: str) -> bool:
    """Whether ``actor_role_name`` may assign ``target_role_name``.

    A role may assign itself or any lower-privileged role
    (``super_admin > dept_admin > teacher > assistant > student``).
    Unknown role names are rejected.
    """
    actor_rank = ROLE_RANK.get(actor_role_name)
    target_rank = ROLE_RANK.get(target_role_name)
    if actor_rank is None or target_rank is None:
        return False
    return target_rank >= actor_rank


DEFAULT_ROLES: Dict[str, Dict[str, object]] = {
    "super_admin": {
        "description": "超级管理员，拥有全部权限（信息中心/IT运维）",
        "permissions": Permission.all_permissions(),
    },
    "dept_admin": {
        "description": "系部管理员，管理系统内知识库、智能体和用户（系主任/实训中心主任）",
        "permissions": [
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
        ],
    },
    "teacher": {
        "description": "主讲教师，可创建管理自有知识库和智能体（任课教师）",
        "permissions": [
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
        ],
    },
    "assistant": {
        "description": "助理教师，可编辑知识库内容、使用智能体（实训指导教师/助教）",
        "permissions": [
            Permission.KB_READ,
            Permission.KB_WRITE,
            Permission.AGENT_READ,
            Permission.MONITOR_READ,
            Permission.AUTOREPAIR_READ,
            Permission.GRAPH_READ,
            Permission.GRAPH_WRITE,
        ],
    },
    "student": {
        "description": "学生，可查看知识库并使用智能体问答（各年级学生）",
        "permissions": [
            Permission.KB_READ,
            Permission.AGENT_READ,
            Permission.AUTOREPAIR_READ,
            Permission.GRAPH_READ,
        ],
    },
}


def get_role_permissions(role_permissions_json: str) -> List[str]:
    """Parse the `roles.permissions` JSON payload into a list."""
    try:
        perms = json.loads(role_permissions_json or "[]")
        return perms if isinstance(perms, list) else []
    except (json.JSONDecodeError, TypeError):
        return []


def has_permission_from_role(role_permissions_json: str, required: str) -> bool:
    """Check whether a serialized role permission set contains `required`."""
    return required in get_role_permissions(role_permissions_json)
