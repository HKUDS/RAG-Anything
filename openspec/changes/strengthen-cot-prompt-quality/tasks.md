## 1. CoT Prompt 强化

- [x] 1.1 `agentic_rag.py` `_build_cot_prompt()`: 系统规则新增"每条事实都必须能追溯到检索内容原文，不得编造或增减"
- [x] 1.2 `agentic_rag.py` `_build_cot_prompt()`: user_prompt 追加"不要编造检索内容中没有的信息"

## 2. 验证

- [ ] 2.1 CoT 模式提问，确认回答不包含检索内容以外的编造信息
