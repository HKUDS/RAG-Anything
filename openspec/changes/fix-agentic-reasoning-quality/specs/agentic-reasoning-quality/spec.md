# Agentic Reasoning Quality

## Purpose

修复 ReAct 模式下 Agent 跳过 search 直接 FINISH 的问题，以及 CoT 模式完全无检索能力导致编造回答的问题。

## ADDED Requirements

### Requirement: ReAct 强制首步检索
ReAct 推理 prompt SHALL 要求 Agent 第一步必须调用 search 工具检索知识库，不得在未检索的情况下 FINISH 或要求用户澄清。

#### Scenario: 模糊问题也必须先检索
- **WHEN** 用户提问不包含明确的系统/领域名称（如"功能模块有哪些"）
- **THEN** Agent SHALL 第一步调用 search 检索知识库，而非要求用户澄清

#### Scenario: 检索结果为空时允许说明
- **WHEN** search 返回"知识库中未找到相关信息"
- **THEN** Agent SHALL 在 FINISH 回答中说明"知识库中未找到相关信息"，可建议用户补充细节

### Requirement: CoT 模式注入检索上下文
CoT 推理 SHALL 在 LLM 推理前先通过 RRF 检索获取知识库上下文，将上下文注入 CoT prompt，确保推理基于检索内容而非 LLM 自带知识。

#### Scenario: CoT 先检索后推理
- **WHEN** server.py 以 agent_mode="cot" 执行查询
- **THEN** 系统 SHALL 先调用 `rag.aquery(mode="rrf", only_need_context=True)` 获取上下文，再启动 AgenticRAG(mode="cot").run()

#### Scenario: CoT 基于检索内容回答
- **WHEN** 检索上下文包含"糖尿病视网膜病变筛查工具"的功能模块信息
- **THEN** CoT 回答 SHALL 引用检索内容中的具体模块名称，不得编造通用软件工程概念

### Requirement: _cot_loop 接受外部上下文参数
`_cot_loop()` SHALL 接受可选的 `context: str` 参数，当提供时将上下文注入 prompt 的检索内容区域。

#### Scenario: 带上下文调用
- **WHEN** `_cot_loop(query, context="...")` 被调用
- **THEN** CoT prompt 的 user prompt SHALL 包含 `## 检索内容\n{context}\n\n## 用户问题\n{query}`

#### Scenario: 不带上下文调用（向后兼容）
- **WHEN** `_cot_loop(query)` 不传 context 参数
- **THEN** 行为 SHALL 与现有版本一致（纯 LLM 推理，不做检索注入）

### Requirement: ReAct 提示词精确前后矛盾
ReAct prompt 中的规则 7 SHALL 从"如果确实无法回答，Action 设为 FINISH，Action Input: {"answer": "抱歉，当前无法回答此问题"}"改为"只有在至少检索 1 次且仍然无法回答时，才能 FINISH 并说明无法回答"
