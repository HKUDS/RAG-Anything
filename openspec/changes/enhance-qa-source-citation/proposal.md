## Why

当前 RAG-Anything 的问答输出在引用来源方面不够完整和规范：LLM 有时不标注来源、实体关系信息丢失在上下文中未被引用、回答格式不统一导致可读性差。用户需要**每个回答都能追溯到明确的文档来源、原文证据和实体关系**，且输出格式清晰一致。

## What Changes

- **强化 LLM 回答提示**：将 `INLINE_QUOTE_INSTRUCTION` 从"建议"升级为"强制要求"，确保每个回答必定包含文档来源引用
- **增加实体关系引用**：在 prompt 中要求 LLM 在回答中引用知识图谱中的实体关系（如 `[实体A] →[关系]→ [实体B]`），而非仅将实体信息埋在上下文中
- **规范输出格式**：定义清晰的回答结构模板（回答正文 → 引用来源 → 关联实体），确保输出整洁易读
- **后处理检测与补充**：当检测到 LLM 回答缺少来源标注时，自动触发补充引用请求或追加提示

## Capabilities

### New Capabilities

- `entity-relation-citation`: 要求 LLM 在回答中引用知识图谱检索到的实体关系路径，格式为 `[实体A] →[关系]→ [实体B]`，并附带关联实体摘要块
- `answer-format-spec`: 定义标准化的回答输出格式模板（正文 → 来源引用块 → 关联实体块），确保所有查询模式输出一致

### Modified Capabilities

- `citation-structured-output`: 将 LLM 引用格式指令从"建议级"升级为"强制级"，要求每个事实性陈述必须标注来源；增加来源缺失检测与自动补充机制

## Impact

- **受影响代码**: `raganything/prompt.py`（INLINE_QUOTE_INSTRUCTION 升级）、`raganything/query.py`（RRF/Graph/Agentic 三种查询模式的 prompt 构建逻辑）
- **受影响 API**: `/api/query` 和 `/api/query/stream` 的响应中 `citations` 字段结构增强（新增 `entity_relations` 子字段）
- **依赖**: 复用已有 `citation-source-tracing`（chunk 源信息）和 `citation-parser.py`（引用解析），不引入新外部依赖
- **向后兼容**: 现有客户端忽略新增字段不受影响；旧格式的 INLINE_QUOTE_INSTRUCTION 行为被新的强制版本替代
