## Context

当前 `ANSWER_FORMAT_INSTRUCTION` 第 3 条写的是"若检索内容有文档名…使用该文档名；无文档名则只引原文，不可编造"。这给 LLM 留下了跳过文档名的理由。实际场景中，检索上下文中每个 chunk 都有 `(文档：xxx)` 标签，且 server.py 的 `_get_kb_doc_list` 会在 prompt 头部注入 `## 可用文档` 列表。

问题：LLM 有时只输出 `[来源 1]` 编号而不附带文档名，导致用户无法快速定位信息来源。

## Goals / Non-Goals

**Goals:**
- `ANSWER_FORMAT_INSTRUCTION` 中"文档名"要求从"若有则用"改为"必须包含"
- `【引用来源】` 块每个条目必须包含 `源文档：文档名`
- 检索上下文中每个 chunk 的文档名标签确保清晰可见

**Non-Goals:**
- 不改变前端显示
- 不改变 `citation_parser.py` 的解析逻辑

## Decisions

### Decision 1: 修改 `ANSWER_FORMAT_INSTRUCTION` 第 3、4 条

**选择**: 将第 3 条"若检索内容有文档名…使用该文档名"改为"每条引用必须标注所属文档名；若无则标注"未知文档""，第 4 条强制要求 `源文档：文档名`。

**理由**: prompt 是最直接的修改点，成本最低。

### Decision 2: 增强 `_get_kb_doc_list` 输出

**选择**: 在 `## 可用文档` 列表前加一句指引："以下文档在检索内容中对应的标注名（引用时请使用这些名称）"。

**理由**: 帮助 LLM 正确映射 chunk 中的简写文档名到完整名称。

## Risks / Trade-offs

| Risk | Mitigation |
|------|------------|
| 单文档 KB 时文档名标注显得多余 | 保留，一致性优于特例 |
| LLM 可能编造文档名 | 指令中强调"使用上下文中的文档名，未找到时写未知文档" |
