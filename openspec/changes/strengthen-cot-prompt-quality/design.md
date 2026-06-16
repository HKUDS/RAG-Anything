## Context

ReAct 和 CoT 使用两套独立的 system prompt。ReAct prompt 已在上一个 change 中强化了质量规则（"每条事实都能追溯到 Observation 原文"），CoT 需要同步。

## Decisions

### Decision 1: CoT 规则对齐 ReAct

**修改**: 在 CoT system_prompt 规则中新增：
- "最终回答中的每条事实都必须能追溯到检索内容的原文"
- "如果检索内容中列出了 N 个条目，就只列出那 N 个，不要增减"

并在 user_prompt 中补强："不要编造检索内容中没有的信息。"
