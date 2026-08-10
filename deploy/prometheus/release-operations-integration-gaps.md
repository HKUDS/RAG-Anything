# Required Metrics Before Enabling Additional Alerts

Do not enable an alert until its source has been verified in the target deployment.

| Alert category | Required metric/query | Owner | Acceptance |
|---|---|---|---|
| Upload queue | `rag_upload_queue_oldest_seconds`, `rag_upload_queue_jobs{state}` | application or PG exporter owner | A queued/failed task changes the query without exposing filename/user data. |
| SSE error rate | `rag_sse_stream_events_total{outcome}` and `error / (done + error)` | application owner | Client cancellation is separate from server error. |
| Certificate expiry | `probe_ssl_earliest_cert_expiry` or x509 exporter equivalent | edge/certificate owner | Test certificate produces a warning at 30 days. |
| Backup freshness | `raganything_backup_verified_timestamp_seconds` | backup wrapper owner | Published only after checksum and encrypted off-site copy both succeed. |

All future rules require `severity`, `for`, a deployment label, and the runbook URL used by `release-operations-alerts.yml`.
