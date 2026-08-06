# RAG-Anything 项目核心总结

> 本文件是所有项目任务的首要阅读入口和精简知识库。开始任务前必须完整阅读；完成任务前必须同步当前事实并追加复盘记录。它用于导航，不替代代码、迁移、运行配置或 OpenSpec。

## 0. 元信息与使用规则

| 项目 | 当前值 |
|---|---|
| 最后核验日期 | 2026-08-06（Asia/Shanghai） |
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
- 个人设置与上传面板的解析器/分块策略选项由 `GET /users/me/settings/options` 目录下发：解析器 5 种（含安装可用性、未安装置灰）、分块策略 6 种（`fixed_size`/`recursive`/`sentence`/`structure`/`semantic`/`agentic`）；平台允许列表非空时过滤、空=不限制；legacy `fixed` 渲染/保存统一归一化为 `fixed_size`；目录仅在接口失败时回退最小集合。
- 上传任务的 legacy LLM 档案按 `LLM_MODEL`、`LLM_BINDING_MODEL` 顺序解析模型；上传持久化前预检文本与 Embedding 模型。`legacy-vlm` 为兼容 ID，设置页显示实际模型 `qwen-vl-plus`；VLM OCR 兜底覆盖全部 PDF 页，上限不足显式失败。OpenDataLoader 输出根目录绝对化，结果载体携带页覆盖与来源引用，避免转换成功后路径或构造失败。
- 智能体问答的请求级设置快照必须携带 LLM/VLM 的公开 profile 指纹；知识库实例严格校验 LLM 可用性和两类指纹一致性。纯文本问答不依赖 VLM 可用性，只有图片问答和多模态处理要求可用 VLM；SSE 失败会保留错误消息，不再被会话初始化覆盖。面向用户的检索进度仅发送经过中文化的可解释阶段，第三方库的初始化、缓存、模型和存储告警只保留在服务端日志。
- 个人设置桌面工作区采用独立详情滚动：左侧分区菜单保持静止，点击项目仅滚动右侧详情；1100px 以下保留页面滚动与横向分区导航。
- 主侧栏末尾顺序固定为“用户管理、审计日志、个人设置”；权限不足时仅隐藏相应管理入口，个人设置始终位于可见列表末尾。
- 智能体启用“重排”的 RRF 查询可正常工作：失败降级为融合顺序、预算不足 1.5s 跳过；图谱检索按查询级快照执行（一次读节点/边、批量取 chunk、种子上限 20）。；检索预算默认 12s。
- 认证仅使用用户名+密码：`users.email` 列已随迁移 `025` 移除（历史数据不可恢复），注册、管理端用户管理、个人设置与审计详情均不再出现邮箱；`DEFAULT_ADMIN_EMAIL` 环境变量不再支持。

### 进行中

- **按文件类型解析器覆盖**：`parser-per-type-overrides` + `collapse-parser-per-type-options` 已实现未提交，详见 2026-08-04 记录；per-type 解析器优先级、前端按类型三行下拉与折叠摘要已就位。
- **个人设置中心与平台设置策略**：`redesign-personal-settings-center` 规格已归档，实现仍在未提交工作区。`/preferences` 统一“个人设置”，具备独立分区保存、存储值/生效值/来源/约束展示、可执行检索预设和移动端锚点；`/admin/platform` 管理默认值、允许范围和硬上限。
- **分级个人设置权限投影**：`enforce-personal-settings-capabilities` 已实现未提交。实时权限控制分区与 API；降级的新任务继承默认，旧快照不变。
- **知识库级上传默认**：`knowledge-base-ingestion-settings` 已实现未提交。新任务按平台/个人/知识库/单次覆盖解析；KB 稀疏覆盖保存在 `kb_metadata.extra.ingestion_defaults` 并以独立 revision 乐观锁更新，不影响 `vision_embedding` 等现有元数据或历史快照。`GET/PUT /kb/{kb}/ingestion-settings` 分别要求可访问 KB 与 `kb:write`；student 无上传、配置写入或目录加载，assistant、teacher、dept_admin、super_admin 仍受既有 KB 范围约束，平台策略留在 `/admin/platform`。五种上传入口实际使用快照的生效值。
- **视觉模型配置与混合检索链路**：工作区实现模型目录、请求/任务设置快照、作用域缓存和 KB 视觉向量重建。默认 `hybrid` 查询使用不可变的用户检索选项（含图谱深度），不修改共享检索器；KB 重建失败保留旧索引并持续显示失败状态与重试入口。生产迁移及真实 PostgreSQL 多进程验收仍取决于部署环境。
- **部署配置**：Docker 构建上下文排除 `.env`，模型目录使用只读挂载；本机没有 Docker 命令，容器构建和除 `027` 外的部署迁移未在本轮验收。
- **项目总结质量检查**：当前工作区新增标准库检查器、10 项定向测试和 non-blocking GitHub Actions workflow；本地违规仍返回非零，CI 仅用 `continue-on-error` 提示，不作为合并门禁。入口见 [`check_project_summary.py`](scripts/check_project_summary.py) 和 [`project-summary-quality.yml`](.github/workflows/project-summary-quality.yml)。
- **处理中上传任务删除**：`cancel-inflight-upload-tasks` 扩展上传抽屉和 `DELETE /upload/tasks/{task_id}`：排队任务即时删除，处理中/重试任务先进入持久化 `cancelling`，停止 worker、抑制晚到状态/重试写入并清理残留；worker 限时终止再限时强杀，未退出则保留 `cancelling` 交由轮询/恢复收敛。前端仅在服务端确认删除后移除任务。部署前须执行迁移 `024_upload_task_cancellation.sql`；真实 PostgreSQL 多进程验收仍取决于部署环境。
- **上传 claim/PG 瞬断韧性**：`harden-upload-claim-db-resilience` 已实现未提交；claim fencing、15 秒心跳、180 秒 PG 宽限和 300 秒 stale 接管已落地。真实多进程故障注入仍待部署环境验收。

- **前端导航与首屏性能优化**：`optimize-frontend-navigation-latency` 未归档，详见 2026-08-03 记录；启动链 483,290 B，较旧快照降 14.2%（非同源基线未达 ≥20%，待浏览器/nginx 验收）。
- **知识库/智能体空态布局修复**：前端页面仅在加载中或存在当前分页结果时挂载资源卡片网格；零资源、搜索无匹配和列表加载失败直接渲染主内容空态，避免桌面 `1fr` 网格将空态推到底部。未改变五级 RBAC、资源所有权或写操作门控；学生、助教、教师、系部管理员和超级管理员沿用各自可见资源与 CTA 规则。
- **图片召回与会话摘要 Schema**：`fix-agent-media-deadline-and-summary-schema` 已纳入集成检查点（未归档），实现独立媒体预算、超时保留已验证图片和幂等迁移 `027`；本地 PostgreSQL 已连续执行两次并核验摘要列与部分索引，仍待重启后的真实问答验收。
- **视频语义分段索引**：进行中；新视频固定 v2、中文分段、无页码空块；legacy 处理器/整段模板退役，遗留未完成任务取消或以 `video_profile_retired` 失败，历史成品不回填。段字数回写且重试不累计；帧短暂不可读重试，持续失败以可重试 `video_frame_encode_failed` 输出，不走 Docling/OCR 兜底或误报完成。批量以完整任务 ID 隔离暂存，逐文件稳定序号并区分重复跳过/注册失败、清理未入队文件。聚焦 151 通过、2 跳过；真实 Worker/PG 待验收。

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
- **架构取证（2026-08-05）**：后端为模块化单体 + 子进程 Worker；缓存/WS 在进程内。Redis 仅见 Compose；`/ws` 未按用户/KB 过滤。
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

# 前端

# 后端测试

# 项目总结质量；本地严格返回检查结果，CI 仅作非阻断提示

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
| 2026-08-06 | 上传/分页 | UI | 上传折叠；10条/页、分页居中。 | 详情 | 单测/构建 | UI |
| 2026-08-06 | v2 视频帧/批量反馈 | Bug/OpenSpec、进行中 | 帧短暂不可读重试；持续失败为可重试 `video_frame_encode_failed`，Worker 不再经 Docling/OCR 兜底或误报完成；批量注册失败返回逐文件错误；已启用只读上传监控。 | 视频、Worker、上传 | 聚焦 151 通过、2 跳过；编译、strict、总结、diff 通过 | 重启后生效；未改写历史任务，真实 Worker/PG 新上传待验收。 |
| 2026-08-05 | `fix-kb-card-update-time` | Bug/OpenSpec、进行中 | 列表新增 `last_updated_at`，兼容旧字段；卡片/排序优先新字段。`031` 移除遗留触发器，并对重复时间按终态上传/语料提交最佳可得回填。 | KB 列表、卡片、迁移 | 后端 17 通过、PG 1 跳过；前端 155/155、构建、OpenSpec strict 通过 | 现网须在备份和预览后确认 `026`/`031`；历史设置时间无法精确恢复。 |
| 2026-08-05 | Docling ASCII 镜像自愈修复 | Bug 修复 | 残缺镜像 + os.replace 无法覆盖已存在非空目录导致启动失败；锁内先移除残缺镜像再原子替换 | office_parser.py | 定向重建镜像、py_compile、diff check 通过；tiktoken 下载受沙箱网络阻塞未全量启动 | 无 API/迁移变更 |
| 2026-08-05 | `architecture-overview-deep-dive` | 架构文档 | 确认单体 + Worker、PG/LightRAG/工作区与 32 项迁移。 | 全栈/Compose | 源码核验、两级审查、15 页渲染 | Redis 未证实接入；`/ws` 未按用户/KB 过滤；未跑容器/PG/SSE。 |
| 2026-08-05 | `video-semantic-segment-index` | 功能/OpenSpec、进行中 | v2 新上传支持确定性视频分段、时间引用、受控播放和失败补偿清理；已覆盖迁移、认证、CRUD、入口分发与隔离 PG 验收 | 视频处理/分段服务、KB 入口、迁移 029/030、相关 tests | 视频聚焦 105 通过 2 跳过；PG 集成、OpenSpec strict、py_compile、diff check 通过 | Recall@5/MRR 与真实 Worker 样片 E2E 待 5.3；Docker 暂缓 |
| 2026-08-05 | 视频分段中文化/批量字数 | Bug 修复 | 新段中文化、纯视频无页码空块；字数重试不累计，批量任务隔离并按 `file_index` 回填。 | 视频、上传 | v2 聚焦 162 通过、2 跳过；前端 157/157 | 真实 Worker/PG 待验收；历史 legacy 不改。 |
| 2026-08-05 | `knowledge-base-ingestion-settings` | 功能/OpenSpec、进行中 | 个人 -> KB -> 单次三层 ingestion 默认，KB 稀疏值/revision 存 `kb_metadata.extra`，五个上传入口使用不可变快照；学生无写入目录/控件。 | settings、KB API/页面、测试 | 后端 100、前端 25、语法、OpenSpec、diff、构建通过 | 未做真实 PG 多角色和浏览器上传验收。 |
| 2026-08-04 | `parser-per-type-overrides` | 功能/OpenSpec | 个人设置支持按 pdf/office/image 覆盖解析器，运行时按 per-type > 全局优先级；前端目录下发可用性与类型约束 | user settings、parser dispatch、KB upload、Preferences | 后端 75、前端 20 通过；py_compile/OpenSpec validate 通过 | Vite build 和重启后实测待环境；与 parser options delta 需合并 |
| 2026-08-04 | `collapse-parser-per-type-options` | 功能/OpenSpec | 个人设置上传/解析区渐进式折叠：全局下拉改名「默认解析器」并加说明，PDF/办公/图片三行收进 `<details>`「按文件类型指定（可选）」，折叠摘要由新工具 `summarizeParsersByType` 生成（pdf→office→image 规范顺序、忽略空值/未知键、drafts ?? effective 实时反映）；主网格拆两段、折叠区居中；summary 样式并入既有规则（含 dark）；纯前端，后端/接口/数据不变 | `PreferencesPage.jsx`、`index.css`、`parserTypeOptions.js`(+test)、change 工件 | parserTypeOptions 单测 15/15、前端工具全量 152/152（frontend 目录）、JSX/JS 语法解析通过；两级调度（2 提案评审+1 执行+1 审查+1 测试）通过 | Vite build 仍受沙箱 esbuild 目录读取权限 + 自动审批服务故障阻塞，需用户侧运行；与 parser-per-type-overrides 等 3 个 change 的 personal-settings-center delta 同区，归档时合并清理 |
| 2026-08-04 | `restore-chunking-parser-options` | Bug 修复/OpenSpec | 设置整合（1857767）回归修复：个人设置分块策略下拉由硬编码 2 项改为 options 目录 6 项；解析器下拉由空（allowed 空数组被当无选项）改为目录渲染、未安装置灰；上传面板切块选择器恢复加载（`strategies` 不再为空）；`fixed`→`fixed_size` 三处归一化；mineru 安装检查加 10s 超时 | `raganything/services/user_settings.py`、`routers/user_settings.py`、`parser/pdf_parser.py`、`PreferencesPage.jsx`、`KnowledgeDetailPage.jsx`、`chunkingOptions.js`、相关 tests | 后端 29+99、前端 137 通过；py_compile、OpenSpec strict、diff check 通过；两级调度（2 提案评审+1 审查+1 测试）通过；Vite build 受沙箱 esbuild 权限阻塞 | 空数组目录=平台限制应渲染为空、仅接口失败才回退；无 ingestion 用户不构建/返回目录；解析器探测 TTL 60s 且异常记为不可用 |
| 2026-08-03 | `optimize-frontend-navigation-latency` | 前端性能优化、进行中 | 导航与按需加载优化 | frontend | 单测、构建、strict 通过；启动链降 14.2% | 非同源基线；浏览器/nginx 待验收 |
| 2026-08-05 | `harden-upload-claim-db-resilience` | Bug 修复/OpenSpec、进行中 | 区分 PG 瞬断与 claim fencing；修正 asyncpg 0.31 连接池参数；上传/KB mutation 租约窗口、一次性终止与 durable 恢复；四类后台循环指数退避和恢复日志；补充 provenance/owner-generation 回归 | `pg_state_repo.py`、`kb_service.py`、`kb_mutation.py`、`upload_retry.py`、`document_tagging.py`、相关 tests/OpenSpec | 五文件套件 140 通过；无未等待协程；py_compile/OpenSpec strict/diff check；本机 PG 两端点 200 | 未执行真实 PostgreSQL 故障注入、跨进程 owner 争抢及数据重复核验；工作区仍含并行无关未提交改动 |


## 11. 历史里程碑

- **2026-07-31 `restore-agent-query-latency`（性能修复）**：共用 deadline 与租约感知 SSE 清理；RRF 尾延迟 71s 已改 context-only 返回。
- **2026-08-01 `consolidate-frontend-streaming-client`（冗余治理）**：SSE 统一共享认证传输；删除含硬编码凭据的测试文件。
- **2026-08-03 智能体检索冷/热请求复核（性能排查）**：冷请求初始化+改写耗尽 8s；graph 通道占满预算。
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

## 13. 2026-08-06 HNSW ingestion memory hardening

- HNSW OOM (`53200`/context) is terminal `graph_index`: no degraded or auto
  retry; lease-fenced retry-now only. Compose profile, health check, and
  runbook added. Focused 98 tests, py_compile, strict, and diff passed; full
  pytest is blocked by unrelated PG-pool setup. Compose/live PG/MP4 E2E pending.

## 14. 2026-08-06 LightRAG embedding identity and KB isolation

- Added `stabilize-lightrag-embedding-kb-isolation`: upload snapshots now freeze
  a secret-free provider/model/endpoint/dimension identity; LightRAG table
  namespaces, semantic chunking, cache, Worker and query compatibility use the
  same identity. Unsafe `PG_WORKSPACE` overrides fail before initialization.
- Added additive migration `032_kb_text_embedding_identity.sql`, locked KB
  identity registration, legacy unsuffixed-vector blocking, and an admin-only
  read-only diagnostic endpoint. Existing vectors are not copied or rewritten.
- Focused identity/settings/Worker/KB tests: 51 passed; `py_compile` and
  `git diff --check` passed. OpenSpec strict validation passes for this change;
  repository-wide validation still reports three unrelated pre-existing changes.
- Real PostgreSQL two-KB chunk/entity/relation isolation, Worker upload, and
  full pytest remain pending live-environment acceptance.
- 2026-08-06 崩溃修复与本地验收（并入本 change）：`_legacy_rows` 改为
  information_schema 大小写不敏感存在性 + workspace 列检查，缺表/缺列返回 0
  不中止事务（原带引号大写查询无法发现小写 legacy 表，缺表时吞错后事务被
  PostgreSQL 标记 aborted，导致 `InFailedSQLTransactionError` 启动崩溃）；
  诊断端点同步 ILIKE 发现 + 小写 legacy 比较。迁移 `031/032` 已应用本地 PG
  （应用前已备份）。live 验收通过：`python server.py` 启动成功、
  `./rag_storage` 身份注册落库、suffixed 向量表创建、legacy workspace
  （`./rag_storage_新能源`）被 `embedding_legacy_storage_incompatible` 阻止
  且无注册写入、诊断正确标记 legacy 表；focused 26 测试通过。

## 15. 2026-08-06 排查与修复：embedding identity 启动崩溃

- 现象：`python server.py` 启动即 `Application startup failed. Exiting.`，报错为 `pg_embedding_identity.py:26` 的 `InFailedSQLTransactionError`。
- 根因（已实测复现）：`ensure_kb_embedding_identity` 在事务内用带引号大写 `"LIGHTRAG_VDB_*"` 做 legacy 计数；LightRAG 实际以小写未引号建表，该查询必然 `UndefinedTableError`，被 `_legacy_rows` 吞掉但 PostgreSQL 已把整个事务标记为 aborted，第二条 COUNT 即抛 `InFailedSQLTransactionError` 上抛。
- 附带：迁移 `032`（`kb_text_embedding_identities`）当时未应用；当前 PGVectorStorage 使用带 identity 后缀的 suffixed 表，unsuffixed 表仅承载 legacy 数据，修复后 legacy 探测不误伤当前存储。
- 处置：按 OpenSpec 并入 `stabilize-lightrag-embedding-kb-isolation`（任务 2.4/3.1/3.3/4.4）修复并完成本地 PG 验收，详见第 14 节。
