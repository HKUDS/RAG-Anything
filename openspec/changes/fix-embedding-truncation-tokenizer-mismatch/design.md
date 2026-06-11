## Context

多模态处理的批量路径在 Stage 3（`_store_chunks_to_lightrag_storage_type_aware`）调用 LightRAG 的 `chunks_vdb.upsert()` 进行批量向量嵌入。千问 `text-embedding-v3` API 的输入上限为 8192 token。

LightRAG 使用 `o200k_base`（gpt-4o-mini 对应的 tiktoken 编码）作为内部 tokenizer，该编码对中文文本的 token 计数约为千问 API 实际 tokenizer 的 **50%**。这意味着 LightRAG 认为安全的内容，可能已被千问 API 拒绝。

**示例**：2000 字中文文本，LightRAG（o200k_base）计数 2000 token，千问 API 计数约 4000 token。反之，LightRAG 数 4000 token 的内容，千问已接近 8000 token。

**影响**：批量嵌入时任意一条 chunk 触发 8192 上限 → 整批 75 条全部失败 → 触发逐条回退（`_process_multimodal_content_individual`）→ 处理时间从 ~25 分钟变为 ~70 分钟。

## Goals / Non-Goals

**Goals:**
- 消除 tokenizer 不匹配导致的误判
- 批量路径一次成功，不再降级为逐条回退
- 单条 chunk 嵌入失败不影响其余 chunk

**Non-Goals:**
- 不修改 LightRAG 内部的 tokenizer 选择
- 不修改嵌入 API 调用方式（仍使用 LightRAG 的 `chunks_vdb`）

## Decisions

### Decision 1: 字符级截断替代 token 级截断

**选择**：使用 `len(content)` 字符数作为截断依据，上限 8000 字符。

**理由**：
- 中文最坏情况约 1 char/token → 8000 chars ≤ 8000 tokens < 8192
- 英文约 4 chars/token → 8000 chars ≈ 2000 tokens，远低于上限
- 不依赖任何 tokenizer 实现，消除了 o200k_base 与千问 API 的不匹配问题

**备选方案**：
- ❌ 改用 cl100k_base tokenizer：更接近千问但仍有差异，且需修改 LightRAG 配置
- ❌ 调低 token 阈值到 3000：tokenizer 更新后可能再次失效

### Decision 2: 逐条嵌入替代批量嵌入

**选择**：将 `chunks_vdb.upsert(chunks)` 改为逐个调用 `chunks_vdb.upsert({chunk_id: chunk_data})`。

**理由**：即使有截断，也应防御意外。逐条嵌入确保单条失败不拖垮整批。

**风险**：逐条嵌入增加 API 调用次数（N 次 vs 1 次），每次调用增加少量延迟。但 75 次调用增加的延迟（~2 秒）远低于逐条回退的代价（~50 分钟）。

## Risks / Trade-offs

- **[风险] 截断丢失信息**：VLM 生成的长描述被截断至 8000 字符 → **缓解**：8000 字符已覆盖绝大多数内容；尾部追加截断标识
- **[风险] 逐条嵌入性能**：75 次 API 调用增加延迟 → **可接受**：额外延迟 < 5 秒，批量的并行优势仍保留在描述生成阶段

## Open Questions

<!-- None. Implementation is complete and tested. -->
