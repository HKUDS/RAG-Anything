## Context

RAG-Anything 当前的多模态处理架构基于 `BaseModalProcessor` 抽象基类，派生 `ImageModalProcessor`、`TableModalProcessor`、`EquationModalProcessor`、`GenericModalProcessor` 四个处理器。每个处理器通过 `generate_description_only()` 生成描述和实体信息，再通过 `process_multimodal_content()` 创建知识图谱实体和文本 chunk。

视频处理在架构上与图片处理最为接近——都需要 VLM 进行视觉分析。但视频引入了两个核心差异：
1. **多帧时序**：视频由多个帧组成，需要处理时序维度
2. **音频轨道**：视频通常包含语音/音频，需要转录为文本补充视觉分析

当前系统已具备的基础设施：
- `BaseModalProcessor` 基类提供 context extraction、JSON parsing、entity/chunk creation 等通用能力
- `ContextExtractor` 支持页面/块级别的上下文提取
- `RAGAnythingConfig` 通过 dataclass + env var 管理配置
- `get_processor_for_type()` 做类型到处理器的路由
- `PROMPTS` 字典管理各模态的 Prompt 模板

## Goals / Non-Goals

**Goals:**
- 新增 `VideoModalProcessor` 继承 `BaseModalProcessor`，复用现有的 entity/chunk 创建、JSON 解析、上下文提取能力
- 支持从视频文件中提取关键帧（基于采样率或场景变化检测）
- 支持提取音频轨道并通过 Whisper 转录音频为文本
- 将帧描述 + 音频转录 + 时序元数据合并为知识图谱实体
- 通过配置开关控制视频处理启用/禁用，默认关闭
- 可选依赖优雅降级：缺少 opencv/ffmpeg/whisper 时给出明确错误提示
- 异步非阻塞处理：视频处理作为后台任务执行，不阻塞主流程

**Non-Goals:**
- 实时视频流处理
- 视频中的人脸识别、物体检测等专项 CV 任务
- 视频字幕/字幕轨道的 OCR（仅使用 Whisper 做音频转录）
- 视频编辑/转码能力
- GPU 加速（视频处理使用 CPU，VLM 调用可配置）
- 视频存储/托管（仅引用本地路径或 URL）

## Decisions

### Decision 1: VideoModalProcessor 继承 BaseModalProcessor

**选择**：`class VideoModalProcessor(BaseModalProcessor)`

**理由**：
- 复用 `_create_entity_and_chunk()`、`_robust_json_parse()`、`_get_context_for_item()`、`_strip_thinking_tags()` 等通用方法
- 保持与现有 ImageModalProcessor/TableModalProcessor 的一致性
- 仅需实现 `generate_description_only()` 和 `process_multimodal_content()` 两个核心方法

**备选方案**：独立处理器类（不继承 BaseModalProcessor）
- 优点：更灵活，不需要适配基类约定
- 缺点：大量重复代码（JSON 解析、实体创建、chunk 存储等），与现有架构不一致

### Decision 2: 视频分析 Pipeline：帧采样 → 音频转录 → VLM 分析 → 实体创建

**选择**：分两个阶段处理
- **Stage 1（预处理）**：提取关键帧 + 音频转录为文本
- **Stage 2（VLM 分析）**：将代表性帧 + 转录文本一起发送给 VLM 生成描述

**理由**：
- 将计算密集型操作（抽帧、转录）与 LLM 调用分离
- 音频转录提供语义上下文，增强 VLM 对视频内容的理解
- 帧采样避免向 VLM 发送过多图片（成本控制）

**备选方案**：逐帧独立分析 → 合并结果
- 缺点：丢失帧间时序关系，缺少音频上下文，VLM 调用次数多（成本高）

### Decision 3: 帧采样策略默认 1 fps，支持场景变化检测

**选择**：
- 默认采样率：1 fps（每秒 1 帧）
- 可选场景变化检测：当相邻帧差异超过阈值时额外采样
- 最大采样帧数：60 帧（防止超长视频）

**理由**：
- 1 fps 在大多数视频中足以捕获关键画面变化
- 场景检测补充关键过渡帧
- 上限防止无限 VLM 调用

**备选方案**：固定 N 帧采样、仅关键帧（I-frame）
- 固定 N 帧：无法适应不同长度视频
- 仅 I-frame：实现简单但可能错失内容变化的粒度

### Decision 4: 音频转录使用 Whisper，作为可选功能

**选择**：
- 使用 `openai-whisper` 库
- 默认使用 `tiny` 模型（平衡速度与准确性）
- 通过 `video_audio_transcribe` 配置开关控制
- 转录失败时降级为无音频模式

**理由**：
- Whisper 是开源标准，支持多语言
- tiny 模型在 CPU 上也能快速运行
- 可选关闭避免不必要开销（如纯画面视频）

**备选方案**：云端 ASR API（如 OpenAI Whisper API）
- 优点：无需本地模型，质量更高
- 缺点：额外 API 费用，网络依赖，隐私顾虑

### Decision 5: 可选依赖管理与优雅降级

**选择**：
- 视频处理依赖（`opencv-python-headless`、`openai-whisper`、`ffmpeg-python`）不加入 `requirements.txt`
- 在 `VideoModalProcessor.__init__()` 中做 import 检查
- 缺少依赖时抛出清晰的 `ImportError` 提示安装命令
- `enable_video_processing` 默认 `False`

**理由**：
- 不强制所有用户安装视频处理依赖
- 保持轻量化安装体验
- 符合 Python 可选依赖的最佳实践

**备选方案**：使用 extras（`pip install raganything[video]`）
- 优点：更标准的 Python 包管理方式
- 缺点：需要包发布体系支持，当前项目尚未采用

### Decision 6: 视频文件支持范围

**选择**：支持 MP4、AVI、MOV、MKV、WebM 格式

**理由**：覆盖最常见的视频容器格式，与 OpenCV/FFmpeg 默认支持的格式一致

## Risks / Trade-offs

- **[成本风险] VLM 调用费用**：每个视频最多 60 帧 × VLM 调用，按 1 fps 采样 10 分钟视频 = 600 帧，截断为 60 帧。→ 通过 `max_frames_per_video` 配置上限，长视频默认只取首尾和均匀间隔共 60 帧。
- **[性能风险] 视频处理耗时**：抽帧 + 转录 + VLM 分析可能需要数分钟。→ 全部作为后台异步任务 (`asyncio.Task`) 执行，与现有 `register_background_task()` 机制集成。
- **[精度风险] 1 fps 采样丢失细节**：快速切换的画面可能被遗漏。→ 提供 `video_sample_rate` 配置让用户调整；场景变化检测作为补充。
- **[兼容性风险] ffmpeg 环境依赖**：OpenCV 和 Whisper 依赖 ffmpeg 解码。→ 在初始化时做环境检查，给出清晰的安装指引。
- **[存储风险] 视频实体体积**：视频描述可能很长。→ 复用现有的 `MAX_CHUNK_CHARS=8000` 截断机制。
