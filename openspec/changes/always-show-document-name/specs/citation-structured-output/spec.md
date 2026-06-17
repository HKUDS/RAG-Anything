# Citation Structured Output (Delta)

## MODIFIED Requirements

### Requirement: LLM 引用格式指令

通用 RAG 查询提示 SHALL 包含**强制**的引用格式指令。每条引用的 `[来源 N]` 标记**必须**对应一个源文档名，不可省略。LLM 不得仅在句末标注来源编号而不指明文档名。

#### Scenario: RRF 查询包含强制文档名指令

- **WHEN** 系统构建 RRF 查询模式的 LLM 提示
- **THEN** 提示 MUST 包含"每条引用必须标注所属文档名"的强制指令
- **AND** 提示 MUST 要求 `【引用来源】` 块中每条 `[来源 N]` 条目包含 `源文档：文档名`
- **AND** 若检索内容中某条来源确实无文档名，MUST 标注 `源文档：未知文档`

#### Scenario: Graph 查询包含强制文档名指令

- **WHEN** 系统构建知识图谱查询模式的 LLM 提示
- **THEN** 提示 MUST 包含与 RRF 模式一致的强制文档名要求

#### Scenario: 文档名映射辅助

- **WHEN** 检索上下文开头提供了"可用文档"列表（`## 可用文档`）
- **THEN** LLM MUST 使用该列表中的文档名填写 `【引用来源】` 块
- **AND** 如果来源编号对应的 chunk 在上下文中标注了文档名（如 `(文档：xxx)`），MUST 使用该文档名
