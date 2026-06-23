## Context

视频处理模块 `raganything/video_processor/__init__.py`（949行）已实现完整的帧提取→音频转录→VLM分析→知识图谱管线，但`ENABLE_VIDEO_PROCESSING=false`默认关闭。代码审查识别出4个P0缺陷需要修复才能安全交付甲方。

关键约束：
- 所有配置值必须从环境变量→`RAGAnythingConfig`→处理器实例，不硬编码
- Whisper为CPU推理（`fp16=False`），部署环境通常无GPU
- DashScope VLM API有速率限制，需要合理的帧分析并发控制
- 修改范围限定在video_processor内部，不改变对外接口

## Goals / Non-Goals

**Goals:**
- 建立 `RAGAnythingConfig` → `VideoModalProcessor` 的配置传递路径
- 在视频处理入口处强制执行 `video_max_duration` 校验
- 使 Whisper 模型大小可通过环境变量配置
- 修复 `max_transcript_tokens` 截断逻辑（配置值接线 + token级截断）
- 优化短/中视频的帧提取性能，同时避免长视频的decode浪费

**Non-Goals:**
- `faster-whisper` 替换（Phase 3）
- VLM API 熔断器（Phase 3）
- `SceneDetector` 接线到帧选择逻辑（Phase 2）
- `video_max_concurrent` Semaphore接线（Phase 2）
- `_frame_cache` LRU淘汰+TTL（Phase 2）
- 音频预处理增强（loudnorm/VAD/降噪，Phase 3）
- 帧prompt修复（Phase 2）

## Decisions

### D1: Config传递方式——传入完整config对象

**选择**：在 `VideoModalProcessor.__init__` 中接收 `config: RAGAnythingConfig` 对象，提取所需字段存储为实例属性。

**替代方案**：
- A) 逐个传递字段（`max_duration`, `max_transcript_tokens`, `whisper_model_size`）→ 拒绝：每新增一个配置项就要改函数签名
- B) 在处理器内部直接读 `os.getenv()` → 拒绝：绕过统一配置层，`process_worker.py` 和 `kb_service.py` 已有`_env_int()`安全读取模式，重复实现增加不一致风险

**理由**：config对象路径与现有的 `modal_caption_func` 传递模式一致。`raganything.py:267` 已有config对象可用。字段提取在 `__init__` 中完成，后续代码引用实例属性，保持与当前代码风格一致。

### D2: 时长校验位置——generate_description_only 入口

**选择**：在 `generate_description_only()` 方法开头（`validate_video_file` 之后、帧提取之前）进行时长校验。

**具体流程**：
1. `validate_video_file()` 先行（文件存在性、格式、ffprobe可用性）
2. 通过后，检查 `metadata["duration"] > self._max_duration`
3. 超限：raise `ValueError(f"视频时长{metadata['duration']}s超过上限{self._max_duration}s")`
4. 调用方（`multimodal_processor.py`）的 `except Exception` 捕获后创建fallback entity

**替代方案**：
- A) 在 `validate_video_file()` 中校验 → 拒绝：该函数当前不接收config参数，且职责为"验证文件格式"，加入业务策略会违反单一职责
- B) 在 `FrameExtractor.extract_frames()` 中校验 → 拒绝：帧提取可能被独立调用，不应承担业务策略

**理由**：`generate_description_only` 是视频处理的主入口，在此校验确保不浪费任何资源（帧提取、转录、VLM调用）在超限视频上。

### D3: Whisper模型默认——`small`

**选择**：默认 `WHISPER_MODEL_SIZE=small`（244M参数，~500MB，中文WER~10-15%）。

| 模型 | 参数 | 内存 | 中文WER | RTF(CPU) |
|------|------|------|---------|----------|
| tiny（旧默认） | 39M | ~1GB | ~32% | ~0.03 |
| base | 74M | ~1.2GB | ~20-25% | ~0.05 |
| **small（新默认）** | **244M** | **~2GB** | **~10-15%** | **~0.1** |
| medium | 769M | ~5GB | ~8-11% | ~0.3 |

**替代方案**：base作为默认 → 拒绝：base的中文WER仍在~20-25%，对LLM消费而言仍是噪音级别

**验证**：`config.__post_init__` 中枚举验证，仅允许 `("tiny", "base", "small", "medium", "large")`

**迁移**：存量用户如需保持tiny，设置 `WHISPER_MODEL_SIZE=tiny`

### D4: 帧提取——时长感知路由

**选择**：基于视频时长选择提取策略，而非一刀切使用fps filter。

```
video_duration < 180s AND source_frames/output_frames < 100:
    → 单次ffmpeg fps filter（避免60次子进程开销）
otherwise:
    → 串行ffmpeg -ss seek（避免decode浪费，长视频3600s/60帧 = 99%帧被丢弃）
```

**替代方案**：
- A) 始终使用fps filter → 拒绝：长视频场景下108,000帧decode取60帧输出，CPU浪费率99.94%
- B) 始终使用串行seek → 拒绝：短视频场景下60次子进程启动开销显著
- C) 并行seek（ThreadPoolExecutor）→ 考虑但暂不实施：增加复杂度，Phase 1保持简单

**帧时间戳恢复**：fps filter输出文件名为 `frame_0001.png`, `frame_0002.png`...，时间戳通过 `timestamp = index / sample_rate` 计算。这比ffmpeg `-ss` 方式更精确（避免了seek精度误差）。

**VFR视频处理**：fps filter会将VFR标准化为CFR。对于VFR视频（手机拍摄常见），fps filter可能产生轻微时间戳偏移（≤1/fps），对VLM分析无实质影响。

**Fallback**：如果fps filter调用失败，回退到串行seek模式并记录WARNING日志。

### D5: Token计数——tiktoken优先，字符估算回退

**选择**：
1. 尝试 `import tiktoken` + `tiktoken.get_encoding("cl100k_base")`
2. 成功 → `len(encoding.encode(text))` 精确token计数
3. 失败 → 估算：中文 `len(text)` (≈1 token/char)，英文 `len(text.split()) * 1.3`，混合 `len(text) * 0.6`
4. 截断时反向查找最近句子边界（`。！？\n`），确保不截断在句子中间
5. 超过限制时在文本末尾追加 `[转录已截断]`

**理由**：`tiktoken` 为 `openai` SDK自带依赖（项目已依赖），无需新增安装。字符估算为fallback，cover边缘场景。

### D6: AudioTranscriber参数化

**选择**：`AudioTranscriber.__init__` 接受 `model_size: str` 参数（默认 `"small"`），不再硬编码 `"tiny"`。`raganything.py:257` 构造时传入 `config.whisper_model_size`。

**当前代码**（`__init__.py:409`）：
```python
def __init__(self, model_size: str = "tiny", timeout: int = 300):
```

**修改后**：
```python
def __init__(self, model_size: str = "small", timeout: int = 300):
```

## Risks / Trade-offs

| 风险 | 影响 | 缓解措施 |
|------|------|----------|
| Whisper `small` 在<2GB内存的机器上OOM | 进程崩溃 | `__post_init__`中不强制内存检查（依赖多样性），部署文档注明最低2.5GB RAM |
| fps filter在精简ffmpeg构建中不可用 | 帧提取失败 | 回退到串行seek模式 + WARNING日志 |
| VFR视频时间戳轻微偏移 | VLM分析质量略降 | 偏移≤1/fps，对帧描述影响可忽略；需要准确时间戳的场景使用seek模式 |
| `tiktoken`未安装时使用字符估算 | token截断可能误差2-3x | 默认`max_transcript_tokens=4000`下有足够余量；字符估算偏保守 |
| 超限视频从"截断"改为"拒绝" | 部分用户可能需要处理长教学视频 | env var `VIDEO_MAX_DURATION` 可调高上限；Phase 2可考虑添加截断选项 |
| Config接线增加`VideoModalProcessor.__init__`参数 | 调用方需更新 | 仅2个调用方（`raganything.py` + `test_video_processor.py`），改动量极小 |

## Open Questions

1. **长视频"截断"方案是否需要在Phase 2恢复？** 当前决定"拒绝"以保护API成本。如果用户反馈需要处理长视频（如教学录播），可在Phase 2添加可配置的截断模式。
2. **`small`模型是否应在首次使用前预下载？** Docker镜像构建时预下载可避免首次处理的冷启动延迟，但增加镜像体积~500MB。作为部署文档事项而非代码逻辑。
