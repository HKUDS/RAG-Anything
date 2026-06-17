## Why

视频处理 MVP 已实现基础管线（抽帧→转录→VLM 分析→实体创建），但存在三个效率瓶颈：(1) 多帧 VLM 分析串行执行，耗时与帧数线性增长；(2) 相同视频重复处理时无缓存，浪费 API 调用；(3) 视频并发未与图片处理分离，可能因视频任务耗尽资源导致其他模态饥饿。此变更针对性地消除这三个瓶颈，使视频处理成本可控、性能可预测。

## What Changes

- 帧分析并行化：将 `generate_description_only()` 中逐帧串行调用改为 `asyncio.gather` 并发调用，通过信号量控制最大并发帧数
- 帧描述缓存：以 `video_path + mtime + sample_rate` 为键缓存帧级描述结果，避免重复 VLM 调用
- 视频独立并发控制：抽帧/转录/VLM 三级并发分离，视频帧分析使用独立信号量，与图片处理互不影响
- 配置项扩展：新增 `VIDEO_FRAME_CONCURRENT`（帧分析并发数）、`ENABLE_FRAME_CACHE`（帧缓存开关）
- 视频处理器增加 `_check_video_processed()` 跳过已完成处理的相同视频文件

## Capabilities

### New Capabilities

- `video-parallel-frames`: 视频多帧 VLM 分析并行化，通过独立信号量控制并发，与图片处理信号量隔离
- `video-frame-cache`: 基于文件路径+修改时间的帧描述缓存，避免重复视频处理时重复调用 VLM

### Modified Capabilities

- `video-knowledge-graph`: 帧分析从串行改为并发，`generate_description_only()` 行为变更（新增并发控制和缓存查询）

## Impact

- **修改文件**：`raganything/video_processor.py` — `generate_description_only()` 重构为并发执行 + 缓存集成
- **修改文件**：`raganything/raganything.py` — `_initialize_processors()` 传入独立信号量和缓存配置
- **修改文件**：`raganything/config.py` — 新增 `video_frame_concurrent`、`enable_frame_cache` 配置项
- **修改文件**：`env.example` — 新增环境变量说明
- **无破坏性变更**：默认行为不变（帧并发数默认 3，缓存默认开启）
