## ADDED Requirements

### Requirement: Zoom in button
The system SHALL provide a functional zoom-in button that increases the graph magnification.

#### Scenario: Click zoom in
- **WHEN** the user clicks the zoom-in button
- **THEN** the graph SHALL zoom in by a factor of 1.5× relative to the current center
- **AND** the transition SHALL be smooth (animated over ~300ms)

### Requirement: Zoom out button
The system SHALL provide a functional zoom-out button that decreases the graph magnification.

#### Scenario: Click zoom out
- **WHEN** the user clicks the zoom-out button
- **THEN** the graph SHALL zoom out by a factor of 0.67× relative to the current center
- **AND** the transition SHALL be smooth (animated over ~300ms)
- **AND** the zoom SHALL be clamped to the minimum scale extent (0.2×)

### Requirement: Reset view button
The system SHALL provide a functional reset button that restores the graph to its initial fitted view.

#### Scenario: Click reset
- **WHEN** the user clicks the reset button after panning or zooming
- **THEN** the graph SHALL smoothly transition back to the initial fitted view showing all nodes
- **AND** the transition SHALL be animated over ~500ms

### Requirement: Auto-fit on data load
The system SHALL automatically fit the graph view to show all nodes when data first loads.

#### Scenario: Initial auto-fit
- **WHEN** graph data finishes loading and nodes are positioned
- **THEN** the view SHALL automatically scale and translate to fit all nodes within the visible SVG area
- **AND** a padding of 40px SHALL be maintained around the graph bounding box
