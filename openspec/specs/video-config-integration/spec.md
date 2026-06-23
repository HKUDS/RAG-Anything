# Video Config Integration

## Purpose

为视频处理提供配置管理、处理器注册和依赖检测能力，确保视频功能可选择性启用且优雅降级。

## Requirements

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

### Requirement: 处理器类型路由

系统 SHALL 在 `get_processor_for_type()` 中支持 `"video"` 类型到 `VideoModalProcessor` 的路由。

#### Scenario: 视频类型路由
- **WHEN** `content_type == "video"` 且视频处理器已注册
- **THEN** `get_processor_for_type()` 返回 `VideoModalProcessor` 实例
- **THEN** 视频内容按照标准处理器流程执行

#### Scenario: 视频类型无可用处理器
- **WHEN** `content_type == "video"` 但视频处理器未注册（功能未启用）
- **THEN** `get_processor_for_type()` 回退到 `GenericModalProcessor`
- **THEN** 视频内容作为通用模态处理

### Requirement: 可选依赖优雅降级

系统 SHALL 在缺少视频处理依赖时给出清晰的错误提示，不阻止系统启动。

#### Scenario: 启用视频处理但缺少 opencv
- **WHEN** `enable_video_processing=True` 但 `cv2` 模块不可导入
- **THEN** 系统在初始化时记录 `ERROR` 日志
- **THEN** 日志提示 `pip install opencv-python-headless`
- **THEN** `VideoModalProcessor` 未被注册
- **THEN** 系统继续启动，其他功能正常

#### Scenario: 启用视频处理但缺少 whisper
- **WHEN** `enable_video_processing=True` 且 `video_audio_transcribe=True` 但 `whisper` 不可导入
- **THEN** 系统记录 `WARNING` 日志
- **THEN** 日志提示 `pip install openai-whisper`
- **THEN** 视频处理继续但跳过音频转录

#### Scenario: 所有依赖满足
- **WHEN** `enable_video_processing=True` 且所有可选依赖均已安装
- **THEN** 系统正常初始化 `VideoModalProcessor`
- **THEN** 视频处理完全可用

### Requirement: 视频文件扩展名注册

系统 SHALL 在 `supported_file_extensions` 中注册视频文件扩展名。

#### Scenario: 批量处理包含视频文件
- **WHEN** `supported_file_extensions` 包含 `.mp4,.avi,.mov,.mkv,.webm`
- **THEN** 批量处理模式识别并处理这些视频文件
- **THEN** 视频文件路由到视频处理流程

#### Scenario: 视频扩展名被排除
- **WHEN** 用户通过 `SUPPORTED_FILE_EXTENSIONS` 排除了视频扩展名
- **THEN** 即使 `enable_video_processing=True`，视频文件也被跳过
- **THEN** 记录 `INFO` 日志说明视频被扩展名过滤跳过
