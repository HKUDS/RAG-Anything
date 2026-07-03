## ADDED Requirements

### Requirement: PromptBuilder 统一构造

系统 SHALL 通过 `PromptBuilder` 类统一三种智能体模式（RAG/ReAct/CoT）的 Prompt 拼接逻辑，替代当前分散在 `agent.py` 中的三处独立拼接代码。

#### Scenario: Builder 组装所有上下文层
- **WHEN** 调用 `PromptBuilder` 并依次添加 system instruction、user profile、conversation summary、recent history、image context、retrieval context、user query
- **THEN** `build()` 方法按 priority（升序）组装所有启用的层
- **AND** 返回 `(final_prompt, system_prompt)` 元组

#### Scenario: 禁用的层不出现在 Prompt 中
- **WHEN** 某个 context layer 的 `enabled=False`
- **THEN** 该层内容不出现在最终 Prompt 中
- **AND** 其他层按原有顺序正常组装

#### Scenario: 三种模式输出一致性
- **WHEN** 使用相同输入分别在 RAG/ReAct/CoT 模式调用 `PromptBuilder.build()`
- **THEN** 生成的 Prompt 结构与重构前对应模式的输出一致
- **AND** 对话历史、检索结果、用户问题的相对顺序不变

### Requirement: 上下文分层模型

系统 SHALL 支持按优先级分层组装 Prompt 上下文，每层拥有独立的 `priority`（升序排列）、`max_tokens`、`enabled` 属性。

#### Scenario: 层级定义
- **WHEN** 系统组装 Prompt
- **THEN** 支持以下上下文层（按默认 priority 排序）：
  - Layer 0: 系统指令（system_instruction），永不截断
  - Layer 1: 用户画像（user_profile），priority=10，max_tokens=500，默认关闭
  - Layer 2: 对话摘要（conversation_summary），priority=20，max_tokens=1000
  - Layer 3: 近期对话（recent_history），priority=30，max_tokens=CONVERSATION_MAX_TOKENS
  - Layer 4: 图片上下文（image_context），priority=25，max_tokens=2000
  - Layer 5: 检索结果（retrieval_context），使用剩余 token 预算
  - Layer 6: 用户问题 + 引用指令（user_query），永不截断

#### Scenario: Token 超预算时截断低优先级层
- **WHEN** 所有层的预估总 token 超过全局 `max_tokens` 预算
- **THEN** 从 priority 最低的非系统层开始截断
- **AND** 先截断检索结果（Layer 5），再截断近期对话（Layer 3），以此类推
- **AND** 系统指令（Layer 0）和用户问题（Layer 6）永不截断

#### Scenario: 分层可配置
- **WHEN** 通过环境变量或配置字典修改某层的 `max_tokens` 或 `enabled`
- **THEN** 系统按新配置组装 Prompt
- **AND** 支持 `PROMPT_LAYER_<NAME>_MAX_TOKENS` 和 `PROMPT_LAYER_<NAME>_ENABLED` 环境变量覆盖

### Requirement: 图片上下文独立层

系统 SHALL 将图片描述和视觉相似图片信息作为独立的上下文层（image_context），而非嵌入到对话历史或检索结果中。

#### Scenario: 图片上下文注入
- **WHEN** 用户查询包含图片（有 image_description 或 similar_images）
- **THEN** 图片上下文作为独立层（priority=25）注入 Prompt
- **AND** 图片层出现在近期对话（priority=30）之前、对话摘要（priority=20）之后

#### Scenario: 无图片时不注入
- **WHEN** 用户查询不包含图片
- **THEN** image_context 层 disabled，不出现在 Prompt 中
