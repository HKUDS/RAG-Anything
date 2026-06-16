## Context

工作流画布使用 ReactFlow + JSON 存储。现有后端已集成 LightRAG（文档解析、分块、嵌入、检索、LLM 查询）。需要在现有架构上增加执行引擎，复用已有组件。

## Goals / Non-Goals

**Goals:**
- 工作流点击运行后，按拓扑排序依次执行每个节点
- 节点执行状态实时推送到前端（WebSocket）
- 6 种内置节点各有对应的执行器
- 支持运行历史回溯
- 前端展示执行进度和最终结果

**Non-Goals:**
- 不支持并行执行（同层节点串行）
- 不支持 cron 定时调度
- 不支持节点间数据转换/映射（数据直通）
- 不支持条件分支

## Decisions

### 决策 1：执行架构 — 后端 Pipeline vs 前端驱动

| 方案 | 优点 | 缺点 | 结论 |
|------|------|------|------|
| 后端 Pipeline | 可靠、可复用、可扩展 | 需要 WebSocket 通信 | ✅ |
| 前端驱动 | 简单、少一次通信 | 不可靠（页面关闭=中断）、无法复用 | ❌ |

**选择后端 Pipeline**：server.py 增加执行端点，通过 WebSocket 推送每个节点的状态变化。

### 决策 2：节点执行器注册模式

```python
class NodeExecutor:
    node_type: str
    async def execute(self, config: dict, inputs: dict) -> dict:

# 注册表
EXECUTORS = {
    "document_input": DocumentInputExecutor(),
    "text_splitter": TextSplitterExecutor(),
    "embedding": EmbeddingExecutor(),
    "retriever": RetrieverExecutor(),
    "llm_answer": LLMAnswerExecutor(),
    "output": OutputExecutor(),
}
```

每个执行器接收节点配置 + 上游输出，返回本节点结果。

### 决策 3：WebSocket 状态推送

WebSocket 端点 `/ws/workflow/{run_id}`，推送 JSON：
```json
{"type": "node_status", "node_id": "xxx", "status": "running|done|error", "data": {...}}
{"type": "run_complete", "run_id": "xxx", "output": "..."}
```

前端连接 WebSocket，根据 `node_id` 更新对应节点的 `data.runStatus`。

### 决策 4：6 种节点执行逻辑

| 节点 | 执行逻辑 |
|------|---------|
| `document_input` | 从 `uploads/` 读取指定文件，返回文本内容 |
| `text_splitter` | 按 chunk_size/chunk_overlap 分块，返回 chunks 列表 |
| `embedding` | 调用嵌入 API 向量化文本 |
| `retriever` | 查询 LightRAG 知识库，返回 top-k 文档 |
| `llm_answer` | 调用 LLM，system_prompt + 上下文生成回答 |
| `output` | 汇总上游结果，返回格式化输出 |

### 决策 5：运行历史存储

运行记录存为 JSON 文件：`workflows/runs/{run_id}.json`
```json
{
  "run_id": "uuid",
  "workflow_id": "uuid",
  "status": "completed|failed",
  "started_at": "ISO8601",
  "completed_at": "ISO8601",
  "node_results": [{"node_id": "x", "status": "done", "output": "...", "duration_ms": 120}],
  "final_output": "..."
}
```

## Risks / Trade-offs

- **[低风险] LLM 调用耗时**：执行包含 LLM 节点的工作流可能需要 10-60s → WebSocket 推送进度解决等待焦虑
- **[中风险] 大文件处理**：document_input 读大 PDF 可能 OOM → MVP 限制 100MB
- **[低风险] 错误传播**：某节点失败后后续节点全部跳过 → 前端显示红色错误节点

## Open Questions

- 是否支持"单步执行"逐节点调试？→ 后续迭代
- 是否支持节点输出预览（运行到某节点暂停）？→ 后续迭代
