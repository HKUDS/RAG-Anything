# RBAC Authorization

基于角色的访问控制（RBAC），替代现有的 `is_admin` 二值模型，支持可扩展的角色与权限定义。

## ADDED Requirements

### Requirement: System defines built-in roles with permissions
系统 SHALL 定义三个内置角色：admin（全部权限）、editor（读写内容）、viewer（只读）。每个角色 MUST 包含 permissions 数组。角色定义 SHALL 存储在 `roles` 表中。

#### Scenario: Read roles list
- **WHEN** 管理员调用 `GET /api/admin/roles`
- **THEN** 系统返回三个内置角色，每个角色包含 `id`, `name`, `description`, `permissions` 数组

#### Scenario: Admin has all permissions
- **WHEN** 查询 admin 角色的权限
- **THEN** admin 角色的 permissions 数组包含 `users:read`, `users:write`, `users:delete`, `kb:read`, `kb:write`, `kb:delete`, `agent:read`, `agent:write`, `agent:delete`, `settings:read`, `settings:write`, `audit:read`, `monitor:read`

#### Scenario: Editor has limited permissions
- **WHEN** 查询 editor 角色的权限
- **THEN** editor 角色的 permissions 数组包含 `kb:read`, `kb:write`, `agent:read`, `agent:write`, `monitor:read`

#### Scenario: Viewer has read-only permissions
- **WHEN** 查询 viewer 角色的权限
- **THEN** viewer 角色的 permissions 数组仅包含 `kb:read`, `agent:read`, `monitor:read`

### Requirement: Permission check dependency
系统 SHALL 提供 `require_permission(permission: str)` FastAPI 依赖，用于端点级别的权限校验。该校验 MUST 先认证用户身份，再检查用户角色是否包含所需权限。

#### Scenario: User has required permission
- **WHEN** 具有 `users:write` 权限的用户访问受 `require_permission("users:write")` 保护的端点
- **THEN** 请求正常处理

#### Scenario: User lacks required permission
- **WHEN** 不具有 `users:write` 权限的用户访问受 `require_permission("users:write")` 保护的端点
- **THEN** 系统返回 403 Forbidden，错误消息指明缺少的权限

#### Scenario: Unauthenticated access
- **WHEN** 未认证用户访问受 `require_permission` 保护的端点
- **THEN** 系统返回 401 Unauthorized

### Requirement: User-role association
每个用户 SHALL 关联一个角色（`role_id`）。创建用户时 MUST 指定角色。`is_admin` 字段 SHALL 保留为 deprecated，其值通过 `role.name == 'admin'` 动态派生。

#### Scenario: User object includes role info
- **WHEN** 调用 `GET /api/auth/me`
- **THEN** 响应中 user 对象包含 `role: {id, name, permissions}` 和 deprecated `is_admin: true/false`

#### Scenario: Backward compatible is_admin
- **WHEN** 现有代码读取 `user.is_admin` 字段
- **THEN** 该字段仍返回正确的布尔值（通过 property 从 role 派生）

### Requirement: Existing endpoints adopt RBAC
所有现有受 `get_admin_user()` 保护的端点 SHALL 迁移为使用 `require_permission()` 依赖，对应具体的权限常量。

#### Scenario: Admin endpoints require specific permissions
- **WHEN** 访问 `DELETE /api/admin/users/{id}` 端点
- **THEN** 系统要求调用者具有 `users:delete` 权限（而非简单地检查 is_admin）

#### Scenario: Knowledge base management requires kb permissions
- **WHEN** 访问知识库管理端点
- **THEN** 系统要求调用者具有对应的 `kb:read` / `kb:write` / `kb:delete` 权限
