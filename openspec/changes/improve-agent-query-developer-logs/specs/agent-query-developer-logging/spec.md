## ADDED Requirements

### Requirement: Interactive agent query terminal journey summary
The system SHALL emit exactly one `QUERY_JOURNEY` INFO record when an
interactive agent query reaches its terminal timing close.  The record SHALL
include the trace identifier, terminal outcome, total elapsed milliseconds,
and an ordered compact representation of all completed timing stages.

#### Scenario: Successful query includes retrieval and generation stages
- **WHEN** an interactive agent query records retrieval, media, LLM, and
  persistence timing stages and then completes successfully
- **THEN** the terminal log SHALL contain one `QUERY_JOURNEY` record for its
  trace identifier with terminal outcome `ok`
- **THEN** the ordered stages SHALL retain each stage's bounded channel,
  outcome, cache status, and elapsed duration in fixed lifecycle and retrieval
  channel order

#### Scenario: Terminal failure still produces a diagnostic summary
- **WHEN** an interactive agent query ends with `error`, `timeout`, or
  `cancelled`
- **THEN** the terminal log SHALL contain one `QUERY_JOURNEY` record with that
  terminal outcome and all stages completed before termination

### Requirement: Query journey summaries preserve diagnostic privacy
The system SHALL build query journey summaries only from the trace identifier,
bounded timing labels, counts, and elapsed durations.  It SHALL NOT include
raw query text, rewritten query text, prompts, model output, retrieved content,
document names, paths, user identifiers, credentials, or exception messages.

#### Scenario: Sensitive query content is absent from summary logs
- **WHEN** a caller creates and completes timing for an interactive query whose
  query text or document data contains a unique sensitive marker
- **THEN** the `QUERY_JOURNEY` record SHALL not contain that marker

### Requirement: Existing timing observability remains compatible
The system SHALL continue emitting existing `QUERY_TIMING` records and
observing the existing Prometheus phase metric for every timing stage and
terminal total.

#### Scenario: Existing phase record remains available
- **WHEN** a query timing stage finishes
- **THEN** the system SHALL emit its existing `QUERY_TIMING` record and observe
  the existing phase duration metric in addition to including it in the
  terminal journey summary

### Requirement: Query journey terminal logging is idempotent
The system SHALL emit no more than one terminal `QUERY_JOURNEY` record and no
more than one terminal `QUERY_TIMING` total record for a `QueryTiming` instance,
including when cleanup invokes `total()` more than once.

#### Scenario: Duplicate terminal close does not duplicate terminal logs
- **WHEN** a caller invokes `total()` twice for the same timing instance
- **THEN** the system SHALL preserve the elapsed duration from the first close
- **THEN** the system SHALL emit exactly one terminal `QUERY_JOURNEY` record and
  exactly one terminal `QUERY_TIMING` total record
