# Answer Format Specification

## Purpose

定义 RAG-Anything 所有查询模式下 LLM 回答的标准输出格式模板，确保每个回答的结构清晰一致：正文 → 来源引用块 → 关联实体块，使用户能快速定位答案、验证来源和追溯实体关系。

## ADDED Requirements

### Requirement: 标准化回答格式模板

所有查询提示 SHALL 要求 LLM 按照统一的三段式结构输出回答。

#### Scenario: 标准三段式输出结构

- **WHEN** LLM 完成检索增强生成
- **THEN** 回答 MUST 按以下顺序组织：
  1. **回答正文**：清晰回答用户问题，使用自然流畅的语言
  2. **【引用来源】**：列出所有引用的来源，每项包含编号、源文档名和原文摘录
  3. **【关联实体】**（如有）：列出回答中涉及的关键实体及其关系

#### Scenario: 回答正文可读性要求

- **WHEN** LLM 生成回答正文
- **THEN** 正文 MUST 使用段落分明的自然语言，避免冗长的单段文字
- **AND** 引用原文时必须使用 `[来源 N]` 上标标记，格式为 `"原文摘录..."`[来源 1]
- **AND** 每个要点 MUST 只引用 1-2 处关键原文，保持回答简洁流畅

#### Scenario: 引用来源块格式

- **WHEN** LLM 输出引用来源块
- **THEN** 格式 MUST 为：
  ```
  【引用来源】
  [来源 1] 源文档：xxx.pdf | 原文："被引用的原文摘录..."
  [来源 2] 源文档：yyy.docx | 原文："被引用的原文摘录..."
  ```
- **AND** 每个 `[来源 N]` 标记 MUST 与正文中的引用编号一一对应

### Requirement: 来源缺失保护

系统 SHALL 在回答中未检测到来源引用时进行纠正。

#### Scenario: 检测到引用标记缺失

- **WHEN** 解析器检测到 LLM 回答中不包含任何 `[来源 N]` 标记
- **THEN** 系统 MUST 在日志中记录警告
- **AND** 若启用了自动纠正，系统 SHALL 追加一段 LLM 请求以补充引用

#### Scenario: 引用来块缺失但内联引用存在

- **WHEN** LLM 回答包含 `[来源 N]` 内联标记但缺少 `【引用来源】` 块
- **THEN** 解析器 MUST 仍能通过内联标记提取引用信息
- **AND** MUST NOT 触发纠正请求

### Requirement: 不同查询模式格式一致性

所有查询模式（RRF、Graph、Agentic）的输出 SHALL 遵循相同的三段式结构。

#### Scenario: RRF 模式遵循标准格式

- **WHEN** 系统通过 RRF 模式执行查询
- **THEN** LLM 提示 MUST 包含标准三段式格式要求

#### Scenario: Graph 模式遵循标准格式

- **WHEN** 系统通过知识图谱模式执行查询
- **THEN** LLM 提示 MUST 包含标准三段式格式要求

#### Scenario: Agentic RAG 模式遵循标准格式

- **WHEN** 系统在 Agentic RAG 模式下执行查询
- **THEN** FINISH 动作的输出 MUST 遵循标准三段式格式
