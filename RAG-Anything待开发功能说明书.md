# RAG-Anything 待开发功能说明书（开发蓝图）

> **用途**: 开发人员直接据此编码的功能规格文档  
> **配套**: 《RAG-Anything已实现功能说明书》(当前可演示) + 《技术方案与功能参数说明书》(完整交付蓝图)  
> **日期**: 2026年6月10日  
> **标记**: 🔄=第2周 | 🎯=第3-4周 | ❌=远期规划  
> **可行性**: ✅=可行 | ⚠️=时间偏紧 | 🔴=需降级 | 📊=性能数字待实测

---

## 目录

1. [开发总览](#1-开发总览)
2. [第2周 🔄 进行中](#2-第2周-进行中)
3. [第3周 🎯 计划交付](#3-第3周-计划交付)
4. [第4周 🎯 计划交付](#4-第4周-计划交付)
5. [远期规划 ❌](#5-远期规划)

---

## 1. 开发总览

| 优先级 | 数量 | 时间 | 说明 |
|--------|------|------|------|
| 🔄 第2周 | 3 项 | 6.23-6.29 | 正在开发 |
| 🎯 第3周 | 6 项 | 6.30-7.06 | 核心功能交付 |
| 🎯 第4周 | 5 项 | 7.07-7.13 | 企业版完善 |
| ❌ 远期 | 7 项 | 待定 | 按需扩展 |

---

## 2. 第2周 🔄 进行中

### 2.1 HyDE + Multi-Query 查询改写独立模块 ✅

**可行性**: ✅ 可行 — 本质是 LLM 文本生成 + 去重融合，基础改写代码已有。

**技术规格**:

| 参数 | 值 | 说明 |
|------|-----|------|
| HyDE 假设文档数 | n=3 | 每个查询生成 3 个假设文档 |
| HyDE temperature | 0.7 | 生成多样性 |
| HyDE max_tokens | 512 | 每个假设文档最大长度 |
| Multi-Query 变体数 | n=3 | 每个查询生成 3 个变体 |
| Multi-Query temperature | 0.8 | 变体多样性 |
| Multi-Query max_tokens | 128 | 每个变体最大长度 |
| 融合策略 | 原始 query + 3 HyDE + 3 Multi-Query | 去重 → 向量检索 → RRF 融合 |

**文件规划**:

```
raganything/
└── query_rewriter.py          # 新建文件
    ├── class QueryRewriter:
    │   ├── rewrite_hyde(query) → List[str]
    │   ├── rewrite_multiquery(query) → List[str]
    │   └── rewrite(query, strategies=["hyde","multiquery"]) → List[str]
    └── async def rewrite_and_search(query, rag_instance) → List[Chunk]

server.py                       # 修改
└── /api/query/stream           # 在查询管线中调用 QueryRewriter
```

**实现步骤**:

1. 创建 `raganything/query_rewriter.py`
2. 实现 `QueryRewriter` 类，内部调用 `llm_model_func` 生成 HyDE 和 Multi-Query
3. 添加环境变量 `QUERY_REWRITE_STRATEGIES=hyde,multiquery` 控制开关
4. 在 `server.py` 的 `/api/query/stream` 和 `/api/agents/{id}/query/stream` 中集成
5. 在 `/api/settings` 中暴露配置项

**验收标准**:
- [ ] 输入 "年假政策" → 生成 3 个假设文档 + 3 个变体查询
- [ ] 召回率相比单查询提升 ≥ 20%
- [ ] 可通过环境变量关闭/启用各策略
- [ ] 查询改写不超时（30s），超时自动降级为原始查询

---

### 2.2 后端模块化重构（5 Router） ✅

**可行性**: ✅ 可行 — 纯代码搬运不改逻辑，每个文件 < 400 行。

**技术规格**:

| Router 文件 | 负责端点 | 预计行数 | 依赖 |
|------------|---------|---------|------|
| `routers/auth.py` | /api/auth/* | ~300 | auth.py |
| `routers/knowledge.py` | /api/knowledge/*, /api/upload/* | ~400 | process_worker.py |
| `routers/agent.py` | /api/agents/* | ~350 | agent_manager.py |
| `routers/query.py` | /api/query/*, /api/query/stream | ~300 | query.py |
| `routers/admin.py` | /api/admin/*, /api/settings, /api/monitor/* | ~300 | auth.py |

**文件规划**:

```
raganything/
└── routers/                    # 新建目录
    ├── __init__.py
    ├── auth.py                 # from server.py 解耦
    ├── knowledge.py            # from server.py 解耦
    ├── agent.py                # from server.py 解耦
    ├── query.py                # from server.py 解耦
    └── admin.py                # from server.py 解耦

server.py                       # 精简为 app 创建 + router 注册 + startup/shutdown
```

**实现步骤**:

1. 创建 `raganything/routers/` 目录
2. 逐个提取路由函数到对应 Router 文件
3. 提取公共依赖（`limiter`, `get_current_user`, `verify_kb_access`）到 `dependencies.py`
4. 在 `server.py` 中 `app.include_router()` 注册
5. 确保所有现有 API 测试通过

**验收标准**:
- [ ] 每个 Router 文件 < 400 行
- [ ] `server.py` < 300 行
- [ ] 所有现有 API 端点路径不变
- [ ] `pytest` 全部通过

---

### 2.3 Agentic RAG 多步推理引擎 ⚠️

**可行性**: ⚠️ 时间偏紧 — ReAct 循环+工具调用+错误恢复完整实现需 1.5-2 周。建议第 2 周先交付最小版本：2 步推理 + Search 工具，第 3 周完善 Calculator + DB 工具。

**技术规格**:

| 参数 | 值 | 说明 |
|------|-----|------|
| 推理模式 | ReAct / Chain-of-Thought | 可配置 `AGENT_MODE` |
| 最大推理步数 | max_steps=5 | 超出返回中间结果 |
| 单步超时 | 30s | 超时跳过该步 |
| 内置工具 | Calculator / WebSearch / DatabaseQuery | 可扩展 |

**ReAct 循环逻辑**:

```
用户提问
  ↓
Step 1: Thought → "我需要检索年假相关政策"
        Action → search("年假政策")
        Observation → [检索到 5 个相关分段]
  ↓
Step 2: Thought → "信息不够完整，需要查具体天数"
        Action → search("年假天数 工龄")
        Observation → [检索到 3 个补充分段]
  ↓
Step 3: Thought → "信息已足够，可以综合回答"
        Action → finish("根据公司规定...")
```

**文件规划**:

```
raganything/
└── agentic_rag.py              # 新建文件
    ├── class AgenticRAG:
    │   ├── tools: List[Tool]
    │   ├── max_steps: int
    │   ├── mode: "react" | "cot"
    │   ├── async run(query, kb_ids) → AgentResult
    │   └── _parse_action(response) → (tool_name, tool_input)

    └── class Tool:              # 工具抽象
        ├── name: str
        ├── description: str
        ├── parameters: dict     # JSON Schema
        └── async execute(input) → str

server.py
└── /api/query                  # 添加 agent_mode 参数
```

**实现步骤**:

1. 创建 `raganything/agentic_rag.py`
2. 实现 ReAct 循环（Thought → Action → Observation 循环）
3. 实现内置工具: `SearchTool`, `CalculatorTool`
4. 预留 `DatabaseQueryTool` 接口
5. 在 `server.py` 的查询端点中添加 `agent_mode` 参数
6. 添加环境变量 `AGENT_MODE=react` 和 `AGENT_MAX_STEPS=5`

**验收标准**:
- [ ] 输入 "去年销售额最高的产品是什么，比第二名高多少%" → Agent 自动分步检索+计算
- [ ] max_steps=5 时不会无限循环
- [ ] 单工具调用超时 30s 后自动跳过
- [ ] 不支持的问题明确告知用户

---

## 3. 第3周 🎯 计划交付

### 3.1 RRF 显式三路融合检索 ✅

**可行性**: ✅ 可行 — RRF 公式仅一行 `Σ 1/(k+rank)`，BM25 和向量已有，图谱通道基础已有。

**技术规格**:

| 通道 | 算法 | 参数 | 权重 | 独立 top_k |
|------|------|------|------|-----------|
| BM25 关键词 | Okapi BM25 | k1=1.5, b=0.75 | w=0.3 | top_k=50 |
| 向量语义 | Cosine(HNSW) | M=16, ef=200 | w=0.5 | top_k=100 |
| 知识图谱 | 实体遍历 | LightRAG 引擎内置 | w=0.2 | top_k=30 |

**RRF 公式**:

```
RRF_score(chunk) = Σ (1 / (k + rank_i))
其中 k=60, rank_i 是 chunk 在第 i 个通道中的排名
```

**文件规划**:

```
raganything/
└── hybrid_search.py            # 新建文件
    ├── class HybridSearchEngine:
    │   ├── bm25_index: BM25Okapi
    │   ├── vector_index: HNSW
    │   ├── graph_index: NetworkX
    │   ├── async search(query, top_k=100) → List[ScoredChunk]
    │   ├── _bm25_search(query) → List[(chunk_id, score)]
    │   ├── _vector_search(query) → List[(chunk_id, score)]
    │   ├── _graph_search(entities) → List[(chunk_id, score)]
    │   └── _rrf_fuse(results, k=60) → List[ScoredChunk]
    └── class ScoredChunk:
        ├── chunk_id, content, score, sources: List[str]
```

**实现步骤**:

1. 安装 `rank-bm25`（已有）
2. 创建 `raganything/hybrid_search.py`
3. 实现 BM25 索引构建（文档入库时触发）
4. 实现 `_rrf_fuse()` 融合算法
5. 在查询管线中替换当前 hybrid 模式为显式三路 RRF
6. 添加环境变量 `RRF_K=60`, `BM25_WEIGHT=0.3`, `VECTOR_WEIGHT=0.5`, `GRAPH_WEIGHT=0.2`

**验收标准**:
- [ ] 三路独立检索并行执行
- [ ] RRF 融合后 Hit Rate 相比单通道提升 ≥ 50%
- [ ] P95 延迟 < 200ms（三路并行）
- [ ] BM25 索引支持增量更新（新文档入库时自动更新）

---

### 3.2 GraphRAG 知识图谱增强检索 ✅

**可行性**: ✅ 可行 — 实体抽取已有（LightRAG processor），图谱存储已有（NetworkX），需做的是检索管线集成和前端可视化。

**技术规格**:

| 参数 | 值 | 说明 |
|------|-----|------|
| 实体抽取 | LightRAG 引擎内置 | 置信度由引擎内部判断 |
| 关系深度 | 2 | 1-2 跳邻居遍历 |
| 单文档最大实体数 | 50 | 超过截断 |
| 图谱检索模式 | 实体匹配 → 邻居遍历 → chunk 召回 | |

**文件规划**:

```
raganything/
└── graph_rag.py                # 新建文件
    ├── class GraphRAG:
    │   ├── entity_extractor: Callable
    │   ├── relation_extractor: Callable
    │   ├── graph: NetworkX DiGraph
    │   ├── async extract_entities(text) → List[Entity]
    │   ├── async extract_relations(entities) → List[Relation]
    │   ├── build_graph(doc_id, entities, relations)
    │   ├── search(query_entities, depth=2) → List[chunk_id]
    │   └── visualize_subgraph(entity_ids) → dict (nodes+edges)
```

**实现步骤**:

1. 创建 `raganything/graph_rag.py`
2. 实现基于 LLM 的实体关系抽取（调用 `llm_model_func`）
3. 实现 NetworkX 有向图存储和遍历
4. 在 `hybrid_search.py` 中集成图谱通道（作为第三路检索）
5. 前端 D3 力导向图渲染图谱检索结果

**验收标准**:
- [ ] 输入 "张三参与了哪些项目" → 图谱检索返回张三相关的项目实体和文档
- [ ] 1-2 跳邻居遍历正确
- [ ] 图谱可视化（D3 力导向布局）
- [ ] 图谱随新文档入库自动更新

---

### 3.3 可视化工作流 DAG 引擎 🔴

**可行性**: 🔴 需降级 — 原方案（41 种节点 + cron 调度 + 完整执行引擎）实际需要 **3 周**，不是 1 周。

**建议 MVP 版本**（第 3 周可交付）：
- 节点类型缩减到 **5-8 种**（数据源: 文件上传+数据库 / 清洗: 筛选+去重 / AI: PDF解析+分段+向量化 / 输出: 导入知识库）
- **仅支持手动执行**，cron 调度延后到远期
- 节点配置用简单 JSON 表单，不做动态表单
- 完整版 41 种节点 + 周期调度 → 远期规划

**技术规格**:

| 参数 | 值 | 说明 |
|------|-----|------|
| 前端库 | React Flow | 节点拖拽 + 贝塞尔连线 |
| 节点类型 | 数据源(6) + 清洗算子(17) + AI算子(15) + 输出(3) | 共 41 种 |
| 布局 | 自由/网格(20px) | 可切换 |
| 连线规则 | DAG，禁止环路 | 拓扑排序校验 |
| 周期调度 | cron 表达式 | 天/周/月 |
| 并发限制 | 同项目 max 3 任务 | 超出排队 |

**数据库表设计**:

```sql
CREATE TABLE workflows (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id UUID NOT NULL,
    name VARCHAR(200) NOT NULL,
    description TEXT,
    nodes JSONB NOT NULL,       -- [{id,type,config,position}]
    edges JSONB NOT NULL,       -- [{source,target,condition}]
    schedule VARCHAR(100),      -- cron expression
    is_active BOOLEAN DEFAULT true,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE workflow_runs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    workflow_id UUID REFERENCES workflows(id) ON DELETE CASCADE,
    status VARCHAR(20) DEFAULT 'pending',  -- pending/running/completed/failed
    started_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ,
    node_results JSONB,         -- [{node_id, status, input_rows, output_rows, duration_ms, error}]
    trigger_type VARCHAR(20),   -- manual/schedule
    created_at TIMESTAMPTZ DEFAULT NOW()
);
```

**前端组件树**:

```
frontend/src/
└── pages/
    └── WorkflowEditor/
        ├── index.tsx                # 主页面
        ├── Canvas.tsx               # React Flow 画布
        ├── NodePalette.tsx          # 左侧算子面板
        ├── NodeConfigPanel.tsx      # 右侧节点配置抽屉
        ├── nodes/                   # 自定义节点组件
        │   ├── DataSourceNode.tsx
        │   ├── CleanNode.tsx
        │   ├── AINode.tsx
        │   └── OutputNode.tsx
        ├── hooks/
        │   ├── useWorkflow.ts       # 工作流状态管理
        │   └── useWorkflowRun.ts    # 运行状态
        └── utils/
            ├── validateDAG.ts       # DAG 环路检测
            └── nodeTemplates.ts     # 节点模板定义
```

**实现步骤**:

1. 安装 `reactflow` 包
2. 创建数据库迁移脚本（`workflows` + `workflow_runs` 表）
3. 创建后端 CRUD API: `/api/workflows`
4. 创建后端执行引擎: `workflow_engine.py`
5. 前端构建 `WorkflowEditor` 页面
6. 实现节点拖拽 + 连线 + 配置面板
7. 实现 DAG 验证（环路检测）
8. 实现周期调度（APScheduler / Celery Beat）

**验收标准**:
- [ ] 可从面板拖拽节点到画布
- [ ] 节点间可连线，自动检测并阻止环路
- [ ] 点击节点弹出配置面板
- [ ] 可手动执行工作流并查看每节点运行结果
- [ ] cron 定时任务正确触发

---

### 3.4 SSO/OIDC 企业统一认证 ✅

**可行性**: ✅ 可行 — authlib 库成熟，Keycloak/OIDC 标准协议，现有 JWT 认证体系兼容。

**技术规格**:

| 参数 | 值 | 说明 |
|------|-----|------|
| 协议 | OIDC (OpenID Connect) | 基于 OAuth 2.0 |
| 支持 Provider | Keycloak / LDAP / OAuth 2.0 | |
| 配置方式 | 环境变量 | OIDC_ISSUER, OIDC_CLIENT_ID, OIDC_CLIENT_SECRET |
| 用户映射 | OIDC sub → 本地 user_id | 首次登录自动创建本地用户 |
| 兼容性 | 保留现有 JWT 登录 | 两种方式并行 |

**文件规划**:

```
auth.py                         # 修改
├── class OIDCProvider:
│   ├── __init__(issuer, client_id, client_secret)
│   ├── async get_authorization_url(redirect_uri) → str
│   ├── async exchange_code(code, redirect_uri) → token
│   ├── async get_user_info(access_token) → dict
│   └── async verify_token(token) → bool

server.py                       # 修改
├── /api/auth/oidc/login        # 重定向到 OIDC Provider
├── /api/auth/oidc/callback     # OIDC 回调处理
└── /api/auth/login             # 保留现有（兼容）
```

**实现步骤**:

1. 安装 `python-jose` 或使用 `authlib`
2. 在 `auth.py` 中实现 `OIDCProvider` 类
3. 添加 OIDC 回调路由
4. OIDC 用户首次登录自动创建本地用户记录
5. 前端登录页添加"企业账号登录"按钮
6. 添加环境变量 `OIDC_ENABLED=true`, `OIDC_ISSUER`, `OIDC_CLIENT_ID`, `OIDC_CLIENT_SECRET`

**验收标准**:
- [ ] 可通过 Keycloak 账号登录
- [ ] 首次 OIDC 登录自动创建本地用户
- [ ] 现有用户名密码登录不受影响
- [ ] OIDC Token 过期后自动刷新

---

### 3.5 多轮对话上下文管理 ✅

**可行性**: ✅ 可行 — conversations API 已有，滑动窗口+摘要压缩是纯逻辑层改动。

**技术规格**:

| 参数 | 值 | 说明 |
|------|-----|------|
| context_window | 10 轮 | 保留最近 10 轮对话 |
| token_budget | 2000 | 超出时触发摘要压缩 |
| 压缩策略 | extractive(前3轮) + abstractive(后续) | |
| 摘要模型 | 同 LLM_MODEL | 复用现有 LLM |

**实现步骤**:

1. 在 `agent_manager.py` 的对话管理中添加 `context_window` 和 `token_budget`
2. 实现 `compress_history(messages) → compressed_context` 方法
3. 在 SSE 流式查询中注入压缩后的上下文
4. 前端显示"上下文长度指示器"

**验收标准**:
- [ ] 超过 10 轮对话自动压缩
- [ ] 压缩后 Token 节省 ≥ 60%
- [ ] 压缩后的上下文仍能正确回答关联问题

---

### 3.6 密钥管理与依赖安全扫描 ✅

**可行性**: ✅ 可行 — 两个都是配置+CI 集成类任务，无技术难点。

**密钥管理** (`t15`):
- secrets.token_hex(32) 自动生成（已有）
- .env 文件加入 .gitignore + .dockerignore（已有）
- mask_sensitive_data() 日志脱敏（已有）
- **待做**: 密钥轮换策略文档 + CI 环境变量注入指南

**依赖安全扫描** (`t16`):
- `pip-audit` + `npm audit` CI 集成
- CVE 数据库定期比对（Trivy / Dependabot）
- 高危漏洞阻断 PR 合并

**实现步骤**:
1. 添加 `.github/workflows/security-scan.yml`
2. 配置 pip-audit + npm audit 自动运行
3. 高危漏洞自动创建 Issue

**验收标准**:
- [ ] CI 自动运行安全扫描
- [ ] 高危漏洞阻断 PR
- [ ] 密钥无硬编码（CI 检查）

---

### 3.7 核心测试覆盖

**当前状态**: 已有基础测试（`tests/test_auth.py`, `tests/test_core_modules.py`），需扩展。

**技术规格**:

| 测试类型 | 目标覆盖 | 框架 |
|---------|---------|------|
| 认证模块 | 100% | pytest + pytest-asyncio |
| 知识库 CRUD | 80% | pytest + httpx TestClient |
| 文档上传处理 | 80% | pytest + mock |
| 智能问答管线 | 80% | pytest |
| 智能体管理 | 80% | pytest |
| 分块策略 | 90% | pytest |

**新增测试文件**:

```
tests/
├── test_auth.py                # 已有，扩展
├── test_core_modules.py        # 已有，扩展
├── test_knowledge_api.py       # 新建
├── test_upload.py              # 新建
├── test_query_pipeline.py      # 新建
├── test_agent_manager.py       # 新建
├── test_chunking_strategies.py # 新建
└── conftest.py                 # 新建（fixtures）
```

**实现步骤**:

1. 创建 `conftest.py`，提供 `test_app`, `test_client`, `auth_headers` 等 fixtures
2. 逐个模块编写测试
3. CI 集成: `.github/workflows/test.yml` 或 GitLab CI
4. 覆盖率报告: `pytest --cov=raganything --cov-report=html`

**验收标准**:
- [ ] 整体覆盖率 ≥ 60%
- [ ] 认证模块覆盖率 100%
- [ ] CI 自动运行测试
- [ ] PR 合并前必须通过所有测试

---

## 4. 第4周 🎯 计划交付

### 4.1 审计日志系统 ✅

**可行性**: ✅ 可行 — SQLite 表 + 中间件，半天工作量，无技术难点。

**技术规格**:

```sql
CREATE TABLE audit_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER,
    username TEXT,
    ip_address TEXT,
    action TEXT NOT NULL,           -- create/read/update/delete/login/logout/export
    resource_type TEXT,             -- document/knowledge_base/agent/user/settings
    resource_id TEXT,
    detail JSON,                    -- {field_changed, old_value, new_value}
    status TEXT DEFAULT 'success',
    user_agent TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_audit_user ON audit_logs(user_id);
CREATE INDEX idx_audit_action ON audit_logs(action);
CREATE INDEX idx_audit_created ON audit_logs(created_at);
CREATE INDEX idx_audit_resource ON audit_logs(resource_type, resource_id);
```

**API 端点**:

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | /api/audit-logs | 查询（分页+筛选） |
| GET | /api/audit-logs/export | 导出 CSV |

**查询参数**: `user_id`, `action`, `resource_type`, `start_date`, `end_date`, `page`, `page_size`

**中间件注入**:

```
# 在每个 API 请求处理完成后自动记录
@app.middleware("http")
async def audit_middleware(request, call_next):
    response = await call_next(request)
    # 异步写入审计日志，不阻塞响应
    background_tasks.add_task(write_audit_log, request, response)
    return response
```

**实现步骤**:

1. 创建 `audit.py`
2. 数据库迁移（新建 `audit_logs` 表）
3. 实现审计中间件
4. 实现查询/导出 API
5. 前端添加审计日志页面

**验收标准**:
- [ ] 所有 API 调用自动记录
- [ ] 可按用户/操作/资源/时间筛选
- [ ] 支持 CSV 导出
- [ ] 审计日志不影响 API 响应时间（异步写入）

---

### 4.2 文档解析管线升级（Docling/Marker 集成） ⚠️

**可行性**: ⚠️ 可行但注意依赖冲突 — Docling 和 Marker 各自依赖不同版本的 PyTorch/transformers，可能冲突。建议作为**可选依赖**：`pip install raganything[docling]`，不默认安装。parser 适配器模式已有，接入成本低。

**技术规格**:

| 引擎 | 优势 | 适用场景 |
|------|------|---------|
| MinerU 2.0 (当前) | 版面分析+OCR | PDF/扫描件 |
| Docling (新增) | IBM 开源，表格精度高 | 表格密集型 PDF |
| Marker (新增) | 快速、轻量 | 纯文本文档批量处理 |

**配置方式**: 环境变量 `PARSER_BACKEND=mineru|docling|marker|auto`

**自动选择逻辑**:
```
if parser == "auto":
    if 文档包含 > 10 个表格 → Docling
    elif 文档 > 50 页纯文本 → Marker
    else → MinerU (默认)
```

**实现步骤**:

1. 安装 `docling` 和 `marker-pdf` 包（可选依赖）
2. 在 `raganything/parser.py` 中添加 `DoclingParser` 和 `MarkerParser` 适配器
3. 实现 `auto` 模式自动选择逻辑
4. 在 `/api/settings` 中暴露 `parser_backend` 配置

**验收标准**:
- [ ] 三种引擎可切换
- [ ] auto 模式正确选择引擎
- [ ] 解析精度相比单引擎提升 40%+

---

### 4.3 前端 Zustand + i18n 国际化

**当前状态**: 前端使用 React Context 管理状态，无国际化。

**技术规格**:

| 项目 | 现有 | 目标 |
|------|------|------|
| 状态管理 | React Context | Zustand |
| 国际化 | 无 | react-i18next |
| 支持语言 | 中文 | 中文 + 英文 |

**Zustand Store 设计**:

```typescript
// frontend/src/stores/
├── useAuthStore.ts         // 认证状态
├── useKnowledgeStore.ts    // 知识库/文档状态
├── useAgentStore.ts        // 智能体状态
├── useQueryStore.ts        // 问答状态
└── useUIStore.ts           // UI 状态(主题/侧栏/弹窗)
```

**i18n 语言包**:

```
frontend/src/locales/
├── zh-CN/
│   ├── common.json          # 通用（按钮、提示）
│   ├── knowledge.json       # 知识库相关
│   ├── agent.json           # 智能体相关
│   └── query.json           # 问答相关
└── en-US/
    ├── common.json
    ├── knowledge.json
    ├── agent.json
    └── query.json
```

**实现步骤**:

1. 安装 `zustand` + `react-i18next` + `i18next`
2. 逐个 Context 迁移到 Zustand Store
3. 提取所有中文字符串到语言包
4. 实现语言切换组件
5. 测试中英文界面

**验收标准**:
- [ ] 所有页面中英文切换正常
- [ ] Zustand Store 替代所有 Context
- [ ] 语言偏好保存到 localStorage
- [ ] 无硬编码中文（全部通过 t() 函数）

---

### 4.4 性能压测与生产调优

**当前状态**: 未进行性能基准测试。

**压测工具**: `locust` (Python) 或 `k6` (JS)

**压测场景**:

| 场景 | 并发 | 持续时间 | 目标 |
|------|------|---------|------|
| 健康检查 | 200 | 5min | P95 < 50ms |
| 登录 | 50 | 5min | P95 < 500ms |
| 文档上传(1MB) | 20 | 10min | P95 < 5s |
| 知识库查询 | 50 | 10min | P95 < 200ms |
| 流式问答 | 10 | 10min | 首Token < 5s |

**调优项**:

| 配置项 | 当前默认 | 调优后 |
|--------|---------|--------|
| Uvicorn workers | 1 | CPU 核数 |
| PostgreSQL pool | 5 | 20 |
| Redis maxmemory | 无限制 | 512MB, allkeys-lru |
| Nginx worker_connections | 默认 | 1024 |
| Python GC | 默认 | 调整为 gc.set_threshold(1000, 50, 50) |

**实现步骤**:

1. 编写 locustfile.py 压测脚本
2. 执行压测，收集数据
3. 根据压测结果调整配置
4. 重复压测直到达标
5. 输出《性能测试报告》

**验收标准**:
- [ ] QPS ≥ 50（非AI接口）
- [ ] P95 延迟 < 200ms（非AI接口）
- [ ] 流式问答首Token < 5s
- [ ] 无内存泄漏（24小时运行）

---

### 4.5 项目管理看板集成

**当前状态**: `项目管理看板.html` 已作为独立文件存在。

**目标**: 集成到主前端应用中，作为 `/admin/pm` 页面。

**实现步骤**:

1. 将看板逻辑迁移到 React 组件
2. 使用 Zustand Store 管理看板状态
3. 数据从 localStorage 迁移到后端 API `/api/pm/*`
4. 支持多用户协作（通过 WebSocket 实时同步）

---

## 性能数字诚实声明 📊

以下数字在本文档中出现，均**非实测值**，来源说明：

| 数字 | 出现位置 | 实际来源 | 建议 |
|------|---------|---------|------|
| 召回率 +20~40%（HyDE） | 2.1 验收标准 | HyDE 论文 (Gao et al.) | 标为 📊 目标值，待第4周实测 |
| Hit Rate +50%（RRF） | 3.1 验收标准 | RRF 论文 + BEIR 基准推算 | 同上 |
| 解析精度 +40%（Docling/Marker） | 4.2 验收标准 | Docling 官方 benchmark | 同上 |
| 首Token < 5s | 4.4 验收标准 | qwen-max API 典型值 | 取决于模型 API 延迟，非系统可控 |
| Token 节省 ≥ 60% | 3.5 验收标准 | LLM 摘要压缩论文推算 | 标为 📊 目标值 |

> **原则**: 第 4 周压测完成后，用实测数据替换所有 📊 标记的数字。

---

## 5. 远期规划 ❌

### 5.1 数据集模块

对标火山引擎"数据集"模块：

| 功能 | 技术方案 | 优先级 |
|------|---------|--------|
| 创建数据集 (Clickhouse/Hive) | Clickhouse Python 客户端 | P2 |
| 表结构预览 | SQLAlchemy inspect | P2 |
| 数据预览 (前1000条) | 分页查询 | P2 |
| SQL 查询 | 受限 SQL 执行（SELECT only） | P2 |
| 数据血缘 | 解析 SQL + 追踪来源 | P3 |
| 操作记录 | 审计日志扩展 | P3 |

---

### 5.2 多数据库接入扩展

当前支持 MySQL + PostgreSQL，需扩展：

| 数据库 | 驱动 | 优先级 |
|--------|------|--------|
| Oracle | cx_Oracle / oracledb | P2 |
| SQL Server | pymssql / pyodbc | P2 |
| TiDB | mysql-connector (兼容MySQL) | P2 |
| MongoDB | motor (async) | P2 |
| ClickHouse | clickhouse-driver | P3 |
| Hive | pyhive | P3 |

**统一接口设计**:

```python
# raganything/db_connectors/
class BaseDBConnector(ABC):
    @abstractmethod
    async def connect(config) -> None
    @abstractmethod
    async def list_tables() -> List[str]
    @abstractmethod
    async def get_schema(table) -> dict
    @abstractmethod
    async def query(sql, params) -> List[dict]
    @abstractmethod
    async def close() -> None
```

---

### 5.3 知识质量检测独立实现

| 功能 | 技术方案 | 优先级 |
|------|---------|--------|
| 错别字检测 | pycorrector 库 + LLM 辅助 | P2 |
| 语句完整性 | 句法分析 (LTP / HanLP) | P2 |
| 敏感词检测 | 本地敏感词库 + AC 自动机 | P2 |

---

### 5.4 非结构化数据打标应用

独立的打标产品线，含：

- 预置 ASR/图片理解/标签打标/情感识别/观点总结/水军识别 AI 应用
- 自定义打标应用（自定义提示词 + 输出字段）
- 标签库管理（上传维度表）
- 错题反馈 + 提示词自动优化

**优先级**: P3（需甲方明确需求后启动）

---

### 5.5 更多数据源接入

| 数据源 | 接入方式 | 优先级 |
|--------|---------|--------|
| 腾讯云文档 | API | P3 |
| 钉钉云文档 | API | P3 |
| 金山云文档 | API | P3 |
| 微信素材库 | API | P3 |

---

### 5.6 实时协作功能

| 功能 | 技术 | 优先级 |
|------|------|--------|
| 多人实时编辑知识库 | WebSocket + CRDT | P3 |
| 评论/标注 | 数据库 + 实时推送 | P3 |
| 任务分配 | 权限扩展 | P3 |

---

### 5.7 移动端适配

| 平台 | 方案 | 优先级 |
|------|------|--------|
| 微信小程序 | Taro / uni-app | P3 |
| 移动 Web | 响应式适配 | P3 |

---

> **编制单位**: RAG-Anything 项目组  
> **编制日期**: 2026 年 6 月 10 日  
> **文档版本**: v1.0  
> **用途**: 开发蓝图 — 每个功能含技术规格、文件规划、实现步骤、验收标准
