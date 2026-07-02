## Context

引用增强 (`enhance-citation-source-display`) 实现后，用户反馈引用系统过于复杂：`[来源 N]` 上标 + `【引用来源】` 块 + CitationPanel 的三层交互割裂了阅读体验。用户期望更直接的方式——在回答正文中看到原文引用。

本变更将引用方式从"结构化标记 + 面板"改为"内联原文引用"，移除所有引用 UI 组件，仅通过 LLM 提示词控制输出格式。

## Goals / Non-Goals

**Goals:**
- LLM 在回答中直接嵌入检索内容的原文摘录，以引号标注
- 所有检索模式（RRF、Graph、LightRAG 原生、Agentic RAG）均生效
- 移除 CitationPanel、citation_parser 调用、`[来源 N]` 格式指令
- 保留 ScoredChunk 源追溯字段和 chunk source cache（不影响其他功能）

**Non-Goals:**
- 不改变检索逻辑本身
- 不改变 API 响应结构（仅移除 citations 字段）
- 不改变 LightRAG 内部行为

## Decisions

### Decision 1: 内联引用指令格式

新指令要求 LLM 在引用检索内容时直接嵌入原文：

```
## 引用原文要求
- 回答中引用检索内容的具体事实或数据时，必须在对应位置用引号直接嵌入原文摘录
- 引用格式示例："根据文档描述，该系统'面向管理员，提供系统级别数据管理和权限管理'"
- 原文摘录必须从检索内容中逐字复制（至少20字），不可概括或改写
- 不要使用 [来源 N] 标记或单独的引用来源列表
```

### Decision 2: 移除范围

| 组件 | 动作 |
|------|------|
| `CITATION_FORMAT_INSTRUCTION` | 替换为 `INLINE_QUOTE_INSTRUCTION` |
| `CitationPanel.jsx` | 删除 |
| `CitationMarkdown` 组件 | 删除，恢复纯 ReactMarkdown |
| `citation_parser` 调用（server.py） | 删除 |
| `/api/document/open` | 删除 |
| `/api/document/context` | 删除 |
| 响应中 `citations` 字段 | 删除 |
| SSE done 事件中 `citations` | 删除 |
| `ScoredChunk` 源字段 | 保留（不破坏数据流） |
| `_chunk_source_cache` | 保留（不破坏数据流） |
| `citation_parser.py` | 保留（制造模块依赖） |

### Decision 3: 全模式覆盖策略

| 模式 | 注入方式 |
|------|---------|
| RRF | `query.py` `_aquery_rrf()` prompt |
| Graph | `query.py` `_aquery_graph()` prompt |
| LightRAG 原生 | `server.py` `final_prompt`（非流式 + 流式） |
| Agentic RAG ReAct | `agentic_rag.py` `_build_react_prompt()` 规则 12 |
| Agentic RAG CoT | `agentic_rag.py` `_build_cot_prompt()` 规则 6 |

### Decision 4: 前端恢复纯 Markdown 渲染

AgentChatPage 恢复为直接使用 `<ReactMarkdown components={markdownComponents}>{m.content}</ReactMarkdown>`，移除 CitationMarkdown、CitationPanel、highlightedCitation 状态、事件委托 onClick。

## Risks / Trade-offs

- **[风险] LLM 不遵循引号指令** → **缓解**：提示中多次强调、提供示例格式；内联引用比 `[来源 N]` 格式更自然，LLM 遵循率更高
- **[风险] 原文摘录可能不准确** → **缓解**：要求"逐字复制，至少20字"
- **[权衡] 答案文本变长** → 内联引用增加回答长度约 10-20%，token 消耗略增
