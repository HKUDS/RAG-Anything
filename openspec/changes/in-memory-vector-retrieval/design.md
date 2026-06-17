## Context

当前工作流执行器 `RetrieverExecutor` 仅支持查询 LightRAG 持久化知识库（`kb_instance.lightrag.aquery()`）。工作流中 document_input → text_splitter → embedding 链路产出的 chunks 和 vectors 被完全忽略。用户必须先将文档通过主界面上传到知识库，工作流才能检索到内容。

**目标架构**：Retriever 的输入可以是（a）上游节点传来的临时 chunks+vectors，或（b）持久化 KB。优先使用（a），降级到（b）。

## Goals / Non-Goals

**Goals:**
- Retriever 收到上游 vectors + chunks 时，用余弦相似度在内存中做 Top-K 检索
- 无上游向量数据时，退回到原有 LightRAG aquery 行为（向后兼容）
- 前端 Retriever 节点支持手动输入 query 文本（可选的 query 输入框）
- 使用纯 Python 实现余弦相似度，零外部依赖

**Non-Goals:**
- 不替换或重构 LightRAG 的持久化检索逻辑
- 不改动 Embedding 节点的输出格式
- 不支持大规模向量检索（百万级）——这是内存方案，受限于单次工作流执行
- 不支持索引持久化——每次工作流运行都重新计算

## Decisions

### Decision 1: 余弦相似度用纯 numpy 实现

**选择**：numpy 向量点积归一化，不引入 faiss/chroma 等向量数据库。

**理由**：
- 工作流 context 内 chunks 数量通常 < 1000，numpy 批量计算足够
- 零新增依赖，numpy 已存在于 lightrag 依赖链
- 代码简单透明，不超过 30 行

**备选**：faiss-cpu（更快但多一个依赖），chromadb（过重）

### Decision 2: Retriever 自动判断检索模式

**选择**：根据输入数据自动切换，不增加配置项。

```python
has_vector = any("vector" in v or ("dims" in v and v.get("dims", 0) > 0) for v in upstream_inputs.values())
if has_vector and chunks_available:
    # 内存模式：余弦相似度
else:
    # KB 模式：LightRAG aquery
```

**理由**：用户无需配置模式，零学习成本。有向量就用内存检索，没有就查 KB。

### Decision 3: Node config 增加 query 输入框

**选择**：Retriever 节点增加 `query_text` 字段（text 类型），用户手动输入要检索的问题。

**理由**：当前自动拿上游 chunks 拼接为 query 不合理——chunks 是文档内容，不是检索问题。用户应该输入类似"糖尿病视网膜病变如何分级？"这样的自然语言问题。

### Decision 4: Retriever 数据流优先级

```
1. config.query_text（手动输入）→ 作为检索 query
2. 上游 embedding 节点 vector → 直接用于相似度计算
3. 上游 text_splitter 节点 chunks → 作为被检索的文档池
```

上游 inputs 合并规则：多个上游节点的 outputs 合并到 inputs dict，key 冲突时后者覆盖。

## Risks / Trade-offs

- **[内存压力]** 大批量 chunks 全部加载到内存 → 已有 max_size_mb 限制输入端，chunks 总数通常可控
- **[降级行为不透明]** 用户可能不知道走了哪种检索模式 → 在返回结果中标注 `search_mode: "in_memory"` 或 `search_mode: "knowledge_base"`，前端 RunPanel 展示
- **[余弦相似度 vs BM25]** 纯向量检索可能不如混合检索 → 后续可在内存模式中加简单的 BM25 评分融合（不在本次范围）
