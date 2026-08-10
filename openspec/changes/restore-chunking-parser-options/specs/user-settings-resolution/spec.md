## MODIFIED Requirements

### Requirement: Settings options and section schemas are secret-free and bounded
`GET /api/users/me/settings/options` SHALL expose only permitted catalog choices and policy ranges, never provider hosts, keys, or environment names. The server SHALL validate the `models`, `ingestion`, `retrieval`, and `runtime` section schemas: models permit text LLM/VLM ids; ingestion permits parser, chunk strategy/size, image/table/equation/video toggles, entity types, and minimum relation degree; retrieval permits preset, RRF, channel Top K, graph depth, channels, BM25 tokenizer/k1/b; runtime permits LLM wait time and personal concurrency. `values:null` means remove exactly that section override. The options response SHALL include secret-free `parsers` and `chunking_strategies` catalogs: `parsers` SHALL list every supported parser id with installation availability; `chunking_strategies` SHALL list every supported strategy id with name, description, and cost metadata. Catalogs SHALL be projected per user section permissions (ingestion only) and SHALL be filtered by the platform `allowed.parsers`/`allowed.chunking_strategies` allow-lists: a non-empty allow-list restricts the catalog to its entries, an empty allow-list means no restriction and the full catalog is returned.

#### Scenario: Options are restricted by platform policy
- **WHEN** a user requests personal settings options
- **THEN** the response includes only allowed values and ranges applicable to that user and no private provider configuration

#### Scenario: Options expose the full parser and chunking strategy catalog when allow-lists are empty
- **WHEN** the platform policy has empty `parsers` and `chunking_strategies` allow-lists
- **THEN** the response includes all supported parser ids with `available` flags and all six strategy ids with metadata

#### Scenario: Options are restricted to a non-empty allow-list
- **WHEN** the platform policy restricts `chunking_strategies` to a subset such as `["recursive","fixed_size"]`
- **THEN** the response includes only that subset while an empty allow-list returns the full catalog

#### Scenario: Non-ingestion users receive no parser or chunking strategy catalog
- **WHEN** a user without ingestion section permission requests personal settings options
- **THEN** the response omits `parsers` and `chunking_strategies` catalogs

#### Scenario: Parser installation probe failure is surfaced as unavailable
- **WHEN** a parser's installation check raises or fails on the server
- **THEN** that parser appears in the catalog with `available=false` and the options request still succeeds
