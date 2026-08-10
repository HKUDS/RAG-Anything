## MODIFIED Requirements

### Requirement: Whisper 语音转录

系统 SHALL 通过 Whisper 模型将视频音频转录为文本，并在可用时保留有序的
`start`、`end`、`text` 时间段；返回值 MUST 同时提供兼容的合并文本和时间段列表。

#### Scenario: 成功转录音频

- **WHEN** 音频文件有效且 Whisper 模型可用
- **THEN** 系统使用配置的 Whisper 模型进行转录
- **THEN** 返回文本、语言和按时间排序的非空时间段

#### Scenario: Whisper 模型不可用

- **WHEN** `openai-whisper` 包未安装
- **THEN** 系统抛出 `ImportError` 并提示 `pip install openai-whisper`
- **THEN** 如 `ENABLE_AUDIO_TRANSCRIPTION=false`，系统跳过转录并返回空文本和空时间段

#### Scenario: 转录超时

- **WHEN** 转录时间超过 `video_transcribe_timeout=300`
- **THEN** 系统中止转录进程
- **THEN** 记录警告并返回空文本和空时间段
