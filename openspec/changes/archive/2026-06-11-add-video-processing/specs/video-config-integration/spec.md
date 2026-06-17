# Video Config Integration

## Purpose

为视频处理提供配置管理、处理器注册和依赖检测能力，确保视频功能可选择性启用且优雅降级。

## ADDED Requirements

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
- **THEN** 初始化时注册 `VideoModalProcessor`
- **THEN** `get_processor_for_type("video")` 返回视频处理器

#### Scenario: 自定义视频处理参数
- **WHEN** 设置 `VIDEO_SAMPLE_RATE=2`、`VIDEO_MAX_DURATION=1800`、`VIDEO_MAX_FRAMES=30`、`VIDEO_AUDIO_TRANSCRIBE=false`
- **THEN** 配置对象反映所有自定义值
- **THEN** 视频处理使用自定义参数执行

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
