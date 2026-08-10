"""Real-PostgreSQL video segment persistence and upload snapshot integration.

Runs against an isolated acceptance database (``DATABASE_URL``) whose schema
was applied with the canonical migration chain (including
``029_video_semantic_segments.sql``).  Every row uses a unique KB/document id
and is removed by the fixture teardown.
"""

from __future__ import annotations

import os
import uuid

import pytest

try:
    import pytest_asyncio
except ImportError:  # pragma: no cover - the frozen CI dev group includes it
    pytest_asyncio = None

pytestmark = pytest.mark.skipif(
    not os.getenv("DATABASE_URL"),
    reason="DATABASE_URL is required for PostgreSQL video segment integration",
)

KB = f"video_int_{uuid.uuid4().hex[:10]}"
DOC = f"doc-{uuid.uuid4().hex[:24]}"
MEDIA = f"media-{uuid.uuid4().hex[:24]}"
SOURCE = "a" * 64
PROFILE = "v2"


@((pytest_asyncio.fixture) if pytest_asyncio else pytest.fixture)
async def video_db():
    from raganything.services.pg_state_repo import close_pg_pool, init_pg_pool
    # A previous test may have closed the shared pool; force a fresh one so
    # this suite is order-independent.
    await close_pg_pool()
    await init_pg_pool()
    yield
    from raganything.services.video_segments import delete_video_segments
    try:
        await delete_video_segments(KB, DOC)
    except Exception:
        pass
    await close_pg_pool()


async def _insert_asset_and_segments() -> None:
    from raganything.services.video_segments import (
        upsert_video_asset,
        upsert_video_segment,
    )
    await upsert_video_asset({
        "media_id": MEDIA, "kb_name": KB, "document_id": DOC,
        "source_sha256": SOURCE, "original_name": "7、蓄电池检测.mp4",
        "server_path": "/server-only/uploads/7、蓄电池检测.mp4",
        "duration_ms": 215_100, "fps": 25.0, "has_audio": True,
        "profile_version": PROFILE,
    })
    for index, (start_ms, end_ms) in enumerate(((0, 24_000), (21_000, 48_000))):
        await upsert_video_segment({
            "segment_id": f"seg-{SOURCE[:8]}-{index}-{start_ms}-{end_ms}",
            "media_id": MEDIA, "kb_name": KB, "document_id": DOC,
            "segment_index": index, "start_ms": start_ms, "end_ms": end_ms,
            "transcript_text": f"局部转录 {index}", "visual_summary": f"视觉摘要 {index}",
            "frame_refs": [{"timestamp_ms": start_ms, "index": index}],
            "chunk_id": f"chunk-{index}", "source_sha256": SOURCE,
            "profile_version": PROFILE,
        })


@pytest.mark.asyncio
async def test_segment_upsert_list_retry_idempotency_and_delete(video_db):
    from raganything.services.video_segments import (
        get_video_asset,
        list_video_segments,
        upsert_video_segment,
    )
    await _insert_asset_and_segments()
    # A retry with the same deterministic segment IDs must not duplicate rows.
    await upsert_video_segment({
        "segment_id": "seg-%s-0-0-24000" % SOURCE[:8],
        "media_id": MEDIA, "kb_name": KB, "document_id": DOC,
        "segment_index": 0, "start_ms": 0, "end_ms": 24_000,
        "transcript_text": "局部转录 0", "visual_summary": "视觉摘要 0",
        "frame_refs": [], "chunk_id": "chunk-0", "source_sha256": SOURCE,
        "profile_version": PROFILE,
    })

    rows = await list_video_segments(KB, DOC)
    assert [row["segment_index"] for row in rows] == [0, 1]
    assert [row["start_ms"] for row in rows] == [0, 21_000]
    assert [row["end_ms"] for row in rows] == [24_000, 48_000]
    assert all(row["profile_version"] == PROFILE for row in rows)

    asset = await get_video_asset(KB, MEDIA)
    assert asset is not None
    assert asset["document_id"] == DOC
    assert asset["profile_version"] == PROFILE

    await upsert_video_segment({
        "segment_id": "seg-%s-0-0-24000" % SOURCE[:8],
        "media_id": MEDIA, "kb_name": KB, "document_id": DOC,
        "segment_index": 0, "start_ms": 0, "end_ms": 24_000,
        "transcript_text": "重试后的更新文本", "visual_summary": "视觉摘要 0",
        "frame_refs": [], "chunk_id": "chunk-0", "source_sha256": SOURCE,
        "profile_version": PROFILE,
    })
    rows = await list_video_segments(KB, DOC)
    assert len(rows) == 2
    assert rows[0]["transcript_text"] == "重试后的更新文本"

    from raganything.services.video_segments import delete_video_segments
    await delete_video_segments(KB, DOC)
    assert await list_video_segments(KB, DOC) == []
    assert await get_video_asset(KB, MEDIA) is None


@pytest.mark.asyncio
async def test_chunk_lookup_and_video_segment_citation_dto(video_db):
    from raganything.services.video_segments import (
        enrich_video_segment_citations,
        list_video_segments_for_chunks,
    )
    await _insert_asset_and_segments()

    lookup = await list_video_segments_for_chunks(KB, ["chunk-0", "chunk-1", "missing"])
    assert set(lookup) == {"chunk-0", "chunk-1"}
    assert lookup["chunk-0"]["start_ms"] == 0
    assert lookup["chunk-1"]["start_ms"] == 21_000
    assert lookup["chunk-0"]["media_id"] == MEDIA
    assert lookup["chunk-0"]["media_kb"] == KB

    enriched = enrich_video_segment_citations(
        [
            {
                "segment_id": lookup["chunk-1"]["segment_id"],
                "segment_index": 1,
                "start_ms": 21_000,
                "end_ms": 48_000,
                "media_id": MEDIA,
                "document_id": DOC,
                "document_name": "7、蓄电池检测.mp4",
            },
            {"text": "普通引用不丢"},
        ],
        KB,
    )
    video = [item for item in enriched if "media_id" in item]
    assert len(video) == 1
    assert video[0]["media_id"] == MEDIA
    assert video[0]["media_url"].startswith("/api/knowledge/media/")
    assert video[0]["video_segments"] == [
        {"segment_id": lookup["chunk-1"]["segment_id"], "start_ms": 21_000, "end_ms": 48_000}
    ]
    assert any(item.get("text") == "普通引用不丢" for item in enriched)


@pytest.mark.asyncio
async def test_video_enabled_upload_snapshot_freezes_v2_profile(video_db):
    from raganything.services import user_settings
    from raganything.services.pg_auth_repo import create_user

    username = f"ci_video_{uuid.uuid4().hex[:16]}"
    user = await create_user(username, "CiVideo!2026")
    try:
        resolved = await user_settings.resolve_user_settings_for_task(
            int(user["id"]),
            request_overrides={"ingestion": {"enable_video": True}},
            permitted_sections=await user_settings.available_sections_for_user(int(user["id"])),
        )
        assert resolved.ingestion.enable_video is True
        snapshot_settings = user_settings.with_task_ingestion_overrides(
            resolved, enable_video=True
        )
        assert snapshot_settings.ingestion.video_index_profile_version == "v2"

        task_id = f"task-{uuid.uuid4().hex[:20]}"
        await user_settings.create_task_settings_snapshot(
            task_id, int(user["id"]), snapshot_settings
        )
        stored = await user_settings.get_task_settings_snapshot(task_id)
        assert stored["settings"]["ingestion"]["video_index_profile_version"] == "v2"

        without_video = user_settings.with_task_ingestion_overrides(
            resolved, enable_video=False
        )
        assert without_video.ingestion.video_index_profile_version == "v2"
    finally:
        from raganything.services.pg_state_repo import get_pg_pool
        pool = get_pg_pool()
        async with pool.acquire() as conn:
            await conn.execute(
                "DELETE FROM audit_logs WHERE actor_id = $1 OR target_user_id = $1",
                int(user["id"]),
            )
            await conn.execute("DELETE FROM users WHERE id = $1", int(user["id"]))
