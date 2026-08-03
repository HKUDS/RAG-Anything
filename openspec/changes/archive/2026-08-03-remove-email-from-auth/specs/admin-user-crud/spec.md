## MODIFIED Requirements

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
