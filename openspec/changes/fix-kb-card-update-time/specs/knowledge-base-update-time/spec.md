## ADDED Requirements

### Requirement: Knowledge-base list provides a canonical update time
The `/kb/list` response SHALL provide `last_updated_at` for every visible
knowledge base. Its value SHALL be that KB's persisted generic update time, or
its creation time when no update time is available.

#### Scenario: Distinct resource updates
- **WHEN** two visible knowledge bases have different persisted update times
- **THEN** their `last_updated_at` values SHALL remain distinct in one list response

#### Scenario: Missing update time
- **WHEN** a knowledge base has no persisted update time
- **THEN** `last_updated_at` SHALL equal its creation time

### Requirement: Legacy list timestamp remains compatible
The `/kb/list` response SHALL retain `last_content_updated_at` and SHALL set it
to the same value as `last_updated_at`.

#### Scenario: Existing client field
- **WHEN** a client consumes `last_content_updated_at` from a list response
- **THEN** it SHALL receive the same ISO timestamp as `last_updated_at`

### Requirement: Cards and time sorting use the canonical update time
Knowledge-base cards and the knowledge-base time sort SHALL select
`last_updated_at`, then `last_content_updated_at`, then `created`.

#### Scenario: Canonical field is present
- **WHEN** a list item includes all three timestamps with different values
- **THEN** the card and time sort SHALL use `last_updated_at`

#### Scenario: Older response fallback
- **WHEN** a list item lacks `last_updated_at`
- **THEN** the card and time sort SHALL use `last_content_updated_at` before `created`
