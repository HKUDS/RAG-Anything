## ADDED Requirements

### Requirement: Authorized video time citation

Query and SSE citation payloads SHALL optionally include `video_segment` data
with `segment_id`, `start_ms`, `end_ms`, parent document identity, `media_id`,
`media_kb`, and a controlled media URL. The URL MUST be issued only after the
existing KB permission check, MUST NOT contain a local absolute path, and MUST
support HTTP Range requests.

#### Scenario: Authorized segment citation

- **WHEN** a retrieved chunk belongs to a video segment and the caller has
  `kb:read`
- **THEN** the citation MUST include its start/end time, `media_id`, `media_kb`,
  and a usable controlled media reference

#### Scenario: Unauthorized segment citation

- **WHEN** the caller lacks access to the parent knowledge base
- **THEN** the API MUST return the existing authorization failure and MUST NOT
  disclose the media URL, path, or timing metadata

#### Scenario: Range and expired media handling

- **WHEN** a client requests a permitted media URL with a valid Range header
- **THEN** the endpoint MUST return the corresponding partial content
- **AND** expired or missing media MUST return a controlled 404/410 without a
  filesystem path

### Requirement: Segment-aware retrieval presentation

The query pipeline SHALL deduplicate video results by parent document while
retaining adjacent relevant segments, and the frontend SHALL render a compact
time-range action that seeks the protected video source to the segment start.

#### Scenario: Adjacent segments

- **WHEN** multiple adjacent segments from one video are retrieved
- **THEN** the response MUST preserve their order and avoid duplicate parent
  entries while retaining their distinct time ranges

#### Scenario: Playback action

- **WHEN** a user activates a video citation time range
- **THEN** the frontend MUST open the controlled source and seek to
  `start_ms / 1000` without exposing the server path
- **AND** a 403, 404, or Range failure MUST render an actionable inline error
