## ADDED Requirements

### Requirement: 智能体图片召回使用独立媒体预算

系统 SHALL 为标准、CoT 和 ReAct 智能体路径的图片召回提供独立于文本检索 deadline 的媒体预算；该预算 SHALL 在媒体阶段开始时计算，默认 8 秒，并可由 `AGENT_MEDIA_RECALL_TIMEOUT` 配置。

#### Scenario: 文本检索耗尽预算后仍召回图片
- **WHEN** 文本 RRF graph 通道已经耗尽或接近文本检索 deadline
- **AND** 检索上下文包含可交付图片路径
- **THEN** 媒体阶段 MUST 使用新的独立 deadline
- **AND** 已通过受控校验的图片 MUST 出现在 SSE `done.images` 中

#### Scenario: agentic 路径使用同一媒体预算规则
- **WHEN** CoT 或 ReAct 智能体完成推理并开始图片召回
- **THEN** 系统 MUST 使用与标准路径相同的独立媒体预算和受控 payload 转换逻辑

#### Scenario: 非法媒体预算配置
- **WHEN** `AGENT_MEDIA_RECALL_TIMEOUT` 为空、不可解析、NaN 或无穷值
- **THEN** 系统 MUST 回退到 8 秒默认值
- **AND** 有限的非正值 MUST 被限制为最小 0.1 秒

### Requirement: 媒体超时保留已验证结果

系统 SHALL 在媒体预算耗尽时保留此前已经完成受控媒体校验的图片，不得因后续候选超时而清空整个结果集。

#### Scenario: 后续图片校验超时
- **WHEN** 多张候选图片按顺序执行受控校验
- **AND** 至少一张图片已完成 KB 证据、grant、sha256 与文件校验
- **AND** 后续图片在媒体 deadline 前未完成
- **THEN** 系统 MUST 返回此前已验证的图片
- **AND** `media` timing MUST 记录 `outcome=timeout`
- **AND** 系统 MUST 记录 `timeout-partial` 日志且不得留下继续签发 grant 的后台任务

#### Scenario: 无图片完成受控校验
- **WHEN** 媒体 deadline 到达前没有候选完成受控校验
- **THEN** 系统 MUST 返回空图片列表
- **AND** MUST NOT 向客户端暴露任何本地路径或未验证 payload

#### Scenario: 请求主动取消
- **WHEN** 客户端断开或上层取消媒体召回任务
- **THEN** 系统 MUST 向上传播 `CancelledError`
- **AND** MUST NOT 将请求取消转换为媒体超时或继续后台校验
