import asyncio
import logging
import time
from types import SimpleNamespace

import pytest

import raganything.agentic_rag.tools as agent_tools
import raganything.query.pipeline as query_pipeline
from raganything.agentic_rag.tools import SearchTool
from raganything.hybrid_search import ScoredChunk
from raganything.query.pipeline import QueryMixin
from raganything.query.tag_scoped_retriever import TagScope, retrieve_tag_scoped_context
from raganything.services.query_execution import QueryExecutionScope, await_before_deadline
from raganything.services.query_timing import QueryTiming


@pytest.mark.asyncio
async def test_deadline_returns_without_waiting_for_cancelled_cleanup():
    cancelled = asyncio.Event()

    async def slow_operation():
        try:
            await asyncio.sleep(1)
        finally:
            cancelled.set()

    started = time.perf_counter()
    with pytest.raises(TimeoutError):
        await await_before_deadline(slow_operation(), time.monotonic() + 0.01)

    assert time.perf_counter() - started < 0.2
    await asyncio.wait_for(cancelled.wait(), timeout=0.2)


@pytest.mark.asyncio
async def test_deadline_detaches_shared_initialization_without_cancelling_it():
    completed = asyncio.Event()

    async def shared_initialization():
        await asyncio.sleep(0.03)
        completed.set()
        return "ready"

    with pytest.raises(TimeoutError):
        await await_before_deadline(
            shared_initialization(),
            time.monotonic() + 0.001,
            cancel_on_timeout=False,
        )

    await asyncio.wait_for(completed.wait(), timeout=0.2)


@pytest.mark.asyncio
async def test_tag_scope_honors_the_request_deadline():
    class SlowChunks:
        async def get_by_ids(self, _ids):
            await asyncio.sleep(1)
            return []

    instance = SimpleNamespace(lightrag=SimpleNamespace(text_chunks=SlowChunks()))
    result = await retrieve_tag_scoped_context(
        instance,
        TagScope(1, "tag", ("chunk-1",)),
        "query",
        deadline_monotonic=time.monotonic() + 0.01,
    )

    assert result == ""


@pytest.mark.asyncio
async def test_rrf_post_processing_does_not_outlive_retrieval_deadline():
    graph_called = False

    class SlowGraph:
        async def get_all_nodes(self):
            nonlocal graph_called
            graph_called = True
            await asyncio.sleep(1)
            return []

    class Engine:
        _lightrag = SimpleNamespace(chunk_entity_relation_graph=SlowGraph())

        async def search(self, *_args, **_kwargs):
            return [ScoredChunk("chunk-1", "usable context", 1.0, ["vector"])]

    query = object.__new__(QueryMixin)
    query.hybrid_search_engine = Engine()
    query.callback_manager = None
    query.logger = logging.getLogger("raganything.query.pipeline")

    async def source_info(_chunk_ids):
        return {"chunk-1": {"document_name": "Visible source"}}

    query.batch_get_doc_source_info_async = source_info

    started = time.perf_counter()
    context = await query._aquery_rrf(
        "deadline test",
        only_need_context=True,
        query_execution_scope={"deadline_monotonic": time.monotonic() + 0.01},
    )

    assert time.perf_counter() - started < 0.2
    assert graph_called is False
    assert "[来源 Visible source]" in context
    assert "usable context" in context


@pytest.mark.asyncio
async def test_rrf_context_source_lookup_settles_before_router_watchdog():
    cancelled = asyncio.Event()

    class Engine:
        _lightrag = SimpleNamespace(chunk_entity_relation_graph=None)

        async def search(self, *_args, **_kwargs):
            return [ScoredChunk("chunk-1", "usable context", 1.0, ["vector"])]

    query = object.__new__(QueryMixin)
    query.hybrid_search_engine = Engine()
    query.callback_manager = None
    query.logger = logging.getLogger("raganything.query.pipeline")

    async def slow_source_info(_chunk_ids):
        try:
            await asyncio.Event().wait()
        finally:
            cancelled.set()

    query.batch_get_doc_source_info_async = slow_source_info
    deadline = asyncio.get_running_loop().time() + 0.2
    task = asyncio.create_task(
        query._aquery_rrf(
            "deadline test",
            only_need_context=True,
            query_execution_scope={"deadline_monotonic": deadline},
        )
    )

    while not task.done():
        assert asyncio.get_running_loop().time() < deadline
        await asyncio.sleep(min(0.06, deadline - asyncio.get_running_loop().time()))

    context = await task
    assert "usable context" in context
    await asyncio.wait_for(cancelled.wait(), timeout=0.2)


@pytest.mark.asyncio
async def test_agentic_search_forwards_immutable_scope_and_options():
    captured = {}

    class KB:
        async def aquery(self, _query, **kwargs):
            captured.update(kwargs)
            return "context"

    scope = QueryExecutionScope(
        trace_id="trace-test",
        workspace="kb",
        corpus_revision="revision",
        permission_scope="scope",
        settings_fingerprint="settings",
        llm_profile_fingerprint="llm",
        deadline_monotonic=time.monotonic() + 1,
    )
    options = object()
    result = await SearchTool(
        KB(),
        retrieval_options=options,
        query_execution_scope=scope,
    ).execute({"query": "question"})

    assert result == "context"
    assert captured["retrieval_options"] is options
    assert captured["query_execution_scope"] is scope


@pytest.mark.asyncio
async def test_concurrent_searches_keep_profiles_options_and_workspaces_isolated():
    calls = []

    class KB:
        async def aquery(self, _query, **kwargs):
            await asyncio.sleep(0)
            calls.append((kwargs["query_execution_scope"], kwargs["retrieval_options"]))
            return "context"

    first = QueryExecutionScope(
        "trace-a", "workspace-a", "revision-a", "user:1", "settings-a", "llm-a",
        time.monotonic() + 1,
    )
    second = QueryExecutionScope(
        "trace-b", "workspace-b", "revision-b", "user:2", "settings-b", "llm-b",
        time.monotonic() + 1,
    )
    first_options = object()
    second_options = object()
    await asyncio.gather(
        SearchTool(KB(), retrieval_options=first_options, query_execution_scope=first)
        .execute({"query": "one"}),
        SearchTool(KB(), retrieval_options=second_options, query_execution_scope=second)
        .execute({"query": "two"}),
    )

    assert {(scope.trace_id, options) for scope, options in calls} == {
        ("trace-a", first_options), ("trace-b", second_options)
    }


def test_query_timing_never_accepts_query_content(caplog):
    secret_prompt = "sensitive-question-must-not-appear"
    with caplog.at_level("INFO"):
        timing = QueryTiming("trace-private")
        timing.start("retrieval")
        timing.finish("retrieval", channel="bm25")

    assert secret_prompt not in caplog.text
    assert "trace-private" in caplog.text


@pytest.mark.asyncio
async def test_vlm_image_path_logs_are_content_free(tmp_path, monkeypatch, caplog):
    query = object.__new__(QueryMixin)
    query.logger = logging.getLogger("raganything.query.pipeline")
    known_path = r"C:\\private\\patient-image.png"
    safe_path = str(tmp_path / "provider-image.png")
    provider_error = "provider echoed SENSITIVE_PROMPT /private/provider-request"

    monkeypatch.setattr(query_pipeline, "validate_image_file", lambda _path: True)

    def raise_provider_error(_path):
        raise RuntimeError(provider_error)

    monkeypatch.setattr(query_pipeline, "encode_image_to_base64", raise_provider_error)
    prompt = f"Image Path: {known_path}\nImage Path: {safe_path}"

    with caplog.at_level(logging.DEBUG, logger="raganything.query.pipeline"):
        enhanced, processed = await query._process_image_paths_for_vlm(
            prompt,
            extra_safe_dirs=[str(tmp_path)],
        )

    assert enhanced == prompt
    assert processed == 0
    assert known_path not in caplog.text
    assert safe_path not in caplog.text
    assert provider_error not in caplog.text
    assert "Blocking image outside approved directories" in caplog.text
    assert "Controlled image processing failed" in caplog.text


def test_query_timing_closes_cancelled_phase_and_total_once(caplog):
    with caplog.at_level("INFO"):
        timing = QueryTiming("trace-cancelled")
        timing.start("media")
        timing.total(outcome="cancelled")

    messages = [record.getMessage() for record in caplog.records]
    assert sum("phase=media outcome=cancelled" in message for message in messages) == 1
    assert sum("phase=total outcome=cancelled" in message for message in messages) == 1


@pytest.mark.asyncio
async def test_agentic_search_records_cancelled_retrieval_without_query_content(monkeypatch):
    events = []

    class RecordingTiming:
        def __init__(self, trace_id):
            assert trace_id == "trace-private"

        def record(self, phase, _elapsed, **labels):
            events.append((phase, labels["outcome"]))

    class KB:
        async def aquery(self, *_args, **_kwargs):
            await asyncio.Event().wait()

    monkeypatch.setattr(agent_tools, "QueryTiming", RecordingTiming)
    scope = QueryExecutionScope(
        trace_id="trace-private",
        workspace="kb",
        corpus_revision="revision",
        permission_scope="scope",
        settings_fingerprint="settings",
        llm_profile_fingerprint="llm",
        deadline_monotonic=time.monotonic() + 30,
    )
    task = asyncio.create_task(
        SearchTool(KB(), query_execution_scope=scope).execute(
            {"query": "sensitive-question-must-not-appear"}
        )
    )
    await asyncio.sleep(0)
    task.cancel()

    with pytest.raises(asyncio.CancelledError):
        await task
    assert events == [("retrieval", "cancelled")]


def test_multimodal_cache_key_uses_explicit_request_scope():
    query = object.__new__(QueryMixin)
    first = query._generate_multimodal_cache_key(
        "question", [{"type": "image", "image_path": "same.png"}], "hybrid",
        query_execution_scope={"permission_scope": "user:1", "corpus_revision": "one"},
    )
    second = query._generate_multimodal_cache_key(
        "question", [{"type": "image", "image_path": "same.png"}], "hybrid",
        query_execution_scope={"permission_scope": "user:2", "corpus_revision": "one"},
    )

    assert first != second
