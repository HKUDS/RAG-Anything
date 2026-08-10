# -*- coding: utf-8 -*-
"""
Video Processing Module.

Layer: Core
Primary Responsibility: Video modal processing — frame extraction via ffmpeg,
    audio transcription, scene detection, VLM-based frame analysis.
Key Dependencies: lightrag (LightRAG), raganything.prompt (PROMPTS), ffmpeg

Components:
- FrameExtractor: Extract key frames from video files via ffmpeg (duration-aware
  routing: fps-filter for short videos, serial-seek for long videos)
- SceneDetector: Detect scene boundaries for intelligent frame selection
- AudioTranscriber: Transcribe audio tracks via Whisper (configurable model size,
  default ``"small"`` for Chinese)
- VideoModalProcessor: Main processor integrating all sub-components; accepts an
  optional ``RAGAnythingConfig`` object for duration enforcement, transcript
  truncation, and whisper model selection

Duration Enforcement:
    Videos exceeding ``VIDEO_MAX_DURATION`` (default 3600s) are rejected BEFORE
    any frame extraction or API calls to prevent runaway costs.  The caller
    (``multimodal_processor.py``) catches the ``ValueError`` and creates a
    graceful fallback entity.
"""

import os
import time
import re
import json
import base64
import asyncio
import hashlib
import tempfile
import subprocess
from typing import Dict, Any, Tuple, List, Optional
from pathlib import Path

from lightrag.utils import logger, compute_mdhash_id
from lightrag.lightrag import LightRAG

from raganything.modalprocessors import BaseModalProcessor, ContextExtractor
from raganything.prompt import PROMPTS


class VideoProcessingError(RuntimeError):
    """A bounded, retryable video-ingestion failure safe for Worker output."""

    def __init__(self, failure_code: str, message: str = "") -> None:
        self.failure_code = failure_code
        super().__init__(message or failure_code)


def _probe_error(code: str, detail: str = "") -> VideoProcessingError:
    """Never include the upload path or unbounded tool output in task errors."""
    return VideoProcessingError(code, f"{code}: {str(detail)[:240]}" if detail else code)


_CHINESE_TEXT = re.compile(r"[\u4e00-\u9fff]")


def _has_chinese_summary(value: object) -> bool:
    """Require enough Chinese prose before a segment becomes searchable."""
    return len(_CHINESE_TEXT.findall(str(value or ""))) >= 2


def _format_metrics_line(fields: dict[str, object]) -> str:
    """Format structured key=value metrics fields for stable log parsing."""
    return " ".join(f"{key}={value}" for key, value in fields.items())


def _elapsed_ms(start: float) -> float:
    """Return elapsed milliseconds since a ``time.perf_counter()`` start."""
    return max(0.0, (time.perf_counter() - start) * 1000.0)

# ── Utility helpers ────────────────────────────────────────────────────────


def _check_ffmpeg_available() -> bool:
    """Check if ffmpeg is available on the system PATH."""
    try:
        subprocess.run(
            ["ffmpeg", "-version"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=10,
        )
        return True
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False
    except OSError as exc:
        logger.warning("ffmpeg probe failed; disabling video support: %s", exc)
        return False


def _check_ffprobe_available() -> bool:
    """Check if ffprobe is available on the system PATH."""
    try:
        subprocess.run(
            ["ffprobe", "-version"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=10,
        )
        return True
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False
    except OSError as exc:
        logger.warning("ffprobe probe failed; disabling video support: %s", exc)
        return False


def _get_video_metadata(video_path: str) -> Dict[str, Any]:
    """Get video metadata using ffprobe.

    Args:
        video_path: Path to the video file

    Returns:
        Dict with keys: duration, width, height, codec, fps, has_audio, audio_codec
    """
    try:
        cmd = [
            "ffprobe",
            "-v",
            "quiet",
            "-print_format",
            "json",
            "-show_format",
            "-show_streams",
            str(video_path),
        ]
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=30,
        )
        if result.returncode != 0:
            return {"error": result.stderr.strip()}

        data = json.loads(result.stdout)

        video_stream = None
        audio_stream = None
        for stream in data.get("streams", []):
            if stream.get("codec_type") == "video" and video_stream is None:
                video_stream = stream
            elif stream.get("codec_type") == "audio" and audio_stream is None:
                audio_stream = stream

        duration = float(data.get("format", {}).get("duration", 0))
        if duration == 0 and video_stream:
            # Try to parse duration from stream tags
            dur_tag = video_stream.get("tags", {}).get("DURATION", "")
            if dur_tag:
                duration = _parse_duration(dur_tag)

        fps_str = video_stream.get("r_frame_rate", "0/1") if video_stream else "0/1"
        try:
            num, den = fps_str.split("/")
            fps = float(num) / float(den) if float(den) != 0 else 0.0
        except (ValueError, ZeroDivisionError):
            fps = 0.0

        return {
            "duration": duration,
            "width": video_stream.get("width", 0) if video_stream else 0,
            "height": video_stream.get("height", 0) if video_stream else 0,
            "codec": video_stream.get("codec_name", "unknown") if video_stream else "unknown",
            "fps": fps,
            "has_audio": audio_stream is not None,
            "audio_codec": audio_stream.get("codec_name", "unknown") if audio_stream else "",
        }
    except subprocess.TimeoutExpired:
        return {"error": "ffprobe timed out"}
    except json.JSONDecodeError:
        return {"error": "Failed to parse ffprobe output"}
    except Exception as e:
        return {"error": str(e)}


def _parse_duration(dur_str: str) -> float:
    """Parse duration string like '00:05:30.500' into seconds."""
    parts = dur_str.replace(",", ".").split(":")
    if len(parts) == 3:
        return float(parts[0]) * 3600 + float(parts[1]) * 60 + float(parts[2])
    return 0.0


def validate_video_file(video_path: str) -> Dict[str, Any]:
    """Validate a video file and return its metadata.

    Args:
        video_path: Path to the video file

    Returns:
        Dict with metadata or error info. Contains 'valid': bool key.
    """
    path = Path(video_path)

    if not path.exists():
        return {"valid": False, "error": f"File not found: {video_path}"}

    # Check supported extensions
    supported = {".mp4", ".avi", ".mov", ".mkv", ".webm"}
    if path.suffix.lower() not in supported:
        return {
            "valid": False,
            "error": f"Unsupported video format: {path.suffix}. Supported: {supported}",
        }

    # Check file size (skip empty files)
    try:
        file_size = os.path.getsize(str(path))
        if file_size < 1024:  # < 1KB
            return {"valid": False, "error": f"Video file too small: {file_size} bytes"}
    except OSError as e:
        return {"valid": False, "error": f"Cannot read file: {e}"}

    if not _check_ffprobe_available():
        return {
            "valid": False,
            "error": "ffprobe not available. Install ffmpeg to process videos.",
        }

    metadata = _get_video_metadata(str(path))
    if "error" in metadata:
        return {"valid": False, "error": metadata["error"], "metadata": metadata}

    return {"valid": True, "metadata": metadata}


def probe_video_for_indexing(video_path: str) -> Dict[str, Any]:
    """Fail closed before indexing a v2 video upload."""
    if not _check_ffprobe_available():
        raise _probe_error("video_ffprobe_unavailable")
    if not _check_ffmpeg_available():
        raise _probe_error("video_ffmpeg_unavailable")
    result = validate_video_file(video_path)
    if not result.get("valid"):
        message = str(result.get("error") or "invalid video")
        code = "video_probe_timeout" if "timed out" in message.lower() else "video_probe_invalid"
        raise _probe_error(code, message)
    metadata = result.get("metadata") or {}
    if (
        float(metadata.get("duration") or 0) <= 0
        or float(metadata.get("fps") or 0) <= 0
        or int(metadata.get("width") or 0) <= 0
        or int(metadata.get("height") or 0) <= 0
    ):
        raise _probe_error("video_probe_invalid_metadata")
    return metadata


def check_video_skippable(video_path: str, config: Any = None) -> Tuple:
    """Check if a video should skip processing (too short, static, etc.)

    Args:
        video_path: Path to the video file
        config: Optional RAGAnythingConfig for thresholds

    Returns:
        (reason, label) tuple if skippable, or None if should process
    """
    metadata = _get_video_metadata(video_path)
    if "error" in metadata:
        return None  # Can't determine, let normal path handle it

    duration = metadata.get("duration", 0)

    # Skip extremely short videos (< 1 second)
    if duration < 1.0:
        return (f"too_short_{duration:.1f}s", "Very short video clip")

    return None  # Not skippable


# ── FrameExtractor ─────────────────────────────────────────────────────────


class FrameExtractor:
    """Extract key frames from video files using ffmpeg.

    Uses duration-aware routing:
    - Short/medium videos (< 180 s and < 100 source frames per output frame):
      single ffmpeg invocation with the ``fps`` filter (avoids N subprocess spawns).
    - Long videos: serial ``-ss`` seeks (avoids decoding 99%+ of frames just to
      drop them).
    """

    # Thresholds for fps-filter vs. serial-seek routing
    FPS_FILTER_MAX_DURATION = 180       # seconds
    FPS_FILTER_MAX_SOURCE_RATIO = 100   # source frames / output frames

    def __init__(self, sample_rate: float = 1.0, max_frames: int = 60):
        """Initialize frame extractor.

        Args:
            sample_rate: Frames per second to extract (default 1.0 = 1 fps)
            max_frames: Maximum number of frames to extract per video
        """
        self.sample_rate = sample_rate
        self.max_frames = max_frames

    def _extract_fps_filter(
        self,
        video_path: str,
        output_dir: str,
        frame_count: int,
        duration: float,
    ) -> List[Dict[str, Any]]:
        """Extract frames via a single ffmpeg ``fps`` filter invocation.

        This is optimal for short/medium videos because it avoids ``frame_count``
        subprocess spawns.  Frame timestamps are recovered from the sequential
        file naming (``frame_%04d.png``) via ``index / sample_rate``.
        """
        fps = self.sample_rate
        if fps <= 0:
            fps = frame_count / duration if duration > 0 else 1.0
        if fps <= 0:
            fps = 1.0

        cmd = [
            "ffmpeg",
            "-y",
            "-i", str(video_path),
            "-vf", f"fps={fps}",
            "-vframes", str(frame_count),
            "-q:v", "2",
            "-loglevel", "error",
            os.path.join(output_dir, "frame_%04d.png"),
        ]
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=120,
        )

        frames = []
        if result.returncode != 0:
            raise RuntimeError(
                f"ffmpeg fps filter failed: {result.stderr.strip()[:200]}"
            )

        # Collect output frames by glob pattern
        import glob as _glob
        pattern = os.path.join(output_dir, "frame_*.png")
        for path in sorted(_glob.glob(pattern)):
            basename = os.path.basename(path)
            # Extract index from "frame_0001.png"
            try:
                idx_str = basename.replace("frame_", "").replace(".png", "")
                index = int(idx_str)
            except ValueError:
                index = len(frames)
            timestamp = index / fps if fps > 0 else float(index)
            frames.append({
                "path": path,
                "timestamp": round(timestamp, 2),
                "index": index,
            })

        return frames

    def _extract_serial_seek(
        self,
        video_path: str,
        output_dir: str,
        frame_count: int,
        duration: float,
    ) -> List[Dict[str, Any]]:
        """Extract frames via separate ``ffmpeg -ss`` invocations.

        This is optimal for long videos where the fps filter would decode and
        discard >99% of source frames.
        """
        interval = duration / frame_count if duration > 0 else 1.0
        frames = []

        for i in range(frame_count):
            timestamp = i * interval
            frame_filename = f"frame_{i:04d}_{timestamp:.2f}s.png"
            frame_path = os.path.join(output_dir, frame_filename)

            try:
                cmd = [
                    "ffmpeg",
                    "-y",
                    "-ss", str(timestamp),
                    "-i", str(video_path),
                    "-vframes", "1",
                    "-q:v", "2",
                    "-loglevel", "error",
                    frame_path,
                ]
                result = subprocess.run(
                    cmd,
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    timeout=30,
                )

                if result.returncode == 0 and os.path.exists(frame_path):
                    frames.append({
                        "path": frame_path,
                        "timestamp": timestamp,
                        "index": i,
                    })
                else:
                    logger.warning(
                        f"Failed to extract frame at {timestamp:.2f}s: {result.stderr.strip()}"
                    )
            except subprocess.TimeoutExpired:
                logger.warning(f"Timeout extracting frame at {timestamp:.2f}s")
            except Exception as e:
                logger.error(f"Error extracting frame at {timestamp:.2f}s: {e}")

        return frames

    def extract_frames(
        self, video_path: str, output_dir: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """Extract frames from a video file.

        Args:
            video_path: Path to the video file
            output_dir: Directory to save extracted frames (temp dir if None)

        Returns:
            List of dicts with keys: path, timestamp, index
        """
        if not _check_ffmpeg_available():
            raise RuntimeError(
                "ffmpeg is required for video frame extraction. "
                "Install ffmpeg: https://ffmpeg.org/download.html"
            )

        metadata = _get_video_metadata(video_path)
        duration = metadata.get("duration", 0)
        if "error" in metadata:
            logger.warning(f"Could not get video metadata for {video_path}: {metadata['error']}")
            duration = 0

        # Calculate frame count based on sample rate
        if duration > 0:
            estimated_frames = int(duration * self.sample_rate)
        else:
            estimated_frames = self.max_frames

        # Apply max frames cap
        frame_count = min(estimated_frames, self.max_frames)

        if frame_count == 0:
            return []

        # Create output directory
        if output_dir is None:
            output_dir = tempfile.mkdtemp(prefix="rag_video_frames_")
        os.makedirs(output_dir, exist_ok=True)

        # ── Duration-aware routing ────────────────────────────────────────
        # Choose between single ffmpeg fps-filter invocation (fast for short
        # videos) and serial -ss seeks (efficient for long videos).
        video_fps = metadata.get("fps", 0) or 0
        total_source_frames = int(duration * video_fps) if video_fps > 0 else 0
        source_ratio = (total_source_frames / frame_count) if frame_count > 0 else 999
        use_fps_filter = (
            duration > 0
            and duration < self.FPS_FILTER_MAX_DURATION
            and source_ratio < self.FPS_FILTER_MAX_SOURCE_RATIO
        )

        if use_fps_filter:
            try:
                frames = self._extract_fps_filter(
                    video_path, output_dir, frame_count, duration
                )
                logger.info(
                    f"Extracted {len(frames)}/{frame_count} frames (fps-filter) from {video_path} "
                    f"(duration: {duration:.1f}s, source_ratio: {source_ratio:.0f}:1)"
                )
                return frames
            except Exception as e:
                logger.warning(
                    f"fps filter extraction failed ({e}), falling back to serial seek"
                )

        # Fallback: serial seek path
        frames = self._extract_serial_seek(
            video_path, output_dir, frame_count, duration
        )
        logger.info(
            f"Extracted {len(frames)}/{frame_count} frames (serial-seek) from {video_path} "
            f"(duration: {duration:.1f}s, sample_rate: {self.sample_rate} fps)"
        )
        return frames


# ── SceneDetector ──────────────────────────────────────────────────────────


class SceneDetector:
    """Detect scene boundaries in video using histogram difference."""

    def __init__(self, threshold: float = 0.3, min_scene_duration: float = 2.0):
        """Initialize scene detector.

        Args:
            threshold: Histogram difference threshold for scene change (0.0-1.0)
            min_scene_duration: Minimum duration in seconds between scene changes
        """
        self.threshold = threshold
        self.min_scene_duration = min_scene_duration

    def detect_scenes(self, video_path: str) -> List[Dict[str, Any]]:
        """Detect scene boundaries in a video.

        Uses ffmpeg's scene detection filter. Falls back to empty list
        if PIL is not available for histogram comparison.

        Args:
            video_path: Path to the video file

        Returns:
            List of scene dicts with keys: start_time, end_time
        """
        if not _check_ffmpeg_available():
            logger.warning("ffmpeg not available, skipping scene detection")
            return []

        try:
            # Use ffmpeg's built-in scene detection
            cmd = [
                "ffmpeg",
                "-i", str(video_path),
                "-vf", f"select='gt(scene\\,{self.threshold})',showinfo",
                "-f", "null",
                "-loglevel", "info",
                "-",
            ]
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=60,
            )

            # Parse scene change timestamps from stderr
            scene_times = []
            for line in result.stderr.split("\n"):
                if "pts_time:" in line:
                    match = re.search(r"pts_time:([\d.]+)", line)
                    if match:
                        t = float(match.group(1))
                        scene_times.append(t)

            # Build scene boundaries
            scenes = []
            prev_time = 0.0
            for t in scene_times:
                if t - prev_time >= self.min_scene_duration:
                    scenes.append({
                        "start_time": prev_time,
                        "end_time": t,
                    })
                    prev_time = t

            # Add final scene
            metadata = _get_video_metadata(video_path)
            duration = metadata.get("duration", prev_time)
            if duration > prev_time:
                scenes.append({
                    "start_time": prev_time,
                    "end_time": duration,
                })

            logger.info(f"Detected {len(scenes)} scenes in {video_path}")
            return scenes

        except subprocess.TimeoutExpired:
            logger.warning("Scene detection timed out")
            return []
        except Exception as e:
            logger.error(f"Scene detection failed: {e}")
            return []


# ── AudioTranscriber ───────────────────────────────────────────────────────


class AudioTranscriber:
    """Transcribe audio from video files using Whisper."""

    def __init__(self, model_size: str = "small", timeout: int = 300):
        """Initialize audio transcriber.

        Args:
            model_size: Whisper model size ('tiny', 'base', 'small', 'medium', 'large')
            timeout: Maximum transcription time in seconds
        """
        self.model_size = model_size
        self.timeout = timeout
        self._model = None
        self.last_segments: list[dict[str, Any]] = []

    def _load_model(self):
        """Lazy-load the Whisper model."""
        if self._model is not None:
            return self._model

        try:
            import whisper
            self._model = whisper.load_model(self.model_size)
            logger.info(f"Loaded Whisper model: {self.model_size}")
            return self._model
        except ImportError:
            raise ImportError(
                "openai-whisper is required for audio transcription. "
                "Install with: pip install openai-whisper"
            )

    def is_available(self) -> bool:
        """Check if Whisper is available without loading the model."""
        try:
            import whisper  # noqa: F401
            return True
        except ImportError:
            return False

    def transcribe(self, video_path: str) -> str:
        """Transcribe audio from a video file.

        Args:
            video_path: Path to the video file

        Returns:
            Transcribed text, or empty string if transcription fails or no audio
        """
        metadata = _get_video_metadata(video_path)
        if not metadata.get("has_audio", False):
            logger.info(f"No audio track in {video_path}, skipping transcription")
            return ""

        if not _check_ffmpeg_available():
            logger.warning("ffmpeg not available, cannot extract audio for transcription")
            return ""

        # Extract audio to temporary WAV file
        audio_path = None
        try:
            fd, audio_path = tempfile.mkstemp(suffix=".wav", prefix="rag_video_audio_")
            os.close(fd)

            extract_cmd = [
                "ffmpeg",
                "-y",
                "-i", str(video_path),
                "-vn",                # No video
                "-acodec", "pcm_s16le",  # 16-bit PCM
                "-ar", "16000",       # 16kHz sample rate
                "-ac", "1",           # Mono
                "-loglevel", "error",
                audio_path,
            ]
            result = subprocess.run(
                extract_cmd,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=60,
            )

            if result.returncode != 0 or not os.path.exists(audio_path):
                logger.warning(f"Audio extraction failed: {result.stderr.strip()}")
                return ""

            # Check extracted audio has content
            if os.path.getsize(audio_path) < 1024:
                logger.info("Extracted audio too small, skipping transcription")
                return ""

            # Load model and transcribe
            model = self._load_model()

            logger.info(f"Transcribing audio from {video_path}...")
            result = model.transcribe(
                audio_path,
                fp16=False,  # Use FP32 on CPU for compatibility
                language=None,  # Auto-detect language
            )

            transcript = result.get("text", "").strip()
            self.last_segments = [
                {
                    "start": float(seg.get("start", 0) or 0),
                    "end": float(seg.get("end", 0) or 0),
                    "text": str(seg.get("text", "")).strip(),
                }
                for seg in (result.get("segments") or [])
                if str(seg.get("text", "")).strip()
            ]
            detected_lang = result.get("language", "unknown")
            logger.info(
                f"Transcription complete: {len(transcript)} chars, "
                f"language: {detected_lang}"
            )

            return transcript

        except subprocess.TimeoutExpired:
            logger.warning("Audio extraction timed out")
            return ""
        except Exception as e:
            logger.error(f"Transcription failed: {e}")
            self.last_segments = []
            return ""
        finally:
            # Clean up temporary audio file
            if audio_path and os.path.exists(audio_path):
                try:
                    os.unlink(audio_path)
                except OSError:
                    pass


# ── VideoModalProcessor ────────────────────────────────────────────────────


class VideoModalProcessor(BaseModalProcessor):
    """Processor specialized for video content.

    Orchestrates frame extraction, audio transcription, scene detection,
    and VLM analysis to create knowledge graph entities for video content.
    """

    def __init__(
        self,
        lightrag: LightRAG,
        modal_caption_func,
        context_extractor: ContextExtractor = None,
        frame_extractor: FrameExtractor = None,
        audio_transcriber: AudioTranscriber = None,
        scene_detector: SceneDetector = None,
        video_frame_concurrent: int = 3,
        video_segment_concurrent: int = 2,
        enable_frame_cache: bool = True,
        config = None,
    ):
        """Initialize video processor.

        Args:
            lightrag: LightRAG instance
            modal_caption_func: Function for generating descriptions (VLM)
            context_extractor: Context extractor instance
            frame_extractor: Optional pre-configured FrameExtractor
            audio_transcriber: Optional pre-configured AudioTranscriber (None = no audio)
            scene_detector: Optional pre-configured SceneDetector
            video_frame_concurrent: Max concurrent frame VLM calls (default 3)
            video_segment_concurrent: Max concurrent v2 segments per video (default 2)
            enable_frame_cache: Whether to cache frame descriptions (default True)
            config: Optional RAGAnythingConfig for duration/transcript/whisper settings
        """
        super().__init__(lightrag, modal_caption_func, context_extractor)

        # Initialize sub-components
        self.frame_extractor = frame_extractor or FrameExtractor()
        self.audio_transcriber = audio_transcriber  # None = graceful degradation
        self.scene_detector = scene_detector or SceneDetector()

        # Config-derived attributes (safe defaults when config is None)
        self._max_duration = int(getattr(config, "video_max_duration", 3600) or 3600)
        self._max_transcript_tokens = int(getattr(config, "max_transcript_tokens", 4000) or 4000)
        self._whisper_model_size = str(getattr(config, "whisper_model_size", "small") or "small")
        self._video_index_profile_version = str(
            getattr(config, "video_index_profile_version", "v2") or "v2"
        )

        # Frame concurrency control (isolated from image processing semaphore)
        self._frame_semaphore = asyncio.Semaphore(video_frame_concurrent)

        # Per-video segment concurrency: each segment runs one VLM description
        # plus entity extraction; effective extraction concurrency is bounded by
        # segment_concurrent * llm_model_max_async.
        self._video_segment_concurrent = max(1, int(video_segment_concurrent))
        self._segment_semaphore = asyncio.Semaphore(self._video_segment_concurrent)

        # Frame description cache
        self._enable_frame_cache = enable_frame_cache
        self._frame_cache: Dict[str, List[str]] = {}

        # Check optional dependencies
        self._ffmpeg_available = _check_ffmpeg_available()
        self._ffprobe_available = _check_ffprobe_available()
        self._whisper_available = (
            self.audio_transcriber.is_available()
            if self.audio_transcriber
            else False
        )

        if not self._ffmpeg_available:
            logger.warning(
                "ffmpeg not found on PATH. Video processing requires ffmpeg. "
                "Install from: https://ffmpeg.org/download.html"
            )

        if self.audio_transcriber and not self._whisper_available:
            logger.warning(
                "Whisper not available but audio_transcriber configured. "
                "Install with: pip install openai-whisper. "
                "Video processing will continue without audio transcription."
            )

    @property
    def capabilities(self) -> Dict[str, bool]:
        """Report processor capabilities."""
        return {
            "video_processing": True,
            "frame_extraction": self._ffmpeg_available,
            "audio_transcription": self._whisper_available,
            "scene_detection": self._ffmpeg_available,
            "frame_cache": self._enable_frame_cache,
            "parallel_frames": True,
        }

    def _get_cache_key(self, video_path: str, sample_rate: float) -> str:
        """Generate a cache key from video path, mtime, and sample rate.

        Args:
            video_path: Absolute path to the video file
            sample_rate: Frames-per-second sampling rate

        Returns:
            16-char hex digest, or empty string if cache disabled
        """
        if not self._enable_frame_cache:
            return ""

        try:
            mtime = os.path.getmtime(video_path)
            raw = f"{video_path}|{mtime}|{sample_rate}"
            return hashlib.sha256(raw.encode()).hexdigest()[:16]
        except OSError:
            return ""

    def _encode_image_to_base64(self, image_path: str) -> str:
        """Encode a freshly extracted frame, tolerating short-lived file locks."""
        failure = ""
        for attempt in range(3):
            try:
                with open(image_path, "rb") as image_file:
                    image_bytes = image_file.read()
                if image_bytes:
                    return base64.b64encode(image_bytes).decode("utf-8")
                failure = "empty_file"
            except OSError as exc:
                failure = type(exc).__name__
            except Exception as exc:
                failure = type(exc).__name__
                break
            if attempt < 2:
                time.sleep(0.1 * (attempt + 1))

        # Do not log an upload path: it is server-side-only metadata.  The
        # stable error below is surfaced by the Worker as a retryable failure.
        logger.warning(
            "Unable to encode extracted video frame after retries: reason=%s",
            failure or "unknown",
        )
        return ""

    def _truncate_transcript(self, text: str, max_tokens: int) -> str:
        """Truncate transcript to max_tokens at the nearest sentence boundary.

        Uses tiktoken ``cl100k_base`` for accurate token counting when available,
        falling back to character-based estimation (``len(text) * 0.6``) otherwise.
        Truncation always lands on a sentence boundary (。！？\\n) and appends a
        ``[转录已截断]`` marker so downstream consumers know the text is partial.

        Args:
            text: Raw transcription text
            max_tokens: Token budget (from config.max_transcript_tokens)

        Returns:
            Truncated text with truncation marker appended, or original text if
            it already fits within the token budget.
        """
        if not text:
            return text

        # Token counting: prefer tiktoken, fall back to character estimate
        token_count = 0
        try:
            import tiktoken
            enc = tiktoken.get_encoding("cl100k_base")
            tokens = enc.encode(text)
            token_count = len(tokens)
        except (ImportError, Exception):
            # Fallback: ~0.6 tokens per character for mixed Chinese/English text
            token_count = int(len(text) * 0.6)

        if token_count <= max_tokens:
            return text

        # Truncate: reverse-scan for nearest sentence boundary
        # Estimate character cutoff: max_tokens / 0.6 tokens-per-char
        char_cutoff = int(max_tokens / 0.6)
        truncated = text[:char_cutoff]

        # Find last sentence boundary (。！？\n) within the cutoff region
        boundary = -1
        for sep in ("。", "！", "？", "\n"):
            pos = truncated.rfind(sep)
            if pos > boundary:
                boundary = pos

        if boundary > 0:
            truncated = truncated[: boundary + 1]

        return truncated + "[转录已截断]"

    async def generate_description_only(
        self,
        modal_content,
        content_type: str,
        item_info: Dict[str, Any] = None,
        entity_name: str = None,
        doc_id: str = None,
        file_path: str = "",
    ) -> Tuple[str, Dict[str, Any]]:
        """Generate video description and entity info.

        Pipeline:
        1. Validate video file
        2. Extract key frames
        3. Transcribe audio (if available and enabled)
        4. Analyze frames with VLM
        5. Synthesize comprehensive description

        Args:
            modal_content: Video content info (dict with 'video_path' or string)
            content_type: Type of modal content ("video")
            item_info: Item information for context extraction
            entity_name: Optional predefined entity name

        Returns:
            Tuple of (enhanced_caption, entity_info)
        """
        try:
            # Parse video content
            if isinstance(modal_content, str):
                try:
                    content_data = json.loads(modal_content)
                except json.JSONDecodeError:
                    content_data = {"video_path": modal_content}
            else:
                content_data = modal_content

            video_path = content_data.get("video_path", "")
            if not video_path:
                raise ValueError("No video_path provided in modal_content")

            video_path_obj = Path(video_path)
            if not video_path_obj.exists():
                raise FileNotFoundError(f"Video file not found: {video_path}")

            # Validate video
            validation = validate_video_file(str(video_path_obj))
            if not validation.get("valid", False):
                raise ValueError(f"Invalid video file: {validation.get('error')}")

            # Check if skippable
            skip_result = check_video_skippable(str(video_path_obj))
            if skip_result:
                skip_reason, fallback_label = skip_result
                logger.info(f"Skipping video {video_path}: {skip_reason}")
                fallback_entity = {
                    "entity_name": (
                        f"{video_path_obj.stem} (video)"
                    ),
                    "entity_type": "video",
                    "summary": fallback_label,
                    "analysis_source": "fallback",
                    "non_indexable": True,
                }
                return f"[{fallback_label}]", fallback_entity

            metadata = validation["metadata"]
            duration = metadata.get("duration", 0)

            # Duration enforcement: reject videos exceeding max_duration
            if duration > self._max_duration:
                raise ValueError(
                    f"视频时长 {duration:.1f}s 超过上限 {self._max_duration}s，"
                    f"请调整 VIDEO_MAX_DURATION 环境变量或截取片段后重试"
                )

            # Extract frames
            logger.info(f"Extracting frames from {video_path}...")
            frames = self.frame_extractor.extract_frames(str(video_path_obj))
            if not frames:
                logger.warning(f"No frames extracted from {video_path}")
                fallback_entity = {
                    "entity_name": f"{video_path_obj.stem} (video)",
                    "entity_type": "video",
                    "summary": f"Video: {video_path_obj.name} ({duration:.1f}s, no frames extracted)",
                    "analysis_source": "fallback",
                    "non_indexable": True,
                }
                return f"Video file: {video_path_obj.name}", fallback_entity

            # Transcribe audio (if audio_transcriber is available)
            transcript = ""
            transcript_segments: list[dict[str, Any]] = []
            if self.audio_transcriber and self._whisper_available:
                try:
                    transcript = self.audio_transcriber.transcribe(str(video_path_obj))
                    transcript_segments = list(getattr(self.audio_transcriber, "last_segments", []) or [])
                except Exception as e:
                    logger.warning(f"Audio transcription failed (continuing without): {e}")

            # Extract context
            context = ""
            if item_info:
                context = self._get_context_for_item(item_info)

            # Analyze representative frames with VLM
            # For efficiency, select key frames: first, last, and scene-change frames
            total_frames = len(frames)
            if total_frames <= 5:
                key_frames = frames
            else:
                # Select first, last, and evenly distributed frames up to 5
                indices = [0]
                step = max(1, (total_frames - 2) // 3)
                for idx in range(step, total_frames - 1, step):
                    indices.append(idx)
                indices.append(total_frames - 1)
                # Deduplicate and limit to 5
                indices = sorted(set(indices))[:5]
                key_frames = [frames[i] for i in indices]

            # Check frame cache
            cache_key = self._get_cache_key(
                str(video_path_obj), self.frame_extractor.sample_rate
            )
            if cache_key and cache_key in self._frame_cache:
                logger.info(f"Frame cache hit for {video_path}")
                frame_descriptions = list(self._frame_cache[cache_key])
            else:
                # Define per-frame analysis coroutine (isolated error handling)
                async def analyze_frame(frame: dict) -> str:
                    async with self._frame_semaphore:
                        try:
                            image_base64 = self._encode_image_to_base64(frame["path"])
                            if not image_base64:
                                return f"[Frame at {frame['timestamp']:.1f}s: image unavailable]"

                            frame_prompt = PROMPTS["vision_prompt"].format(
                                section_path=f"Video frame at {frame['timestamp']:.1f}s",
                                entity_name=f"frame_{frame['index']}_at_{frame['timestamp']:.1f}s",
                                image_path=frame["path"],
                                captions="None",
                                footnotes="None",
                            )

                            response = await self._call_modal_caption(
                                frame_prompt,
                                image_data=image_base64,
                                system_prompt=PROMPTS["IMAGE_ANALYSIS_SYSTEM"],
                            )

                            parsed = self._robust_json_parse(response)
                            desc = parsed.get("detailed_description", response[:200])
                            return f"[Frame {frame['index']} at {frame['timestamp']:.1f}s]: {desc}"
                        except Exception as e:
                            logger.warning(
                                f"Frame analysis failed for frame {frame['index']}: {e}"
                            )
                            return f"[Frame {frame['index']} at {frame['timestamp']:.1f}s: analysis failed]"

                # Concurrent frame analysis with independent semaphore
                tasks = [analyze_frame(f) for f in key_frames]
                results = await asyncio.gather(*tasks)
                frame_descriptions = list(results)

                # Write to cache
                if cache_key:
                    self._frame_cache[cache_key] = list(frame_descriptions)
                    logger.debug(f"Frame descriptions cached for key: {cache_key}")

            # Build video analysis prompt
            video_prompt = PROMPTS["video_prompt"].format(
                entity_name=entity_name or f"{video_path_obj.stem} (video)",
                video_path=str(video_path_obj),
                duration=f"{duration:.1f}",
                frame_count=str(len(frames)),
                frame_descriptions="\n\n".join(frame_descriptions),
                transcript=self._truncate_transcript(transcript, self._max_transcript_tokens)
                if transcript
                else "No audio transcript available",
                context=context if context else "No additional context",
            )

            # Call LLM for video synthesis
            response = await self._call_modal_caption(
                video_prompt,
                system_prompt=PROMPTS["VIDEO_ANALYSIS_SYSTEM"],
            )

            # Parse response
            enhanced_caption, entity_info = self._parse_video_response(
                response, entity_name
            )
            if isinstance(entity_info, dict):
                entity_info["analysis_source"] = "model"
                entity_info["non_indexable"] = False
                entity_info["video_duration"] = duration
                entity_info["video_fps"] = metadata.get("fps", 0)
                entity_info["video_frame_count"] = len(frames)
                entity_info["transcript_segments"] = transcript_segments

            # Clean up temp frames
            try:
                import shutil
                frame_dir = os.path.dirname(frames[0]["path"]) if frames else None
                if frame_dir and os.path.exists(frame_dir):
                    shutil.rmtree(frame_dir, ignore_errors=True)
            except Exception:
                pass

            return enhanced_caption, entity_info

        except Exception as e:
            logger.error(f"Error generating video description: {e}")
            fallback_entity = {
                "entity_name": entity_name
                or f"video_{compute_mdhash_id(str(modal_content))}",
                "entity_type": "video",
                "summary": f"Video content: {str(modal_content)[:100]}",
                "analysis_source": "fallback",
                "non_indexable": True,
                "processing_error": str(e)[:500],
            }
            return "[Video processing unavailable]", fallback_entity

    def _local_transcript(self, asr_segments: list[dict[str, Any]], start_ms: int, end_ms: int) -> str:
        return " ".join(
            str(item.get("text") or "").strip()
            for item in asr_segments
            if float(item.get("end") or 0) * 1000 > start_ms
            and float(item.get("start") or 0) * 1000 < end_ms
            and str(item.get("text") or "").strip()
        ).strip()

    async def _ensure_chinese_segment_summary(self, summary: object) -> str:
        """Translate one non-Chinese model response once or fail before indexing."""
        value = str(summary or "").strip()
        if _has_chinese_summary(value):
            return value[:2000]

        translated = await self._call_modal_caption(
            "请将以下教学视频片段摘要改写为简体中文。"
            "只返回中文摘要，不要保留英文标题、标签或字段名；"
            "型号、数字和单位可以保留。\n"
            f"待改写摘要：{value}",
            system_prompt="你是中文教学视频分析助手。所有输出必须使用简体中文。",
        )
        translated = str(translated or "").strip()
        if not _has_chinese_summary(translated):
            raise _probe_error("video_segment_summary_not_chinese")
        return translated[:2000]

    async def _describe_segment_frames(
        self, frames: list[dict[str, Any]], transcript: str, start_ms: int, end_ms: int
    ) -> tuple[str, list[dict[str, Any]]]:
        """Describe only a segment's representative frames; frame paths stay local."""
        if not frames:
            raise _probe_error("video_frame_extraction_empty")
        picks = [frames[0], frames[len(frames) // 2], frames[-1]]
        selected: list[dict[str, Any]] = []
        for frame in picks:
            if frame not in selected:
                selected.append(frame)

        async def describe(frame: dict[str, Any]) -> str:
            async with self._frame_semaphore:
                image_data = self._encode_image_to_base64(frame["path"])
                if not image_data:
                    return ""
                prompt = (
                    "请用中文分析教学视频中的这一帧，只返回 JSON："
                    '{"detailed_description":"画面中的操作、器材、读数和安全要点"}。\n'
                    f"所属视频片段：{start_ms}ms-{end_ms}ms\n"
                    f"画面时间：{float(frame['timestamp']):.1f} 秒\n"
                    "描述必须使用中文，不要使用英文标签或文件路径。"
                )
                response = await self._call_modal_caption(
                    prompt,
                    image_data=image_data,
                    system_prompt="你是教学视频画面分析助手。所有输出必须使用中文。",
                )
                parsed = self._robust_json_parse(response)
                return str(parsed.get("detailed_description") or response).strip()[:900]

        descriptions = await asyncio.gather(*(describe(frame) for frame in selected))
        usable = [description for description in descriptions if description]
        if not usable:
            raise _probe_error("video_frame_encode_failed")
        local_prompt = (
            "请将以下教学视频片段归纳为一个中文操作步骤。"
            "必须说明操作、器材或对象、读数（如有）、安全注意事项和可见依据。"
            "仅输出中文摘要，不要使用英文标题、标签或字段名。\n"
            f"时间范围：{start_ms}ms-{end_ms}ms\n"
            f"本段转写：{transcript or '无'}\n"
            f"画面观察：{' '.join(usable)}"
        )
        summary = await self._call_modal_caption(
            local_prompt,
            system_prompt="你是中文教学视频分析助手。所有输出必须使用中文。",
        )
        frame_refs = [
            {"timestamp_ms": round(float(frame["timestamp"]) * 1000), "index": int(frame["index"])}
            for frame in selected
        ]
        return await self._ensure_chinese_segment_summary(summary), frame_refs

    async def _process_v2_segments(
        self, modal_content, content_type: str, file_path: str, entity_name: str,
        item_info: Dict[str, Any], batch_mode: bool, doc_id: str, chunk_order_index: int,
    ):
        if isinstance(modal_content, str):
            try:
                content_data = json.loads(modal_content)
            except json.JSONDecodeError:
                content_data = {"video_path": modal_content}
        else:
            content_data = modal_content or {}
        video_path = str(content_data.get("video_path") or "")
        if not video_path:
            raise _probe_error("video_source_unavailable")
        _v2_start = time.perf_counter()
        probe_start = time.perf_counter()
        metadata = probe_video_for_indexing(video_path)
        duration = float(metadata["duration"])
        if duration > self._max_duration:
            raise _probe_error("video_duration_exceeded")

        workspace = str(getattr(self.lightrag, "workspace", "")).replace("\\", "/")
        kb_name = "default" if workspace == "./rag_storage" else workspace.rsplit("_", 1)[-1]
        parent_name = entity_name or Path(video_path).stem

        # A retried task may carry artifacts from an attempt that was killed
        # before its compensation cleanup ran.  Remove them up front so the
        # deterministic segment rows and chunks are inserted exactly once.
        await self._preclean_v2_segment_artifacts(doc_id, kb_name, parent_name)

        frame_dir = ""
        frames: list[dict[str, Any]] = []
        pending_chunk_ids: list[str] = []
        pending_node_names: list[str] = []
        chunk_ids: list[str] = []
        results: list[Any] = []
        segment_content_length = 0
        # Per-stage timing in milliseconds; emitted as structured log lines
        # so long videos can be profiled without touching document metadata.
        stage_timings: dict[str, float] = {"probe_ms": _elapsed_ms(probe_start)}
        segment_metrics: list[dict[str, float]] = []
        try:
            _stage_start = time.perf_counter()
            frame_dir = tempfile.mkdtemp(prefix="rag_video_frames_")
            frames = self.frame_extractor.extract_frames(video_path, output_dir=frame_dir)
            stage_timings["frames_ms"] = _elapsed_ms(_stage_start)
            if not frames:
                raise _probe_error("video_frame_extraction_empty")
            transcript = ""
            asr_segments: list[dict[str, Any]] = []
            _stage_start = time.perf_counter()
            if self.audio_transcriber and self._whisper_available and metadata.get("has_audio"):
                transcript = self.audio_transcriber.transcribe(video_path)
                asr_segments = list(getattr(self.audio_transcriber, "last_segments", []) or [])
            stage_timings["asr_ms"] = _elapsed_ms(_stage_start)
            _stage_start = time.perf_counter()
            scene_boundaries = []
            if self.scene_detector:
                for scene in self.scene_detector.detect_scenes(video_path):
                    value = scene.get("end_time")
                    if isinstance(value, (int, float)):
                        scene_boundaries.append(float(value))
            stage_timings["scene_ms"] = _elapsed_ms(_stage_start)

            from raganything.video_segments import plan_segments, segment_id, source_sha256
            segments = plan_segments(duration, asr_segments=asr_segments, scene_boundaries=scene_boundaries)
            source_hash = source_sha256(video_path)
            media_id = f"video-{source_hash[:32]}"
            from raganything.processor.chunk_processor import compute_chunk_id
            from raganything.services.video_segments import upsert_video_asset, upsert_video_segment
            await upsert_video_asset({
                "media_id": media_id, "kb_name": kb_name, "document_id": doc_id,
                "source_sha256": source_hash, "original_name": Path(video_path).name,
                "server_path": video_path, "duration_ms": round(duration * 1000),
                "fps": metadata["fps"], "has_audio": metadata.get("has_audio", False),
                "profile_version": self._video_index_profile_version,
            })

            async def _process_one_segment(offset: int, segment: Any) -> dict[str, Any]:
                """Describe, persist, and extract one independent segment.

                Runs under the per-video segment semaphore so model-endpoint
                concurrency stays bounded.  Only computes and mutates
                in-memory storages; PostgreSQL rows and deterministic result
                ordering are applied by the caller after every segment
                finishes, so completion order never changes persisted order.
                """
                async with self._segment_semaphore:
                    seg_timings: dict[str, float] = {}
                    local_frames = [
                        frame for frame in frames
                        if segment.start_ms <= float(frame["timestamp"]) * 1000 <= segment.end_ms
                    ]
                    local_text = segment.transcript or self._local_transcript(
                        asr_segments, segment.start_ms, segment.end_ms
                    )
                    _seg_start = time.perf_counter()
                    visual_summary, frame_refs = await self._describe_segment_frames(
                        local_frames or frames, local_text, segment.start_ms, segment.end_ms
                    )
                    seg_timings["describe_ms"] = _elapsed_ms(_seg_start)
                    chunk_text = (
                        f"视频片段：{segment.index + 1}/{len(segments)}\n"
                        f"时间范围：{segment.start_ms}ms-{segment.end_ms}ms\n"
                        f"媒体标识：{media_id}\n"
                        f"操作摘要：{visual_summary}"
                    )[:8000]
                    segment_entity_name = f"{parent_name} 第{segment.index + 1}段"
                    segment_info = {
                        "entity_name": segment_entity_name,
                        "entity_type": "video_segment",
                        "summary": visual_summary,
                        "parent_video": parent_name,
                        "segment_index": segment.index,
                        "start_ms": segment.start_ms,
                        "end_ms": segment.end_ms,
                        "media_id": media_id,
                    }
                    chunk_id = compute_chunk_id(chunk_text)
                    pending_chunk_ids.append(chunk_id)
                    pending_node_names.append(segment_entity_name)
                    _seg_start = time.perf_counter()
                    _chunk, persisted, _early_results = await self._create_entity_and_chunk(
                        chunk_text, segment_info, file_path, batch_mode,
                        doc_id, chunk_order_index + offset,
                        defer_flush=True, defer_extraction=True,
                    )
                    seg_timings["create_ms"] = _elapsed_ms(_seg_start)
                    persisted_chunk_id = persisted.get("chunk_id")
                    if not persisted_chunk_id:
                        raise _probe_error("video_segment_chunk_missing")
                    if persisted_chunk_id != chunk_id:
                        pending_chunk_ids.append(persisted_chunk_id)
                        chunk_id = persisted_chunk_id
                    _seg_start = time.perf_counter()
                    chunk_results = await self._process_chunk_for_extraction(
                        chunk_id, segment_entity_name, batch_mode
                    ) or []
                    seg_timings["extract_ms"] = _elapsed_ms(_seg_start)
                    logger.info(
                        "video_v2_segment_metrics doc_id=%s index=%d "
                        "describe_ms=%.0f create_ms=%.0f extract_ms=%.0f",
                        doc_id, segment.index,
                        seg_timings["describe_ms"],
                        seg_timings["create_ms"],
                        seg_timings["extract_ms"],
                    )
                    segment_metrics.append(seg_timings)
                    return {
                        "offset": offset,
                        "chunk_id": chunk_id,
                        "chunk_results": chunk_results or [],
                        "visual_summary": visual_summary,
                        "frame_refs": frame_refs,
                        "local_text": local_text,
                        "content_length": len(chunk_text),
                    }

            _segments_start = time.perf_counter()
            gathered = await asyncio.gather(
                *(_process_one_segment(offset, segment)
                  for offset, segment in enumerate(segments))
            )
            stage_timings["segments_ms"] = _elapsed_ms(_segments_start)
            stage_timings["describe_ms"] = sum(
                (metrics.get("describe_ms", 0.0) for metrics in segment_metrics), 0.0
            )
            stage_timings["extract_ms"] = sum(
                (metrics.get("extract_ms", 0.0) for metrics in segment_metrics), 0.0
            )

            # Deterministic write phase: PostgreSQL rows, chunk ids, extraction
            # results, and the character-count summary follow segment order
            # regardless of which segment finished first.
            _pg_start = time.perf_counter()
            by_offset = {item["offset"]: item for item in gathered}
            for offset, segment in enumerate(segments):
                item = by_offset[offset]
                segment_content_length += item["content_length"]
                await upsert_video_segment({
                    "segment_id": segment_id(source_hash, segment.start_ms, segment.end_ms, self._video_index_profile_version),
                    "media_id": media_id, "kb_name": kb_name, "document_id": doc_id,
                    "segment_index": segment.index, "start_ms": segment.start_ms, "end_ms": segment.end_ms,
                    "transcript_text": item["local_text"], "visual_summary": item["visual_summary"],
                    "frame_refs": item["frame_refs"], "chunk_id": item["chunk_id"], "source_sha256": source_hash,
                    "profile_version": self._video_index_profile_version,
                })
                chunk_ids.append(item["chunk_id"])
                results.extend(item["chunk_results"])
            stage_timings["pg_ms"] = _elapsed_ms(_pg_start)

            # The parent is graph-only manifest data: it must not create a
            # competing full-video text/vector chunk.  Each segment remains
            # independently searchable and has an explicit belongs_to edge.
            parent_node = {
                "entity_id": parent_name,
                "entity_type": "video",
                "description": f"视频清单，包含 {len(chunk_ids)} 个语义片段",
                "source_id": chunk_ids[0] if chunk_ids else "",
                "created_at": int(time.time()),
            }
            pending_node_names.append(parent_name)
            await self.knowledge_graph_inst.upsert_node(parent_name, parent_node)
            for offset, chunk_id in enumerate(chunk_ids):
                segment_name = f"{parent_name} 第{offset + 1}段"
                await self.knowledge_graph_inst.upsert_edge(
                    segment_name,
                    parent_name,
                    {
                        "description": f"{segment_name} 属于 {parent_name}",
                        "keywords": "belongs_to,video_segment",
                        "source_id": chunk_id,
                        "weight": 10.0,
                        "file_path": file_path,
                    },
                )

            # Video segments bypass the normal text-chunk writer. Keep the
            # document summary in sync so list views do not report a completed
            # v2 video as having zero characters.
            current_doc_status = await self.lightrag.doc_status.get_by_id(doc_id)
            if current_doc_status:
                existing_metadata = current_doc_status.get("metadata") or {}
                metadata = (
                    dict(existing_metadata)
                    if isinstance(existing_metadata, dict)
                    else {}
                )
                try:
                    existing_length = int(current_doc_status.get("content_length") or 0)
                except (TypeError, ValueError):
                    existing_length = 0
                try:
                    previous_video_length = int(metadata.get("video_content_length") or 0)
                except (TypeError, ValueError):
                    previous_video_length = 0
                # Preserve ordinary text length in mixed documents and make
                # retries replace, rather than add, the previous video total.
                text_length = max(0, existing_length - previous_video_length)
                metadata["video_content_length"] = segment_content_length
                await self.lightrag.doc_status.upsert({
                    doc_id: {
                        **current_doc_status,
                        "content_length": text_length + segment_content_length,
                        "metadata": metadata,
                    }
                })
                await self.lightrag.doc_status.index_done_callback()
        except Exception:
            # A v2 video is an atomic indexing unit.  Remove every partial
            # LightRAG artifact before the Worker marks the task retryable so
            # the same deterministic segment IDs can be inserted on retry.
            logger.info(
                "video_v2_metrics %s",
                _format_metrics_line({
                    "doc_id": doc_id,
                    "failed": "true",
                    "segments_completed": len(segment_metrics),
                    "total_ms": round(_elapsed_ms(_v2_start), 1),
                    "probe_ms": round(stage_timings.get("probe_ms", 0.0), 1),
                    "frames_ms": round(stage_timings.get("frames_ms", 0.0), 1),
                    "asr_ms": round(stage_timings.get("asr_ms", 0.0), 1),
                    "scene_ms": round(stage_timings.get("scene_ms", 0.0), 1),
                }),
            )
            await self._cleanup_v2_segment_artifacts(
                doc_id=doc_id, kb_name=kb_name,
                chunk_ids=pending_chunk_ids, node_names=pending_node_names,
            )
            raise
        finally:
            if frame_dir and os.path.isdir(frame_dir):
                import shutil
                shutil.rmtree(frame_dir, ignore_errors=True)
        logger.info(
            "video_v2_metrics %s",
            _format_metrics_line({
                "doc_id": doc_id,
                "segments": len(segments),
                "concurrent": getattr(self, "_video_segment_concurrent", 2),
                "total_ms": round(_elapsed_ms(_v2_start), 1),
                "probe_ms": round(stage_timings.get("probe_ms", 0.0), 1),
                "frames_ms": round(stage_timings.get("frames_ms", 0.0), 1),
                "asr_ms": round(stage_timings.get("asr_ms", 0.0), 1),
                "scene_ms": round(stage_timings.get("scene_ms", 0.0), 1),
                "describe_ms": round(stage_timings.get("describe_ms", 0.0), 1),
                "extract_ms": round(stage_timings.get("extract_ms", 0.0), 1),
                "pg_ms": round(stage_timings.get("pg_ms", 0.0), 1),
            }),
        )
        return (
            f"视频清单：{parent_name}（共 {len(segments)} 个片段）",
            {"entity_name": parent_name, "entity_type": "video", "chunk_id": chunk_ids[0] if chunk_ids else None,
             "chunk_ids": chunk_ids, "non_indexable": True, "media_id": media_id},
            results,
        )

    async def _preclean_v2_segment_artifacts(
        self, doc_id: str, kb_name: str, parent_name: str
    ) -> None:
        """Remove artifacts a killed earlier attempt left for the same document.

        A retry can start only after a failed attempt; when that attempt was
        killed before its compensation cleanup ran, its deterministic segment
        rows, chunks, and graph nodes may still exist.  Cleaning them up front
        keeps the retry idempotent: the same rows are upserted exactly once
        and no stale chunk/vector/entity remains searchable.
        """
        try:
            from raganything.services.video_segments import list_video_segments
            rows = await list_video_segments(kb_name, doc_id)
        except Exception:
            logger.exception("v2 segment pre-clean list failed for document")
            return
        chunk_ids = [str(row.get("chunk_id")) for row in rows if row.get("chunk_id")]
        node_names: set[str] = set()
        if rows:
            node_names.add(parent_name)
        for row in rows:
            try:
                segment_index = int(row.get("segment_index"))
            except (TypeError, ValueError):
                continue
            node_names.add(f"{parent_name} 第{segment_index + 1}段")
            # Releases before Chinese localization used this graph node name.
            # Include it during pre-clean so a retry cannot leave stale nodes.
            node_names.add(f"{parent_name} segment {segment_index + 1}")
        if chunk_ids or node_names:
            await self._cleanup_v2_segment_artifacts(
                doc_id=doc_id, kb_name=kb_name,
                chunk_ids=chunk_ids, node_names=sorted(node_names),
            )

    async def _cleanup_v2_segment_artifacts(
        self, *, doc_id: str, kb_name: str,
        chunk_ids: list[str], node_names: list[str],
    ) -> None:
        """Compensate every partial artifact a failed v2 segment run persisted.

        ``adelete_by_doc_id`` cannot cover these artifacts: segment chunks are
        not declared in ``doc_status.chunks_list`` until the segment loop has
        fully succeeded, and batch mode skips ``full_entities``/``full_relations``
        tracking.  Delete them explicitly so a Worker retry can insert the
        same deterministic segment rows exactly once.
        """
        chunk_ids = [str(chunk_id) for chunk_id in chunk_ids if chunk_id]
        node_names = [str(name) for name in dict.fromkeys(node_names) if name]
        if chunk_ids:
            try:
                if getattr(self.lightrag, "chunks_vdb", None) is not None:
                    await self.lightrag.chunks_vdb.delete(chunk_ids)
            except Exception:
                logger.exception("v2 segment vector cleanup failed for document")
            try:
                if getattr(self.lightrag, "text_chunks", None) is not None:
                    await self.lightrag.text_chunks.delete(chunk_ids)
            except Exception:
                logger.exception("v2 segment chunk cleanup failed for document")
            await self._remove_v2_chunk_ids_from_doc_status(doc_id, chunk_ids)
        if node_names:
            await self._remove_v2_segment_graph_artifacts(node_names)
        try:
            from raganything.services.video_segments import delete_video_segments
            await delete_video_segments(kb_name, doc_id)
        except Exception:
            logger.exception("v2 segment catalog cleanup failed for document")
        try:
            if hasattr(self.lightrag, "_insert_done"):
                await self.lightrag._insert_done()
        except Exception:
            logger.exception("v2 segment cleanup persistence failed for document")

    async def _remove_v2_chunk_ids_from_doc_status(
        self, doc_id: str, chunk_ids: list[str]
    ) -> None:
        """Drop retried segment chunks from doc_status so BM25/vector rebuilds
        and ``adelete_by_doc_id`` never see stale searchable entries."""
        doc_status = getattr(self.lightrag, "doc_status", None)
        if doc_status is None:
            return
        try:
            current = await doc_status.get_by_id(doc_id)
        except Exception:
            logger.exception("v2 segment doc_status read failed for document")
            return
        if not isinstance(current, dict):
            return
        remove = set(chunk_ids)
        chunks_list = [str(value) for value in current.get("chunks_list") or [] if value]
        remaining = [chunk_id for chunk_id in chunks_list if chunk_id not in remove]
        if remaining == chunks_list:
            return
        try:
            await doc_status.upsert({
                doc_id: {
                    **current,
                    "chunks_list": remaining,
                    "chunks_count": len(remaining),
                    "updated_at": current.get("updated_at"),
                }
            })
            if hasattr(doc_status, "index_done_callback"):
                await doc_status.index_done_callback()
        except Exception:
            logger.exception("v2 segment doc_status cleanup failed for document")

    async def _remove_v2_segment_graph_artifacts(self, node_names: list[str]) -> None:
        """Remove v2 segment nodes, their incident edges, and all related
        entity/relationship vectors and tracking storage."""
        lightrag = self.lightrag
        graph = getattr(lightrag, "chunk_entity_relation_graph", None)
        edge_pairs: list[tuple[str, str]] = []
        try:
            if graph is not None and hasattr(graph, "get_nodes_edges_batch"):
                nodes_edges = await graph.get_nodes_edges_batch(node_names)
                seen: set[tuple[str, str]] = set()
                for edges in (nodes_edges or {}).values():
                    for src, tgt in edges or []:
                        pair = tuple(sorted((str(src), str(tgt))))
                        if pair not in seen:
                            seen.add(pair)
                            edge_pairs.append(pair)
            if edge_pairs and getattr(lightrag, "relationships_vdb", None) is not None:
                rel_ids = []
                for src, tgt in edge_pairs:
                    rel_ids.append(compute_mdhash_id(src + tgt, prefix="rel-"))
                    rel_ids.append(compute_mdhash_id(tgt + src, prefix="rel-"))
                await lightrag.relationships_vdb.delete(rel_ids)
            if edge_pairs and graph is not None and hasattr(graph, "remove_edges"):
                await graph.remove_edges(edge_pairs)
            if graph is not None and hasattr(graph, "remove_nodes"):
                await graph.remove_nodes(node_names)
            if getattr(lightrag, "entities_vdb", None) is not None:
                entity_ids = [compute_mdhash_id(name, prefix="ent-") for name in node_names]
                await lightrag.entities_vdb.delete(entity_ids)
            entity_chunks = getattr(lightrag, "entity_chunks", None)
            if entity_chunks is not None:
                await entity_chunks.delete(node_names)
            if edge_pairs:
                from lightrag.utils import make_relation_chunk_key
                relation_chunks = getattr(lightrag, "relation_chunks", None)
                if relation_chunks is not None:
                    await relation_chunks.delete([
                        make_relation_chunk_key(src, tgt) for src, tgt in edge_pairs
                    ])
        except Exception:
            logger.exception("v2 segment graph cleanup failed for document")
    async def process_multimodal_content(
        self,
        modal_content,
        content_type: str,
        file_path: str = "manual_creation",
        entity_name: str = None,
        item_info: Dict[str, Any] = None,
        batch_mode: bool = False,
        doc_id: str = None,
        chunk_order_index: int = 0,
    ) -> Tuple[str, Dict[str, Any]]:
        """Process video content with full pipeline.

        Args:
            modal_content: Video content to process
            content_type: Type of modal content ("video")
            file_path: Source file path
            entity_name: Optional predefined entity name
            item_info: Item information for context extraction
            batch_mode: Whether in batch processing mode
            doc_id: Document ID
            chunk_order_index: Chunk ordering index

        Returns:
            Tuple of (description, entity_info)
        """
        return await self._process_v2_segments(
            modal_content, content_type, file_path, entity_name, item_info,
            batch_mode, doc_id, chunk_order_index,
        )

    def _parse_video_response(
        self, response: str, entity_name: str = None
    ) -> Tuple[str, Dict[str, Any]]:
        """Parse video analysis response with robust JSON handling."""
        try:
            response_data = self._robust_json_parse(response)

            description = response_data.get("detailed_description", "")
            entity_data = response_data.get("entity_info", {})

            if not description or not entity_data:
                raise ValueError("Missing required fields in video response")

            if not all(
                key in entity_data
                for key in ["entity_name", "entity_type", "summary"]
            ):
                raise ValueError("Missing required fields in entity_info")

            entity_data["entity_name"] = (
                f"{entity_data['entity_name']} ({entity_data['entity_type']})"
            )
            if entity_name:
                entity_data["entity_name"] = entity_name

            return description, entity_data

        except (json.JSONDecodeError, AttributeError, ValueError) as e:
            logger.error(f"Error parsing video analysis response: {e}")
            logger.debug(f"Raw response: {response}")
            cleaned = self._strip_thinking_tags(response)
            fallback_entity = {
                "entity_name": entity_name
                or f"video_{compute_mdhash_id(cleaned)}",
                "entity_type": "video",
                "summary": cleaned[:100] + "..." if len(cleaned) > 100 else cleaned,
            }
            return cleaned, fallback_entity
