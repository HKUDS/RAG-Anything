## MODIFIED Requirements

### Requirement: LLM 内联原文引用覆盖所有模式

所有检索模式（RRF、Graph、LightRAG 原生 hybrid/mix/local/global/naive、Agentic RAG ReAct/CoT）的 LLM 提示 SHALL 包含足够信息使 LLM 能输出 `"原文摘录..."（来源：文档名）` 格式。

#### Scenario: LightRAG 原生模式有文档名可用

- **WHEN** 系统通过 LightRAG 原生模式执行查询
- **THEN** server.py 构建的 prompt MUST 在检索内容前包含 KB 中可用文档的名称列表
- **AND** LLM 回答中的原文引用 MUST 能标注正确的文档名

#### Scenario: LightRAG 原生模式无文档名可用

- **WHEN** KB 中无文档或检索结果无法追溯到具体文档
- **THEN** LLM MUST 只引用原文，不编造来源名称
- **AND** LLM MUST NOT 使用实体名作为来源标注

#### Scenario: 所有模式统一降级行为

- **WHEN** 任何检索模式下 context 中无文档名信息
- **THEN** LLM MUST 只输出 `"原文..."` 格式（有引号，无来源标注）
- **AND** MUST NOT 输出 `（来源实体：xxx）` 或类似编造的来源格式
