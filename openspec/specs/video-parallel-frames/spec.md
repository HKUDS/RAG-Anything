# Video Parallel Frames

## Purpose

将视频帧的 VLM 分析从串行改为并发执行，通过独立信号量控制帧级并发数，与图片处理信号量隔离，显著缩短视频处理总耗时。

## ADDED Requirements

### Requirement: 帧分析并行化

系统 SHALL 使用 `asyncio.gather` 并发执行关键帧的 VLM 分析，通过独立信号量 `_frame_semaphore` 控制最大并发帧数。

#### Scenario: 正常并发帧分析
- **WHEN** 视频提取了 5 个关键帧且 `video_frame_concurrent=3`
- **THEN** 系统同时最多发起 3 个 VLM 请求
- **THEN** 5 帧在 2 轮内完成（3 + 2）
- **THEN** 所有帧描述按原始帧索引排序后返回

#### Scenario: 部分帧失败不影响整体
- **WHEN** 并发分析时某一帧 VLM 调用失败（超时或 API 错误）
- **THEN** 该帧记录为错误描述 `"[Frame X at Ys: analysis failed]"`
- **THEN** 其余帧继续分析，不中断整体流程
- **THEN** 综合描述中标注"部分帧分析失败"

#### Scenario: 串行回退
- **WHEN** `video_frame_concurrent=1`
- **THEN** 系统按帧顺序串行分析
- **THEN** 行为与优化前一致

### Requirement: 视频独立并发信号量

系统 SHALL 为视频帧分析使用独立的 `asyncio.Semaphore`，默认并发数由 `VIDEO_FRAME_CONCURRENT` 环境变量控制（默认 3），与图片处理的 `MULTIMODAL_MAX_CONCURRENT` 信号量互不影响。

#### Scenario: 视频与图片并发互不干扰
- **WHEN** 批处理同时包含 2 个视频和 10 张图片
- **THEN** 视频帧分析使用视频独立信号量（如 3 并发）
- **THEN** 图片处理使用图片独立信号量（如 8 并发）
- **THEN** 视频帧任务不会占用图片处理的并发配额

#### Scenario: 视频并发数配置
- **WHEN** 设置 `VIDEO_FRAME_CONCURRENT=5`
- **THEN** 视频帧分析最多同时发起 5 个 VLM 请求
- **THEN** `VideoModalProcessor._frame_semaphore` 的值为 5
