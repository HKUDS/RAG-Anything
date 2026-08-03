# RAG-Anything 后端 RBAC 隔离审计报告

- 审计类型：只读静态代码审计（未修改任何代码/配置/迁移文件）
- 审计日期：2026-08-03（Asia/Shanghai）
- 审计分支：feature/custom-enhancements（工作区含未提交改动）
- 审计范围：`raganything/permissions.py`、`raganything/dependencies.py`、`raganything/routers/*.py`、`raganything/services/pg_auth_repo.py`、`raganything/services/auth.py`、`migrations/001_pg_schema.sql`、`migrations/015_restore_5level_rbac.sql` 及相关辅助文件
- 权限事实源：`raganything/permissions.py` 的 `DEFAULT_ROLES`（五角色）
- 说明：本报告仅作静态核验，不含任何密钥、密码、令牌或真实用户数据。

---

## 1. 权限事实源（raganything/permissions.py → DEFAULT_ROLES）

角色缩写：SA=super_admin、DA=dept_admin、T=teacher、A=assistant、S=student。

| 权限 | SA | DA | T | A | S |
|---|---|---|---|---|---|
| users:read | ✓ | ✓ | – | – | – |
| users:write | ✓ | ✓ | – | – | – |
| users:delete | ✓ | – | – | – | – |
| kb:read | ✓ | ✓ | ✓ | ✓ | ✓ |
| kb:write | ✓ | ✓ | ✓ | ✓ | – |
| kb:delete | ✓ | ✓ | – | – | – |
| agent:read | ✓ | ✓ | ✓ | ✓ | ✓ |
| agent:write | ✓ | ✓ | ✓ | – | – |
| agent:delete | ✓ | ✓ | – | – | – |
| settings:read | ✓ | ✓ | – | – | – |
| settings:write | ✓ | – | – | – | – |
| audit:read | ✓ | ✓ | – | – | – |
| monitor:read | ✓ | ✓ | ✓ | ✓ | – |
| analytics:read | ✓ | ✓ | ✓ | – | – |
| workflow:read | ✓ | ✓ | ✓ | – | – |
| workflow:write | ✓ | ✓ | – | – | – |
| graph:read | ✓ | ✓ | ✓ | ✓ | ✓ |
| graph:write | ✓ | ✓ | ✓ | ✓ | – |
| autorepair:read | ✓ | ✓ | ✓ | ✓ | ✓ |
| autorepair:write | ✓ | ✓ | ✓ | – | – |

说明：`has_permission()`（`pg_auth_repo.py:549`）对 `super_admin` 动态放行全部权限（不依赖 roles 表 JSON）；运行时 `init_db()`（`pg_auth_repo.py:157`）每次启动以 `DEFAULT_ROLES` 对 roles 表做 `ON CONFLICT DO UPDATE`，确保 DB 与权限事实源一致。

---

## 2. 路由 × 权限守卫矩阵

路由前缀统一为 `/api`（`server.py` include_router）。守卫方式中：
- `P(权限)` = `require_permission(Permission.xxx)`；
- `U` = `get_current_user`（仅登录）；
- `U?` = `get_optional_user`（匿名可过，端点内再校验）；
- `KB` = `verify_kb_access`（登录 + 管理员或 KB 属主，见 §4 说明）；
- 所有权 = 端点内对 agent/kb/thread 的 owner_id 校验；
- “公开” = 无任何认证/权限守卫。
- 期望 200 集合为“仅凭守卫与权限模型即可 200”的角色；KB/Agent 端点还需满足所有权条件，已单独标注。

### 2.1 routers/auth.py

| Method | Path | 守卫 | 期望 200 | 期望 403 |
|---|---|---|---|---|
| POST | /api/auth/register | 公开（限流 5/min） | 所有人（注册 student） | – |
| POST | /api/auth/login | 公开（限流 10/min） | 所有人 | – |
| POST | /api/auth/refresh | 公开（限流 10/min） | 持有效 refresh token | – |
| GET | /api/auth/me | U | 任意登录用户 | 未登录 401 |
| PUT | /api/auth/me/profile | U（限流 5/min） | 任意登录用户 | – |
| POST | /api/auth/logout | U | 任意登录用户 | – |
| PUT | /api/auth/me/password | U（限流 5/min） | 任意登录用户 | – |
| GET | /api/auth/check-password-status | U | 任意登录用户 | – |
| GET | /api/admin/roles | P(users:read) | SA、DA | T/A/S |
| GET | /api/admin/users | P(users:read)（限流 30/min） | SA、DA | T/A/S |
| POST | /api/admin/users | P(users:write)（限流 5/min） | SA、DA | T/A/S |
| GET | /api/admin/users/{user_id} | P(users:read) | SA、DA | T/A/S |
| PUT | /api/admin/users/{user_id} | P(users:write) | SA、DA | T/A/S |
| DELETE | /api/admin/users/{user_id} | P(users:delete) | SA | DA/T/A/S |
| GET | /api/admin/audit-logs | P(audit:read)（限流 30/min） | SA、DA | T/A/S |
| GET | /api/admin/health/audit | P(audit:read)（限流 30/min） | SA、DA | T/A/S |

### 2.2 routers/admin.py

| Method | Path | 守卫 | 期望 200 | 期望 403 |
|---|---|---|---|---|
| GET | /api/workflows | P(workflow:read) | SA、DA、T | A、S |
| GET | /api/workflows/files | P(workflow:read) | SA、DA、T | A、S |
| POST | /api/workflows/upload | P(workflow:write) | SA、DA | T/A/S |
| GET | /api/workflows/models | U（无权限校验） | 任意登录用户 | – |
| GET | /api/workflows/{workflow_id} | P(workflow:read) | SA、DA、T | A、S |
| POST | /api/workflows | P(workflow:write) | SA、DA | T/A/S |
| PUT | /api/workflows/{workflow_id} | P(workflow:write) | SA、DA | T/A/S |
| DELETE | /api/workflows/{workflow_id} | P(workflow:write) | SA、DA | T/A/S |
| POST | /api/workflows/{workflow_id}/run | P(workflow:write) | SA、DA | T/A/S |
| GET | /api/workflows/{workflow_id}/runs | P(workflow:read) | SA、DA、T | A、S |
| GET | /api/workflows/{workflow_id}/runs/{run_id} | P(workflow:read)（无属主过滤） | SA、DA、T | A、S |
| WS | /api/ws/workflow-run/{run_id} | WS token 鉴权 + P(workflow:read) | SA、DA、T | A、S（关闭 4001） |
| WS | /api/ws | WS token 鉴权（仅登录，无权限） | 任意登录用户 | 未登录 4001 |
| GET | /api/settings | P(settings:read) | SA、DA | T/A/S |
| PUT | /api/settings | P(settings:write)（实现返回 410 已废弃） | SA | DA/T/A/S |
| POST | /api/settings/reset | P(settings:write)（实现返回 410 已废弃） | SA | DA/T/A/S |
| POST | /api/reload-kb/{kb_name} | P(settings:write) | SA | DA/T/A/S |
| GET | /api/cache/stats | P(monitor:read) | SA、DA、T、A | S |
| POST | /api/cache/evict/{kb_name} | P(settings:write) | SA | DA/T/A/S |
| POST | /api/cache/pin/{kb_name} | P(settings:write) | SA | DA/T/A/S |
| POST | /api/cache/unpin/{kb_name} | P(settings:write) | SA | DA/T/A/S |
| GET | /api/monitor/status | P(monitor:read) | SA、DA、T、A | S |
| GET | /api/monitor/stats | P(monitor:read) | SA、DA、T、A | S |
| GET | /api/monitor/logs | P(monitor:read) | SA、DA、T、A | S |
| GET | /api/health/vision-embedding | P(settings:read) | SA、DA | T/A/S |
| GET | /api/health | 公开 | 所有人 | – |

### 2.3 routers/agent.py（Agent 端点均叠加“所有权”校验：仅 agent 属主或 super_admin；owner_id=0 的系统智能体对所有登录用户开放读）

| Method | Path | 守卫 | 期望 200 | 期望 403 |
|---|---|---|---|---|
| GET | /api/agents | P(agent:read) + 属主过滤 | SA、DA、T、A、S（各自可见范围） | – |
| GET | /api/agents/templates | P(agent:read) | SA、DA、T、A、S | – |
| POST | /api/agents | P(agent:write) + verify_kb_access | SA、DA、T | A、S |
| PUT | /api/agents/{agent_id} | P(agent:write) + 所有权 | SA、DA、T（属主） | 非属主 T、A、S |
| DELETE | /api/agents/{agent_id} | P(agent:delete) + 所有权 | SA、DA（属主） | T（属主也无 agent:delete）、A、S |
| GET | /api/agents/{agent_id}/conversations | P(agent:read) + 所有权 | SA、属主（DA/T/A/S 若为属主） | 非属主 |
| GET | /api/agents/{agent_id}/conversations/{thread_id} | P(agent:read) + Agent/Thread 所有权 | SA、属主 | 非属主 |
| POST | /api/agents/{agent_id}/conversations | P(agent:write) + Agent 所有权 | SA、属主（DA/T） | 非属主 A/S、S 全员 |
| PUT | /api/agents/{agent_id}/conversations/{thread_id} | P(agent:write) + 所有权 | SA、属主（DA/T） | A、S、非属主 |
| DELETE | /api/agents/{agent_id}/conversations/{thread_id} | P(agent:delete) + 所有权 | SA、属主（DA） | T/A/S、非属主 |
| PUT | /api/agents/{agent_id}/conversations/{thread_id}/messages/{message_id} | P(agent:write) + 所有权 | SA、属主（DA/T） | A、S、非属主 |
| POST | /api/agents/{agent_id}/query/stream | P(agent:read) + Agent 所有权 | SA、属主、系统智能体(owner_id=0)的所有登录用户 | 非属主的私有 Agent（含 S） |

### 2.4 routers/autorepair.py

| Method | Path | 守卫 | 期望 200 | 期望 403 |
|---|---|---|---|---|
| GET | /api/autorepair/knowledge-graph/summary|nodes|edges|nodes/{id}|lineage | P(autorepair:read) | SA、DA、T、A、S | – |
| GET | /api/autorepair/cases/search|stats|categories|{case_id} | P(autorepair:read) | SA、DA、T、A、S | – |
| POST | /api/autorepair/cases | P(autorepair:write) | SA、DA、T | A、S |
| PUT | /api/autorepair/cases/{case_id} | P(autorepair:write) | SA、DA、T | A、S |
| DELETE | /api/autorepair/cases/{case_id} | P(autorepair:write) | SA、DA、T | A、S |
| GET | /api/autorepair/process-library/search|categories|documents/{doc_id} | P(autorepair:read) | SA、DA、T、A、S | – |
| GET | /api/autorepair/fault-cases/search|stats | P(autorepair:read) | SA、DA、T、A、S | – |
| POST | /api/autorepair/code/parse | P(autorepair:write) | SA、DA、T | A、S |
| GET | /api/autorepair/dashboard | P(autorepair:read) | SA、DA、T、A、S | – |
| GET | /api/autorepair/institutions | P(autorepair:read) | SA、DA、T、A、S | – |
| POST | /api/autorepair/qa | P(autorepair:write) | SA、DA、T | A、S |
| POST | /api/autorepair/qa/stream | P(autorepair:write) | SA、DA、T | A、S |
| POST | /api/autorepair/fault-diagnosis | P(autorepair:write) | SA、DA、T | A、S |
| POST | /api/autorepair/fault-diagnosis/continue | P(autorepair:write) | SA、DA、T | A、S |
| GET | /api/autorepair/kb-list | P(autorepair:read) | SA、DA、T、A、S | – |
| GET | /api/autorepair/health | 公开 | 所有人 | – |

### 2.5 routers/knowledge.py（KB 读端点以 `verify_kb_access` 为主，实际等价“管理员或 KB 属主”）

| Method | Path | 守卫 | 期望 200 | 期望 403 |
|---|---|---|---|---|
| GET | /api/kb/{kb}/vision-settings | `_verify_kb_vision_write_access`（写守卫） | 仅 KB 属主/SA | 非属主 T/A/S（含持 kb:read 的 S） |
| PUT | /api/kb/{kb}/vision-settings | `_verify_kb_vision_write_access` | KB 属主/SA | 非属主 |
| POST | /api/upload | KB + P(kb:write)（限流 30/min） | KB 属主（SA/DA/T/A） | 非属主、S |
| POST | /api/upload/batch | KB + P(kb:write)（限流 20/min） | KB 属主（SA/DA/T/A） | 非属主、S |
| GET | /api/upload/tasks | KB（无显式权限） | KB 属主/SA | 非属主 |
| POST | /api/upload/tasks/{task_id}/retry-now | KB + P(kb:write) | KB 属主（SA/DA/T/A） | 非属主、S |
| POST | /api/upload/tasks/{task_id}/cancel-retry | KB + P(kb:write) | KB 属主（SA/DA/T/A） | 非属主、S |
| DELETE | /api/upload/tasks/{task_id} | KB + P(kb:write) | KB 属主（SA/DA/T/A） | 非属主、S |
| POST | /api/upload/folder | KB + P(kb:write)（folder_path 无路径限制） | KB 属主（SA/DA/T/A） | 非属主、S |
| POST | /api/upload/content | KB + P(kb:write) | KB 属主（SA/DA/T/A） | 非属主、S |
| POST | /api/upload/url | KB + P(kb:write) | KB 属主（SA/DA/T/A） | 非属主、S |
| GET | /api/knowledge/documents | KB（无显式权限） | KB 属主/SA | 非属主 |
| GET | /api/knowledge/documents/{doc_id}/chunks[/{chunk_id}] | KB（无显式权限） | KB 属主/SA | 非属主 |
| GET | /api/knowledge/tags | KB（无显式权限） | KB 属主/SA | 非属主 |
| GET | /api/knowledge/tags/{tag_id}/links | KB（无显式权限） | KB 属主/SA | 非属主 |
| POST | /api/knowledge/documents/{doc_id}/tags/regenerate | KB + P(kb:write) | KB 属主（SA/DA/T/A） | 非属主、S |
| PUT/PATCH/DELETE | /api/knowledge/documents/.../chunks... | KB + P(kb:write) | KB 属主（SA/DA/T/A） | 非属主、S |
| GET | /api/knowledge/stats | KB（无显式权限） | KB 属主/SA | 非属主 |
| POST | /api/knowledge/stats/batch | U + `_is_kb_visible_to_user` 过滤 | 任意登录用户（仅可见 KB） | – |
| POST | /api/knowledge/repair | KB + P(settings:write) | SA | 其他 |
| GET | /api/knowledge/entities | KB（无显式权限） | KB 属主/SA | 非属主 |
| GET | /api/knowledge/graph | KB（无显式权限） | KB 属主/SA | 非属主 |
| GET | /api/knowledge/graph/nodes/{entity_name:path} | KB（无显式权限） | KB 属主/SA | 非属主 |
| POST/PUT/DELETE | /api/knowledge/graph/nodes|edges | KB + P(graph:write) | KB 属主（SA/DA/T/A） | 非属主、S |
| GET | /api/knowledge/documents/{doc_id}/download | U? + token 回退 + `_verify_kb_access_for_download` | KB 属主/SA（任意认证方式） | 非属主、匿名 |
| DELETE | /api/knowledge/documents/{doc_id} | KB + P(kb:write) | KB 属主（SA/DA/T/A） | 非属主、S |
| POST | /api/knowledge/documents/batch-delete | KB + P(kb:write) | KB 属主（SA/DA/T/A） | 非属主、S |
| POST | /api/knowledge/documents/{doc_id}/retry | KB + P(kb:write) | KB 属主（SA/DA/T/A） | 非属主、S |
| POST | /api/kb/{kb_name}/reprocess-multimodal | P(kb:write)（无 KB 校验，path 参数） | 任意 kb:write 用户 | S |
| GET | /api/kb/list | U + 属主过滤 | 任意登录用户（各自可见范围） | – |
| POST | /api/kb/create | P(kb:write) | SA、DA、T、A | S |
| PUT | /api/kb/switch | U | 任意登录用户 | – |
| DELETE | /api/kb/{name} | P(kb:delete) | SA、DA | T/A/S |
| POST | /api/image-search | KB（无显式权限） | KB 属主/SA | 非属主 |
| GET | /api/knowledge/media/{media_id} | P(kb:read) + KB | KB 属主/SA | 非属主 |
| GET | /api/knowledge/media/legacy/{grant} | P(kb:read) + KB | KB 属主/SA | 非属主 |
| GET | /api/files/image | 公开（实现返回 410，已废弃） | 所有人（410） | – |

### 2.6 routers/user_settings.py / routers/vision.py

| Method | Path | 守卫 | 期望 200 | 期望 403 |
|---|---|---|---|---|
| GET | /api/users/me/settings | U | 任意登录用户 | – |
| GET | /api/users/me/settings/options | U | 任意登录用户 | – |
| PATCH | /api/users/me/settings/{section} | U | 任意登录用户 | – |
| GET | /api/admin/platform | P(settings:read) | SA、DA | T/A/S |
| PUT | /api/admin/platform | P(settings:write) | SA | DA/T/A/S |
| GET | /api/vision-models | U | 任意登录用户 | – |
| GET | /api/model-profiles | U | 任意登录用户 | – |
| POST | /api/admin/model-profiles/{profile_id}/probe | P(settings:write) | SA | DA/T/A/S |
| GET | /api/users/me/model-preferences | U | 任意登录用户 | – |
| PUT | /api/users/me/model-preferences | U | 任意登录用户 | – |

---

## 3. 预识别疑点核验结论（C 部分）

### C-1 【高】POST/PUT /api/admin/users* 仅要求 users:write，dept_admin 可创建/提升 super_admin（垂直越权提权）

- 证据：`routers/auth.py:438-458`（POST /admin/users 仅 `require_permission(USERS_WRITE)`，把 `req.role_id` 直接透传 `create_user`）；`routers/auth.py:509-577`（PUT /admin/users/{user_id} 仅 `require_permission(USERS_WRITE)`，`role_id` 可改为任意角色）；`services/pg_auth_repo.py:345-407`（create_user 仅校验 role_id 属于 `DEFAULT_ROLES` 名集合，**未限制 super_admin**）；`services/pg_auth_repo.py:410-463`（update_user 同样仅校验角色在 `DEFAULT_ROLES` 内，**未限制提升为 super_admin**，也未阻止 DA 修改 super_admin 账号的 `is_active`/`username`）。
- 影响：dept_admin 持有 `users:write`（permissions.py 定义），可新建 super_admin 账号或把任意用户（含自己）提升为 super_admin，从而获得全部权限，越权提权。PUT 端点唯一保护是“不能取消自己的管理员权限”（auth.py:525-529），与防止提权无关。
- 定性：确认成立，高危。
- 建议：`users:write` 类操作按“目标角色等级 ≤ 操作者等级”约束；只有 super_admin 可分配/修改 super_admin 角色；禁止修改 super_admin 账号（或要求至少保留一名 super_admin）。

### C-2 【中】GET /api/workflows/models 无权限守卫

- 证据：`routers/admin.py:181-215`（`get_workflow_models` 仅 `Depends(get_current_user)`，无 `require_permission`）。
- 影响：任意登录用户（含 student）可读取系统配置的 LLM/VLM/Embedding 模型清单（来自环境变量，含默认与 fallback 模型名）。不含密钥，属低敏感配置泄露；但与其他 workflow 端点（workflow:read）守卫不一致。
- 定性：确认成立，中危（信息泄露面小，但守卫缺失与周边不一致）。

### C-3 【低/设计冲突】POST/PUT/DELETE /agents/*/conversations* 要求 agent:write/agent:delete，student 只有 agent:read

- 证据：`routers/agent.py:845-857`（create_conversation 要求 `AGENT_WRITE`）、`routers/agent.py:860-877`（改名要求 `AGENT_WRITE`）、`routers/agent.py:880-898`（删除要求 `AGENT_DELETE`）、`routers/agent.py:951-968`（query/stream 还要求 Agent 属主）。
- 影响：方向为“过严”而非“越权”：student 可对系统智能体（owner_id=0）发起流式问答（agent:read），但**无法创建/重命名/删除会话**（无 agent:write/delete），也无法使用任何非己有私有智能体。若产品要求学生可保存对话记录或使用教师共享智能体，则该权限模型与产品意图冲突；从隔离角度无数据越权。
- 定性：确认成立，但属权限模型与产品功能不一致（可用性缺口），低危（安全上无越权面）。

### C-4 【中】GET /kb/{kb}/vision-settings 误用写守卫

- 证据：`routers/knowledge.py:546-556`（`get_kb_vision_settings` 用 `Depends(_verify_kb_vision_write_access)`）、`routers/knowledge.py:531-544`（该守卫要求 KB 属主或 admin 或 kb:write）。
- 影响：读接口被写守卫约束：持 `kb:read` 的 student 及非属主用户即使能读该 KB 也无法读取 vision-settings 状态；同时该守卫内部 `_auth_has_permission(kb:write)` 分支在 `verify_kb_access` 之后实际不可达（非属主已被 403），语义冗余。方向过严，无越权泄露。
- 定性：确认成立，中危（权限语义错误 + 可用性影响）。

### C-5 【低/设计冲突】/autorepair/qa*、/fault-diagnosis*、/code/parse、cases 写操作要求 autorepair:write，student 只有 autorepair:read

- 证据：`routers/autorepair.py`：POST `/autorepair/qa`、`/autorepair/qa/stream`、`/autorepair/fault-diagnosis`、`/autorepair/fault-diagnosis/continue`、`/autorepair/code/parse`、POST/PUT/DELETE `/autorepair/cases*` 全部为 `require_permission(AUTOREPAIR_WRITE)`。
- 影响：student 只能读图谱/案例/工艺库，不能发起汽修问答、故障诊断、代码解析与案例增改。若产品定位学生可进行汽修问答，则该守卫过严（功能不可用）；无越权面。
- 定性：确认成立，低危（权限模型与产品功能冲突，非隔离漏洞）。

### C-6 【中】WebSocket 端点鉴权与推送内容

- 证据：
  - `/api/ws`：`routers/admin.py:540-556`，`_authenticate_ws(ws, required_permission=None)`（admin.py:348-408）仅校验有效登录 token，任何角色可连；推送内容来自 `ws_broadcast`（`services/ws_service.py`）：上传/回溯处理进度、文件名、kb 名、task_id 等任务元数据（`routers/knowledge.py:697`、`services/kb_service.py:4290,4330,5091,5207,5292,5457,5623,6019,6120,6148`），**不含文档正文或密钥**。
  - `/api/ws/workflow-run/{run_id}`：`routers/admin.py:413-435` 有 `required_permission=WORKFLOW_READ` 校验（确认存在）；但 run_id 无属主过滤，`push_run_status`（ws_service.py）会把节点结果（含 `result` 数据，`workflow_executor.py:476-509`）推给订阅同一 run_id 的所有 workflow:read 用户。
- 影响：/ws 为跨 KB 元数据广播（任何登录用户可观察全平台任务进度/文件名）；/ws/workflow-run 存在跨用户订阅同一 run 的越权观察面（workflow:read 用户可看他人运行状态与节点输出）。
- 定性：/ws 权限校验确实缺失（仅登录），推送内容不含高敏感数据，中危；/ws/workflow-run 的 workflow:read 校验确认存在，但缺运行属主隔离，中危。

### C-7 【低/维护】pg_auth_repo.py L171-220 硬编码角色矩阵与 permissions.py 重复（死代码）

- 证据：`services/pg_auth_repo.py:171-220` 硬编码 `default_roles`（旧版，缺 `graph:*`、student 缺 `graph:read` 等），`services/pg_auth_repo.py:221-227` 立即用 `DEFAULT_ROLES` 重新赋值覆盖，L228-238 实际写入的是 `DEFAULT_ROLES` 内容。
- 影响：L171-220 为不可达死代码，运行时无影响（确认 L221 起从 DEFAULT_ROLES 重建）；但若将来有人引用/保留该片段会造成权限漂移（如 student 缺 graph:read 导致图谱读端点对 student 403）。
- 定性：确认成立，低危（死代码/漂移风险，建议删除）。

### C-8 【低】迁移角色定义与 permissions.py 一致性

- 证据：`migrations/001_pg_schema.sql` 种子角色使用旧权限 `manufacturing:read/write`（缺 `autorepair:*`、`graph:*`），且 `ON CONFLICT DO NOTHING`；`migrations/010_manufacturing_to_autorepair_permissions.sql` 完成 manufacturing→autorepair 重命名；`migrations/015_restore_5level_rbac.sql` 的角色 JSON 与 permissions.py 的 `DEFAULT_ROLES` **逐项一致**（含 graph:*、autorepair:*）。
- 影响：015 与 permissions.py 一致；001/002/010 为历史演进且运行时 `init_db()`（pg_auth_repo.py:157-238）以 DEFAULT_ROLES 做 `ON CONFLICT DO UPDATE` 强制刷新，最终一致性由运行时保证。若跳过 init_db 或 015 未执行，非 super_admin 将缺 graph:* 权限（图谱端点 403）。
- 定性：001 与 permissions.py 不一致但无运行时影响；015 一致；建议以 015 + init_db 为唯一事实来源，清理 001 中的旧种子注释。

---

## 4. 额外发现（D 部分）

### D-1 【高】POST /api/upload/folder 可读取服务器任意目录（本地路径遍历 / 任意文件读取面）
- 证据：`routers/knowledge.py:1108-1160`（`upload_folder`）：`folder_path` 来自 query 参数，仅 `os.path.isdir(folder_path)` 校验后 `Path(folder_path).rglob("*")` 递归收集文件并进入解析流水线；无“工作区内路径”白名单或防目录穿越限制。
- 影响：任何 KB 属主（teacher/assistant/dept_admin 有 kb:write）可指定服务器任意目录（如用户主目录、配置目录）触发文档解析与索引，造成任意文件读取面与服务器资源消耗。
- 建议：限制 `folder_path` 必须位于上传根目录内（resolve + `relative_to` 校验），或移除该端点。

### D-2 【中】workflow 运行数据跨用户可读（list/get runs 无属主过滤）
- 证据：`routers/admin.py:490-515`（list_workflow_runs 仅按 workflow_id 过滤）、`routers/admin.py:518-537`（get_workflow_run 仅按 run_id 查询，返回含 `final_output` 的完整运行记录）；`workflow_executor.py:523-545` 的 `workflow_runs` 表虽记录 `user_id`，但读端点未使用。
- 影响：任何有 workflow:read 的用户（T/DA/SA）可枚举并读取任意用户的运行记录与最终输出（可能含检索上下文与 LLM 回答）。
- 建议：list/get run 按 `user_id`（或运行发起者）过滤；admin 例外。

### D-3 【中】KB 读端点未显式校验 kb:read，实际为“管理员或属主”模型，权限语义与 DEFAULT_ROLES 错位
- 证据：`routers/dependencies.py:210-243`（verify_kb_access 放行 is_admin / allowed_kbs / 属主）；`get_current_user`（dependencies.py:46-93）返回的用户字典**从不注入 allowed_kbs**，故非属主非 admin 一律 403；大量 KB 读端点（如 /knowledge/documents、/chunks、/graph、/upload/tasks）只挂 `verify_kb_access` 而无 `require_permission(KB_READ)`。
- 影响：`kb:read` 在权限矩阵中形同虚设：assistant/student 即便有 kb:read 也无法读取非属主 KB（含 owner_id=0 的 default 种子 KB，仅 super_admin 可访问）。若产品需要“按授权分享 KB”，当前模型不可用；若为严格私有模型，则应清理权限矩阵或补充授权机制。
- 建议：明确 KB 分享/授权模型；要么为 verify_kb_access 增加授权注入，要么将 KB 端点权限收敛为 kb:read+属主并在文档中声明。

### D-4 【中】DELETE /api/admin/users/{user_id} 硬删除且无最后管理员保护
- 证据：`routers/auth.py:580-610`（仅防删除自己）；`services/pg_auth_repo.py:466-473`（`DELETE FROM users` 硬删除，非注释声称的软删除）。
- 影响：super_admin 可删除其他 super_admin，可能造成平台无管理员；硬删除使审计与恢复困难（虽有 audit_log 记录）。
- 建议：至少保留一名 super_admin；改为软删除（is_active=0）。

### D-5 【低】公开注册无邀请/验证码门槛
- 证据：`routers/auth.py:88-98`（POST /auth/register 公开，默认 student 角色，仅限流 5/min）。
- 影响：任何人可注册账号进入平台（默认低权限）。取决于部署策略，若面向公网且无邀请码则存在滥用面（如批量注册、消耗配额）。
- 建议：按部署环境启用注册开关/邀请码；保持默认 student 最小权限。

### D-6 【低】/api/kb/{kb_name}/reprocess-multimodal 使用 path 参数但无 verify_kb_access
- 证据：`routers/knowledge.py`（POST /kb/{kb_name}/reprocess-multimodal 仅 `require_permission(KB_WRITE)` + `get_current_user`，未挂 verify_kb_access）。
- 影响：任何有 kb:write 的用户（含非属主 T/A/DA）可对任意 KB 名触发多模态重处理（后端会因 KB 不存在或无权而失败，但接口层面缺少 KB 级校验，与同文件其他 KB 端点不一致）。
- 建议：补充 verify_kb_access。

### D-7 【低】GET /api/knowledge/documents/{doc_id}/download 双模式认证但审计与错误信息存在一致性风险
- 证据：`routers/knowledge.py:3657-3724`：匿名无 token 时 401；`?token=` 回退路径先解码再 `_verify_kb_access_for_download`；路径限制 `real_path.relative_to(Path.cwd())` 存在（防目录逃逸 ✓）。
- 影响：实现本身隔离正确（KB 属主/管理员才可下载）；`token` 通过 query 字符串传递会进入访问日志（凭据泄漏面，属部署/日志治理问题）。
- 建议：日志脱敏或仅限 header 认证用于敏感文档。

### D-8 【低】GET /api/files/image 与 /api/health、/api/autorepair/health 无守卫
- 证据：`routers/knowledge.py:5139`（serve_image 返回 410，已废弃）、`routers/admin.py`（/health 无守卫）、`routers/autorepair.py`（/health 无守卫）。
- 影响：健康检查端点公开属常见设计，风险低；/files/image 已 410，建议删除路由避免探测。

---

## 5. 结论摘要

- 权限事实源 `DEFAULT_ROLES`（permissions.py）与运行时 `init_db()` 刷新、015 迁移一致；001 迁移为历史种子（旧 manufacturing:* 权限），仅当跳过 init_db/015 时会产生 graph:* 缺失。
- 最严重问题集中在**用户管理越权提权**（C-1，高）与**上传文件夹任意路径读取**（D-1，高）；其次是 workflow 运行数据跨用户可读（D-2）、WebSocket 广播越权观察（C-6）、KB 读权限语义错位（D-3）、vision-settings 读接口误用写守卫（C-4）。
- 预识别疑点 (3)(5) 方向为“过严”而非“越权”，属权限模型与产品功能冲突，建议产品侧确认学生/助教的目标权限后调整 `DEFAULT_ROLES` 或端点守卫。
- 修复优先级建议：C-1、D-1（高）→ C-6、D-2、D-3、C-4（中）→ C-2/C-7/C-8、D-4~D-8（低）。