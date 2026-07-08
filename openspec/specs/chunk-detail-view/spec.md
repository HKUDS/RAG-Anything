## ADDED Requirements

### Requirement: API returns document chunks detail

The system SHALL provide an API endpoint `GET /api/knowledge/documents/{doc_id}/chunks` that returns all chunks for a given document, sorted by `chunk_order_index` in ascending order.

Each chunk in the response SHALL include:
- `chunk_id`: the chunk identifier
- `content`: the chunk's full text content
- `tokens`: token count
- `chunk_order_index`: zero-based order within the document
- `file_path`: source file reference
- `is_multimodal`: boolean indicating if this is a multimodal chunk
- `original_type`: the multimodal content type (image/table/equation/video), or null for text chunks
- `page_idx`: source page number, or null
- `media_path`: extracted image/table path from chunk content, or null
- `media_url`: public URL if `RAGANYTHING_PUBLIC_ASSET_BASE_URL` is configured, or null

The endpoint SHALL require authentication and SHALL return 404 if the document does not exist.

#### Scenario: Successful chunks retrieval
- **WHEN** an authenticated user requests `GET /api/knowledge/documents/doc-abc/chunks`
- **AND** the document has 15 chunks in `doc_status.chunks_list`
- **THEN** the system returns a JSON array of 15 chunk objects sorted by `chunk_order_index`

#### Scenario: Document not found
- **WHEN** an authenticated user requests chunks for a non-existent document ID
- **THEN** the system returns HTTP 404

#### Scenario: Chunk ID in list but data missing
- **WHEN** a chunk ID in `chunks_list` does not exist in `text_chunks` storage
- **THEN** the system skips that chunk and returns the remaining chunks without error

### Requirement: Clickable chunk count in document list

The system SHALL render the chunk count in the document list table as a clickable element that opens the chunk detail panel.

#### Scenario: Click chunk count to open panel
- **WHEN** user clicks the chunk count number in a document row
- **THEN** the chunk detail panel opens for that document

#### Scenario: Chunk count visual affordance
- **WHEN** the document list renders
- **THEN** the chunk count SHALL be styled as a clickable button with hover and focus states distinct from plain text

### Requirement: Chunk detail drawer panel

The system SHALL display a right-side drawer panel when a chunk count is clicked, showing chunk details for the selected document.

The panel SHALL include:
- A header with the document name and close button
- A statistics summary row showing total chunk count and total token count
- A scrollable chunk list
- A text filter input for searching chunks by content
- "Expand All" and "Collapse All" buttons

The panel SHALL close when the user clicks the backdrop, the close button, or presses Escape.

#### Scenario: Open chunk detail panel
- **WHEN** user clicks a chunk count
- **THEN** a right-side drawer slides in showing the chunk list for that document

#### Scenario: Close panel via backdrop
- **WHEN** the chunk detail panel is open
- **AND** user clicks the semi-transparent backdrop area
- **THEN** the panel closes

#### Scenario: Close panel via Escape key
- **WHEN** the chunk detail panel is open
- **AND** user presses the Escape key
- **THEN** the panel closes

### Requirement: Chunk content expand and collapse

The system SHALL display each chunk as a collapsible row in the chunk list.

When collapsed, each row SHALL show:
- Chunk order index (starting from 1)
- Token count
- Page number (if available)
- Multimodal type badge (if applicable)
- A text preview of the chunk content truncated to 120 characters

When expanded, each row SHALL additionally show the full chunk content.

The first chunk SHALL be expanded by default. All other chunks SHALL be collapsed by default.

#### Scenario: Default state on panel open
- **WHEN** the chunk detail panel opens
- **THEN** the first chunk is expanded showing full content
- **AND** all other chunks are collapsed showing 120-character previews

#### Scenario: Toggle chunk expansion
- **WHEN** user clicks a collapsed chunk row
- **THEN** that chunk expands to show full content

#### Scenario: Expand all
- **WHEN** user clicks the "Expand All" button
- **THEN** all chunks in the list expand to show full content

#### Scenario: Collapse all
- **WHEN** user clicks the "Collapse All" button
- **THEN** all chunks in the list collapse to show previews only

### Requirement: Multimodal chunk display

The system SHALL distinguish multimodal chunks from text chunks with visual indicators.

For each multimodal chunk, the system SHALL:
- Display a type-specific icon (Image/Table/Equation/Video from lucide-react)
- Display the `modal_entity_name` as a label
- Display a thumbnail image if `media_path` or `media_url` is available, using the `/api/files/image` endpoint or public URL respectively
- Display the enhanced description text in the expanded view

For thumbnail loading failure, the system SHALL show a placeholder icon instead of a broken image.

#### Scenario: Image chunk with thumbnail
- **WHEN** a chunk has `is_multimodal: true` and `original_type: "image"`
- **AND** `media_path` points to an existing image file
- **THEN** the chunk row displays an image icon badge and a 120px thumbnail

#### Scenario: Table chunk display
- **WHEN** a chunk has `original_type: "table"`
- **THEN** the chunk row displays a table icon badge and a thumbnail if `media_path` is available

#### Scenario: Thumbnail load failure
- **WHEN** a multimodal chunk's thumbnail image fails to load
- **THEN** a placeholder type icon is displayed instead

### Requirement: Text filter for chunk search

The system SHALL provide a text input at the top of the chunk list that filters chunks by their content text.

Filtering SHALL be case-insensitive and SHALL match against the chunk `content` field. Only chunks whose content contains the filter text SHALL be displayed. The chunk count indicator SHALL update to show "showing N of M chunks" when a filter is active.

#### Scenario: Filter chunks by keyword
- **WHEN** user types "发动机" in the filter input
- **THEN** only chunks whose content contains "发动机" (case-insensitive) are displayed
- **AND** the display updates to show "showing 3 of 15 chunks"

#### Scenario: Clear filter
- **WHEN** user clears the filter input
- **THEN** all chunks are displayed again

#### Scenario: Empty filter result
- **WHEN** the filter text matches no chunks
- **THEN** an empty state message "没有匹配的切块" is displayed
