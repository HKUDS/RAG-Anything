## Why

LightRAG currently receives a text embedding callable with a dimension but no
stable model identifier. Its PostgreSQL backend consequently uses unsuffixed
vector tables, so different embedding models or dimensions can be mixed in the
same physical tables; KB separation still depends on the workspace predicate
and must be verified independently.

A follow-up defect fix makes legacy detection transaction-safe and
case-insensitive: the original quoted-uppercase `LIGHTRAG_VDB_*` probe raised
`UndefinedTableError` inside the registration transaction, which PostgreSQL
marks aborted, so the next statement failed with `InFailedSQLTransactionError`
and `python server.py` could not start.

## What Changes

- Freeze a canonical provider/model/dimension/identity-version snapshot at
  enqueue time and use it for Worker, retry, query, cache, and semantic
  chunking construction.
- Attach a collision-resistant PostgreSQL-safe `model_name` to LightRAG's
  embedding callable, while retaining `workspace=kb_dir(kb)` as the KB
  isolation boundary and rejecting `PG_WORKSPACE` overrides.
- Add an atomic KB identity registry and refuse incompatible changes before
  LightRAG initialization, writes, completion, or automatic retry.
- Define an explicit legacy policy: populated KBs using unsuffixed vector
  tables are blocked from automatic cutover; no normal query/upload may copy
  them into a suffixed table. Legacy detection is case-insensitive and must
  not abort the registration transaction when the tables are absent.
- Add startup diagnostics and a credential-safe read-only verification path
  that discovers actual suffixed vector tables, identities, dimensions,
  workspace counts, and cross-KB evidence.

## Capabilities

### New Capabilities

- `lightrag-embedding-kb-isolation`: Stable embedding identity and demonstrable
  PostgreSQL vector isolation for LightRAG knowledge bases.

### Modified Capabilities

- `upload-failure-detection`: Upload preflight must fail explicitly when a
  populated KB has an incompatible text embedding identity.

## Impact

Affected areas include LightRAG construction in `kb_service.py`, task settings
snapshots, Worker preflight, PostgreSQL KB identity metadata, vector storage
initialization and diagnostics, deployment configuration, operational health
checks, and upload/retrieval integration tests. Existing completed data is
neither deleted nor silently re-embedded.
