import pytest
from fastapi import HTTPException


@pytest.mark.asyncio
async def test_knowledge_stats_batch_filters_to_owner_visible_kbs(monkeypatch):
    from raganything.routers.knowledge import knowledge_stats_batch, KBStatsBatchRequest

    async def fake_load_kb_meta():
        return {
            "kb-a": {"owner_id": 1},
            "kb-b": {"owner_id": 2},
            "kb-c": {"owner_id": 1},
        }

    async def fake_compute_kb_stats(name):
        return {
            "documents": len(name),
            "entities": 1,
            "relations": 2,
            "chunks": 3,
        }

    monkeypatch.setattr(
        "raganything.routers.knowledge.load_kb_meta",
        fake_load_kb_meta,
    )
    monkeypatch.setattr(
        "raganything.routers.knowledge._compute_kb_stats_batch_fast",
        lambda names: {},
    )
    monkeypatch.setattr(
        "raganything.routers.knowledge._compute_kb_stats",
        fake_compute_kb_stats,
    )

    current_user = {
        "id": 1,
        "username": "alice",
        "is_admin": False,
        "allowed_kbs": [],
    }

    result = await knowledge_stats_batch(
        req=KBStatsBatchRequest(kb_names=["kb-a", "kb-b", "kb-c", "kb-a", "missing"]),
        current_user=current_user,
    )

    assert set(result["stats"]) == {"kb-a", "kb-c"}
    assert result["stats"]["kb-a"]["documents"] == 4
    assert result["stats"]["kb-c"]["documents"] == 4


@pytest.mark.asyncio
async def test_knowledge_stats_batch_marks_timeout_as_unavailable(monkeypatch):
    from raganything.routers.knowledge import knowledge_stats_batch, KBStatsBatchRequest

    async def fake_load_kb_meta():
        return {
            "kb-a": {"owner_id": 1},
        }

    async def fake_compute_kb_stats(name):
        raise TimeoutError(f"{name} timed out")

    monkeypatch.setattr(
        "raganything.routers.knowledge.load_kb_meta",
        fake_load_kb_meta,
    )
    monkeypatch.setattr(
        "raganything.routers.knowledge._compute_kb_stats_batch_fast",
        lambda names: {},
    )
    monkeypatch.setattr(
        "raganything.routers.knowledge._compute_kb_stats",
        fake_compute_kb_stats,
    )

    current_user = {
        "id": 1,
        "username": "alice",
        "is_admin": True,
        "allowed_kbs": [],
    }

    result = await knowledge_stats_batch(
        req=KBStatsBatchRequest(kb_names=["kb-a"]),
        current_user=current_user,
    )

    assert result["stats"]["kb-a"]["unavailable"] is True
    assert result["stats"]["kb-a"]["documents"] == 0


@pytest.mark.asyncio
async def test_knowledge_stats_batch_prefers_batched_fast_path(monkeypatch):
    from raganything.routers.knowledge import knowledge_stats_batch, KBStatsBatchRequest

    async def fake_load_kb_meta():
        return {
            "kb-a": {"owner_id": 1},
            "kb-c": {"owner_id": 1},
        }

    async def fake_batch_stats(names):
        assert names == ["kb-a", "kb-c"]
        return {
            "kb-a": {"documents": 2, "entities": 3, "relations": 4, "chunks": 5},
            "kb-c": {"documents": 6, "entities": 7, "relations": 8, "chunks": 9},
        }

    async def fail_single_kb(_name):
        raise AssertionError("single-KB fallback should not run when batch path succeeds")

    monkeypatch.setattr(
        "raganything.routers.knowledge.load_kb_meta",
        fake_load_kb_meta,
    )
    monkeypatch.setattr(
        "raganything.routers.knowledge._compute_kb_stats_batch_fast",
        fake_batch_stats,
    )
    monkeypatch.setattr(
        "raganything.routers.knowledge._compute_kb_stats",
        fail_single_kb,
    )

    current_user = {
        "id": 1,
        "username": "alice",
        "is_admin": False,
        "allowed_kbs": [],
    }

    result = await knowledge_stats_batch(
        req=KBStatsBatchRequest(kb_names=["kb-a", "kb-c"]),
        current_user=current_user,
    )

    assert result["stats"]["kb-a"]["documents"] == 2
    assert result["stats"]["kb-c"]["chunks"] == 9


@pytest.mark.asyncio
async def test_list_kbs_embeds_stats_from_fast_batch_path(monkeypatch):
    from raganything.routers.knowledge import list_kbs

    async def fake_load_kb_meta():
        return {
            "kb-a": {"name": "KB A", "created": "2026-07-01", "owner_id": 1, "owner_username": "alice"},
            "kb-b": {"name": "KB B", "created": "2026-07-02", "owner_id": 2, "owner_username": "bob"},
        }

    async def fake_batch_stats(names):
        assert names == ["kb-a"]
        return {
            "kb-a": {"documents": 3, "entities": 4, "relations": 5, "chunks": 6},
        }

    monkeypatch.setattr(
        "raganything.routers.knowledge.load_kb_meta",
        fake_load_kb_meta,
    )
    monkeypatch.setattr(
        "raganything.routers.knowledge._compute_kb_stats_batch_fast",
        fake_batch_stats,
    )
    monkeypatch.setattr(
        "raganything.routers.knowledge._shared.active_kb",
        "kb-a",
    )

    current_user = {
        "id": 1,
        "username": "alice",
        "is_admin": False,
        "allowed_kbs": [],
    }

    result = await list_kbs(current_user=current_user)

    assert result["knowledge_bases"][0]["name"] == "kb-a"
    assert result["knowledge_bases"][0]["stats"]["documents"] == 3

