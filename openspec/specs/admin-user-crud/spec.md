# Admin User CRUD

## Purpose
管理员对用户的完整 CRUD 操作能力，含分页、搜索、筛选、排序；用户账号仅由用户名与密码标识，不收集或存储邮箱。
## Requirements
### Requirement: Admin can create new users
系统 SHALL 提供 `POST /api/admin/users` 端点，允许管理员创建新用户。创建时 MUST 设置初始密码并标记 `must_change_password=True`。创建请求 MUST NOT 要求或接受 `email` 字段。

#### Scenario: Admin creates user successfully
- **WHEN** 管理员以有效 Token 调用 `POST /api/admin/users` 并提供 `username`, `password`, `role_id`
- **THEN** 系统创建用户并返回 201，响应包含 `id`, `username`, `role_id`, `must_change_password`（新用户为 1），且不包含 `email` 字段

#### Scenario: Non-admin cannot create users
- **WHEN** 非管理员用户调用 `POST /api/admin/users`
- **THEN** 系统返回 403 Forbidden

#### Scenario: Duplicate username
- **WHEN** 管理员创建用户时使用已存在的 `username`
- **THEN** 系统返回 409 Conflict，错误消息指明用户名冲突

#### Scenario: Weak password rejected
- **WHEN** 管理员创建用户时提供不符合复杂度要求的密码
- **THEN** 系统返回 422 Unprocessable Entity，错误消息说明密码要求

### Requirement: Admin can list users with pagination
系统 SHALL 提供分页用户列表端点 `GET /api/admin/users`，支持 `page`、`page_size`、`search`、`role`、`status` 查询参数。`search` 仅匹配 `username`，响应 MUST NOT 包含 `email` 字段。

#### Scenario: Paginated user list
- **WHEN** 管理员调用 `GET /api/admin/users?page=1&page_size=20`
- **THEN** 系统返回第一页 20 个用户，响应包含 `users` 数组、`total`、`page`、`page_size`、`total_pages`

#### Scenario: Search users by username
- **WHEN** 管理员调用 `GET /api/admin/users?search=john`
- **THEN** 系统返回用户名包含 "john" 的用户列表（大小写不敏感）

#### Scenario: Filter by role
- **WHEN** 管理员调用 `GET /api/admin/users?role=editor`
- **THEN** 系统仅返回角色为 "editor" 的用户

#### Scenario: Filter by status
- **WHEN** 管理员调用 `GET /api/admin/users?status=inactive`
- **THEN** 系统仅返回 `is_active=0` 的用户

### Requirement: Admin can view user details
系统 SHALL 提供 `GET /api/admin/users/{id}` 端点返回单个用户详细信息，包含角色、最后登录时间。

#### Scenario: View user detail
- **WHEN** 管理员调用 `GET /api/admin/users/{id}`
- **THEN** 系统返回用户完整信息（不含 password_hash），包含 `role` 对象和 `last_login_at`

#### Scenario: View non-existent user
- **WHEN** 管理员调用 `GET /api/admin/users/99999`
- **THEN** 系统返回 404 Not Found

### Requirement: Admin can update user
系统 SHALL 扩展 `PUT /api/admin/users/{id}` 端点支持修改 `role_id`、`is_active` 等字段。管理员 MUST NOT 取消自己的管理员角色。

#### Scenario: Change user role
- **WHEN** 管理员调用 `PUT /api/admin/users/{id}` 并设置 `role_id=2`（editor）
- **THEN** 系统更新用户角色为 editor 并返回 200

#### Scenario: Admin cannot demote themselves
- **WHEN** 管理员尝试修改自己的 `role_id` 为非管理员角色
- **THEN** 系统返回 403 Forbidden，错误消息 "Cannot change your own role"

#### Scenario: Disable user account
- **WHEN** 管理员调用 `PUT /api/admin/users/{id}` 并设置 `is_active=false`
- **THEN** 系统禁用该用户账号，该用户后续登录请求返回 403

### Requirement: Admin can delete user
系统 SHALL 保留 `DELETE /api/admin/users/{id}` 端点。管理员 MUST NOT 删除自己的账号。

#### Scenario: Delete user
- **WHEN** 管理员调用 `DELETE /api/admin/users/{id}`
- **THEN** 系统删除用户并返回 204 No Content，同时清理该用户的审计日志引用

#### Scenario: Admin cannot delete themselves
- **WHEN** 管理员尝试删除自己的账号
- **THEN** 系统返回 403 Forbidden
