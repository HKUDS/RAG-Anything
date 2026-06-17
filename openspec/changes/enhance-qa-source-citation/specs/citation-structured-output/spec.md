# Citation Structured Output (Delta)

## MODIFIED Requirements

### Requirement: LLM 引用格式指令

通用 RAG 查询提示 SHALL 包含**强制**的引用格式指令，要求 LLM 在回答中**必须**使用 `[来源 N]` 标注每条引用的来源，不可省略。

#### Scenario: RRF 查询包含强制引用格式指令

- **WHEN** 系统构建 RRF 查询模式的 LLM 提示
- **THEN** 提示 MUST 包含"**必须**使用 `[来源 N]` 格式标注引用"的强制指令
- **AND** 提示 MUST 包含"每个事实性陈述必须标注来源，不得省略"的明确要求
- **AND** 提示 MUST 要求 LLM 在回答末尾附带"【引用来源】"部分，包含每条来源的编号、源文档名和原文摘录

#### Scenario: Graph 查询包含强制引用格式指令

- **WHEN** 系统构建知识图谱查询模式的 LLM 提示
- **THEN** 提示 MUST 包含与 RRF 模式一致的强制引用格式要求
- **AND** 提示 MUST 额外要求 LLM 在回答中引用实体关系路径

#### Scenario: Agentic RAG 查询包含强制引用格式指令

- **WHEN** 系统在 Agentic RAG 模式下执行查询
- **THEN** ReAct 系统提示 MUST 要求 FINISH 动作的输出包含 `[来源 N]` 格式标注
- **AND** 若 FINISH 输出缺少 `[来源 N]` 标记，系统 SHALL 追加补充引用请求

#### Scenario: 来源引用缺失时的处理

- **WHEN** LLM 回答中不包含任何 `[来源 N]` 格式标记
- **THEN** 系统 MUST 记录警告日志
- **AND** 若 `enforce_citation` 配置项启用，系统 SHALL 自动发起一次补充 LLM 请求，要求为回答添加来源引用

### Requirement: 查询响应包含 citations 字段

所有查询 API 的响应 SHALL 包含 `citations` 字段，其值为结构化引用列表，**并新增 `entity_relations` 子字段**。

#### Scenario: 非流式查询返回 citations

- **WHEN** 客户端调用 `/api/query` 执行非流式查询
- **THEN** 响应 JSON MUST 包含 `citations` 字段
- **AND** `citations` 字段 MUST 为对象，包含 `sources` 数组（每项含 `index`、`document_name`、`excerpt`、`file_path`）和 `entity_relations` 数组（每项含 `entity_a`、`relation`、`entity_b`、`types`）

#### Scenario: 流式查询在 done 事件返回 citations

- **WHEN** 客户端连接 `/api/query/stream` 执行流式查询
- **THEN** SSE `done` 事件 MUST 包含 `citations` 字段
- **AND** `citations` 的数据结构 MUST 与非流式查询一致（含 `sources` 和 `entity_relations`）

#### Scenario: 向后兼容

- **WHEN** 现有客户端未处理 `citations` 字段
- **THEN** 响应中的其他字段（`answer`, `images`, `id` 等）MUST 保持不变
- **AND** 未处理 `citations` 的客户端 MUST 不受影响
- **AND** `citations.sources` 数组的结构 MUST 与旧版 `citations` 数组格式保持兼容（新增 `entity_relations` 为独立子字段）
