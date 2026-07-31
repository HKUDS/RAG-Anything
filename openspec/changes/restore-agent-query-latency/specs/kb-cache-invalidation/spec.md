## ADDED Requirements

### Requirement: Cached query-core invalidation is lease-aware
The system SHALL treat an invalidated or evicted cached KB query core as
retiring while it has active query leases.  It MUST remove retiring cores from
new acquisition, create a compatible replacement when required, and finalize a
retiring core once after all leases release.

#### Scenario: Corpus update during an active query
- **WHEN** a corpus revision invalidates a cached core while an agent query uses it
- **THEN** the active query can complete with its acquired core
- **THEN** the next query does not acquire that stale core

#### Scenario: Cache pressure with active cores
- **WHEN** cache capacity is reached and every eviction candidate has an active lease
- **THEN** the cache temporarily retains the active entries
- **THEN** it converges to its configured capacity after leases release
