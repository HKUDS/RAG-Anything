## Context

The repository distributes the same Impeccable skill through two discovery
directories and tracks generated ODL/DOCX output. The ODL directory is also a
controlled-media compatibility root, so existing artifacts cannot safely be
removed without an independently verified archive.

## Goals / Non-Goals

**Goals:**
- Prevent new generated output from being added accidentally.
- Make skill mirror drift detectable and repairable.
- Remove an unreferenced credential-exposing diagnostic entry point.

**Non-Goals:**
- Do not untrack existing ODL or DOCX artifacts.
- Do not change controlled-media delivery, CI policy, or public APIs.

## Decisions

- Keep two physical discovery trees for Windows/tool compatibility, with
  `.agents` canonical and a deterministic transform for `.github` paths.
- Use a standard-library checker with `--write` for explicit synchronization
  and a default non-mutating verification mode.
- Add ignores only; a later evidence-backed change can remove tracked output.

## Risks / Trade-offs

- [Metadata differs by discovery host] → allow a small documented path and
  tool-metadata transformation, while hashing every other file.
- [Ignore rules do not remove tracked files] → retain that limitation explicitly
  and require an archive manifest before any untracking.
