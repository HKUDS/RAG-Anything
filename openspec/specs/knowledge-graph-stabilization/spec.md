## ADDED Requirements

### Requirement: Force simulation stabilization
The system SHALL automatically stop the D3 force simulation when the layout has stabilized, eliminating perpetual node bouncing.

#### Scenario: Simulation auto-stop
- **WHEN** the force simulation alpha drops below 0.02
- **THEN** the system SHALL call `simulation.stop()` to halt the simulation
- **AND** nodes SHALL remain fixed at their final positions

#### Scenario: Cooling parameters
- **WHEN** the force simulation is initialized
- **THEN** the system SHALL configure `alphaDecay` to 0.0228 (D3 default, ~300 iterations)
- **AND** the system SHALL configure `alphaMin` to 0.001

#### Scenario: Dragging triggers controlled restart
- **WHEN** a user drags a node
- **THEN** the simulation SHALL restart with `alphaTarget(0.3)`
- **AND** upon drag end the simulation SHALL set `alphaTarget(0)` to begin cooling
- **AND** the simulation SHALL auto-stop again when alpha drops below 0.02

### Requirement: Consistent initial layout
The system SHALL produce a consistent, centered initial layout for the knowledge graph on each load.

#### Scenario: Fixed seed
- **WHEN** the same graph data is loaded
- **THEN** nodes SHALL appear at reproducible initial positions between renders
- **AND** the layout SHALL be centered around the SVG midpoint
