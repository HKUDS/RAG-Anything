## ADDED Requirements

### Requirement: Hover highlight
The system SHALL visually highlight a node and its connected edges when the user hovers over it.

#### Scenario: Node hover
- **WHEN** the user hovers the cursor over a node
- **THEN** the hovered node SHALL enlarge to 1.5× its normal radius
- **AND** all directly connected edges SHALL increase in opacity to 1.0 and stroke-width to 2.5
- **AND** all non-connected nodes and edges SHALL reduce opacity to 0.15
- **AND** a tooltip SHALL appear showing the node's full name and type label

#### Scenario: Hover exit
- **WHEN** the cursor leaves a node
- **THEN** all visual properties SHALL return to their default state
- **AND** the tooltip SHALL disappear

### Requirement: Drag visual feedback
The system SHALL provide visual feedback during node dragging operations.

#### Scenario: Drag start
- **WHEN** the user starts dragging a node
- **THEN** the dragged node SHALL increase to 1.3× its normal radius
- **AND** the node SHALL gain a drop-shadow effect (svg filter)
- **AND** the cursor SHALL change to `grabbing`

#### Scenario: Drag end cooldown
- **WHEN** the user releases a dragged node
- **THEN** the node SHALL snap back to normal size over 200ms
- **AND** the shadow effect SHALL be removed
- **AND** the simulation SHALL enter cooldown (alphaTarget set to 0)

### Requirement: Responsive container
The system SHALL adapt the SVG canvas size to its parent container dimensions.

#### Scenario: Container resize
- **WHEN** the parent container changes width (window resize, sidebar toggle, etc.)
- **THEN** the SVG SHALL update its width/height to match the container
- **AND** the force center SHALL be updated to the new midpoint
- **AND** a ResizeObserver SHALL be used to monitor container dimension changes

#### Scenario: Minimum height
- **WHEN** the viewport height is small
- **THEN** the SVG SHALL maintain a minimum height of 350px
- **AND** the graph SHALL remain fully interactive (scrollable if needed)

### Requirement: Edge labels
The system SHALL display relationship type labels on edges connecting knowledge nodes.

#### Scenario: Edge label display
- **WHEN** edges are rendered between nodes
- **THEN** each edge SHALL display a small text label at its midpoint showing the Chinese label of the relationship type
- **AND** label text SHALL use font-size 8px with semi-transparent warm-gray color
- **AND** labels SHALL be positioned along the edge line
