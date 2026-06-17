## Context

当前 `VideoModalProcessor.generate_description_only()` 的帧分析流程是串行的：对每个关键帧依次调用 VLM。对于 5 帧的视频，串行耗时 = 5 × (单帧 VLM 延迟 + 网络 RTT)。改为并发后理论耗时 ≈ max(单帧延迟) + 网络开销。

此外，当前的 BatchMixin 使用统一的 `MULTIMODAL_MAX_CONCURRENT` 信号量控制所有模态（图片、表格、公式、视频）的并发处理。视频帧提取和 VLM 调用远比图片处理昂贵，可能在批处理场景中导致其他模态饥饿。

现有"已处理"检测基于 chunk 级别的 `parse_cache`，而非逐帧描述缓存，无法避免重复视频的重复帧分析。

## Goals / Non-Goals

**Goals:**
- 将帧级 VLM 调用从串行改为并发，显著缩短视频分析总耗时
- 用独立信号量隔离视频帧分析并发，防止视频任务占用全部并发配额
- 以 `video_path + mtime + sample_rate` 为键缓存帧描述，避免重复 VLM 调用
- 跳过已完成处理的相同视频（检测实体是否已存在于知识图谱中）

**Non-Goals:**
- 音频转录的并行化（Whisper 已内部并行，且只调用一次）
- 分布式缓存（仅本地内存缓存，服务重启后失效）
- 帧描述的增量更新（同一视频修改后重新处理全部帧）
- 视频转码或格式优化

## Decisions

### Decision 1: asyncio.gather + Semaphore 控制帧并发

**选择**：在 `generate_description_only()` 中使用 `asyncio.Semaphore(video_frame_concurrent)` + `asyncio.gather` 并发调用帧 VLM 分析。

**默认并发数**：3（在 VLM API 速率限制和总耗时之间平衡）

**理由**：
- `asyncio.gather` 是标准库方案，零额外依赖
- 独立信号量确保视频帧并发不受图片处理信号量影响
- 所有帧共享同一个视频上下文和转录文本，帧间无依赖，天然可并行

**备选方案**：线程池并发
- 缺点：asyncio 生态中线程池增加复杂度，且 VLM 调用通常也是 async 的

### Decision 2: 内存字典 + mtime 缓存帧描述

**选择**：在 `VideoModalProcessor` 实例上维护一个 `_frame_cache: Dict[str, List[str]]` 字典，key 为 `sha256(video_path + str(mtime) + str(sample_rate))[:16]`，value 为帧描述列表。

**理由**：
- 服务生命周期内，同一视频重复处理时直接复用帧描述
- mtime 作为版本标识，文件修改后自动失效
- 内存缓存零配置，无需外部依赖

**备选方案**：文件系统缓存（pickle/json）
- 优点：跨服务重启持久化
- 缺点：增加 I/O 开销，需要清理策略，当前阶段过度设计

### Decision 3: 帧分析并发数默认 3

**选择**：`video_frame_concurrent=3`

**理由**：
- 大多数 VLM API 的 rate limit 允许 3-5 并发
- 5 个关键帧在并发 3 时 2 轮完成，耗时约 2×单次延迟
- 串行 5 帧 = 5×延迟，并发 3 = ~2×延迟，提速约 2.5×

## Risks / Trade-offs

- **[速率限制] VLM API 并发超限**：并发 3 帧可能在短时间内触发 rate limit。→ 默认并发 3 是保守值；可配置为 1 回退到串行。
- **[缓存一致性] mtime 变化检测不完美**：如果文件被 `touch` 但内容未变，缓存失效浪费一次 VLM 调用（但结果正确）。→ 可接受，mtime 已覆盖绝大多数场景。
- **[内存泄漏] 帧缓存无限增长**：长运行服务处理大量视频时缓存可能过大。→ 非目标（当前阶段不处理），后续可加 LRU 淘汰。
- **[GPU 竞争] 并发帧分析 + 音频转录**：两者同时运行可能 CPU 竞争（Whisper + VLM API 调用）。→ 音频转录本身不耗 GPU（VLM 是 API 调用），实际影响很小。

## Open Questions

- 帧缓存是否需要 TTL 过期机制？（当前阶段：不需要，服务重启自然清空）
- 是否需要持久化缓存到 LightRAG KV storage？（当前阶段：内存足够）
