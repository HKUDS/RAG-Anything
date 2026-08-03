## Why

五级 RBAC 分级隔离存在可证实缺口：`users:write` 允许 dept_admin 创建/提升 `super_admin`（越权提权），多个端点权限守卫缺失或过严，且前端多个页面未按角色门控操作入口，导致按钮可见但后端 403。此外 KB 删除在 PG 模式下必然 500（`cleanup_kb_resources` 删除中状态仍调用 `get_kb`），`POST /upload/folder` 可读取任意服务器目录。

## What Changes

- 角色分配等级限制：操作者只能分配不高于自身等级的角色（`super_admin > dept_admin > teacher > assistant > student`）；`init_db` bootstrap 创建默认管理员显式豁免；前端角色下拉同步过滤（目标角色高于操作者时禁用该字段）。
- 智能体会话端点（创建/重命名/删除会话）从 `agent:write/delete` 降为 `agent:read`（会话为用户私有使用资源，保留所有权校验）；仅消息编辑（`PUT .../messages/{id}`）维持 `agent:write` 并在前端按此门控。
- `GET /workflows/models` 增加 `workflow:read` 守卫。
- `GET /kb/{kb}/vision-settings` 守卫从写权限降为 `kb:read`（写端点保持 `kb:write` 或属主）。
- 工作流 run 列表/详情与 `/ws/workflow-run/{run_id}` 订阅按属主隔离（非管理员仅见/订阅自己的运行）。
- 前端按权限矩阵门控写操作：用户删除（`users:delete`）与创建/编辑（`users:write`）、知识库上传/创建/删除/图谱编辑（`kb:write`/`kb:delete`/`graph:write`）、工作流编辑/运行（`workflow:write`）、汽修 QA/诊断/案例 CRUD（`autorepair:write`）。
- 修复 KB 删除 500：`cleanup_kb_resources` 时序改为“文件收集 → begin_deletion → retire → 删目录”。
- 移除 `pg_auth_repo.py` 死代码硬编码角色矩阵，新增运行时角色种子与 `permissions.py` 一致性测试。
- `POST /upload/folder` 的 `folder_path` 限制在可配置 `FOLDER_UPLOAD_ROOTS` 白名单（默认 `uploads/` 与 `WORKING_DIR`），越界返回 403。

## Capabilities

### New Capabilities
- `frontend-permission-gating`: 前端页面/操作按五角色权限矩阵门控，按钮与后端 403 语义一致。

### Modified Capabilities
- `rbac-authorization`: 角色分配受等级约束；智能体会话端点归入 `agent:read` 使用语义；运行时角色种子与 `permissions.py` 一致性受测试守护。
- `admin-user-crud`: 创建/更新用户的角色必须不高于操作者等级；删除用户仍仅 `users:delete`。
- `kb-access-control`: `GET /kb/{kb}/vision-settings` 只需 `kb:read`；KB 删除流程在 PG 模式下可正常完成。
- `data-import-tools`: 服务端文件夹导入仅允许白名单根目录内的路径。
- `workflow-persistence`: 运行记录与实时订阅按属主隔离。

## Impact

后端：`raganything/permissions.py`、`routers/auth.py`、`routers/agent.py`、`routers/admin.py`、`routers/knowledge.py`、`services/pg_auth_repo.py`、`services/kb_service.py`。
前端：`UserRoleSelect.jsx`、`CreateUserModal.jsx`、`EditUserModal.jsx`、`AdminUsersPage.jsx`、`KnowledgePage.jsx`、`KnowledgeDetailPage.jsx`、`WorkflowPage.jsx`、`AutoRepairAgentPage.jsx`、`AutoRepairDashboardPage.jsx`、`AutoRepairKnowledgePage.jsx`、`AutoRepairKBSelector.jsx`、`AgentChatPage.jsx`。
测试：新增越权回归、权限守卫、角色种子一致性、文件夹白名单、KB 删除、前端门控测试；API 五角色矩阵复验。API 路径与响应结构不变；不涉及数据库迁移。
