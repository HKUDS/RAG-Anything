## Why

当前 RAG-Anything 的查询模式是"单次检索-单次回答"：用户提问 → 检索文档 → LLM 生成回答。对于需要多步推理的复杂问题（如"计算近三年营收增长率，并与行业平均对比"），系统无法自主分解问题、调用外部工具、基于中间结果迭代推理。引入 Agentic RAG 引擎将使系统从"被动检索器"升级为"主动推理体"。

> ⚠️ **可行性**: 时间偏紧 — ReAct 循环+工具调用+错误恢复完整实现需 1.5-2 周。建议先交付最小版本：2步推理 + SearchTool，后续完善 Calculator + DB 工具。

## What Changes

- 新增 **AgenticRAG 推理引擎**：支持 ReAct / Chain-of-Thought 两种推理模式，通过 `AGENT_MODE` 环境变量配置。ReAct 循环：Thought → Action → Observation → 判断是否充分 → 循环直到信息充分或达到 max_steps=5。单步超时 30s
- 新增 **Tool 基类**：`name`、`description`、`parameters` (JSON Schema)、`async execute(input) → str`。支持注册自定义工具。内置 4 个工具：
  - **SearchTool** — 知识库检索（ReAct 循环中的核心工具，让 LLM 自主决定检索时机和内容）
  - **CalculatorTool** — 四则运算，安全沙箱求值
  - **WebSearchTool** — 外部网页搜索
  - **DatabaseQueryTool** — 预留接口，后续完善
- 新增 `raganything/agentic_rag.py`：`AgenticRAG` 类（tools, max_steps, mode, async run）+ `Tool` 基类 + `AgentResult` 数据结构
- 修改 **`server.py` `/api/query`**：新增 `agent_mode` 参数，设为 "react" 或 "cot" 时启动推理循环
- 新增环境变量：`AGENT_MODE=react`、`AGENT_MAX_STEPS=5`
- 前端新增 **推理轨迹面板**：展示每一步的 Thought → Action → Observation

## Capabilities

### New Capabilities
- `reasoning-engine`: ReAct/CoT 多步推理循环，max_steps=5，单步超时 30s，可配置 AGENT_MODE
- `tool-framework`: Tool 基类 + 工具注册/调用/超时控制框架
- `search-tool`: 知识库检索工具，封装现有 RAG 检索能力
- `calculator-tool`: 四则运算安全求值工具
- `web-search-tool`: 外部网页搜索工具
- `db-query-tool`: 内部数据库只读查询（预留接口）
- `reasoning-trace`: 推理过程数据结构与序列化

### Modified Capabilities
- `agent-config`: AgentConfig 新增 reasoning_mode、max_steps、enabled_tools 字段
- `query-api`: `server.py` `/api/query` 新增 agent_mode 参数，响应附带 reasoning_trace

## Impact

- **`server.py`** — `/api/query` 端点新增 `agent_mode` 参数
- **新增 `raganything/agentic_rag.py`** — AgenticRAG 类 + Tool 基类 + 4 个内置工具 + AgentResult
- **`frontend/src/components/`** — 新增 ReasoningTrace 组件
- **`.env`** — 新增 `AGENT_MODE`、`AGENT_MAX_STEPS` 环境变量
- **依赖** — `httpx`（项目已有）、`sqlite3`（标准库）
- **非破坏性变更** — 默认 `agent_mode` 不传时保持现有行为完全不变
