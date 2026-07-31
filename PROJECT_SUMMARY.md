# RAG-Anything 项目核心总结

> 本文件是所有项目任务的首要阅读入口和精简知识库。开始任务前必须完整阅读；完成任务前必须同步当前事实并追加复盘记录。它用于导航，不替代代码、迁移、运行配置或 OpenSpec。

## 0. 元信息与使用规则

| 项目 | 当前值 |
|---|---|
| 最后核验日期 | 2026-07-31（Asia/Shanghai） |
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
- 上传任务的 legacy LLM 档案按 `LLM_MODEL`、`LLM_BINDING_MODEL` 顺序解析模型，当前部署可从 `LLM_BINDING_MODEL=qwen-plus` 生成正确的任务快照；上传会在持久化前预检文本与 Embedding 模型。`legacy-vlm` 仅为兼容配置 ID，设置页显示其实际模型 `qwen-vl-plus`；VLM OCR 兜底默认覆盖全部 PDF 页，配置上限不足时显式失败而不写入部分内容。OpenDataLoader 将相对输出配置规范为绝对运行根目录，解析结果载体同时携带页覆盖与来源引用，避免成功转换后在产物相对化或结果构造阶段失败。
- 智能体问答的请求级设置快照必须携带 LLM/VLM 的公开 profile 指纹；知识库实例严格校验 LLM 可用性和两类指纹一致性。纯文本问答不依赖 VLM 可用性，只有图片问答和多模态处理要求可用 VLM；SSE 失败会保留错误消息，不再被会话初始化覆盖。
- 个人设置桌面工作区采用独立详情滚动：左侧分区菜单保持静止，点击项目仅滚动右侧详情；1100px 以下保留页面滚动与横向分区导航。
- 主侧栏末尾顺序固定为“用户管理、审计日志、个人设置”；权限不足时仅隐藏相应管理入口，个人设置始终位于可见列表末尾。

### 进行中

- **个人设置中心与平台设置策略**：`redesign-personal-settings-center` 已完成规格同步并归档；实现仍在未提交工作区，尚未成为稳定基线。`/preferences` 统一使用“个人设置”，具备独立分区保存、存储值/生效值/来源/约束展示、可执行检索预设和移动端锚点；`/admin/platform` 管理平台默认值、允许范围和硬上限。
- **视觉模型配置与混合检索链路**：工作区实现模型目录、请求/任务设置快照、作用域缓存和 KB 视觉向量重建。默认 `hybrid` 查询会使用不可变的用户检索选项（包括图谱深度），而不修改共享检索器；KB 重建失败会保留旧索引并在页面持续显示失败状态与重试入口。生产迁移及真实 PostgreSQL 多进程验收仍取决于部署环境。
- **部署配置**：Docker 构建上下文排除 `.env`，模型目录使用只读挂载；本机没有 Docker 命令，容器构建和真实 PostgreSQL 迁移未在本轮执行。
- **项目总结质量检查**：当前工作区新增标准库检查器、10 项定向测试和 non-blocking GitHub Actions workflow；本地违规仍返回非零，CI 仅用 `continue-on-error` 提示，不作为合并门禁。入口见 [`check_project_summary.py`](scripts/check_project_summary.py) 和 [`project-summary-quality.yml`](.github/workflows/project-summary-quality.yml)。
- **处理中上传任务删除**：`cancel-inflight-upload-tasks` 在未提交工作区中扩展上传抽屉和 `DELETE /upload/tasks/{task_id}`：排队任务即时删除，处理中或等待自动重试任务先进入持久化 `cancelling`，停止关联 worker、抑制晚到状态/重试写入并按任务来源清理残留；worker 先限时终止、再限时强杀，仍未退出时保留 `cancelling` 和去重占用，交由后续轮询或恢复继续收敛。列表对有明确持久任务 ID 的活动行在能力标记滞后时仍请求任务取消，服务端继续执行上传者、KB 和状态校验；前端仅在服务端确认删除后移除任务。部署前须执行迁移 `024_upload_task_cancellation.sql`；真实 PostgreSQL 多进程取消验收仍取决于部署环境。

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
- 未提交的请求级设置实现会为每次智能体问答创建并销毁未缓存的 KB 实例，并让默认 `hybrid` 在携带检索选项时改走三通道 RRF；scoped BM25 准备发生在通道硬超时之前，旧媒体归属校验还会另取共享 KB 实例。当前耗时未覆盖首次实例初始化且未拆分检索、首 token 和生成阶段，性能验收前须补齐分阶段观测并恢复可复用的配置隔离实例。

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
| 2026-07-31 | `restore-agent-query-latency` | 性能修复/进行中 | 已补齐无内容阶段计时、改写/VLM 路径隐私日志、revision 感知的 query-core 获取、标准/tag/CoT/ReAct/媒体路径共用 deadline 与租约感知 SSE 清理；确定性基准覆盖 acquire、检索、媒体和 SSE 边界。 | Agent SSE、KB cache、query pipeline、RRF/BM25、受控媒体 | 定向 pytest 96 通过、1 个依赖弃用警告；OpenSpec strict、`py_compile`、`git diff --check`、总结检查通过；受控重启后新 PID 的健康端点 200。全量 pytest 仍在约 60% 后复现 pytest 捕获临时文件关闭级联错误。 | 5.2 未勾选：真实 SSE 会向外部 provider 发送检索上下文和派生 prompt，尚无此数据外发授权；确定性基准不得作为生产 provider 测量。 |
| 2026-07-31 | 智能体问答 192 秒延迟诊断 | 性能排查 | 确认 192.31 秒为服务端记录而非前端误计时，约 161.5 秒发生在最终生成前的 RRF/图片召回区段；请求级设置使 KB 每问创建未缓存实例、默认 `hybrid` 改走 RRF 并产生新的 Embedding worker，远程向量调用或其取消传播是最高概率长尾来源；旧媒体校验另触发约 2 秒共享实例初始化 | 智能体 SSE、KB 实例、混合检索、模型 profile | 带时间戳日志、工作区差异、PostgreSQL 元数据与运行配置只读核验；502 块 BM25 约 1.2 秒、最长 15 块实体标注约 4.5 秒、RRF 超时测试 44/44 通过；无业务行为变化 | 当前日志不能把 161.5 秒精确拆到单个内部调用；先补 KB/RRF 通道/Embedding/媒体/首 token 分段指标，再按配置指纹复用重型检索核心并验证真实调用可抢占总 deadline；Embedding 缓存关闭和 worker 冷启会放大长尾，`LLM_TIMEOUT=180` 与 rerank 告警均非本次主因 |
| 2026-07-30 | 上传恢复租约列迁移 | 数据库修复 | 已为现有 PostgreSQL 补齐 `processing_owner`、generation 和 heartbeat 列及索引，解除启动恢复阻断 | `uploaded_files`、迁移 `023` | 列查询、恢复函数成功恢复 2 个任务、定向测试 2/2 | 所有部署须在应用重启前执行迁移 `023` |
| 2026-07-30 | 启动恢复迁移与租约 TTL 修复 | 数据库/队列修复 | 完整执行迁移 `023`；租约 TTL 以整数 interval 绑定，修复 asyncpg 参数类型错误 | 启动恢复、KB 队列、`kb_mutation.py` | 服务启动、健康端点 200、65 项定向测试 | `023` 必须先于重启；旧 processing 任务按 5 分钟心跳回收 |
| 2026-07-30 | Embedding 预检工厂契约修复 | Bug 修复 | worker 使用统一 KB 工厂时显式保留绕过缓存的 Embedding 预检 provider；预检仅在 provider 缺失时回退 | DOCX 等上传任务的模型预检 | `tests/test_upload_retry_resilience.py`、`tests/test_process_worker_lifecycle.py` 定向回归 | `getattr` 的默认参数会被提前求值，不能用于可能不存在的旧属性回退 |
| 2026-07-30 | 上传任务 LLM 模型回退修复 | Bug 修复 | legacy LLM 档案优先读取 `LLM_BINDING_MODEL`，模型目录以实际 `qwen-plus`/`qwen-vl-plus` 显示；上传在文本持久化前预检 LLM 与 Embedding，避免实体抽取才暴露模型 404 | `vision_models.py`、`kb_service.py`、`process_worker.py`、设置页和知识库上传任务 | 模型目录/worker 14 项、上传回归 81 项、后端健康端点 200、`git diff --check` | 已重启后端；已有 degraded 文档应点击“补偿图谱”，无需重新上传 |
| 2026-07-30 | `cancel-inflight-upload-tasks` | 功能/生命周期 | 未完成上传任务可由授权用户删除；处理中和重试等待使用可轮询取消并清理任务来源残留；上传抽屉和文档列表均以服务端任务溯源调用取消接口，确认框以 Portal 下的视口坐标固定居中；有明确任务 ID 的活动列表行在能力标记滞后时仍走任务取消，服务端保留上传者、KB 和状态校验 | 上传 API、worker、重试、任务状态、上传抽屉、文档列表和迁移 `024` | 104 项既有定向后端测试、本次文档列表契约 10 项、67 项前端单测、Vite build、OpenSpec 严格校验、`git diff --check` | 生产启用前必须执行 `024`；确认框不得受抽屉、滚动或动画容器影响；无明确任务 ID 或无上传者权限的活动行不可取消；真实 PostgreSQL 多进程 worker 取消需部署环境补验 |
| 2026-07-30 | 图片理解模型名称展示 | Bug 修复/UI | 将兼容 profile `legacy-vlm` 的用户可见名称和“实际生效”值解析为实际模型 `qwen-vl-plus`，技术详情仍保留配置 ID | 模型目录、个人设置 | 前端单测 66 项、Vite build、模型目录 pytest 10 项、运行时健康端点与目录核验 | 配置 ID 用于兼容，不应作为模型名称展示 |
| 2026-07-30 | PDF OCR 页覆盖与自动关键词完整性 | Bug 修复/数据质量 | 移除 VLM OCR 的 30 页静默截断，按页持久化 OCR 文本；媒体路径引用在有语义块时不再阻断自动关键词，空块、缺文本/向量与纯路径文档仍拒绝 | PDF 上传兜底、文本分块、自动关键词 | 61 项定向 pytest、39 页源文件与旧索引覆盖差异核验、关键词任务完成、后端健康端点 200 | 旧版已入库的截断文档需完整重处理，不能在原索引上补写 |
| 2026-07-30 | 截断 PDF 重处理运行事件 | 运行/数据恢复 | 已移除指定文档的不完整索引；删除接口同步清理上传暂存源，未能继续重入库，已取消指向缺失源文件的队列记录并恢复后端 | 单个文档索引、上传元数据与队列 | 端口监听、健康端点 200、队列记录取消核验 | 重处理前必须先保存独立副本或由用户重新选择源文件；不得假设删除文档会保留 `uploads/` 暂存文件 |
| 2026-07-31 | 上传租约与完成状态加固 | Bug 修复/运行验证 | 配额租约允许原 owner 在未被接管时续期；Worker 将真实租约丢失或心跳异常标为可重试 `quota` 错误；完成回写按显式任务元数据匹配并在缓存未同步时直读 PG，避免 `processed_document_status_missing` 误失败 | `user_settings.py`、`process_worker.py`、`kb_service.py`、上传状态和自动标签 | 定向 pytest 38 通过、静态检查/OpenSpec 严格校验通过；后端重启健康；保留的 39 页 PDF 受控重试后完成，37 块、页 32-39 文本逐页命中、标签任务完成（36/36 可标注块） | 不把内部 `track_id` 当作队列任务 ID；延迟心跳必须由 ID+owner 围栏判断，跨进程完成状态以 PG 为准 |
| 2026-07-31 | 上传外网恢复与 ODL 结果契约修复 | Bug 修复/运行恢复 | Embedding 瞬时连接失败按持久作业重试；后端在具备模型网络权限的环境恢复后自动完成原任务。ODL 输出根目录先绝对化，`PageTrackedContent` 接收并保存 `provenance_ref`，消除转换成功后的路径与构造异常 | 上传预检/自动重试、`opendataloader_parser.py`、`office_parser.py` | DashScope 最小 Embedding 返回 1024 维；ODL 真实 3 页解析 3/3 成功；目标 39 页 PDF 完成，37/37 文本与向量、0 空向量、标签 36/36，末页 32-38 与源文 99.4%-99.8% 相似，第 39 页 122/124 字连续命中；后端健康 200 | 外部服务故障不得绕过预检；持久重试依赖存活的后端调度器，部署须由服务管理器自动拉起；文本 Embedding 尚未进入不可变任务快照，后续需单独消除重试期间配置漂移风险 |
| 2026-07-30 | 上传取消 worker 有界终止 | Bug 修复 | worker 终止后两次限时等待，强杀后仍存活则保留 `cancelling`，不清理内容或解除去重 | `kb_service.py`、上传生命周期测试 | 104 项上传生命周期定向 pytest、`py_compile` | 取消 coordinator 不能无界等待；未收敛状态必须保持可轮询 |

| 2026-07-31 | 文本与图片理解模型名称显示 | UI 优化 | 个人设置与平台默认模型下拉优先显示 profile 的纯 model 名称，移除默认类型前缀和不可用后缀；保留后端 display_name 兼容契约 | frontend/src/pages/PreferencesPage.jsx、frontend/src/pages/AdminPlatformPage.jsx | 前端单元测试 67 项通过；Vite production build 通过；git diff --check 通过 | 不修改模型目录 API 字段，禁用状态仍由 disabled 与详情区域表达 |
| 2026-07-31 | 知识库问答失败、提示闪退与推理卡死修复 | Bug 修复/运行操作 | 请求级设置快照补齐模型 profile 指纹，修复 `get_kb` 初始化失败；纯文本问答解除对 VLM 可用性的错误依赖；补齐流式请求 `getToken` 导入；稳定 toast 回调并持久展示 HTTP/SSE 错误；RRF 子通道到期后隔离不响应取消的任务并使用可用通道降级返回，外层取消同步回收通道任务；智能体检索增加总时限和断连回收；前端收到 `done/error` 即停止读流，异常 EOF、错误和取消均结束推理状态；随后按用户要求停止本地后端 | `user_settings.py`、`kb_service.py`、`agent.py`、`hybrid_search/__init__.py`、`App.jsx`、`AgentChatPage.jsx`、本地端口 `8001` | 后端定向 pytest 64 项及终止链路复验 55 项、前端单测 67 项、Vite production build、`py_compile`、`git diff --check` 通过；停止后 `8001` 无监听且健康端点不可达，`5173` 仍返回 200 | 图片问答仍严格要求 VLM；真实模型回答质量仍取决于模型服务状态；检索通道超时不得等待协程取消完成，SSE 终止事件或异常 EOF 均不得保留无限加载状态；持久上传重试会暂停到后端恢复 |
### 2026-07-31 验证更新

`restore-agent-query-latency` 的 5.2 已完成受控验收：最终新 listener 健康 200 后，使用已授权、已处理、标准模式智能体执行 1 cold 和 20 次顺序 warm 常规 SSE；21/21 为 HTTP 200、`done` 且有 token，端到端 P95 为 23.120 秒。query-core 为 1 miss/20 hit，21 次 LLM 首末 token、持久化和 total=ok 均恰好记录一次，检索三通道及媒体均成功；日志和汇总未记录查询、SSE 内容、标识符、凭据或主机。此前 RRF 通道完成后仍枚举全图导致约 71 秒尾延迟，现使 context-only 路径在保留收敛余量的来源富化后返回，并覆盖慢来源取消及来源标签回归。

## 11. 历史里程碑

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
