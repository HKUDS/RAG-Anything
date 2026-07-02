## Context

当前认证系统使用 SQLite (`auth.db`)，用户表 `users` 仅有 `is_admin` 二值字段区分角色。认证服务在 `raganything/services/auth.py`，API 路由在 `raganything/routers/auth.py`，权限依赖在 `raganything/dependencies.py`。前端管理页面 `AdminUsersPage.jsx` 为单页列表，无分页/搜索/创建功能。

### 当前数据模型
```sql
-- users 表（现状）
CREATE TABLE users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT UNIQUE NOT NULL,
    email TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,
    is_admin INTEGER DEFAULT 0,        -- 将被 role_id 替代
    is_active INTEGER DEFAULT 1,
    failed_login_attempts INTEGER DEFAULT 0,
    locked_until TEXT DEFAULT NULL,
    created_at TEXT DEFAULT (datetime('now','localtime')),
    updated_at TEXT DEFAULT (datetime('now','localtime'))
);
```

### 约束
- SQLite 数据库，无计划迁移到 PostgreSQL
- 现有 API 契约需保持向后兼容
- 前端使用 React + Tailwind CSS，无 UI 框架
- 项目规模：中小型部署（预计 < 1000 用户）

## Goals / Non-Goals

**Goals:**
- 实现 RBAC 角色系统（admin / editor / viewer），权限细粒度可扩展
- 管理员可创建用户、搜索/筛选/分页用户列表
- 统一前后端密码策略
- 实现 Logout 时 Token 失效
- 用户管理操作审计日志
- 保持现有 API 向后兼容

**Non-Goals:**
- 用户自助注册邮箱验证（本次不做）
- 用户自助密码重置（本次不做）
- 组织/租户多级隔离
- OAuth2/SSO 第三方登录集成
- 数据库从 SQLite 迁移到 PostgreSQL
- 实时通知/WebSocket 推送

## Decisions

### Decision 1: RBAC 数据模型 — 角色表 + JSON 权限数组

**选择**：新增 `roles` 表，权限以 JSON 数组存储在 `roles.permissions` 字段中。

```sql
CREATE TABLE roles (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT UNIQUE NOT NULL,           -- 'admin', 'editor', 'viewer'
    description TEXT NOT NULL DEFAULT '',
    permissions TEXT NOT NULL DEFAULT '[]', -- JSON array: ["users:read","kb:write",...]
    created_at TEXT DEFAULT (datetime('now','localtime'))
);

-- users 表变更
ALTER TABLE users ADD COLUMN role_id INTEGER REFERENCES roles(id) DEFAULT NULL;
ALTER TABLE users ADD COLUMN last_login_at TEXT DEFAULT NULL;
ALTER TABLE users ADD COLUMN must_change_password INTEGER DEFAULT 0;
```

**权限常量定义**（`raganything/permissions.py`）：
```python
class Permission:
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

DEFAULT_ROLES = {
    "admin": {"description": "系统管理员", "permissions": [ALL]},
    "editor": {"description": "内容编辑", "permissions": [KB_READ/WRITE, AGENT_READ/WRITE, MONITOR_READ]},
    "viewer": {"description": "只读用户", "permissions": [KB_READ, AGENT_READ, MONITOR_READ]},
}
```

**替代方案**：
- ❌ 独立 `permissions` 表 + `role_permissions` 关联表：对当前规模过度设计，查询需多表 JOIN
- ❌ 在 users 表直接加多个 boolean 字段：扩展性差，每加权限需 ALTER TABLE
- ✅ JSON 数组方案：SQLite 原生支持 JSON 函数（`json_each`, `json_extract`），足够灵活且单表查询

**向后兼容**：迁移时将现有 `is_admin=1` 用户自动分配 `admin` 角色，`is_admin=0` 分配 `viewer` 角色。`is_admin` 字段保留但标记 deprecated，通过 property 代理到 `role.name == 'admin'`。

### Decision 2: API 设计

**新增端点**：

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/admin/users` | 创建用户 |
| GET | `/api/admin/users?page=1&size=20&search=&role=&status=` | 分页用户列表 |
| GET | `/api/admin/users/{id}` | 用户详情 |
| PUT | `/api/admin/users/{id}` | 更新用户（扩展支持 role_id） |
| DELETE | `/api/admin/users/{id}` | 删除用户 |
| GET | `/api/admin/roles` | 角色列表 |
| GET | `/api/admin/audit-logs?page=1&size=20&user_id=&action=` | 审计日志 |
| POST | `/api/auth/logout` | 增强：记录 Token 到黑名单 |

**分页响应格式**：
```json
{
  "users": [...],
  "total": 42,
  "page": 1,
  "page_size": 20,
  "total_pages": 3
}
```

**向后兼容**：现有 `GET /api/admin/users`（无参数）仍返回全部用户列表，带分页参数时启用分页。`PUT /api/admin/users/{id}` 接受的字段向后兼容，新增 `role_id` 可选。

### Decision 3: Token 撤销机制

**选择**：内存集合 + JWT ID (jti) 黑名单。

```python
# raganything/services/token_blacklist.py
from threading import Lock
from datetime import datetime, timezone

class TokenBlacklist:
    def __init__(self):
        self._blacklist: dict[str, datetime] = {}  # jti -> expiry
        self._lock = Lock()
    
    def revoke(self, jti: str, expires_at: datetime):
        with self._lock:
            self._blacklist[jti] = expires_at
            self._cleanup()
    
    def is_revoked(self, jti: str) -> bool:
        with self._lock:
            self._cleanup()
            return jti in self._blacklist
    
    def _cleanup(self):
        now = datetime.now(timezone.utc)
        expired = [jti for jti, exp in self._blacklist.items() if exp < now]
        for jti in expired:
            del self._blacklist[jti]
```

- JWT payload 增加 `jti` (UUID4) 字段
- Logout 时将 access token 的 jti 加入黑名单，过期时间设为 token 本身的 exp
- 每次请求在 `get_current_user` 依赖中校验 jti 是否在黑名单
- 定期清理（每次 revoke/check 时惰性清理）
- Refresh Token 轮转：refresh 时同时撤销旧的 refresh token

**替代方案**：
- ❌ Redis 黑名单：引入外部依赖，对当前规模过度
- ❌ 数据库黑名单表：增加 SQLite 写入压力
- ✅ 内存集合：零依赖，Token 有效期短（24h），重启后黑名单自然清空（安全侧：重启后所有旧 Token 因 `sid` 变化已失效）

### Decision 4: 审计日志存储

**选择**：SQLite `audit_logs` 表，结构化 JSON details 字段。

```sql
CREATE TABLE audit_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    actor_id INTEGER NOT NULL REFERENCES users(id),
    action TEXT NOT NULL,                -- 'user.create', 'user.update', 'user.delete', 'user.role_change'
    target_user_id INTEGER REFERENCES users(id),
    details TEXT NOT NULL DEFAULT '{}',  -- JSON: {"changed_fields": {...}, "before": {...}, "after": {...}}
    ip_address TEXT DEFAULT NULL,
    created_at TEXT DEFAULT (datetime('now','localtime'))
);

CREATE INDEX idx_audit_actor ON audit_logs(actor_id);
CREATE INDEX idx_audit_action ON audit_logs(action);
CREATE INDEX idx_audit_created ON audit_logs(created_at);
```

- 通过 `raganything/services/audit.py` 的 `AuditLogger.log(action, actor, target, details, request)` 统一写入
- 管理员可通过 API 查询（分页 + 按操作人/操作类型筛选）
- 不实现自动清理策略（管理员手动管理）

### Decision 5: 前端架构

**组件树变更**：
```
AdminUsersPage
├── UserToolbar (搜索 + 角色筛选 + 状态筛选 + 创建按钮)
├── CreateUserModal (创建用户对话框)
├── EditUserModal (编辑用户对话框，复用现有内联编辑逻辑)
├── UserTable (分页表格)
│   └── UserRow (单行：用户名 / 邮箱 / 角色徽标 / 状态 / 最后登录 / 操作)
└── Pagination (通用分页组件)
```

- 使用 URL search params 持久化分页/搜索状态（`?page=1&search=foo&role=editor`）
- 通用 `Pagination` 组件可复用到审计日志页面
- Tailwind CSS 样式，保持与现有 UI 一致

### Decision 6: 密码策略统一

**统一规则**：≥8 位，≤128 位，必须包含以下 4 类中至少 3 类：
1. 大写字母 (A-Z)
2. 小写字母 (a-z)
3. 数字 (0-9)
4. 特殊字符 (!@#$%^&*()_+-=[]{}|;':",./<>?`~)

- 前端 `RegisterPage.jsx` 和 `CreateUserModal.jsx` 实时显示满足条件进度
- 后端 `auth.py` 保持现有 `_validate_password_complexity()` 逻辑
- 管理员创建用户时设置初始密码并标记 `must_change_password=True`

## Risks / Trade-offs

- **[Token 黑名单内存泄漏]** → 惰性清理 + Token 24h 短有效期 + 重启自动清空，风险可控
- **[SQLite 并发写入瓶颈]** → 审计日志异步写入（`threading.Thread` 后台写入），不阻塞主请求
- **[向后兼容风险]** → `is_admin` 字段保留，通过 property 映射到 role；旧 API 响应保持 `is_admin` 字段，新增 `role` 字段
- **[权限迁移遗漏]** → 现有所有 `is_admin` 检查点需逐个替换为 `has_permission()` 调用；使用 Grep 全量扫描确保不遗漏
- **[前端包大小]** → 新增组件均为轻量级，Pagination 组件 < 50 行，不引入新依赖

## Migration Plan

1. **数据库迁移**（`scripts/migrate_to_rbac.py`）：

   - 创建 `roles` 表，插入 3 个默认角色
   - `users` 表新增 `role_id`, `last_login_at`, `must_change_password` 列
   - 现有用户：`is_admin=1` → role_id=admin；`is_admin=0` → role_id=viewer
   - 创建 `audit_logs` 表及索引

2. **部署步骤**：
   - 停止服务 → 备份 `auth.db` → 运行迁移脚本 → 部署新代码 → 启动服务
   - 迁移脚本使用事务，失败自动回滚

3. **回滚策略**：
   - 恢复备份的 `auth.db` → 部署旧版本代码
   - `is_admin` 字段在迁移中不删除，回滚后旧代码可直接使用

## Open Questions

1. 是否需要支持用户在首次登录时修改初始密码的强制流程？（建议：是，本次实现）
2. 审计日志是否需要自动清理策略（如保留 90 天）？（建议：本次不做，后续迭代）
3. 是否需要支持自定义角色创建？（建议：本次不做，预留 `roles` 表的 CRUD 扩展点）
