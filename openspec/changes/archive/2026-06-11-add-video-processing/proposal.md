## Why

RAG-Anything 当前的多模态处理仅覆盖文档中的静态内容（图片、表格、公式），完全缺失视频处理能力。随着视频内容在企业知识库、教育培训、会议记录等场景中的占比持续增长，用户需要能够将视频文件（如 MP4 会议录像、产品演示、培训课程）纳入 RAG 知识库进行语义检索。此变更填补这一关键能力空白，使 RAG-Anything 从"文档多模态"升级为真正的"多媒体" RAG 系统。

## What Changes

- 新增 `VideoModalProcessor` 处理器，继承 `BaseModalProcessor`，实现视频内容的描述生成与知识图谱实体抽取
- 新增视频帧采样模块，支持关键帧提取（默认 1 fps）和场景变化检测
- 新增音频转录集成（Whisper），将视频语音转换为文本上下文
- 新增视频分析 Prompt 模板（`VIDEO_ANALYSIS_SYSTEM`、`video_prompt`、`video_chunk`），引导 VLM 同时分析视觉帧和转录文本
- 新增配置项：`enable_video_processing`、`video_sample_rate`、`video_max_duration`、`video_audio_transcribe` 等
- 扩展 `get_processor_for_type()` 支持 `"video"` 类型路由
- 扩展 `RAGAnythingConfig` 和 `RAGAnything._initialize_processors()` 以注册视频处理器
- 新增可选依赖处理：`opencv-python`（帧提取）、`openai-whisper`（音频转录）、`ffmpeg-python`（音视频解码）
- 扩展 `query.py` 支持视频内容的查询描述生成

## Capabilities

### New Capabilities

- `video-frame-extraction`: 从视频文件中按采样率提取关键帧，支持抽帧间隔配置和场景变化检测
- `video-audio-transcription`: 提取视频音频轨道并通过 Whisper 模型转录为文本，作为视觉分析的上下文补充
- `video-knowledge-graph`: 将视频内容（帧描述 + 音频转录 + 时序信息）作为知识图谱实体存储，支持语义检索
- `video-config-integration`: 视频处理相关的配置项与环境变量支持，可选依赖的优雅降级

### Modified Capabilities

<!-- 无需修改现有 spec -->

## Impact

- **新增文件**：`raganything/video_processor.py`（视频处理器模块）
- **修改文件**：
  - `raganything/modalprocessors.py` — 可能提取公共辅助方法供视频处理器复用
  - `raganything/raganything.py` — `_initialize_processors()` 注册视频处理器
  - `raganything/utils.py` — `get_processor_for_type()` 添加 video 路由
  - `raganything/processor.py` — 多模态处理流中插入视频类型
  - `raganything/config.py` — 新增视频处理配置项
  - `raganything/prompt.py` — 新增视频分析 Prompt 模板
  - `raganything/query.py` — 查询时支持视频内容描述
- **新增依赖（可选）**：`opencv-python-headless`、`openai-whisper`、`ffmpeg-python`
- **无破坏性变更**：所有视频功能通过配置开关控制，默认关闭，不影响现有流程
