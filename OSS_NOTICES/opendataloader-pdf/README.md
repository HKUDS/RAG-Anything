# OpenDataLoader PDF Redistribution Evidence

This directory is populated only from the exact wheel selected for an
OpenDataLoader-enabled release. It is not a legal approval and it must not be
filled with files copied from an unverified local installation.

The release workflow runs:

```text
python scripts/opendataloader_release_gate.py collect ...
python scripts/opendataloader_release_gate.py verify ...
```

`collect` extracts the wheel's `LICENSE`, `NOTICE`, third-party notices, and
license texts into this directory, records SHA-256 values for the wheel and
bundled JAR, and writes `release-manifest.json`. The release gate then requires
SBOMs from the final wheel, JAR, and OCI image, a version reconciliation record
(including veraPDF), immutable corresponding-source references, the final image
digest, and a written license-owner approval. Missing or placeholder data fails
the release gate.

This evidence covers the OpenDataLoader integration only. It does not certify
the rest of the product dependency set.
