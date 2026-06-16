# CoT Prompt Quality

## Purpose

对齐 CoT prompt 与 ReAct prompt 的质量约束强度，防止 CoT 模式编造或增减检索内容中不存在的信息。

## ADDED Requirements

### Requirement: CoT prompt 严格基于检索内容
CoT system prompt SHALL 包含"最终回答中的每条事实都必须能追溯到检索内容的原文，不得添加检索内容中没有的信息，不得使用你自己的知识补充或编造"的规则。

#### Scenario: 不编造不增减
- **WHEN** 检索内容列出 6 个模块
- **THEN** CoT 回答 SHALL 只列出这 6 个，不增减模块名称
