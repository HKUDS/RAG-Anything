## Context

### 架构背景

制造智能体（Manufacturing Agent）使用自定义的 RRF 三路融合检索引擎（`HybridSearchEngine`），而非 LightRAG 原生的 `aquery()`。两条路径的对比如下：

```
普通智能体:  query → LightRAG.aquery(mode="hybrid")
                 → 实体匹配 → 关系遍历 → chunk 提取 → LLM

制造智能体:  query → HybridSearchEngine.search()
                 ├─ BM25 通道 (Okapi BM25 + jieba)
                 ├─ Graph 通道 (实体匹配 + BFS 邻居遍历)
                 └─ Vector 通道 (LightRAG.aquery mode="local")
                 → RRF 融合 → 取 top-15 → LLM
```

测试环境：小语料库（4 chunks，2 文档），`chunk_token_size=800`。

### 问题链

在同一 KB 上问 "PLC 输出信号无响应"，普通智能体正确回答（引用了 PLC 文档第 2.2 节），制造智能体回答"参考资料中未找到相关信息"。以下是从检索到生成的完整问题链：

**Step 1 — BM25 通道全空（已修复）**

```
Query "PLC 输出信号无响应" → jieba → ["PLC", "输出", "信号", "无", "响应"]

语料库 N=4，"PLC" 出现在 2/4 文档，"输出" 出现在 2/4 文档...
BM25 IDF = log((N - df + 0.5) / (df + 0.5))
当 df≥2, N=4 时 → IDF ≤ 0 → BM25 score ≤ 0

hybrid_search.py:172:
  if scores[idx] <= 0: continue  ← 🔴 全部丢弃

BM25 通道返回 0 条结果
```

**Step 2 — Graph 通道崩溃（已修复）**

```
LightRAG NetworkXStorage API (≥1.3):
  get_all_nodes() → async, returns coroutine
  get_node(id)    → async, returns coroutine
  get_node_edges  → async, returns coroutine
  node_degree     → async, returns coroutine

原代码（同步调用）:
  all_nodes = graph.get_all_nodes()    → coroutine object
  for node_data in all_nodes:          → 🔴 'coroutine' is not iterable
  degree = graph.node_degree(node_id)  → coroutine, never awaited

Graph 通道崩溃，返回 0 条结果
```

**Step 3 — Vector 通道模式不当（已修复）**

```
原代码: QueryParam(mode="local", ...)
  → LightRAG local 模式: 实体优先搜索
    → 匹配实体 → 遍历关联 → 收集关联 chunk
    → 实体提取质量差时 → 0 chunks 关联

日志证据:
  "Final context: 41 entities, 34 relations, 0 chunks"

Vector 通道返回实体/关系，但没有 raw text chunks
```

**Step 4 — RRF 融合结果（待验证）**

三个通道都修复后，BM25 返回 4 chunks，Vector 返回 4 chunks，Graph 返回若干 chunks。RRF 融合去重后应得到 ~8 chunks。但即使检索到了正确的 chunk（PLC 文档第 2.2 节），LLM 仍说"参考资料中没有"——说明 RRF→LLM 的 context 传递链路可能有问题。

`_aquery_rrf` 中的 context 构建：
```python
for i, chunk in enumerate(chunks[:15]):
    context_parts.append(f"[Doc {i+1}] (sources: {sources_str})\n{chunk.content}")
context = "\n\n".join(context_parts)
```

`chunk.content` 字段来自 `ScoredChunk`。需要验证三个通道创建的 `ScoredChunk` 对象的 `content` 字段是否正确填充。

## Decisions

### Decision 1: BM25 移除 `<= 0` 过滤

**选择**：移除 `if scores[idx] <= 0: continue`，让所有非空结果进入 RRF 融合。

**理由**：RRF 使用 rank-based fusion（`1/(k + rank)`），只关心通道内的相对排序，不关心绝对分数大小。负分/零分不影响排序正确性。

**替代方案**：将 IDF 公式改为非负（如 `max(0, idf)`）。缺点是改变了 BM25 的标准语义，且 rank_bm25 库不可控。

### Decision 2: GraphRetriever 全方法 async 化

**选择**：将 `_match_entities`、`_traverse_neighbors`、`search`、`get_subgraph` 全部改为 async，内部 await 所有 NetworkXStorage 调用。

**理由**：lightrag-hku≥1.3 中 NetworkXStorage 的 `get_all_nodes`、`get_node`、`get_node_edges`、`get_all_edges`、`node_degree` 全部是 async 方法。不 await 会导致 coroutine was never awaited 警告和 `not iterable` 错误。

### Decision 3: Vector 通道使用 naive 模式

**选择**：`QueryParam(mode="naive", ...)` 替代 `mode="local"`。

**理由**：naive 模式直接在 chunk 向量空间做相似度搜索，不依赖实体提取质量。在小语料库和实体质量差的场景下更可靠。lightRAG naive 模式等价于纯向量检索。

**替代方案**：使用 hybrid 模式。缺点是 hybrid 模式内部也做实体匹配+全局社区，与 RRF 的 graph 通道功能重叠。

### Decision 4: Context 传递链路修复（新增，待实施）

**问题分析**：即使 RRF 检索到了正确的 chunks，LLM 仍说"没有相关信息"。需要 debug 确认是：
1. `ScoredChunk.content` 为空
2. `_aquery_rrf` 中 `chunks[:15]` 截断了正确结果
3. LLM prompt 模板问题（如来源标签混乱）

**选择**：在 `_aquery_rrf` 中添加 debug 日志打印 top-3 检索结果的内容摘要，验证 context 传递链路。

## Risks / Trade-offs

- [Risk] naive 模式返回的 context 格式可能与 LightRAG 其他模式不同 → Mitigation: 需要验证 `only_need_context=True` + `mode="naive"` 的返回格式
- [Risk] Graph 通道 async 化后，如果 LightRAG 版本 < 1.3 可能不兼容 → Mitigation: 本项目已使用 lightrag-hku>=1.3
- [Trade-off] 三通道全开在小语料库下 RRF 退化为简单投票，与单一 naive 查询无异 → 接受，大语料库下三通道互补优势才能体现
