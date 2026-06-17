## ADDED Requirements

### Requirement: LLM 引用格式指令

通用 RAG 查询提示 SHALL 包含明确的引用格式指令，要求 LLM 在回答中使用 `[来源 N]` 标注每条引用的来源。

#### Scenario: RRF 查询包含引用格式指令

- **WHEN** 系统构建 RRF 查询模式的 LLM 提示
- **THEN** 提示 MUST 包含要求 LLM 使用 `[来源 N]` 格式标注引用的指令
- **AND** 提示 MUST 要求 LLM 在回答末尾附带"引用来源"部分，包含每条来源的编号、源文档名和原文摘录

#### Scenario: Graph 查询包含引用格式指令

- **WHEN** 系统构建知识图谱查询模式的 LLM 提示
- **THEN** 提示 MUST 包含与 RRF 模式一致的引用格式要求

#### Scenario: Agentic RAG 查询包含引用格式指令

- **WHEN** 系统在 Agentic RAG 模式下执行查询
- **THEN** ReAct 系统提示 MUST 要求 FINISH 动作的输出包含 `[来源 N]` 格式标注

### Requirement: 引用解析器

系统 SHALL 提供通用引用解析模块 `citation_parser.py`，从 LLM 回答文本中提取结构化的引用列表。

#### Scenario: 解析标准格式引用

- **WHEN** LLM 回答中包含 `[来源 1] 源文档：xxx.pdf | 原文："..."` 格式的引用
- **THEN** 解析器 MUST 提取出包含 `index`（来源编号）、`document_name`（源文档名）、`excerpt`（原文摘录）的结构化列表
- **AND** 解析器 MUST 正确解析中文标点（全角引号、中文冒号等）

#### Scenario: 解析仅有编号的引用

- **WHEN** LLM 回答中仅包含 `[来源 N]` 标记而无附带原文
- **THEN** 解析器 MUST 提取出 `index` 和 `document_name`
- **AND** `excerpt` 字段 MUST 设为从对应 chunk 内容中自动截取的前 200 字符

#### Scenario: 回答中无引用标记

- **WHEN** LLM 回答中不包含任何 `[来源 N]` 格式的标记
- **THEN** 解析器 MUST 返回空列表
- **AND** 系统 MAY 触发 LLM 补充引用的纠正请求

### Requirement: 查询响应包含 citations 字段

所有查询 API 的响应 SHALL 包含 `citations` 字段，其值为结构化引用列表。

#### Scenario: 非流式查询返回 citations

- **WHEN** 客户端调用 `/api/query` 执行非流式查询
- **THEN** 响应 JSON MUST 包含 `citations` 字段
- **AND** `citations` 字段 MUST 为数组，每项包含 `index`、`document_name`、`excerpt`、`file_path` 字段

#### Scenario: 流式查询在 done 事件返回 citations

- **WHEN** 客户端连接 `/api/query/stream` 执行流式查询
- **THEN** SSE `done` 事件 MUST 包含 `citations` 字段
- **AND** `citations` 的数据结构 MUST 与非流式查询一致

#### Scenario: 向后兼容

- **WHEN** 现有客户端未处理 `citations` 字段
- **THEN** 响应中的其他字段（`answer`, `images`, `id` 等）MUST 保持不变
- **AND** 未处理 `citations` 的客户端 MUST 不受影响
