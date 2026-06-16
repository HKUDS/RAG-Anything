## 1. ReAct Prompt 修复

- [x] 1.1 `agentic_rag.py` `_build_react_prompt()`: 规则 2 从"如果用户的问题需要知识库中的信息，第一步必须先调用 search"改为"第一步必须调用 search 检索知识库。不得在检索前 FINISH 或反问用户"
- [x] 1.2 `agentic_rag.py` `_build_react_prompt()`: 规则 7 从"如果确实无法回答，Action 设为 FINISH"改为"只有在至少检索 1 次且仍然无法回答时，才能 FINISH 并说明无法回答"

## 2. CoT 检索增强

- [x] 2.1 `agentic_rag.py` `_cot_loop()`: 签名新增 `context: str = ""` 参数
- [x] 2.2 `agentic_rag.py` `_build_cot_prompt()`: 当 context 非空时，user_prompt 改为 `## 检索内容\n{context}\n\n## 用户问题\n{query}\n\n请基于上述检索内容逐步推理...`
- [x] 2.3 `agentic_rag.py` `AgenticRAG.run()`: 新增 `run_with_context(query, context)` 方法，调用 `_cot_loop(query, context=context)`
- [x] 2.4 `server.py` CoT 路径: 在 `agentic.run()` 前先执行 RRF 检索获取 context，通过 `agentic.run_with_context(query, context)` 传入

## 3. 验证

- [ ] 3.1 重启服务，ReAct 模式提问"功能模块有哪些"，确认第一步调用 search 并给出基于 KB 的回答
- [ ] 3.2 CoT 模式提问"功能模块有哪些"，确认回答引用检索内容而非通用知识
- [ ] 3.3 普通模式提问同一问题，确认行为不变（回归）
