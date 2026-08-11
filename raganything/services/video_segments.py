"""PostgreSQL persistence for versioned video assets and segments."""

from __future__ import annotations

import json
from collections import defaultdict
from typing import Any
from urllib.parse import quote, urlencode

from raganything.services.pg_state_repo import get_pg_pool
from raganything.utils import display_document_name


async def upsert_video_asset(asset: dict[str, Any]) -> None:
    pool = get_pg_pool()
    await pool.execute(
        """INSERT INTO video_assets
        (media_id,kb_name,document_id,source_sha256,original_name,server_path,
         duration_ms,fps,has_audio,profile_version,status)
        VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11)
        ON CONFLICT (media_id) DO UPDATE SET
          duration_ms=EXCLUDED.duration_ms, fps=EXCLUDED.fps,
          has_audio=EXCLUDED.has_audio, status=EXCLUDED.status,
          updated_at=NOW()""",
        asset["media_id"], asset["kb_name"], asset["document_id"],
        asset["source_sha256"], asset.get("original_name", ""),
        asset["server_path"], int(asset["duration_ms"]), float(asset["fps"]),
        bool(asset.get("has_audio")), asset["profile_version"],
        asset.get("status", "ready"),
    )


async def upsert_video_segment(segment: dict[str, Any]) -> None:
    pool = get_pg_pool()
    await pool.execute(
        """INSERT INTO video_segments
        (segment_id,media_id,kb_name,document_id,segment_index,start_ms,end_ms,
         transcript_text,visual_summary,frame_refs,chunk_id,source_sha256,
         profile_version,status)
        VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10::jsonb,$11,$12,$13,$14)
        ON CONFLICT (segment_id) DO UPDATE SET
          transcript_text=EXCLUDED.transcript_text,
          visual_summary=EXCLUDED.visual_summary, frame_refs=EXCLUDED.frame_refs,
          chunk_id=EXCLUDED.chunk_id, status=EXCLUDED.status, updated_at=NOW()""",
        segment["segment_id"], segment["media_id"], segment["kb_name"],
        segment["document_id"], int(segment["segment_index"]),
        int(segment["start_ms"]), int(segment["end_ms"]),
        segment.get("transcript_text", ""), segment.get("visual_summary", ""),
        json.dumps(segment.get("frame_refs", []), ensure_ascii=True),
        segment.get("chunk_id"), segment["source_sha256"],
        segment["profile_version"], segment.get("status", "ready"),
    )


async def list_video_segments(kb_name: str, document_id: str) -> list[dict[str, Any]]:
    pool = get_pg_pool()
    rows = await pool.fetch(
        "SELECT * FROM video_segments WHERE kb_name=$1 AND document_id=$2 "
        "ORDER BY segment_index", kb_name, document_id
    )
    return [dict(row) for row in rows]


async def get_video_asset(kb_name: str, media_id: str) -> dict[str, Any] | None:
    """Resolve an owned video asset. Its server path stays server-side."""
    pool = get_pg_pool()
    row = await pool.fetchrow(
        "SELECT media_id, kb_name, document_id, original_name, server_path, "
        "duration_ms, fps, has_audio, profile_version, status "
        "FROM video_assets WHERE kb_name=$1 AND media_id=$2 AND status='ready'",
        kb_name, media_id,
    )
    return dict(row) if row else None


async def list_video_segments_for_chunks(
    kb_name: str, chunk_ids: list[str],
) -> dict[str, dict[str, Any]]:
    """Return ready segment descriptors keyed by their searchable chunk ID."""
    ids = [str(chunk_id) for chunk_id in chunk_ids if chunk_id]
    if not ids:
        return {}
    pool = get_pg_pool()
    rows = await pool.fetch(
        "SELECT s.chunk_id, s.segment_id, s.segment_index, s.start_ms, s.end_ms, "
        "s.document_id, s.media_id, a.original_name "
        "FROM video_segments s JOIN video_assets a ON a.media_id=s.media_id "
        "WHERE s.kb_name=$1 AND s.chunk_id = ANY($2::text[]) "
        "AND s.status='ready' AND a.status='ready'",
        kb_name, ids,
    )
    return {
        str(row["chunk_id"]): {
            "segment_id": str(row["segment_id"]),
            "segment_index": int(row["segment_index"]),
            "start_ms": int(row["start_ms"]),
            "end_ms": int(row["end_ms"]),
            "document_id": str(row["document_id"]),
            "media_id": str(row["media_id"]),
            "media_kb": kb_name,
            "document_name": display_document_name(row["original_name"]),
        }
        for row in rows if row.get("chunk_id")
    }


def controlled_video_media_url(media_id: str, kb_name: str) -> str:
    """Build an opaque URL after the caller has authorized the KB."""
    return f"/api/knowledge/media/{quote(media_id, safe='')}?{urlencode({'kb': kb_name})}"


def merge_video_segment_citations(segments: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Deduplicate parent videos while retaining ordered segment hits."""
    grouped: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for segment in segments:
        media_id, media_kb = segment.get("media_id"), segment.get("media_kb")
        if isinstance(media_id, str) and media_id and isinstance(media_kb, str) and media_kb:
            grouped[(media_kb, media_id)].append(segment)
    citations: list[dict[str, Any]] = []
    for (media_kb, media_id), group in grouped.items():
        seen: set[str] = set()
        ordered = sorted(group, key=lambda item: (item["segment_index"], item["start_ms"]))
        ranges = []
        for segment in ordered:
            segment_id = str(segment["segment_id"])
            if segment_id in seen:
                continue
            seen.add(segment_id)
            ranges.append({"segment_id": segment_id, "start_ms": int(segment["start_ms"]), "end_ms": int(segment["end_ms"])})
        if ranges:
            citations.append({
                "document_id": ordered[0]["document_id"],
                "document_name": display_document_name(
                    ordered[0].get("document_name"), default="video"
                ),
                "media_id": media_id, "media_kb": media_kb,
                "media_url": controlled_video_media_url(media_id, media_kb),
                "video_segment": ranges[0], "video_segments": ranges,
            })
    return citations


def enrich_video_segment_citations(citations: object, kb_name: str) -> list[dict[str, Any]]:
    """Keep ordinary citations while converting authorized video anchors to DTOs."""
    if not isinstance(citations, list):
        return []
    passthrough: list[dict[str, Any]] = []
    segments: list[dict[str, Any]] = []
    for citation in citations:
        if not isinstance(citation, dict):
            continue
        raw = citation.get("video_segment")
        raw = raw if isinstance(raw, dict) else citation
        required = ("segment_id", "start_ms", "end_ms", "media_id")
        if all(raw.get(key) is not None or citation.get(key) is not None for key in required):
            try:
                segments.append({
                    "segment_id": str(raw.get("segment_id", citation.get("segment_id"))),
                    "segment_index": int(raw.get("segment_index", citation.get("segment_index", raw.get("start_ms", citation.get("start_ms"))))),
                    "start_ms": int(raw.get("start_ms", citation.get("start_ms"))),
                    "end_ms": int(raw.get("end_ms", citation.get("end_ms"))),
                    "media_id": str(raw.get("media_id", citation.get("media_id"))),
                    "media_kb": kb_name,
                    "document_id": str(raw.get("document_id", citation.get("document_id", ""))),
                    "document_name": str(raw.get("document_name", citation.get("document_name", "video"))),
                })
            except (TypeError, ValueError):
                continue
        else:
            passthrough.append(citation)
    return passthrough + merge_video_segment_citations(segments)


async def delete_video_segments(kb_name: str, document_id: str) -> None:
    """Remove one document's video catalog without cascading to shared media.

    ``media_id`` is content-derived, so a shared source can keep asset/segment
    rows under another document.  Delete this document's segment rows before
    its asset row: the asset FK cascade would otherwise remove every segment
    that references the shared ``media_id``.  A deployment without PostgreSQL
    (unit tests / non-PG storage) skips the catalog cleanup silently.
    """
    try:
        pool = get_pg_pool()
    except RuntimeError:
        logger = __import__("logging").getLogger(__name__)
        logger.debug("video segment catalog cleanup skipped: PG pool unavailable")
        return
    await pool.execute(
        "DELETE FROM video_segments WHERE kb_name=$1 AND document_id=$2",
        kb_name, document_id,
    )
    await pool.execute(
        "DELETE FROM video_assets WHERE kb_name=$1 AND document_id=$2",
        kb_name, document_id,
    )
