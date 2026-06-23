# Video Config Integration (Delta)

## ADDED Requirements

### Requirement: Whisper模型大小配置项

系统 SHALL 在 `RAGAnythingConfig` 中提供 `whisper_model_size` 配置项，支持通过 `WHISPER_MODEL_SIZE` 环境变量设置，默认值为 `small`。

#### Scenario: 默认值
- **WHEN** 未设置 `WHISPER_MODEL_SIZE` 环境变量
- **THEN** `RAGAnythingConfig.whisper_model_size` 为 `small`

#### Scenario: 通过环境变量设置
- **WHEN** 设置 `WHISPER_MODEL_SIZE=medium`
- **THEN** `RAGAnythingConfig.whisper_model_size` 为 `medium`

#### Scenario: 无效值回退
- **WHEN** 设置 `WHISPER_MODEL_SIZE=xlarge`
- **THEN** `__post_init__` 发出 `UserWarning`
- **THEN** `whisper_model_size` 回退为 `small`

### Requirement: VideoModalProcessor接收Config对象

系统 SHALL 将 `RAGAnythingConfig` 的视频相关配置字段传入 `VideoModalProcessor` 构造函数，使处理器能访问运行时配置值而不直接读取环境变量。

#### Scenario: Config对象正常传入
- **WHEN** `RAGAnything._initialize_processors()` 初始化视频处理器
- **THEN** `VideoModalProcessor.__init__` 接收 `config` 参数（`RAGAnythingConfig` 实例）
- **THEN** 处理器提取 `max_duration`、`max_transcript_tokens`、`whisper_model_size` 等字段存储为实例属性

#### Scenario: 缺少config参数时优雅降级
- **WHEN** `VideoModalProcessor` 被构造但未传入 `config` 参数
- **THEN** 处理器使用硬编码安全默认值（`max_duration=3600`, `max_transcript_tokens=4000`）
- **THEN** 记录 `WARNING` 日志提示配置未传入

## MODIFIED Requirements

### Requirement: 视频处理配置项

系统 SHALL 在 `RAGAnythingConfig` 中提供视频处理相关的配置项，支持通过环境变量设置。

#### Scenario: 默认禁用视频处理
- **WHEN** 未设置任何视频处理环境变量
- **THEN** `enable_video_processing` 默认为 `False`
- **THEN** 系统不初始化 `VideoModalProcessor`
- **THEN** `.mp4` 等视频文件被跳过或按文本类型处理

#### Scenario: 通过环境变量启用
- **WHEN** 设置 `ENABLE_VIDEO_PROCESSING=true`
- **THEN** `RAGAnythingConfig.enable_video_processing` 为 `True`
- **THEN** 初始化时注册 `VideoModalProcessor` 并传入 config 对象
- **THEN** `get_processor_for_type("video")` 返回视频处理器

#### Scenario: 自定义视频处理参数
- **WHEN** 设置 `VIDEO_SAMPLE_RATE=2`、`VIDEO_MAX_DURATION=1800`、`VIDEO_MAX_FRAMES=30`、`WHISPER_MODEL_SIZE=base`
- **THEN** 配置对象反映所有自定义值
- **THEN** 视频处理使用自定义参数执行
