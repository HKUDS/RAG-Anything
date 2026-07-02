## Why

单个 40K 字符的 Word 文档完整处理需要 ~45 分钟（文本分块 12 分钟 + 实体抽取/向量化 33 分钟），其中实体抽取阶段每个 chunk 串行调用 LLM + 大量 embedding API 重试是核心瓶颈。当前架构在 subprocess 内所有 LLM 和 embedding 调用都是串行的，缺乏批量调用、并发请求和智能缓存机制。需要在确保处理质量的前提下，将总耗时降低 40-60%。

## What Changes

- **实体抽取并行化**：将 LightRAG 实体抽取从单 chunk 串行改为可控并发（默认 3 并发），减少 LLM 调用的总等待时间
- **Embedding 批量调用**：将 embedding API 单条请求改为批量请求（batch size 可配置），减少 API 往返次数和 rate limit 触发频率
- **LLM 缓存增强**：扩大实体抽取结果的缓存命中率，同一文档内相似 chunk 共享实体抽取结果
- **Prompt 精简**：优化实体抽取 prompt（中文），减少不必要 token 消耗，降低单次 LLM 调用延迟
- **处理进度细化**：将 worker 进度信息从粗粒度（仅文本分块）细化为分阶段上报，前端可看到实体抽取/向量化等各阶段进度
- **配置化并发控制**：新增环境变量 `ENTITY_EXTRACT_CONCURRENCY`、`EMBEDDING_BATCH_SIZE`，允许用户根据 API 配额调整

## Capabilities

### New Capabilities
- `entity-extract-concurrency`: 实体抽取并发控制 — 允许 LightRAG 的实体抽取步骤以可配置的并发度运行，减少串行等待
- `embedding-batch-api`: Embedding 批量调用 — 将多个单条 embedding 请求合并为一次批量 API 调用
- `processing-progress-granularity`: 处理进度细化 — worker 子进程分阶段上报进度（解析 → 分块 → 实体抽取 → 向量化 → 图谱构建）

### Modified Capabilities
- 无 — 本次改动不改变现有功能的 spec 级行为，仅优化内部处理速度

## Impact

- **process_worker.py**: 引入 asyncio.Semaphore 控制实体抽取并发，embedding 调用改为批量模式
- **raganything/processor.py**: `_store_chunks_to_lightrag_storage_type_aware` 增大并发上限（10→20），细化进度上报
- **raganything/raganything.py**: LightRAG 初始化参数新增 `embedding_batch_num`、`embedding_func_max_async` 配置
- **raganything/prompts_zh.py**: 实体抽取 prompt 精简（减少 token 消耗）
- **server.py**: 新增环境变量透传，前端进度展示适配
- **.env / 配置**: 新增 `ENTITY_EXTRACT_CONCURRENCY`、`EMBEDDING_BATCH_SIZE` 环境变量
