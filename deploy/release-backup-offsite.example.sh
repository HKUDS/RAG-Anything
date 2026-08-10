#!/usr/bin/env sh
# Deployment-owned wrapper. Values are secret-manager references, not literals.
set -eu

: "${BACKUP_BUNDLE:?path to already verified bundle is required}"
: "${BACKUP_ENCRYPT_COMMAND:?approved encryption command reference is required}"
: "${BACKUP_UPLOAD_COMMAND:?approved off-site upload command reference is required}"

# The deployed wrapper resolves command references from the platform secret
# manager. This checked-in example intentionally cannot transfer unencrypted
# data or contain a recipient, credential, bucket, or key material.
"$BACKUP_ENCRYPT_COMMAND" "$BACKUP_BUNDLE"
"$BACKUP_UPLOAD_COMMAND" "$BACKUP_BUNDLE.enc"

# Publish raganything_backup_verified_timestamp_seconds only after the upload
# command returns successfully. The metrics writer is deployment-owned.
