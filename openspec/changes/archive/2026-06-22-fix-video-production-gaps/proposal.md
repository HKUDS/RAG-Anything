## Why

视频处理模块（`raganything/video_processor/__init__.py`，949行）存在4个P0级生产缺陷，导致：API预算不可控（无视频时长上限执行）、中文音频转录质量极差（Whisper tiny模型中文WER~32%）、配置项被硬编码忽略（`max_transcript_tokens`定义为4000但代码使用字符截断）、帧提取性能差（60次串行ffmpeg子进程）。此模块目前`ENABLE_VIDEO_PROCESSING=false`，修复后方可安全交付甲方。

**关键前提**：所有修复依赖将 `RAGAnythingConfig` 的视频字段传入 `VideoModalProcessor.__init__`。当前 `VideoModalProcessor` 完全不接收 config 对象，导致 `video_max_duration`、`max_transcript_tokens` 等值没有传递路径。此 config 接线是 Phase 1 的先决条件。

## What Changes

- **视频时长上限强制执行**：`video_max_duration`（默认3600s）从纯声明变为 `generate_description_only` 入口处实际校验，超限视频直接拒绝处理（`ValueError`），防止API预算被数小时视频耗尽。**BREAKING**：此为spec行为变更——原spec定义"超限截断"，现改为"超限拒绝"（截断方案对API成本保护不充分，且截断后分析结果具有误导性）
- **音频转录模型大小可配置**：新增 `WHISPER_MODEL_SIZE` 环境变量（默认`small`），解决硬编码`tiny`在中文场景下WER高达32%的问题。**BREAKING**：默认值从`tiny`（~150MB）变为`small`（~500MB），存量部署首次使用将触发新模型下载，CPU转录时间约增加2x
- **转录文本截断修复**：`max_transcript_tokens` 从硬编码4000字符改为读取配置值，按token计数截断（tiktoken优先、字符估算回退），截断边界对齐最近句子边界（`。！？\n`），并在末尾标注"[转录已截断]"
- **帧提取性能优化**：60次串行`ffmpeg -ss`子进程改为单次ffmpeg `fps` filter调用（短视频 < 180s），长视频回退到并行seek方式。帧时间戳通过 `index / fps` 计算恢复，无需依赖文件名解析

## Capabilities

### New Capabilities
无新增能力。所有改动均为对现有 spec 中已定义行为的修复或增强。

### Modified Capabilities
- `video-audio-transcription`: 新增 `WHISPER_MODEL_SIZE` 可配置需求（Whisper模型大小通过环境变量选择）；修正转录截断需求（从硬编码4000字符改为使用 `max_transcript_tokens` 配置值，按token计数，对齐句子边界）
- `video-config-integration`: 新增 `WHISPER_MODEL_SIZE` 环境变量配置项；新增 `video_max_duration` 运行时执行校验需求；新增 `VideoModalProcessor` 接收 config 对象需求（config接线先决条件）
- `video-frame-extraction`: **spec行为变更**——视频时长超限策略从"截断处理"改为"拒绝处理"（附理由：截断无法保护API成本，且产生误导性分析结果）；帧提取方法从多次串行子进程改为时长感知路由（短视频单次fps filter，长视频并行seek）

注：`max_transcript_tokens` 截断行为同时影响 `video-knowledge-graph`（截断后的转录文本作为VLM综合分析的输入）。`video-knowledge-graph` spec通过引用 `video-audio-transcription` 继承截断行为，不需要独立修改。

## Impact

- **受影响代码**：
  - `raganything/video_processor/__init__.py`（主要改动：AudioTranscriber新增model_size参数、FrameExtractor新增fps模式、VideoModalProcessor接收config、generate_description_only入口时长校验、transcript截断修复）
  - `raganything/raganything.py`（AudioTranscriber构造传参、VideoModalProcessor构造传入config）
  - `raganything/config.py`（新增 `whisper_model_size` 配置项 + `__post_init__` 枚举验证）
  - `raganything/processor/multimodal_processor.py`（可能需要处理视频时长超限导致的跳过逻辑）
- **不受影响的代码**（经grep验证）：
  - `process_worker.py`：无任何视频处理引用
  - `raganything/services/kb_service.py`：无任何视频处理引用
- **受影响API**：无新增或修改API端点
- **受影响依赖**：无新增依赖。`tiktoken`（如需精确token计数）为openai SDK自带，已间接依赖
- **向后兼容**：Whisper模型默认从`tiny`→`small`（迁移指南：如需保持`tiny`，设置 `WHISPER_MODEL_SIZE=tiny`）；视频超限行为从静默截断→明确拒绝；对外接口（`generate_description_only`签名）不变
- **风险**：中。核心改动集中在 `video_processor/__init__.py`，但配置接线路径跨越3个文件，需要集成测试验证 config 值实际到达处理器。帧提取性能在长视频场景下需验证回退路径
