## MODIFIED Requirements

### Requirement: Frontend defers KB data loading until ownership is confirmed
The knowledge base page frontend SHALL NOT request any knowledge-base-scoped data (documents, stats, entities, graph) until the user's KB list has been successfully fetched and the active KB has been confirmed to belong to the user. The same confirmed-identity rule SHALL apply to AutoRepair KB-scoped graph, QA, diagnosis, and code-parse requests; an empty, failed, or forbidden KB list MUST leave the active KB unset rather than fabricating a default name.

#### Scenario: KnowledgePage mounts for the first time
- **WHEN** the KnowledgePage component mounts
- **THEN** it SHALL first call `/api/kb/list` and await the response before making any KB-scoped data calls (documents, stats, entities, graph)

#### Scenario: KB data loading uses confirmed active KB
- **WHEN** `loadKBData()` executes
- **THEN** the `activeKB` value used SHALL have been derived from the `/api/kb/list` response and confirmed present in the user's KB list, never from a hardcoded default

#### Scenario: AutoRepair KB list has no accessible entries
- **WHEN** `/api/autorepair/kb-list` returns an empty list, a forbidden response, or a network failure
- **THEN** the frontend SHALL clear any stale selected KB, leave the active KB unset, show a neutral empty/error state, and issue no KB-scoped graph, QA, diagnosis, or code-parse request

### Requirement: Module-level KB state validates before use
The frontend module-level `currentKB` state SHALL validate that the KB name is non-empty and exists in the user's KB list before appending it to any API request URL. Requests with an unconfirmed or empty KB name SHALL NOT be dispatched. AutoRepair selectors and callers SHALL use one consistent selected-KB prop and SHALL not restore a stale value that is absent from the confirmed list.

#### Scenario: API request with uninitialized KB state
- **WHEN** an API call is made before `currentKB` has been set to a confirmed user-owned KB
- **THEN** the request SHALL be skipped or deferred, not dispatched with a hardcoded or stale KB name

#### Scenario: Stored AutoRepair KB is no longer accessible
- **WHEN** local storage contains a KB name that is absent from the current `/api/autorepair/kb-list` response
- **THEN** the stored value SHALL be removed or replaced only after a confirmed accessible item exists, and no request SHALL use the stale name
