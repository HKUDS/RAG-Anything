## Context

当前文档处理流水线在 `process_worker.py` 子进程中串行执行：文本分块 → LightRAG `ainsert`（实体抽取 + 关系提取 + 向量化）→ 后台多模态任务。其中实体抽取对每个 chunk 依次调用 LLM，embedding 对每个 chunk 依次调用 API。对于 109 chunks 的文档，这导致 ~33 分钟的等待时间。

### 关键约束
- LLM API (qwen-plus) 和 Embedding API (text-embedding-v3) 共用同一 API key，有并发限制
- 处理在独立子进程中运行，不阻塞主服务
- `MAX_CONCURRENT_FILES=1`，每次只处理一个文档
- LightRAG 的 `ainsert` 内部流程不可直接控制，只能通过 `lightrag_kwargs` 参数调优

## Goals / Non-Goals

**Goals:**
- 将 40K 字符文档的总处理时间从 ~45 分钟降低到 **20-25 分钟**（40-50% 提升）
- 在 embedding chunk 存储阶段使用批量 API 减少往返次数
- 细化 worker 进度上报，让用户了解处理处于哪个阶段
- 所有并发参数可通过环境变量配置，适应不同 API 配额

**Non-Goals:**
- 不做 LightRAG 内核修改（`ainsert` 内部串行实体抽取不改动）
- 不做多文档并行处理（`MAX_CONCURRENT_FILES` 机制已有）
- 不改变文档处理质量或结果
- 不做 LLM 模型切换或 API 供应商更换

## Decisions

### Decision 1: 从 embedding 批量化入手（非侵入式）

**选择**：在 `_store_chunks_to_lightrag_storage_type_aware` 中将 embedding 请求从单条调用改为批量调用。

- embedding API 支持一次传 `[text1, text2, ..., textN]`，返回 `N × 1024` 维向量
- 将 `Semaphore(10)` 改为批量收集 + 一次调用，减少 ~90% 的 API 往返
- 当前每个 chunk 一次 embedding 调用 → 109 chunks = 109 次 API 调用，改为 batch=20 后只需要 6 次
- **备选方案（放弃）**：直接改 LightRAG 的 embedding 函数签名 — 风险太高，可能破坏兼容性

### Decision 2: Entity 抽取不直接并行化（尊重 LightRAG 内部流程）

**选择**：不在 `process_worker.py` 层面强行对 LightRAG 实体抽取做并行，而是通过 LightRAG 的参数优化加速。

- LightRAG 的 `ainsert` → `extract_entities` 流程是内部串行的，强行并行会破坏关系图一致性
- 替代方案：通过 `addon_params` 限制实体类型（减少 LLM 生成量）、增大 `embedding_func_max_async` 参数
- `embedding_func_max_async`: LightRAG 的 embedding 函数最大并发数，默认可能很低
- **备选方案（保留评估）**：在 `processor.py` 的 `_extract_entities_from_chunks` 层面包装并发 — 若本次效果不佳可后续再试

### Decision 3: 进度分为 5 个阶段上报

**选择**：在 `process_worker.py` 的关键步骤之间输出结构化进度行（`[PROGRESS] phase=chunking 20/109`），server.py 解析并转发。

- 不需要改 API schema，复用现有 `emit_progress` 机制
- Worker 输出带前缀的行便于 server 端正则解析
- 前端在现有进度条基础上增加阶段文字标签

### Decision 4: 新增环境变量

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `EMBEDDING_BATCH_SIZE` | 20 | 每次批量 embedding 的文本数 |
| `ENTITY_EXTRACT_CONCURRENCY` | 3 | LightRAG entity 抽取并发数（传入 `embedding_func_max_async`） |

## Risks / Trade-offs

- **[风险] 批量 embedding 单次失败影响多个 chunk** → 降级策略：批量失败时逐个重试
- **[风险] 并发增加可能触发 API rate limit 更频繁** → 复用现有的 `openai._base_client` 重试机制；加入自适应退避
- **[风险] LightRAG `embedding_func_max_async` 参数可能不被实际使用** → 需验证 LightRAG 版本是否支持该参数；如不支持则仅靠批量 embedding
- **[权衡] 批量 embedding 增加单次调用延迟但减少总时间** → batch_size=20 时单次调用约 2-3s（vs 0.4s 单条），但总 API 往返从 N 降到 N/20
