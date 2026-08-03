# Frontend Permission Gating (Delta)

## ADDED Requirements

### Requirement: 前端操作按角色权限矩阵门控
前端页面操作入口 SHALL 与后端权限矩阵一致：无对应写权限的角色不得看到或触发会返回 403 的写操作按钮。实现上操作入口按权限隐藏或禁用（二选一即可，测试断言任一状态），并在页面级给出只读提示。

#### Scenario: 无写权限角色查看写操作
- **WHEN** 当前用户角色缺少 `users:delete`、`users:write`、`kb:write`、`kb:delete`、`graph:write`、`agent:write`、`workflow:write` 或 `autorepair:write` 中任一权限
- **THEN** 对应删除/创建/编辑/运行/诊断等操作入口 SHALL 隐藏或禁用，页面 SHALL 显示只读提示，且不发起会 403 的请求

#### Scenario: 页面×元素×权限映射
- **WHEN** 审核前端权限显示
- **THEN** 以下映射 SHALL 成立：用户删除按钮→`users:delete`；用户创建/编辑按钮→`users:write`；KB 创建/删除→`kb:write`/`kb:delete`；上传、文档删除/批量删除/重试、上传任务删除/重试/取消→`kb:write`；图谱新增/编辑/删除→`graph:write`；工作流新建/保存/运行/删除→`workflow:write`；汽修 QA/诊断/案例新增/编辑/删除→`autorepair:write`；AR-KB 创建→`kb:write`；消息编辑→`agent:write`；会话新建/重命名/删除不按写权限隐藏（后端为 `agent:read`）

### Requirement: 角色分配下拉按操作者等级过滤
用户管理页的角色下拉 SHALL 仅展示不高于操作者等级的角色；目标角色高于操作者等级时，角色字段 SHALL 禁用且不得在未变更情况下提交该字段。

#### Scenario: 非 super_admin 操作者打开角色下拉
- **WHEN** 操作者可达用户管理页（具有 `users:read`）且角色非 `super_admin`
- **THEN** 角色下拉 SHALL 隐藏 `super_admin` 及高于操作者等级的角色

#### Scenario: 编辑高于自身等级的用户
- **WHEN** 操作者编辑目标角色高于自身等级的用户且未变更角色字段
- **THEN** 角色字段 SHALL 禁用，提交请求 SHALL 不携带 `role_id`
