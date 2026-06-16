## Why

ReAct prompt 已通过新增规则 8（严格基于检索内容、禁止编造）解决了幻觉问题。CoT prompt 虽有"不得使用你自己的知识"但约束力度不如 ReAct，需要对齐规则强度。

## What Changes

- `_build_cot_prompt()`: 系统 prompt 规则对齐 ReAct 的规则 8 — "每条事实都能追溯到检索内容原文"、"检索内容中列了N个就只列N个"

## Capabilities

### New Capabilities

- `cot-prompt-quality`: CoT prompt 质量强化

### Modified Capabilities

<!-- None -->

## Impact

- **`raganything/agentic_rag.py`**: `_build_cot_prompt()` 系统规则和 user prompt
