## ADDED Requirements

### Requirement: Skill mirrors remain synchronized
The repository SHALL treat `.agents/skills/impeccable` as canonical and SHALL
provide a deterministic checker for the `.github/skills/impeccable` discovery
mirror. The checker MUST fail when non-host-specific skill content drifts and
MUST support an explicit write mode to refresh the mirror.

#### Scenario: Canonical skill changes
- **WHEN** a canonical skill file changes without refreshing the GitHub mirror
- **THEN** the checker reports the differing relative path and exits non-zero

#### Scenario: Mirror refresh
- **WHEN** a maintainer runs the checker in explicit write mode
- **THEN** the GitHub mirror is regenerated from the canonical skill using only
  documented host-specific substitutions

### Requirement: Generated runtime output is not newly tracked
The repository SHALL ignore newly created `odl-artifacts` and `temp_docx`
runtime output while preserving already tracked artifacts until a separate
change verifies independent archival and media-delivery migration.

#### Scenario: New local parser output
- **WHEN** a parser creates a new file under either generated-output directory
- **THEN** Git does not report it as an untracked file by default

#### Scenario: Existing media evidence
- **WHEN** a tracked ODL artifact remains required by controlled media delivery
- **THEN** the hygiene change does not remove it from version control
