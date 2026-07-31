## ADDED Requirements

### Requirement: RRF preparation and channels share one total deadline
The system SHALL execute scoped BM25 preparation as part of the BM25 channel
and start it concurrently with vector and graph channels.  BM25 preparation,
all enabled channels, and fusion MUST consume one absolute monotonic retrieval
deadline.  The effective channel timeout SHALL NOT exceed the remaining total
budget.

#### Scenario: Scoped BM25 is slow
- **WHEN** scoped BM25 requires PostgreSQL reads or an index build
- **THEN** vector and graph retrieval begin without waiting for that preparation
- **THEN** completed channels are fused when the total deadline expires

#### Scenario: A channel exceeds its remaining budget
- **WHEN** any enabled channel exceeds its effective timeout
- **THEN** the system records the timeout and excludes only that channel
- **THEN** successful channels remain eligible for RRF fusion

### Requirement: Scoped BM25 indexes are revision-keyed and single-flight
The system SHALL key scoped BM25 indexes by workspace, authoritative corpus
revision, tokenizer, k1, and b.  A cache hit for a supplied corpus revision
MUST NOT rescan document status or fetch chunks from PostgreSQL.  Concurrent
misses for the same key SHALL share one index build.

#### Scenario: Revision-keyed cache hit
- **WHEN** a query supplies a revision and matching BM25 configuration already exists
- **THEN** the system returns that index without PostgreSQL preparation work

#### Scenario: Concurrent same-key cache miss
- **WHEN** multiple queries miss the same scoped BM25 key
- **THEN** exactly one build is started
- **THEN** a requester timing out does not cancel the shared build for another requester
