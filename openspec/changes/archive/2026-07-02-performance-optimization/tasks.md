# Tasks: 性能优化

## 1. LLM 自适应并发

- [x] 1.1 创建 `raganything/utils/adaptive_concurrency.py` — 滑动窗口错误率检测 + 并发升降级
- [x] 1.2 在 `server.py` 的 LLM worker 初始化时接入自适应并发
- [x] 1.3 添加 `.env` 配置项：`ADAPTIVE_CONCURRENCY_ENABLED`、`ADAPTIVE_CONCURRENCY_ERROR_RATE`

## 2. 查询缓存

- [x] 2.1 创建 `raganything/utils/query_cache.py` — TTL + LRU 查询缓存
- [x] 2.2 在 `server.py` 的 `/api/query` 和 `/api/query/stream` 端点接入缓存
- [x] 2.3 添加 `X-Cache: HIT/MISS` 响应头，支持 `?refresh=true`

## 3. 前端智能轮询

- [x] 3.1 改造 `ManufacturingDashboardPage.jsx` — Page Visibility API + 自适应间隔
- [x] 3.2 其他前端页面（Knowledge、Agent）移除不必要的自动刷新

## 4. 多模态小组重试

- [x] 4.1 改造 `modalprocessors.py`：降级时按 4 个一组重试，而非逐个串行

## 5. 验证

- [x] 5.1 上传同一文档对比优化前后耗时
- [x] 5.2 验证缓存命中率
- [x] 5.3 前端构建验证
