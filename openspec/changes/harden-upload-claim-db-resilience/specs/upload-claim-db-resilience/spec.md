## ADDED Requirements

### Requirement: Claim-aware persistence distinguishes outages from fencing
The system SHALL re-raise transient PostgreSQL connection failures from claim-aware state updates and SHALL return `None` only when a successful owner/generation-qualified SQL update affects zero rows.

#### Scenario: Database connection is interrupted
- **WHEN** a claim-aware update encounters an `OSError` or asyncpg connection failure
- **THEN** the exception propagates to the worker supervision path and the task is not classified as `upload_claim_lost`

#### Scenario: Claim is fenced by another owner
- **WHEN** the SQL command succeeds and the qualified `UPDATE` affects zero rows
- **THEN** the caller immediately stops the old worker and records an ownership-loss outcome

### Requirement: Heartbeat grace is bounded by durable fencing
Upload heartbeats SHALL run every 15 seconds and tolerate no more than 180 seconds of consecutive database failures; KB mutation leases SHALL use a 300-second TTL and enforce `grace + heartbeat_interval < lease_ttl`.

#### Scenario: Short outage recovers
- **WHEN** PostgreSQL is unreachable for less than the grace period and then recovers
- **THEN** the existing worker continues with its original owner and generation

#### Scenario: Grace expires
- **WHEN** PostgreSQL remains unreachable beyond the grace period
- **THEN** the worker is terminated once, in-memory registrations are cleaned, and durable stale recovery remains authoritative

### Requirement: Recovery is provenance-scoped and idempotent
The system SHALL use the original task, file hash, owner, and generation for retry recovery and SHALL clean existing residual chunks, media, entities, and relations before reprocessing.

#### Scenario: Owner changes during outage
- **WHEN** a different owner or generation is committed
- **THEN** the old worker exits immediately and cannot perform late status or data writes

#### Scenario: Database remains unavailable at grace expiry
- **WHEN** the worker is stopped but PostgreSQL cannot accept the recovery update
- **THEN** processing state is retained for the five-minute stale scanner to recover

### Requirement: Background loops back off uniformly
Upload retry, durable queue scanning, terminal tag reconciliation, and automatic tag claiming SHALL use capped exponential backoff up to 60 seconds and reset the delay after success.

#### Scenario: Reconciliation outage recovers
- **WHEN** terminal tag reconciliation fails repeatedly and then succeeds
- **THEN** the loop increases its delay while failing and logs one recovery INFO before returning to its base interval

### Requirement: PostgreSQL pool startup uses supported asyncpg options
The system SHALL create its PostgreSQL pool using connection and pool options supported by the configured asyncpg version, including `timeout=10`, `command_timeout=30`, and `max_inactive_connection_lifetime=300`.

#### Scenario: Service initializes the shared pool
- **WHEN** the server or worker initializes the shared PostgreSQL pool
- **THEN** pool creation does not pass unsupported `connection_timeout` or `tcp_keepalive` keyword arguments to `asyncpg.connect`
