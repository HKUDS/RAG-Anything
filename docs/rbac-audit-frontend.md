# RAG-Anything 前端权限显示审计报告

- 审计日期：2026-08-03（Asia/Shanghai）
- 审计类型：只读静态审计（未修改任何代码文件）
- 权限事实源：`raganything/permissions.py` 中 `DEFAULT_ROLES`（五角色），辅以后端路由 `require_permission` 交叉核验
- 结论可信度：基于源码静态核验，未做运行时联调；行号以审计当日工作区为准

## 0. 五角色权限矩阵（事实源：raganything/permissions.py:10-98）

| 权限 | super_admin | dept_admin | teacher | assistant | student |
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

## A. 角色 × 页面/元素门控表

图例：可见=页面/元素按权限显示；── 表示不可见或不可达；“不一致”指前端显示与后端 `require_permission` 允许集合不符。

### A1. 全局导航与路由守卫（frontend/src/App.jsx）

| 导航项 / 路由 | 守卫权限（App.jsx） | 可见角色 | 与后端矩阵 | 备注 |
|---|---|---|---|---|
| 知识库（侧栏+顶栏） | 无（`requiredPermission: null`，App.jsx:132、123） | 全部五角色 | 一致 | 全角色均有 kb:read，入口不设权限合理 |
| 路由 `/`、`/knowledge`、`/knowledge/*` | 无（App.jsx:655、658-661） | 全部五角色 | 一致 | 同上 |
| 智能体 `/agents`、`/agents/:id` | agent:read（App.jsx:656-657） | 全部五角色 | 一致 | 侧栏 App.jsx:133，顶栏 App.jsx:124 |
| 工作流 `/workflow` | workflow:read（App.jsx:662） | super_admin/dept_admin/teacher | 一致 | 侧栏 App.jsx:134 |
| 汽修 `/autorepair*` | autorepair:read（App.jsx:663-665） | 全部五角色 | 一致 | 侧栏 App.jsx:135 |
| 监控 `/monitor` | monitor:read（App.jsx:669） | super_admin/dept_admin/teacher/assistant | 一致 | 侧栏 App.jsx:136，顶栏 App.jsx:128 |
| 平台管理 `/admin/platform` | settings:read（App.jsx:668） | super_admin/dept_admin | 一致 | 侧栏 App.jsx:137 |
| 用户管理 `/admin/users` | users:read（App.jsx:670） | super_admin/dept_admin | 一致 | 侧栏 App.jsx:138，顶栏 App.jsx:594-604 |
| 审计日志 `/admin/audit-logs` | audit:read（App.jsx:671） | super_admin/dept_admin | 一致 | 侧栏 App.jsx:139，顶栏 App.jsx:605-615 |
| 个人设置 `/preferences` | 无（App.jsx:667） | 全部五角色 | 一致 | 侧栏 App.jsx:140 |

- 侧栏过滤：`visibleNavItems = NAV_ITEMS.filter(item => !item.requiredPermission || hasPermission(...))`（App.jsx:484-485）
- 顶栏过滤：`NAV.filter(...)`（App.jsx:577-581），用户管理/审计日志再显式 `hasPermission` 包裹（App.jsx:594、605）
- 结论：导航项与路由守卫一一对应、与后端矩阵一致，无“导航可见但路由 403”的入口级不一致。

### A2. 用户管理（AdminUsersPage.jsx + CreateUserModal / EditUserModal / UserRoleSelect）

| 元素 | 前端门控 | 依据 | 后端要求 | 各角色 | 一致性 |
|---|---|---|---|---|---|
| 页面入口（路由） | users:read | App.jsx:670 | users:read（auth.py:380） | super_admin/dept_admin | 一致 |
| “创建用户”按钮 | 无（仅页面可达即显示） | AdminUsersPage.jsx:464-466 | users:write（auth.py:443） | 两个可达角色均有 users:write | 一致（防御性缺口，见 B3） |
| 编辑用户按钮 | 无 | AdminUsersPage.jsx:582 | users:write（auth.py:514） | 同上 | 一致（防御性缺口，见 B3） |
| 删除用户按钮 | 仅排除本人（`u.id !== me?.id`） | AdminUsersPage.jsx:584-585 | users:delete（auth.py:584） | dept_admin 可见但**无** users:delete | **不一致（高，见 B1）** |
| 角色下拉 | 全部角色，无操作者过滤 | UserRoleSelect.jsx:32-55；CreateUserModal.jsx:160；EditUserModal.jsx:272 | create_user 仅校验角色存在（pg_auth_repo.py:386-392）；update 仅防自降级（auth.py:525-529） | dept_admin 可选 super_admin | **不一致风险（高，见 B2）** |

### A3. 平台管理（AdminPlatformPage.jsx）

| 元素 | 前端门控 | 依据 | 后端要求 | 一致性 |
|---|---|---|---|---|
| 页面入口 | settings:read | App.jsx:668 | settings:read（admin.py:561） | 一致 |
| 各字段/保存按钮 | `canWrite = hasPermission('settings:write')`，只读时 disabled | AdminPlatformPage.jsx:91-92、144、156-157、166、175、182 | settings:write（admin.py:570、576） | 一致（dept_admin 只见只读态，正确） |

### A4. 审计日志（AdminAuditLogsPage.jsx）

| 元素 | 前端门控 | 依据 | 后端要求 | 一致性 |
|---|---|---|---|---|
| 页面入口 | audit:read | App.jsx:671 | audit:read（auth.py:623） | 一致 |
| 页面操作 | 纯只读列表/筛选 | AdminAuditLogsPage.jsx:82 | 仅 GET | 一致 |

### A5. 运行监控（MonitorPage.jsx）

| 元素 | 前端门控 | 依据 | 后端要求 | 一致性 |
|---|---|---|---|---|
| 页面入口 | monitor:read | App.jsx:669 | monitor:read（admin.py:683、703、719） | 一致 |
| 重载/固定/驱逐 KB 等维护操作 | `canMaintain = hasPermission('settings:write')`，按钮 disabled + toast 提示 | MonitorPage.jsx:103、134、233、248、256、264 | settings:write（admin.py:584、620、654、669） | 一致（teacher/assistant 只读，正确） |

### A6. 知识库（KnowledgePage.jsx / KnowledgeDetailPage.jsx / DocumentChunksPage.jsx / DocumentChunkDetailPage.jsx）

| 元素 | 前端门控 | 依据 | 后端要求 | 各角色 | 一致性 |
|---|---|---|---|---|---|
| 知识库列表/详情入口 | 无（路由 App.jsx:658-661） | — | kb:read | 全部 | 一致 |
| “创建知识库”按钮 | **无任何门控（页面无 useAuth）** | KnowledgePage.jsx:478、558、637 | kb:write（knowledge.py:4898） | student 可见 | **不一致（高，见 B5）** |
| 删除知识库按钮 | **无任何门控** | KnowledgePage.jsx:143、182、413-418 | kb:delete（knowledge.py:4950） | student 可见 | **不一致（高，见 B5）** |
| 上传面板/上传/URL/粘贴/批量上传 | **无门控**（`canManageKB` 仅用于视觉模型区） | KnowledgeDetailPage.jsx:556、580、649、662、681、697-698 | kb:write（knowledge.py:662、779、1110、1195、1246） | student 可见 | **不一致（高，见 B5）** |
| 文档删除/批量删除/重试 | **无门控** | KnowledgeDetailPage.jsx:1864、1987、1978 | kb:write（knowledge.py:4298、4451、4578） | student 可见 | **不一致（高，见 B5）** |
| 视觉向量模型区 | `canManageKB = isAdmin || kb:write` | KnowledgeDetailPage.jsx:929、1792 | KB 所有者或 kb:write（knowledge.py:531-543） | 与后端略偏（见 C2） | 低 |
| 图谱查看 | 未显式按 graph:read 门控 | KnowledgeDetailPage.jsx:2040-2051 | 全角色有 graph:read | 全部 | 一致 |
| 图谱编辑（新增实体/连线、重命名、删除节点/边） | **无 graph:write 门控** | KnowledgeDetailPage.jsx:2054-2059、2123、2128、2152 | graph:write（knowledge.py:3360、3393、3426、3450、3506） | student 可见 | **不一致（中，见 B6）** |
| 切块编辑/删除/标签 | `canWrite = hasPermission('kb:write')` | DocumentChunksPage.jsx:123、160、358-360、373；DocumentChunkDetailPage.jsx:109、111、267、298、303 | kb:write（knowledge.py:2536、2662、2491） | student 只读提示 | 一致 |

### A7. 智能体（AgentsPage.jsx）

| 元素 | 前端门控 | 依据 | 后端要求 | 一致性 |
|---|---|---|---|---|
| 页面入口 | agent:read | App.jsx:656 | agent:read（agent.py:691） | 一致 |
| 新建/编辑 | `canWrite = hasPermission('agent:write')`，按钮 disabled | AgentsPage.jsx:104、202-211、389、396、458、520 | agent:write（agent.py:724、760） | 一致 |
| 删除 | `canDelete = hasPermission('agent:delete')`，按钮 disabled | AgentsPage.jsx:105、310、463-466 | agent:delete（agent.py:785） | 一致（assistant/student 只读，正确） |

### A8. 智能体会话（AgentChatPage.jsx）

| 元素 | 前端门控 | 依据 | 后端要求 | 各角色 | 一致性 |
|---|---|---|---|---|---|
| 页面入口 | agent:read | App.jsx:657 | agent:read | 全部 | 一致 |
| 新建对话按钮 + send 自动建会话 | **无门控**（仅 catch+toast） | AgentChatPage.jsx:751、557-559；api.js:720 | **agent:write**（agent.py:847） | student 可见→403 | **不一致（高，见 B7）** |
| 重命名对话 | 无 | AgentChatPage.jsx:790 | agent:write（agent.py:862） | student 可见→403 | 不一致（并入 B7） |
| 删除对话 | 无 | AgentChatPage.jsx:797 | agent:delete（agent.py:882） | student 可见→403 | 不一致（并入 B7） |
| 编辑回答 | 无 | AgentChatPage.jsx:1159、1174 | agent:write（agent.py:911） | student 可见→403 | 不一致（并入 B7） |
| 模式切换 | `canAdjustModes = agent:read`（全员） | AgentChatPage.jsx:170、848、1415 | 仅前端展示态 | — | 无权限含义 |

### A9. 工作流（WorkflowPage.jsx + components/workflow/*）

| 元素 | 前端门控 | 依据 | 后端要求 | 各角色 | 一致性 |
|---|---|---|---|---|---|
| 页面入口 | workflow:read | App.jsx:662 | workflow:read（admin.py:132） | super_admin/dept_admin/teacher | 一致 |
| 新建/保存/运行/删除 | **无门控**（页面仅取 token，无 hasPermission） | WorkflowPage.jsx:16、66、359-368、445；WorkflowToolbar.jsx:29、32、74 | workflow:write（admin.py:252、286、331、439） | teacher 可见→403 | **不一致（高，见 B8）** |
| 运行历史查看 | 无 | WorkflowRunPanel.jsx:36-53 | workflow:read（admin.py:493、521） | 一致 | 一致 |

### A10. 汽修（AutoRepairAgentPage / AutoRepairDashboardPage / AutoRepairKnowledgePage / AutoRepairKBSelector）

| 元素 | 前端门控 | 依据 | 后端要求 | 各角色 | 一致性 |
|---|---|---|---|---|---|
| 三个页面入口 | autorepair:read | App.jsx:663-665 | autorepair:read | 全部 | 一致 |
| QA 问答发送 | **无门控**（页面无 useAuth） | AutoRepairAgentPage.jsx:478-479；API:205 | **autorepair:write**（autorepair.py:616） | student 可见→403 | **不一致（高，见 B9）** |
| 故障诊断 | **无门控** | AutoRepairAgentPage.jsx:631-632 | **autorepair:write**（autorepair.py:722、733） | student 可见→403 | 不一致（并入 B9） |
| 案例新建/编辑/删除 | **无门控** | AutoRepairKnowledgePage.jsx:568、572、628、633、837 | **autorepair:write**（autorepair.py:438、468、485） | student 可见→403 | 不一致（并入 B9） |
| AR-KB 新建领域 | **无门控** | AutoRepairKBSelector.jsx:70-72、102；useAutoRepairKB.js:85-90 | **kb:write**（knowledge.py:4898） | student 可见→403 | 不一致（并入 B9） |
| 仪表盘操作 | 读+导航 | AutoRepairDashboardPage.jsx:122-158、194-248 | 读端点 | 全部 | 一致 |

## B. 发现清单

### B1（高）用户删除按钮未按 users:delete 隐藏
- 证据：`frontend/src/pages/AdminUsersPage.jsx:584-585`（仅 `u.id !== me?.id` 排除本人，未检查 `users:delete`）；后端 `DELETE /admin/users/{user_id}` 需 `users:delete`（`raganything/routers/auth.py:584`）。
- 影响：dept_admin（有 users:read/write，无 users:delete，permissions.py:57-77）看到删除按钮并点击后后端返回 403；删除需二次 confirm（AdminUsersPage.jsx:431），不会误删，但 UI 与权限契约不符，属于“按钮可见但后端 403”。

### B2（高）dept_admin 可通过角色下拉分配 super_admin（提权面）
- 证据：`UserRoleSelect.jsx:32-55` 渲染全部五角色无过滤；CreateUserModal.jsx:160、EditUserModal.jsx:272 直接复用；后端 create_user 仅校验角色存在（`pg_auth_repo.py:386-392`），update 仅防“本人取消自己的超管”（`auth.py:525-529`），均不限制操作者把他人设为 super_admin。
- 影响：dept_admin 可创建/提升 super_admin 用户，实现横向提权。前端“显示”与后端“允许”在此一致，但这是权限模型缺陷：前端应在下拉中过滤高于操作者等级的角色，后端应强制“仅 super_admin 可分配 super_admin”。（属于安全设计问题，非纯显示不一致，按高处理。）

### B3（低）用户管理创建/编辑按钮未按 users:write 门控（防御性缺口）
- 证据：`AdminUsersPage.jsx:464`（创建）、`:582`（编辑）无 `hasPermission('users:write')`；后端要求 users:write（auth.py:443、514）。
- 影响：当前五角色中拥有 users:read 的（super_admin/dept_admin）均同时拥有 users:write，无实际 403；但前端未按后端契约显式门控，未来若出现“只读管理员”角色会立刻暴露。

### B4（通过）ProtectedRoute 403 处理
- 证据：`frontend/src/components/ProtectedRoute.jsx:33-50`。
- 结论：未登录跳 `/login` 并携带 from；已登录无权限渲染 403 页（含所需权限提示与“前往个人设置”恢复按钮，`deniedRouteRecovery=/preferences`，settingsRouting.js:1）。行为正确，无安全或可用性问题。`adminOnly` 为历史兼容参数，等价 `users:read`，当前无使用点。

### B5（高）知识库列表/详情写操作对 student 全暴露
- 证据：`KnowledgePage.jsx` 无 useAuth/hasPermission；创建按钮 :478/:558，删除按钮 :143/:182，后端分别要求 kb:write（knowledge.py:4898）、kb:delete（knowledge.py:4950）。`KnowledgeDetailPage.jsx` 上传面板 :556、批量上传 :697、文档删除 :1987、批量删除 :1864、重试 :1978 均未用 `canManageKB`（:929 仅包裹视觉模型区 :1792）；后端要求 kb:write（knowledge.py:662/779/1110/1195/1246、4298、4451、4578）。
- 影响：student 进入知识库页可见“创建/删除知识库”“上传”“删除文档”等全部写操作，点击即 403；上传面板还会在详情页渲染（:565-750）。应整体按 `kb:write`（创建/上传/文档删除）与 `kb:delete`（删库）分别门控。

### B6（中）知识图谱编辑按钮未按 graph:write 门控
- 证据：`KnowledgeDetailPage.jsx:2054-2059`（新增实体/创建连线）、:2123/:2128（重命名/删除节点）、:2152（删除边）；后端 graph 写端点均要求 graph:write（knowledge.py:3360、3393、3426、3450、3506）。
- 影响：student（仅 graph:read）可见图谱编辑入口并触发 403。应为 graph:write 门控（隐藏或禁用按钮）。

### B7（高）AgentChatPage：student 无法创建会话且前端不引导
- 证据：`AgentChatPage.jsx:751`（新建对话按钮无条件渲染）、:557-559（send 无活动线程时自动 `createThread`，失败直接 return）、:332-333（仅 toast）；`api.js:720` POST `/agents/{id}/conversations`；后端要求 **agent:write**（agent.py:847）。
- 影响：student 有 agent:read 可进入页面，但无 agent:write → 无法新建会话、无法发送首条消息（聊天功能对 student 整体不可用）；重命名/删除/编辑回答按钮（:790/:797/:1174）同样 403。前端虽有 catch+toast 的“优雅”报错，但未按 `agent:write` 隐藏/禁用按钮，也没有只读引导。属高影响显示不一致。

### B8（高）工作流页写操作未按 workflow:write 门控
- 证据：`WorkflowPage.jsx:16`（import useAuth）、:66（仅取 token）、:359-368（onNew/onSave/onRun 无条件传入）、:445（删除按钮）；`WorkflowToolbar.jsx:29/32/74`（新建/保存/运行无条件渲染）；后端 POST/PUT/DELETE/run 均要求 workflow:write（admin.py:252、286、331、439）。
- 影响：teacher 只有 workflow:read（permissions.py:80-88），进入页面后可见新建/保存/运行/删除并触发 403。前端完全缺少 workflow:write 门控。

### B9（高）汽修三个页面与 AR-KB 选择器完全无权限门控
- 证据：AutoRepairAgentPage.jsx / AutoRepairDashboardPage.jsx / AutoRepairKnowledgePage.jsx 均无 useAuth（import 见各自 :1-14）；QA 发送 :478-479 调 `POST /autorepair/qa/stream`（autorepair.py:616）、诊断 :631-632 调 `POST /autorepair/fault-diagnosis`（autorepair.py:722）、案例新建/编辑/删除 :568/:572/:628/:633/:837 调 cases CRUD（autorepair.py:438/468/485）、AutoRepairKBSelector.jsx:70-72/:102 调 `POST /kb/create`（kb:write，knowledge.py:4898，经 useAutoRepairKB.js:85-90）。
- 影响：student（autorepair:read）可进入全部汽修页面并触发 QA/诊断/案例 CRUD/AR-KB 创建的 403。应按 `autorepair:write`（QA/诊断/案例）与 `kb:write`（AR-KB 创建）分别门控。

### B10（通过）AdminPlatformPage / AdminAuditLogsPage / MonitorPage 写操作门控
- 证据：AdminPlatformPage.jsx:91-92、182（readOnly 全量禁用，dept_admin 只读正确）；AdminAuditLogsPage.jsx 纯只读；MonitorPage.jsx:103、248、256、264（canMaintain=settings:write 禁用维护按钮）。
- 结论：三页均与后端一致，无“按钮可见但 403”问题。

### B11（通过）AgentsPage 与切块页门控
- 证据：AgentsPage.jsx:104-105、202-211、389、396、458、463-466、520；DocumentChunksPage.jsx:123、160、358-360、373；DocumentChunkDetailPage.jsx:109、111、267、298、303。
- 结论：agent:write/agent:delete、kb:write 门控齐全，与后端一致。

### B12（通过）AuthContext 权限来源与 hasPermission 逻辑
- 证据：`frontend/src/context/AuthContext.jsx:173-183`。
- 结论：`permissions = user.role.permissions`（来自 `/api/auth/me`，非解析 JWT）；登录/刷新后均重新拉取 /me（AuthContext.jsx:7-59、85-105）；`isAdmin = role.name === 'super_admin'`；`hasPermission`：isAdmin 恒 true、空权限要求恒 true、否则 `permissions.includes(perm)`。与后端“super_admin 拥有全部权限 + 按角色权限集判定”的模型一致。低风险点见 C3。

## C. 额外发现

- C1（高，安全设计）角色分配无“不可提升自己等级”约束：见 B2，前端下拉与后端 create/update 均允许 dept_admin 分配 super_admin。修复建议是前后端同时收紧（后端为准）。
- C2（低，显示偏保守）视觉向量模型区：前端 `canManageKB = isAdmin || kb:write`（KnowledgeDetailPage.jsx:929）比后端“KB 所有者或 kb:write”（knowledge.py:531-543）更严；当前五角色下所有可能的 KB 所有者都拥有 kb:write，实际无差异，仅记录。
- C3（低，陈旧权限缓存）刷新令牌续期后若 `/api/auth/me` 失败，会回退到 localStorage 中旧 `user`（AuthContext.jsx:34-43），权限展示可能过期直到下次 verifyToken；若角色/权限被降级，前端可能短暂显示旧权限下的按钮，点击仍会被后端 403 兜底。
- C4（低，防御性）`/knowledge` 系列路由未设 `requiredPermission="kb:read"`（App.jsx:655、658-661），当前依赖“全角色均有 kb:read”的隐式约定；导航项同样 `requiredPermission: null`（App.jsx:132、123）。建议显式声明以便未来新增角色时保持 fail-closed。
- C5（提示）AdminUsersPage 的“创建/编辑”未按 users:write 门控（见 B3）；MonitorPage 维护按钮的门控键是 `settings:write` 而非 `monitor:write`（权限模型本身无 monitor:write），与后端一致，仅提示命名语义。

## 后端端点权限核验依据（节选）

- 用户：users:read（auth.py:380/490）、users:write（auth.py:443/514）、users:delete（auth.py:584）、audit:read（auth.py:623）
- 知识库：kb:write（knowledge.py:662/779/1110/1195/1246/2434/2491/2536/2662/4298/4451/4578/4777/4898）、kb:delete（knowledge.py:4950）、graph:write（knowledge.py:3360/3393/3426/3450/3506）、settings:write（knowledge.py:2989）
- 智能体：agent:read（agent.py:691/707/803/828/953）、agent:write（agent.py:724/760/847/862/911）、agent:delete（agent.py:785/882）
- 工作流/平台/监控：workflow:read（admin.py:132/224/493/521）、workflow:write（admin.py:171/252/286/331/439）、settings:read（admin.py:561）、settings:write（admin.py:570/576/584/620/654/669）、monitor:read（admin.py:605/683/703/719）
- 汽修：autorepair:read（autorepair.py:340-576 等 GET）、autorepair:write（autorepair.py:438/468/485/553/587/616/722/733）

## 修复优先级建议

1. 高优先级：B5（知识库写操作门控）、B7（会话创建按 agent:write 门控并给 student 只读引导）、B8（工作流 workflow:write 门控）、B9（汽修 autorepair:write/kb:write 门控）、B1（删除按钮 users:delete 门控）、B2（角色分配收紧）。
2. 中优先级：B6（图谱编辑 graph:write 门控）。
3. 低优先级：B3/C2/C3/C4（防御性与体验打磨）。
