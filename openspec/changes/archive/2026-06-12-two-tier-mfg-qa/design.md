## Context

当前 QAEngine.answer() 无条件走 AgenticRAG ReAct。大多数制造问答只需要 1 次检索+1 次 LLM 调用就能解决。

## Goals / Non-Goals

**Goals:**
- 简单问题（检索结果充分）走直接路径：RRF 检索 → 构造 prompt → LLM 生成 → 返回
- 复杂问题（检索结果差）回退 AgenticRAG 多步推理
- answer() 和 answer_stream() 都支持两级策略

**Non-Goals:**
- 不修改 AgenticRAG 引擎本身
- 不修改 server 端点签名

## Decisions

### Decision 1: 置信度阈值控制回退

检索上下文 < 50 字符 → 直接走 AgenticRAG（无有效内容，不可能回答好）
检索上下文 ≥ 200 字符 → 直接生成，不走 AgenticRAG（内容充分）
50-200 字符之间 → 直接生成后评估置信度，< 0.3 则回退

### Decision 2: Tier 1 直接生成复用通用智能体的 prompt 风格

```python
prompt = f"以下是知识库检索内容。\n\n## 检索内容\n{ctx}\n\n## 问题\n{query}\n\n从检索内容提取事实和数据。有数字必须引用。没有就说未找到。不编造。"
```

与通用智能体的 prompt 保持一致。

### Decision 3: answer_stream() 的 Tier 1 路径直接调 LLM stream

不经过 AgenticRAG.run_stream() — 避免了 ReAct 格式解析的开销。thinking 事件产出简化为 1 条"检索完成"。
