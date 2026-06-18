# User Audit Logging

管理员对用户管理操作的审计日志记录、存储与查询。

## ADDED Requirements

### Requirement: Automatic audit log recording
系统 SHALL 在管理员执行用户管理操作（创建、更新、删除、角色变更）时自动记录审计日志。每条日志 MUST 包含：操作人 ID、操作类型、目标用户 ID、变更详情 JSON、IP 地址、时间戳。

#### Scenario: User creation logged
- **WHEN** 管理员成功创建新用户
- **THEN** 系统在 `audit_logs` 表中写入一条 `action='user.create'` 的记录，details 包含 `{username, email, role_id}`

#### Scenario: User update logged
- **WHEN** 管理员更新用户的角色或状态
- **THEN** 系统写入 `action='user.update'` 记录，details 包含 `{changed_fields: [...], before: {...}, after: {...}}`

#### Scenario: User deletion logged
- **WHEN** 管理员删除用户
- **THEN** 系统写入 `action='user.delete'` 记录，details 包含被删用户的 `{username, email, role}` 快照；target_user_id 设为被删用户 ID（保留引用信息）

#### Scenario: Role change specifically logged
- **WHEN** 管理员仅修改用户角色
- **THEN** 系统写入 `action='user.role_change'` 记录，details 包含 `{from_role, to_role}`

### Requirement: Audit log querying
系统 SHALL 提供 `GET /api/admin/audit-logs` 端点，支持分页查询和按 `actor_id`、`action` 类型筛选。仅具有 `audit:read` 权限的用户可访问。

#### Scenario: Query all audit logs
- **WHEN** 管理员调用 `GET /api/admin/audit-logs?page=1&page_size=20`
- **THEN** 系统返回分页的审计日志列表，按时间倒序排列

#### Scenario: Filter by action type
- **WHEN** 管理员调用 `GET /api/admin/audit-logs?action=user.delete`
- **THEN** 系统仅返回 `action='user.delete'` 的日志

#### Scenario: Filter by actor
- **WHEN** 管理员调用 `GET /api/admin/audit-logs?actor_id=1`
- **THEN** 系统仅返回该操作人产生的日志

#### Scenario: Non-admin cannot access audit logs
- **WHEN** 不具有 `audit:read` 权限的用户访问审计日志端点
- **THEN** 系统返回 403 Forbidden

### Requirement: Audit log is append-only
审计日志 SHALL 为追加写入，不支持修改或删除。系统 MUST NOT 提供修改或删除审计日志的 API 端点。

#### Scenario: No mutation endpoints for audit logs
- **WHEN** 任何人尝试 PUT/PATCH/DELETE 审计日志端点
- **THEN** 系统返回 405 Method Not Allowed
