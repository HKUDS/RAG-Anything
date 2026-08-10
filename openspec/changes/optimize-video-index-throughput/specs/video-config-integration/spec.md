## ADDED Requirements

### Requirement: 视频片段并发配置项

系统 SHALL 在 `RAGAnythingConfig` 中提供 `video_segment_concurrent` 配置项，支持通过 `VIDEO_SEGMENT_CONCURRENT` 环境变量设置，默认值为 `2`，钳制范围为 `1` 到 `4`，并透传到 `VideoModalProcessor`。

#### Scenario: 默认值

- **WHEN** 未设置 `VIDEO_SEGMENT_CONCURRENT` 环境变量
- **THEN** `RAGAnythingConfig.video_segment_concurrent` 为 `2`

#### Scenario: 通过环境变量设置

- **WHEN** 设置 `VIDEO_SEGMENT_CONCURRENT=3`
- **THEN** `RAGAnythingConfig.video_segment_concurrent` 为 `3`
- **THEN** `RAGAnything` 初始化视频处理器时传入该值
- **THEN** `VideoModalProcessor` 的片段信号量上限为 `3`

#### Scenario: 越界钳制

- **WHEN** 设置 `VIDEO_SEGMENT_CONCURRENT=10`
- **THEN** `__post_init__` 发出 `UserWarning`
- **THEN** `video_segment_concurrent` 被钳制为 `4`

#### Scenario: 处理器缺省降级

- **WHEN** `VideoModalProcessor` 构造时未传入 `video_segment_concurrent`
- **THEN** 处理器使用默认值 `2`