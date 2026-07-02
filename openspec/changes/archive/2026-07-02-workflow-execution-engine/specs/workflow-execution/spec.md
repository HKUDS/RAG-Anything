## ADDED Requirements

### Requirement: Run workflow via API
The system SHALL provide a POST endpoint to execute a saved workflow by its ID.

#### Scenario: Execute a valid workflow
- **WHEN** user sends POST `/api/workflows/{id}/run`
- **THEN** the system SHALL validate the DAG, create a run record, and start executing nodes in topological order

#### Scenario: Reject workflow with cycles
- **WHEN** the workflow DAG contains a cycle
- **THEN** the system SHALL return a 400 error with "Workflow contains a cycle"

### Requirement: Node execution in topological order
The system SHALL execute nodes one at a time in topological sort order, passing each node's output as input to downstream nodes.

#### Scenario: Three-node linear workflow
- **WHEN** a workflow has nodes A→B→C
- **THEN** the system SHALL execute A first, then B (receiving A's output), then C (receiving B's output)

### Requirement: Real-time status via WebSocket
The system SHALL push node execution status changes to connected WebSocket clients.

#### Scenario: Node status transitions
- **WHEN** a node starts executing, completes, or fails
- **THEN** the WebSocket SHALL send a message with the node ID and new status

### Requirement: Error handling
The system SHALL skip downstream nodes when a node fails, and mark the run as failed.

#### Scenario: Mid-pipeline failure
- **WHEN** node B fails during execution
- **THEN** downstream nodes C and D SHALL be skipped, and the overall run status SHALL be "failed"

### Requirement: Run history
The system SHALL persist run results to disk and allow listing past runs for a workflow.

#### Scenario: List runs for a workflow
- **WHEN** user sends GET `/api/workflows/{id}/runs`
- **THEN** the system SHALL return a list of past runs with status, timestamps, and final output
