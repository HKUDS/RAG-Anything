## ADDED Requirements

### Requirement: Administrator manages a user's knowledge-base grants
The user administration API and UI SHALL allow a caller with `users:write` to view and replace a target user's `allowed_kbs` as named KB grants.  An omitted `allowed_kbs` field SHALL preserve the existing grant set; an empty list SHALL revoke all grants.

#### Scenario: Administrator saves an empty grant list
- **WHEN** an authorized administrator saves `allowed_kbs: []` for a target user
- **THEN** the system SHALL revoke all explicit KB grants for that user while preserving their owned KBs

#### Scenario: Grant controls are hidden from non-administrators
- **WHEN** a user without `users:write` views non-administrator pages
- **THEN** the interface SHALL not render knowledge-base grant management controls
