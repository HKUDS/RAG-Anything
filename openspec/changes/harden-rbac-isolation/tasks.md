# Harden RBAC Isolation — Tasks

## 1. 后端角色分配等级限制

- [x] 1.1 `permissions.py` 增加 `ROLE_ORDER`/`ROLE_RANK` 与 `can_assign_role()`；补单测。
- [x] 1.2 `pg_auth_repo.create_user/update_user` 增加 `actor_role_name` 并强制等级校验；`routers/auth.py` 传入操作者角色；`init_db` bootstrap 显式传 `super_admin` 豁免（保证启动正常）。
- [x] 1.3 回归测试：dept_admin 创建/提升 super_admin 必须 403；同级/降级分配正常；bootstrap 启动不受影响。

## 2. 端点守卫修正

- [x] 2.1 `agent.py` 会话 POST/PUT/DELETE 降为 `AGENT_READ`（保留所有权校验）；消息编辑维持 `agent:write`；同步受影响的既有测试。
- [x] 2.2 `admin.py` `GET /workflows/models` 增加 `WORKFLOW_READ` 守卫。
- [x] 2.3 `knowledge.py` `GET /kb/{kb}/vision-settings` 改用 `kb:read` 读守卫（PUT 不变）。
- [x] 2.4 工作流 run 列表/详情按属主过滤（非管理员仅见自己的 run）；`/ws/workflow-run/{run_id}` 订阅前校验 run 属主。

## 3. 前端权限门控

- [x] 3.1 `UserRoleSelect/CreateUserModal/EditUserModal` 按操作者等级过滤可选角色（操作者角色由 AdminUsersPage 传 prop）；目标角色高于操作者时角色字段禁用且不提交；补前端单测。
- [x] 3.2 `AdminUsersPage` 删除按钮按 `users:delete`、创建/编辑按钮按 `users:write` 门控。
- [x] 3.3 `KnowledgePage` 创建/删除 KB 按 `kb:write`/`kb:delete` 门控；`KnowledgeDetailPage` 上传/文档删除/批量删除/文档重试/上传任务删除/重试/取消按 `kb:write`，图谱编辑按 `graph:write` 门控；视觉设置区写按钮按 `kb:write` 禁用（只读仍可见）。
- [x] 3.4 `WorkflowPage` 新建/保存/运行/删除按 `workflow:write` 门控。
- [x] 3.5 `AutoRepairAgentPage/AutoRepairKnowledgePage/AutoRepairKBSelector` 按 `autorepair:write`/`kb:write` 隐藏或禁用写操作并给出只读提示；`AutoRepairDashboardPage` 无写操作，仅核对。
- [x] 3.6 `AgentChatPage` 仅消息编辑按钮按 `agent:write` 门控；会话新建/重命名/删除不按写权限隐藏（后端已降 `agent:read`）。

## 4. 稳定性与一致性

- [x] 4.1 修复 KB 删除 500：`cleanup_kb_resources` 时序改为“文件收集 → begin_deletion → retire → 删目录”；验证 PG 模式删除（含文档 KB 与空 KB）返回 200。
- [x] 4.2 移除 `pg_auth_repo.py` 死代码角色矩阵；新增运行时种子 == `permissions.py` 一致性测试。
- [x] 4.3 `POST /upload/folder` 目录白名单校验（`realpath` 前缀检查，`FOLDER_UPLOAD_ROOTS` 默认 `uploads/`+`WORKING_DIR`）+ 越界 403 测试。

## 5. 验证与收尾

- [x] 5.1 后端定向 pytest、`py_compile`、`git diff --check`。
- [x] 5.2 前端 `npm --prefix frontend run test:unit` 与 Vite production build（如受环境权限阻塞则记录并复验）。
- [x] 5.3 重启后端后重跑五角色 API 矩阵：越权创建/提升 403、`workflows/models` student 403、student 可创建会话且跨用户会话仍 403、upload/folder 越界 403、PG 模式删除 KB 200。
- [x] 5.4 更新 PROJECT_SUMMARY.md 与验证报告。
