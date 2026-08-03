## Why

用户注册流程强制收集邮箱，但平台不存在任何邮件发送、验证码或找回功能，邮箱仅作为冗余的用户资料字段存储（`users.email TEXT UNIQUE NOT NULL`）。该字段同时渗透到登录/注册、管理端用户管理、个人设置、审计日志与 OpenSpec 契约中，增加表单负担与数据隐私面；登录流程本就不含邮箱（用户名+密码）。

## What Changes

- **BREAKING** `POST /api/auth/register` 请求体移除 `email`，仅需 `username` + `password`；注册默认仍分配 `student` 角色，密码复杂度校验不变。
- **BREAKING** 管理端 `POST /api/admin/users`、`PUT /api/admin/users/{id}`、`PUT /api/auth/me/profile` 请求体移除 `email`；`GET /api/auth/me`、用户列表/详情响应不再包含 `email` 字段。
- 管理端用户搜索仅按用户名匹配；user.create/user.delete 审计详情不再记录邮箱。
- **BREAKING** 新增数据库迁移 `migrations/025_remove_user_email.sql` 删除 `users.email` 列（PG 随列自动删除 `idx_users_email` 索引）；历史邮箱数据不可恢复。
- 删除 `DEFAULT_ADMIN_EMAIL` 环境变量及默认管理员邮箱；`.env.example` 同步移除。
- 前端注册页、创建/编辑用户弹窗、用户列表、个人设置账户资料、审计日志字段映射全部移除邮箱输入与展示。
- 运维脚本同步去邮箱：`scripts/kb_regression_suite.py`（创建用户载荷）、`scripts/reset_system.py`（preflight 查询与报告）、`scripts/migrate_sqlite_to_pg.py`（读/写列）。
- `utils/security.py` 的日志 EMAIL 脱敏规则保留（守护历史日志中的既有邮箱，非本次功能代码）。

## Capabilities

### New Capabilities
<!-- 无新增能力 -->

### Modified Capabilities
- `admin-user-crud`: 创建用户请求/响应移除 email、删除“重复 email”冲突场景、搜索仅按用户名匹配
- `user-audit-logging`: user.create/user.delete 审计详情不再包含 email
- `user-settings-resolution`: `/api/auth/me` 不再返回 masked email；profile 更新仅支持用户名

## Impact

- 后端：`raganything/routers/auth.py`、`raganything/services/auth.py`、`raganything/services/pg_auth_repo.py`
- 数据库：`migrations/025_remove_user_email.sql`（删除 `users.email` 列与索引）
- 前端：`RegisterPage.jsx`、`AuthContext.jsx`、`CreateUserModal.jsx`、`EditUserModal.jsx`、`AdminUsersPage.jsx`、`PreferencesPage.jsx`、`AdminAuditLogsPage.jsx`
- 脚本：`scripts/kb_regression_suite.py`、`scripts/reset_system.py`、`scripts/migrate_sqlite_to_pg.py`
- 配置与文档：`.env.example`、`CHANGELOG.md`
- 测试：`tests/test_auth.py`、`tests/test_settings_compatibility_contracts.py`、`tests/test_kb_regression_suite.py`
- 明确不改：`utils/security.py` EMAIL 日志脱敏规则（有意保留）；历史说明书（`RAG-Anything技术方案与功能参数说明书.md`、`RAG-Anything已实现功能说明书.md`）属历史材料保留原样；`config/manufacturing.yaml` 的 `alert_channels: ["email","webhook"]` 是告警渠道名，与用户邮箱系统无关。
