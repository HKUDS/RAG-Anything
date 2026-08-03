# Frontend Permission Gating

## MODIFIED Requirements

### Requirement: Frontend operation entry points follow permissions
The frontend SHALL derive operation visibility from the authenticated user's live permission set. A write-only operation MUST NOT be mounted when its required permission is absent. Read-only pages MAY retain data and search controls, but ordinary business pages MUST NOT use disabled write controls or routine permission banners as the representation of missing access. Handlers SHALL retain silent early returns as defense in depth.

#### Scenario: User lacks a write permission
- **WHEN** a user lacks the permission required for create, edit, delete, upload, run, diagnosis, or graph mutation
- **THEN** the corresponding control, input, tab, shortcut, or empty-state CTA is absent and no permission toast is emitted

#### Scenario: Administrative permission details
- **WHEN** an authorized user views user management or audit logs
- **THEN** permission details in those administrative views remain visible
