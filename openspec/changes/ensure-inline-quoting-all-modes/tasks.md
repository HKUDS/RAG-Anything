## 1. LightRAG 原生模式文档名注入

- [x] 1.1 在 `server.py` 中新增 `_get_kb_doc_list(kb)` 方法，从 doc_status 获取 KB 下所有文档的名称列表
- [x] 1.2 在 `server.py` 非流式 `final_prompt` 中，检索内容前注入可用文档列表
- [x] 1.3 在 `server.py` 流式 `final_prompt` 中，检索内容前注入可用文档列表
- [x] 1.4 在 `server.py` 提示中更新内联引用指令，要求 LLM 从文档列表中选择正确的文档名

## 2. 验证

- [x] 2.1 验证 hybrid 模式下回答包含 `（来源：正确的文档名）` 而非 `（来源实体：xxx）`
- [x] 2.2 验证 RRF 模式下回答格式不受影响
- [x] 2.3 验证 Agentic RAG 模式下回答格式不受影响
- [x] 2.4 验证前后端启动无报错
