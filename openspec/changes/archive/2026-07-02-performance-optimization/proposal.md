# Proposal: 性能优化 — 上传加速 + 查询提速 + 降低API成本

## Why

21分钟的文档上传暴露了三个性能瓶颈：① LLM 并发策略粗糙（qwen-plus 8并发触发限流后逐个降级，75个项目跑了10分钟）；② 多模态 fallback 无批次概念（一次失败就全部转串行）；③ 前端 5 秒全量轮询造成不必要的 API 压力。此外大量 LLM 调用缺少结果缓存和去重机制。本次优化目标：上传时间缩至 5 分钟内，查询延迟降 30%，无效 API 调用减少 50%。

## What Changes

- **新增** LLM 自适应并发：根据最近 API 错误率动态调整并发数（限流→减半，正常→恢复）
- **新增** 多模态小组重试：批量处理失败时按 4 个一组重试，而非逐个串行
- **新增** 查询结果缓存：相同查询 60 秒内返回缓存结果，跳过 RAG + LLM
- **优化** Embedding 重试去重：同一文档的向量化失败后不重复请求已成功的 chunk
- **优化** 前端智能轮询：看板从 5 秒全量刷新改为 15 秒增量 + 活跃时 5 秒
- **优化** LLM 调用合并：实体提取阶段相同/相似 chunk 合并处理

## Capabilities

### New Capabilities

- `adaptive-concurrency`: LLM 自适应并发。监控最近 10 次 API 调用的错误率，超过 30% 自动减半并发，连续 20 次无错恢复原值。应用于实体提取、多模态描述、查询生成。
- `query-cache`: 查询结果缓存。基于查询文本哈希的 TTL 缓存（60s），相同查询直接返回缓存结果。支持通过 `?refresh=true` 参数跳过缓存。
- `frontend-smart-polling`: 前端智能轮询。看板页面从固定 5 秒改为：页面不可见时停止轮询，可见时 15 秒，有活跃查询时 5 秒。降低 60% 的 API 负载。

### Modified Capabilities

- `data-import-tools`: 多模态批量处理失败时的降级策略从逐个串行改为小组（4个）并行重试。

## Impact

- **修改文件**: `raganything/modalprocessors.py`（多模态小组重试）、`raganything/query.py`（查询缓存 + 自适应并发）、`frontend/src/pages/ManufacturingDashboardPage.jsx`（智能轮询）
- **新增文件**: `raganything/utils/adaptive_concurrency.py`（自适应并发工具类）、`raganything/utils/query_cache.py`（查询缓存）
- **配置**: `.env` 新增 `ADAPTIVE_CONCURRENCY_ENABLED=true`、`QUERY_CACHE_TTL=60`
- **API 消耗预期**: 日均 API 调用量降低 30-50%
