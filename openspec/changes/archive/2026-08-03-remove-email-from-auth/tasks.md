## 1. OpenSpec 契约与配置文档

- [x] 1.1 校对工件一致性（proposal / delta specs / design / tasks 与实现计划一致）
- [x] 1.2 删除 `.env.example` 中的 `DEFAULT_ADMIN_EMAIL` 行
- [x] 1.3 `CHANGELOG.md` 追加邮箱移除变更说明

## 2. 后端实现

- [x] 2.1 `raganything/routers/auth.py`：四个 Pydantic 模型去 email、删除 `_masked_email`、register/me/update_my_profile/admin_list_users/admin_create_user/admin_delete_user 移除 email 出入参与审计字段
- [x] 2.2 `raganything/services/pg_auth_repo.py`：删除 `DEFAULT_ADMIN_EMAIL`、`create_user` 去 email 参数与重复检查、`update_user` allowed_fields 去 email、`init_db` 与文件头注释同步
- [x] 2.3 `raganything/services/auth.py`：删除 `DEFAULT_ADMIN_EMAIL` 定义与跨模块同步
- [x] 2.4 新增 `migrations/025_remove_user_email.sql`（DROP COLUMN email）

## 3. 前端实现

- [x] 3.1 `RegisterPage.jsx` 与 `AuthContext.jsx`：注册链路移除邮箱
- [x] 3.2 `CreateUserModal.jsx`、`EditUserModal.jsx`：管理端创建/编辑用户移除邮箱
- [x] 3.3 `AdminUsersPage.jsx`、`AdminAuditLogsPage.jsx`：用户列表/审计字段映射移除邮箱
- [x] 3.4 `PreferencesPage.jsx`：账户资料仅用户名，删除 masked email 展示

## 4. 脚本与测试更新

- [x] 4.1 `scripts/kb_regression_suite.py`（create_user 去 email 与两处调用）、`scripts/reset_system.py`（preflight 查询/报告去 email）、`scripts/migrate_sqlite_to_pg.py`（读写列去 email）
- [x] 4.2 更新 `tests/test_auth.py`、`tests/test_settings_compatibility_contracts.py`、`tests/test_kb_regression_suite.py`
- [x] 4.3 后端改动文件 `py_compile` + 定向 pytest 通过
- [x] 4.4 前端单测（72 项）与 7 个 JSX 文件 babel 解析通过；Vite build 受环境权限阻塞（同既有记录，部署环境复验）
- [x] 4.5 `git diff --check`、`openspec validate`（严格）、项目总结检查通过
- [x] 4.6 更新 `PROJECT_SUMMARY.md` 当前事实并追加近期任务记录

## 5. 验收与归档

- [x] 5.1 025 迁移已应用；后端（8010）全链路冒烟 13/13 通过：注册/登录/`/auth/me`/profile/管理端创建/搜索/更新/审计/清理均无 email，测试用户已清理
- [x] 5.2 总结已同步；`openspec archive` 已执行，三份主规格更新并归档为 `2026-08-03-remove-email-from-auth`
