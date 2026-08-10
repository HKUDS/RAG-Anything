## MODIFIED Requirements

### Requirement: 视频实体创建

系统 SHALL 将新视频的每个时间段作为独立知识图谱实体和文本 chunk 存储，并
通过父视频标识建立归属关系。父视频总览可作为清单元数据，但不得成为与段块
竞争的整片检索块。

#### Scenario: 创建视频分段实体

- **WHEN** 视频分段分析完成
- **THEN** 系统 MUST 创建包含 `segment_index`、`start_ms`、`end_ms`、局部转录、视觉摘要和受控媒体引用的 chunk
- **AND** 实体类型 MUST 为 `video_segment` 并关联父视频

#### Scenario: 分段实体与其他实体关联

- **WHEN** 分段文本中存在可提取的实体
- **THEN** 系统 MUST 通过 `belongs_to` 关系将其关联到该视频分段实体

### Requirement: 视频 Chunk 模板

系统 SHALL 使用视频分段模板，包含分段序号、起止时间、局部转录、视觉分析和受控
媒体引用。新上传视频的 chunk MUST NOT 包含本地绝对路径或仅路径占位内容。

#### Scenario: 格式化视频分段 chunk

- **WHEN** 视频分段分析完成
- **THEN** chunk MUST 包含有效 `duration`、`frame_count`、`start_ms`、`end_ms`、`transcript_summary` 和 `enhanced_caption`
- **AND** chunk 长度 MUST 不超过 `MAX_CHUNK_CHARS=8000`
