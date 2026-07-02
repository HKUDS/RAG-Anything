## ADDED Requirements

### Requirement: Side panel opens on node click
The system SHALL display a side configuration panel when a node is clicked on the canvas.

#### Scenario: Click node to open config
- **WHEN** user clicks a node on the canvas
- **THEN** a right-side panel SHALL slide in showing the node's configuration form

#### Scenario: Close config panel
- **WHEN** user clicks the close button or clicks empty canvas area
- **THEN** the side panel SHALL close

### Requirement: Node-type-specific configuration forms
The system SHALL render different configuration fields based on the node type.

#### Scenario: Document input node config
- **WHEN** user clicks a document_input node
- **THEN** the panel SHALL show fields for file_type and max_size_mb

#### Scenario: LLM node config
- **WHEN** user clicks an llm_answer node
- **THEN** the panel SHALL show fields for model, temperature, and system_prompt

### Requirement: Config changes update node data in real-time
The system SHALL update the node's data immediately when configuration fields are changed.

#### Scenario: Change node label
- **WHEN** user edits the label field in the config panel
- **THEN** the node's display label on the canvas SHALL update in real-time

### Requirement: At least 6 built-in node types
The system SHALL predefine at least 6 node types: document_input, text_splitter, embedding, retriever, llm_answer, output.

#### Scenario: Node palette shows all 6 types
- **WHEN** the workflow page loads
- **THEN** the left node palette SHALL display all 6 node types with distinct icons and colors
