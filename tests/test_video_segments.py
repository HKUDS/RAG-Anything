import asyncio
import logging
import pytest
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

from raganything.video_segments import plan_segments, segment_id
from lightrag.utils import compute_mdhash_id
from raganything.processor.chunk_processor import compute_chunk_id


def test_plan_segments_covers_video_with_bounds_and_overlap():
    segments = plan_segments(215.08)
    assert len(segments) > 1
    assert segments[0].start_ms == 0
    assert segments[-1].end_ms == 215080
    assert all(0 < s.duration_ms <= 30000 for s in segments)
    assert all(a.start_ms < a.end_ms for a in segments)
    assert all(a.end_ms >= b.start_ms for a, b in zip(segments, segments[1:]))


def test_plan_segments_uses_asr_text_and_scene_boundaries():
    segments = plan_segments(
        60,
        asr_segments=[{"start": 0, "end": 20, "text": "检查电池"}],
        scene_boundaries=[22, 45],
    )
    assert any("检查电池" in segment.transcript for segment in segments)
    assert segments[-1].end_ms == 60000


@pytest.mark.asyncio
async def test_v2_segment_description_and_chunk_template_are_chinese(monkeypatch, tmp_path):
    fixture = _build_v2_segment_fixture(tmp_path)
    captured = []
    _install_v2_processor_fakes(monkeypatch, fixture)

    async def chinese_description(_frames, _transcript, _start_ms, _end_ms):
        return "检查蓄电池电压并确认接线状态", [{"timestamp_ms": 0, "index": 0}]

    async def capture_chunk(chunk_text, segment_info, *_args, **_kwargs):
        captured.append((chunk_text, segment_info))
        chunk_id = compute_chunk_id(chunk_text)
        return segment_info["summary"], {"chunk_id": chunk_id}, []

    fixture.processor._describe_segment_frames = chinese_description
    fixture.processor._create_entity_and_chunk = capture_chunk
    fixture.processor._process_chunk_for_extraction = AsyncMock(return_value=[])
    await fixture.processor._process_v2_segments(
        {"video_path": fixture.video}, "video", "lesson.mp4", None,
        {"index": 0}, True, "doc-v1", 0,
    )

    assert captured
    first_chunk, first_entity = captured[0]
    assert "视频片段" in first_chunk
    assert "操作摘要" in first_chunk
    assert "检查蓄电池电压" in first_chunk
    assert "第1段" in first_entity["entity_name"]


@pytest.mark.asyncio
async def test_v2_segment_retries_english_summary_before_indexing(monkeypatch, tmp_path):
    fixture = _build_v2_segment_fixture(tmp_path)
    responses = iter(["请检查蓄电池端子是否牢固"])

    async def translate_once(*_args, **_kwargs):
        return next(responses)

    fixture.processor._call_modal_caption = translate_once

    assert await fixture.processor._ensure_chinese_segment_summary(
        "Inspect the battery terminals."
    ) == "请检查蓄电池端子是否牢固"


@pytest.mark.asyncio
async def test_v2_segment_rejects_english_summary_after_retry(monkeypatch, tmp_path):
    fixture = _build_v2_segment_fixture(tmp_path)

    async def still_english(*_args, **_kwargs):
        return "Inspect the battery terminals."

    fixture.processor._call_modal_caption = still_english

    from raganything.video_processor import VideoProcessingError

    with pytest.raises(VideoProcessingError, match="video_segment_summary_not_chinese"):
        await fixture.processor._ensure_chinese_segment_summary(
            "Inspect the battery terminals."
        )


def test_segment_id_is_retry_stable():
    args = ("a" * 64, 0, 24000, "v2")
    assert segment_id(*args) == segment_id(*args)
    assert segment_id(*args) != segment_id(args[0], 0, 24000, "v3")


def test_plan_rejects_invalid_duration():
    try:
        plan_segments(0)
    except ValueError as exc:
        assert str(exc) == "video_duration_invalid"
    else:
        raise AssertionError("invalid duration must fail")


def test_v2_probe_fails_closed_when_native_tool_is_missing(monkeypatch):
    from raganything import video_processor

    monkeypatch.setattr(video_processor, "_check_ffprobe_available", lambda: False)
    with pytest.raises(video_processor.VideoProcessingError) as exc:
        video_processor.probe_video_for_indexing("does-not-matter.mp4")
    assert exc.value.failure_code == "video_ffprobe_unavailable"
    assert "does-not-matter" not in str(exc.value)


def test_v2_probe_rejects_zero_duration_or_fps(monkeypatch):
    from raganything import video_processor

    monkeypatch.setattr(video_processor, "_check_ffprobe_available", lambda: True)
    monkeypatch.setattr(video_processor, "_check_ffmpeg_available", lambda: True)
    monkeypatch.setattr(video_processor, "validate_video_file", lambda _path: {
        "valid": True,
        "metadata": {"duration": 0, "fps": 0, "width": 1920, "height": 1080},
    })
    with pytest.raises(video_processor.VideoProcessingError) as exc:
        video_processor.probe_video_for_indexing("private.mp4")
    assert exc.value.failure_code == "video_probe_invalid_metadata"


@pytest.mark.asyncio
async def test_segment_rejects_when_every_representative_frame_cannot_encode():
    from raganything.video_processor import VideoModalProcessor, VideoProcessingError

    processor = object.__new__(VideoModalProcessor)
    processor._frame_semaphore = asyncio.Semaphore(1)
    processor._encode_image_to_base64 = lambda _path: ""
    processor._call_modal_caption = AsyncMock()
    frames = [
        {"path": "frame-a.png", "timestamp": 1.0, "index": 1},
        {"path": "frame-b.png", "timestamp": 2.0, "index": 2},
        {"path": "frame-c.png", "timestamp": 3.0, "index": 3},
    ]

    with pytest.raises(VideoProcessingError) as exc:
        await processor._describe_segment_frames(frames, "转写", 0, 3000)

    assert exc.value.failure_code == "video_frame_encode_failed"
    processor._call_modal_caption.assert_not_awaited()


def test_worker_gate_rejects_retired_video_profiles_and_probes_v2(monkeypatch):
    import process_worker

    calls = []
    monkeypatch.setattr(
        "raganything.video_processor.probe_video_for_indexing",
        lambda path: calls.append(path) or {},
    )
    for ingestion in (
        {"enable_video": True, "video_index_profile_version": "legacy"},
        {"enable_video": True},
        {"enable_video": True, "video_index_profile_version": "v3"},
    ):
        with pytest.raises(process_worker.RetiredVideoProfileError) as exc:
            process_worker._probe_video_indexing_gate("retired.mp4", ingestion)
        assert exc.value.failure_code == "video_profile_retired"
        assert process_worker._is_retryable_video_error(exc.value) is False

    assert calls == []
    process_worker._probe_video_indexing_gate(
        "new.mp4", {"enable_video": True, "video_index_profile_version": "v2"}
    )
    assert calls == ["new.mp4"]


def test_v2_probe_failure_remains_retryable(monkeypatch):
    import process_worker

    from raganything.video_processor import VideoProcessingError

    monkeypatch.setattr(
        "raganything.video_processor.probe_video_for_indexing",
        lambda _path: (_ for _ in ()).throw(VideoProcessingError("video_ffprobe_unavailable")),
    )
    with pytest.raises(process_worker.RetryableVideoProcessingError) as exc:
        process_worker._probe_video_indexing_gate(
            "new.mp4", {"enable_video": True, "video_index_profile_version": "v2"}
        )
    assert exc.value.failure_code == "video_ffprobe_unavailable"
    assert process_worker._is_retryable_video_error(exc.value) is True


@pytest.mark.asyncio
async def test_normal_multimodal_path_routes_v2_video_to_segment_processor(monkeypatch):
    from raganything.processor.multimodal_processor import MultimodalProcessorMixin

    processor = object.__new__(MultimodalProcessorMixin)
    processor.logger = Mock()
    processor.modal_processors = {}
    processor.lightrag = SimpleNamespace(
        doc_status=SimpleNamespace(get_by_id=AsyncMock(return_value=None))
    )
    processor._ensure_lightrag_initialized = AsyncMock(return_value={"success": True})
    processor._process_multimodal_content_individual = AsyncMock(return_value=True)
    processor._process_multimodal_content_batch_type_aware = AsyncMock()
    processor._mark_multimodal_processing_complete = AsyncMock(return_value=True)
    monkeypatch.setattr(
        "raganything.processor.multimodal_processor.get_processor_for_type",
        lambda *_args: SimpleNamespace(_video_index_profile_version="v2"),
    )

    await processor._process_multimodal_content(
        [{"type": "video", "video_path": "private.mp4"}], "private.mp4", "doc-1"
    )

    processor._process_multimodal_content_individual.assert_awaited_once()
    processor._process_multimodal_content_batch_type_aware.assert_not_awaited()


@pytest.mark.asyncio
async def test_multimodal_video_never_uses_generic_batch_for_a_stale_profile(monkeypatch):
    from raganything.processor.multimodal_processor import MultimodalProcessorMixin

    processor = object.__new__(MultimodalProcessorMixin)
    processor.logger = Mock()
    processor.modal_processors = {}
    processor.lightrag = SimpleNamespace(
        doc_status=SimpleNamespace(get_by_id=AsyncMock(return_value=None))
    )
    processor._ensure_lightrag_initialized = AsyncMock(return_value={"success": True})
    processor._process_multimodal_content_individual = AsyncMock(return_value=True)
    processor._process_multimodal_content_batch_type_aware = AsyncMock()
    processor._mark_multimodal_processing_complete = AsyncMock(return_value=True)
    monkeypatch.setattr(
        "raganything.processor.multimodal_processor.get_processor_for_type",
        lambda *_args: SimpleNamespace(_video_index_profile_version="legacy"),
    )

    await processor._process_multimodal_content(
        [{"type": "video", "video_path": "private.mp4"}], "private.mp4", "doc-1"
    )

    processor._process_multimodal_content_individual.assert_awaited_once()
    processor._process_multimodal_content_batch_type_aware.assert_not_awaited()
# ── Retry-safe failure compensation (tasks 3.4 / 5.1) ──────────────────────


class _RecordingStore:
    """Minimal KV/vector double recording upserts and deletes."""

    def __init__(self):
        self.data = {}
        self.upserted = []
        self.deleted = []

    async def upsert(self, payload):
        self.data.update(payload)
        self.upserted.append(payload)

    async def delete(self, ids):
        self.deleted.extend(ids)
        for key in ids:
            self.data.pop(key, None)

    async def get_by_id(self, key):
        return self.data.get(key)

    async def index_done_callback(self):
        pass


class _RecordingGraph:
    """Minimal graph double mirroring LightRAG's node/edge API."""

    def __init__(self):
        self.nodes = {}
        self.edges = []
        self.removed_nodes = []
        self.removed_edges = []

    async def upsert_node(self, node_id, node_data):
        self.nodes[node_id] = node_data

    async def upsert_edge(self, src, tgt, edge_data):
        self.edges.append((src, tgt, edge_data))

    async def get_nodes_edges_batch(self, node_ids):
        return {
            node_id: [
                (src, tgt) for src, tgt, _data in self.edges
                if src == node_id or tgt == node_id
            ]
            for node_id in node_ids
        }

    async def remove_edges(self, edges):
        self.removed_edges.extend(edges)
        removed = {tuple(edge) for edge in edges}
        self.edges = [e for e in self.edges if (e[0], e[1]) not in removed]

    async def remove_nodes(self, nodes):
        self.removed_nodes.extend(nodes)
        for node_id in nodes:
            self.nodes.pop(node_id, None)
            self.edges = [
                e for e in self.edges if e[0] != node_id and e[1] != node_id
            ]


class _FakeDocStatus:
    def __init__(self):
        self.records = {
            "doc-v1": {
                "chunks_list": ["chunk-text-pre-existing"],
                "chunks_count": 1,
                "status": "handling",
                "metadata": {},
                "updated_at": "2026-01-01T00:00:00+00:00",
            }
        }

    async def get_by_id(self, doc_id):
        return self.records.get(doc_id)

    async def upsert(self, payload):
        self.records.update(payload)

    async def index_done_callback(self):
        pass


def _build_v2_segment_fixture(tmp_path):
    """Assemble a VideoModalProcessor with lightweight LightRAG doubles."""
    from raganything.video_processor import VideoModalProcessor

    video = tmp_path / "lesson.mp4"
    video.write_bytes(b"fake-video-bytes")

    text_chunks = _RecordingStore()
    chunks_vdb = _RecordingStore()
    entities_vdb = _RecordingStore()
    relationships_vdb = _RecordingStore()
    entity_chunks = _RecordingStore()
    relation_chunks = _RecordingStore()
    graph = _RecordingGraph()
    doc_status = _FakeDocStatus()
    lightrag = SimpleNamespace(
        workspace="./rag_storage",
        text_chunks=text_chunks,
        chunks_vdb=chunks_vdb,
        entities_vdb=entities_vdb,
        relationships_vdb=relationships_vdb,
        entity_chunks=entity_chunks,
        relation_chunks=relation_chunks,
        chunk_entity_relation_graph=graph,
        doc_status=doc_status,
        _insert_done=AsyncMock(),
    )
    processor = object.__new__(VideoModalProcessor)
    processor.lightrag = lightrag
    processor.knowledge_graph_inst = graph
    processor.frame_extractor = SimpleNamespace(
        extract_frames=lambda _video_path, output_dir=None: [
            {"path": f"{output_dir}/frame_0001.png", "timestamp": 1.0, "index": 0}
        ]
    )
    processor.audio_transcriber = None
    processor.scene_detector = None
    processor._whisper_available = False
    processor._video_index_profile_version = "v2"
    processor._max_duration = 3600
    processor._frame_semaphore = asyncio.Semaphore(1)
    processor._video_segment_concurrent = 2
    processor._segment_semaphore = asyncio.Semaphore(2)

    return SimpleNamespace(
        video=str(video),
        processor=processor,
        lightrag=lightrag,
        text_chunks=text_chunks,
        chunks_vdb=chunks_vdb,
        entities_vdb=entities_vdb,
        relationships_vdb=relationships_vdb,
        entity_chunks=entity_chunks,
        relation_chunks=relation_chunks,
        graph=graph,
        doc_status=doc_status,
    )


def _install_v2_processor_fakes(monkeypatch, fixture, *, fail_at_segment=None):
    """Wire probe, segment describe, chunk persistence, and PG service doubles."""
    from raganything.services import video_segments as video_segments_service

    monkeypatch.setattr(
        "raganything.video_processor.probe_video_for_indexing",
        lambda _path: {"duration": 70.0, "fps": 30.0, "has_audio": False},
    )

    state = {"call": 0}
    created = {"chunks": [], "nodes": []}

    async def fake_create_entity_and_chunk(
        chunk_text, segment_info, file_path, batch_mode, doc_id, chunk_order_index,
        **_kwargs,
    ):
        state["call"] += 1
        chunk_id = compute_chunk_id(chunk_text)
        entity_name = segment_info["entity_name"]
        created["chunks"].append(chunk_id)
        created["nodes"].append(entity_name)
        await fixture.text_chunks.upsert({chunk_id: {"content": chunk_text, "full_doc_id": doc_id}})
        await fixture.chunks_vdb.upsert({chunk_id: {"content": chunk_text, "full_doc_id": doc_id}})
        await fixture.graph.upsert_node(entity_name, {"entity_id": entity_name, "source_id": chunk_id})
        await fixture.entities_vdb.upsert({
            compute_mdhash_id(entity_name, prefix="ent-"): {"source_id": chunk_id}
        })
        if fail_at_segment is not None and state["call"] >= fail_at_segment:
            raise RuntimeError("simulated mid-write failure")
        await fixture.graph.upsert_edge(
            "extracted-tool", entity_name, {"source_id": chunk_id, "keywords": "belongs_to"}
        )
        await fixture.relationships_vdb.upsert({
            compute_mdhash_id("extracted-tool" + entity_name, prefix="rel-"): {"source_id": chunk_id}
        })
        return segment_info["summary"], {"chunk_id": chunk_id}, []

    async def fake_describe_segment_frames(_frames, _transcript, _start_ms, _end_ms):
        return f"visual summary {_start_ms}-{_end_ms}", [{"timestamp_ms": _start_ms, "index": 0}]

    fixture.processor._describe_segment_frames = fake_describe_segment_frames
    fixture.processor._create_entity_and_chunk = fake_create_entity_and_chunk
    fixture.processor._process_chunk_for_extraction = AsyncMock(return_value=[])

    segment_upserts = []
    deleted_rows = []
    monkeypatch.setattr(video_segments_service, "list_video_segments", AsyncMock(return_value=[]))
    monkeypatch.setattr(video_segments_service, "upsert_video_asset", AsyncMock())
    monkeypatch.setattr(
        video_segments_service, "upsert_video_segment",
        AsyncMock(side_effect=lambda segment: segment_upserts.append(segment)),
    )
    monkeypatch.setattr(
        video_segments_service, "delete_video_segments",
        AsyncMock(side_effect=lambda kb, doc: deleted_rows.append((kb, doc))),
    )
    return SimpleNamespace(
        segment_upserts=segment_upserts,
        deleted_rows=deleted_rows,
        created=created,
    )


@pytest.mark.asyncio
async def test_v2_segment_failure_cleans_partial_lightrag_artifacts(monkeypatch, tmp_path):
    fixture = _build_v2_segment_fixture(tmp_path)
    recording = _install_v2_processor_fakes(
        monkeypatch, fixture, fail_at_segment=2
    )

    with pytest.raises(RuntimeError, match="simulated mid-write failure"):
        await fixture.processor._process_v2_segments(
            {"video_path": fixture.video}, "video", "lesson.mp4", None,
            {"index": 0}, True, "doc-v1", 0,
        )

    # Every chunk written before the failure was removed from text/vector stores.
    assert fixture.text_chunks.data == {}
    assert fixture.chunks_vdb.data == {}
    assert fixture.entities_vdb.data == {}
    assert fixture.relationships_vdb.data == {}
    # Segment nodes (including the one that failed mid-write) were removed.
    assert "lesson 第1段" in fixture.graph.removed_nodes
    assert "lesson 第2段" in fixture.graph.removed_nodes
    assert fixture.graph.nodes == {}
    # Belongs-to edges for completed segments were removed.
    assert ("extracted-tool", "lesson 第1段") in fixture.graph.removed_edges
    # Pre-existing text chunks in doc_status were preserved untouched.
    assert fixture.doc_status.records["doc-v1"]["chunks_list"] == ["chunk-text-pre-existing"]
    assert fixture.doc_status.records["doc-v1"]["chunks_count"] == 1
    # PG video rows were removed for the document.
    assert recording.deleted_rows == [("default", "doc-v1")]
    # The cleanup was persisted through LightRAG's own flush hook.
    fixture.lightrag._insert_done.assert_awaited()


@pytest.mark.asyncio
async def test_v2_retry_after_failure_inserts_deterministic_rows_once(monkeypatch, tmp_path):
    fixture = _build_v2_segment_fixture(tmp_path)

    async def run(fail_at_segment=None):
        recording = _install_v2_processor_fakes(
            monkeypatch, fixture, fail_at_segment=fail_at_segment
        )
        if fail_at_segment is None:
            await fixture.processor._process_v2_segments(
                {"video_path": fixture.video}, "video", "lesson.mp4", None,
                {"index": 0}, True, "doc-v1", 0,
            )
        else:
            with pytest.raises(RuntimeError, match="simulated mid-write failure"):
                await fixture.processor._process_v2_segments(
                    {"video_path": fixture.video}, "video", "lesson.mp4", None,
                    {"index": 0}, True, "doc-v1", 0,
                )
        return recording

    # A mid-write failure must leave no residue for the next retry.
    await run(fail_at_segment=2)
    assert fixture.text_chunks.data == {}
    assert fixture.chunks_vdb.data == {}
    assert fixture.entities_vdb.data == {}
    assert fixture.relationships_vdb.data == {}
    assert fixture.graph.nodes == {}

    # The retry inserts the same deterministic rows exactly once.
    retry = await run(fail_at_segment=None)
    retry_rows = [(row["segment_id"], row["chunk_id"]) for row in retry.segment_upserts]
    assert len(retry_rows) == 3
    assert len({segment_id for segment_id, _chunk in retry_rows}) == 3
    assert fixture.doc_status.records["doc-v1"]["content_length"] > 0

    # A separate attempt produces the same segment/chunk IDs (no duplication).
    reference = await run(fail_at_segment=None)
    reference_rows = [(row["segment_id"], row["chunk_id"]) for row in reference.segment_upserts]
    assert reference_rows == retry_rows
    assert sorted(fixture.text_chunks.data) == sorted(
        chunk_id for _segment_id, chunk_id in retry_rows
    )


@pytest.mark.asyncio
async def test_v2_video_failure_does_not_fall_back_to_whole_video_batch(monkeypatch):
    from raganything.processor.multimodal_processor import MultimodalProcessorMixin
    from raganything.video_processor import VideoProcessingError

    processor = object.__new__(MultimodalProcessorMixin)
    processor.logger = Mock()
    processor.modal_processors = {}
    processor.lightrag = SimpleNamespace(
        doc_status=SimpleNamespace(get_by_id=AsyncMock(return_value=None))
    )
    processor._ensure_lightrag_initialized = AsyncMock(return_value={"success": True})
    processor._process_multimodal_content_individual = AsyncMock(
        side_effect=VideoProcessingError("video_frame_analysis_empty")
    )
    processor._process_multimodal_content_batch_type_aware = AsyncMock(return_value=True)
    monkeypatch.setattr(
        "raganything.processor.multimodal_processor.get_processor_for_type",
        lambda *_args: SimpleNamespace(_video_index_profile_version="v2"),
    )

    with pytest.raises(VideoProcessingError):
        await processor._process_multimodal_content(
            [{"type": "video", "video_path": "private.mp4"}], "private.mp4", "doc-1"
        )

    # A v2 failure must never re-index the source through a whole-video path.
    processor._process_multimodal_content_batch_type_aware.assert_not_awaited()


@pytest.mark.asyncio
async def test_delete_video_segments_removes_document_segments_too(monkeypatch):
    from raganything.services import video_segments

    calls = []

    class Pool:
        async def execute(self, query, *args):
            calls.append((query, args))

    monkeypatch.setattr(video_segments, "get_pg_pool", lambda: Pool())
    await video_segments.delete_video_segments("kb-a", "doc-1")

    assert len(calls) == 2
    assert "DELETE FROM video_segments" in calls[0][0]
    assert calls[0][1] == ("kb-a", "doc-1")
    assert "DELETE FROM video_assets" in calls[1][0]
    assert calls[1][1] == ("kb-a", "doc-1")


# ── v2 index throughput: concurrency, ordering, metrics ─────────────────────


@pytest.mark.asyncio
async def test_v2_segment_concurrency_overlaps_under_semaphore(monkeypatch, tmp_path):
    """Two segments must overlap their describe/extract work under a semaphore of 2."""
    fixture = _build_v2_segment_fixture(tmp_path)
    _install_v2_processor_fakes(monkeypatch, fixture)

    active = 0
    max_active = 0
    lock = asyncio.Lock()
    two_active = asyncio.Event()
    release = asyncio.Event()

    async def slow_describe(_frames, _transcript, start_ms, _end_ms):
        nonlocal active, max_active
        async with lock:
            active += 1
            max_active = max(max_active, active)
        if active >= 2:
            two_active.set()
        await asyncio.wait_for(release.wait(), timeout=5)
        async with lock:
            active -= 1
        return f"summary {start_ms}", [{"timestamp_ms": start_ms, "index": 0}]

    fixture.processor._describe_segment_frames = slow_describe
    fixture.processor._segment_semaphore = asyncio.Semaphore(2)

    task = asyncio.create_task(
        fixture.processor._process_v2_segments(
            {"video_path": fixture.video}, "video", "lesson.mp4", None,
            {"index": 0}, True, "doc-v1", 0,
        )
    )
    await asyncio.wait_for(two_active.wait(), timeout=5)
    assert max_active >= 2
    release.set()
    await task
    assert max_active <= 2


@pytest.mark.asyncio
async def test_v2_segment_write_order_is_deterministic(monkeypatch, tmp_path):
    """PG rows, chunk_ids, and results follow segment order even when a later
    segment finishes before an earlier one."""
    fixture = _build_v2_segment_fixture(tmp_path)
    recording = _install_v2_processor_fakes(monkeypatch, fixture)

    async def variable_describe(_frames, _transcript, start_ms, _end_ms):
        # Let segment 0 finish last to prove completion order is irrelevant.
        if start_ms == 0:
            await asyncio.sleep(0.05)
        return f"summary {start_ms}", [{"timestamp_ms": start_ms, "index": 0}]

    fixture.processor._describe_segment_frames = variable_describe
    fixture.processor._segment_semaphore = asyncio.Semaphore(2)

    description, entity_info, results = await fixture.processor._process_v2_segments(
        {"video_path": fixture.video}, "video", "lesson.mp4", None,
        {"index": 0}, True, "doc-v1", 0,
    )
    assert "视频清单" in description
    assert len(entity_info["chunk_ids"]) == 3
    assert [row["segment_index"] for row in recording.segment_upserts] == [0, 1, 2]
    assert entity_info["chunk_ids"] == [
        row["chunk_id"] for row in recording.segment_upserts
    ]
    assert len({row["chunk_id"] for row in recording.segment_upserts}) == 3
    assert results == []


@pytest.mark.asyncio
async def test_v2_metrics_logged_on_success(monkeypatch, tmp_path, caplog):
    fixture = _build_v2_segment_fixture(tmp_path)
    _install_v2_processor_fakes(monkeypatch, fixture)
    captured: list[str] = []
    real_logger = logging.getLogger("lightrag")
    monkeypatch.setattr(
        real_logger, "info",
        lambda msg, *args, **kwargs: captured.append(
            msg % args if args else str(msg)
        ),
    )

    await fixture.processor._process_v2_segments(
        {"video_path": fixture.video}, "video", "lesson.mp4", None,
        {"index": 0}, True, "doc-v1", 0,
    )

    messages = captured
    summary = next((m for m in messages if m.startswith("video_v2_metrics")), None)
    assert summary is not None
    assert "doc_id=doc-v1" in summary
    assert "segments=3" in summary
    assert "concurrent=2" in summary
    assert "total_ms=" in summary and "probe_ms=" in summary
    assert "frames_ms=" in summary and "asr_ms=" in summary
    assert "scene_ms=" in summary and "describe_ms=" in summary
    assert "extract_ms=" in summary and "pg_ms=" in summary
    segment_lines = [m for m in messages if m.startswith("video_v2_segment_metrics")]
    assert len(segment_lines) == 3
    assert all("describe_ms=" in m and "create_ms=" in m and "extract_ms=" in m for m in segment_lines)


@pytest.mark.asyncio
async def test_v2_metrics_logged_on_failure(monkeypatch, tmp_path, caplog):
    fixture = _build_v2_segment_fixture(tmp_path)
    _install_v2_processor_fakes(monkeypatch, fixture, fail_at_segment=2)
    captured: list[str] = []
    real_logger = logging.getLogger("lightrag")
    monkeypatch.setattr(
        real_logger, "info",
        lambda msg, *args, **kwargs: captured.append(
            msg % args if args else str(msg)
        ),
    )

    with pytest.raises(RuntimeError, match="simulated mid-write failure"):
        await fixture.processor._process_v2_segments(
            {"video_path": fixture.video}, "video", "lesson.mp4", None,
            {"index": 0}, True, "doc-v1", 0,
        )

    messages = captured
    summary = next((m for m in messages if m.startswith("video_v2_metrics")), None)
    assert summary is not None
    assert "failed=true" in summary
    assert "segments_completed=1" in summary
    assert "total_ms=" in summary


@pytest.mark.asyncio
async def test_create_entity_and_chunk_defer_flush_and_extraction(tmp_path):
    """defer_flush=True skips the per-chunk JSON flush; defer_extraction=True
    skips extraction; defaults keep the previous behavior."""
    from raganything.video_processor import VideoModalProcessor

    class _Recorder:
        def __init__(self):
            self.flushed = 0
            self.data = {}

        async def upsert(self, payload):
            self.data.update(payload)

        async def index_done_callback(self):
            self.flushed += 1

    processor = object.__new__(VideoModalProcessor)
    processor.tokenizer = Mock(encode=lambda s: [1] * min(8, max(1, len(s))))
    processor.text_chunks_db = _Recorder()
    processor.chunks_vdb = _Recorder()
    processor.entities_vdb = _Recorder()
    processor.knowledge_graph_inst = AsyncMock()
    processor._process_chunk_for_extraction = AsyncMock(return_value=[("nodes", "edges")])

    entity_info = {
        "entity_name": "测试实体",
        "entity_type": "video_segment",
        "summary": "摘要",
    }
    summary, persisted, chunk_results = await processor._create_entity_and_chunk(
        "测试内容", entity_info, "lesson.mp4", True, "doc-v1", 0,
        defer_flush=True, defer_extraction=True,
    )
    assert processor.text_chunks_db.flushed == 0
    assert chunk_results == []
    assert persisted["chunk_id"]

    summary, persisted, chunk_results = await processor._create_entity_and_chunk(
        "测试内容2", entity_info, "lesson.mp4", True, "doc-v1", 1,
    )
    assert processor.text_chunks_db.flushed == 1
    processor._process_chunk_for_extraction.assert_awaited_once()
    assert chunk_results == [("nodes", "edges")]
    assert processor.knowledge_graph_inst.upsert_node.await_count >= 2
