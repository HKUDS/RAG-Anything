## Why

制造智能体的自定义 RRF 检索管线（QAEngine + HybridSearchEngine）是从零实现的，与 LightRAG 原生查询走不同的代码路径。在开发过程中暴露了 4 个独立 bug（BM25 负分过滤、NetworkXStorage async API 不兼容、Vector 通道模式选择不当、Graph 通道 content 获取失败），且每个都导致检索召回率显著低于已验证的 LightRAG 原生 hybrid 查询。重复造轮子没有带来任何优势，反而增加了维护成本和 bug 面。

## What Changes

- **删除**：`QAEngine` 在制造智能体 QA 中的使用，`ServerLLMAdapter`，`_get_mfg_agent_components` 中的 QA 初始化逻辑
- **替换**：`/api/manufacturing/qa` → 直接调用 `LightRAG.aquery(mode="hybrid")`（与普通智能体用同一代码路径）
- **替换**：`/api/manufacturing/qa/stream` → 直接调用 `LightRAG.aquery(mode="hybrid", stream=True)`
- **保留**：`FaultDiagnosisEngine`（故障诊断逻辑独立，不依赖 RRF）
- **保留**：`CodeParser`（代码解析逻辑独立，不依赖 RRF）
- **保留**：前端 `ManufacturingAgentPage` 的 UI 和交互不变

## Capabilities

### New Capabilities
- 无

### Modified Capabilities
- `rag-integration`: 制造智能体 QA 不再使用自定义 QAEngine，改为直接调用 LightRAG 原生查询

## Impact

- `server.py` — 删除 `ServerLLMAdapter`，简化 `_get_mfg_agent_components`，重写 QA 端点
- `raganything/manufacturing/agent/qa_engine.py` — 不再被制造智能体 QA 端点使用（模块保留，FaultDiagnosis 和 CodeParser 仍可用）
- `raganything/query.py` — `_aquery_rrf` 不再被制造智能体调用（普通查询的 RRF mode 仍可用）
