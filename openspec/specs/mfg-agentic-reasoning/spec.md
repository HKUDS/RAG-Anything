# Manufacturing Agentic Reasoning

## Purpose

将制造智能体 QA 引擎从单步"检索→LLM 直出"升级为 AgenticRAG 多步推理（ReAct/CoT），复用通用智能体的推理循环和工具生态，同时保留制造领域专有能力。

## Requirements

### Requirement: QA 引擎使用 AgenticRAG 多步推理
QAEngine SHALL 采用两级策略：Tier 1 直接 RRF 检索+LLM 生成（快速路径），仅在检索不充分（< 50 字符或置信度 < 0.3）时回退到 AgenticRAG 多步推理。

#### Scenario: 仅低质量检索触发 AgenticRAG
- **WHEN** 直接 RRF 检索返回 < 50 字符或置信度 < 0.3
- **THEN** QAEngine SHALL 启动 AgenticRAG 多步推理作为兜底

#### Scenario: 充分检索跳过 AgenticRAG
- **WHEN** 直接 RRF 检索返回 ≥ 200 字符充分上下文
- **THEN** QAEngine SHALL 不启动 AgenticRAG，直接构造 prompt 生成回答

### Requirement: 制造领域专用 System Prompt
AgenticRAG 的 ReAct system prompt SHALL 支持制造领域定制，将通用 AI 助手身份替换为"智能制造教学专家"。

#### Scenario: 制造领域身份注入
- **WHEN** QAEngine 初始化 AgenticRAG
- **THEN** ReAct prompt 的角色身份 SHALL 使用"智能制造教学专家"，保留工具描述和推理格式指令不变

#### Scenario: 领域知识约束
- **WHEN** Agent 生成最终回答
- **THEN** 回答 SHALL 基于检索到的文档内容，不编造制造参数和工艺信息

### Requirement: 制造 QA 保留图片匹配能力
QAEngine SHALL 在 AgenticRAG 推理完成后执行三级图片匹配（图号精确→Caption jieba→路径关键字），将匹配结果附加到 AgentResponse 中。

#### Scenario: 推理结束后图片匹配
- **WHEN** AgenticRAG 返回最终答案
- **THEN** QAEngine SHALL 对答案文本和检索上下文执行三级图片匹配，返回匹配的 base64 编码图片列表

#### Scenario: 无匹配图片
- **WHEN** 三级匹配均无结果
- **THEN** AgentResponse.related_images SHALL 为空列表，不返回随机图片

### Requirement: 制造 QA 保留引用溯源能力
QAEngine SHALL 使用 SourceTracer 从 AgenticRAG 输出中提取来源引用并评估可靠度。

#### Scenario: 提取来源引用
- **WHEN** AgenticRAG 返回包含 `[来源 N]` 标记的最终回答
- **THEN** SourceTracer SHALL 解析引用标记，关联到检索文档，返回结构化引用列表

#### Scenario: 无引用标记
- **WHEN** 回答不含任何 `[来源 N]` 标记
- **THEN** citations SHALL 为空列表，不强制要求引用

### Requirement: 推理轨迹输出
AgentResponse SHALL 包含 `trace` 字段，记录每一步推理的 thought、action、observation，供前端展示和调试。

#### Scenario: 包含推理轨迹
- **WHEN** AgenticRAG 完成多步推理
- **THEN** AgentResponse.trace SHALL 包含所有 ReasoningStep 记录，每步含 step_number、thought、action、observation、elapsed_ms

#### Scenario: 流式输出推理过程
- **WHEN** 用户通过 `/api/manufacturing/qa/stream` 发起流式问答
- **THEN** 系统 SHALL 在 ReAct 循环每步完成后即时发送 `{"type":"thinking","step":N,"thought":"...","action":"..."}` 事件，在 FINISH 步逐 token 发送 `{"type":"token","content":"..."}` 事件，流式体验与通用智能体一致

### Requirement: SearchTool 默认使用 RRF 检索模式
制造 QA 的 SearchTool SHALL 默认使用 `mode="rrf"` 进行检索，同时允许通过配置切换到其他模式。

#### Scenario: RRF 模式检索
- **WHEN** 制造 Agent 执行 search 工具
- **THEN** SearchTool SHALL 以 `mode="rrf"` 调用 `rag.aquery()`，三通道融合返回结果

#### Scenario: 模式可配置
- **WHEN** 智能体配置中 query_mode 设为 "hybrid"
- **THEN** SearchTool SHALL 以指定模式进行检索
