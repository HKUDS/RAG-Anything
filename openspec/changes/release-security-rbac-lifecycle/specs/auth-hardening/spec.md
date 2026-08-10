## ADDED Requirements

### Requirement: Public registration is closed by default
The system SHALL reject unauthenticated account creation unless an explicit non-production registration configuration is enabled.  Production configuration MUST reject any attempt to enable public registration.

#### Scenario: Public registration is disabled
- **WHEN** an unauthenticated caller sends `POST /api/auth/register` with the default configuration
- **THEN** the system rejects the request and does not create an account

#### Scenario: Production attempts to enable registration
- **WHEN** production configuration enables the public-registration switch
- **THEN** startup fails before serving requests
