## ADDED Requirements

### Requirement: Run button in toolbar
The system SHALL display a "Run" button in the workflow toolbar when nodes are present on the canvas.

#### Scenario: Run button visible with nodes
- **WHEN** the canvas has one or more nodes
- **THEN** a "▶ 运行" button SHALL be visible in the toolbar

#### Scenario: Run button hidden when empty
- **WHEN** the canvas has zero nodes
- **THEN** the run button SHALL be disabled or hidden

### Requirement: Node status color during execution
The system SHALL change the visual appearance of nodes based on their execution status.

#### Scenario: Node colors during run
- **WHEN** a workflow is running
- **THEN** pending nodes SHALL show white, running nodes blue, completed nodes green, and failed nodes red

### Requirement: Output panel
The system SHALL display a collapsible bottom panel showing the final output of a completed workflow run.

#### Scenario: Panel shows after run completes
- **WHEN** a workflow run completes successfully
- **THEN** a bottom panel SHALL automatically open showing the formatted output

### Requirement: Run history in output panel
The system SHALL allow users to view past run results from the output panel.

#### Scenario: Switch between run results
- **WHEN** the output panel is open and user selects a past run from the dropdown
- **THEN** the panel SHALL display that run's node results and final output
