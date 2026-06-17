## Why

当前工作流 Retriever 节点只能查询 LightRAG 持久化知识库，导致 document_input → text_splitter → embedding 链路产出的 chunks 和 vectors 被浪费——用户必须先将文件上传到主界面知识库，工作流才能检索。这割裂了"端到端文档问答"体验。

## What Changes

- **RetrieverExecutor 增加内存向量检索模式**：当上游节点提供了 vector 和 chunks 时，直接在内存中做余弦相似度检索，不依赖 LightRAG 持久化 KB
- **RetrieverExecutor 保留 KB 检索降级**：当上游没有 vectors/chunks 时，退回到原有的 LightRAG aquery 方式
- **Retriever 节点增加 query 输入配置**：允许用户在前端手动输入检索问题文本，替代自动从上游 chunks 拼接的 query
- Embedding 节点输出标准化，确保 vector 数据可被下游 Retriever 消费

## Capabilities

### New Capabilities
- `in-memory-vector-retrieval`: Retriever 节点支持基于上游 Embedding 节点产出的向量和 TextSplitter 产出的 chunks，在内存中进行余弦相似度 Top-K 检索

### Modified Capabilities
<!-- 无现有 spec 被修改 -->

## Impact

- `raganything/workflow_executor.py` — RetrieverExecutor 重构
- `frontend/src/components/workflow/nodeTypes.js` — Retriever 节点增加 query 配置字段
- `frontend/src/components/workflow/NodeConfigPanel.jsx` — 新增 query 输入框 UI
