# Video Audio Transcription

## Purpose

从视频文件中提取音频轨道，通过 Whisper 模型转录音频为文本，为视频视觉分析提供语义上下文补充。

## ADDED Requirements

### Requirement: 音频轨道提取

系统 SHALL 从视频文件中提取音频轨道并保存为临时音频文件，支持无音频轨道的视频优雅降级。

#### Scenario: 视频包含音频轨道
- **WHEN** 视频文件包含有效的音频轨道
- **THEN** 系统使用 ffmpeg 提取音频为 16kHz 单声道 WAV 文件
- **THEN** 音频文件保存到临时目录

#### Scenario: 视频不包含音频轨道
- **WHEN** 视频文件没有音频轨道
- **THEN** 系统记录 `INFO` 日志"视频无音频轨道"
- **THEN** 转录结果为空字符串
- **THEN** 后续 VLM 分析仅基于视觉帧进行

#### Scenario: 音频提取失败
- **WHEN** ffmpeg 音频提取过程出错（如编码不支持）
- **THEN** 系统记录 `WARNING` 日志包含错误详情
- **THEN** 转录结果为空字符串
- **THEN** 处理流程继续，不中断整个视频处理

### Requirement: Whisper 语音转录

系统 SHALL 通过 Whisper 模型将提取的音频转录为文本，支持多语言识别和配置模型大小。

#### Scenario: 成功转录音频
- **WHEN** 音频文件有效且 Whisper 模型可用
- **THEN** 系统使用配置的 Whisper 模型（默认 `tiny`）进行转录
- **THEN** 返回转录文本字符串
- **THEN** 文本中标注语言类型（如 `zh`、`en`）

#### Scenario: Whisper 模型不可用
- **WHEN** `openai-whisper` 包未安装
- **THEN** 系统抛出 `ImportError` 并提示 `pip install openai-whisper`
- **THEN** 如 `video_audio_transcribe=False`，系统跳过转录直接返回空字符串

#### Scenario: 转录超时
- **WHEN** 转录时间超过 `video_transcribe_timeout=300`（默认 5 分钟）
- **THEN** 系统中止转录进程
- **THEN** 记录 `WARNING` 日志"转录超时"
- **THEN** 返回空字符串，处理流程继续

### Requirement: 转录文本截断

系统 SHALL 对超长转录文本进行截断，确保不超过上下文窗口限制。

#### Scenario: 转录文本在限制内
- **WHEN** 转录文本长度 ≤ `max_transcript_tokens=4000`（按 token 计数）
- **THEN** 系统保留完整转录文本

#### Scenario: 转录文本超过限制
- **WHEN** 转录文本长度 > `max_transcript_tokens=4000`
- **THEN** 系统截断至 `max_transcript_tokens` 个 token
- **THEN** 截断位置在最近的句子边界
- **THEN** 在文本末尾标注"[转录已截断]"
