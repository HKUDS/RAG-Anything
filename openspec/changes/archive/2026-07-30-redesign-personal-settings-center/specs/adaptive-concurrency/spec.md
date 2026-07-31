## ADDED Requirements

### Requirement: Effective concurrency combines personal quota with global limits
The system SHALL resolve the personal concurrency choice against platform, provider, and worker hard limits and enforce the resulting effective quota through durable leases. Adaptive provider concurrency remains an outer constraint and SHALL not be mutated by a user's request.

#### Scenario: Adaptive provider cap lowers available user concurrency
- **WHEN** adaptive concurrency or a provider hard limit is lower than a user's saved quota
- **THEN** the resolver reports the lower effective limit and its constraint source without modifying the user's stored value
