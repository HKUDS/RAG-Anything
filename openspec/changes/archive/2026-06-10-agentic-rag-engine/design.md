## Context

RAG-Anything 当前架构为**单轮 RAG**：用户问题 → 检索知识库 → LLM 生成回答。引入 Agentic RAG 在现有架构上叠加推理循环层。关键约束：
- **兼容性**：默认不传 `agent_mode` 时行为完全不变
- **工具安全**：Calculator 沙箱化，DBQuery 只读，WebSearch 限流
- **可扩展性**：Tool 基类支持注册自定义工具

## Goals / Non-Goals

**Goals:**
- 实现 ReAct 推理循环（Thought → Action → Observation），max_steps=5，单步超时 30s
- 实现 CoT 推理模式（Chain-of-Thought 逐步思考 → Final Answer）
- 通过 `AGENT_MODE` 环境变量切换 react/cot，通过 `AGENT_MAX_STEPS` 配置步数
- 提供 SearchTool、CalculatorTool、WebSearchTool、DatabaseQueryTool 四个工具
- Tool 基类抽象（name、description、parameters、async execute），支持注册自定义工具
- 推理过程可追溯、可序列化、前端可展示

**Non-Goals:**
- 不支持工具间并行调用（串行执行）
- 不支持文件系统写入工具
- 不引入 LangChain/LlamaIndex 等重框架
- MVP 先交付 2 步推理 + SearchTool + CalculatorTool，DatabaseQueryTool 预留接口

## Decisions

### D1: 推理循环架构 — 手写 ReAct/CoT Loop

**选择**：在 `raganything/agentic_rag.py` 中单文件实现。核心类：

```python
class AgenticRAG:
    tools: List[Tool]
    max_steps: int          # 默认 5
    mode: str              # "react" | "cot"

    async def run(self, query: str, kb_ids: list[str] | None = None) -> AgentResult: ...
    def _parse_action(self, response: str) -> tuple[str, dict]: ...
```

ReAct 循环示例：
```
Step 1: Thought → "需要检索年假相关政策"
        Action → search("年假政策")
        Observation → [检索到 5 个分段]
Step 2: Thought → "信息不够，需查具体天数"
        Action → search("年假天数 工龄")
        Observation → [检索到 3 个补充分段]
Step 3: Thought → "信息已足够"
        Action → finish("根据公司规定...")
```

CoT 模式：逐步思考 → 汇总回答，不调用外部工具。

**原因**：与 LangChain 相比手写代码约 250 行，零额外依赖，精确控制 prompt 格式和解析逻辑。

### D2: 工具抽象 — Tool 基类

```python
class Tool:
    name: str
    description: str
    parameters: dict       # JSON Schema

    async def execute(self, input: dict) -> str: ...
```

内置工具通过继承 Tool 实现，execute 返回字符串结果（超时由 AgenticRAG 框架用 asyncio.wait_for 控制）。

### D3: 环境变量配置

```bash
AGENT_MODE=react          # "react" | "cot" | "none"
AGENT_MAX_STEPS=5         # 默认 5
```

### D4: 查询端点集成 — server.py /api/query

**选择**：在现有 `/api/query` 端点新增 `agent_mode` 可选参数。不改 query.py 的内部逻辑。

```
POST /api/query
{
  "query": "...",
  "agent_mode": "react",     // 可选，"none" 默认
  "kb_ids": ["default"],     // 可选
}
Response: { "answer": "...", "reasoning_trace": {...} }
```

### D5: 推理轨迹

```python
class ReasoningStep(BaseModel):
    step_number: int
    thought: str
    action: str | None
    action_input: dict | None
    observation: str | None
    elapsed_ms: float

class AgentResult(BaseModel):
    answer: str
    trace: list[ReasoningStep]
    total_steps: int
    total_elapsed_ms: float
```

## Risks / Trade-offs

- **[R1] LLM 输出格式不可靠** → prompt 要求 JSON 格式，代码层正则 fallback + 单次重试
- **[R2] max_steps=5 耗尽** → 返回已收集信息 + "推理达到最大步数"，绝不无限循环
- **[R3] 工具超时 30s** → `asyncio.wait_for(30)`，超时跳过，Observation 写入"工具调用超时"
- **[R4] Calculator 安全** → 白名单求值，禁止 `__`/import/exec/open
- **[R5] Token 成本** → 多步推理约 2-5x，仅 agent_mode 显式启用时生效

## MVP Acceptance Criteria

- [ ] 输入"去年销售额最高的产品是什么，比第二名高多少%" → Agent 自动分步检索+计算
- [ ] max_steps=5 时不会无限循环
- [ ] 单工具调用超时 30s 后自动跳过
- [ ] 不支持的问题明确告知用户
