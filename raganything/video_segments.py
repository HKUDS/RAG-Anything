"""Deterministic planning primitives for time-aware video indexing."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Any, Iterable


@dataclass(frozen=True)
class VideoSegment:
    index: int
    start_ms: int
    end_ms: int
    transcript: str = ""

    @property
    def duration_ms(self) -> int:
        return self.end_ms - self.start_ms


def segment_id(source_sha256: str, start_ms: int, end_ms: int, profile: str) -> str:
    value = f"{source_sha256}:{start_ms}:{end_ms}:{profile}".encode()
    return "vseg-" + hashlib.sha256(value).hexdigest()[:32]


def source_sha256(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def plan_segments(
    duration_seconds: float,
    *,
    asr_segments: Iterable[dict[str, Any]] = (),
    scene_boundaries: Iterable[float] = (),
    target_seconds: float = 24.0,
    min_seconds: float = 15.0,
    max_seconds: float = 30.0,
    overlap_seconds: float = 3.0,
) -> list[VideoSegment]:
    """Plan bounded, ordered windows with deterministic fallback behavior."""
    if duration_seconds <= 0:
        raise ValueError("video_duration_invalid")
    duration = float(duration_seconds)
    asr_segments = list(asr_segments)
    boundaries = sorted({0.0, duration, *[float(x) for x in scene_boundaries if 0 < float(x) < duration]})
    for item in asr_segments:
        try:
            boundaries.extend([float(item["start"]), float(item["end"])])
        except (KeyError, TypeError, ValueError):
            continue
    boundaries = sorted({round(x, 3) for x in boundaries if 0 <= x <= duration})
    segments: list[VideoSegment] = []
    start = 0.0
    while start < duration - 1e-6:
        desired = min(duration, start + target_seconds)
        candidates = [x for x in boundaries if start + min_seconds <= x <= start + max_seconds]
        end = min(candidates, key=lambda x: abs(x - desired)) if candidates else desired
        if end - start < min_seconds and duration - start > min_seconds:
            end = min(duration, start + min_seconds)
        if end - start > max_seconds:
            end = start + max_seconds
        if end <= start:
            break
        start_ms, end_ms = round(start * 1000), round(end * 1000)
        transcript = " ".join(
            str(item.get("text", "")).strip()
            for item in asr_segments
            if isinstance(item, dict) and float(item.get("end", 0) or 0) > start and float(item.get("start", 0) or 0) < end
        ).strip()
        segments.append(VideoSegment(len(segments), start_ms, end_ms, transcript))
        if end >= duration:
            break
        start = max(end - overlap_seconds, start + 0.001)
    if not segments or segments[-1].end_ms < round(duration * 1000):
        end_ms = round(duration * 1000)
        start_ms = max(0, end_ms - round(max_seconds * 1000))
        segments.append(VideoSegment(len(segments), start_ms, end_ms, ""))
    return segments
