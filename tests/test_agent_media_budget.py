import asyncio
import json
from types import SimpleNamespace

import pytest


def _instance():
    return SimpleNamespace(lightrag=SimpleNamespace(text_chunks=object()))


@pytest.mark.parametrize(
    ("raw", "expected"),
    (
        ("", 8.0),
        ("invalid", 8.0),
        ("NaN", 8.0),
        ("inf", 8.0),
        ("-inf", 8.0),
        ("0", 0.1),
        ("-2", 0.1),
        ("1.25", 1.25),
    ),
)
def test_media_timeout_configuration_is_finite_and_bounded(monkeypatch, raw, expected):
    from raganything.routers import agent

    monkeypatch.setenv("AGENT_MEDIA_RECALL_TIMEOUT", raw)

    assert agent._agent_media_recall_timeout() == expected


@pytest.mark.asyncio
async def test_media_budget_is_independent_of_expired_retrieval_deadline(monkeypatch):
    from raganything.routers import agent

    async def recall(*_args):
        return ["/controlled/one.png"], "", "direct"

    async def resolve(*, kb_name, image_path, text_chunk_reader=None):
        return {"media_id": "one", "kb": kb_name, "url": "/media/one"}

    monkeypatch.setenv("AGENT_MEDIA_RECALL_TIMEOUT", "0.2")
    monkeypatch.setattr(agent, "recall_query_images", recall)
    monkeypatch.setattr(agent, "resolve_controlled_media_payload", resolve)

    retrieval_deadline = asyncio.get_running_loop().time() - 1
    images, backfill, source, timed_out = await agent._recall_controlled_media_with_budget(
        _instance(), "query", "kb", "context"
    )

    assert retrieval_deadline < asyncio.get_running_loop().time()
    assert images == [{"media_id": "one", "kb": "kb", "url": "/media/one"}]
    assert backfill == ""
    assert source == "direct"
    assert timed_out is False


@pytest.mark.asyncio
async def test_media_timeout_keeps_already_validated_payloads(monkeypatch):
    from raganything.routers import agent

    paths = ["/controlled/one.png", "/controlled/two.png", "/controlled/three.png"]
    resolved_paths = []

    async def recall(*_args):
        return paths, "backfill", "direct"

    async def resolve(*, kb_name, image_path, text_chunk_reader=None):
        resolved_paths.append(image_path)
        if image_path == paths[1]:
            await asyncio.sleep(0.2)
        return {
            "media_id": image_path.rsplit("/", 1)[-1],
            "kb": kb_name,
            "url": "/media/controlled",
        }

    monkeypatch.setenv("AGENT_MEDIA_RECALL_TIMEOUT", "0.05")
    monkeypatch.setattr(agent, "recall_query_images", recall)
    monkeypatch.setattr(agent, "resolve_controlled_media_payload", resolve)

    images, backfill, source, timed_out = await agent._recall_controlled_media_with_budget(
        _instance(), "query", "kb", "context"
    )

    assert timed_out is True
    assert images == [{
        "media_id": "one.png",
        "kb": "kb",
        "url": "/media/controlled",
    }]
    assert backfill == "backfill"
    assert source == "direct"
    assert resolved_paths == paths[:2]
    assert "/controlled/" not in json.dumps(images)


@pytest.mark.asyncio
async def test_media_budget_propagates_cancellation(monkeypatch):
    from raganything.routers import agent

    async def recall(*_args):
        return ["/controlled/one.png"], "", "direct"

    async def resolve(**_kwargs):
        raise asyncio.CancelledError

    monkeypatch.setenv("AGENT_MEDIA_RECALL_TIMEOUT", "1")
    monkeypatch.setattr(agent, "recall_query_images", recall)
    monkeypatch.setattr(agent, "resolve_controlled_media_payload", resolve)

    with pytest.raises(asyncio.CancelledError):
        await agent._recall_controlled_media_with_budget(
            _instance(), "query", "kb", "context"
        )


@pytest.mark.asyncio
async def test_media_budget_preserves_three_image_cap(monkeypatch):
    from raganything.routers import agent

    paths = [f"/controlled/{index}.png" for index in range(5)]
    resolved_paths = []

    async def recall(*_args):
        return paths, "", "direct"

    async def resolve(*, kb_name, image_path, text_chunk_reader=None):
        resolved_paths.append(image_path)
        return {"media_id": image_path, "kb": kb_name, "url": "/media/controlled"}

    monkeypatch.setenv("AGENT_MEDIA_RECALL_TIMEOUT", "1")
    monkeypatch.setattr(agent, "recall_query_images", recall)
    monkeypatch.setattr(agent, "resolve_controlled_media_payload", resolve)

    images, _backfill, _source, timed_out = await agent._recall_controlled_media_with_budget(
        _instance(), "query", "kb", "context"
    )

    assert timed_out is False
    assert len(images) == 3
    assert resolved_paths == paths[:3]
