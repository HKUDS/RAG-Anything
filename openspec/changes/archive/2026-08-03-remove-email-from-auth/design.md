# Design: 移除用户邮箱系统

## 目标与原则

全链路下线 `users.email`：请求/响应契约、管理端与个人设置 UI、审计详情、数据库列全部移除；保留登录行为（用户名+密码）与注册默认 `student` 角色；密码复杂度校验不变。破坏性接口变更同步更新 OpenSpec 规格与测试。`utils/security.py` 日志 EMAIL 脱敏规则保留（保护历史日志）。

## 后端

### raganything/routers/auth.py
- `AuthRegisterRequest` → `{username, password}`；`AdminCreateUserRequest` → `{username, password, role_id}`；`AdminUpdateUserRequest` 删除 `email`（保留 `is_admin` no-op 兼容字段）；`ProfileUpdateRequest` → `{username, current_password}`。
- 删除 `_masked_email()` 与所有调用：`register`（`create_user(req.username, req.password)`）、`me`（响应无 email）、`update_my_profile`（仅更新 username，审计 `fields: ["username"]`）、`admin_list_users`（搜索仅 username，docstring 同步）、`admin_create_user`（调用与审计 details 无 email，409 映射删除“邮箱已被占用”）、`admin_delete_user`（审计 details 无 email）。

### raganything/services/pg_auth_repo.py
- 删除 `DEFAULT_ADMIN_EMAIL` 常量与 env 读取；`init_db()` 默认管理员改调 `create_user(DEFAULT_ADMIN_USERNAME, DEFAULT_ADMIN_PASSWORD, ...)`。
- `create_user(username, password, role_id=None, must_change_password=False)`：INSERT 仅 `(username, password_hash, role_id, must_change_password)`；UniqueViolation 兜底仅查 username 冲突（“用户名已被占用”）；无 email 分支。
- `update_user`：`allowed_fields` 删除 `email`。
- 文件头表结构注释同步移除 email。

### raganything/services/auth.py
- 删除 `DEFAULT_ADMIN_EMAIL` 定义、`pg_auth_repo` 导入/再同步行。

### migrations/025_remove_user_email.sql
- `BEGIN; ALTER TABLE users DROP COLUMN IF EXISTS email; COMMIT;`（PG 自动删除 `idx_users_email`；历史邮箱数据不可恢复）。不改历史 `001_pg_schema.sql`；按仓库惯例由部署方手动 `psql` 执行。

## 前端

- `RegisterPage.jsx`：删除 email state/输入框/校验（含 `!email.includes('@')` 与“请填写所有字段”中的 email 条件）。
- `AuthContext.jsx`：`register(username, password)`，body 仅 `{username, password}`。
- `CreateUserModal.jsx`：删除 email state、校验、payload、输入框。
- `EditUserModal.jsx`：删除 email 表单字段、校验、初始化、dirty 比对、提交 payload。
- `AdminUsersPage.jsx`：删除邮箱表头与单元格 `{u.email}`；搜索占位改“搜索用户名...”。
- `PreferencesPage.jsx`：账户资料仅 username；删除 maskedEmail state、展示与“新邮箱”输入；描述文案改为仅用户名。
- `AdminAuditLogsPage.jsx`：`FIELD_MAP` 删除 `email: '邮箱'`。

## 脚本与配置

- `scripts/kb_regression_suite.py`：`DummyAdminApi.create_user(username, password, role_id)` 去 email 参数与 payload，两处调用（创建 student/teacher）去掉 `f"{username}@example.com"`。
- `scripts/reset_system.py`：`database_preflight()` 的 SELECT 去 `u.email` 列，admin 报告字典去 `"email"` 键。
- `scripts/migrate_sqlite_to_pg.py`：SQLite SELECT 与 PG INSERT 均移除 email 列/参数（历史邮箱不迁入新 schema）。
- `.env.example` 删除 `DEFAULT_ADMIN_EMAIL` 行；`CHANGELOG.md` 追加变更说明。

## 测试

- `tests/test_auth.py`：`create_user("test", "Ab1!")`（弱密码用例，行为不变）。
- `tests/test_settings_compatibility_contracts.py`：profile 更新契约改为无 email——payload 无 email、`update_user` 假实现无 email、断言 `fields == ["username"]`、响应无 email；保留“审计不含当前密码”断言。
- `tests/test_kb_regression_suite.py`：inline `DummyAdminApi.create_user(username, password, role_id)` 去 email 参数并更新调用处。

## 明确不改（已知残留）

- `utils/security.py` 的 EMAIL 日志脱敏规则：有意保留，守护历史日志。
- 历史说明书（`RAG-Anything技术方案与功能参数说明书.md`、`RAG-Anything已实现功能说明书.md`）中的 email 示例：历史材料，保留原样。
- `config/manufacturing.yaml` 的 `alert_channels: ["email","webhook"]`：告警渠道名，与用户邮箱系统无关。

## 验证

- 后端：改动文件 `py_compile`；定向 pytest（auth/settings/kb 相关）。
- 前端：单测（`frontend/src/utils/*.test.js`）与 Vite production build。
- 质量闸：`git diff --check`、`openspec validate`（严格）、项目总结检查。
- 验收（需真实后端与 PostgreSQL）：执行 025 迁移后，验证注册（无邮箱字段）、登录、管理端用户创建/编辑/搜索、个人设置、`/auth/me` 响应均无 email；`users` 表无 email 列。归档前用 `openspec archive` 同步三份主规格。
