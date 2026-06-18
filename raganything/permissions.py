# -*- coding: utf-8 -*-
"""
RAG-Anything 权限常量定义。

定义系统内所有权限常数字符串以及内置角色及其默认权限集。
权限命名规范：`<resource>:<action>`（如 kb:read, users:write）。
"""

from __future__ import annotations

import json
from typing import List, Dict


class Permission:
    """权限常量 — 字符串格式 `resource:action`。"""

    # 用户管理
    USERS_READ = "users:read"
    USERS_WRITE = "users:write"
    USERS_DELETE = "users:delete"

    # 知识库
    KB_READ = "kb:read"
    KB_WRITE = "kb:write"
    KB_DELETE = "kb:delete"

    # 智能体
    AGENT_READ = "agent:read"
    AGENT_WRITE = "agent:write"
    AGENT_DELETE = "agent:delete"

    # 系统设置
    SETTINGS_READ = "settings:read"
    SETTINGS_WRITE = "settings:write"

    # 审计日志
    AUDIT_READ = "audit:read"

    # 监控
    MONITOR_READ = "monitor:read"

    @classmethod
    def all_permissions(cls) -> List[str]:
        """返回所有权限常量的列表。"""
        return [
            v for k, v in vars(cls).items()
            if not k.startswith("_") and isinstance(v, str) and ":" in v
        ]


# ── 内置角色定义 ────────────────────────────────────────────

DEFAULT_ROLES: Dict[str, Dict] = {
    "admin": {
        "description": "系统管理员，拥有全部权限",
        "permissions": Permission.all_permissions(),
    },
    "editor": {
        "description": "内容编辑，可读写知识库和智能体",
        "permissions": [
            Permission.KB_READ,
            Permission.KB_WRITE,
            Permission.AGENT_READ,
            Permission.AGENT_WRITE,
            Permission.MONITOR_READ,
        ],
    },
    "viewer": {
        "description": "只读用户，仅可查看知识库和智能体",
        "permissions": [
            Permission.KB_READ,
            Permission.AGENT_READ,
            Permission.MONITOR_READ,
        ],
    },
}


# ── 权限工具函数 ────────────────────────────────────────────

def get_role_permissions(role_permissions_json: str) -> List[str]:
    """从 roles 表的 JSON permissions 字段解析权限列表。"""
    try:
        perms = json.loads(role_permissions_json or "[]")
        return perms if isinstance(perms, list) else []
    except (json.JSONDecodeError, TypeError):
        return []


def has_permission_from_role(role_permissions_json: str, required: str) -> bool:
    """检查角色的 JSON permissions 中是否包含指定权限。"""
    return required in get_role_permissions(role_permissions_json)
