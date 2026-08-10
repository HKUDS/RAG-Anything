## ADDED Requirements

### Requirement: JWT signing secrets are not application-generated in production
Production authentication SHALL obtain both JWT signing secrets from externally managed configuration.  It MUST NOT generate, persist to application settings, or log fallback JWT secrets.

#### Scenario: Both secrets are externally supplied
- **WHEN** production starts with nonblank `JWT_SECRET` and `JWT_REFRESH_SECRET`
- **THEN** authentication signs and verifies tokens with those supplied values without recording them in application data or logs
