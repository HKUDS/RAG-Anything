## Why

The repository contains duplicated skill distribution trees and generated
runtime directories that are easy to re-add accidentally. Existing ODL samples
remain a controlled-media compatibility root, so cleanup must be preventative
and evidence-driven rather than destructive.

## What Changes

- Define `.agents/skills/impeccable` as the canonical skill source and add an
  explicit sync/check workflow for the GitHub discovery mirror.
- Ignore new generated ODL and temporary DOCX output without removing existing
  tracked artifacts.
- Remove the unreferenced legacy retrieval diagnostic that hard-codes a work
  directory and prints a credential prefix.
- Retain compatibility wrappers and tracked artifacts until independent archive
  and reference evidence permits a separate removal change.

## Capabilities

### New Capabilities

- `repository-hygiene`: generated output prevention and skill-mirror integrity.

### Modified Capabilities

None.

## Impact

Repository ignore rules, a small validation script and test, the skill mirror,
and `diagnose_retrieval.py` change. Runtime APIs, migrations, and media delivery
behavior do not change.
