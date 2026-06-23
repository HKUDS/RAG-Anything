# Video Audio Transcription (Delta)

## ADDED Requirements

### Requirement: Whisper模型大小可配置

系统 SHALL 支持通过环境变量 `WHISPER_MODEL_SIZE` 配置音频转录使用的 Whisper 模型大小，默认值为 `small`。

#### Scenario: 默认使用small模型
- **WHEN** 用户未设置 `WHISPER_MODEL_SIZE` 环境变量
- **THEN** `AudioTranscriber` 使用 `small` 模型进行初始化
- **THEN** 转录质量和性能对标 small 模型（中文 WER ~10-15%，内存 ~2GB）

#### Scenario: 环境变量指定模型
- **WHEN** 设置 `WHISPER_MODEL_SIZE=medium`
- **THEN** `RAGAnythingConfig.whisper_model_size` 为 `medium`
- **THEN** `AudioTranscriber` 使用 `medium` 模型进行转录

#### Scenario: 无效模型大小
- **WHEN** 设置 `WHISPER_MODEL_SIZE=xlarge`（不在允许列表中）
- **THEN** 系统在 `__post_init__` 中发出 `UserWarning` 并回退到默认值 `small`
- **THEN** 允许的取值为 `tiny`、`base`、`small`、`medium`、`large`

#### Scenario: 模型文件缺失
- **WHEN** `whisper.load_model("small")` 需要下载但网络不可用
- **THEN** 系统抛出 `ImportError` 并提示模型下载失败
- **THEN** 如果 `ENABLE_AUDIO_TRANSCRIPTION=false`，转录被跳过而非报错

## MODIFIED Requirements

### Requirement: 转录文本截断

系统 SHALL 对超长转录文本按 token 数进行截断，使用 `max_transcript_tokens` 配置项（而非硬编码字符数），截断边界对齐最近句子边界，并标注截断标记。

#### Scenario: 转录文本在限制内
- **WHEN** 转录文本的 token 数 ≤ `max_transcript_tokens` 配置值
- **THEN** 系统保留完整转录文本，不做任何截断

#### Scenario: 转录文本超过限制
- **WHEN** 转录文本的 token 数 > `max_transcript_tokens` 配置值
- **THEN** 系统精确计算 token 数（tiktoken `cl100k_base` 优先，字符估算 `len(text)*0.6` 回退）
- **THEN** 系统在 `max_transcript_tokens` 以内的最近句子边界（`。！？\n`）处截断
- **THEN** 在截断后的文本末尾追加 `[转录已截断]`

#### Scenario: tiktoken不可用时回退
- **WHEN** `tiktoken` 模块不可导入
- **THEN** 系统使用字符估算 `len(text) * 0.6` 近似 token 数
- **THEN** 记录 `DEBUG` 日志"tiktoken not available, using character-based estimation"

### Requirement: Whisper 语音转录

系统 SHALL 通过 Whisper 模型将提取的音频转录为文本，支持多语言识别和可配置模型大小。

#### Scenario: 成功转录音频
- **WHEN** 音频文件有效且 Whisper 模型可用
- **THEN** 系统使用配置的 Whisper 模型（默认 `small`，可配置）进行转录
- **THEN** 返回转录文本字符串
- **THEN** 文本中标注语言类型（如 `zh`、`en`）

#### Scenario: Whisper 模型不可用
- **WHEN** `openai-whisper` 包未安装
- **THEN** 系统抛出 `ImportError` 并提示 `pip install openai-whisper`
- **THEN** 如 `ENABLE_AUDIO_TRANSCRIPTION=false`，系统跳过转录直接返回空字符串

#### Scenario: 转录超时
- **WHEN** 转录时间超过 `video_transcribe_timeout=300`（默认 5 分钟）
- **THEN** 系统中止转录进程
- **THEN** 记录 `WARNING` 日志"转录超时"
- **THEN** 返回空字符串，处理流程继续
