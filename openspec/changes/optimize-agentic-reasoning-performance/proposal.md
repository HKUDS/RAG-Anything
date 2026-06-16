## Why

ReAct 模式单步推理耗时 49.56 秒，CoT 模式 21.6 秒，远超可接受的用户体验阈值（目标 < 10 秒）。根因是三条热点：非 FINISH 步 LLM 调用使用 max_tokens=4096（实际只需 ~200 tokens 产出 Thought + Action JSON）、SearchTool 使用 full hybrid 模式检索（全量 entity/relation 查询）、LLM 重试中有 1 秒阻塞 sleep。

## What Changes

- `_call_llm_with_retry()`: 新增 `is_final_step` 参数，非 FINISH 步 max_tokens=1024，去除重试中 1s sleep
- `SearchTool.execute()`: 检索模式默认改为 "rrf"，top_k 从 60 降到 30，max_total_tokens 从 16000 降到 8000
- `AgenticRAG.__init__()`: 新增 `agent_query_mode` 参数，透传给 SearchTool
- CoT 调用 max_tokens 从 4096 降到 2048（CoT 需要推理空间但不需要 4K）

## Capabilities

### New Capabilities

- `agentic-performance-tuning`: AgenticRAG 推理引擎性能调优 — 分步 token 预算控制、SearchTool 轻量检索模式、无阻塞重试

### Modified Capabilities

<!-- No existing spec requirements change. Pure implementation-level optimization. -->

## Impact

- **`raganything/agentic_rag.py`**: `_call_llm_with_retry`、`_react_loop`、`_cot_loop`、`run_stream`、`SearchTool.execute`
- **`server.py`**: agent query stream 中 `SearchTool` 构造传参 `query_mode`
- **无 API 变更**，无 Breaking Change
