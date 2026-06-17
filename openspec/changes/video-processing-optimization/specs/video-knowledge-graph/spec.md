# Video Knowledge Graph (Delta)

## MODIFIED Requirements

### Requirement: 视频内容分析

系统 SHALL 通过 VLM 并发分析视频的关键帧，并结合音频转录生成综合描述和知识图谱实体信息。帧分析使用独立信号量控制并发数，支持帧描述缓存以避免重复 VLM 调用。

#### Scenario: 成功生成视频描述（并发帧分析）
- **WHEN** 关键帧已提取且音频转录已完成
- **THEN** 系统通过 `asyncio.gather` 并发调用 VLM 分析代表性帧（默认最多 3 帧同时进行）
- **THEN** 所有帧分析完成后合成 JSON 格式的 `detailed_description`
- **THEN** 返回的 `entity_info` 包含 `entity_name`、`entity_type: "video"`、`summary`

#### Scenario: 帧缓存命中
- **WHEN** 关键帧已提取且帧缓存命中
- **THEN** 系统跳过 VLM 调用，直接使用缓存的帧描述
- **THEN** 缓存的帧描述与音频转录合成综合描述
- **THEN** 处理时间显著缩短

#### Scenario: VLM 不可用（无 vision_model_func）
- **WHEN** 未配置 `vision_model_func` 且 `modal_caption_func` 也不支持图片
- **THEN** 系统使用纯文本分析模式
- **THEN** 仅基于音频转录文本和帧元数据生成描述
- **THEN** 描述中标注"无视觉分析"

#### Scenario: 部分帧分析失败
- **WHEN** 某个关键帧的并发 VLM 调用失败（如 API 超时）
- **THEN** 系统记录该帧失败原因并继续分析其余帧
- **THEN** 综合描述中标注"部分帧分析失败"
