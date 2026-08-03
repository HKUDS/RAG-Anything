import asyncio
from pathlib import Path
from types import SimpleNamespace

import pytest


@pytest.fixture(autouse=True)
def _reset_controlled_roots_cache(tmp_path, monkeypatch):
    """Clear the process-level controlled-roots TTL cache per test and pin
    the project root to a temp dir so real repo `output*` dirs stay inert."""
    from raganything.services.odl_media_delivery import _reset_controlled_roots_cache

    _reset_controlled_roots_cache()
    monkeypatch.setattr(
        "raganything.services.odl_media_delivery._project_root",
        lambda: Path(tmp_path),
    )


def _write_png(path: Path, size: int = 16) -> None:
    path.write_bytes(b"\x89PNG\r\n\x1a\n" + (b"0" * size))


def _controlled_marker(path: Path, *, chinese: bool = False, full_width: bool = False) -> str:
    colon = "：" if full_width else ":"
    if chinese:
        return f"[图片路径{colon}{path}]"
    return f"Image Path{colon} {path}"


def _allow_controlled_root(monkeypatch, root: Path) -> None:
    monkeypatch.setenv("ODL_LEGACY_MEDIA_ROOTS", str(root))


@pytest.mark.asyncio
async def test_recall_query_images_direct_keeps_first_three(monkeypatch, tmp_path):
    from raganything.routers import shared

    _allow_controlled_root(monkeypatch, tmp_path)
    paths = []
    for idx in range(4):
        img = tmp_path / f"direct-{idx}.png"
        _write_png(img)
        paths.append(str(img))

    def fail_filter(*args, **kwargs):
        raise AssertionError("direct recall should not run relevance filter")

    monkeypatch.setattr(shared, "_filter_images_by_relevance", fail_filter)

    ctx = "\n".join(_controlled_marker(path) for path in paths)
    images, backfill, source = await shared.recall_query_images(object(), "query", "demo", ctx)

    assert source == "direct"
    assert backfill == ""
    assert images == paths[:3]


@pytest.mark.asyncio
async def test_recall_query_images_falls_back_to_graph_and_soft_keeps_one(monkeypatch, tmp_path):
    from raganything.routers import shared

    _allow_controlled_root(monkeypatch, tmp_path)
    graph_img = tmp_path / "graph-hit.png"
    _write_png(graph_img)

    async def fake_graph(instance, query, kb_name, ctx):
        return [str(graph_img)], "graph backfill"

    async def fake_bigram(*args, **kwargs):
        return [], ""

    monkeypatch.setattr(shared, "_discover_images_via_graph", fake_graph)
    monkeypatch.setattr(shared, "_bigram_image_scan", fake_bigram)
    monkeypatch.setattr(shared, "_filter_images_by_relevance", lambda *args, **kwargs: [])

    images, backfill, source = await shared.recall_query_images(object(), "???????", "demo", "ctx")

    assert source == "graph"
    assert backfill == "graph backfill"
    assert images == [str(graph_img)]


@pytest.mark.asyncio
async def test_recall_query_images_falls_back_to_bigram_and_drops_invalid(monkeypatch, tmp_path):
    from raganything.routers import shared

    _allow_controlled_root(monkeypatch, tmp_path)
    valid_img = tmp_path / "bigram-hit.png"
    _write_png(valid_img)

    async def fake_graph(instance, query, kb_name, ctx):
        return [], ""

    async def fake_bigram(*args, **kwargs):
        return [str(valid_img), str(tmp_path / "missing.png")], "bigram backfill"

    monkeypatch.setattr(shared, "_discover_images_via_graph", fake_graph)
    monkeypatch.setattr(shared, "_bigram_image_scan", fake_bigram)
    monkeypatch.setattr(shared, "_filter_images_by_relevance", lambda paths, *args, **kwargs: list(paths))

    images, backfill, source = await shared.recall_query_images(object(), "?1?????", "demo", "ctx")

    assert source == "bigram"
    assert backfill == "bigram backfill"
    assert images == [str(valid_img)]


def test_extract_image_paths_accepts_both_protocols_and_deduplicates(monkeypatch, tmp_path):
    from raganything.routers import shared

    _allow_controlled_root(monkeypatch, tmp_path)
    first = tmp_path / "first.png"
    second = tmp_path / "second.png"
    _write_png(first)
    _write_png(second)

    result = shared.extract_image_paths_with_stats(
        "\n".join((
            _controlled_marker(first),
            _controlled_marker(first, chinese=True, full_width=True),
            _controlled_marker(second, full_width=True),
            "[图片路径:]",
        ))
    )

    assert result.paths == [str(first.resolve()), str(second.resolve())]
    assert result.candidate_count == 4
    assert result.protocol_counts == {"english": 2, "chinese": 2}
    assert result.rejection_counts["empty"] == 1


def test_extract_image_paths_rejects_uncontrolled_and_invalid_paths(monkeypatch, tmp_path):
    from raganything.routers import shared

    controlled = tmp_path / "controlled"
    controlled.mkdir()
    _allow_controlled_root(monkeypatch, controlled)
    valid = controlled / "valid.png"
    _write_png(valid)
    outside = tmp_path / "outside.png"
    _write_png(outside)
    non_image = controlled / "not-image.txt"
    non_image.write_text("not an image", encoding="utf-8")

    result = shared.extract_image_paths_with_stats(
        "\n".join((
            _controlled_marker(valid),
            _controlled_marker(outside),
            _controlled_marker(controlled / "missing.png", chinese=True),
            _controlled_marker(non_image),
            _controlled_marker(controlled / "nested" / ".." / "valid.png"),
        ))
    )

    assert result.paths == [str(valid.resolve())]
    assert result.rejection_counts["outside_controlled_root"] == 1
    assert result.rejection_counts["missing"] == 1
    assert result.rejection_counts["unsupported_extension"] == 1
    # A normalised root-internal path is not traversal and resolves to the
    # same controlled asset, so it contributes no second returned path.
    assert result.candidate_count == 5


def test_extract_image_paths_rejects_symlink_escape(monkeypatch, tmp_path):
    from raganything.routers import shared

    controlled = tmp_path / "controlled"
    controlled.mkdir()
    _allow_controlled_root(monkeypatch, controlled)
    outside = tmp_path / "outside.png"
    _write_png(outside)
    link = controlled / "escaped.png"
    try:
        link.symlink_to(outside)
    except OSError:
        pytest.skip("symlink creation is unavailable for this test account")

    result = shared.extract_image_paths_with_stats(_controlled_marker(link))

    assert result.paths == []
    assert result.rejection_counts == {"symlink": 1}


@pytest.mark.asyncio
async def test_graph_timeout_does_not_discard_direct_or_local_images(
    monkeypatch, tmp_path
):
    from raganything.routers import shared

    _allow_controlled_root(monkeypatch, tmp_path)
    direct_img = tmp_path / "direct.png"
    local_img = tmp_path / "local.png"
    _write_png(direct_img)
    _write_png(local_img)

    async def fake_bigram(*args, **kwargs):
        return [str(local_img)], "local backfill"

    class SlowGraphRetriever:
        async def search_with_paths(self, query, top_k):
            await asyncio.sleep(0.2)
            return {"matched_entities": [], "results": []}

    instance = SimpleNamespace(
        hybrid_search_engine=SimpleNamespace(
            graph_retriever=SlowGraphRetriever()
        )
    )
    real_graph = shared._discover_images_via_graph

    async def graph_with_test_budget(instance, query, kb_name, ctx):
        return await real_graph(
            instance,
            query,
            kb_name,
            ctx,
            timeout_budget_seconds=0.05,
        )

    monkeypatch.setattr(shared, "_bigram_image_scan", fake_bigram)
    monkeypatch.setattr(shared, "_discover_images_via_graph", graph_with_test_budget)
    monkeypatch.setattr(shared, "_filter_images_by_relevance", lambda paths, *args, **kwargs: list(paths))
    graph_logs = []

    def capture_graph_warning(message, *args):
        graph_logs.append(message % args if args else message)

    monkeypatch.setattr(shared.lightrag_logger, "warning", capture_graph_warning)

    images, backfill, source = await shared.recall_query_images(
        instance, "query", "demo", _controlled_marker(direct_img)
    )

    assert source == "direct"
    assert images == [str(direct_img.resolve()), str(local_img)]
    assert backfill == "local backfill"
    assert len(graph_logs) == 1
    assert "outcome=timeout" in graph_logs[0]
    assert "attempt_count=1" in graph_logs[0]
    assert "timeout_budget_ms=50" in graph_logs[0]
    assert "elapsed_ms=" in graph_logs[0]


@pytest.mark.asyncio
async def test_recall_query_images_without_images_returns_empty(monkeypatch):
    from raganything.routers import shared

    async def fake_bigram(*args, **kwargs):
        return [], ""

    async def fake_graph(*args, **kwargs):
        return [], ""

    monkeypatch.setattr(shared, "_bigram_image_scan", fake_bigram)
    monkeypatch.setattr(shared, "_discover_images_via_graph", fake_graph)

    images, backfill, source = await shared.recall_query_images(object(), "query", "demo", "plain text")

    assert images == []
    assert backfill == ""
    assert source == "none"


class _DummyRAG:
    def __init__(self, working_dir: str):
        self.working_dir = working_dir

    async def aquery(self, query, mode="rrf", only_need_context=True, top_k=10):
        return "Image Path: C:/tmp/demo.png\n[Image: Demo image]"


@pytest.mark.asyncio
async def test_qa_engine_answer_stream_emits_recalled_images(monkeypatch, tmp_path):
    from raganything.autorepair.agent.qa_engine import QAEngine

    img = tmp_path / "recalled.png"
    _write_png(img)

    async def dummy_llm(prompt, system_prompt=None, history_messages=None, **kw):
        return "answer text"

    engine = QAEngine(
        rag_client=_DummyRAG(str(tmp_path / "rag_storage_demo")),
        llm_client=dummy_llm,
        kb_name="demo",
        media_url_resolver=lambda _path: f"/api/knowledge/media/legacy/{_legacy_grant()}?kb=demo",
    )

    async def fake_direct_retrieve(query):
        return f"Image Path: {img}\nCaptions: ?????"

    async def fake_recall_query_images(instance, query, kb_name, ctx):
        assert kb_name == "demo"
        return [str(img)], "", "direct"

    monkeypatch.setattr(engine, "_direct_retrieve", fake_direct_retrieve)
    monkeypatch.setattr("raganything.autorepair.agent.qa_engine.recall_query_images", fake_recall_query_images)

    events = []
    async for event in engine.answer_stream("??????????"):
        events.append(event)

    done_event = next(event for event in events if event["type"] == "done")
    assert len(done_event["images"]) == 1
    assert done_event["images"][0]["data_url"].startswith("/api/knowledge/media/legacy/")
    assert done_event["images"][0]["caption"] == "?????"
    assert done_event["images"][0]["page"] is None


@pytest.mark.asyncio
async def test_qa_engine_answer_stream_uses_fallback_when_shared_recall_is_empty(monkeypatch, tmp_path):
    from raganything.autorepair.agent.qa_engine import QAEngine

    img = tmp_path / "fallback.png"
    _write_png(img)

    async def dummy_llm(prompt, system_prompt=None, history_messages=None, **kw):
        return "answer text"

    engine = QAEngine(
        rag_client=_DummyRAG(str(tmp_path / "rag_storage_demo")),
        llm_client=dummy_llm,
        kb_name="demo",
        media_url_resolver=lambda _path: f"/api/knowledge/media/legacy/{_legacy_grant()}?kb=demo",
    )

    async def fake_direct_retrieve(query):
        return "fallback context with no direct image path but enough content " * 3

    async def fake_recall_query_images(instance, query, kb_name, ctx):
        return [], "", "none"

    monkeypatch.setattr(engine, "_direct_retrieve", fake_direct_retrieve)
    monkeypatch.setattr("raganything.autorepair.agent.qa_engine.recall_query_images", fake_recall_query_images)
    monkeypatch.setattr(
        engine,
        "_match_relevant_images",
        lambda query, docs: [{"_local_path": str(img), "caption": "fallback", "page": 2, "relevance": 0.7}],
    )

    events = []
    async for event in engine.answer_stream("fallback query"):
        events.append(event)

    done_event = next(event for event in events if event["type"] == "done")
    assert done_event["images"] == [{
        "data_url": f"/api/knowledge/media/legacy/{_legacy_grant()}?kb=demo",
        "url": f"/api/knowledge/media/legacy/{_legacy_grant()}?kb=demo",
        "caption": "fallback",
        "page": 2,
        "relevance": 0.7,
    }]


@pytest.mark.asyncio
async def test_qa_engine_answer_stream_skips_missing_or_unencodable_images(monkeypatch, tmp_path):
    from raganything.autorepair.agent.qa_engine import QAEngine

    async def dummy_llm(prompt, system_prompt=None, history_messages=None, **kw):
        return "answer text"

    engine = QAEngine(
        rag_client=_DummyRAG(str(tmp_path / "rag_storage_demo")),
        llm_client=dummy_llm,
        kb_name="demo",
    )

    async def fake_direct_retrieve(query):
        return "Image Path: missing.png\nCaptions: missing"

    async def fake_recall_query_images(instance, query, kb_name, ctx):
        return [str(tmp_path / "missing.png")], "", "direct"

    monkeypatch.setattr(engine, "_direct_retrieve", fake_direct_retrieve)
    monkeypatch.setattr("raganything.autorepair.agent.qa_engine.recall_query_images", fake_recall_query_images)
    monkeypatch.setattr(engine, "_match_relevant_images", lambda query, docs: [])

    events = []
    async for event in engine.answer_stream("missing image"):
        events.append(event)

    done_event = next(event for event in events if event["type"] == "done")
    assert done_event["images"] == []


def _legacy_grant() -> str:
    return f"abcdefghijklmnopqrstuvwx.{ 'a' * 64 }"
