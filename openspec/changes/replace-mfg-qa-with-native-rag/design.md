## Context

制造智能体 QA 的当前架构：

```
/api/manufacturing/qa
  → _get_mfg_agent_components()
    → QAEngine(rag_client=rag, llm_client=ServerLLMAdapter(), image_paths=...)
  → qa.answer()
    → _retrieve()  → rag.aquery(mode="rrf")  → HybridSearchEngine
    → _generate()  → ServerLLMAdapter.generate()  → openai_complete_if_cache

/api/manufacturing/qa/stream
  → qa._retrieve()  → rag.aquery(mode="rrf")  → HybridSearchEngine
  → openai_complete_if_cache(stream=True)
```

其中 `HybridSearchEngine` 是自定义 RRF 三路融合（BM25+Vector+Graph），与 LightRAG 原生查询走不同路径。已发现 4 个 bug：BM25 `<=0` 过滤、NetworkXStorage async、Vector `local`→0 chunks、Graph `get_by_id` content 为空。

而普通智能体 `/api/query` 直接用 `LightRAG.aquery(mode="hybrid")`，经过充分测试，没有这些问题。同一 KB 同一问题，两条路径的召回率差距明显。

## Goals / Non-Goals

**Goals:**
- 制造智能体 QA 与普通智能体走同一检索代码路径（`LightRAG.aquery`）
- 删除自定义 RRF 管线的 QA 使用，消除 4 个 bug 的维护负担
- 保持流式回答体验

**Non-Goals:**
- 不删除 `HybridSearchEngine` 代码本身（保留以备将来需要独立 RRF 分析的场景）
- 不删除 `QAEngine` 模块（FaultDiagnosis、CodeParser 等其他制造功能仍依赖部分代码）
- 不修改前端 UI

## Decisions

### Decision 1: QA 端点直接调 LightRAG.aquery

**选择**：`/api/manufacturing/qa` → `instance.aquery(query, mode="hybrid", system_prompt="你是智能制造教学专家...")`

**理由**：LightRAG 原生 hybrid 模式是经过充分测试的单一代码路径，已经证明在制造类问题上召回正确。不再需要自定义 RRF。

### Decision 2: 图片匹配逻辑保留但简化

**选择**：从前端移除 `related_images` 的展示（普通智能体查询不返回图片），或改为从 `extract_image_paths(ctx)` 提取。

**理由**：普通智能体的 hybrid 查询返回纯文本 context，图片匹配原本就是 QAEngine 的附加功能。简化处理，后续有需求再加。

### Decision 3: 流式端点直接调 LightRAG.aquery(stream=True)

**选择**：复用 `/api/query_stream` 的模式——先 `only_need_context` 获取检索上下文，再 `stream=True` 流式生成。

**理由**：与普通查询流式完全一致，减少代码重复。

## Risks / Trade-offs

- [Trade-off] 失去 RRF 三路融合的"独立性"——普通 hybrid 查询不区分 BM25/Vector/Graph 通道 → 接受，当前阶段检索质量 > 架构独立性
- [Risk] 流式体验与普通智能体一致，没有制造领域的特殊 prompt → Mitigation: 在 system_prompt 中保持"你是智能制造教学专家"
