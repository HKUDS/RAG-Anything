## ADDED Requirements

### Requirement: Administrator user lifecycle operations preserve security invariants
Administrator user-management APIs SHALL present archive/disable as the default destructive lifecycle action and SHALL not physically delete the user record.  They MUST reject lifecycle operations that would remove the final active `super_admin` and MUST invalidate target sessions after a successful security-sensitive change.

#### Scenario: Delete-compatible API archives a regular user
- **WHEN** an authorized administrator invokes the documented delete-compatible lifecycle action for a non-protected account
- **THEN** the account is archived rather than physically removed and its active sessions are invalidated
