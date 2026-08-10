## ADDED Requirements

### Requirement: Personal settings surface follows live section capabilities
The frontend SHALL derive visible personal-settings task sections from the
intersection of the server-provided `available_sections` and live
`hasPermission()` capabilities. `models` SHALL require `agent:write`; `ingestion`,
`retrieval`, and `runtime` SHALL require `kb:write`. It MUST NOT branch on role
names, mount unavailable section controls, or request model data when `models`
is unavailable.

#### Scenario: Student opens personal settings
- **WHEN** the user lacks both `kb:write` and `agent:write`
- **THEN** the page presents only appearance, account, and password/security
  controls and does not request the model catalog or settings options

#### Scenario: Assistant opens personal settings
- **WHEN** the user has `kb:write` but lacks `agent:write`
- **THEN** the page presents ingestion, retrieval, and runtime controls but
  does not mount model controls or request model data

### Requirement: Personal settings navigation recovers to a visible section
The frontend MUST make desktop navigation, mobile navigation, mounted sections,
and the scroll observer use the same ordered visible-section list. An unavailable or invalid hash
MUST be replaced with the first visible task section, or appearance when no task
section is available.

#### Scenario: Student opens a model hash
- **WHEN** a student navigates to `/preferences#models`
- **THEN** the page replaces the hash with the first visible section and has no
  active link without matching content
