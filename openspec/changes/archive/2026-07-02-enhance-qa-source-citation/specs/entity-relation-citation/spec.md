# Entity Relation Citation

## Purpose

在 RAG 问答回答中强制要求 LLM 引用知识图谱中的实体关系路径，并在回答末尾附带结构化的"关联实体"块，使用户能追溯回答中涉及的实体及其关系。

## ADDED Requirements

### Requirement: LLM 实体关系引用指令

所有使用知识图谱通道的查询提示 SHALL 包含实体关系引用指令，要求 LLM 在回答中明确标注涉及的实体及其关系路径。

#### Scenario: Graph 查询包含实体引用指令

- **WHEN** 系统构建知识图谱（Graph）查询模式的 LLM 提示
- **THEN** 提示 MUST 包含指令要求 LLM 在回答中引用实体关系，格式为 `实体A →[关系]→ 实体B`
- **AND** 提示 MUST 要求 LLM 在回答末尾附带"关联实体"部分，列出涉及的关键实体及其关系摘要

#### Scenario: RRF 查询包含实体引用指令

- **WHEN** 系统在 RRF 混合检索模式下检测到上下文中包含实体标注（`（涉及实体：...）`）
- **THEN** 提示 MUST 包含指令要求 LLM 在回答中引用这些实体及其关系
- **AND** 若上下文不包含实体标注，MUST 不强制要求实体引用

#### Scenario: Agentic RAG 查询包含实体引用指令

- **WHEN** 系统在 Agentic RAG 模式下执行查询
- **THEN** ReAct 系统提示 MUST 要求在 FINISH 动作输出中包含关联实体块

### Requirement: 关联实体块格式

LLM 回答中的"关联实体"块 SHALL 使用统一的格式，便于程序化解析。

#### Scenario: 关联实体块标准格式

- **WHEN** LLM 在回答末尾输出关联实体块
- **THEN** 格式 MUST 为 `【关联实体】\n- 实体名（类型）←[关系]← 实体名（类型）` 或 `- 实体名（类型）→[关系]→ 实体名（类型）`
- **AND** 每个实体 MUST 附带其类型标注（如 人物、组织、概念、事件等）

#### Scenario: 无实体关系时的降级

- **WHEN** 检索结果中不包含实体关系信息
- **THEN** LLM MUST 不编造实体关系
- **AND** 可省略"关联实体"块

### Requirement: 实体关系解析器扩展

引用解析器 `citation_parser.py` SHALL 支持从 LLM 回答中提取关联实体信息。

#### Scenario: 解析关联实体块

- **WHEN** LLM 回答中包含 `【关联实体】` 块
- **THEN** 解析器 MUST 提取出实体关系列表，每项包含 `entity_a`、`relation`、`entity_b` 和 `entity_types` 字段

#### Scenario: 关联实体整合到 citations 响应

- **WHEN** 查询 API 返回响应
- **THEN** `citations` 对象 MUST 包含 `entity_relations` 数组
- **AND** 每条实体关系 MUST 包含 `entity_a`、`relation`、`entity_b`、`types` 字段
