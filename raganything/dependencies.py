"""
RAG-Anything 共享 FastAPI 依赖项。

提取 server.py 中的公共依赖（认证、KB 访问验证、分页、限流），
各 Router 模块统一从此处导入，避免重复定义。
"""

from typing import Optional, Dict, Any

from fastapi import Query as QueryParam, Request, Depends, HTTPException
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from slowapi import Limiter
from slowapi.util import get_remote_address

from raganything.services.auth import (
    decode_token,
    get_user_by_id,
    check_account_locked,
    has_permission as _auth_has_permission,
    get_user_role as _auth_get_user_role,
)
from raganything.services.token_blacklist import get_token_blacklist

security = HTTPBearer()

# ── 限流器 ─────────────────────────────────────
limiter = Limiter(key_func=get_remote_address)


# ── 认证依赖 ─────────────────────────────────────

async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
) -> Dict[str, Any]:
    """从 Bearer Token 中解析当前登录用户。

    Args:
        credentials: HTTP Bearer Token 凭据

    Returns:
        包含 user_id, username, is_admin 等字段的用户字典

    Raises:
        HTTPException(401): Token 无效或过期
        HTTPException(401): 用户不存在或已禁用
    """
    try:
        payload = decode_token(credentials.credentials)
    except Exception:
        raise HTTPException(401, "Token 格式无效")

    if payload is None:
        raise HTTPException(401, "Token 无效或已过期")

    user_id = payload.get("user_id")
    if not user_id:
        raise HTTPException(401, "Token 无效或已过期")

    # 检查 Token 是否已被撤销（黑名单）
    jti = payload.get("jti")
    if jti and get_token_blacklist().is_revoked(jti):
        raise HTTPException(401, "Token 已被撤销，请重新登录")

    user = await get_user_by_id(user_id)
    if not user:
        raise HTTPException(401, "用户不存在")

    if not user.get("is_active"):
        raise HTTPException(401, "账号已被禁用")

    lock_error = await check_account_locked(user_id)
    if lock_error:
        raise HTTPException(403, lock_error)

    # 获取角色信息 — is_admin 必须从角色派生，不从 is_admin 列回退
    role = await _auth_get_user_role(user_id)
    is_admin = role is not None and role.get("name") == "admin"

    return {
        "id": user_id,
        "username": user["username"],
        "is_admin": is_admin,
        "role": role,  # 完整角色信息（含 permissions）
    }


async def get_admin_user(
    current_user: dict = Depends(get_current_user),
) -> dict:
    """.. deprecated:: v2.0
        请使用 ``require_permission(Permission.*)`` 代替。
        此函数保留仅为向后兼容。

    Args:
        current_user: 当前登录用户（由 get_current_user 注入）

    Returns:
        当前管理员用户字典

    Raises:
        HTTPException(403): 非管理员用户
    """
    if not current_user.get("is_admin"):
        raise HTTPException(403, "需要管理员权限")
    return current_user


def require_permission(permission: str):
    """FastAPI 依赖工厂：验证当前用户具有指定权限。

    用法：
        @router.get("/admin/users")
        async def list_users(user: dict = Depends(require_permission("users:read"))):
            ...

    Args:
        permission: 权限常数字符串（如 Permission.USERS_READ）

    Returns:
        依赖函数，注入当前已验证用户
    """

    async def _check_permission(
        current_user: dict = Depends(get_current_user),
    ) -> dict:
        """检查当前用户是否具有指定权限（统一通过 RBAC 角色权限系统）。"""
        # 统一通过 RBAC 角色-权限系统检查（admin 角色的 permissions 包含所有权限）
        user_id = current_user["id"]
        if await _auth_has_permission(user_id, permission):
            return current_user

        raise HTTPException(
            403,
            f"权限不足，需要权限: {permission}",
        )

    # 修改函数签名以便 FastAPI 正确生成 OpenAPI schema
    _check_permission.__name__ = f"require_{permission.replace(':', '_')}"
    return _check_permission


async def get_current_user_from_token(
    token: Optional[str] = None,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(
        HTTPBearer(auto_error=False)
    ),
) -> Optional[Dict[str, Any]]:
    """从 query 参数 token 或 Bearer header 中解析用户。

    优先级: query 参数 token > Authorization header。
    用于 img 标签等无法设置 header 的场景。
    """
    # 尝试从 query 参数获取 token
    if token:
        from fastapi.security import HTTPAuthorizationCredentials
        fake = HTTPAuthorizationCredentials(
            scheme="Bearer", credentials=token
        )
        try:
            return await get_current_user(fake)
        except HTTPException:
            return None

    # 回退到 Authorization header
    if credentials is not None:
        return await get_current_user(credentials)

    return None


async def get_optional_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(
        HTTPBearer(auto_error=False)
    ),
) -> Optional[Dict[str, Any]]:
    """可选的用户认证 — Token 存在则解析，不存在则返回 None。

    用于同时支持登录/匿名的端点。
    """
    if credentials is None:
        return None
    return await get_current_user(credentials)


# ── 知识库访问验证 ─────────────────────────────────────

async def verify_kb_access(
    kb: str = QueryParam("default"),
    current_user: dict = Depends(get_current_user),
) -> str:
    """验证当前用户对指定知识库的访问权限。

    Args:
        kb: 知识库名称（默认 "default"）
        current_user: 当前用户

    Returns:
        验证通过的知识库名称

    Raises:
        HTTPException(404): 知识库不存在
        HTTPException(403): 用户无权访问
    """
    from raganything.services.kb_service import load_kb_meta

    kb_meta = load_kb_meta()

    if kb not in kb_meta:
        raise HTTPException(404, f"知识库 '{kb}' 不存在")

    # 管理员可访问所有知识库
    if current_user.get("is_admin"):
        return kb

    allowed_kbs = current_user.get("allowed_kbs", [])
    if kb not in allowed_kbs:
        raise HTTPException(403, "无权访问该知识库")

    return kb


# ── 分页参数 ─────────────────────────────────────

class PaginationParams:
    """分页查询参数。

    Args:
        page: 页码（从 1 开始）
        page_size: 每页数量（默认 20，最大 100）
    """

    def __init__(
        self,
        page: int = QueryParam(1, ge=1, description="页码"),
        page_size: int = QueryParam(20, ge=1, le=100, description="每页数量"),
    ):
        self.page = page
        self.page_size = page_size
        self.offset = (page - 1) * page_size

    def paginate_response(self, items: list, total: int) -> dict:
        """构造标准化分页响应。

        Returns:
            {"items": [...], "total": N, "page": N, "page_size": N,
             "total_pages": N, "has_next": bool, "has_prev": bool}
        """
        total_pages = max(1, (total + self.page_size - 1) // self.page_size)
        return {
            "items": items,
            "total": total,
            "page": self.page,
            "page_size": self.page_size,
            "total_pages": total_pages,
            "has_next": self.page < total_pages,
            "has_prev": self.page > 1,
        }
