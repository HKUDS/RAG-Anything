## Context

RAG-Anything 是一个基于 LightRAG 的多模态 RAG 系统，核心包 `raganything/` 包含 45+ 个 Python 文件，支撑文档解析、知识图谱构建、混合检索、Agentic RAG、制造领域知识管理等能力。项目当前架构存在以下结构性债务：

**当前分层现状（问题标注）**：
```
server.py ───────────────────────────────────────────── (Web 入口)
  ├── auth.py ❌ 根级模块，被包内反向依赖
  ├── agent_manager.py ❌ 根级模块，被包内反向依赖
  └── raganything/
        ├── routers/shared.py ❌ God Module (708行)，所有 router 的共享中枢
        ├── routers/{knowledge,agent,query,admin,auth,manufacturing}.py
        ├── dependencies.py ❌ 与 shared.py 功能重叠
        ├── raganything.py       (主类，Mixin 组合)
        ├── modalprocessors.py   ❌ 1672行巨型文件
        ├── agentic_rag.py       ❌ 1145行
        ├── query/pipeline.py    ❌ 1445行
        ├── processor/           (7个 Mixin，隐式契约)
        ├── parser/              (解析器注册表模式 ✅)
        └── manufacturing/       (内部层次清晰 ✅)
```

**核心约束**：
- 所有改造不得改动原有业务流程、API 接口出入参、数据库交互逻辑
- 必须保持与 LightRAG 上游库的兼容性
- 29 个测试文件必须全部通过
- 前端 React SPA 的 API 调用不受影响

## Goals / Non-Goals

**Goals:**
- 建立清晰的 4 层架构：Router → Service → Core → Infrastructure
- 消灭所有 >500 行的 Python 文件（24+ 个文件拆分）
- 消除根级模块被包内反向依赖的违规
- 统一共享状态管理，消除 `dependencies.py` 与 `shared.py` 的重复
- 为所有 Mixin 引入显式 Protocol 接口
- 标准化模块注释头和导出清单，降低 AI 解析成本

**Non-Goals:**
- 不改动 LightRAG 上游库的任何代码
- 不修改数据库 schema、API 端点路径、请求/响应格式
- 不重构前端代码
- 不引入新的第三方依赖框架
- 不改变 manufacturing 子包的内部架构（其层次已足够清晰）

## Decisions

### Decision 1: 四层架构模型

**选择**：Router → Service → Core → Infrastructure

```
┌─────────────────────────────────────────────┐
│  Router 层 (routers/)                        │
│  职责：HTTP 请求验证、路由、响应格式化        │
│  依赖方向：→ Service 层                      │
├─────────────────────────────────────────────┤
│  Service 层 (新增 services/)                 │
│  职责：业务编排、事务管理、跨模块协调          │
│  依赖方向：→ Core 层                         │
├─────────────────────────────────────────────┤
│  Core 层 (raganything 核心)                  │
│  职责：领域逻辑、RAG 引擎、解析器、查询引擎    │
│  依赖方向：→ Infrastructure 层               │
├─────────────────────────────────────────────┤
│  Infrastructure 层                           │
│  职责：LightRAG 适配、外部 API、文件系统、DB   │
│  依赖方向：不依赖上层                         │
└─────────────────────────────────────────────┘
```

**替代方案考虑**：
- **六边形架构（Ports & Adapters）**：过度设计。当前项目是单体应用，领域逻辑集中在 RAG 引擎，引入 Port/Adapter 抽象层会增加不必要的间接层次，反而降低 AI 可读性。
- **保持现状 + 仅拆分文件**：不解决分层违规问题，根级模块依赖混乱会持续存在。短期收益有限。

**选择理由**：四层架构是 layered architecture 的最小必要子集，清晰定义了依赖方向但不过度抽象。对于 AI 工具来说，每层职责明确、依赖方向单向，调用链追溯成本最低。

### Decision 2: 根级模块迁移路径

**选择**：将 `auth.py` 和 `agent_manager.py` 迁移到 `raganything/services/`，在根级保留向后兼容的 re-export wrapper。

```
根级 auth.py (新)         → from raganything.services.auth import *
根级 agent_manager.py (新) → from raganything.services.agent_manager import *
raganything/services/auth.py            (原 auth.py 逻辑)
raganything/services/agent_manager.py   (原 agent_manager.py 逻辑)
```

**替代方案考虑**：
- **直接删除根级文件**：会破坏所有现有导入（scripts/、tests/、server.py），需要一次性更新所有引用，风险高。
- **仅移动不保留 wrapper**：同样需要全量更新导入，无法渐进迁移。

**选择理由**：wrapper 模式允许渐进迁移——先移动逻辑，验证测试通过，再逐步更新各模块的导入路径，最终移除 wrapper。风险可控。

### Decision 3: God Module 拆分 (routers/shared.py)

**选择**：拆分为 3 个独立模块：

| 原 shared.py 职责 | 新模块 | 说明 |
|---|---|---|
| KB 实例字典、创建/获取/删除 | `raganything/services/kb_service.py` | 知识库生命周期管理 |
| WebSocket 连接管理、广播 | `raganything/services/ws_service.py` | WebSocket 推送 |
| 查询历史、处理任务状态 | `raganything/services/state_service.py` | 内存状态管理 |
| Prompt 注入检测、通用工具 | `raganything/utils/security.py` | 已有 utils.py，安全相关工具独立 |

**替代方案考虑**：
- **合并到 server.py**：server.py 应只负责 FastAPI app 创建和中间件注册，不应承载业务状态。
- **使用 Redis/外部状态存储**：引入外部依赖，增加运维复杂度。当前规模不需要。

### Decision 4: 巨型文件分解策略

**选择**：按"一个类一个文件"或"一个职责一个文件"原则拆分，而非按行数机械切割。

| 文件 | 行数 | 拆分方案 |
|---|---|---|
| `modalprocessors.py` | 1672 | `modalprocessors/image.py`, `modalprocessors/table.py`, `modalprocessors/equation.py`, `modalprocessors/generic.py`, `modalprocessors/context.py` |
| `query/pipeline.py` | 1445 | `query/pipeline.py`(核心查询), `query/streaming.py`(流式), `query/context_builder.py`(上下文构建) |
| `processor/doc_processor.py` | 1201 | `processor/doc_processor.py`(≤500行精简), `processor/doc_ingestion.py`(文档摄取), `processor/doc_tracking.py`(状态追踪) |
| `agentic_rag.py` | 1145 | `agentic_rag/engine.py`, `agentic_rag/tools.py`, `agentic_rag/react_loop.py` |

**选择理由**：按职责拆分后每个文件职责单一，AI 工具只需阅读相关文件即可理解业务逻辑。机械按行数切割会导致逻辑碎片化。

### Decision 5: Mixin 契约显式化

**选择**：为每个 Mixin 定义 Protocol 类，声明其依赖的属性（`config`, `lightrag`, `logger` 等），但不强制运行时检查。

```python
# 新增 raganything/protocols.py
class RAGCoreProtocol(Protocol):
    config: RAGAnythingConfig
    lightrag: LightRAG
    logger: logging.Logger

class QueryCapable(RAGCoreProtocol, Protocol):
    def query(...): ...
    async def aquery(...): ...
```

**替代方案考虑**：
- **ABC 强制继承检查**：运行时开销，且需要修改所有现有类的继承链，风险高。
- **不做任何改变**：AI 工具无法从代码中理解 Mixin 依赖了哪些属性，每次需人工推断。

**选择理由**：Protocol 是静态类型检查工具（mypy/pyright）的标准做法，零运行时开销，AI 工具可以从 Protocol 定义中立即理解属性契约。

### Decision 6: 向后兼容策略

**选择**：所有模块迁移采用"先建新 → 保留旧 re-export → 更新引用 → 清理旧"四步流程。

每步独立验证（全量测试通过），确保任何一步失败都可以安全回退。

## Risks / Trade-offs

- **[风险] 导入路径变更导致 CI/CD 失败** → 缓解：import 路径变更集中在独立 PR 中，每步全量测试；wrapper 确保旧路径在过渡期仍可用
- **[风险] 拆分后模块数量增加（从 45 到 ~70），包结构更复杂** → 缓解：每个模块职责单一、命名自解释；新增 `__init__.py` 中明确的公开 API 导出
- **[风险] 拆分过程中引入回归 bug** → 缓解：29 个现有测试作为回归安全网；每次拆分后立即运行全量测试；优先拆分测试覆盖良好的模块
- **[权衡] Protocol 定义增加约 100 行样板代码** → 交换：AI 工具可读性显著提升，新开发者理解 Mixin 契约时间从数小时降至数分钟
- **[权衡] 模块数量增加导致 import 语句增多** → 交换：每个 import 更精确，按需加载，减少循环依赖风险
