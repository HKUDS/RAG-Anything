## MODIFIED Requirements

### Requirement: Personal settings present bounded model and retrieval controls
The AI section SHALL show current text/VLM profiles, actual model identifier, source, status, available candidates, and collapsed technical detail. The retrieval section SHALL offer balanced, precise, broad, and custom presets; custom SHALL reveal RRF, channel Top K, graph depth, channels, BM25 tokenizer/k1/b, and constraint state. Upload controls SHALL state that changes affect only subsequently started tasks. The upload/parsing section SHALL offer parser and chunking strategy selectors backed by the server catalog: every supported parser SHALL appear with uninstalled parsers disabled, and every supported chunking strategy (`fixed_size`, `recursive`, `sentence`, `structure`, `semantic`, `agentic`) SHALL appear using canonical ids; a non-empty platform allow-list SHALL restrict the visible choices and an empty allow-list SHALL show the full catalog. When the options request fails, the selectors SHALL fall back to a minimal usable set (`docling`; `recursive`/`fixed_size`) so the section remains editable.

#### Scenario: User selects a retrieval preset
- **WHEN** a user selects the precise preset
- **THEN** the page shows the preset's resolved retrieval values and their source before save

#### Scenario: User selects custom retrieval
- **WHEN** a user selects custom retrieval
- **THEN** all supported underlying retrieval controls become visible with effective constraints

#### Scenario: Personal settings list all six chunking strategies and installed parsers
- **WHEN** a user opens the upload/parsing section with empty platform allow-lists
- **THEN** the chunking strategy dropdown lists all six canonical strategies and the parser dropdown lists every supported parser with uninstalled ones disabled

#### Scenario: Options request fails while preferences is open
- **WHEN** the options request fails and the upload/parsing section is visible
- **THEN** the parser selector offers `docling` and the chunking strategy selector offers `recursive` and `fixed_size`, while account/theme/password sections remain usable

### Requirement: Upload panel chunking selector is always usable
The knowledge base upload panel SHALL load the chunking strategy catalog from the personal settings options response and SHALL render the strategy selector from that catalog; when the catalog is unavailable the selector SHALL show the built-in six-strategy presentation instead of remaining stuck on a loading state.

#### Scenario: Upload panel loads available chunking strategies
- **WHEN** a user opens the knowledge base upload panel and the options response is available
- **THEN** the chunking strategy selector shows the strategies from the server catalog

#### Scenario: Upload panel options request fails
- **WHEN** the options request fails while the upload panel is open
- **THEN** the chunking strategy selector falls back to the built-in six-strategy presentation and remains usable
#### Scenario: Legacy fixed chunking value is normalized
- **WHEN** a user previously saved the legacy chunking strategy value `fixed`
- **THEN** the selector shows and saves the canonical `fixed_size` value
