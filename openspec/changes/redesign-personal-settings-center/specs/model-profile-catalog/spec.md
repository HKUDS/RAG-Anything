## ADDED Requirements

### Requirement: Public model profile catalog is sanitized and availability-aware
The system SHALL compose configured OpenAI-compatible LLM/VLM and supported Doubao multimodal embedding profiles from server-owned catalog files and legacy deployment configuration. The public profile DTO SHALL include only `id`, `kind`, display metadata, provider/model identity, capabilities, embedding dimension, availability, and unavailable reason; it MUST NOT include host, API-key environment variable, credentials, timeout, or concurrency fields.

#### Scenario: List configured available VLM profiles
- **WHEN** an authenticated user requests `GET /api/model-profiles?kind=vlm`
- **THEN** the system returns only configured VLM public profile DTOs with availability state and no secret/private field

#### Scenario: Unsupported profile is visible but unavailable
- **WHEN** a configured profile lacks a usable adapter or required deployment configuration
- **THEN** the profile is returned with `available=false` and a non-secret unavailable reason

### Requirement: Catalog probing is administrator-controlled
The system SHALL expose `POST /api/admin/model-profiles/{id}/probe` only to callers with platform settings write permission and SHALL audit the profile id and outcome without recording connection secrets.

#### Scenario: Authorized profile probe
- **WHEN** a user with `settings:write` probes a configured profile
- **THEN** the system invokes its server-side adapter and returns a sanitized availability result

#### Scenario: Unauthorized profile probe
- **WHEN** a user lacking `settings:write` probes a profile
- **THEN** the system returns 403 without contacting the provider

### Requirement: Legacy vision model API delegates to the unified catalog
The system SHALL retain `GET /api/vision-models` for one compatibility version as a projection of the unified catalog and SHALL mark its response deprecated.

#### Scenario: Existing vision client uses legacy route
- **WHEN** an existing client requests `/api/vision-models`
- **THEN** it receives compatible sanitized VLM choices derived from the same catalog as `/api/model-profiles`
