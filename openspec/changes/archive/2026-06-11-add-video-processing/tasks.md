## 1. 配置扩展

- [x] 1.1 在 `RAGAnythingConfig` 中添加视频处理配置项（`enable_video_processing`、`video_sample_rate`、`video_max_duration`、`video_max_frames`、`enable_audio_transcription`、`enable_scene_detection`），默认关闭视频处理
- [x] 1.2 在 `supported_file_extensions` 默认值中添加视频格式（`.mp4,.avi,.mov,.mkv,.webm`）

## 2. 视频处理子组件

- [x] 2.1 实现 `FrameExtractor` 类：基于 ffmpeg 的视频帧提取，支持均匀采样和帧数上限控制
- [x] 2.2 实现 `SceneDetector` 类：基于直方图差异的场景变化检测，返回场景边界时间戳
- [x] 2.3 实现 `AudioTranscriber` 类：基于 openai-whisper 的音频转录，支持模型大小配置、超时控制、优雅降级
- [x] 2.4 实现 `validate_video_file()` 函数：通过 ffprobe 验证视频文件有效性，返回元数据（时长、分辨率、编码、音频轨道信息）
- [x] 2.5 实现 `check_video_skippable()` 函数：检测极短视频（<1s）和静态画面视频，避免无效处理

## 3. VideoModalProcessor 核心

- [x] 3.1 在 `video_processor.py` 中新增 `VideoModalProcessor(BaseModalProcessor)` 类，采用外观模式聚合子组件
- [x] 3.2 实现 `generate_description_only()`：抽取关键帧 → 音频转录（可选）→ VLM 逐帧分析 → LLM 综合描述 → 返回 `(description, entity_info)`
- [x] 3.3 实现 `process_multimodal_content()`：调用 `generate_description_only()` + `_create_entity_and_chunk()` 完成实体创建
- [x] 3.4 在构造函数中实现可选依赖的懒加载检测（ffmpeg、whisper），缺少时记录清晰日志

## 4. Prompt 模板

- [x] 4.1 在 `prompt.py` 中添加 `VIDEO_ANALYSIS_SYSTEM` 系统提示词
- [x] 4.2 在 `prompt.py` 中添加 `video_prompt`（含帧描述、转录文本、时长元数据占位符）
- [x] 4.3 在 `prompt.py` 中添加 `video_prompt_with_context`（含上下文信息）
- [x] 4.4 在 `prompt.py` 中添加 `video_chunk` 模板（含 video_path、duration、frame_count、transcript_summary、enhanced_caption 占位符）

## 5. 集成点

- [x] 5.1 在 `utils.py` 的 `get_processor_for_type()` 中添加 `elif content_type == "video"` 路由分支
- [x] 5.2 在 `utils.py` 的 `get_processor_supports()` 中添加 `"video"` 条目（支持格式列表、最大时长、依赖状态）
- [x] 5.3 在 `utils.py` 的 `separate_content()` 中添加 `type == "video"` 识别，将视频路由到多模态处理路径
- [x] 5.4 在 `processor.py` 的 `_apply_chunk_template()` 中添加 `content_type == "video"` 分支
- [x] 5.5 在 `processor.py` 的 `parse_document()` 中添加对视频文件扩展名的路由识别
- [x] 5.6 在 `raganything.py` 中导入 `VideoModalProcessor`
- [x] 5.7 在 `raganything.py` 的 `_initialize_processors()` 中添加视频处理器注册（在 equation 之后、generic 之前）

## 6. 文件扩展名与批量处理

- [x] 6.1 更新 `env.example` 添加所有视频相关环境变量及说明
- [x] 6.2 确保 batch 模式的 `_process_multimodal_content_batch_type_aware()` 通过 `get_processor_for_type("video")` 正确路由视频处理
- [x] 6.3 添加视频处理专用的并发控制（环境变量 `VIDEO_MAX_CONCURRENT`，默认 2）

## 7. 测试与验证

- [x] 7.1 编写 `FrameExtractor` 单元测试（均匀采样、帧数上限、格式不支持）
- [x] 7.2 编写 `AudioTranscriber` 单元测试（有音频、无音频、Whisper 不可用降级）
- [x] 7.3 编写 `VideoModalProcessor` 集成测试（端到端：视频文件 → 实体创建）
- [x] 7.4 编写配置集成测试（默认禁用、启用后处理器注册、缺少依赖降级）
- [x] 7.5 手动验证：使用短视频文件（~30s MP4）测试完整的处理+检索流程
