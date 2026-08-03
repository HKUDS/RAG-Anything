## MODIFIED Requirements

### Requirement: Automatic audit log recording
系统 SHALL 在管理员执行用户管理操作（创建、更新、删除、角色变更）时自动记录审计日志。每条日志 MUST 包含：操作人 ID、操作类型、目标用户 ID、变更详情 JSON、IP 地址、时间戳。变更详情 MUST NOT 记录邮箱。

#### Scenario: User creation logged
- **WHEN** 管理员成功创建新用户
- **THEN** 系统在 `audit_logs` 表中写入一条 `action='user.create'` 的记录，details 包含 `{username, role_id}`，不包含 email

#### Scenario: User update logged
- **WHEN** 管理员更新用户的角色或状态
- **THEN** 系统写入 `action='user.update'` 记录，details 包含 `{changed_fields: [...], before: {...}, after: {...}}`

#### Scenario: User deletion logged
- **WHEN** 管理员删除用户
- **THEN** 系统写入 `action='user.delete'` 记录，details 包含被删用户的 `{username, role_id, actor_role}` 快照，不包含 email；target_user_id 设为被删用户 ID（保留引用信息）

#### Scenario: Role change specifically logged
- **WHEN** 管理员仅修改用户角色
- **THEN** 系统写入 `action='user.role_change'` 记录，details 包含 `{changed_fields, before_role_name, after_role_name, actor_role}`
