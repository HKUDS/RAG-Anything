## 1. 数据库迁移与基础设施

- [x] 1.1 创建迁移脚本 `scripts/migrate_to_rbac.py`：建 `roles` 表 + 插入 3 个默认角色（admin/editor/viewer）
- [x] 1.2 迁移脚本：`users` 表新增 `role_id`、`last_login_at`、`must_change_password` 列
- [x] 1.3 迁移脚本：现有用户数据迁移（is_admin=1 → role=admin, is_admin=0 → role=viewer）
- [x] 1.4 迁移脚本：创建 `audit_logs` 表及索引（actor_id, action, created_at）
- [x] 1.5 迁移脚本：使用事务包裹，失败自动回滚；输出迁移结果统计

## 2. RBAC 权限系统

- [x] 2.1 创建 `raganything/permissions.py`：定义 Permission 类（权限常量字符串）和 DEFAULT_ROLES 字典
- [x] 2.2 扩展 `raganything/services/auth.py` 用户模型：新增 `get_role()`, `has_permission()`, `is_admin` property（向后兼容）
- [x] 2.3 创建 `require_permission(permission: str)` FastAPI 依赖到 `raganything/dependencies.py`
- [x] 2.4 添加 `GET /api/admin/roles` 端点（返回角色列表）
- [x] 2.5 替换 `routers/auth.py` 中 `get_admin_user()` 为 `require_permission()` 具体权限
- [x] 2.6 替换 `routers/admin.py` 中 `is_admin` 检查 — 通过 get_current_user 向后兼容派生 is_admin
- [x] 2.7 替换 `routers/knowledge.py`、`routers/agent.py`、`routers/query.py` 中的 admin 检查 — 向后兼容
- [x] 2.8 合并 `routers/auth.py` 与 `dependencies.py` 中重复的 `get_current_user`/`get_admin_user` 定义

## 3. 管理员用户 CRUD API

- [x] 3.1 实现 `POST /api/admin/users` — 创建用户（含密码校验、初始角色分配、must_change_password 标记）
- [x] 3.2 重构 `GET /api/admin/users` — 添加分页（page/page_size）、搜索（search）、筛选（role/status）参数
- [x] 3.3 实现 `GET /api/admin/users/{id}` — 用户详情（含 role 对象、last_login_at）
- [x] 3.4 扩展 `PUT /api/admin/users/{id}` — 支持 role_id 修改、防自降级保护
- [x] 3.5 保持 `DELETE /api/admin/users/{id}` — 防自删保护、级联处理关联数据
- [x] 3.6 所有用户管理操作集成审计日志记录

## 4. 密码策略与 Token 管理

- [x] 4.1 创建 `raganything/services/token_blacklist.py`：TokenBlacklist 类（内存集合 + 惰性清理）
- [x] 4.2 JWT payload 增加 `jti` (UUID4) 字段（`services/auth.py` 的 `create_token` 函数）
- [x] 4.3 `get_current_user` 依赖增加 JTI 黑名单校验
- [x] 4.4 Logout 端点：将 Access Token JTI 加入黑名单 + Refresh Token 撤销
- [x] 4.5 Refresh Token 轮转：`POST /api/auth/refresh` 返回新 access + refresh token，撤销旧的 refresh token
- [x] 4.6 Refresh Token 重放检测：检测到已撤销的 refresh token 时撤销该用户全部 refresh token
- [x] 4.7 实现 `PUT /api/auth/me/password` — 用户修改密码端点
- [x] 4.8 `must_change_password` 强制修改中间件：标记用户访问受保护端点时返回 403 + PASSWORD_CHANGE_REQUIRED
- [x] 4.9 更新用户登录时设置 `last_login_at` 时间戳

## 5. 审计日志系统

- [x] 5.1 创建 `raganything/services/audit.py`：AuditLogger 类（异步后台线程写入）
- [x] 5.2 实现 `GET /api/admin/audit-logs` — 分页查询 + 按 actor_id/action 筛选
- [x] 5.3 审计日志端点权限保护（`require_permission("audit:read")`）

## 6. 前端升级

- [x] 6.1 创建通用 `Pagination` 组件（`frontend/src/components/Pagination.jsx`）
- [x] 6.2 重构 `AdminUsersPage.jsx`：添加搜索栏、角色/状态筛选下拉、创建用户按钮
- [x] 6.3 创建 `CreateUserModal.jsx`：创建用户表单（用户名/邮箱/密码/角色选择 + 实时密码强度指示器）
- [x] 6.4 创建 `EditUserModal.jsx`：编辑用户表单（角色选择/启用禁用/重置密码）
- [x] 6.5 `AdminUsersPage` 表格列扩展：角色徽标、状态开关、最后登录时间、"（我）"标识
- [x] 6.6 创建 `AdminAuditLogsPage.jsx`：审计日志查看页面（分页表格 + 操作类型/操作人筛选）
- [x] 6.7 更新 `App.jsx` 路由：添加 `/admin/audit-logs` 路由（adminOnly）
- [x] 6.8 更新 `RegisterPage.jsx`：前端密码复杂度实时校验（与后端规则一致）
- [x] 6.9 更新 `AuthContext.jsx`：user 对象增加 role 信息（含 permissions 数组）
- [x] 6.10 更新 `LoginPage.jsx`：处理 `PASSWORD_CHANGE_REQUIRED` 403 响应，引导用户修改密码

## 7. 安全加固

- [x] 7.1 移除 `.env` 中硬编码的 `JWT_SECRET` 默认值，改为启动时检测并强制环境变量/运行时生成
- [x] 7.2 确保所有用户管理端点有速率限制（创建用户 5/min，列表 30/min）

## 8. 测试

- [x] 8.1 创建 `tests/test_rbac.py`：角色创建、权限检查、角色切换、向后兼容 is_admin
- [x] 8.2 创建 `tests/test_admin_users.py`：用户 CRUD（创建/分页/搜索/筛选/更新/删除）、权限控制
- [x] 8.3 创建 `tests/test_audit.py`：审计日志写入、查询、筛选、权限保护、append-only
- [x] 8.4 扩展 `tests/test_auth.py`：密码复杂度测试、Token 黑名单、Refresh Token 轮转、重放检测
- [x] 8.5 运行全部测试：确认无回归 ✅ 45/45 通过

## 9. 清理与文档

- [x] 9.1 更新 CLAUDE.md 或项目 README：管理员用户管理功能说明
- [x] 9.2 标记 `is_admin` 字段为 deprecated（代码注释 + 响应字段标注）
