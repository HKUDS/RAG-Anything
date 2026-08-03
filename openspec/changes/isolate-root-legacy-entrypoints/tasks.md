## 1. Evidence And Documentation

- [x] 1.1 Re-run tracked-path, static-reference, Git-history, and targeted sensitive-information checks for each of the eight named deletion targets; record any exception before editing.
- [x] 1.2 Update historical `CHANGELOG.md` entries to mark the two retired root CLIs unavailable and direct users to the authenticated application surface.
- [x] 1.3 Record the credential-bearing test deletion as source-risk reduction only; state that Git-history credential revocation/rotation remains externally unverified.

## 2. Root Surface Isolation

- [x] 2.1 Delete `server.py.integration-backup` and `_apply_changes.py` after evidence confirms no supported consumer.
- [x] 2.2 Delete `query.py` and `upload_and_query.py` after evidence confirms no supported consumer.
- [x] 2.3 Delete only `worker_output.txt`, `.tmp-redesign-full-suite.xml`, `38692`, and `cd`, and add root-anchored ignore rules for those exact output paths.

## 3. Regression Coverage

- [x] 3.1 Add a focused source-contract test that retains `server.py`, rejects the four retired root entrypoints, validates the four root-anchored ignore rules without ignoring nested names, and protects the excluded JSON ownership rules.
- [x] 3.2 Run the focused source-contract test and the existing relevant compatibility tests.

## 4. Verification And Summary

- [x] 4.1 Run strict OpenSpec validation, the project-summary checker, and `git diff --check`.
- [x] 4.2 Update `PROJECT_SUMMARY.md` with the deletion evidence, validation results, unchanged HTTP/RBAC/schema scope, and external credential-rotation limitation.
