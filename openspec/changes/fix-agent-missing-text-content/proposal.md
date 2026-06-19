## Why

代码重构后，智能体问答中出现"图片能返回但声称未找到原文内容"的矛盾现象。根本原因是：当 RRF 检索返回的上下文缺少 `[来源 ` 标记时，系统注入 `_DEGRADED_HINT`（"本次检索未能获取到关联的文档文本内容"），导致 LLM 回答"未找到原文"。但图片提取逻辑（包括 bigram 全库扫描回退）独立于文本质量检测运行，可以从 `kv_store_text_chunks.json` 中找到匹配的图片——形成"有图无文"的割裂体验。修复需要打通文本与图片的检索回退路径，确保 bigram 扫描找到图片时同步回填文本内容，并让"上下文为空"的判定与图片/文本的实际可用性保持一致。

## What Changes

- **bigram 回退扫描同步回填文本**：当 bigram 全库扫描找到匹配图片时，将对应 chunk 的文本内容也注入检索上下文，消除"有图无文"的断层
- **空上下文检测粒度修正**：`_is_empty_context()` 不再仅以 `[来源 ` 标记和字符数判定空上下文，而是考虑是否有任何可用的文本内容（包括从 bigram 扫描回填的文本）
- **`_DEGRADED_HINT` 触发条件优化**：仅在真正无文本内容时才注入降级提示，避免对已有实质内容的上下文错误提示"未找到原文"
- **`_has_chunks` 检测增强**：扩展为检测上下文是否包含任何有意义的文本块（不限于 `[来源 ` 标记），当有图片描述文本或其他实质性内容时不应判定为"无文本块"
- **幂等性保证**：回填的文本内容不重复注入，避免 bigram 扫描结果与原有检索结果重叠

## Capabilities

### New Capabilities

- `agent-context-backfill`: 智能体检索上下文的后备回填机制——当 RRF 主路径检索不足但 bigram 扫描找到相关 chunk 时，自动回填文本内容到上下文，确保图片和文本的一致性

### Modified Capabilities

- `agent-empty-context-handling`: 扩展空上下文判定逻辑——不再仅依赖 `[来源 ` 标记和 200 字符阈值，而是纳入 bigram 回填后的最终文本可用性进行综合判断

## Impact

- **Affected code**: 
  - `raganything/routers/agent.py` — 核心修改区域：`agent_mode="none"` 路径（line ~590-710）中的 bigram 回退扫描与 prompt 构造逻辑；`agent_mode="react"` 路径（line ~480-565）中的图片扫描逻辑
  - `raganything/routers/shared.py` — `_DEGRADED_HINT` 文本可能需要调整
  - `raganything/query/pipeline.py` — `DEGRADED_CONTEXT_HINT` 可能需同步调整
- **Affected API**: `POST /api/agents/{agent_id}/query/stream` — 行为改进：有图片的上下文中不再触发错误降级提示
- **Dependencies**: 依赖 `kv_store_text_chunks.json` 的结构保持稳定
