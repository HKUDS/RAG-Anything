## 1. 创建核心模块 `raganything/agentic_rag.py`

- [x] 1.1 创建 `raganything/agentic_rag.py`，定义 `Tool` 基类（name, description, parameters, async execute）
- [x] 1.2 定义 `AgentResult` 和 `ReasoningStep` 数据模型（step_number, thought, action, action_input, observation, elapsed_ms）
- [x] 1.3 实现 `AgenticRAG` 类：`tools: List[Tool]`、`max_steps: int`、`mode: "react" | "cot"`、`async run(query, kb_ids) → AgentResult`、`_parse_action(response) → (tool_name, tool_input)`

## 2. 实现 ReAct 推理循环

- [x] 2.1 实现 ReAct Prompt 构建：注入工具 schema、知识库上下文、Thought/Action/Observation 格式指令
- [x] 2.2 实现 ReAct 循环：LLM 调用 → `_parse_action()` 解析 → tool.execute() → 拼接 observation → 循环终止判断（Final Answer 或 max_steps 耗尽）
- [x] 2.3 实现 CoT 模式：逐步思考 prompt → LLM 多段输出 → 汇总 final answer
- [x] 2.4 实现单步 `asyncio.wait_for(timeout=30)` 超时控制 + 防御性解析（正则 fallback + 单次重试）

## 3. 实现内置工具

- [x] 3.1 实现 `SearchTool(Tool)`：封装 RAG 检索，参数 query + kb_ids
- [x] 3.2 实现 `CalculatorTool(Tool)`：四则运算安全求值，白名单 math 函数，禁 `__`/import/exec/open
- [x] 3.3 预留 `DatabaseQueryTool` 接口（类骨架 + 参数 schema，先返回"功能开发中"）

## 4. server.py 查询端点集成

- [x] 4.1 在 `server.py` `/api/query` 端点中添加 `agent_mode` 可选参数（"none" | "react" | "cot"）
- [x] 4.2 当 `agent_mode` 为 "react"/"cot" 时，初始化 AgenticRAG（注册 SearchTool + CalculatorTool）并执行 `run()`
- [x] 4.3 查询响应中附带 `reasoning_trace` JSON（仅 agent_mode 启用时）

## 5. 环境变量配置

- [x] 5.1 添加 `AGENT_MODE=react` 环境变量支持（可通过 .env 配置默认模式）
- [x] 5.2 添加 `AGENT_MAX_STEPS=5` 环境变量支持

## 6. MVP 验收测试

- [x] 6.1 测试 "去年销售额最高的产品是什么，比第二名高多少%" → Agent 自动分步检索+计算
- [x] 6.2 测试 max_steps=5 时不会无限循环（强制终止 + 返回中间结果）
- [x] 6.3 测试单工具调用超时 30s 后自动跳过（mock 延迟 35s），不中断推理
- [x] 6.4 测试不支持的问题明确告知用户（如"请帮我删除系统文件"）
