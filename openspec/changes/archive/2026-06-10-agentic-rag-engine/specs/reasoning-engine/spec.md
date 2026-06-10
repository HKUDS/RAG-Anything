## ADDED Requirements

### Requirement: ReAct Reasoning Loop
The system SHALL support ReAct (Reasoning + Acting) mode: Thought → Action → Observation → (判断是否充分) → Final Answer. Configurable via `AGENT_MODE=react` or `agent_mode="react"` parameter.

#### Scenario: Multi-step retrieval + calculation
- **WHEN** user asks "去年销售额最高的产品是什么，比第二名高多少%"
- **THEN** Agent SHALL autonomously search KB → retrieve data → calculate percentage → output Final Answer in ≥2 steps

#### Scenario: max_steps=5 terminates
- **WHEN** the ReAct loop reaches step 5 without Final Answer
- **THEN** return accumulated info with "推理达到最大步数限制" — never loop infinitely

#### Scenario: Tool timeout at 30s
- **WHEN** any tool execution exceeds 30 seconds
- **THEN** the tool SHALL be cancelled, observation writes "工具调用超时，已跳过", and loop continues

#### Scenario: Unsupported question
- **WHEN** the question cannot be answered even after exhausting tools and steps
- **THEN** the system SHALL explicitly tell the user "抱歉，当前无法回答此问题"

### Requirement: Chain-of-Thought Reasoning
The system SHALL support CoT mode: LLM performs step-by-step reasoning internally and produces a synthesized Final Answer without calling tools. Configurable via `AGENT_MODE=cot`.

#### Scenario: CoT for logical reasoning
- **WHEN** user asks a multi-step logic question with mode="cot"
- **THEN** the LLM produces internal reasoning steps and a final synthesized answer

### Requirement: Reasoning Mode Configuration
The system SHALL read `AGENT_MODE` env var (default "none") and `AGENT_MAX_STEPS` env var (default 5). Query endpoint `agent_mode` parameter overrides env var.

#### Scenario: Default mode preserves existing behavior
- **WHEN** AGENT_MODE is unset or "none", or agent_mode param is absent
- **THEN** the query executes as single-step RAG (unchanged)
