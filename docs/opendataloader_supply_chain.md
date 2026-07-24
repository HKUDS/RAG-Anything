# OpenDataLoader Supply-Chain Release Gate

This file is an evidence checklist, not a redistribution approval.

- Pin source revision, Python wheel SHA-256, bundled JAR SHA-256, and final
  image digest for `opendataloader-pdf==2.5.0`.
- Generate CycloneDX or SPDX SBOMs from the downloaded wheel, extracted JAR,
  and built opt-in image.
- Preserve upstream `LICENSE`, `NOTICE`, third-party notices, component license
  texts, and immutable corresponding-source URLs under the released artifact's
  `OSS_NOTICES/opendataloader-pdf/` directory.
- Reconcile Maven, Python, OS, and container component versions against the
  notices, including the observed veraPDF version discrepancy.
- Block release for `NOASSERTION`, an unknown/missing license, an unresolved
  version mismatch, absent notice, or missing written license-owner approval.

No artifact has been approved merely by adding this checklist.

The CI workflow `.github/workflows/opendataloader-release-gate.yml` keeps lock,
default, OpenDataLoader, and Marker installs separate. Its manual redistribution
job invokes `scripts/opendataloader_release_gate.py`; it fails when approval or
reconciliation records are absent, incomplete, or still use a template value.
