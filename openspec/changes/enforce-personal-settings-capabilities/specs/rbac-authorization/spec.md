## ADDED Requirements

### Requirement: Personal settings section endpoints enforce capabilities
The settings API SHALL derive section access from the authenticated user's live
permissions. `models` requires `agent:write`; `ingestion`, `retrieval`, and
`runtime` require `kb:write`. Reading personal settings SHALL project only
permitted task sections and return their ordered names as `available_sections`.
PATCHing a denied section and reading or writing a legacy personal VLM
preference without `agent:write` MUST return 403.

#### Scenario: Student reads personal settings
- **WHEN** a user lacks `kb:write` and `agent:write`
- **THEN** the API returns an empty `available_sections` list and omits all
  task sections from stored, effective, sources, constraints, and options

#### Scenario: Assistant writes a model setting
- **WHEN** a user has `kb:write` but lacks `agent:write` and PATCHes `models`
- **THEN** the API returns 403 before changing the stored settings row
