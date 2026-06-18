## Why

当前用户管理系统采用简单的 admin/user 二值权限模型，无法满足多角色协作场景。管理员无法创建用户、缺少审计追踪、密码策略不一致、Token 无服务端失效机制等问题已构成安全与运维瓶颈。随着系统用户规模增长，亟需建立可扩展的 RBAC 权限体系与完善的用户生命周期管理。

## What Changes

- **RBAC 角色系统**：从 `is_admin` 二值字段升级为 role-based 模型，支持 admin / editor / viewer 三个内置角色，预留扩展点
- **管理员创建用户**：新增 `POST /api/admin/users` 端点，支持管理员直接创建用户（含初始密码强制修改标记）
- **用户列表增强**：添加分页、搜索（用户名/邮箱）、排序、按角色/状态筛选
- **密码策略统一**：前端注册表单与服务端密码复杂度规则一致（≥8 位，3/4 字符类）
- **Token 失效机制**：Logout 时服务端记录已撤销 Token（内存集合 + 定期清理），Refresh Token 轮转
- **用户管理审计日志**：记录管理员对用户的所有操作（创建/更新/删除/角色变更），含操作人、时间、IP、变更内容
- **前端用户管理升级**：新增创建用户对话框、分页控件、搜索栏、角色徽标、最后登录时间展示
- **安全加固**：JWT Secret 强制环境变量覆盖/运行时生成，移除 `.env` 中的硬编码默认值
- **依赖去重**：合并 `routers/auth.py` 与 `dependencies.py` 中的重复认证依赖定义

## Capabilities

### New Capabilities

- `admin-user-crud`: 管理员对用户的完整 CRUD 操作，含分页、搜索、筛选、排序
- `rbac-authorization`: 基于角色的访问控制，内置 admin/editor/viewer 角色，可扩展角色定义
- `user-audit-logging`: 用户管理操作的审计日志记录与查询
- `password-policy-enforcement`: 统一前后端密码复杂度策略与服务端 Token 管理

### Modified Capabilities

<!-- 无现有 capability 被修改 — 这是全新功能模块 -->

## Impact

- **数据库**：`auth.db` 新增 `roles` 表、`audit_logs` 表；`users` 表新增 `role_id`、`last_login_at`、`must_change_password` 字段；迁移脚本保持向后兼容
- **后端 API**：新增/修改 `raganything/routers/auth.py` 管理员端点；`raganything/dependencies.py` 扩展权限检查依赖；新增 `raganything/services/audit.py` 审计服务
- **前端**：重构 `AdminUsersPage.jsx`；新增 `CreateUserModal.jsx`、`UserSearchBar.jsx` 组件；`AuthContext.jsx` 扩展角色信息
- **安全**：`.env` 移除硬编码 JWT Secret；Logout 增加 Token 撤销逻辑；Refresh Token 轮转
- **测试**：新增 `tests/test_admin_users.py`、`tests/test_rbac.py`、`tests/test_audit.py`
