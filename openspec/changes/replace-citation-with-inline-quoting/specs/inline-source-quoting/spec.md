## ADDED Requirements

### Requirement: LLM 内联原文引用

所有检索模式的 LLM 提示 SHALL 包含内联原文引用指令，要求 LLM 在回答中直接嵌入检索内容的原文摘录。

#### Scenario: RRF 模式下 LLM 内联引用原文

- **WHEN** 系统通过 RRF 模式执行查询
- **THEN** LLM 提示 MUST 包含要求"引用检索内容时用引号直接嵌入原文摘录"的指令
- **AND** LLM 回答中的事实陈述 MUST 附带引号标注的原文摘录

#### Scenario: Graph 模式下 LLM 内联引用原文

- **WHEN** 系统通过知识图谱模式执行查询
- **THEN** LLM 提示 MUST 包含与 RRF 模式一致的内联引用指令

#### Scenario: LightRAG 原生模式下 LLM 内联引用原文

- **WHEN** 系统通过 LightRAG 原生模式（hybrid/mix/local/global/naive）执行查询
- **THEN** server.py 构建的 prompt MUST 包含内联引用指令

#### Scenario: Agentic RAG 模式下 LLM 内联引用原文

- **WHEN** 系统通过 Agentic RAG（ReAct/CoT）模式执行查询
- **THEN** 系统提示 MUST 包含内联引用规则

### Requirement: 移除结构化引用标记

LLM 提示 SHALL NOT 要求使用 `[来源 N]` 标记或 `【引用来源】` 块格式。

#### Scenario: 回答中无来源标记

- **WHEN** LLM 生成回答
- **THEN** 回答 MUST NOT 包含 `[来源 N]` 格式的标记
- **AND** 回答 MUST NOT 包含 `【引用来源】` 块

## MODIFIED Requirements

### Requirement: 查询响应不包含 citations 字段

查询 API 的响应 MAY 省略 `citations` 字段。引用信息通过回答文本中的内联原文摘录体现。

#### Scenario: 非流式查询响应

- **WHEN** 客户端调用 `/api/query`
- **THEN** 响应 JSON MUST NOT 包含 `citations` 字段
- **AND** `answer` 字段 MUST 包含内联原文引用

#### Scenario: 流式查询 done 事件

- **WHEN** SSE 流式查询完成
- **THEN** `done` 事件 MUST NOT 包含 `citations` 字段

## REMOVED Requirements

### Requirement: 引用来源展示面板

**Reason**: 替换为内联原文引用，不再需要独立的引用面板。

**Migration**: 引用信息已嵌入回答正文，前端恢复纯 Markdown 渲染。

### Requirement: 引用内联标记渲染

**Reason**: 不再使用 `[来源 N]` 标记，无需自定义渲染。

**Migration**: 移除 CitationMarkdown 组件，恢复 ReactMarkdown 直接渲染。

### Requirement: 源文档跳转

**Reason**: 内联引用直接展示原文，无需跳转到源文件。

**Migration**: 移除 `/api/document/open` 和 `/api/document/context` 端点。
