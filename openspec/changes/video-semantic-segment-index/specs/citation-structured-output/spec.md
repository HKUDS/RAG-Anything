## MODIFIED Requirements

### Requirement: 查询响应包含 citations 字段

所有查询 API 的响应 SHALL 包含 `citations` 字段，其值为结构化引用列表。视频段引用
可额外包含 `video_segment`，但既有字段和非视频响应 MUST 保持兼容。

#### Scenario: 非流式查询返回视频时间引用

- **WHEN** 客户端调用查询 API 且命中视频分段
- **THEN** 响应 JSON MUST 包含既有引用字段和 `video_segment` 的段 ID、起止毫秒与受控媒体引用

#### Scenario: 流式查询在 done 事件返回视频时间引用

- **WHEN** 客户端连接流式查询并命中视频分段
- **THEN** SSE `done` 事件 MUST 包含同样结构的 `citations`

#### Scenario: 向后兼容

- **WHEN** 现有客户端未处理 `video_segment`
- **THEN** 其他响应字段 MUST 保持不变，旧文本/旧视频块仍可按原格式返回
