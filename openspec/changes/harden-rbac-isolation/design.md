## Context

五级 RBAC 以 `raganything/permissions.py` 为事实源，`require_permission()` 统一守卫后端端点。审计与运行时矩阵证实：dept_admin 可创建/提升 super_admin（200/201）；`GET /workflows/models` 对 student/assistant 返回 200；会话创建要求 `agent:write` 与学生 `agent:read` 冲突；`GET /kb/{kb}/vision-settings` 误用写守卫；前端汽修/工作流/用户管理/知识库页面未按权限门控；KB 删除在 PG 模式必然 500（`begin_deletion` 标记后 Step 6 收集文件仍调用 `get_kb` → `kb_query_deleting`）；`POST /upload/folder` 接受任意服务器路径。

## Goals / Non-Goals

**Goals:**
- 服务端角色分配受等级约束，杜绝低等级角色提权（含 bootstrap 正常启动）。
- 端点守卫与五角色权限矩阵一致（过严改 `agent:read`/`kb:read`，缺失补 `workflow:read`）。
- 前端可见/可操作范围与后端权限矩阵一致。
- KB 删除在 PG 模式可用；工作流运行按属主隔离；文件夹导入受限；角色种子一致性有测试守护。

**Non-Goals:**
- 不引入新权限常量或数据库迁移；不改变 API 路径与响应结构；不实现浏览器 E2E。
- 不改 `/ws` 通用推送的跨用户元数据广播（记录为已知限制）。
- 不做“最后一名 super_admin 保护”“student 是否可用汽修问答”的产品决策（记录为后续项）。
- 不修 `AuthContext` 刷新回退 localStorage 陈旧权限、`/knowledge` 路由未显式声明 `kb:read`（记录为已知限制，前者为防御性改进）。

## Decisions

- `permissions.py` 增加 `ROLE_ORDER`/`ROLE_RANK` 与 `can_assign_role(actor, target)`：`super_admin > dept_admin > teacher > assistant > student`，可分配等级 ≤ 自身。
- `pg_auth_repo.create_user/update_user` 增加 `actor_role_name` 参数并在服务层强制等级校验；`routers/auth.py` 传入操作者角色。`init_db` bootstrap 创建默认管理员时显式传 `actor_role_name="super_admin"` 豁免；`actor_role_name=None` 且指定 `role_id` 时拒绝（register 无 role_id，不受影响）。
- 会话端点 `POST/PUT/DELETE /agents/*/conversations*` 改为 `require_permission(AGENT_READ)`，保留智能体/会话所有权校验；`PUT .../messages/{id}` 维持 `agent:write`。
- `GET /workflows/models` 增加 `require_permission(WORKFLOW_READ)`。
- `GET /kb/{kb}/vision-settings` 使用 `_verify_kb_vision_read_access`（`verify_kb_access` + `kb:read`）；`PUT` 保持写守卫。
- 前端：`UserRoleSelect` 增加 `canAssignRole(actorRole, targetRole)` 过滤（操作者角色由 `AdminUsersPage` 经 prop 传入模态框）；目标角色高于操作者时角色字段禁用且不提交；删除按钮按 `users:delete`、创建/编辑按钮按 `users:write`；汽修/工作流/知识库/会话页按对应写权限隐藏或禁用操作并给出页面级只读提示。
- KB 删除修复：`cleanup_kb_resources` 完整时序为“锁与删除标记 → 取消查询/等待租约 → 清理 worker/队列/任务 → 收集文档与分块文件路径 → `begin_deletion` → retire → 删除目录/上传文件/元数据/PG 行”。不做“容忍 kb_query_deleting 返回空”备选（会漏删上传文件）。
- 工作流 run：`list_workflow_runs`/`get_workflow_run` 增加 `(user_id = $self OR is_admin)` 过滤；`/ws/workflow-run/{run_id}` 在订阅前校验 run 属主。
- `POST /upload/folder`：`folder_path` 经 `os.path.realpath` 归一化后必须位于白名单根（`FOLDER_UPLOAD_ROOTS`，默认 `uploads/` 与 `WORKING_DIR` 解析后的绝对路径）之内，越界返回 403。

## Risks / Trade-offs

- 会话端点降级为 `agent:read` 扩大可写面 → 以所有权校验兜底（仅本人会话），且会话为用户私有资源。
- 角色分配收紧可能影响既有管理流程 → 仅限制“分配高于自身等级”，同级可分配不受影响。
- 文件夹导入白名单限制任意路径 → 默认根为 `uploads/` 与 `WORKING_DIR`，运维可经 `FOLDER_UPLOAD_ROOTS` 扩充。
- KB 删除重排门控时序 → 收集阶段可能进入新查询，由 `_kbs_being_deleted` 集合与查询租约机制兜底。
