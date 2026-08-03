# -*- coding: utf-8 -*-
"""KB list timestamp semantics: last_content_updated_at uses kb_metadata.updated_at."""
import pytest
from datetime import datetime, timezone


@pytest.mark.asyncio
async def test_list_kbs_uses_updated_at_with_created_fallback(monkeypatch):
    from raganything.routers.knowledge import list_kbs

    async def fake_load_kb_meta():
        return {
            "kb-a": {
                "name": "知识库A",
                "created": "2026-07-01T00:00:00+00:00",
                "updated_at": "2026-08-01T02:00:00+00:00",
                "owner_id": 1,
                "owner_username": "alice",
            },
            "kb-b": {
                "name": "知识库B",
                "created": "2026-07-02T00:00:00+00:00",
                "owner_id": 1,
                "owner_username": "alice",
            },
        }

    monkeypatch.setattr("raganything.routers.knowledge.load_kb_meta", fake_load_kb_meta)
    async def fake_stats(names):
        return {}

    monkeypatch.setattr(
        "raganything.routers.knowledge._compute_kb_stats_batch_fast",
        fake_stats,
    )

    current_user = {"id": 1, "username": "alice", "is_admin": False}
    result = await list_kbs(current_user=current_user)
    by_name = {kb["name"]: kb for kb in result["knowledge_bases"]}

    assert by_name["kb-a"]["last_content_updated_at"] == "2026-08-01T02:00:00+00:00"
    assert by_name["kb-b"]["last_content_updated_at"] == "2026-07-02T00:00:00+00:00"


@pytest.mark.asyncio
async def test_create_kb_writes_utc_aware_created(monkeypatch):
    from raganything.routers.knowledge import create_kb

    captured = {}

    async def fake_load_kb_meta():
        return {}

    async def fake_save_kb_meta(meta):
        captured["meta"] = meta

    async def fake_get_kb(name):
        return None

    class _FakeProfile:
        fingerprint = "fp-1"
        profile = type("P", (), {"embedding_dim": 1024})()

    async def fake_platform_defaults():
        return {"vision_embedding_profile_id": "profile-1"}

    def fake_get_entry(profile_id, kind):
        return _FakeProfile()

    monkeypatch.setattr("raganything.routers.knowledge.load_kb_meta", fake_load_kb_meta)
    monkeypatch.setattr("raganything.routers.knowledge.save_kb_meta", fake_save_kb_meta)
    monkeypatch.setattr("raganything.routers.knowledge.get_kb", fake_get_kb)
    monkeypatch.setattr(
        "raganything.services.vision_models.get_platform_defaults",
        fake_platform_defaults,
    )
    monkeypatch.setattr(
        "raganything.services.vision_models.get_entry",
        fake_get_entry,
    )

    current_user = {"id": 7, "username": "bob"}
    result = await create_kb(
        kb_name="new-kb",
        _perm=None,
        current_user=current_user,
    )
    assert result["status"] == "created"
    created = captured["meta"]["new-kb"]["created"]
    parsed = datetime.fromisoformat(created)
    assert parsed.tzinfo is not None
    assert parsed.utcoffset() == timezone.utc.utcoffset(parsed)


@pytest.mark.asyncio
async def test_pg_save_all_kb_meta_preserves_existing_updated_at(monkeypatch):
    from raganything.services import pg_kb_meta_repo

    captured_sql = []
    captured_args = []

    class FakeTransaction:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

    class FakeConn:
        def transaction(self):
            return FakeTransaction()

        async def execute(self, sql, *args):
            captured_sql.append(sql)
            captured_args.append(args)

    class FakePool:
        def acquire(self):
            return FakeAcquire()

    class FakeAcquire:
        async def __aenter__(self):
            return FakeConn()

        async def __aexit__(self, *exc):
            return False

    monkeypatch.setattr(pg_kb_meta_repo, "_get_pool", lambda: FakePool())

    await pg_kb_meta_repo.pg_save_all_kb_meta(
        {
            "kb-x": {
                "name": "X",
                "created": "2026-06-01T00:00:00",
                "owner_id": 1,
            }
        }
    )

    assert len(captured_sql) == 1
    sql = captured_sql[0]
    # Existing rows keep their updated_at; only new rows get created_at == updated_at.
    assert "updated_at = EXCLUDED.updated_at" not in sql
    args = captured_args[0]
    created_arg = args[-2]
    updated_arg = args[-1]
    assert created_arg == updated_arg
    assert created_arg.tzinfo is not None
    assert created_arg.utcoffset() == timezone.utc.utcoffset(created_arg)
