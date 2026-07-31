# RAG-Anything 多对话并行协作规则

## 目的

这份规则用于指导同一项目下多个 Codex 对话并行处理不同任务，目标是同时保证三件事：

- 并行效率
- OpenSpec 流程一致性
- 文件、分支和运行态冲突可控

默认原则只有一句话：

**并行的是多个任务 / 多个 branch / 多个 worktree / 多个 change，不是同一个 change 的多个执行对话。**

## 核心铁律

1. 一条对话只服务一个明确任务。
2. 一个任务只绑定一个 branch，最好只绑定一个 worktree。
3. 一个执行型对话只推进一个 OpenSpec `change`。
4. 同一个 `change` 只能有一个主执行对话推进 `/opsx:apply`。
5. 每次用户请求都必须经过两级调度；使用 OpenSpec 时必须遵守：
   - `/opsx:propose` 之前先调度，至少 2 个专家评审提案质量
   - `/opsx:apply` 之前先调度，至少 3 个专家分别覆盖执行、审查、测试
   - `/opsx:archive` 必须在调度确认后归档
6. 任何对话都不得静默扩 scope。目标、验收、影响范围任一变化，都要停下确认是否拆成新的 sibling `change`。
7. 代码分层必须遵守既有约束：`Router -> Service -> Core -> Infrastructure`，并避免在 `raganything/` 包内直接依赖根目录脚本模块。
8. `PROJECT_SUMMARY.md` 是所有任务的强制首读和收尾更新入口，由唯一协调者串行维护。

## 项目总结协同规则

1. 每个任务启动前完整阅读 `PROJECT_SUMMARY.md`，再按其中的导航定向核验相关事实。
2. 执行者发现长期有效的事实、风险或经验时，在 handoff 中提交“总结增量”：应替换的当前事实、应新增的风险和一条近期任务记录。
3. `PROJECT_SUMMARY.md` 是必须串行的共享资源。除明确指定的唯一协调者外，并行子任务不得直接修改。
4. 协调者在任务完成前先更新当前事实，再追加任务记录；无持久行为变化也要记录结论。
5. OpenSpec `propose` 把总结同步写入最终 tasks；`apply` 验证通过后更新；`archive` 前检查总结已经同步。
6. 总结保持在 350 行、30 KB 以内，近期任务最多 15 条；不得包含密钥、用户数据、运行日志或生成产物。

## 并行单位怎么切

推荐按下面的顺序分片：

1. 先按业务域切。
2. 再按处理链路或页面入口切。
3. 最后按明确文件 ownership 切。

优先选择“改动边界清楚、共享入口少、测试可独立运行”的任务块。对这个仓库，建议固定 5 条并行泳道：

- `auth / RBAC`
- `知识库 / 上传`
- `query / RAG`
- `frontend page / component`
- `infra / migration / CI`

### 推荐切片

| 切片 | 推荐 owner 路径 | 不要顺手带上的共享热点 |
|---|---|---|
| 认证 / RBAC 后端 | `raganything/routers/auth.py`, `raganything/routers/admin.py`, `raganything/services/auth.py`, `raganything/permissions.py`, `raganything/dependencies.py`, 对应测试 | `server.py`, `auth.db`, `migrations/*.sql` |
| 知识库 / 图谱前端 | `frontend/src/pages/KnowledgePage.jsx`, `frontend/src/pages/KnowledgeDetailPage.jsx`, `frontend/src/components/ChunkDetailDrawer.jsx`, `frontend/src/components/KnowledgeGraphD3.jsx` | `frontend/src/App.jsx`, `frontend/src/context/AuthContext.jsx`, `frontend/src/utils/api.js` |
| 工作流前端 | `frontend/src/pages/WorkflowPage.jsx`, `frontend/src/components/workflow/*` | `frontend/src/App.jsx`, `frontend/src/index.css` |
| 智能体 / 汽修场景前端 | `frontend/src/pages/AgentsPage.jsx`, `frontend/src/pages/AgentChatPage.jsx`, `frontend/src/pages/AutoRepair*.jsx`, `frontend/src/hooks/useAutoRepairKB.js` | `frontend/src/App.jsx`, `frontend/src/context/AuthContext.jsx` |
| 知识库 / 查询后端 | `raganything/routers/knowledge.py`, `raganything/query/*`, `raganything/graph_rag/*`, `raganything/hybrid_search/*`, `raganything/services/kb_service.py` | `raganything/dependencies.py`, `server.py` |
| 文档处理 / Worker 链路 | `process_worker.py`, `raganything/processor/*`, `raganything/modalprocessors/*`, `raganything/video_processor/*` | `migrations/*.sql`, `uv.lock`, 共享存储结构 |

### 切片规则

- 如果一个需求要同时修改 API 契约和页面行为，而且接口还没稳定，不要拆成两个对话，保持一个对话纵向打通更稳。
- 如果接口已经稳定，可以把后端和前端拆成两个对话，但必须先固定请求 / 响应格式。
- 不要让一个对话同时跨两个业务域，例如“RBAC + 工作流”或“知识图谱 + 汽修场景”。
- 能并行的最好是叶子模块改动，例如单页 UI、局部组件、独立 service、单组测试。
- 共享状态、迁移、权限常量、启动入口，默认不作为并行切片，默认串行 owner。

## 哪些文件必须串行

下面分成三类：`必须串行`、`高冲突，尽量串行`、`运行态资源必须隔离`。

### 必须串行

这些路径一旦被改动，就应该只允许一个对话拥有：

- `openspec/changes/<same-change>/**`
- `migrations/*.sql`
- `auth.db`
- `.env`
- `uv.lock`
- `package-lock.json`
- `frontend/package-lock.json`
- `requirements.txt`
- `pyproject.toml`
- `.github/workflows/*`
- `scripts/migrate_*.py`
- `AGENTS.md`
- `CLAUDE.md`
- `PROJECT_SUMMARY.md`
- `raganything/permissions.py`
- `raganything/dependencies.py`

原因：

- `openspec/changes/<same-change>/**` 是同一个需求的规范真相源，多个执行对话同时修改会让 proposal / tasks / design 失配。
- `migrations/*.sql` 和 `auth.db` 直接影响数据结构与本地状态，冲突代价高于普通代码冲突。
- 锁文件、依赖清单和环境文件非常容易出现“看起来都能运行，但合并后不可复现”的问题。
- `permissions.py` 和 `dependencies.py` 是权限与依赖注入的全局边界，多个并行改动很容易造成全局回归。
- CI、迁移脚本和项目级约束文件一旦并发修改，回归通常会跨出单个功能边界。

### 高冲突，尽量串行

这些文件技术上可以并行修改，但最好先指定单一 owner：

- `server.py`
- `raganything/services/auth.py`
- `raganything/routers/auth.py`
- `raganything/routers/shared.py`
- `frontend/src/App.jsx`
- `frontend/src/context/AuthContext.jsx`
- `frontend/src/utils/api.js`
- `frontend/src/index.css`
- `package.json`
- `docs/architecture.md`
- 根目录兼容导出脚本，如 `auth.py`, `agent_manager.py`

原因：

- 它们要么是启动入口、路由入口、全局上下文、共享 API 封装，要么是依赖 / 权限 / 认证的中心点。
- 这些文件常常不是“代码冲突”，而是“行为冲突”，例如权限判断、路由挂载、认证状态、请求头格式、依赖版本。

### 运行态资源必须隔离

这些不是代码文件，但并行时必须视为红区资源：

- `auth.db`
- `rag_storage*`
- `uploads/`
- `output*`
- `query_history.json`
- `rag_storage_kb_meta.json`
- 日志文件和日志目录
- 默认端口，如 `8000`、`5173`

建议规则：

- 一对话一 worktree 时，同时给它一套独立的 `WORKING_DIR`、`LOG_DIR` 和测试数据目录。
- 本地多实例并行时，不要共用默认数据库文件和默认知识库存储目录。
- 如果任务涉及上传、处理、回放、导入脚本或监控日志，优先先做运行态隔离，再做代码并行。

## OpenSpec 并行规则

### 什么时候新建 change

以下任一成立，就新建 `change`，不要往旧 `change` 里塞：

- 目标变了
- 验收标准变了
- 影响范围变了
- 需要新增或重写 `proposal.md`, `design.md`, `tasks.md`, `specs/**`
- 新对话只是“相关”，但不在完成同一个验收闭环

### 什么时候复用已有 change

只有同时满足下面条件，才复用已有 `change`：

- 目标不变
- 验收不变
- 只是补完现有 tasks 或修复该 `change` 下的遗留问题
- 不需要扩 spec 边界

### 什么情况下不能并行推进同一个 change

默认不能。

下面任一成立，就禁止多个对话同时推进同一个 `change`：

- 都会改 `openspec/changes/<change-name>/**`
- 都会改相同热点代码
- 都会改迁移、权限模型、共享状态
- 任务存在前后依赖
- 任务共享同一套验收 / 回滚面

同一个 `change` 唯一允许的“并行”，是单轮调度中的专家分工；不是多个执行对话同时各自 `apply`。

## 每个对话的标准作业流程

### 开始前

1. 完整阅读 `PROJECT_SUMMARY.md`，确认当前状态、约束和已知风险。
2. 明确本对话的唯一任务名。
3. 明确 branch 和 worktree。
4. 明确对应 `change` 名。
5. 明确 owner 文件列表和禁止修改文件列表。
6. 明确运行态隔离：`WORKING_DIR`、`LOG_DIR`、测试数据目录、后端端口、前端端口。
7. 先检查是否已有别的对话正在处理同一 `change`、`PROJECT_SUMMARY.md` 或其他串行资源。

### 执行中

1. 只改 owner 文件。
2. 如果必须碰到串行文件，先停下，由协调者改 owner 或转为串行。
3. 如果发现 scope 变化，立即停止裸改，改为新建 sibling `change` 或重新分片。
4. 改动共享入口时，要同步检查依赖方向是否仍然符合 `Router -> Service -> Core -> Infrastructure`。
5. 不要共享运行态目录。并行对话默认不得共用 `auth.db`、`rag_storage*`、`uploads/`、`output*`、日志目录或同一组服务端口。
6. 子任务只维护自己的“总结增量”，不得在未取得协调者 ownership 时修改 `PROJECT_SUMMARY.md`。

### 提交前

1. 先同步主线，再处理冲突。
2. 只验证与本切片相关的测试，不替别的对话做隐式重构。
3. 输出 handoff：变更摘要、已测范围、未改动共享文件、遗留风险。
4. 如果本对话只是评审 / 测试，不要顺手混入实现改动。
5. handoff 必须包含总结增量；协调者完成合并、状态替换和近期记录后，任务才能标记完成。

## 推荐的多对话协作角色

一个复杂需求可以拆成下面几类对话：

- `主执行对话`
  - 拥有 `change`
  - 负责 `/opsx:apply`
  - 负责最终合并前的结果整合
- `实现对话`
  - 只拥有自己那组文件
  - 不扩 scope
  - 不接管别人的串行资源
- `评审对话`
  - 只做审查、架构检查、回归风险识别
  - 不和主执行对话同时改同一文件
- `测试对话`
  - 只负责测试、复现、验证
  - 如果需要修测试，只修改测试 owner 范围或经主执行对话授权

## 开场提示词模板

下面这些模板可以直接在新对话开头使用。把尖括号占位符替换掉即可。

### 模板 A：通用执行对话

```text
你在 RAG-Anything 项目中负责一个独立子任务，请严格遵守以下约束：

- 当前任务：<task-name>
- 当前 branch：<branch-name>
- 当前 worktree：<worktree-path>
- 当前 OpenSpec change：<change-name>
- summary owner：<coordinator-or-none>
- 你的 owner 文件：<file-paths>
- 明确禁止修改：<blocked-paths>
- runtime isolation：<working-dir / log-dir / ports / test-data-dir>

强约束：
- 本对话只服务这 1 个任务和这 1 个 change，不得裸做需求。
- 如果目标、验收、影响范围变化，立即停止并建议新建 sibling change。
- 同一个 change 只能有一个主执行对话推进 /opsx:apply；若发现别的对话已在执行同一 change，本对话自动降级为评审或测试。
- 必须遵守两级调度：/opsx:propose 先至少 2 专家评审，/opsx:apply 先至少 3 专家覆盖执行、审查、测试，/opsx:archive 需调度确认。
- 只修改 owner 文件；若任务需要触碰 server.py、raganything/dependencies.py、raganything/permissions.py、migrations/*.sql、App.jsx、AuthContext.jsx、锁文件、运行态目录或同一 change 文档，先停下再确认 owner。
- 保持依赖方向 Router -> Service -> Core -> Infrastructure；不要在 raganything/ 包内直接依赖根目录脚本模块。

开始前先做三件事：
- 完整阅读 PROJECT_SUMMARY.md
- 确认当前 change 是否已存在且状态正确
- 复述你的 owner 文件、禁止修改文件和 runtime isolation
```

### 模板 B：后端实现对话

```text
你负责 RAG-Anything 后端子任务：<task-name>。

owner 范围：
- <backend-paths>

禁止修改：
- server.py
- raganything/dependencies.py
- raganything/permissions.py
- migrations/*.sql
- auth.db
- openspec/changes/<change-name>/**
- 其他对话已拥有的文件

runtime isolation：
- WORKING_DIR=<path>
- LOG_DIR=<path>
- API_PORT=<port>
- TEST_DATA_DIR=<path>

执行要求：
- 开始前完整阅读 PROJECT_SUMMARY.md；只在 handoff 提交总结增量，不直接修改总结。
- 优先在现有 routers / services / core 模块内修改，不新增根目录业务脚本。
- 保持 Router -> Service -> Core -> Infrastructure 依赖方向。
- 如果需要新增权限、迁移、全局依赖注入或启动入口改动，先停止并升级为串行资源处理。
- 如果任务会触碰上传、知识库存储、处理状态或本地数据库，先确认运行态目录没有和别的对话共享。
- 输出时说明：你改了哪些文件、没改哪些共享文件、需要谁继续接力。
```

### 模板 C：前端实现对话

```text
你负责 RAG-Anything 前端子任务：<task-name>。

owner 范围：
- <frontend-paths>

禁止修改：
- frontend/src/App.jsx
- frontend/src/context/AuthContext.jsx
- frontend/src/utils/api.js
- frontend/src/index.css
- frontend/package-lock.json
- openspec/changes/<change-name>/**
- 其他对话已拥有的文件

runtime isolation：
- FRONTEND_PORT=<port>
- API_BASE_URL=<url>

执行要求：
- 开始前完整阅读 PROJECT_SUMMARY.md；只在 handoff 提交总结增量，不直接修改总结。
- 尽量把改动收敛在 page + local component 范围。
- 如果需要改全局路由、认证上下文、共享 API 封装或全局样式，先暂停并申请串行 owner。
- 不要顺手重排无关页面结构，不要把别的场景页混进来一起改。
- 输出时说明页面影响范围、接口假设、未触碰的全局入口。
```

### 模板 D：评审 / 测试对话

```text
你在本轮中只负责评审 / 测试，不负责主实现。

约束：
- 开始前完整阅读 PROJECT_SUMMARY.md
- 不接管 change 所有权
- 不推进 /opsx:apply 主执行
- 默认不改实现文件，除非主执行对话明确授权

你的目标：
- 找行为回归
- 找架构越层
- 找共享入口误改
- 找迁移 / 权限 / 锁文件 / 运行态资源风险
- 给出是否允许 archive 的结论
- handoff 提交总结增量；无持久变化时明确写出该结论
```

## 协调者的最小任务卡

如果你同时开多个对话，建议先手工写一张很小的任务卡，再把它贴到每个新对话开头：

```text
任务名：
change 名：
branch / worktree：
owner 文件：
禁止修改：
summary owner：
runtime isolation：
依赖哪个上游对话：
交付物：
测试要求：
总结增量：
```

没有这张任务卡，就不要开并行执行对话。

## 快速判断表

| 场景 | 结论 |
|---|---|
| 不同 branch + 不同 worktree + 不同文件集 | 安全，可并行 |
| 不同 branch + 同一文件 | 高冲突，尽量串行 |
| 同一 branch + 多个执行对话 | 不建议 |
| 同一 worktree + 多个执行对话 | 不安全 |
| 同一 change + 多个执行对话 | 禁止 |
| 不同 change，但共享 `migrations/*.sql`、锁文件或运行态目录 | 串行处理 |

## 建议落地方式

最简单的落地方式是：

1. 先由一个主对话做任务分片和 change 规划。
2. 给每个子任务分配独立 branch / worktree / change。
3. 给每个 worktree 分配独立的 `WORKING_DIR`、`LOG_DIR` 和端口。
4. 把上面的模板 A/B/C/D 作为每个对话的开场提示词。
5. 把 `必须串行` 文件和红区运行态资源当成预约资源，不要让多个对话碰运气。

如果执行中拿不准，宁可少并行一个对话，也不要让多个对话同时进入共享入口、共享状态文件和共享运行态目录。
