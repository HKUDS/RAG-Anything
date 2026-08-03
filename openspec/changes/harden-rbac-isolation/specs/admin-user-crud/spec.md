# Admin User CRUD (Delta)

## MODIFIED Requirements

### Requirement: 用户删除权限
删除用户 SHALL 仅授予具有 `users:delete` 的角色（当前仅 `super_admin`）；前端删除按钮按该权限显示。

#### Scenario: dept_admin 删除用户
- **WHEN** 角色为 `dept_admin` 的操作者请求删除用户
- **THEN** 服务端 SHALL 返回 403，前端不展示删除入口

### Requirement: 用户创建/编辑入口门控
前端用户创建/编辑按钮 SHALL 按 `users:write` 显示；后端保持 `users:write` 守卫。

#### Scenario: 只读角色查看用户管理
- **WHEN** 用户具有 `users:read` 但无 `users:write`
- **THEN** 前端 SHALL 隐藏创建/编辑入口（当前无该组合角色，属防御性约束）
