## ADDED Requirements

### Requirement: Personal settings center isolates section lifecycle
`/preferences` SHALL provide AI model, upload/parsing, retrieval, runtime, appearance, account profile, and password/security sections with independent load, save, rollback, restore-inheritance, and error behavior. Each editable section SHALL distinguish stored value, effective value, source, and constraint; model-catalog failure MUST NOT block account, theme, or password controls.

#### Scenario: Model catalog failure leaves account settings usable
- **WHEN** the model-options request fails while preferences is open
- **THEN** the AI model section shows its local error and account/theme/password sections remain interactive

#### Scenario: User restores a retrieval override
- **WHEN** a user chooses restore inheritance in the retrieval section
- **THEN** the client PATCHes null section values and shows the inherited effective values and sources returned by the API

#### Scenario: Failed section save rolls back locally
- **WHEN** a section PATCH fails validation, conflict, or network transport
- **THEN** the client retains the last confirmed stored/effective state and leaves unrelated sections usable

### Requirement: Personal settings present bounded model and retrieval controls
The AI section SHALL show current text/VLM profiles, actual model identifier, source, status, available candidates, and collapsed technical detail. The retrieval section SHALL offer balanced, precise, broad, and custom presets; custom SHALL reveal RRF, channel Top K, graph depth, channels, BM25 tokenizer/k1/b, and constraint state. Upload controls SHALL state that changes affect only subsequently started tasks.

#### Scenario: User selects a retrieval preset
- **WHEN** a user selects the precise preset
- **THEN** the page shows the preset's resolved retrieval values and their source before save

#### Scenario: User selects custom retrieval
- **WHEN** a user selects custom retrieval
- **THEN** all supported underlying retrieval controls become visible with effective constraints

### Requirement: Platform administration and legacy settings navigation are separated
`/admin/platform` SHALL require platform settings read permission for viewing and write permission for edits, and SHALL not render provider host/key data. The legacy `/settings` route SHALL redirect authenticated users with `settings:read` to `/admin/platform` and all other authenticated users to `/preferences`; legacy settings API responses SHALL include a deprecation header during the compatibility version.

#### Scenario: Administrator opens legacy settings route
- **WHEN** an administrator navigates to `/settings`
- **THEN** the client redirects to `/admin/platform`

#### Scenario: Editor opens legacy settings route
- **WHEN** an editor without `settings:read` navigates to `/settings`
- **THEN** the client redirects to `/preferences`
