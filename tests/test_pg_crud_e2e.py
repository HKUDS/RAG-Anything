#!/usr/bin/env python
"""E2E CRUD test for all Phase 1-3 PG tables."""
import asyncio, os, sys

if not os.getenv("DATABASE_URL"):
    raise RuntimeError("DATABASE_URL must be supplied explicitly for the PG E2E test")

async def test():
    from raganything.services.pg_state_repo import init_pg_pool, get_pg_pool

    pool = await init_pg_pool()
    print("PG pool initialized")

    passed = 0
    failed = 0

    async def check(test_name, coro):
        nonlocal passed, failed
        try:
            await coro
            print(f"  [PASS] {test_name}")
            passed += 1
        except Exception as e:
            print(f"  [FAIL] {test_name}: {e}")
            failed += 1

    async with pool.acquire() as conn:
        # 1. token_revocations (Phase 1: family_id)
        await check("token_revocations (family_id)", _test_token(conn))
        # 2. audit_logs (Phase 1: PG write)
        await check("audit_logs", _test_audit(conn))
        # 3. image_vision_vectors + cosine (Phase 2)
        await check("image_vision_vectors + array_cosine_similarity", _test_vision(conn))
        # 4. workflow_definitions + runs CASCADE (Phase 3)
        await check("workflow_definitions + runs (CASCADE)", _test_workflow(conn))
        # 5. fault_cases (Phase 3)
        await check("fault_cases", _test_fault(conn))
        # 6. process_documents (Phase 3)
        await check("process_documents", _test_process(conn))
        # 7. dashboard_query_log (Phase 3)
        await check("dashboard_query_log", _test_dashboard(conn))

    print(f"\nResult: {passed}/7 passed, {failed}/7 failed")
    await pool.close()
    return failed == 0


async def _test_token(conn):
    await conn.execute(
        "INSERT INTO token_revocations (jti, expires_at, family_id) "
        "VALUES ('e2e-test-jti', NOW()+INTERVAL'1h','e2e-fam') "
        "ON CONFLICT(jti) DO UPDATE SET family_id='e2e-fam'"
    )
    row = await conn.fetchrow("SELECT * FROM token_revocations WHERE jti='e2e-test-jti'")
    assert row and row["family_id"] == "e2e-fam", "family_id mismatch"
    await conn.execute("DELETE FROM token_revocations WHERE jti='e2e-test-jti'")


async def _test_audit(conn):
    # Do not specify id — let SERIAL auto-increment
    row = await conn.fetchrow(
        "INSERT INTO audit_logs (actor_id, action, details, ip_address) "
        "VALUES (99999, 'e2e.test.20260630', $1::jsonb, '127.0.0.1') RETURNING *",
        '{"key":"val"}',
    )
    assert row is not None, "audit insert returned None"
    assert row["action"] == "e2e.test.20260630", f"audit insert: {dict(row)}"
    await conn.execute("DELETE FROM audit_logs WHERE action='e2e.test.20260630'")


async def _test_vision(conn):
    await conn.execute(
        "INSERT INTO image_vision_vectors (id, image_hash, doc_id, embedding) "
        "VALUES ('e2e-img', 'abc123', 'doc-1', ARRAY[1.0,0.0,0.0]::double precision[]) "
        "ON CONFLICT(id) DO UPDATE SET embedding=ARRAY[1.0,0.0,0.0]::double precision[]"
    )
    score = await conn.fetchval(
        "SELECT array_cosine_similarity("
        "ARRAY[1.0,0.0,0.0]::double precision[], "
        "ARRAY[1.0,0.0,0.0]::double precision[]) "
    )
    assert abs(score - 1.0) < 0.001, f"cosine expected 1.0, got {score}"
    # Test orthogonal
    score2 = await conn.fetchval(
        "SELECT array_cosine_similarity("
        "ARRAY[1.0,0.0,0.0]::double precision[], "
        "ARRAY[0.0,1.0,0.0]::double precision[]) "
    )
    assert abs(score2 - 0.0) < 0.001, f"orthogonal expected 0.0, got {score2}"
    await conn.execute("DELETE FROM image_vision_vectors WHERE id='e2e-img'")


async def _test_workflow(conn):
    await conn.execute(
        "INSERT INTO workflow_definitions (id, name, definition) "
        "VALUES ('e2e-wf', 'Test WF', $1::jsonb)",
        '{"nodes":[],"edges":[]}',
    )
    await conn.execute(
        "INSERT INTO workflow_runs (run_id, workflow_id, status) "
        "VALUES ('e2e-run', 'e2e-wf', 'completed')"
    )
    row = await conn.fetchrow("SELECT * FROM workflow_runs WHERE run_id='e2e-run'")
    assert row and row["status"] == "completed", "run insert failed"
    # CASCADE delete
    await conn.execute("DELETE FROM workflow_definitions WHERE id='e2e-wf'")
    row = await conn.fetchrow("SELECT * FROM workflow_runs WHERE run_id='e2e-run'")
    assert row is None, "CASCADE delete failed"


async def _test_fault(conn):
    await conn.execute(
        "INSERT INTO fault_cases (id, title, equipment_type, fault_category, phenomenon, root_cause) "
        "VALUES ('e2e-fc', 'Test Case', 'CNC', 'mechanical', 'noise', 'bearing wear')"
    )
    row = await conn.fetchrow("SELECT * FROM fault_cases WHERE id='e2e-fc'")
    assert row and row["title"] == "Test Case", "fault_cases insert failed"
    await conn.execute("DELETE FROM fault_cases WHERE id='e2e-fc'")


async def _test_process(conn):
    await conn.execute(
        "INSERT INTO process_documents (id, title, category, full_text) "
        "VALUES ('e2e-proc', 'Test Process', 'machining', 'CNC machining process')"
    )
    row = await conn.fetchrow("SELECT * FROM process_documents WHERE id='e2e-proc'")
    assert row and row["category"] == "machining", "process_documents insert failed"
    await conn.execute("DELETE FROM process_documents WHERE id='e2e-proc'")


async def _test_dashboard(conn):
    await conn.execute(
        "INSERT INTO dashboard_query_log (user_id, query, query_type, kb_name) "
        "VALUES ('e2e-user', 'test query', 'qa', 'default')"
    )
    row = await conn.fetchrow(
        "SELECT * FROM dashboard_query_log WHERE user_id='e2e-user' "
        "ORDER BY created_at DESC LIMIT 1"
    )
    assert row and row["query"] == "test query", "dashboard_query_log insert failed"
    await conn.execute("DELETE FROM dashboard_query_log WHERE user_id='e2e-user'")


if __name__ == "__main__":
    ok = asyncio.run(test())
    sys.exit(0 if ok else 1)
