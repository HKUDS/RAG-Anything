# Design: 性能优化

## Context

实测发现：4MB Word 文档（75个多模态元素）上传耗时 21 分钟，其中多模态处理占 10+ 分钟。主要原因：LLM 限流后降级为逐个串行处理。前端制造看板 5 秒全量轮询造成约 1200 次/小时额外 API 请求。

## Goals / Non-Goals

**Goals:**
- 文档上传时间从 21 分钟降至 5 分钟内
- 前端看板 API 请求减少 60%
- 重复查询零 API 消耗

**Non-Goals:**
- 不修改 RAG-Anything 核心架构
- 不引入 Redis/外部缓存依赖（使用进程内存）
- 不改变现有 API 契约

## Decisions

### Decision 1: 自适应并发用滑动窗口错误率

**选择**: 维护最近 10 次 API 调用结果，错误率 >30% 减半并发，连续 20 次无错恢复。

**理由**: 简单有效，无需外部配置。比固定并发更适合不同模型（qwen-max 支持 8，qwen-plus 只能 4）。

### Decision 2: 查询缓存用进程内存 + 文本哈希

**选择**: `{query_hash: (result, timestamp)}` dict，TTL 60 秒，LRU 最多 500 条。

**理由**: 同一用户 30 秒内重复提问同一问题很常见。不引入 Redis 避免运维复杂度。

### Decision 3: 前端用 Page Visibility API + 条件刷新

**选择**: `document.visibilityState` 检测页面可见性，不可见时停止轮询。根据最后查询时间动态调整间隔。

**理由**: 零依赖，浏览器原生 API，立即生效。

## Risks

| 风险 | 缓解 |
|------|------|
| 缓存导致查询结果过时 | TTL 60s + `?refresh=true` 强制刷新 |
| 自适应并发过于保守 | 恢复阈值低（连续 20 次无错），快速回升 |
