## ADDED Requirements

### Requirement: Tool Base Class
The system SHALL provide a `Tool` class with `name: str`, `description: str`, `parameters: dict` (JSON Schema), and `async execute(input: dict) -> str` method.

#### Scenario: Implement a built-in tool
- **WHEN** a developer subclasses Tool and implements async execute()
- **THEN** the tool can be registered and called by AgenticRAG

#### Scenario: Execute returns string
- **WHEN** a tool's execute() completes
- **THEN** it SHALL return a string result (success content or error message)

### Requirement: Tool Registration in AgenticRAG
The `AgenticRAG` class SHALL maintain `tools: List[Tool]` and expose `register_tool(tool: Tool)`.

#### Scenario: Register and call tools
- **WHEN** tools are registered via register_tool()
- **THEN** AgenticRAG can enumerate them and inject their schemas into the ReAct prompt

### Requirement: Tool Execution Timeout
Every tool execution SHALL be wrapped with `asyncio.wait_for(timeout=30)`. On timeout, the tool call SHALL be cancelled and return "工具调用超时，已跳过".

#### Scenario: Tool exceeds 30s
- **WHEN** a tool takes >30 seconds
- **THEN** it is cancelled and the ReAct loop continues to the next step
