## ADDED Requirements

### Requirement: Structured Trace Recording
The system SHALL record each reasoning step as a `ReasoningStep` object containing step_number, thought, action (optional), action_input (optional), observation (optional), and elapsed_ms.

#### Scenario: ReAct trace with tool call
- **WHEN** a ReAct query calls the Calculator tool at step 2
- **THEN** the ReasoningStep for step 2 SHALL include thought, action="calculator", action_input, observation, and elapsed_ms

#### Scenario: CoT trace without tools
- **WHEN** a CoT query produces 3 reasoning steps
- **THEN** each ReasoningStep SHALL have thought text and action=None

### Requirement: Trace Serialization
The system SHALL serialize the full `ReasoningTrace` (including all steps and final answer) as JSON for API responses and frontend consumption.

#### Scenario: API response includes trace
- **WHEN** an agentic query completes
- **THEN** the API response SHALL include a JSON field "reasoning_trace" with all steps and metadata

#### Scenario: Trace persistence
- **WHEN** a query is saved to conversation history
- **THEN** the reasoning trace SHALL be serialized and stored alongside the message

### Requirement: Trace Metadata
Each ReasoningTrace SHALL include mode ("react" or "cot"), total_elapsed_ms, and a unique trace_id.

#### Scenario: Trace metadata present
- **WHEN** any agentic query completes
- **THEN** the trace object SHALL contain trace_id, mode, total_elapsed_ms, and the list of steps
