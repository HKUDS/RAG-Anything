## ADDED Requirements

### Requirement: Interactive query execution reuses a lease-protected core
The system SHALL execute interactive agent queries against a reusable,
lease-protected KB query core when KB name, workspace, corpus revision, storage
and index compatibility, and active visual-embedding profile fingerprint match.
The core MUST NOT be keyed by user, LLM/VLM selection, permission scope, or
retrieval settings.  Initialization SHALL be single-flight and MUST publish an
instance only after complete initialization succeeds.  Ingestion and retry
tasks SHALL retain their task-bound, uncached instance lifecycle.

#### Scenario: Consecutive compatible queries
- **WHEN** two interactive queries use the same compatible KB core
- **THEN** the second query reuses the initialized retrieval state
- **THEN** the first query's completion does not finalize that shared core

#### Scenario: Retiring core has an active request
- **WHEN** a corpus revision changes or the cache selects a leased core for eviction
- **THEN** new compatible queries acquire a replacement core
- **THEN** the retiring core is finalized only after its final lease releases

### Requirement: Request execution state is isolated
The system SHALL carry model selection, permission scope, retrieval options,
canonical retrieval fingerprint, result-cache scope, trace ID, KB/workspace,
captured corpus revision, and retrieval deadline as immutable request execution
state.  Shared query-core fields MUST NOT be mutated with any of those values.
Text LLM and VLM contextual profile resolution MUST fail closed when the
context is missing or its fingerprint is stale.

#### Scenario: Concurrent users select different profiles
- **WHEN** concurrent queries use different LLM profiles or retrieval options
- **THEN** they may share compatible retrieval state
- **THEN** each query invokes only its own selected model and cache namespace

### Requirement: Agent query phases are observable without content leakage
The system SHALL record monotonic phase timings for settings/quota, query-core
acquisition, retrieval, media, LLM, persistence, and total query execution.
Metrics SHALL use bounded labels and logs SHALL omit prompts, answers, user
data, local paths, credentials, and provider secrets.

#### Scenario: Query completes normally
- **WHEN** an agent query completes
- **THEN** phase timing events contain a trace ID, phase, outcome, cache status, and duration
- **THEN** no query content or secret-bearing configuration is emitted

### Requirement: Active media validation reuses the query reader
The system SHALL pass the active authorized chunk reader to controlled legacy
media validation when one is available.

#### Scenario: Legacy image is returned from an agent query
- **WHEN** media ownership validation requires chunk inspection
- **THEN** the validation reads from the active query core
- **THEN** it does not acquire a second KB instance
