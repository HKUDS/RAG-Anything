## MODIFIED Requirements

### Requirement: AgentConfig reasoning_mode field
The AgentConfig model SHALL include `reasoning_mode: str = "none"`. Accepted values: `"none"`, `"react"`, `"cot"`.

#### Scenario: Default mode
- **WHEN** AgentConfig created without reasoning_mode → defaults to "none"

#### Scenario: ReAct mode
- **WHEN** reasoning_mode="react" → queries route through AgenticRAG ReAct loop

#### Scenario: CoT mode
- **WHEN** reasoning_mode="cot" → queries route through AgenticRAG CoT loop

### Requirement: AgentConfig max_steps field
The AgentConfig model SHALL include `max_steps: int = 5`, valid range 1-20. Configurable via `AGENT_MAX_STEPS` env var.

### Requirement: AgentConfig enabled_tools field
The AgentConfig model SHALL include `enabled_tools: list[str] = []`. Accepted values: `"search"`, `"calculator"`, `"web_search"`, `"database_query"`.
