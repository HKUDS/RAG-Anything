## MODIFIED Requirements

### Requirement: Personal settings center isolates section lifecycle
`/preferences` SHALL provide only the AI model, upload/parsing, retrieval, and
runtime sections available to the authenticated user's live capabilities, plus
appearance, account profile, and password/security sections. Each editable
section SHALL distinguish stored value, effective value, source, and constraint
and SHALL retain independent load, save, rollback, restore-inheritance, and
error behavior. Model-catalog failure MUST NOT block account, theme, or password
controls, and unavailable model sections MUST NOT trigger a catalog request.

#### Scenario: Model catalog failure leaves account settings usable
- **WHEN** the model-options request fails while a model-authorized user has
  preferences open
- **THEN** the AI model section shows its local error and account, theme, and
  password sections remain interactive

#### Scenario: User restores a retrieval override
- **WHEN** a user with `kb:write` chooses restore inheritance in the retrieval
  section
- **THEN** the client PATCHes null section values and shows the inherited
  effective values and sources returned by the API

#### Scenario: Failed section save rolls back locally
- **WHEN** a section PATCH fails validation, conflict, or network transport
- **THEN** the client retains the last confirmed stored/effective state and
  leaves unrelated available sections usable

#### Scenario: Permission changes while preferences is open
- **WHEN** a section save returns 403 or the available-section list no longer
  includes a mounted section
- **THEN** the client removes that section and its draft, reloads the projected
  settings state, and recovers its active hash to a visible section

### Requirement: Personal settings present bounded model and retrieval controls
The AI section SHALL show current text/VLM profiles, actual model identifier,
source, status, available candidates, and collapsed technical detail only to a
user with `agent:write`. The retrieval section SHALL offer balanced, precise,
broad, and custom presets only to a user with `kb:write`; custom SHALL reveal
RRF, channel Top K, graph depth, channels, BM25 tokenizer/k1/b, and constraint
state. Upload controls SHALL state that changes affect only subsequently started
tasks and SHALL be available only with `kb:write`.

#### Scenario: User selects a retrieval preset
- **WHEN** a user with `kb:write` selects the precise preset
- **THEN** the page shows the preset's resolved retrieval values and their
  source before save

#### Scenario: User selects custom retrieval
- **WHEN** a user with `kb:write` selects custom retrieval
- **THEN** all supported underlying retrieval controls become visible with
  effective constraints

#### Scenario: Student opens personal settings
- **WHEN** a user lacks `kb:write` and `agent:write`
- **THEN** the page does not render models, upload/parsing, retrieval, or
  runtime controls or their technical state
