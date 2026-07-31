## ADDED Requirements

### Requirement: Quota lease survives an owner-local heartbeat delay
The system SHALL allow a quota lease owner to renew its own lease after its stored expiry when the lease row has not been reclaimed or replaced.

#### Scenario: Worker bootstrap delays heartbeat
- **WHEN** a worker owns a quota lease and synchronous bootstrap delays its event loop past the lease TTL
- **AND** no other worker has reclaimed the lease row
- **THEN** the worker's next heartbeat SHALL renew the same lease and processing SHALL continue

#### Scenario: Expired lease has been reclaimed
- **WHEN** a worker's quota lease has expired
- **AND** a later acquisition has removed or replaced that lease for another owner
- **THEN** the former owner's heartbeat SHALL fail and SHALL NOT renew or modify the newer lease

### Requirement: Lease loss is an actionable worker failure
The system SHALL classify a worker cancelled because its quota lease was actually lost as a retryable quota-stage failure.

#### Scenario: Current lease owner loses its row
- **WHEN** the worker heartbeat cannot renew the exact owner-matched quota lease
- **THEN** the worker SHALL exit with a retryable structured error containing `stage` `quota`, `root_type` `QuotaLeaseLost`, and a `quota_lease_lost` failure code

#### Scenario: External cancellation is preserved
- **WHEN** the worker receives cancellation without a recorded quota lease loss
- **THEN** the worker SHALL preserve the cancellation rather than misclassifying it as a quota failure
