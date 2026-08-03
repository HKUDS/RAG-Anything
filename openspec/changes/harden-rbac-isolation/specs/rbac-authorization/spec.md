# RBAC Authorization (Delta)

> 注：主规格 `rbac-authorization` 仍含历史三角色（admin/editor/viewer）遗留描述，仅作迁移背景；本 delta 以五角色为准，后续独立清理主规格。

## MODIFIED Requirements

### Requirement: 角色分配等级约束
用户创建/更新的目标角色 SHALL 不高于操作者角色等级（`super_admin > dept_admin > teacher > assistant > student`）；`super_admin` 仅 `super_admin` 可分配。系统初始化 bootstrap 创建默认管理员不受此约束。

#### Scenario: dept_admin 尝试分配 super_admin
- **WHEN** 角色为 `dept_admin` 的操作者创建用户或修改用户角色为目标 `super_admin`
- **THEN** 服务端 SHALL 返回 403，且不写入任何变更

#### Scenario: 同级与降级分配
- **WHEN** 操作者分配不高于自身等级的角色（含同级）
- **THEN** 服务端 SHALL 允许并完成写入

### Requirement: 智能体会话为使用级资源
会话线程（创建/重命名/删除）SHALL 归入 `agent:read` 使用语义；`agent:write/delete` 仅约束智能体本体的创建/修改/删除以及消息编辑。

#### Scenario: student 创建会话
- **WHEN** 具有 `agent:read` 的用户（如 student）对可访问的智能体创建/重命名/删除自己的会话
- **THEN** 服务端 SHALL 允许（仍校验智能体与会话所有权）

### Requirement: 运行时角色种子一致性
启动时写入 `roles` 表的权限集合 SHALL 与 `raganything/permissions.py` 的 `DEFAULT_ROLES` 一致，且由一致性测试守护，防止重复定义漂移。

#### Scenario: 种子与常量漂移
- **WHEN** `pg_auth_repo` 的运行时种子与 `permissions.py` 的五角色权限集合不一致
- **THEN** 一致性测试 SHALL 失败
