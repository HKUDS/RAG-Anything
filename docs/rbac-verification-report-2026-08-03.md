# 五级 RBAC 分级隔离验证报告（2026-08-03）

## 1. 元信息

| 项目 | 值 |
|---|---|
| 验证日期 | 2026-08-03（Asia/Shanghai） |
| 分支 | `feature/custom-enhancements`（工作区含大量任务前既有未提交改动，本次不提交） |
| 范围 | 后端权限隔离 + 前端按权限显示，五角色：super_admin / dept_admin / teacher / assistant / student |
| 方法 | 双专家静态审计 → OpenSpec 提案（2 专家评审）→ 执行修复（2 专家）→ 代码审查（1 专家）→ 运行时五角色 API 矩阵复验 |
| 权限事实源 | `raganything/permissions.py`（`DEFAULT_ROLES`），前端显示基准 = 该矩阵 |
| 运行环境 | 本地 PG 5432、后端 8001（当前工作区代码，`/api/health` 200）、前端 5173 |

## 2. 结论摘要

- **后端隔离主体正确**：逐端点守卫清单（`routers/*.py`）与五角色权限矩阵一致，未发现新越权面；修复前确认的高危越权点（dept_admin 可创建/提升 super_admin、`/upload/folder` 任意目录读取）已修复并通过运行时复验。
- **前端显示与后端权限一致**：静态审计 + 前端门控实现（用户/知识库/工作流/汽修/会话五类页面）逐项与后端守卫对应，前端不会对低权限角色暴露会返回 403 的写操作入口。
- **运行时矩阵复验 24/24 通过**：越权创建/提升 super_admin=403、`workflows/models` student=403、学生可使用系统智能体会话且跨用户会话仍 403、vision-settings 读守卫=200、`/upload/folder` 越界=403、PG 模式删除 KB=200（修复前 500）。
- **修复共 8 类**（见 §4），OpenSpec change `harden-rbac-isolation` 20/20 任务完成且 `openspec validate` 通过。
- **残留风险**：通用 `/ws` 进度推送仍向所有连接者广播（无按用户过滤，中危）、最后一名 super_admin 可被删除（低危）、student 汽修问答后端仍要求 `autorepair:write`（产品决策，前端已门控）、前端 `AuthContext` 权限快照可能陈旧（重新登录刷新）。

## 3. 审计发现与风险分级（修复前基线）

双专家静态审计详见 `docs/rbac-audit-backend.md` 与 `docs/rbac-audit-frontend.md`。

| 编号 | 风险 | 级别 | 处置 |
|---|---|---|---|
| C-1 | `POST/PUT /admin/users*` 仅要求 `users:write`，dept_admin 可创建/提升 super_admin（运行时实证 200/201） | 高 | 已修复（等级约束） |
| D-1 | `POST /upload/folder` 接受任意 `folder_path`（本地任意文件读取面） | 高 | 已修复（目录白名单） |
| C-6 | `/ws/workflow-run/{run_id}` 可跨用户订阅运行状态 | 中 | 已修复（订阅前属主校验） |
| D-2 | workflow run 列表/详情无属主过滤，可读他人运行记录与最终输出 | 中 | 已修复（按 user_id 过滤，admin 放行） |
| D-3 | 大量 KB 读端点仅 `verify_kb_access` 而无 `kb:read`；`allowed_kbs` 从不注入，kb:read 形同虚设 | 中 | 记录为产品模型决策（严格私有模型），未改语义 |
| C-4 | `GET /kb/{kb}/vision-settings` 误用写守卫（有 kb:read 也 403） | 中 | 已修复（读写分离） |
| C-5 | `/autorepair/qa*`、`/fault-diagnosis*`、`/code/parse`、cases 写操作要求 `autorepair:write`，student 仅 `autorepair:read` | 中（可用性） | 前端门控（后端保持，产品决策） |
| C-2 | 会话端点需 `agent:write/delete`，student 无法使用智能体 | 中（可用性） | 已修复（降为 `agent:read`） |
| D-4 | DELETE /admin/users 无最后一名 super_admin 保护 | 低 | 保留为已知限制 |
| C-7/D-4~D-8 | 公开注册无邀请码、reprocess-multimodal 缺 KB 校验、下载 token 进日志、健康端点公开等 | 低 | 未纳入本次修复范围，记录备查 |
| C-8 | `pg_auth_repo.py` 硬编码角色矩阵与 `permissions.py` 重复（漂移风险） | 低 | 已修复（删除死代码 + 一致性测试） |

## 4. 修复清单与验证证据

### 4.1 角色分配等级约束（C-1，高）

- `raganything/permissions.py`：新增 `ROLE_ORDER`/`ROLE_RANK`/`can_assign_role()`（`target_rank >= actor_rank`，未知角色拒绝）。
- `raganything/services/pg_auth_repo.py`：`create_user`/`update_user` 增加 `actor_role_name` 参数并强制等级校验；`init_db` bootstrap 显式传 `super_admin` 豁免。
- `raganything/routers/auth.py`：`PermissionError -> 403`；防自降级逻辑保留。
- 前端 `frontend/src/utils/roleOrdering.js` + `UserRoleSelect/CreateUserModal/EditUserModal`：按操作者等级过滤可选角色，目标角色高于操作者时禁用且不提交 `role_id`。
- 验证：运行时 dept_admin 创建 super_admin=403、提升 super_admin=403、同级分配=200、降级分配=201；单元测试 `tests/test_role_assignment_guard.py`。

### 4.2 会话端点降级（C-2，中）

- `raganything/routers/agent.py`：`POST/PUT/DELETE /agents/{id}/conversations*` 降为 `AGENT_READ`（保留 agent+thread 双重所有权校验）；消息编辑 `PUT .../messages/{id}` 保持 `AGENT_WRITE`。
- 验证：student 对 owner_id=0 系统智能体 创建/重命名/删除会话均 200；对他人智能体创建会话 403。

### 4.3 工作流守卫与属主隔离（D-2/C-6，中）

- `raganything/routers/admin.py`：`GET /workflows/models` 增加 `WORKFLOW_READ`；run 列表/详情按 `user_id` 过滤（admin 放行）；`/ws/workflow-run/{run_id}` 订阅前校验运行属主。
- 验证：student `GET /workflows/models`=403，super=200；`tests/test_rbac_isolation_endpoints.py` 覆盖列表过滤与 WS 属主。

### 4.4 vision-settings 读写分离（C-4，中）

- `raganything/routers/knowledge.py`：GET 改用 `_verify_kb_vision_read_access`（KB 可见性 + `kb:read`），PUT 保持属主/`kb:write`。
- 验证：student 对不可见 default KB=403（可见性正确）；学生作为 KB 属主 GET=200、PUT=200。

### 4.5 `/upload/folder` 目录白名单（D-1，高）

- `raganything/routers/knowledge.py`：`folder_path` 经 `realpath` 归一化后必须位于 `FOLDER_UPLOAD_ROOTS`（默认 `uploads/` + `WORKING_DIR`）任一根内，越界 403；`.env.example` 补充配置说明。
- 验证：`folder_path=C:\Windows`=403；白名单内缺失目录=400（未触发 403，证明白名单通过）。

### 4.6 KB 删除 PG 模式修复（原 500）

- `raganything/services/kb_service.py`：`cleanup_kb_resources` 时序改为“文件收集 → 获取 per-KB 锁 → 删除标记 + begin_deletion → retire → 清理目录/上传/元数据/PG 行”，避免删除中状态重新加载存储导致 500。
- 验证：运行时创建临时 KB 后删除=200；另用该接口清理首轮复验残留的 10 个空 KB 全部 200；`tests/test_rbac_isolation_endpoints.py` 覆盖收集先于 begin_deletion 的顺序断言。

### 4.7 运行时角色种子一致性（C-8，低）

- `raganything/services/pg_auth_repo.py`：删除 L171-220 死代码硬编码矩阵，新增 `build_default_role_rows()` 从 `permissions.py` 派生；新增“运行时种子 == DEFAULT_ROLES”一致性测试（`tests/test_role_assignment_guard.py`）。

### 4.8 前端权限门控（对齐后端矩阵）

- 用户管理：删除按钮 `users:delete`、创建/编辑 `users:write`；角色下拉按操作者等级过滤。
- 知识库：创建/删除 `kb:write`/`kb:delete`；上传、文档删除/批量/重试、上传任务删除/重试/取消 `kb:write`（上传任务按钮补 `canWrite` 防御门控）；图谱编辑 `graph:write`。
- 工作流：新建/保存/运行/删除 `workflow:write`。
- 汽修三页 + AR-KB 选择器：QA/诊断/案例增改删与 AR-KB 创建按 `autorepair:write`/`kb:write` 隐藏或禁用并提示只读。
- 会话页：仅消息编辑按 `agent:write` 门控，会话按钮不隐藏（后端已降 `agent:read`）。
- 验证：前端单测 81 项通过（含新增 `UserRoleSelect.test.js` 8 项）。

## 5. 运行时矩阵复验结果

- 脚本：`rbac_matrix_verify.py`（临时脚本，位于 Codex 可视化目录，不进入仓库）。
- 结果：24/24 通过，证据 JSON 见 `rbac_matrix_out.json`（仅状态码与响应摘要，无凭据/用户数据）。
- 覆盖项（节选）：越权创建/提升 super_admin=403；同级/降级分配=200/201；`workflows/models` student=403/super=200；系统智能体会话 200/200/200；跨用户会话 403；vision-settings 读 403/200 与写 403/200；`autorepair/qa` student=403；`/upload/folder` 越界 403、白名单内 400；KB create/delete 200；用户列表 200/403；kb/list 200；agents 200；autorepair/cases assistant=403。

## 6. 测试基线

| 项 | 结果 |
|---|---|
| 新增 RBAC 测试（`test_rbac_isolation_endpoints.py` + `test_role_assignment_guard.py`） | 39 passed |
| 后端定向（`test_rbac.py`、`test_admin_users.py`、上述 2 项） | 70 passed |
| 受影响既有测试（`test_agent_isolation.py`、`test_auth.py`、`test_settings_compatibility_contracts.py`、`test_upload_tasks.py`、`test_admin_settings_monitor.py`） | 83 passed / 4 failed（任务前既有：`test_upload_tasks.py`x3、`test_reload_kb_clears_cache_and_logs_event`，经 `git blame` 确认 `retire` 调用来自 2026-07-31 提交，与本次无关）/ 6 skipped |
| 前端单测 `npm --prefix frontend run test:unit` | 81 passed / 0 failed |
| `py_compile`（本次改动 10 个 py 文件） | 全部通过 |
| `git diff --check` | 通过（仅 LF/CRLF 提示，来自既有改动文件） |
| Vite production build | 受环境权限阻塞（esbuild 需读取 frontend 父目录被沙箱拒绝；提权请求被审批基础设施拒绝），已记录待有权限环境复验 |
| OpenSpec | `harden-rbac-isolation` 20/20 任务完成，`openspec validate` 通过，状态 `all_done` |

## 7. 已知限制与决策性保留

1. 通用 `/ws` 进度推送仍跨用户（中）：`raganything/services/ws_service.py` 的 `ws_broadcast` 向所有连接者广播上传/进度事件（含 kb 名、文件名、task_id 等元数据），未按用户过滤；本次仅修复了 `/ws/workflow-run/{run_id}` 属主校验。彻底修复需按用户路由事件（较大重构），建议列为后续专项。
2. 最后一名 super_admin 保护缺失（低，D-4）：`DELETE /admin/users/{id}` 仍可删除最后一名 super_admin，仅防删自己；建议后续改为软删除并保留至少一名 super_admin。
3. student 汽修问答后端仍要求 `autorepair:write`（C-5）：前端已按 `autorepair:read` 对 student 隐藏 QA/诊断/案例写入口；后端保持写守卫属于产品决策，如需学生发起问答应调整 `DEFAULT_ROLES` 或端点守卫。
4. KB 共享/授权模型未改变（D-3）：`allowed_kbs` 仍不注入，非属主非 admin 一律 403，属严格私有模型；`kb:read` 权限字面含义与实现存在错位，建议产品侧明确后清理权限矩阵或补授权机制。
5. 前端 `AuthContext` 权限快照可能陈旧：登录后前端缓存的权限列表不会随服务端角色变更自动刷新，需重新登录；属既有设计，非本次引入。
6. `/upload/folder` 白名单存在极小 TOCTOU 窗口（评审 7 号）：文件收集与获取 per-KB 锁之间并发新增文件可能漏删，上传路径的删除门控兜底，可接受。
7. WS 属主校验依赖 PG `workflow_runs` 行：若 run 因 PG 写入失败落入 JSON 回退，属主也无法订阅（fail-closed，与 run 列表/详情 PG-only 行为一致；PG 为强制部署，影响低）。
8. Vite production build 未在本环境复验：前端单测与 esbuild 语法校验已通过，构建需在有权限环境重跑。

## 8. 后续建议

- 专项处理通用 `/ws` 按用户路由事件；补最后一名 super_admin 保护与用户软删除。
- 产品侧确认 student 汽修问答与 KB 共享授权模型，必要时调整 `DEFAULT_ROLES` 与 `verify_kb_access`。
- 在具备权限的环境复验 `npm --prefix frontend run build`，随后可归档 OpenSpec change `harden-rbac-isolation`（先同步主规格与 `PROJECT_SUMMARY.md`）。