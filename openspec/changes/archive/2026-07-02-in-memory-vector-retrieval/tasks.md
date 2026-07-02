## 1. 后端：内存向量检索核心逻辑

- [x] 1.1 在 `workflow_executor.py` 中实现 `_cosine_similarity_top_k(query_vector, chunk_vectors, chunks, top_k)` 函数，使用 numpy 做余弦相似度计算并返回 Top-K
- [x] 1.2 实现 `_collect_upstream_chunks_and_vectors(inputs)` 辅助函数，从上游 outputs 中提取向量和 chunks 列表
- [x] 1.3 重构 `RetrieverExecutor.execute()`：先尝试内存检索（有 vectors+chunks），降级到 LightRAG aquery

## 2. 后端：query_text 支持 + search_mode 标注

- [x] 2.1 RetrieverExecutor 优先使用 config 中的 `query_text` 作为检索 query
- [x] 2.2 Retriever 输出增加 `search_mode` 字段（`"in_memory"` 或 `"knowledge_base"`）

## 3. 前端：Retriever 节点配置更新

- [x] 3.1 `nodeTypes.js`：Retriever 节点增加 `query_text` 配置字段（text 类型，可选）
- [x] 3.2 `WorkflowRunPanel.jsx`：展示 Retriever 结果的 `search_mode` 标识

## 4. 测试验证

- [x] 4.1 搭建 document_input → text_splitter → embedding → retriever → llm_answer → output 工作流，输入 query_text，验证内存检索模式返回正确结果
- [x] 4.2 仅 retriever → llm_answer → output 工作流（无上游向量），验证降级到 KB 检索正常
