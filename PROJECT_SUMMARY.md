# RAG-Anything 项目核心总结

> 本文件是所有项目任务的首要阅读入口和精简知识库。开始任务前必须完整阅读；完成任务前必须同步当前事实并追加复盘记录。它用于导航，不替代代码、迁移、运行配置或 OpenSpec。

## 0. 元信息与使用规则

| 项目 | 当前值 |
|---|---|
| 最后核验日期 | 2026-08-04（Asia/Shanghai） |
| 核验分支 | `feature/custom-enhancements` |
| 基准提交 | `52e0482714de` |
| 工作区状态 | **有未提交改动**；“进行中”内容不得视为已交付 |
| 应用版本 | FastAPI / 前端均标记为 `1.3.1` |
| 维护上限 | 目标不超过 350 行且不超过 30 KB；近期任务最多 15 条 |

### 事实优先级

发生冲突时按以下顺序判定，并在本次任务收尾时修正本文件：

1. 当前代码、数据库迁移、运行配置和已执行验证结果。
2. [`openspec/specs/`](openspec/specs/) 下的主规格。
3. [`openspec/changes/`](openspec/changes/) 下的 active change，仅表示进行中意图。
4. 已归档 change 和 [`docs/adr/`](docs/adr/) 中仍有效的决策。
5. `CHANGELOG.md`、旧功能说明书、旧架构文档等历史材料，仅作背景线索。

### 强制生命周期

- **启动**：完整阅读本文件，再根据任务范围定向核验相关源码、配置、迁移和规格；不得用本文件代替必要的局部核验。
- **执行**：发现长期有效的新事实、风险或经验时记录“总结增量”。并行子任务不得争抢本文件，只在 handoff 提交增量。
- **收尾**：唯一协调者先更新当前状态，再追加一条近期任务记录，最后检查链接、状态、日期、体积和敏感信息。
- **无持久变化**：评审、排查等任务若未改变项目事实，也必须追加一条极短记录并注明“无持久行为变化”。
- **OpenSpec**：`propose` 把总结同步列为最终任务；`apply` 在验证后更新；`archive` 前确认总结已经同步。

### 状态和安全约定

- `稳定现状`：已进入基准提交或有明确实现与验证依据。
- `进行中`：仅存在于未提交工作区或未完成 active change。
- `计划`：规格或任务已提出，但不能对外宣称已经实现。
- `已废弃`：不再作为当前模型、接口或流程使用；必要时保留兼容说明。
- 只记录环境变量名称、用途和默认行为；禁止写入实际密钥、密码、令牌、用户数据、运行日志及生成产物。

## 1. 项目定位与用户

RAG-Anything 是面向教育和专业实训场景的多模态知识库与智能体平台。它将文档解析、分块、向量与知识图谱检索、智能体问答、工作流和领域应用整合在同一 Web 产品中。

主要用户是建设内容和智能体的教师/助教、使用授权问答的学生、管理组织资源的系部管理员，以及负责全局权限、审计与部署的平台管理员。

产品与界面原则以 [`PRODUCT.md`](PRODUCT.md) 和 [`DESIGN.md`](DESIGN.md) 为专项依据；中文为主要界面语言，目标是 WCAG 2.2 AA。

## 2. 当前能力状态

### 稳定现状

| 领域 | 核心能力 | 主要入口 |
|---|---|---|
| 认证与权限 | JWT、密码、用户/角色、审计、五级 RBAC | [`routers/auth.py`](raganything/routers/auth.py)、[`services/auth.py`](raganything/services/auth.py) |
| 知识库 | 多源上传、异步任务、文档/分块/标签/图谱管理 | [`routers/knowledge.py`](raganything/routers/knowledge.py)、[`services/kb_service.py`](raganything/services/kb_service.py) |
| 多模态 RAG | 解析、分块、Embedding、实体关系、混合检索和引用 | [`raganything.py`](raganything/raganything.py)、[`query/`](raganything/query/) |
| 智能体 | 模板、CRUD、KB 绑定、会话和 SSE 问答 | [`routers/agent.py`](raganything/routers/agent.py) |
| 工作流/汽修 | 工作流运行；案例、工艺、诊断和问答 | [`routers/admin.py`](raganything/routers/admin.py)、[`routers/autorepair.py`](raganything/routers/autorepair.py) |
| 运维/前端 | 健康、指标、缓存、恢复任务；React 管理界面 | [`server.py`](server.py)、[`App.jsx`](frontend/src/App.jsx) |

- 主侧栏不再展示静态“知元服务在线”状态卡，也不显示导航分组编号、标题或分隔线；运行状态仍通过“运行监控”页面提供，避免在全局导航重复呈现未经实时校验的信息。
- 上传任务的 legacy LLM 档案按 `LLM_MODEL`、`LLM_BINDING_MODEL` 顺序解析模型；上传持久化前预检文本与 Embedding 模型。`legacy-vlm` 为兼容 ID，设置页显示实际模型 `qwen-vl-plus`；VLM OCR 兜底覆盖全部 PDF 页，上限不足显式失败。OpenDataLoader 输出根目录绝对化，结果载体携带页覆盖与来源引用，避免转换成功后路径或构造失败。
- 智能体问答的请求级设置快照必须携带 LLM/VLM 的公开 profile 指纹；知识库实例严格校验 LLM 可用性和两类指纹一致性。纯文本问答不依赖 VLM 可用性，只有图片问答和多模态处理要求可用 VLM；SSE 失败会保留错误消息，不再被会话初始化覆盖。面向用户的检索进度仅发送经过中文化的可解释阶段，第三方库的初始化、缓存、模型和存储告警只保留在服务端日志。
- 个人设置桌面工作区采用独立详情滚动：左侧分区菜单保持静止，点击项目仅滚动右侧详情；1100px 以下保留页面滚动与横向分区导航。
- 主侧栏末尾顺序固定为“用户管理、审计日志、个人设置”；权限不足时仅隐藏相应管理入口，个人设置始终位于可见列表末尾。
- 智能体启用“重排”的 RRF 查询可正常工作：失败降级为融合顺序、预算不足 1.5s 跳过；图谱检索按查询级快照执行（一次读节点/边、批量取 chunk、种子上限 20）。；检索预算默认 12s。
- 认证仅使用用户名+密码：`users.email` 列已随迁移 `025` 移除（历史数据不可恢复），注册、管理端用户管理、个人设置与审计详情均不再出现邮箱；`DEFAULT_ADMIN_EMAIL` 环境变量不再支持。

- Repository redundancy governance: upload tasks use durable snapshots; retired CLI/client paths removed; shared authenticated SSE serves agent/autorepair Q&A; 4,898 tracked artifacts await archive/reference proof; no HTTP API/migration/RBAC change.

### 进行中

- **个人设置中心与平台设置策略**：`redesign-personal-settings-center` 规格已归档，实现仍在未提交工作区。`/preferences` 统一“个人设置”，具备独立分区保存、存储值/生效值/来源/约束展示、可执行检索预设和移动端锚点；`/admin/platform` 管理默认值、允许范围和硬上限。
- **分级个人设置权限投影**：`enforce-personal-settings-capabilities` 已实现未提交。实时权限控制分区与 API；降级的新任务继承默认，旧快照不变。
- **视觉模型配置与混合检索链路**：工作区实现模型目录、请求/任务设置快照、作用域缓存和 KB 视觉向量重建。默认 `hybrid` 查询使用不可变的用户检索选项（含图谱深度），不修改共享检索器；KB 重建失败保留旧索引并持续显示失败状态与重试入口。生产迁移及真实 PostgreSQL 多进程验收仍取决于部署环境。
- **部署配置**：Docker 构建上下文排除 `.env`，模型目录使用只读挂载；本机没有 Docker 命令，容器构建和除 `027` 外的部署迁移未在本轮验收。
- **项目总结质量检查**：当前工作区新增标准库检查器、10 项定向测试和 non-blocking GitHub Actions workflow；本地违规仍返回非零，CI 仅用 `continue-on-error` 提示，不作为合并门禁。入口见 [`check_project_summary.py`](scripts/check_project_summary.py) 和 [`project-summary-quality.yml`](.github/workflows/project-summary-quality.yml)。
- **处理中上传任务删除**：`cancel-inflight-upload-tasks` 扩展上传抽屉和 `DELETE /upload/tasks/{task_id}`：排队任务即时删除，处理中/重试任务先进入持久化 `cancelling`，停止 worker、抑制晚到状态/重试写入并清理残留；worker 限时终止再限时强杀，未退出则保留 `cancelling` 交由轮询/恢复收敛。前端仅在服务端确认删除后移除任务。部署前须执行迁移 `024_upload_task_cancellation.sql`；真实 PostgreSQL 多进程验收仍取决于部署环境。

- **前端导航与首屏性能优化**：`optimize-frontend-navigation-latency` 已纳入集成检查点（未归档）：KB 卡点击即时跳转、图谱/实体按需加载、15s 任务感知轮询、全局 stats 30s TTL 缓存、加载中显示骨架、App.jsx 移除 framer-motion、字体自托管、nginx 不可变缓存。字体依赖安装和生产构建已通过；启动直接链为 483,290 B，相对旧 `dist` 快照下降 14.2%，因快照非同源干净基线且未达到 ≥20%，仍待可比基准和浏览器/nginx 验收。
- **知识库/智能体空态布局修复**：前端页面仅在加载中或存在当前分页结果时挂载资源卡片网格；零资源、搜索无匹配和列表加载失败直接渲染主内容空态，避免桌面 `1fr` 网格将空态推到底部。未改变五级 RBAC、资源所有权或写操作门控；学生、助教、教师、系部管理员和超级管理员沿用各自可见资源与 CTA 规则。
- **图片召回与会话摘要 Schema**：`fix-agent-media-deadline-and-summary-schema` 已纳入集成检查点（未归档），实现独立媒体预算、超时保留已验证图片和幂等迁移 `027`；本地 PostgreSQL 已连续执行两次并核验摘要列与部分索引，仍待重启后的真实问答验收。
- **智能体查询开发日志**：`improve-agent-query-developer-logs` 已纳入集成检查点（未归档），新增按 trace 汇总的 `QUERY_JOURNEY`，稳定展示检索、媒体、模型和持久化阶段；日志仅含受控标签与耗时，仍待真实 SSE 观察。

### 计划与待收敛 OpenSpec

截至 2026-07-30，active change 的勾选数只用于导航，不代表发布状态：

| Change | 已完成/待办 | 当前判断 |
|---|---:|---|
| [`canvas-rendering-migration`](openspec/changes/2026-07-02-canvas-rendering-migration/) | 0/24 | 计划，待确认 |
| [`orderly-graph-layout`](openspec/changes/2026-07-02-orderly-graph-layout/) | 39/8 | 进行中 |
| [`manufacturing-to-autorepair`](openspec/changes/2026-07-03-manufacturing-to-autorepair/) | 0/26 | 清单落后，待复核/归档 |
| [`add-opendataloader-pdf-parser`](openspec/changes/add-opendataloader-pdf-parser/) | 23/38 | 部分落地，待复核 |

### 已废弃或不得当作当前事实

- 三角色 `admin/editor/viewer` 仅作迁移映射；当前为五级角色。
- `auth.db`/SQLite 不再是认证权威存储；当前要求 PostgreSQL。
- `users.email` 字段与 `DEFAULT_ADMIN_EMAIL` 环境变量：2026-08-03 全链路移除（迁移 `025` 删除列），历史邮箱数据不可恢复；历史说明书仍含旧示例，仅作背景材料。
- 旧 `/upload`、`/query`、单一 `SettingsPage` 和 `manufacturing:*` 描述已过时，以当前路由和 `autorepair:*` 为准。

## 3. 架构与关键数据流

### 分层

`React/Vite 前端 -> FastAPI Router -> Service -> RAG/Core -> PostgreSQL、向量/图存储、Redis、文件工作区`

代码依赖必须保持 `Router -> Service -> Core -> Infrastructure`。`raganything/` 包不得反向依赖根目录脚本。

### 关键数据流

- **文档处理**：上传 API 创建任务 -> Worker 解析文本/多模态内容 -> 分块、标签、Embedding、实体关系与索引 -> PostgreSQL/KB 工作区持久化 -> 轮询、SSE 或 WebSocket 反馈；失败任务进入重试或修复。
- **查询与智能体**：JWT/RBAC/KB 范围校验 -> 智能体选择知识库、提示词和上下文 -> 关键词、向量、图谱、标签、图像联合召回 -> LLM 生成带来源答案 -> 会话与历史写入 PostgreSQL。

### 数据边界

- PostgreSQL 是认证、共享状态和业务仓库的必需后端；迁移见 [`migrations/`](migrations/)。
- `WORKING_DIR`、上传、输出和 ODL 产物按任务/实例隔离；Redis 与外部图/向量存储由环境配置。
- 浏览器只访问受控 API/媒体入口，不能接收本地路径、模型目录或密钥。

## 4. 核心目录导航

| 路径 | 职责 |
|---|---|
| [`server.py`](server.py) | FastAPI 组装、路由挂载、启动/关闭、监控和进程锁 |
| [`raganything/`](raganything/) | RAG 核心及解析、分块、Embedding、图谱、查询模块 |
| [`raganything/routers/`](raganything/routers/) / [`services/`](raganything/services/) | HTTP/WebSocket 边界与业务/仓库层 |
| [`process_worker.py`](process_worker.py) | 隔离的文档处理 Worker 入口 |
| [`frontend/src/`](frontend/src/) | React 页面、组件、状态和 API 封装 |
| [`migrations/`](migrations/) / [`tests/`](tests/) | PostgreSQL 演进与后端/安全/回归验证 |
| [`openspec/specs/`](openspec/specs/) / [`changes/`](openspec/changes/) | 主规格与进行中变更 |
| [`docs/`](docs/) / [`scripts/`](scripts/) | 专项资料与有副作用的辅助入口；使用前核验 |

## 5. 核心业务规则

### RBAC v2

权限常量以 [`raganything/permissions.py`](raganything/permissions.py) 为准，格式为 `resource:action`。默认角色为 `student`。

| 角色 | 业务定位 |
|---|---|
| `super_admin` | 全部权限；`is_admin` 仅作为由该角色派生的兼容字段 |
| `dept_admin` | 组织用户、知识库、智能体及业务管理 |
| `teacher` | 自有 KB/智能体读写及教学业务能力 |
| `assistant` | KB 内容维护、智能体使用和受限业务能力 |
| `student` | 获授权的读取与问答能力 |

关键不变量：

- 受保护接口使用 [`require_permission()`](raganything/dependencies.py)，不得以 `is_admin` 建立新授权模型。
- `is_admin` 仅由 `super_admin` 派生；前端展示权限不能替代服务端校验。
- 用户、角色、审计、JWT 撤销和登录保护由 PostgreSQL auth service 管理。
- 旧三角色用户通过 [`015_restore_5level_rbac.sql`](migrations/015_restore_5level_rbac.sql) 映射到五级角色。
- 角色分配等级约束：`can_assign_role()`（`ROLE_ORDER/ROLE_RANK`）限定操作者只能分配不高于自身等级的角色；`create_user/update_user` 强制校验，bootstrap 以 super_admin 豁免。
- 会话属“使用”资源：创建/重命名/删除按 `agent:read`（保留所有权校验），消息编辑按 `agent:write`。
- `GET /kb/{kb}/vision-settings` 按 `kb:read`+可见性读取，写入保持属主/`kb:write`；`GET /workflows/models` 需 `workflow:read`。
- `POST /upload/folder` 受 `FOLDER_UPLOAD_ROOTS` 白名单约束（默认 `uploads/` 与 `WORKING_DIR`），越界 403；运行时角色种子由 `DEFAULT_ROLES` 派生（`build_default_role_rows`），PG 模式删除 KB 已修复。

### 知识库与任务

- 非管理员只访问授权 KB；工作区、缓存、历史和媒体必须隔离。
- 上传状态需可恢复/重试并避免重复入库；删除同步清理状态、索引、媒体和缓存。
- 图谱、分块、标签编辑保持 KB 范围和缓存/索引一致性。

### 设置、智能体与媒体

- 平台设置与个人设置是不同权限域；个人设置中心实现尚未提交时，以已提交接口为稳定基线。
- 智能体必须绑定调用者可访问的知识库；会话和消息按用户/智能体隔离。
- 媒体路径不得直接暴露本地文件系统；使用受控媒体端点和授权信息。

## 6. 技术栈、配置与运行

### 技术栈

- **后端**：Python `>=3.10`、FastAPI/Uvicorn、RAG-Anything/LightRAG、asyncpg、Prometheus。
- **解析/检索**：Docling、MinerU、PyPDF、可选 OpenDataLoader/PaddleOCR、向量/关键词/图谱检索；Docling 为必装依赖。
- **前端**：React 18、Vite 5、Router、D3/XYFlow/Recharts、Tailwind CSS。
- **基础设施**：PostgreSQL 16、Redis 7、Compose/Nginx，可选外部图/向量库。

### 配置类别

以代码中的 `os.getenv()` 和部署配置为准。[`.env.example`](.env.example) 含大量注释示例但仅启用基础项，[`env.example`](env.example) 覆盖更完整；两者范围不同且可能含历史描述，均不能单独作为事实源。

- 模型：`LLM_BINDING*`、`LLM_MODEL`、`VISION_MODEL`、`EMBEDDING_*`。
- 数据与工作区：`DATABASE_URL`、`POSTGRES_*`、`REDIS_URI`、`WORKING_DIR`、可选图/向量存储变量。
- 处理：`MAX_ASYNC`、`MULTIMODAL_*`、`PROCESS_*`、`AUTO_TAG_*`、切块/解析/缓存/模型预检变量。
- 安全与运维：`JWT_*`、`DEFAULT_ADMIN_*`、登录锁定、`LOG_*`、`ENABLE_METRICS`、`METRICS_PATH`。

敏感变量在生产必须显式设置且不得提交。`config/runtime_settings.json` 是运行时覆盖入口；模型目录以部署配置和 [`config/vision_models.json`](config/vision_models.json) 等受控文件为准。

### 常用命令

```powershell
# 本地后端：server.py 默认端口为 8001，可由 PORT 覆盖
uv run python server.py

# 前端
npm --prefix frontend run dev
npm --prefix frontend run test:unit
npm --prefix frontend run build

# 后端测试
uv run pytest tests -q

# 项目总结质量；本地严格返回检查结果，CI 仅作非阻断提示
uv run python scripts/check_project_summary.py

```

数据库初始化入口为 [`scripts/pg_setup.py`](scripts/pg_setup.py)，会创建数据库、执行迁移并修改 `.env`，运行前必须检查迁移清单和凭证处理。容器链当前存在已知问题，修复并验证前不要把 `docker compose up --build` 视为可用发布命令。

## 7. 开发约束与最低验证

- 每次请求执行两级调度；OpenSpec 额外遵守 [`AGENTS.md`](AGENTS.md) 的专家数量和时序。
- 并行规则见 [`parallel_collaboration_rules.md`](docs/parallel_collaboration_rules.md)；迁移、权限、锁文件、入口和本文件串行维护。
- 保留用户既有改动，不重置、覆盖或格式化无关文件。
- 后端跑相关 `pytest`；共享边界扩大回归。前端跑 `test:unit`，页面/样式再跑 build 和视口检查。
- 迁移验证顺序、幂等、升级与兼容；文档验证链接、结构、敏感信息和 `git diff --check`。

## 8. 已知风险与常见问题

- 2026-06 文档和 [`docs/architecture.md`](docs/architecture.md) 已落后，引用前需核验。
- `pyproject.toml` 声明 `README.md`，但仓库根目录当前缺少该文件；这是独立遗留问题。
- 两份 env 示例覆盖不一；`pg_auth_repo.py` 说明仍残留旧角色/回退描述。
- 已跟踪的 `tests/test_auth.py` 仍有 3 条断言期待 `viewer/admin`，与当前 `student/super_admin` 角色结果冲突，需定向更新而非删除整份有效测试。
- OpenSpec 勾选与代码、迁移编号与演进修正均有漂移，不能按表面状态判断。
- 容器链尚未验收：Dockerfile 在未安装 Node/npm 的 Python 基础镜像中构建前端，Compose 仍挂载旧 `auth.db`，容器端口/健康检查和 `frontend_dist` 产物链也需统一。
- 当前工作区含多组未提交修改；并行实例共享目录、数据库或端口会污染状态。
- 持久上传重试依赖后端进程内调度器；任务在后端停止时不会丢失，但会暂停到进程恢复。生产部署须启用 [`deploy/rag-anything.service`](deploy/rag-anything.service) 或等效服务管理器的自动拉起，不能只依赖交互式终端进程。
- 未提交的请求级设置实现会为每次智能体问答创建未缓存的 KB 实例并让默认 `hybrid` 改走三通道 RRF；性能验收前须补齐分阶段观测并恢复可复用的配置隔离实例。

## 9. 总结更新矩阵

Current active change `role-aware-frontend-capability-cleanup` is included in the integration checkpoint but remains unarchived. It adds live-permission UI gating, silent denied-route recovery, confirmed-KB preflight for direct knowledge routes, neutral ordinary-page states, inert read-only workflow/AutoRepair surfaces, and static platform read views. Backend RBAC, APIs, migrations, and permission constants were not changed.

| 任务类型 | 必须更新的当前事实 | 近期记录重点 |
|---|---|---|
| 新增 | 能力、入口、模块、数据流、配置、权限、迁移 | 结果、影响范围、验证 |
| 优化 | 直接替换旧行为和指标，不并列保留矛盾描述 | 前后差异与收益 |
| Bug 修复 | 症状、根因、修改边界、预防规则 | 复现与回归验证 |
| 配置/业务/技术变更 | 默认行为、优先级、兼容、部署和迁移要求 | 决策依据与风险 |
| 删除/废弃 | 从稳定现状移除，转入废弃说明 | 原因、遗留适配、清理项 |
| 经验/排查 | 只保留可复用检测、规避和标准流程 | 结论；无持久变化也记录 |

近期任务固定字段为“日期、任务/change、类型、结果、影响范围、验证、经验/风险”。超过 15 条时，将最旧记录按月份和子系统归并为里程碑；每月每子系统最多一条，详细历史继续由 Git/OpenSpec 承载。

## 10. 近期任务记录

| 日期 | 任务/change | 类型 | 结果 | 影响范围 | 验证 | 经验/风险 |
|---|---|---|---|---|---|---|
| 2026-08-04 | 修复 6 个既有测试失败（VLM 快照补桩 + list_kbs 陈旧测试） | Bug 修复/测试 | A 组 3 个：未提交 _resolve_upload_vlm_snapshot 重写依赖 PG，测试按既有模式补桩通过；B 组 3 个：list_kbs 已移除内容更新时间查询（0989d15），就地重写断言 updated_at/created 兜底，并给 stats 批量调用加 try/except 容错（与 knowledge_stats_batch 一致） | raganything/routers/knowledge.py、tests/test_upload_tasks.py、tests/test_chunking_strategy_tracking.py | 6 个定向测试通过；7 个相关套件 119 通过；py_compile 通过 | A 组仅测试补桩，未回退 WIP 重写；B 组行为变更源自 0989d15 有意移除 corpus_revision 当时间戳；test_kb_stats_batch.py 同步 lambda stub 为既有风格未改 |
| 2026-08-04 | 智能体重排回答失败修复与图谱快照优化 | Bug 修复/性能优化 | 根因：`rerank_chunks` 从未导入，启用重排必 `NameError` 并耗尽 8s 预算致失败；已补导入、失败降级融合顺序、预算不足 1.5s 跳过。GraphRetriever 改查询级快照（一次读节点/边、批量取 chunk、种子上限 20），存储访问由数千次降至 2 次 | raganything/query/pipeline.py、raganything/graph_rag/__init__.py | 新增 13 回归测试全绿；相关 95 通过；py_compile、diff check、ruff（仅余既有 E402）通过 | 重排依赖外部 API，预算守卫仅防截止边界；`RRF_RERANK_MIN_BUDGET_SECONDS`、`GRAPH_MAX_SEED_ENTITIES` 可经 env 覆盖；建议重启后端实测 ；预算 8s→12s |
| 2026-08-04 | 上传设置快照 NameError 修复 | Bug 修复 | _create_upload_settings_snapshot 新增 permitted_sections 时漏导入 user_settings 模块，运行时 NameError 致上传 500；补齐 available_sections_for_user 局部导入并直接调用 | raganything/routers/knowledge.py、tests/test_upload_tasks.py | 新增定向回归测试通过；test_upload_tasks + test_user_settings_resolution 71 通过；py_compile 通过；5 项既有失败与本次修复无关 | 未提交 RBAC 分权改动中 _resolve_upload_vlm_snapshot 重写、KB 迁移租约与 list_kbs 内容更新另致 5 项既有测试失败，需另行跟进 |
| 2026-08-04 | 知识库详情页 setCurrentKB 未定义修复 | Bug 修复 | KnowledgeDetailPage.jsx 漏导入 setCurrentKB 致运行时 ReferenceError、页面加载失败；恢复导入并新增 kbApiSourceContract.test.js 源码契约回归 | KnowledgeDetailPage.jsx、kbApiSourceContract.test.js | 前端单测 128/128；用户实测可正常加载；Vite build 受沙箱 esbuild 权限阻塞未实跑 | 详情页两处 setCurrentKB 与 useConfirmedKnowledgeBase 冗余但一致，保持最小修复 |
| 2026-08-04 | venv 旧路径与 lightrag 缺失修复 | Bug 修复/排查 | .venv 建于 RAG-Anything，目录改名后 activate.bat 等硬编码旧路径，cmd 激活未生效致 python 落到共享 base（缺 lightrag-hku/asyncpg）；已改相对定位并钉 `lightrag-hku==1.4.16` | .venv 激活、cmd 启动、requirements | cmd 激活后 python 指向 .venv，lightrag 1.4.16 导入成功 | 68 个 uv 启动器 exe 仍旧路径，重建 venv 根治；勿向 base 装包 |
| 2026-08-04 | frontend node_modules 损坏修复（vite 缺失） | Bug 修复 | dev server 运行期间中断的 npm 全量安装被 Windows 文件锁卡住，esbuild.exe/rollup.node 无法替换，node_modules 残留 10 个半解压目录；`npm ci --offline` 按 lock 从本地缓存重建 306 包（vite 5.4.21 恢复） | frontend 依赖树、npm run dev/build | npm ls 无缺失、vite/esbuild 可执行、单测 127/127；沙箱限制 build 未实跑 | 先停 dev server 再 install/ci；离线安装依赖 D:\DevCache\npm 缓存留存 |
| 2026-08-04 | release integration | 发布整合进行中 | Compose 迁移需显式备份确认；新增 live/ready；恢复保护；HTTP 不暴露 443；真实隔离恢复演练完成 | Compose、Nginx、健康、迁移、恢复、CI | 聚焦 24/24；真实 PG16.3 backup/verify/restore/validate；编译、YAML、OpenSpec、diff 通过 | Docker/staging/TLS 未验；TLS 由批准边缘层提供 |
| 2026-08-04 | `enforce-personal-settings-capabilities` | RBAC/个人设置、进行中 | 权限投影分区与 API；降级新任务继承默认、旧快照不变；前端在 403 后刷新 | 设置 API、请求/上传、Preferences | pytest 22、前端 124、构建与严格校验通过 | 未做真实 PostgreSQL 降级或登录态浏览器验收 |
| 2026-08-03 | `optimize-frontend-navigation-latency` | 前端性能优化/集成检查点、进行中 | 消除页面切换闪现与内容延迟：KB 点击即时跳转；图谱按需加载；轮询收敛为可见性+任务感知；stats TTL 缓存；列表骨架；移除 motion/字体自托管与 hover 预取；nginx assets immutable | 前端 App、页面、utils、main/vite、nginx、样式 | 单测 101/101、生产构建、OpenSpec strict、总结检查、diff check 通过；启动链 483,290 B，较旧快照降 14.2% | 旧快照非同源基线，≥20% 未证实；图谱首开骨架；仍需浏览器与 nginx 验收 |

| 2026-08-03 | 五级 RBAC 分级隔离验证与修复（harden-rbac-isolation） | 安全审计+修复 | 完成角色等级约束、目录白名单、会话/工作流/视觉设置/KB 删除守卫、前端页面门控及矩阵测试 | RBAC、API、知识库、前端门控 | 五角色 API 24/24；新增 39、后端定向 70、前端 81；py_compile、OpenSpec、diff check 通过；Vite build 受环境权限阻塞 | /ws 广播过滤、最后 super_admin 保护、student 汽修问答权限、AuthContext 快照仍有残留风险 |
| 2026-08-03 | 时间显示与上传时区修复 | Bug 修复 | KB 列表不再将 corpus revision 当时间戳；KB/文档/用户时间统一 UTC-aware 与 `formatDate`；迁移 `026` 移除触发器 | 知识库、文档、用户时间、迁移 026 | KB 定向 68+3、前端 73、JSX、diff check 通过；Vite build 受权限阻塞 | `agent.py` 缓存键仍为版本号；部署前执行迁移 026 |
| 2026-08-03 | `role-aware-frontend-capability-cleanup` | 前端 RBAC 能力收敛 / 集成检查点、active | 普通角色页面仅挂载实际可执行操作；无权直达路由按知识库、智能体、汽修、工作流、监控、平台设置顺序静默回退；知识库详情/切块页先确认 KB；汽修空列表不再伪造 autorepair | 前端 App、路由、知识库、智能体、工作流、监控、平台、汽修 | 前端单测 119/119；Vite build 沙箱外通过；RBAC/AutoRepair 定向 66 通过；Admin monitor 9 通过/1 个既有 FakeCache 失败；OpenSpec strict、总结检查、diff check 通过；无 Playwright/Chromium，1440/390 与键盘仅源码/服务器契约检查 | 保留既有 optimize-frontend-navigation-latency 脏工作；未改后端权限矩阵、API 或迁移 |
| 2026-08-03 | 智能体检索参数兼容修复与复测 | Bug 修复/运行验收 | QueryMixin 剥离 RRF 专用参数；24 项保存回读、五种检索模式、三种推理模式及重排/引用开关均完成 | Agent SSE、QueryMixin、SearchTool | 真实 API/SSE 复测；定向 pytest 28 通过 | 原生检索模式不应用个人 RRF 选项；已提交 |
| 2026-08-03 | `improve-agent-query-developer-logs` | 开发可观测性/集成检查点 | 新增一次性 `QUERY_JOURNEY` 终态汇总，稳定聚合检索、媒体、模型和持久化阶段 | Agent timing、RRF/Agentic 检索日志 | 定向及回归 93 通过、1 跳过；`py_compile`、strict OpenSpec、diff check 通过 | 未重启后端做真实 SSE 观察；非法 trace 使用安全别名 |

## 11. 历史里程碑

- **2026-07-31 `restore-agent-query-latency`（性能修复）**：共用 deadline 与租约感知 SSE 清理；RRF 尾延迟 71s 已改 context-only 返回。
- **2026-08-01 `consolidate-frontend-streaming-client`（冗余治理）**：SSE 统一共享认证传输；删除含硬编码凭据的测试文件。
- **2026-08-03 智能体检索冷/热请求复核（性能排查）**：冷请求初始化+改写耗尽 8s；graph 通道占满预算。
- **2026-07-31 repository redundancy governance**: `remove-legacy-upload-runtime-paths`, `remove-legacy-client-paths`, and `harden-repository-hygiene` are complete in the uncommitted worktree. Focused backend validation: 130 passed, 2 skipped; compatibility: 17 passed, 6 skipped; frontend: 68 passed and production build passed. Mirror check, strict OpenSpec validation, and `git diff --check` passed.
- **2026-07-31 audit/plan**: Read-only; no behavior change. Isolate credentials/legacy entries, unify HTTP, then archive evidence-backed artifacts.
- **2026-07-31 upload robustness & recovery**：迁移 `023/024` 补齐租约与可取消队列；worker 按显式任务元数据预检、模型回退、PDF OCR 兜底与完成回写；Embedding 瞬时失败按持久作业重试、环境恢复后自动完成；ODL 输出根目录绝对化并携带 `provenance_ref`。39 页受控重试通过、37/37 文本向量、标签 36/36；生产启用前执行 `023/024`。
- **2026-07**：完成智能体会话上下文升级、视频/多模态处理、文档质量/标签/修复/上传重试、评估流水线和 OpenDataLoader 集成；个人设置与视觉能力继续迭代。
- **详细历史**：优先查看 Git 提交与 [`openspec/changes/archive/`](openspec/changes/archive/)；[`CHANGELOG.md`](CHANGELOG.md) 仅覆盖较早阶段。

## 12. 详细资料索引

- 产品定位与体验：[`PRODUCT.md`](PRODUCT.md)、[`DESIGN.md`](DESIGN.md)
- 主规格：[`openspec/specs/`](openspec/specs/)
- 进行中变更：[`openspec/changes/`](openspec/changes/)
- 架构决策：[`docs/adr/`](docs/adr/)
- 并行协作：[`docs/parallel_collaboration_rules.md`](docs/parallel_collaboration_rules.md)
- OpenDataLoader：[`docs/opendataloader_pdf.md`](docs/opendataloader_pdf.md)、[`docs/opendataloader_supply_chain.md`](docs/opendataloader_supply_chain.md)
- 知识库测试：[`docs/knowledge-base-test-plan.md`](docs/knowledge-base-test-plan.md)