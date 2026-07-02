## Context

AgenticRAG 推理引擎上线后发现严重延迟问题：ReAct 单步耗时 49.56s，CoT 21.6s。根因已通过日志分析定位到三个热点。

## Goals / Non-Goals

**Goals:**
- ReAct 目标：单步 < 5s，典型 1-3 步总耗时 < 10s
- CoT 目标：< 8s
- 不改变推理质量和回答正确性

**Non-Goals:**
- 不修改 LLM API 的选择（模型/服务商不变）
- 不引入缓存机制（属于独立优化方向）
- 不修改前端

## Decisions

### Decision 1: 非 FINISH 步 max_tokens=1024

**热点**: `_call_llm_with_retry` 所有步骤统一 max_tokens=4096。非 FINISH 步 LLM 实际只需产出：
```
Thought: 需要检索用户表结构信息
Action: search  
Action Input: {"query": "用户表 内部结构 字段"}
```
约 50-150 tokens。1024 提供了 5-20x 余量。

**选择**: 新增 `is_final_step` 参数区分。
**替代方案**: 用 `max_tokens=512` — 太激进，部分复杂 thought 可能截断。`max_tokens=2048` — 不痛不痒。

### Decision 2: SearchTool 默认 rrf + top_k=30

**热点**: SearchTool 调用 `rag.aquery(mode="hybrid")` 触发了 local entity (60) + global relation (60) + 向量块的全量查询，日志可见每次搜索产生 "110 entities, 139 relations" 的检索结果。

**选择**: 默认 `mode="rrf"` + `top_k=30` + `max_total_tokens=8000`。RRF 三通道融合检索在质量上对标 hybrid 但避免了 entity/relation 的独立向量搜索开销。
**替代方案**: 保持 hybrid 但缩小 top_k — 仍需 local+global 两轮查询，节省有限。

### Decision 3: 去除 1s retry sleep

**热点**: 重试中的 `asyncio.sleep(1)` 在 LLM 首次返回空时强制等待。

**选择**: 移除 sleep，立即重试。
**风险**: 极低 — LLM API 返回空/error 的瞬时故障通常不是限流导致（限流会返回 429），立即重试安全。

## Risks / Trade-offs

- **rrf 模式 vs hybrid 模式**: rrf 在某些边缘 case 下查全率略低 → Agent 有 5 步预算，可在后续步骤中用不同 query 词补充检索
- **1024 tokens 截断风险**: 如果 LLM 输出异常长 → `_parse_action` 设计了 fallback（无法解析时整段作为 FINISH answer），不会丢数据
