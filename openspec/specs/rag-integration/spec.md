# RAG Integration

## Purpose

将智能制造专业智能体的 QA 引擎和故障诊断引擎与 RAG-Anything 检索引擎对接，实现真正的检索增强生成，并通过依赖注入模式保持模块独立性。

## Requirements

### Requirement: QA 引擎对接 RAG 检索
制造智能体 QA 端点 SHALL 通过 AgenticRAG 的 SearchTool 间接调用 RAG 检索引擎，而非直接调用 `LightRAG.aquery()` 或自定义 HybridSearchEngine。SearchTool 封装检索逻辑，Agent 在推理循环中自主决定何时检索、检索什么。

#### Scenario: Agent 自主检索决策
- **WHEN** 用户通过 `/api/manufacturing/qa` 发起文本问答
- **THEN** AgenticRAG SHALL 在 ReAct 循环中自主判断是否需要检索、检索几次，通过 SearchTool 调用 `rag.aquery(mode="rrf", only_need_context=True)` 获取上下文

#### Scenario: 流式回答
- **WHEN** 用户通过 `/api/manufacturing/qa/stream` 发起流式问答
- **THEN** 系统 SHALL 先通过 AgenticRAG 执行推理（含 SearchTool 检索），再通过 SSE 流式输出思考过程和最终回答

#### Scenario: 检索超时降级
- **WHEN** SearchTool 调用 RAG 检索耗时超过 `AGENT_TOOL_TIMEOUT` 秒（默认 30）
- **THEN** Agent SHALL 收到超时提示，可基于已有信息 FINISH 或尝试其他工具，不阻塞整个推理流程

### Requirement: 故障诊断引擎对接案例库
故障诊断引擎 SHALL 通过 FaultCaseLibrary 进行真实案例检索，替代当前的空案例库。

#### Scenario: 案例匹配诊断
- **WHEN** 用户发起故障诊断
- **THEN** 诊断引擎 SHALL 在 FaultCaseLibrary 中检索相似案例，基于匹配结果生成追问或诊断结论

#### Scenario: 案例库为空时的处理
- **WHEN** FaultCaseLibrary 中无任何案例
- **THEN** 诊断引擎 SHALL 告知用户"案例库暂无数据"，仅基于 LLM 知识提供通用建议并标注"仅供参考"

### Requirement: LLM 统一配置
制造智能体 LLM 配置 SHALL 复用服务器已有的 `LLM_BINDING_API_KEY`、`LLM_BINDING_HOST`、`LLM_MODEL` 环境变量，不要求额外配置。

#### Scenario: LLM 环境变量缺失
- **WHEN** 必需的环境变量未设置
- **THEN** 服务器启动 SHALL 打印警告日志，QA/诊断接口返回"LLM 服务未配置"错误
