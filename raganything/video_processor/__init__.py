# -*- coding: utf-8 -*-
"""
Video Processing Module.

Layer: Core
Primary Responsibility: Video modal processing — frame extraction via ffmpeg,
    audio transcription, scene detection, VLM-based frame analysis.
Key Dependencies: lightrag (LightRAG), raganything.prompt (PROMPTS), ffmpeg

Components:
- FrameExtractor: Extract key frames from video files via ffmpeg
- SceneDetector: Detect scene boundaries for intelligent frame selection
- AudioTranscriber: Transcribe audio tracks via Whisper
- VideoModalProcessor: Main processor integrating all sub-components
"""

import os
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
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
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
    """Extract key frames from video files using ffmpeg."""

    def __init__(self, sample_rate: float = 1.0, max_frames: int = 60):
        """Initialize frame extractor.

        Args:
            sample_rate: Frames per second to extract (default 1.0 = 1 fps)
            max_frames: Maximum number of frames to extract per video
        """
        self.sample_rate = sample_rate
        self.max_frames = max_frames

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

        # Calculate frame interval for uniform sampling
        if duration > 0:
            interval = duration / frame_count
        else:
            interval = 1.0 / self.sample_rate if self.sample_rate > 0 else 1.0

        # Use ffmpeg to extract frames at calculated intervals
        # Extract by timestamp to get uniform distribution
        frame_paths = []

        for i in range(frame_count):
            timestamp = i * interval
            frame_filename = f"frame_{i:04d}_{timestamp:.2f}s.png"
            frame_path = os.path.join(output_dir, frame_filename)

            try:
                cmd = [
                    "ffmpeg",
                    "-y",
                    "-ss",
                    str(timestamp),
                    "-i",
                    str(video_path),
                    "-vframes",
                    "1",
                    "-q:v",
                    "2",
                    "-loglevel",
                    "error",
                    frame_path,
                ]
                result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)

                if result.returncode == 0 and os.path.exists(frame_path):
                    frame_paths.append({
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

        logger.info(
            f"Extracted {len(frame_paths)}/{frame_count} frames from {video_path} "
            f"(duration: {duration:.1f}s, sample_rate: {self.sample_rate} fps)"
        )

        return frame_paths


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
                cmd, capture_output=True, text=True, timeout=60
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

    def __init__(self, model_size: str = "tiny", timeout: int = 300):
        """Initialize audio transcriber.

        Args:
            model_size: Whisper model size ('tiny', 'base', 'small', 'medium', 'large')
            timeout: Maximum transcription time in seconds
        """
        self.model_size = model_size
        self.timeout = timeout
        self._model = None

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
            result = subprocess.run(extract_cmd, capture_output=True, text=True, timeout=60)

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
        enable_frame_cache: bool = True,
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
            enable_frame_cache: Whether to cache frame descriptions (default True)
        """
        super().__init__(lightrag, modal_caption_func, context_extractor)

        # Initialize sub-components
        self.frame_extractor = frame_extractor or FrameExtractor()
        self.audio_transcriber = audio_transcriber  # None = graceful degradation
        self.scene_detector = scene_detector or SceneDetector()

        # Frame concurrency control (isolated from image processing semaphore)
        self._frame_semaphore = asyncio.Semaphore(video_frame_concurrent)

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
        """Encode image to base64 for VLM API calls."""
        try:
            with open(image_path, "rb") as image_file:
                return base64.b64encode(image_file.read()).decode("utf-8")
        except Exception as e:
            logger.error(f"Failed to encode image {image_path}: {e}")
            return ""

    async def generate_description_only(
        self,
        modal_content,
        content_type: str,
        item_info: Dict[str, Any] = None,
        entity_name: str = None,
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
                }
                return f"[{fallback_label}]", fallback_entity

            metadata = validation["metadata"]
            duration = metadata.get("duration", 0)

            # Extract frames
            logger.info(f"Extracting frames from {video_path}...")
            frames = self.frame_extractor.extract_frames(str(video_path_obj))
            if not frames:
                logger.warning(f"No frames extracted from {video_path}")
                fallback_entity = {
                    "entity_name": f"{video_path_obj.stem} (video)",
                    "entity_type": "video",
                    "summary": f"Video: {video_path_obj.name} ({duration:.1f}s, no frames extracted)",
                }
                return f"Video file: {video_path_obj.name}", fallback_entity

            # Transcribe audio (if audio_transcriber is available)
            transcript = ""
            if self.audio_transcriber and self._whisper_available:
                try:
                    transcript = self.audio_transcriber.transcribe(str(video_path_obj))
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

                            response = await self.modal_caption_func(
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
                transcript=transcript[:4000] if transcript else "No audio transcript available",
                context=context if context else "No additional context",
            )

            # Call LLM for video synthesis
            response = await self.modal_caption_func(
                video_prompt,
                system_prompt=PROMPTS["VIDEO_ANALYSIS_SYSTEM"],
            )

            # Parse response
            enhanced_caption, entity_info = self._parse_video_response(
                response, entity_name
            )

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
            }
            return f"[Video processing error: {e}]", fallback_entity

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
        try:
            # Generate description and entity info
            enhanced_caption, entity_info = await self.generate_description_only(
                modal_content, content_type, item_info, entity_name
            )

            # Parse video content for building complete chunk
            if isinstance(modal_content, str):
                try:
                    content_data = json.loads(modal_content)
                except json.JSONDecodeError:
                    content_data = {"video_path": modal_content}
            else:
                content_data = modal_content

            video_path = content_data.get("video_path", "")

            # Get metadata for chunk
            validation = validate_video_file(video_path) if video_path else {"valid": False}
            metadata = validation.get("metadata", {}) if validation.get("valid") else {}
            duration = metadata.get("duration", 0)
            frame_count = metadata.get("fps", 0)

            # Build complete video chunk
            modal_chunk = PROMPTS["video_chunk"].format(
                video_path=video_path or "unknown",
                duration=f"{duration:.1f}",
                frame_count=str(int(frame_count * duration)) if frame_count > 0 else "unknown",
                transcript_summary=(enhanced_caption[:200] + "...")
                if len(enhanced_caption) > 200
                else enhanced_caption,
                enhanced_caption=enhanced_caption,
            )

            return await self._create_entity_and_chunk(
                modal_chunk,
                entity_info,
                file_path,
                batch_mode,
                doc_id,
                chunk_order_index,
            )

        except Exception as e:
            logger.error(f"Error processing video content: {e}")
            fallback_entity = {
                "entity_name": entity_name
                or f"video_{compute_mdhash_id(str(modal_content))}",
                "entity_type": "video",
                "summary": f"Video content: {str(modal_content)[:100]}",
            }
            return f"[Video processing error: {e}]", fallback_entity

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
