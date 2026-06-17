# Video Knowledge Graph

## Purpose

将视频内容（帧描述 + 音频转录 + 时序元数据）通过 VLM 分析生成综合描述，作为知识图谱实体存储，支持语义检索。

## ADDED Requirements

### Requirement: 视频内容分析

系统 SHALL 通过 VLM 分析视频的关键帧和音频转录，生成视频的综合描述和知识图谱实体信息。

#### Scenario: 成功生成视频描述
- **WHEN** 关键帧已提取且音频转录已完成
- **THEN** 系统将代表性帧编码为 base64 并附上转录文本发送给 VLM
- **THEN** VLM 返回 JSON 格式的 `detailed_description`（综合帧间分析和音频内容）
- **THEN** 返回的 `entity_info` 包含 `entity_name`、`entity_type: "video"`、`summary`

#### Scenario: VLM 不可用（无 vision_model_func）
- **WHEN** 未配置 `vision_model_func` 且 `modal_caption_func` 也不支持图片
- **THEN** 系统使用纯文本分析模式
- **THEN** 仅基于音频转录文本和帧元数据生成描述
- **THEN** 描述中标注"无视觉分析"

#### Scenario: 部分帧分析失败
- **WHEN** 某个关键帧的 VLM 调用失败（如 API 超时）
- **THEN** 系统记录该帧失败原因并继续分析其余帧
- **THEN** 综合描述中标注"部分帧分析失败"

### Requirement: 视频实体创建

系统 SHALL 将视频分析结果作为知识图谱实体存储，包含完整的视频元数据和描述。

#### Scenario: 创建视频知识图谱实体
- **WHEN** 视频描述和实体信息已生成
- **THEN** 系统调用 `_create_entity_and_chunk()` 创建实体和文本 chunk
- **THEN** 实体类型为 `"video"`
- **THEN** chunk 内容包含视频路径、时长、帧数、转录摘要、综合描述
- **THEN** 实体存入向量数据库以支持语义检索

#### Scenario: 视频实体与其他实体关联
- **WHEN** 视频 chunk 中存在可提取的实体（如人物、地点、概念）
- **THEN** 系统通过 `extract_entities` 提取文本中的实体和关系
- **THEN** 提取的实体通过 `belongs_to` 关系关联到视频实体
- **THEN** 关系存入知识图谱以供图检索通道使用

### Requirement: 视频查询支持

系统 SHALL 支持在查询时对视频内容进行描述生成，使检索结果能包含视频实体的语义信息。

#### Scenario: 查询中包含视频类型的内容
- **WHEN** 检索结果中存在 `type: "video"` 的多模态内容
- **THEN** 系统调用 `VideoModalProcessor` 生成该视频内容的查询描述
- **THEN** 生成的描述用于回答增强

#### Scenario: 视频查询回退
- **WHEN** 视频处理器不可用或视频文件已移动/删除
- **THEN** 系统使用已存储的视频实体摘要作为回退描述
- **THEN** 记录 `WARNING` 日志"视频文件不可用，使用缓存描述"

### Requirement: 视频 Chunk 模板

系统 SHALL 使用专用模板格式化视频内容 chunk，包含完整的视频元数据和分析结果。

#### Scenario: 格式化视频 chunk
- **WHEN** 视频分析完成
- **THEN** chunk 包含以下字段：
  - 视频路径（`video_path`）
  - 视频时长（`duration` 秒）
  - 采样帧数（`frame_count`）
  - 音频转录摘要（`transcript_summary`）
  - VLM 综合描述（`enhanced_caption`）
- **THEN** chunk 长度不超过 `MAX_CHUNK_CHARS=8000`
