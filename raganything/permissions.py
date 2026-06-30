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

    # 使用分析（教学分析：学生使用频率、知识库覆盖率、问答统计）
    ANALYTICS_READ = "analytics:read"

    # 工作流
    WORKFLOW_READ = "workflow:read"
    WORKFLOW_WRITE = "workflow:write"

    # 制造智能体
    MANUFACTURING_READ = "manufacturing:read"
    MANUFACTURING_WRITE = "manufacturing:write"

    @classmethod
    def all_permissions(cls) -> List[str]:
        """返回所有权限常量的列表。"""
        return [
            v for k, v in vars(cls).items()
            if not k.startswith("_") and isinstance(v, str) and ":" in v
        ]


# ── 内置角色定义（五级权限体系）────────────────────────────────
# 角色对应关系：
#   super_admin — 超级管理员（信息中心/IT 运维）
#   dept_admin  — 系部管理员（系主任/实训中心主任）
#   teacher     — 主讲教师（任课教师）
#   assistant   — 助理教师（实训指导教师/助教）
#   student     — 学生（各年级学生）

DEFAULT_ROLES: Dict[str, Dict] = {
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
            Permission.MANUFACTURING_READ,
            Permission.MANUFACTURING_WRITE,
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
            Permission.MANUFACTURING_READ,
            Permission.MANUFACTURING_WRITE,
        ],
    },
    "assistant": {
        "description": "助理教师，可编辑知识库内容、使用智能体（实训指导教师/助教）",
        "permissions": [
            Permission.KB_READ,
            Permission.KB_WRITE,
            Permission.AGENT_READ,
            Permission.MONITOR_READ,
            Permission.MANUFACTURING_READ,
        ],
    },
    "student": {
        "description": "学生，可查看知识库并使用智能体问答（各年级学生）",
        "permissions": [
            Permission.KB_READ,
            Permission.AGENT_READ,
            Permission.MANUFACTURING_READ,
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
