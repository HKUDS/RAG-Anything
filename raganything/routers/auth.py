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
    get_user_by_id,
    get_user_by_username,
    get_user_role as _auth_get_user_role,
    list_users,
    record_failed_login,
    reset_failed_logins,
    update_user,
    verify_password,
    DB_PATH,
)
from raganything.services.token_blacklist import get_token_blacklist
from raganything.services.audit import get_audit_logger, query_audit_logs
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
    role_id: int = 3  # 默认 viewer


class AdminUpdateUserRequest(BaseModel):
    username: Optional[str] = None
    email: Optional[str] = None
    password: Optional[str] = None
    is_admin: Optional[int] = None   # deprecated, retained for backward compat
    is_active: Optional[int] = None
    role_id: Optional[int] = None


class RefreshRequest(BaseModel):
    refresh_token: str


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

    # 更新最后登录时间 (Task 4.9)
    import aiosqlite
    async with aiosqlite.connect(str(DB_PATH)) as db:
        await db.execute(
            "UPDATE users SET last_login_at = ? WHERE id = ?",
            (datetime.now().strftime("%Y-%m-%d %H:%M:%S"), user["id"]),
        )
        await db.commit()

    # Fetch role for embedding in JWT
    role = await _auth_get_user_role(user["id"])
    is_admin = role is not None and role.get("name") in ("super_admin", "admin")
    token = create_token(user["id"], user["username"], is_admin, role)
    refresh = create_refresh_token(user["id"], user["username"], is_admin, role)

    # 注册 refresh token 到 family
    import jwt as _pyjwt
    try:
        r_payload = _pyjwt.decode(refresh, options={"verify_signature": False})
        get_token_blacklist().register_refresh_family(r_payload.get("rfam", ""), r_payload.get("jti", ""))
    except Exception:
        pass

    return {
        "status": "ok",
        "access_token": token,
        "refresh_token": refresh,
        "user": {"id": user["id"], "username": user["username"], "is_admin": user.get("is_admin", False)},
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

    # 检查 refresh token 是否已被撤销（重放检测）
    jti = payload.get("jti")
    blacklist = get_token_blacklist()
    if jti and blacklist.is_revoked(jti):
        # 重放攻击检测：撤销该用户整个 refresh family
        rfam = payload.get("rfam", "")
        if rfam:
            blacklist.revoke_refresh_family(rfam)
        raise HTTPException(401, "Refresh Token 已被使用过，请重新登录")

    user = await get_user_by_id(payload["user_id"])
    if not user or not user.get("is_active"):
        raise HTTPException(401, "用户不存在或已禁用")

    # 撤销旧的 refresh token
    if jti:
        from datetime import timedelta as _td
        blacklist.revoke(jti, datetime.now(timezone.utc) + _td(days=30))

    # 颁发新 token 对（嵌入角色信息）
    role = await _auth_get_user_role(user["id"])
    is_admin = role is not None and role.get("name") in ("super_admin", "admin")
    token = create_token(user["id"], user["username"], is_admin, role)
    new_refresh = create_refresh_token(user["id"], user["username"], is_admin, role)

    # 注册新 refresh token（保持同一 family）
    import jwt as _pyjwt
    try:
        r_payload = _pyjwt.decode(new_refresh, options={"verify_signature": False})
        new_jti = r_payload.get("jti", "")
        rfam = payload.get("rfam", "")  # 使用原始 family
        if rfam and new_jti:
            blacklist.register_refresh_family(rfam, new_jti)
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
    return {
        "status": "ok",
        "user": {**current_user, "must_change_password": bool(must_change)},
    }


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
                    get_token_blacklist().revoke(jti, expires_at)
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
                    get_token_blacklist().revoke(
                        r_jti,
                        datetime.now(timezone.utc) + timedelta(days=30)
                    )
                if rfam:
                    get_token_blacklist().revoke_refresh_family(rfam)
        except Exception:
            pass

    return {"status": "ok"}


# ── Auth: Change Password ───────────────────────────────

@router.put("/auth/me/password")
@limiter.limit("5/minute")
async def change_password(
    request: Request,
    current_user: dict = Depends(get_current_user),
):
    """当前用户修改密码"""
    import aiosqlite
    import re as _re_pw

    # 从 body 解析（用原生 request 避免额外 pydantic model）
    body = await request.json()
    old_password = body.get("old_password", "")
    new_password = body.get("new_password", "")

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

    # 更新密码
    new_hash = pwd_context.hash(new_password)
    async with aiosqlite.connect(str(DB_PATH)) as db:
        await db.execute(
            "UPDATE users SET password_hash = ?, must_change_password = 0, updated_at = ? WHERE id = ?",
            (new_hash, datetime.now().strftime("%Y-%m-%d %H:%M:%S"), current_user["id"]),
        )
        await db.commit()

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
    import aiosqlite
    from raganything.services.auth import DB_PATH

    async with aiosqlite.connect(str(DB_PATH)) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute("SELECT * FROM roles ORDER BY id")
        rows = await cursor.fetchall()
        roles = []
        import json as _json
        for r in rows:
            role = dict(r)
            try:
                role["permissions"] = _json.loads(role.get("permissions", "[]"))
            except (_json.JSONDecodeError, TypeError):
                role["permissions"] = []
            roles.append(role)

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
    """管理员获取用户列表（分页、搜索、筛选）。无分页参数时返回全部用户（向后兼容）。"""
    import aiosqlite
    from raganything.services.auth import DB_PATH

    # 检查是否使用了分页参数
    has_pagination = page > 1 or page_size != 20 or search or role or status or (
        "page" in str(user)  # crude check, always paginate if called with params
    )

    # 构建查询
    where_clauses = []
    params_list = []

    if search:
        where_clauses.append("(u.username LIKE ? OR u.email LIKE ?)")
        params_list.extend([f"%{search}%", f"%{search}%"])

    if role:
        where_clauses.append("r.name = ?")
        params_list.append(role)

    if status == "active":
        where_clauses.append("u.is_active = 1")
    elif status == "inactive":
        where_clauses.append("u.is_active = 0")

    where_sql = " AND ".join(where_clauses)
    if where_sql:
        where_sql = " WHERE " + where_sql

    async with aiosqlite.connect(str(DB_PATH)) as db:
        db.row_factory = aiosqlite.Row

        # 计数
        count_sql = f"""
            SELECT COUNT(*) as cnt FROM users u
            LEFT JOIN roles r ON u.role_id = r.id
            {where_sql}
        """
        cursor = await db.execute(count_sql, params_list)
        total = (await cursor.fetchone())["cnt"]

        # 查询
        offset = (page - 1) * page_size
        query_sql = f"""
            SELECT u.*, r.name as role_name, r.permissions as role_permissions
            FROM users u
            LEFT JOIN roles r ON u.role_id = r.id
            {where_sql}
            ORDER BY u.id
            LIMIT ? OFFSET ?
        """
        cursor = await db.execute(query_sql, params_list + [page_size, offset])
        rows = await cursor.fetchall()

        users = []
        for r in rows:
            u = {k: r[k] for k in r.keys() if k != "password_hash"}
            # 向后兼容: is_admin 字段
            if "role_name" in u and u["role_name"] is not None:
                u["is_admin"] = (u["role_name"] in ("super_admin", "admin"))
            else:
                u["is_admin"] = bool(u.get("is_admin", 0))
            # 清理内部字段
            u.pop("role_permissions", None)
            users.append(u)

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
    import aiosqlite
    from raganything.services.auth import DB_PATH, pwd_context

    # 密码复杂度校验
    import re as _re_pw
    import sqlite3 as _sqlite3

    if len(req.password) < 8:
        raise HTTPException(422, "密码至少需要 8 位")
    if len(req.password) > 128:
        raise HTTPException(422, "密码不能超过 128 位")
    if len(req.username) < 2:
        raise HTTPException(422, "用户名至少需要 2 个字符")

    complexity = 0
    if _re_pw.search(r'[A-Z]', req.password):
        complexity += 1
    if _re_pw.search(r'[a-z]', req.password):
        complexity += 1
    if _re_pw.search(r'[0-9]', req.password):
        complexity += 1
    if _re_pw.search(r'[^A-Za-z0-9]', req.password):
        complexity += 1
    if complexity < 3:
        raise HTTPException(422, "密码需包含大写字母、小写字母、数字、特殊字符中的至少三类")

    # 验证角色存在
    async with aiosqlite.connect(str(DB_PATH)) as db:
        db.row_factory = aiosqlite.Row
        role_row = await (await db.execute(
            "SELECT id FROM roles WHERE id = ?", (req.role_id,)
        )).fetchone()
        if not role_row:
            raise HTTPException(400, "指定角色不存在")

        password_hash = pwd_context.hash(req.password)
        try:
            cursor = await db.execute(
                """INSERT INTO users (username, email, password_hash, role_id, must_change_password)
                   VALUES (?, ?, ?, ?, 1)""",
                (req.username.strip(), req.email.strip(), password_hash, req.role_id),
            )
            await db.commit()
            new_id = cursor.lastrowid
        except _sqlite3.IntegrityError as e:
            msg = str(e).lower()
            if "username" in msg:
                raise HTTPException(409, "用户名已被占用")
            elif "email" in msg:
                raise HTTPException(409, "邮箱已被占用")
            else:
                raise HTTPException(400, "创建失败，请重试")

    new_user = await get_user_by_id(new_id)

    # 审计日志 — 包含角色名称
    audit = get_audit_logger()
    # 解析角色名称
    role_name = "unknown"
    async with aiosqlite.connect(str(DB_PATH)) as _db:
        _db.row_factory = aiosqlite.Row
        _row = await (await _db.execute(
            "SELECT name FROM roles WHERE id = ?", (req.role_id,)
        )).fetchone()
        if _row:
            role_name = _row["name"]

    await audit.log(
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
    import aiosqlite
    from raganything.services.auth import DB_PATH

    async with aiosqlite.connect(str(DB_PATH)) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute("""
            SELECT u.*, r.name as role_name, r.permissions as role_permissions
            FROM users u
            LEFT JOIN roles r ON u.role_id = r.id
            WHERE u.id = ?
        """, (user_id,))
        row = await cursor.fetchone()
        if not row:
            raise HTTPException(404, "用户不存在")

        u = {k: row[k] for k in row.keys() if k != "password_hash"}
        u["is_admin"] = (u.get("role_name") in ("super_admin", "admin"))

        import json as _json
        perms_raw = u.pop("role_permissions", "[]")
        try:
            perms = _json.loads(perms_raw) if perms_raw else []
        except (_json.JSONDecodeError, TypeError):
            perms = []
        u["role"] = {"id": row["role_id"], "name": u.pop("role_name", None), "permissions": perms}

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

    # 兼容: is_admin → role_id 映射
    if "is_admin" in update_data:
        import aiosqlite
        from raganything.services.auth import DB_PATH
        is_admin_val = update_data.pop("is_admin")
        async with aiosqlite.connect(str(DB_PATH)) as db:
            db.row_factory = aiosqlite.Row
            role_name = "super_admin" if is_admin_val else "student"
            role_row = await (await db.execute(
                "SELECT id FROM roles WHERE name = ?", (role_name,)
            )).fetchone()
            if role_row:
                update_data["role_id"] = role_row["id"]

    # 防自降级
    if "role_id" in update_data and user_id == user["id"]:
        import aiosqlite
        from raganything.services.auth import DB_PATH
        async with aiosqlite.connect(str(DB_PATH)) as db:
            db.row_factory = aiosqlite.Row
            admin_role = await (await db.execute(
                "SELECT id FROM roles WHERE name IN ('super_admin', 'admin')"
            )).fetchone()
            if admin_role and update_data["role_id"] != admin_role["id"]:
                raise HTTPException(403, "不能取消自己的管理员权限")

    # 获取更新前的用户信息用于审计
    before_user = await get_user_by_id(user_id)

    try:
        updated = await update_user(user_id, update_data)
    except ValueError as e:
        raise HTTPException(400, str(e))

    if updated is None:
        raise HTTPException(404, "用户不存在")

    # 审计日志 — 角色变更时解析角色名称
    audit = get_audit_logger()
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
        import aiosqlite as _aio
        async with _aio.connect(str(DB_PATH)) as _db:
            _db.row_factory = _aio.Row
            # 解析变更前后的角色名称
            old_role_id = before_user.get("role_id") if before_user else None
            new_role_id = update_data["role_id"]
            for _rid, _key in [(old_role_id, "before_role_name"), (new_role_id, "after_role_name")]:
                if _rid:
                    _row = await (await _db.execute(
                        "SELECT name FROM roles WHERE id = ?", (_rid,)
                    )).fetchone()
                    if _row:
                        audit_details[_key] = _row["name"]
            # 同时记录操作人的角色
            actor_role = user.get("role", {}).get("name", "unknown")
            audit_details["actor_role"] = actor_role
        # _aio 连接在此退出上下文管理器时关闭

    await audit.log(
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

    # 审计日志
    audit = get_audit_logger()
    await audit.log(
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
    """管理员查询审计日志（分页 + 筛选）"""
    result = await query_audit_logs(
        str(DB_PATH),
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
    """检查审计日志子系统健康状态"""
    audit = get_audit_logger()
    return {"status": "ok", **audit.health_check()}
