## ADDED Requirements

### Requirement: Role assignment respects five-level hierarchy across lifecycle operations
The service and repository SHALL enforce `super_admin > dept_admin > teacher > assistant > student` for account creation, role updates, restore, and lifecycle operations that retain or assign a role.  An actor MUST NOT assign a target role more privileged than the actor.

#### Scenario: Department administrator attempts super administrator assignment
- **WHEN** a `dept_admin` attempts to create or promote an account to `super_admin`
- **THEN** the operation returns 403 and no account role changes

#### Scenario: Super administrator assigns a lower role
- **WHEN** a `super_admin` assigns an account to `teacher`, `assistant`, or `student`
- **THEN** the authorized mutation succeeds subject to lifecycle invariants
