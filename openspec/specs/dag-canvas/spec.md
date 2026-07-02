## ADDED Requirements

### Requirement: DAG canvas with drag-and-drop node placement
The system SHALL provide a visual canvas where users can drag nodes from a palette onto the canvas to create workflow nodes.

#### Scenario: Drag node from palette to canvas
- **WHEN** user drags a node type from the left palette onto the canvas
- **THEN** a new node of that type SHALL appear at the drop position with default configuration

#### Scenario: Move node on canvas
- **WHEN** user drags an existing node to a new position
- **THEN** the node SHALL move to the new position and connected edges SHALL follow

### Requirement: Edge creation between nodes
The system SHALL allow users to create directed edges between nodes by dragging from a source node's output handle to a target node's input handle.

#### Scenario: Connect two nodes
- **WHEN** user drags from the output handle of node A to the input handle of node B
- **THEN** a directed edge SHALL be created from A to B

#### Scenario: Delete edge
- **WHEN** user selects an edge and presses Delete or Backspace
- **THEN** the edge SHALL be removed from the canvas

### Requirement: Canvas interaction (zoom, pan, minimap)
The system SHALL support zoom (scroll), pan (drag background), and display a minimap for navigation.

#### Scenario: Zoom with mouse wheel
- **WHEN** user scrolls the mouse wheel on the canvas
- **THEN** the canvas SHALL zoom in or out centered on the cursor position

#### Scenario: Minimap navigation
- **WHEN** the canvas contains nodes outside the visible area
- **THEN** a minimap SHALL show an overview with a draggable viewport indicator

### Requirement: Node deletion
The system SHALL allow users to delete selected nodes and their connected edges.

#### Scenario: Delete selected node
- **WHEN** user selects a node and presses Delete or Backspace
- **THEN** the node and all its connected edges SHALL be removed

### Requirement: Auto-layout
The system SHALL provide an auto-layout button that rearranges nodes using a directed graph layout algorithm.

#### Scenario: Apply auto-layout
- **WHEN** user clicks the auto-layout button in the toolbar
- **THEN** all nodes SHALL be repositioned in a top-to-bottom directed layout
