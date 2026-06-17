## 1. Prompt 指令强化

- [ ] 1.1 修改 `raganything/prompt.py` 中 `ANSWER_FORMAT_INSTRUCTION` 第 3 条：将"若检索内容有文档名…"改为"每条引用必须标注所属文档名；若无则标注'未知文档'"
- [ ] 1.2 修改第 4 条：强调 `【引用来源】` 块每个条目必须包含 `源文档：文档名`

## 2. Server 端检索上下文增强

- [ ] 2.1 修改 `server.py` 中 `_get_kb_doc_list` 的返回格式：在文档列表前加指引文字，帮助 LLM 映射文档名
- [ ] 2.2 检查 `query_rag` 和 `query_rag_stream` 中 `final_prompt` 的文档信息传递是否完整

## 3. 验证

- [ ] 3.1 单元测试：验证 `ANSWER_FORMAT_INSTRUCTION` 包含"必须标注所属文档名"和"未知文档"
- [ ] 3.2 端到端测试：在 12345678 知识库查询"系统包含哪些功能模块"，验证回答的 `【引用来源】` 块每条包含文档名
