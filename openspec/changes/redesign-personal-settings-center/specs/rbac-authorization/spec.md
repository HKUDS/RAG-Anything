## ADDED Requirements

### Requirement: Platform and knowledge-base vision settings use scoped permissions
The system SHALL require `settings:read`/`settings:write` for platform policy view/edit and model probes, and SHALL require knowledge-base ownership or `kb:write` for KB visual-vector settings. It MUST NOT substitute the deprecated `is_admin` check for these authorization decisions.

#### Scenario: Authorized platform reader views policy
- **WHEN** a user with `settings:read` opens platform configuration
- **THEN** the request succeeds subject to read-only state

#### Scenario: KB writer changes vector profile
- **WHEN** a user with `kb:write` requests a valid KB visual-profile change
- **THEN** the authorization layer permits the request before lifecycle validation
