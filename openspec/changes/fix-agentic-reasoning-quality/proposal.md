## Why

ReAct 模式下 Agent 对模糊问题（如"功能模块有哪些"）直接 FINISH 要求用户澄清，完全跳过 search 工具调用。CoT 模式没有任何检索能力，回答完全基于 LLM 自带知识而非 KB 内容。两种模式在真实用户场景下均无法给出正确答案，质量严重不如普通模式。

## What Changes

- **ReAct prompt**: 废除"如果用户的问题需要知识库中的信息，第一步必须先调用 search"这条软约束，改为"无论问题是否明确，第一步必须调用 search 检索知识库，不得在未检索的情况下要求用户澄清或 FINISH"
- **CoT 模式**: 路径从"纯 LLM 思考"改为"先检索→再推理"。`_cot_loop()` 新增 `context` 参数接收预检索上下文，server.py 在 CoT 路径先执行一次 RRF 检索
- CoT prompt 规则改为要求基于检索内容逐步推理并标注来源

## Capabilities

### New Capabilities

- `agentic-reasoning-quality`: AgenticRAG 推理质量保障 — ReAct 强制首步检索、CoT 注入检索上下文

### Modified Capabilities

<!-- No existing spec requirements change. Implementation quality fix. -->

## Impact

- **`raganything/agentic_rag.py`**: `_build_react_prompt()`、`_build_cot_prompt()`、`_cot_loop()`
- **`server.py`**: CoT 路径改为先检索后推理
