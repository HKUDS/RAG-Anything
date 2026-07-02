## ADDED Requirements

### Requirement: Save workflow
The system SHALL persist workflow definitions as JSON files via a backend API.

#### Scenario: Save new workflow
- **WHEN** user clicks save in the toolbar with a new workflow
- **THEN** a POST request SHALL create the workflow and return the saved definition with an ID

#### Scenario: Update existing workflow
- **WHEN** user clicks save on an already-saved workflow
- **THEN** a PUT request SHALL update the existing workflow definition

### Requirement: List and load workflows
The system SHALL allow users to browse saved workflows and load them onto the canvas.

#### Scenario: Load saved workflow
- **WHEN** user selects a workflow from the load dialog and clicks open
- **THEN** the canvas SHALL display the saved nodes and edges

### Requirement: Delete workflow
The system SHALL allow users to delete a saved workflow.

#### Scenario: Delete workflow
- **WHEN** user selects delete on a workflow in the load dialog
- **THEN** the workflow file SHALL be removed and no longer appear in the list

### Requirement: Navigation entry point
The system SHALL add a "工作流" navigation item in the main navigation bar.

#### Scenario: Navigate to workflow page
- **WHEN** user clicks "工作流" in the top navigation bar
- **THEN** the workflow page with the DAG canvas SHALL load
