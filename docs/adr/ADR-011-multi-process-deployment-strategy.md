# ADR-011: Multi-Process Deployment Strategy — Trade-Off Analysis

## Status
Proposed

## Context

RAG-Anything currently runs as a single `uvicorn` process. All core state resides in module-level Python globals within that single process:

- **kb_instances**: `dict[str, RAGAnything]` -- ~2 GB per KB (LightRAG vector indices, graph store, embedding cache all in memory)
- **processing_tasks**: in-flight document processing status
- **query_history**: last 1000 query records (persisted to JSON)
- **ws_clients / active_ws_connections**: WebSocket connection tracking
- **processing_events**: rolling 200-entry event log
- **token_blacklist**: memory cache + SQLite for JWT revocation
- **rate limiter** (slowapi): in-process hit counters
- **conversation_manager**: multi-turn chat state

The server enforces single-instance exclusivity via a PID file and port pre-check (lines 219-296 of `server.py`). Adding a second uvicorn worker would silently break correctness: WebSocket broadcasts would miss clients on other workers, rate limits would not be shared, token revocations would have a visibility gap, and `processing_tasks` would be invisible across workers.

The team (1-3 developers) is targeting 20-50 concurrent users on a single server. The question is: **when scaling beyond a single process becomes necessary, which multi-process strategy fits this architecture?**

This ADR analyzes three candidate strategies. It is a **decision exploration**, not a final recommendation to implement immediately. The analysis is structured as three mini-ADRs (one per option) followed by a comparison matrix and recommendation.

---

## System Constraints (from Code Audit)

These constraints were derived from reading the actual code, not assumptions:

| Constraint | Detail | Source |
|---|---|---|
| C1. kb_instances are heavyweight | ~2 GB memory per KB, loaded lazily | `kb_service.py:177-189` |
| C2. Subprocess-based document processing | `asyncio.subprocess.Process` spawns `process_worker.py`; worker writes to disk, server reloads from disk | `kb_service.py:722-764` |
| C3. WebSocket is broadcast-only | `ws_broadcast()` iterates `ws_clients` list; no targeting | `ws_service.py:41-57` |
| C4. Token blacklist has cross-worker fallback | `is_revoked()` already checks SQLite as fallback after memory cache miss | `token_blacklist.py:119-139` |
| C5. Rate limiter is in-process | `slowapi` with `Limiter(key_func=get_remote_address)` -- no shared store | `server.py:59-61` |
| C6. Server startup guard blocks multi-process | PID file + port bind check prevents second instance | `server.py:219-296` |
| C7. Query history persisted to JSON | Not critical for correctness; best-effort persistence | `state_service.py:39-75` |
| C8. Embedding cache is in-process | `make_cached_embed_func()` creates an in-memory LRU cache | `kb_service.py` imports |
| C9. No infrastructure dependencies beyond SQLite | No Redis, no message queue, no external cache | Full codebase grep for `redis` yields zero hits in core code |

---

## Option A: Single Pool + Redis

### Mini-ADR A

**Status**: Proposed (for analysis)

**Context**: The simplest horizontal scaling model. Run N identical uvicorn workers behind a load balancer. All shared state moves to Redis.

**Decision**: Introduce Redis as the sole inter-worker coordination mechanism. Each worker independently loads `kb_instances` (duplicated memory). Redis holds: `processing_tasks`, rate limiter counters, token blacklist (replacing SQLite fallback), pub/sub for `ws_clients`, `processing_events`, and optionally `query_history`. The server startup guard is removed or made per-worker-port.

### Architectural Fit Analysis (Option A)

**Consistency with existing modular monolith**: Moderate. The service layer (`kb_service`, `ws_service`, `state_service`, `token_blacklist`) already has clear module boundaries. Each service module would need a "Redis adapter" alongside its current in-memory implementation. This is essentially applying the Strategy pattern at the service level -- each service gets a `MemoryBackend` and a `RedisBackend`, selected by configuration. This preserves the existing module structure without requiring a rewrite.

**Refactoring surface (estimated)**:

| Module | Change Required | Effort |
|---|---|---|
| `state_service.py` | Replace `processing_tasks` dict with Redis hash operations | Medium |
| `ws_service.py` | Replace `ws_clients` list with Redis pub/sub channels; each worker subscribes to a broadcast channel and forwards to its local WS connections | High |
| `token_blacklist.py` | Replace memory cache with Redis SET with TTL; SQLite becomes cold-storage fallback only | Low (already has SQLite fallback pattern) |
| `server.py` | Remove PID-file guard; configure uvicorn `--workers N`; add Redis health check on startup | Medium |
| `dependencies.py` | Replace `slowapi` `Limiter` with Redis-backed rate limiter (e.g., `slowapi` with Redis storage, or a custom middleware) | Low-Medium |
| `kb_service.py` | No changes to kb_instances loading; add cache invalidation events via Redis pub/sub for KB create/delete | Low |

**Lines of code preserved**: ~85%. Only the state-holding modules change; the router layer, kb_service core logic, and processing pipeline are untouched.

### Coupling Analysis (Option A)

**New coupling: All workers -> Redis.**

This is a "hub-and-spoke" coupling model. Redis becomes a hard dependency for correctness. If Redis is unavailable, the system is not merely degraded -- it is non-functional:

- Rate limiting: every request checks Redis; without it, requests are either all blocked or all allowed depending on fail-open/fail-closed choice.
- Token blacklist: every authenticated request checks Redis; without it, revoked tokens are accepted (fail-open) or all tokens are rejected (fail-closed).
- WebSocket: without Redis pub/sub, progress events from one worker's upload never reach WebSocket clients on another worker.
- Processing tasks: without Redis, task status queries return stale or empty data.

This coupling is **tight** in the consistency dimension (all workers see the same state) but **brittle** in the availability dimension (Redis is a single point of failure). For 20-50 users, a single Redis instance is unlikely to fail, but the architectural dependency is real.

### Cohesion vs. Duplication Trade-Off

- **Gains coherence**: All workers see identical `processing_tasks`, rate limits, token revocations, and WebSocket events. This is the "correct" behavior for a stateless web application.
- **Pays with duplication**: Each worker holds its own copy of `kb_instances`. For 3 KBs and 4 workers, that is 3 x 2 GB x 4 = 24 GB of RAM for duplicated indices. This is the dominant cost.

The embedding cache (C8) is particularly painful here: each worker independently warms its own cache by re-computing embeddings that another worker may have already computed. A Redis-based embedding cache could mitigate this, but adds complexity (serialization of large embedding vectors).

### Evolution Path (Option A)

- **20-50 users today**: Overkill. The single-process architecture already handles this.
- **50-200 users**: Add workers linearly. Each worker adds ~2 GB/KB of RAM. At 4 workers and 3 KBs, 24 GB RAM is manageable on a 32 GB server.
- **500+ users**: The memory duplication becomes the bottleneck. Options: (a) move to Option B to dedicate KB-heavy and KB-light workers; (b) move kb_instances out of process entirely (e.g., a dedicated embedding service); (c) use Redis as an embedding cache to reduce per-worker memory. This does not require a rewrite -- it is an incremental evolution from Option A.

### Anti-Patterns and Risks

1. **Redis as God Object**: All cross-cutting concerns (caching, pub/sub, rate limiting, state storage, token blacklist) converge on Redis. If the Redis schema becomes tangled (e.g., rate limit keys mixing with task state keys), it becomes a bottleneck for both development and operations.
2. **Embedding cache fragmentation**: Each worker independently caches embeddings. If a worker restarts, its cache is cold while others are warm, creating unpredictable latency variance.
3. **Memory cost of correctness**: You are paying ~2 GB/KB/worker solely to avoid implementing a shared embedding service. Assess whether the operational simplicity of duplicating memory is worth the hardware cost.

### Vendor Lock-In

**Redis is a hard dependency for correctness.** Migrating away from Redis requires re-implementing: pub/sub (could use PostgreSQL LISTEN/NOTIFY), rate limiting (could use in-process with eventual consistency), state storage (could use SQLite with polling), and token blacklist (already has SQLite fallback). This is moderate lock-in: Redis is a well-standardized, multi-vendor component (Redis OSS, Valkey, Dragonfly, ElastiCache, Memorystore), so the operational risk is lower than a proprietary service. But it is still one more infrastructure component to manage, monitor, back up, and secure.

---

## Option B: Query Pool + Admin Pool

### Mini-ADR B

**Status**: Proposed (for analysis)

**Context**: Separate read-heavy query traffic from write-heavy mutation traffic. This recognizes that `kb_instances` are read-mostly (queries use them, only uploads/KB creates mutate them) and that upload processing is the system's most resource-intensive operation.

**Decision**: Split workers into two pools differentiated by responsibility:

- **Query pool** (3-4 workers): Handles all GET/query endpoints, SSE streaming, WebSocket connections. `kb_instances` loaded read-only. No upload processing. No KB creation/deletion.
- **Admin pool** (1-2 workers): Handles POST/PUT/DELETE for KB management, document uploads, and the processing pipeline. After processing, publishes a "KB updated" event to Redis.
- Redis bridges the two pools: query pool workers subscribe to "KB updated" events and reload affected `kb_instances` from disk. Redis also holds shared state (rate limiter, token blacklist, processing_tasks).
- Path-based load balancer routing: `/api/upload*`, `/api/kb/*` (POST/PUT/DELETE) -> admin pool; everything else -> query pool.

### Architectural Fit Analysis (Option B)

**Consistency with existing modular monolith**: Good. This maps naturally to the existing service boundaries. The `kb_service` already distinguishes between read operations (`get_kb`, `query`) and write operations (`create_kb`, `delete_kb`, `_process_uploaded_file`). The `routers/knowledge.py` already separates query endpoints from management endpoints. This option makes the separation physical rather than just logical.

**Refactoring surface (estimated)**:

| Module | Change Required | Effort |
|---|---|---|
| `routers/knowledge.py` | Split into `knowledge_query.py` and `knowledge_admin.py` (or use route-level middleware to direct to appropriate pool) | Low |
| `kb_service.py` | Add `invalidate_kb(name)` that publishes Redis event; add subscription in query workers to reload KB on invalidation | Medium |
| `ws_service.py` | Same Redis pub/sub changes as Option A | High |
| `state_service.py` | `processing_tasks` only lives in admin pool; query pool reads from Redis | Medium |
| Load balancer config | Add path-based routing rules (e.g., nginx `location`, Traefik `PathPrefix` rules) | Medium (ops) |
| `server.py` | Two entry points or one entry point with a `--role` flag (`query` vs `admin`) | Low |

**Lines of code preserved**: ~80%. More refactoring than Option A due to pool role differentiation, but the domain logic remains unchanged.

### Coupling Analysis (Option B)

**New coupling types:**

1. **Query pool -> Redis**: Lighter than Option A. Query workers only use Redis for: rate limiting, token blacklist, KB invalidation events, and reading `processing_tasks` status. They do NOT write to Redis for task state.
2. **Admin pool -> Redis**: Writes `processing_tasks`, publishes KB invalidation events, writes rate limit counters (shared with query pool), writes token revocations.
3. **Query pool -> Admin pool (indirect via Redis)**: The only cross-pool dependency is: admin processes an upload -> publishes "KB updated" -> query workers reload KB from disk. This is an event-driven, eventually-consistent coupling. The temporal gap between "upload complete" and "query worker reloads" is on the order of milliseconds to seconds.
4. **Load balancer -> Both pools**: The LB must be path-aware. This adds an operations dependency: misconfigured routing silently breaks the system (e.g., uploads hitting query pool would try to process but have no worker infrastructure).

### Coherence vs. Duplication Trade-Off

- **Gains specialization**: Query workers can be optimized for read throughput (fewer locks, no processing overhead). Admin workers can be optimized for processing (higher memory for worker subprocesses, dedicated CPU for parsing).
- **Reduces duplication vs Option A**: If you have 3 KBs, Option A with 4 workers duplicates each KB 4 times. Option B with 4 query + 1 admin = 3 query workers holding KBs (admin worker also holds KBs for processing). Still significant duplication, but the admin pool can be sized independently.
- **Loses simplicity**: Two different worker roles means two different deployment configurations, two different health check semantics, two different scaling policies. This doubles the operational surface for a small team.

### Evolution Path (Option B)

- **20-50 users today**: Significant over-engineering. The operational complexity of two pools outweighs the benefit at this scale.
- **100-200 users**: The specialization pays off. Query pool scales independently to handle traffic growth. Admin pool stays small (uploads are less frequent than queries). This is more cost-efficient than Option A because you do not duplicate KB memory on workers that do not need it.
- **500+ users**: This option provides the cleanest evolution path. The query pool can be further specialized (e.g., separate pools for SSE/streaming vs. REST queries). The admin pool can be split into a processing service (async job queue) and a management API. The Redis event channel becomes the integration backbone. **This option is the most evolvable of the three because it establishes bounded contexts at the deployment level that mirror the domain boundaries already in the code.**

### Anti-Patterns and Risks

1. **Distributed monolith in disguise**: If the two pools share the same codebase, database, and deploy together, it is a distributed monolith -- not microservices. This is acceptable at this scale but must be recognized. The risk is that developers treat it as truly independent services and introduce breaking changes between pool versions.
2. **Split-brain on KB state**: If the Redis event is lost (network partition, Redis restart without persistence), a query worker will serve stale KB data indefinitely. Mitigation: periodic health-check reload from disk (e.g., every 60 seconds check KB mtime).
3. **LB routing fragility**: Path-based routing means every new endpoint must be correctly classified as query vs. admin. A developer adding a new endpoint that does not match either pool's routing rules creates a silent failure. Mitigation: default route to query pool, explicit allowlist for admin pool routes.
4. **WebSocket complexity**: WebSocket connections are long-lived. If a WebSocket connects to a query worker but the upload is processed by an admin worker, the progress events must route through Redis pub/sub to reach the correct worker. This is the same complexity as Option A, but with the added twist that the WebSocket might be on a worker that never sees the upload.

### Vendor Lock-In

Same Redis dependency as Option A, plus **LB routing dependency**. The path-based routing rules are specific to the load balancer (nginx `location` blocks, Traefik `PathPrefix` rules, HAProxy ACLs). Migrating load balancers requires rewriting these rules. However, path-based routing is a universal LB feature, so this is low risk.

---

## Option C: Sticky Sessions + In-Memory State

### Mini-ADR C

**Status**: Proposed (for analysis)

**Context**: Avoid all infrastructure changes. Use N independent workers with no shared state, relying on the load balancer's sticky session mechanism to ensure a user's requests always land on the same worker.

**Decision**: Run N identical uvicorn workers. The load balancer sets a session cookie (e.g., `SERVERID`) and routes all requests with that cookie to the same backend. `kb_instances` duplicated per worker. All state remains in-process. No Redis. No shared store. The server startup guard is modified to allow per-worker-port binding.

### Architectural Fit Analysis (Option C)

**Consistency with existing modular monolith**: Perfect. Zero code changes to the service layer. The only code changes are:
1. Remove or modify the PID-file guard to allow multiple instances on different ports.
2. Configure the load balancer for sticky sessions.
3. Optionally, add a health check endpoint that the LB can probe.

**Refactoring surface (estimated)**:

| Module | Change Required | Effort |
|---|---|---|
| `server.py` | Remove PID-file single-instance guard; accept `--port` from environment or CLI; add `/health` endpoint | Low |
| Load balancer config | Enable sticky sessions (e.g., nginx `ip_hash` or cookie-based `sticky`) | Low (ops) |
| All other modules | **No changes** | Zero |

**Lines of code preserved**: ~99%. This is the defining advantage of Option C.

### Coupling Analysis (Option C)

**New coupling: User -> Specific Worker.**

This is a session-affinity coupling. Once a user is pinned to Worker-2, all their requests go to Worker-2. This has subtle consequences:

1. **Uneven load distribution**: If User-A (heavy query user) and User-B (light user) both land on Worker-1, Worker-1 is overloaded while Worker-2 is idle. Mitigation: use cookie-based stickiness (not IP-based) and set a short TTL so sessions can be rebalanced.
2. **Worker failure = session loss**: If Worker-2 crashes, all users pinned to it lose their WebSocket connections, in-flight uploads, and query context. The LB re-pins them to another worker, but `processing_tasks` from the old worker are gone, `query_history` from that session is gone, and the new worker must cold-load `kb_instances`.
3. **No cross-worker visibility**: Progress events from an upload on Worker-1 are invisible to any WebSocket client on Worker-2. If a user opens two browser tabs and the LB pins them to different workers, one tab shows upload progress while the other does not.
4. **Token revocation asymmetry**: If a user logs out on Worker-1, their token is revoked in Worker-1's memory. If the same token is presented to Worker-2 (e.g., the user had a second tab), Worker-2's memory cache does not have the revocation. The SQLite fallback in `token_blacklist.is_revoked()` partially mitigates this, but there is a window between the memory write on Worker-1 and the SQLite write + read on Worker-2.

### Coherence vs. Duplication Trade-Off

- **Maximizes simplicity**: Zero new infrastructure. Zero new code patterns. The system behaves exactly as it does today, just with more processes.
- **Maximizes duplication**: Same memory duplication as Option A, but without the coherence benefits of Redis.
- **Accepts incoherence**: The team explicitly accepts that `processing_tasks`, `ws_clients`, `processing_events`, `query_history`, and rate limits are per-worker and do not need to be globally coherent. For 20-50 users, this is often an acceptable trade-off -- the probability of a single user's requests landing on different workers is low with sticky sessions, and the consequences are mild (missing a progress event, seeing slightly stale task status).

### Evolution Path (Option C)

- **20-50 users today**: This is the only option that makes sense at this scale. It requires no new infrastructure, no code refactoring, and the incoherence problems are statistically rare.
- **50-200 users**: The incoherence problems become more frequent. More users = more concurrent uploads = more progress events crossing worker boundaries = more complaints about "my upload shows 0% on one tab and 80% on another." At this point, the team would need to either: (a) accept the UX degradation, (b) add Redis and migrate to Option A, or (c) add sticky-session-aware WebSocket routing.
- **500+ users**: This option breaks down. The combination of memory duplication cost, session-loss impact, and incoherence makes it unsustainable. **A migration from Option C to Option A or B would require significant refactoring** -- essentially all the changes listed in Option A/B, done under pressure of growing traffic.

### Anti-Patterns and Risks

1. **Silo Pattern (Mini-Monolith per Worker)**: Each worker is a fully self-contained monolith with its own state, its own KB instances, its own WebSocket clients. There is no "system" -- there are N independent systems that happen to serve the same API. This is the defining anti-pattern of sticky-session architectures. It trades systemic coherence for deployment simplicity, and the trade-off becomes worse as the number of workers grows.
2. **Silent data inconsistency**: A user uploads a document on Worker-1, the upload completes, and they immediately query the KB. The LB routes the query to Worker-2 (sticky session expired or cookie lost). Worker-2 has not reloaded the KB from disk, so the new document is invisible. The user thinks the upload failed. This class of bug is hard to reproduce (depends on LB behavior) and hard to diagnose.
3. **Operational blindness**: With no shared state, there is no single place to observe system health. "How many processing tasks are running?" requires querying every worker. "How many WebSocket clients are connected?" requires aggregating across workers. For a small team, this is manageable with a simple aggregator endpoint, but it adds operational toil.
4. **Rate limit escape**: A determined user can bypass rate limits by triggering a re-pin to a different worker (clear cookies, switch IP). Each worker has its own rate limit counter, so the effective rate limit is N x the configured limit.

### Vendor Lock-In

**Sticky session support in the load balancer.** All major load balancers support sticky sessions (nginx `sticky` or `ip_hash`, HAProxy `cookie`, Traefik sticky sessions, AWS ALB stickiness). This is minimal lock-in -- it is a universally available feature. However, **cloud-native serverless platforms (AWS Lambda, Cloud Run) generally do NOT support sticky sessions**, which would block a future migration to serverless.

---

## Comparison Matrix

| Dimension | Option A (Single Pool + Redis) | Option B (Query + Admin Pools) | Option C (Sticky Sessions) |
|---|---|---|---|
| **Code changes** | ~15% of codebase touched | ~20% of codebase touched | <1% of codebase touched |
| **New infrastructure** | Redis (critical path) | Redis (critical path) + LB path routing | LB sticky sessions only |
| **Memory cost (3 KBs, 4 workers)** | ~24 GB | ~18 GB (3 query + 1 admin) | ~24 GB |
| **State coherence** | Strong (all state in Redis) | Strong (Redis-bridged) | Weak (per-worker silos) |
| **Fault tolerance** | Redis SPOF + worker redundancy | Redis SPOF + pool-level redundancy | Worker SPOF per user session |
| **Operational complexity** | Medium (1 pool + Redis to manage) | High (2 pools + Redis + LB rules) | Low (N identical workers) |
| **Scaling model** | Uniform horizontal | Asymmetric horizontal | Uniform horizontal with caveats |
| **Evolution to 500+ users** | Requires embedding service extraction | Clean path to service decomposition | Requires near-rewrite |
| **Team size fit (1-3 devs)** | Stretches the team | Overwhelms the team | Fits the team |
| **User experience consistency** | Consistent | Consistent | Inconsistent under edge cases |
| **Rollback simplicity** | Medium (remove Redis, revert code) | Hard (re-merge pools, remove LB rules) | Trivial (go back to 1 worker) |

---

## Recommendation

### Ranking

**1st: Option C (Sticky Sessions + In-Memory State)** -- for NOW (20-50 users, 1-3 developers)

This is the right architecture for the current scale. It preserves 99% of the codebase, introduces zero new infrastructure, and the incoherence problems (stale task status, missed progress events, cross-worker token visibility) are statistically rare at 20-50 users with sticky sessions. The team can deploy this in a day and observe whether the problems manifest before investing in Redis.

The key argument: **do not solve a scaling problem you do not yet have.** The current single-process architecture serves 20-50 users. When that becomes insufficient, Option C is the minimum-viable step to add capacity. It is also the most reversible decision -- going from Option C to Option A is a forward migration (add Redis, refactor services), not a rollback.

**2nd: Option A (Single Pool + Redis)** -- for 50-200 users

When Option C's incoherence becomes a real operational burden, Option A is the natural next step. The service modules are already structured to accept a backend swap (Strategy pattern). The refactoring is bounded: `state_service`, `ws_service`, `token_blacklist`, `dependencies.py`. The rest of the codebase is unchanged.

**3rd: Option B (Query + Admin Pools)** -- for 200+ users

Option B is the most architecturally pure but also the most operationally complex. A team of 1-3 developers managing two worker pools, Redis, path-based LB routing, and pool-specific health checks is a significant burden. This option only becomes appropriate when the query/admin workload asymmetry is a measurable bottleneck, and the team has grown enough to absorb the operational complexity.

### What to Build Now vs. Later

| Now | Later (when needed) |
|---|---|
| Ensure sticky-session LB config is documented | Add Redis with sentinel for HA |
| Add `/health` endpoint for LB probing | Extract embedding cache to Redis |
| Make `server.py` port configurable via env | Implement Strategy pattern in services |
| Remove PID-file guard behind a `--multi-worker` flag | Split routers into query/admin pools |
| Add a `/api/status` aggregator that reports per-worker stats | Add worker-level metrics (Prometheus) |
| Add `X-Worker-ID` response header for debugging | Implement KB invalidation events |

### Decision

**Propose Option C as the immediate strategy, with Option A as the documented evolution target.** Write the code today such that the migration to Option A is a configuration change + adapter implementation, not a rewrite. Specifically:

1. Keep the service-layer interfaces abstract enough that a Redis backend can be swapped in (the modules already use clear function boundaries -- `get_task_status()`, `ws_broadcast()`, `is_revoked()` -- these are natural adapter seams).
2. Do not introduce new direct accesses to module-level globals outside the service modules that own them.
3. Document the sticky-session constraint in the deployment guide so operators understand the trade-off.

---

## Consequences

### What becomes easier (with Option C adopted now):
- Horizontal scaling is a configuration change (add workers, configure LB sticky sessions)
- No new infrastructure to learn, manage, monitor, secure, or pay for
- Rollback is instant (reduce to 1 worker)
- Developer mental model unchanged -- the system works the same way it always has

### What becomes harder:
- Debugging cross-worker issues requires correlating logs across workers (mitigated by `X-Worker-ID` header)
- Rate limiting is per-worker, not global (mitigated by configuring per-worker limits at total/N)
- WebSocket progress events are only visible on the worker handling the upload
- Token revocation has a brief cross-worker visibility gap (partially mitigated by existing SQLite fallback)
- Future migration to serverless platforms (Lambda, Cloud Run) is blocked by sticky session requirement

### What the team is explicitly accepting:
- State incoherence as the price of simplicity
- A future migration to Option A when scale demands it
- That the architecture is "good enough" rather than "correct"
