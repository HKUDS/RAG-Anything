"""Auth Router — /api/auth/* and /api/admin/* (users, roles, audit)"""

from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException, Request, Query as QueryParam
from pydantic import BaseModel
from typing import Optional

from raganything.services.auth import (
    check_account_locked,
    create_refresh_token,
    create_token,
    create_user,
    decode_refresh_token,
    decode_token,
    delete_user,
    get_role_by_name,
    get_user_by_id,
    get_user_by_username,
    get_user_role as _auth_get_user_role,
    list_roles,
    list_users,
    record_failed_login,
    reset_failed_logins,
    update_last_login_at,
    update_user,
    verify_password,
    # Token blacklist dispatch (Phase 1 PG migration)
    is_token_revoked,
    revoke_token,
    revoke_refresh_family,
    register_refresh_family,
    # Audit log dispatch (PG-backed)
    audit_log,
    query_audit_logs as _dispatch_query_audit_logs,
)
from raganything.dependencies import (
    get_current_user,
    get_admin_user,
    require_permission,
    limiter,
)
from raganything.permissions import Permission

router = APIRouter(tags=["auth"])

# ── Pydantic models ────────────────────────────────────

class AuthRegisterRequest(BaseModel):
    username: str
    email: str
    password: str


class AuthLoginRequest(BaseModel):
    username: str
    password: str


class AdminCreateUserRequest(BaseModel):
    username: str
    email: str
    password: str
    role_id: int = None  # 默认由 create_user 分配 student 角色


class AdminUpdateUserRequest(BaseModel):
    username: Optional[str] = None
    email: Optional[str] = None
    password: Optional[str] = None
    is_admin: Optional[int] = None   # no-op: 已废弃，使用 role_id 代替，前端兼容保留
    is_active: Optional[int] = None
    role_id: Optional[int] = None


class RefreshRequest(BaseModel):
    refresh_token: str


class ProfileUpdateRequest(BaseModel):
    username: str
    email: str
    current_password: str


class PasswordUpdateRequest(BaseModel):
    old_password: str
    new_password: str


def _masked_email(email: str | None) -> str | None:
    if not email or "@" not in email:
        return None
    local, domain = email.split("@", 1)
    visible = local[:1]
    return f"{visible}{'*' * max(1, len(local) - 1)}@{domain}"


# ── Auth Routes ─────────────────────────────────────────

@router.post("/auth/register")
@limiter.limit("5/minute")
async def register(request: Request, req: AuthRegisterRequest):
    """用户注册"""
    try:
        user = await create_user(req.username, req.email, req.password)
        return {"status": "ok", "user": user}
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.post("/auth/login")
@limiter.limit("10/minute")
async def login(request: Request, req: AuthLoginRequest):
    """用户登录"""
    user = await get_user_by_username(req.username)
    if not user:
        raise HTTPException(401, "用户名或密码错误")

    lock_error = await check_account_locked(user["id"])
    if lock_error:
        raise HTTPException(403, lock_error)

    if not user.get("is_active"):
        raise HTTPException(403, "账号已被禁用")

    if not verify_password(req.password, user["password_hash"]):
        await record_failed_login(user["id"])
        raise HTTPException(401, "用户名或密码错误")

    await reset_failed_logins(user["id"])

    # 更新最后登录时间（使用派发函数，支持 PG/SQLite）
    await update_last_login_at(user["id"])

    # Fetch role for embedding in JWT
    role = await _auth_get_user_role(user["id"])
    is_admin = role is not None and role.get("name") == "super_admin"
    token = create_token(user["id"], user["username"], is_admin, role)
    refresh = create_refresh_token(user["id"], user["username"], is_admin, role)

    # 注册 refresh token 到 family (PG-first dispatch)
    import jwt as _pyjwt
    try:
        r_payload = _pyjwt.decode(refresh, options={"verify_signature": False})
        await register_refresh_family(r_payload.get("rfam", ""), r_payload.get("jti", ""))
    except Exception:
        pass

    return {
        "status": "ok",
        "access_token": token,
        "refresh_token": refresh,
        "user": {"id": user["id"], "username": user["username"], "is_admin": is_admin},
    }


@router.post("/auth/refresh")
@limiter.limit("10/minute")
async def refresh(request: Request, req: RefreshRequest):
    """刷新 Token（含 Refresh Token 轮转 + 重放检测）"""
    try:
        payload = decode_refresh_token(req.refresh_token)
    except Exception:
        raise HTTPException(401, "Refresh Token 无效或已过期")

    if payload is None:
        raise HTTPException(401, "Refresh Token 无效或已过期")

    # 检查 refresh token 是否已被撤销（重放检测，PG-first dispatch）
    jti = payload.get("jti")
    if jti and await is_token_revoked(jti):
        # 重放攻击检测：撤销该用户整个 refresh family
        rfam = payload.get("rfam", "")
        if rfam:
            await revoke_refresh_family(rfam)
        raise HTTPException(401, "Refresh Token 已被使用过，请重新登录")

    user = await get_user_by_id(payload["user_id"])
    if not user or not user.get("is_active"):
        raise HTTPException(401, "用户不存在或已禁用")

    # 撤销旧的 refresh token (PG-first dispatch)
    if jti:
        from datetime import timedelta as _td
        await revoke_token(jti, datetime.now(timezone.utc) + _td(days=30))

    # 颁发新 token 对（嵌入角色信息）
    role = await _auth_get_user_role(user["id"])
    is_admin = role is not None and role.get("name") == "super_admin"
    token = create_token(user["id"], user["username"], is_admin, role)
    new_refresh = create_refresh_token(user["id"], user["username"], is_admin, role)

    # 注册新 refresh token（保持同一 family，PG-first dispatch）
    import jwt as _pyjwt
    try:
        r_payload = _pyjwt.decode(new_refresh, options={"verify_signature": False})
        new_jti = r_payload.get("jti", "")
        rfam = payload.get("rfam", "")  # 使用原始 family
        if rfam and new_jti:
            await register_refresh_family(rfam, new_jti)
    except Exception:
        pass

    return {
        "status": "ok",
        "access_token": token,
        "refresh_token": new_refresh,
    }


@router.get("/auth/me")
async def me(current_user: dict = Depends(get_current_user)):
    """获取当前用户信息"""
    # 检查是否需要修改密码
    user = await get_user_by_id(current_user["id"])
    must_change = user.get("must_change_password", False) if user else False
    email = _masked_email(user.get("email") if user else None)
    return {
        "status": "ok",
        "user": {**current_user, "email": email, "must_change_password": bool(must_change)},
    }


@router.put("/auth/me/profile")
@limiter.limit("5/minute")
async def update_my_profile(
    request: Request,
    payload: ProfileUpdateRequest,
    current_user: dict = Depends(get_current_user),
):
    """Update username/email only after current-password verification."""
    user = await get_user_by_id(current_user["id"])
    if not user:
        raise HTTPException(404, "用户不存在")
    if not verify_password(payload.current_password, user["password_hash"]):
        raise HTTPException(400, "当前密码不正确")
    try:
        updated = await update_user(current_user["id"], {"username": payload.username, "email": payload.email})
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    await audit_log(
        actor_id=current_user["id"], action="user.profile.updated", target_user_id=current_user["id"],
        details={"fields": ["username", "email"], "result": "updated"},
        ip_address=request.client.host if request.client else None,
    )
    return {"status": "ok", "user": {**current_user, "username": updated["username"], "email": _masked_email(updated.get("email"))}}


@router.post("/auth/logout")
async def logout(
    request: Request,
    current_user: dict = Depends(get_current_user),
):
    """用户登出 — 撤销当前 Access Token 和 Refresh Token Family"""
    # 从 Authorization header 提取 access token jti
    auth_header = request.headers.get("Authorization", "")
    token_str = auth_header.replace("Bearer ", "") if auth_header.startswith("Bearer ") else ""

    if token_str:
        try:
            payload = decode_token(token_str)
            if payload:
                jti = payload.get("jti")
                if jti:
                    from datetime import timedelta as _td
                    exp = payload.get("exp")
                    if exp:
                        from datetime import datetime as _dt, timezone as _tz
                        expires_at = _dt.fromtimestamp(exp, tz=_tz.utc)
                    else:
                        expires_at = datetime.now(timezone.utc) + _td(hours=24)
                    await revoke_token(jti, expires_at)
        except Exception:
            pass

    # 从请求体提取 refresh token 并撤销其 family
    try:
        body = await request.json()
        refresh_token_str = body.get("refresh_token", "") if body else ""
    except Exception:
        refresh_token_str = ""

    if refresh_token_str:
        try:
            r_payload = decode_refresh_token(refresh_token_str)
            if r_payload:
                rfam = r_payload.get("rfam")
                r_jti = r_payload.get("jti")
                if r_jti:
                    await revoke_token(
                        r_jti,
                        datetime.now(timezone.utc) + timedelta(days=30)
                    )
                if rfam:
                    await revoke_refresh_family(rfam)
        except Exception:
            pass

    return {"status": "ok"}


# ── Auth: Change Password ───────────────────────────────

@router.put("/auth/me/password")
@limiter.limit("5/minute")
async def change_password(
    request: Request,
    payload: PasswordUpdateRequest,
    current_user: dict = Depends(get_current_user),
):
    """当前用户修改密码"""
    import re as _re_pw

    old_password = payload.old_password
    new_password = payload.new_password

    if not old_password or not new_password:
        raise HTTPException(400, "请提供旧密码和新密码")

    user = await get_user_by_id(current_user["id"])
    if not user:
        raise HTTPException(404, "用户不存在")

    # 验证旧密码
    from raganything.services.auth import pwd_context
    if not pwd_context.verify(old_password, user["password_hash"]):
        raise HTTPException(400, "旧密码不正确")

    # 密码复杂度校验
    if len(new_password) < 8:
        raise HTTPException(422, "密码至少需要 8 位")
    if len(new_password) > 128:
        raise HTTPException(422, "密码不能超过 128 位")

    complexity = 0
    if _re_pw.search(r'[A-Z]', new_password):
        complexity += 1
    if _re_pw.search(r'[a-z]', new_password):
        complexity += 1
    if _re_pw.search(r'[0-9]', new_password):
        complexity += 1
    if _re_pw.search(r'[^A-Za-z0-9]', new_password):
        complexity += 1
    if complexity < 3:
        raise HTTPException(422, "密码需包含大写字母、小写字母、数字、特殊字符中的至少三类")

    # 更新密码（使用派发函数，支持 PG/SQLite）
    try:
        await update_user(current_user["id"], {
            "password": new_password,
            "must_change_password": 0,
        })
    except ValueError as e:
        raise HTTPException(400, str(e))

    await audit_log(
        actor_id=current_user["id"], action="user.password.updated", target_user_id=current_user["id"],
        details={"result": "updated"}, ip_address=request.client.host if request.client else None,
    )

    return {"status": "ok", "message": "密码修改成功"}


# ── Auth: must_change_password check ─────────────────────

@router.get("/auth/check-password-status")
async def check_password_status(
    current_user: dict = Depends(get_current_user),
):
    """检查当前用户是否需要修改密码"""
    user = await get_user_by_id(current_user["id"])
    must_change = user.get("must_change_password", False) if user else False
    return {"status": "ok", "must_change_password": bool(must_change)}


# ── Admin: Roles ───────────────────────────────────────

@router.get("/admin/roles")
async def admin_list_roles(
    user: dict = Depends(require_permission(Permission.USERS_READ)),
):
    """返回所有角色列表"""
    roles = await list_roles()
    return {"status": "ok", "roles": roles}


# ── Admin: User Management ─────────────────────────────

@router.get("/admin/users")
@limiter.limit("30/minute")
async def admin_list_users(
    request: Request,
    user: dict = Depends(require_permission(Permission.USERS_READ)),
    page: int = QueryParam(1, ge=1, description="页码"),
    page_size: int = QueryParam(20, ge=1, le=100, description="每页数量"),
    search: str = QueryParam("", description="搜索用户名或邮箱"),
    role: str = QueryParam("", description="按角色名筛选"),
    status: str = QueryParam("", description="按状态筛选: active/inactive"),
):
    """管理员获取用户列表（分页、搜索、筛选）。使用派发函数，支持 PG/SQLite。"""
    # Fetch all users and roles via dispatched functions
    all_users = await list_users()
    all_roles = await list_roles()
    role_map = {r["id"]: r for r in all_roles}

    # Enrich users with role info
    for u in all_users:
        r = role_map.get(u.get("role_id"))
        u["role_name"] = r["name"] if r else None
        u["role_permissions"] = r.get("permissions", []) if r else []
        u["is_admin"] = (u["role_name"] == "super_admin")

    # Filter
    filtered = all_users
    if search:
        search_lower = search.lower()
        filtered = [
            u for u in filtered
            if search_lower in (u.get("username", "") or "").lower()
            or search_lower in (u.get("email", "") or "").lower()
        ]
    if role:
        filtered = [u for u in filtered if u.get("role_name") == role]
    if status == "active":
        filtered = [u for u in filtered if u.get("is_active")]
    elif status == "inactive":
        filtered = [u for u in filtered if not u.get("is_active")]

    total = len(filtered)

    # Paginate
    offset = (page - 1) * page_size
    paged = filtered[offset:offset + page_size]

    # Clean up internal fields for response
    users = []
    for u in paged:
        clean = {k: v for k, v in u.items() if k not in ("password_hash", "role_permissions")}
        users.append(clean)

    total_pages = max(1, (total + page_size - 1) // page_size)
    return {
        "status": "ok",
        "users": users,
        "total": total,
        "page": page,
        "page_size": page_size,
        "total_pages": total_pages,
    }


@router.post("/admin/users", status_code=201)
@limiter.limit("5/minute")
async def admin_create_user(
    request: Request,
    req: AdminCreateUserRequest,
    user: dict = Depends(require_permission(Permission.USERS_WRITE)),
):
    """管理员创建新用户"""
    try:
        new_user = await create_user(
            req.username, req.email, req.password,
            role_id=req.role_id, must_change_password=True,
        )
    except ValueError as e:
        msg = str(e)
        if "用户名已被占用" in msg or "邮箱已被占用" in msg:
            raise HTTPException(409, msg)
        elif "角色" in msg:
            raise HTTPException(400, msg)
        else:
            raise HTTPException(422, msg)

    new_id = new_user["id"]

    # 审计日志 — 包含角色名称（PG-first dispatch）
    role_name = "unknown"
    try:
        role = await _auth_get_user_role(new_id)
        if role:
            role_name = role.get("name", "unknown")
    except Exception:
        pass

    await audit_log(
        actor_id=user["id"],
        action="user.create",
        target_user_id=new_id,
        details={
            "username": req.username,
            "email": req.email,
            "role_id": req.role_id,
            "role_name": role_name,
            "actor_role": user.get("role", {}).get("name", "unknown"),
        },
        ip_address=request.client.host if request.client else None,
    )

    return {"status": "ok", "user": new_user}


@router.get("/admin/users/{user_id}")
async def admin_get_user(
    user_id: int,
    user: dict = Depends(require_permission(Permission.USERS_READ)),
):
    """管理员获取用户详情"""
    u = await get_user_by_id(user_id)
    if not u:
        raise HTTPException(404, "用户不存在")

    # Fetch role info
    role = await _auth_get_user_role(user_id)
    if role:
        u["role"] = {"id": role["id"], "name": role["name"], "permissions": role.get("permissions", [])}
        u["is_admin"] = role.get("name") == "super_admin"
    else:
        u["role"] = {"id": None, "name": None, "permissions": []}
        u["is_admin"] = False

    return {"status": "ok", "user": u}


@router.put("/admin/users/{user_id}")
async def admin_update_user(
    user_id: int,
    req: AdminUpdateUserRequest,
    request: Request,
    user: dict = Depends(require_permission(Permission.USERS_WRITE)),
):
    """管理员更新用户信息"""
    update_data = {k: v for k, v in req.dict().items() if v is not None}
    if not update_data:
        raise HTTPException(400, "无更新内容")

    # is_admin 已废弃，忽略此字段（使用 role_id 代替）
    update_data.pop("is_admin", None)

    # 防自降级（使用派发函数）
    if "role_id" in update_data and user_id == user["id"]:
        my_role = await _auth_get_user_role(user_id)
        if my_role and my_role.get("name") == "super_admin":
            if update_data["role_id"] != my_role["id"]:
                raise HTTPException(403, "不能取消自己的管理员权限")

    # 获取更新前的用户信息和角色用于审计
    before_user = await get_user_by_id(user_id)
    before_role = await _auth_get_user_role(user_id) if before_user else None

    try:
        updated = await update_user(user_id, update_data)
    except ValueError as e:
        raise HTTPException(400, str(e))

    if updated is None:
        raise HTTPException(404, "用户不存在")

    # 获取更新后的角色
    after_role = await _auth_get_user_role(user_id)

    # 审计日志 — 角色变更时解析角色名称（PG-first dispatch）
    action = "user.role_change" if "role_id" in update_data else "user.update"
    # 记录变更字段
    changed_fields = list(update_data.keys())
    if "password" in update_data:
        changed_fields.remove("password")
        changed_fields.append("password_hash")

    # 构建审计详情（含角色名称解析）
    audit_details = {
        "changed_fields": changed_fields,
        "before": {k: before_user[k] for k in changed_fields if k in before_user} if before_user else {},
        "after": {k: updated[k] for k in changed_fields if k in updated},
    }

    # 角色变更时，附加角色名称以便审计可读性
    if "role_id" in update_data:
        if before_role:
            audit_details["before_role_name"] = before_role.get("name", "unknown")
        if after_role:
            audit_details["after_role_name"] = after_role.get("name", "unknown")
        audit_details["actor_role"] = user.get("role", {}).get("name", "unknown")

    await audit_log(
        actor_id=user["id"],
        action=action,
        target_user_id=user_id,
        details=audit_details,
        ip_address=request.client.host if request.client else None,
    )

    return {"status": "ok", "user": updated}


@router.delete("/admin/users/{user_id}")
async def admin_delete_user(
    user_id: int,
    request: Request,
    user: dict = Depends(require_permission(Permission.USERS_DELETE)),
):
    """管理员删除用户"""
    if user_id == user["id"]:
        raise HTTPException(403, "不能删除自己")

    # 获取被删用户信息用于审计
    deleted_user = await get_user_by_id(user_id)

    success = await delete_user(user_id)
    if not success:
        raise HTTPException(404, "用户不存在")

    # 审计日志（PG-first dispatch）
    await audit_log(
        actor_id=user["id"],
        action="user.delete",
        target_user_id=user_id,
        details={
            "username": deleted_user.get("username") if deleted_user else "unknown",
            "email": deleted_user.get("email") if deleted_user else "unknown",
            "role_id": deleted_user.get("role_id") if deleted_user else None,
            "actor_role": user.get("role", {}).get("name", "unknown"),
        },
        ip_address=request.client.host if request.client else None,
    )

    return {"status": "ok"}


# ── Admin: Audit Logs ───────────────────────────────────

@router.get("/admin/audit-logs")
@limiter.limit("30/minute")
async def admin_audit_logs(
    request: Request,
    page: int = QueryParam(1, ge=1, description="页码"),
    page_size: int = QueryParam(20, ge=1, le=100, description="每页数量"),
    actor_id: Optional[int] = QueryParam(None, description="按操作人 ID 筛选"),
    action: Optional[str] = QueryParam(None, description="按操作类型筛选"),
    user: dict = Depends(require_permission(Permission.AUDIT_READ)),
):
    """管理员查询审计日志（分页 + 筛选）- PG-first dispatch"""
    result = await _dispatch_query_audit_logs(
        page=page,
        page_size=page_size,
        actor_id=actor_id,
        action=action,
    )
    return {"status": "ok", **result}


# ── Admin: Audit Health ───────────────────────────────────

@router.get("/admin/health/audit")
@limiter.limit("30/minute")
async def admin_audit_health(
    request: Request,
    user: dict = Depends(require_permission(Permission.AUDIT_READ)),
):
    """检查审计日志子系统健康状态（PG-backed）。"""
    try:
        result = await _dispatch_query_audit_logs(page=1, page_size=1)
        return {"status": "ok", "total_records": result.get("total", 0), "backend": "postgresql"}
    except Exception as e:
        return {"status": "degraded", "error": str(e)}
