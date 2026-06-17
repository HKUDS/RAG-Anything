## Context

当前 RAG-Anything 已有基础的引用系统：
- `citation-source-tracing`：ScoredChunk 携带源文档信息
- `citation-structured-output`：LLM 使用 `[来源 N]` 标记，citation_parser.py 解析引用
- `INLINE_QUOTE_INSTRUCTION`：要求 LLM 内联引用的提示指令（`raganything/prompt.py:484`）
- 实体标注已在上下文中提供（`（涉及实体：...）`），但 LLM 未被要求将其纳入回答

现有问题：
1. `INLINE_QUOTE_INSTRUCTION` 语言偏软（"引用...时，必须"），未强制"每个回答都必须有来源"
2. 实体关系信息仅埋在上下文中，LLM 可能忽略
3. 三种查询模式（RRF/Graph/Agentic）的输出格式不完全一致
4. 缺少来源缺失的后处理检测机制

## Goals / Non-Goals

**Goals:**
- 升级 prompt 指令，强制每个回答必含来源引用
- 要求 LLM 在回答中引用实体关系，并附带关联实体块
- 统一所有查询模式的输出格式为三段式结构
- 添加来源缺失检测与自动纠正机制

**Non-Goals:**
- 不修改 `citation_parser.py` 的核心逻辑（仅扩展实体关系解析）
- 不修改前端显示（已有 `citation-frontend-display` spec 覆盖）
- 不改变 LightRAG 原生的查询管线
- 不引入新的外部依赖

## Decisions

### Decision 1: 新建 `ANSWER_FORMAT_INSTRUCTION` 替代 `INLINE_QUOTE_INSTRUCTION`

**选择**: 在 `prompt.py` 中创建新的 `ANSWER_FORMAT_INSTRUCTION` 常量，替代 `INLINE_QUOTE_INSTRUCTION` 在查询提示中的位置。

**理由**:
- 新版指令从"建议级"升级为"强制级"，语义差异大，不适合原地修改
- 保留 `INLINE_QUOTE_INSTRUCTION` 作为向后兼容选项，可通过配置切换

**替代方案**:
- 直接修改 `INLINE_QUOTE_INSTRUCTION`：风险是改变了已有行为的语义，但代码改动最小 → 不选，保留旧版给需要轻量引用的场景

### Decision 2: Prompt 强制 > 后处理强制

**选择**: 主要通过强化 prompt 指令来实现引用强制，后处理检测仅作为安全网。

**理由**:
- prompt 是 LLM 行为的直接控制点，修改成本最低
- 后处理纠正需要额外 LLM 调用，增加延迟和成本
- 强 prompt 指令在大多数情况下已足够

**替代方案**:
- 仅靠后处理解析+重构回答：过于复杂，破坏流式输出的体验 → 不选

### Decision 3: 实体关系解析器扩展而非新建模块

**选择**: 在 `citation_parser.py` 中添加 `parse_entity_relations()` 函数，而非新建独立模块。

**理由**:
- 实体关系解析与引用解析功能内聚，同属"从 LLM 输出中提取结构化信息"
- 避免模块碎片化，维护成本更低

### Decision 4: 新增 `RAGAnythingConfig.enforce_citation` 配置项

**选择**: 在 `RAGAnythingConfig` 中增加 `enforce_citation: bool = True` 配置项，控制是否启用强制引用。

**理由**:
- 允许向后兼容：用户可关掉强制引用回到旧行为
- 默认启用（opt-out），推动引用质量的提升

## Risks / Trade-offs

| Risk | Mitigation |
|------|------------|
| 更强硬的 prompt 可能增加 LLM token 消耗（每回答多 50-200 tokens） | 默认开启，提供配置开关；token 增量在可接受范围内 |
| 部分模型可能不遵循强制引用指令 | 后处理检测作为安全网，记录警告并可选触发纠正 |
| `【引用来源】` 和 `【关联实体】` 的格式可能被 LLM 自由发挥 | citation_parser 已支持多种格式变体，可逐步扩展正则 |
| 实体关系信息可能不总是存在于检索结果中 | prompt 中明确"如有实体关系则引用"，避免 LLM 编造 |

## Migration Plan

1. **部署**: 新增 prompt 常量和配置项 → 更新 query.py 中三处 prompt 构建 → 扩展 citation_parser
2. **灰度**: 默认 `enforce_citation = True`，出问题时用户可关掉
3. **回滚**: 将 `enforce_citation = False` 恢复旧行为，无需代码回滚
4. **向前兼容**: 旧客户端忽略 `citations.entity_relations` 字段，不受影响

## Open Questions

- 是否需要为 `【关联实体】` 块设计更严格的 schema（如 JSON 输出）而非 Markdown？当前选择 Markdown 因为更自然、模型遵循度更高
- 强制引用是否应该支持"仅部分模式"（如仅在 RRF 和 Graph 强制，Agentic 不强制）？当前设计是所有模式统一
