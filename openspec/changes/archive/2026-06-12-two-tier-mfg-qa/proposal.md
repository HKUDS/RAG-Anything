## Why

制造 QA 对所有问题无条件走 AgenticRAG ReAct 多步推理，导致简单问答（"主轴振动原因"）也要 15 秒、2 次 LLM 调用。通用智能体同样的问题只需 3 秒、1 次 LLM 调用。90% 的制造问答是"查文档→回答"，不需要多步推理。应先用直接检索快速出结果，只有检索质量差时才回退到 AgenticRAG。

## What Changes

- **QAEngine.answer()** 改为两级策略：Tier 1 直接 RRF 检索+LLM 生成 → 置信度 ≥ 阈值直接返回；Tier 2 置信度不足时回退 AgenticRAG
- **QAEngine.answer_stream()** 同理：Tier 1 直接 RRF 检索+流式 LLM → 返回；Tier 2 回退 AgenticRAG.run_stream()
- 简单问题 ~3s（与通用智能体持平），复杂问题才走 ~10s 的 AgenticRAG

## Capabilities

### New Capabilities
- `two-tier-qa`: 制造 QA 引擎两级策略 — 直接检索（快）→ 置信度不足时 AgenticRAG（准）

### Modified Capabilities
- `mfg-agentic-reasoning`: QA 引擎从"无条件 AgenticRAG"改为"先直接检索，仅必要时回退 AgenticRAG"

## Impact

- `raganything/manufacturing/agent/qa_engine.py` — QAEngine.answer() 和 answer_stream() 重写
