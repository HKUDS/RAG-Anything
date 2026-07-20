"""
Audio Modal Processor for RAG-Anything

Processes audio files (MP3, WAV, FLAC, M4A, OGG) by transcribing speech to text
using faster-whisper, then feeding the transcribed text into LightRAG's knowledge graph.

Supports:
- Speech-to-text transcription with timestamps
- Meeting recordings, phone calls, podcasts, lectures
- Multiple languages (auto-detect or specify)
- Long recordings are split into multiple token-bounded chunks (see
  ``generate_chunk_sections``)

Dependencies:
    pip install raganything[audio]
    # or: pip install faster-whisper
"""

import asyncio
import importlib.util
import json
import logging
import os
from pathlib import Path
from typing import Any, Dict, List, Tuple

from lightrag.utils import compute_mdhash_id

from .modalprocessors import BaseModalProcessor

logger = logging.getLogger(__name__)

# Supported audio file extensions
AUDIO_EXTENSIONS = {".mp3", ".wav", ".flac", ".m4a", ".ogg", ".wma", ".aac", ".opus"}


def is_audio_file(file_path: str) -> bool:
    """Check if a file is a supported audio format."""
    return Path(file_path).suffix.lower() in AUDIO_EXTENSIONS


def audio_deps_available() -> bool:
    """Return True if the optional audio dependencies are importable."""
    return importlib.util.find_spec("faster_whisper") is not None


class AudioModalProcessor(BaseModalProcessor):
    """Processor for audio content using faster-whisper for transcription.

    Transcribes audio files into timestamped text segments, then processes
    them through LightRAG for knowledge graph construction and retrieval.

    Suitable for:
    - Meeting recordings
    - Phone call recordings
    - Podcasts and interviews
    - Lectures and presentations
    - Voice memos

    Example:
        >>> processor = AudioModalProcessor(
        ...     lightrag=rag_instance,
        ...     modal_caption_func=caption_func,
        ...     whisper_model="large-v3",
        ... )
        >>> result = await processor.process_multimodal_content(
        ...     modal_content={"audio_path": "/path/to/meeting.mp3"},
        ...     content_type="audio",
        ... )
    """

    def __init__(
        self,
        lightrag,
        modal_caption_func,
        context_extractor=None,
        whisper_model: str = None,
        whisper_device: str = "auto",
        whisper_compute_type: str = "auto",
        language: str = None,
        segment_min_length: int = 0,
    ):
        """Initialize audio processor.

        Args:
            lightrag: LightRAG instance
            modal_caption_func: Function for generating descriptions
            context_extractor: Context extractor instance
            whisper_model: Whisper model size (tiny/base/small/medium/large-v3)
                          Defaults to env WHISPER_MODEL or "base"
            whisper_device: Device for inference ("auto", "cpu", "cuda")
            whisper_compute_type: Compute type ("auto", "float16", "int8")
            language: Language code (e.g., "zh", "en"). None for auto-detect.
            segment_min_length: Minimum segment length in characters to keep.
                Defaults to 0 (keep every non-empty segment); raising it drops
                short utterances such as "Yes." or "Revenue grew 23%.", so only
                increase it when you explicitly want to filter noise.
        """
        super().__init__(lightrag, modal_caption_func, context_extractor)

        self.whisper_model_name = whisper_model or os.environ.get(
            "WHISPER_MODEL", "base"
        )
        self.whisper_device = whisper_device
        self.whisper_compute_type = whisper_compute_type
        self.language = language or os.environ.get("WHISPER_LANGUAGE", None)
        self.segment_min_length = segment_min_length
        self._whisper_model = None

    @property
    def whisper(self):
        """Lazy-load whisper model on first use."""
        if self._whisper_model is None:
            try:
                from faster_whisper import WhisperModel
            except ImportError:
                raise ImportError(
                    "faster-whisper is required for audio processing. "
                    "Install it with: pip install raganything[audio] "
                    "or: pip install faster-whisper"
                )

            logger.info(
                f"Loading whisper model: {self.whisper_model_name} "
                f"(device={self.whisper_device})"
            )
            self._whisper_model = WhisperModel(
                self.whisper_model_name,
                device=self.whisper_device,
                compute_type=self.whisper_compute_type,
            )
        return self._whisper_model

    @staticmethod
    def _resolve_audio_path(modal_content) -> str:
        """Extract the audio path from dict/JSON/string modal content."""
        if isinstance(modal_content, str):
            try:
                content_data = json.loads(modal_content)
            except json.JSONDecodeError:
                return modal_content
        else:
            content_data = modal_content
        return content_data.get("audio_path") or content_data.get("img_path") or ""

    def transcribe(self, audio_path: str) -> List[Dict[str, Any]]:
        """Transcribe audio file to timestamped segments.

        Note: this is a blocking call; async callers should wrap it with
        ``asyncio.to_thread`` so it does not block the event loop.

        Args:
            audio_path: Path to the audio file

        Returns:
            List of segments with start, end (seconds) and text
        """
        if not Path(audio_path).exists():
            raise FileNotFoundError(f"Audio file not found: {audio_path}")

        logger.info(f"Transcribing audio: {audio_path}")

        segments_iter, info = self.whisper.transcribe(
            audio_path,
            language=self.language,
            vad_filter=True,  # Filter out silence
            vad_parameters=dict(min_silence_duration_ms=500),
        )

        segments = []
        for segment in segments_iter:
            text = segment.text.strip()
            if len(text) >= self.segment_min_length:
                segments.append(
                    {
                        "start": segment.start,
                        "end": segment.end,
                        "text": text,
                    }
                )

        logger.info(
            f"Transcription complete: {len(segments)} segments, "
            f"language={info.language}, duration={info.duration:.1f}s"
        )
        return segments

    def _format_timestamp(self, seconds: float) -> str:
        """Format seconds to HH:MM:SS or MM:SS."""
        h = int(seconds // 3600)
        m = int((seconds % 3600) // 60)
        s = int(seconds % 60)
        if h > 0:
            return f"{h}:{m:02d}:{s:02d}"
        return f"{m}:{s:02d}"

    def _segments_to_text(self, segments: List[Dict[str, Any]]) -> str:
        """Convert transcription segments to formatted text with timestamps."""
        lines = []
        for seg in segments:
            start_str = self._format_timestamp(seg["start"])
            end_str = self._format_timestamp(seg["end"])
            lines.append(f"[{start_str}-{end_str}] {seg['text']}")
        return "\n".join(lines)

    def _group_segments_by_tokens(
        self, segments: List[Dict[str, Any]]
    ) -> List[List[Dict[str, Any]]]:
        """Group ordered segments into windows bounded by the chunk token budget.

        Segments are never split mid-utterance, so timestamp alignment is kept.
        A single oversized segment becomes its own window.
        """
        if not segments:
            return []

        budget = self._chunk_token_budget()
        windows: List[List[Dict[str, Any]]] = []
        current: List[Dict[str, Any]] = []
        current_tokens = 0

        for seg in segments:
            seg_tokens = self._count_tokens(seg["text"])
            if current and current_tokens + seg_tokens > budget:
                windows.append(current)
                current = []
                current_tokens = 0
            current.append(seg)
            current_tokens += seg_tokens

        if current:
            windows.append(current)
        return windows

    async def generate_description_only(
        self,
        modal_content,
        content_type: str,
        item_info: Dict[str, Any] = None,
        entity_name: str = None,
    ) -> Tuple[str, Dict[str, Any]]:
        """Generate the full audio transcription and entity info (single description).

        Returns the whole recording as one description. For long recordings the
        batch pipeline uses :meth:`generate_chunk_sections` instead, which splits
        the transcription into multiple token-bounded chunks.

        Returns:
            Tuple of (transcription_text, entity_info)
        """
        try:
            audio_path = self._resolve_audio_path(modal_content)
            if not audio_path:
                raise ValueError(
                    f"No audio path provided in modal_content: {modal_content}"
                )

            segments = await asyncio.to_thread(self.transcribe, audio_path)
            if not segments:
                raise RuntimeError(f"No speech detected in audio: {audio_path}")

            transcription = self._segments_to_text(segments)

            filename = Path(audio_path).stem
            duration = segments[-1]["end"] if segments else 0
            entity_info = {
                "entity_name": entity_name if entity_name else f"audio_{filename}",
                "entity_type": "audio",
                "summary": (
                    f"Audio recording ({self._format_timestamp(duration)} duration). "
                    f"Transcription: {segments[0]['text'][:100]}..."
                    if segments
                    else "Empty audio"
                ),
            }

            return transcription, entity_info

        except Exception as e:
            logger.error(f"Error generating audio transcription: {e}")
            fallback_entity = {
                "entity_name": entity_name
                if entity_name
                else f"audio_{compute_mdhash_id(str(modal_content))}",
                "entity_type": "audio",
                "summary": f"Audio content: {str(modal_content)[:100]}",
            }
            return str(modal_content), fallback_entity

    @staticmethod
    def _section_entity_name(
        entity_name: str, filename: str, part: int, total: int
    ) -> str:
        """Build a unique entity name per section."""
        base = entity_name if entity_name else f"audio_{filename}"
        return base if total == 1 else f"{base}_part{part}"

    async def generate_chunk_sections(
        self,
        modal_content,
        content_type: str,
        item_info: Dict[str, Any] = None,
        entity_name: str = None,
    ) -> List[Dict[str, Any]]:
        """Transcribe the audio and split it into one or more token-bounded sections.

        Short recordings yield a single section (equivalent to the legacy single
        chunk). Long recordings are split into multiple ordered sections so the
        transcription is not stored as one oversized chunk.
        """
        try:
            audio_path = self._resolve_audio_path(modal_content)
            if not audio_path:
                raise ValueError(
                    f"No audio path provided in modal_content: {modal_content}"
                )

            segments = await asyncio.to_thread(self.transcribe, audio_path)
            if not segments:
                raise RuntimeError(f"No speech detected in audio: {audio_path}")

            filename = Path(audio_path).stem
            windows = self._group_segments_by_tokens(segments)
            total = len(windows)

            sections: List[Dict[str, Any]] = []
            for k, window in enumerate(windows, start=1):
                text = self._segments_to_text(window)
                start = window[0]["start"]
                end = window[-1]["end"]
                name = self._section_entity_name(entity_name, filename, k, total)
                part_label = "" if total == 1 else f" part {k}/{total}"
                entity_info = {
                    "entity_name": name,
                    "entity_type": "audio",
                    "summary": (
                        f"Audio recording{part_label} "
                        f"({self._format_timestamp(start)}-{self._format_timestamp(end)}). "
                        f"Transcription: {window[0]['text'][:100]}..."
                    ),
                }
                window_meta = (
                    None
                    if total == 1
                    else {"start": start, "end": end, "part": k, "total": total}
                )
                sections.append(
                    {
                        "description": text,
                        "entity_info": entity_info,
                        "window_meta": window_meta,
                    }
                )

            return sections

        except Exception as e:
            logger.error(f"Error generating audio sections: {e}")
            fallback_entity = {
                "entity_name": entity_name
                if entity_name
                else f"audio_{compute_mdhash_id(str(modal_content))}",
                "entity_type": "audio",
                "summary": f"Audio content: {str(modal_content)[:100]}",
            }
            return [
                {
                    "description": str(modal_content),
                    "entity_info": fallback_entity,
                    "window_meta": None,
                }
            ]

    @staticmethod
    def _build_audio_chunk(audio_path: str, section: Dict[str, Any]) -> str:
        """Format a single audio section into chunk text."""
        meta = section.get("window_meta")
        header = "[Audio Content]"
        if meta:
            header += f" — part {meta['part']}/{meta['total']}"
        return (
            f"{header}\n"
            f"Source: {audio_path}\n"
            f"Entity: {section['entity_info']['entity_name']}\n"
            f"Transcription:\n{section['description']}"
        )

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
    ) -> Tuple[str, Dict[str, Any], List[Any]]:
        """Process audio content: transcribe and insert into knowledge graph.

        Long recordings produce multiple ordered chunks; each section is stored
        with a sequential ``chunk_order_index`` starting at the supplied value.

        Returns:
            Tuple of (primary_summary, primary_entity_info, all_chunk_results)
        """
        try:
            sections = await self.generate_chunk_sections(
                modal_content, content_type, item_info, entity_name
            )
            audio_path = self._resolve_audio_path(modal_content)

            all_chunk_results: List[Any] = []
            section_chunk_ids: List[str] = []
            primary_summary = None
            primary_entity = None

            for offset, section in enumerate(sections):
                modal_chunk = self._build_audio_chunk(audio_path, section)
                (
                    summary,
                    entity_ret,
                    chunk_results,
                ) = await self._create_entity_and_chunk(
                    modal_chunk,
                    section["entity_info"],
                    file_path,
                    batch_mode,
                    doc_id,
                    chunk_order_index + offset,
                )
                all_chunk_results.extend(chunk_results)
                if entity_ret.get("chunk_id"):
                    section_chunk_ids.append(entity_ret["chunk_id"])
                if primary_summary is None:
                    primary_summary = summary
                    primary_entity = entity_ret

            # Expose every section's chunk id so the caller can register them all
            if primary_entity is not None:
                primary_entity["chunk_ids"] = section_chunk_ids

            return primary_summary, primary_entity, all_chunk_results

        except Exception as e:
            logger.error(f"Error processing audio content: {e}")
            fallback_entity = {
                "entity_name": entity_name
                if entity_name
                else f"audio_{compute_mdhash_id(str(modal_content))}",
                "entity_type": "audio",
                "summary": f"Audio content: {str(modal_content)[:100]}",
            }
            return str(modal_content), fallback_entity, []
