## 1. Prevent repository drift

- [x] 1.1 Ignore newly generated ODL and temporary DOCX output without untracking existing artifacts.
- [x] 1.2 Add deterministic Impeccable skill-mirror synchronization and verification tooling.
- [x] 1.3 Add focused tests for the mirror checker and generated-output rules.

## 2. Retire unsafe legacy entry points

- [x] 2.1 Remove the unreferenced hard-coded retrieval diagnostic.
- [x] 2.2 Mark root compatibility wrappers deprecated and migrate internal tests to canonical service imports.

## 3. Verification and documentation

- [x] 3.1 Run focused hygiene and compatibility tests, then verify no retired references remain.
- [x] 3.2 Update PROJECT_SUMMARY.md with completed behavior, retained artifact risk, and validation result.
