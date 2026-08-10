## ADDED Requirements

### Requirement: Five-role authorization regression spans all delivery transports
The automated regression suite SHALL exercise `super_admin`, `dept_admin`, `teacher`, `assistant`, and `student` against protected HTTP endpoints, SSE, WebSocket, controlled media, knowledge bases, agents, and conversations.  The suite SHALL verify both permitted behavior and denied cross-role/cross-user behavior.

#### Scenario: Revoked user opens a protected transport
- **WHEN** an account is disabled, archived, or has its session generation advanced
- **THEN** HTTP, SSE, WebSocket, and controlled-media attempts using a previously issued token are rejected

#### Scenario: Lower role attempts privilege escalation
- **WHEN** a non-super-admin creates, restores, or changes an account to a role more privileged than the actor
- **THEN** the API returns 403 and the target role/state remains unchanged
