## Context

代码重构后，智能体查询流（`agent_mode=none`、`agent_mode=react`）中的文本检索与图片提取形成了两条独立路径：

- **文本路径**：`aquery(only_need_context=True)` → RRF 混合检索 → 组合 `[来源 doc] chunk_content` → 返回给 LLM
- **图片路径**：`extract_image_paths(ctx)` 提取上下文中已有图片 + bigram 全库扫描 `kv_store_text_chunks.json` 回退

当 RRF 检索返回弱上下文（无 `[来源 ` 标记、仅含实体关系数据）时，`_has_chunks` 检测失败，`_DEGRADED_HINT` 被注入 prompt。但 bigram 图片扫描独立运行，仍能从未被检索到的 chunk 中找到图片路径。形成"图片有、文本无"的割裂。

**核心约束**：
- `kv_store_text_chunks.json` 包含所有已索引 chunk 的 content（文本 + 图片路径）
- bigram 扫描已有成熟的去重和评分逻辑
- 图片 chunk 的 content 包含 VLM 生成的 `视觉分析` 描述文本（有价值的信息）
- 不能引入新的外部依赖

## Goals / Non-Goals

**Goals:**
1. bigram 图片回退扫描找到匹配 chunk 时，同步回填文本内容到检索上下文
2. `_has_chunks` 检测改为评估"enriched context"（原始 + 回填后），避免误触发 `_DEGRADED_HINT`
3. 回填文本使用 `[来源 doc_name]` 格式标注，确保 citation 一致性
4. 变更最小化：仅修改 `agent.py` 中的两处 bigram 扫描位置

**Non-Goals:**
- 不修改 RRF 检索流水线本身（那是另一个独立的性能/质量问题）
- 不修改 LightRAG 内部的 fail_response 逻辑
- 不修改前端展示逻辑
- 不新增数据库表或配置项

## Decisions

### Decision 1: 在 bigram 扫描循环中同步收集文本内容

**方案**：在已有的 bigram 扫描循环（`agent.py` line ~662-670）中，除了收集图片路径及其 bigram 分数，也收集对应 chunk 的文本 content。

**理由**：
- 扫描已经遍历所有 chunk，收集文本是零额外 I/O
- 复用已有的 bigram 评分作为文本排序依据
- 代码变更局限在单一函数块内

**备选方案**：
- 方案 B：单独再跑一次文本检索。❌ 不必要的重复遍历，性能差。
- 方案 C：修改 `_aquery_rrf` 使其总是返回足够文本。❌ 改动范围大，风险高。

### Decision 2: 回填文本格式统一为 `[来源 doc_name]`

**方案**：回填文本块使用与 RRF 主路径相同的格式：
```
[来源 {document_name} (回填片段{n})]
{chunk_content}
```

**理由**：
- LLM 的 citation 训练基于 `[来源 ` 格式
- `_has_chunks` 检测依赖 `"[来源 " in ctx`
- `_build_citation_block` 也扫描此格式
- 标记 `(回填片段{n})` 可区分回填来源，方便后续调试追踪

### Decision 3: 调整 agent_mode=none 路径的执行顺序

**方案**：将 `_is_empty_context(ctx)` 的调用时机移到 bigram 回填之后，或在 bigram 回填后重新评估。

具体流程：
```
ctx = await aquery(...)
agent_images = extract_image_paths(ctx)
if not agent_images:
    backfill_result = bigram_scan_and_backfill(query, kb_dir)
    if backfill_result.text:
        ctx = ctx + "\n\n" + backfill_result.text  # 富化上下文
    agent_images = backfill_result.images
is_fallback = _is_empty_context(ctx)  # ← 使用富化后的上下文
```

**理由**：
- 避免在 bigram 回填前就判定 fallback 而跳过图片扫描
- fallback 判定应该基于"最终可用的上下文"，而非原始检索结果

**备选方案**：
- 方案 B：在 `_is_empty_context()` 内部做 bigram 回填。❌ 违反单一职责，函数签名变复杂。
- 方案 C：只在 agent_mode=react 路径修复。❌ 不完整，三个 agent_mode 路径都有此问题。

### Decision 4: agent_mode=react 路径同样修复

**方案**：在 react 路径的 trace 处理阶段（line ~480-520），也将 bigram 扫描收集的文本回填到 `all_retrieved_text` 中。

**理由**：
- react 路径使用 `all_retrieved_text` 做图片提取
- `all_retrieved_text` 累积了所有 observation（即检索上下文）
- 回填文本加入 `all_retrieved_text` 同时解决图片和文本富化问题

## Risks / Trade-offs

| Risk | Mitigation |
|------|------------|
| 回填文本可能引入与查询不相关的内容，干扰 LLM | bigram 评分已有相关性过滤（score > 0），且只取 top-N（N=图片数）chunk |
| 回填可能导致上下文过长 | 限制回填文本总量不超过 max_total_tokens 的 30%（约 4800 字符） |
| `kv_store_text_chunks.json` 文件可能很大（数百 MB），全量加载性能开销 | 文件已在 bigram 扫描中被全量加载，回填不增加额外加载 |
| 回填后 `_has_chunks` 转 True 但内容实际不相关 | 这是改善而非完美方案；伪阳性的 `_has_chunks` 优先于伪阴性的 `_DEGRADED_HINT`，因为 LLM 比 `_DEGRADED_HINT` 更能判断内容相关性 |

## Migration Plan

1. **部署**：代码变更仅限 `raganything/routers/agent.py`，无需数据库迁移或配置变更
2. **回滚**：如果 bigram 回填引入噪声，可通过环境变量 `BACKFILL_ENABLED=false` 禁用回填（保留图片扫描）
3. **验证**：使用已有知识库发送查询，观察 `[IMG-FALLBACK]` 日志中是否出现 `+文本回填` 标记

## Open Questions

1. **回填文本的 token 限制**：是否需要根据 LLM 模型动态调整？目前硬编码 4800 字符。
2. **是否需要在 agent_mode="cot" 路径也处理**：CoT 路径在检索前就做了 `_is_empty_context(cot_context)` 检查，是否需要同样调整？（当前 PR 先处理 none 和 react 两个常用路径）
