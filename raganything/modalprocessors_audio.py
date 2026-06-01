"""
Audio Modal Processor for RAG-Anything

Processes audio files (MP3, WAV, FLAC, M4A, OGG) by transcribing speech to text
using faster-whisper, then feeding the transcribed text into LightRAG's knowledge graph.

Supports:
- Speech-to-text transcription with timestamps
- Meeting recordings, phone calls, podcasts, lectures
- Multiple languages (auto-detect or specify)

Dependencies:
    pip install raganything[audio]
    # or: pip install faster-whisper
"""

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
        segment_min_length: int = 30,
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
            segment_min_length: Minimum segment length in characters to keep
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

    def transcribe(self, audio_path: str) -> List[Dict[str, Any]]:
        """Transcribe audio file to timestamped segments.

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

    async def generate_description_only(
        self,
        modal_content,
        content_type: str,
        item_info: Dict[str, Any] = None,
        entity_name: str = None,
    ) -> Tuple[str, Dict[str, Any]]:
        """Generate audio transcription and entity info.

        Args:
            modal_content: Audio content dict with 'audio_path' key
            content_type: Type of modal content ("audio")
            item_info: Item information for context extraction
            entity_name: Optional predefined entity name

        Returns:
            Tuple of (transcription_text, entity_info)
        """
        try:
            # Parse audio content
            if isinstance(modal_content, str):
                try:
                    content_data = json.loads(modal_content)
                except json.JSONDecodeError:
                    content_data = {"audio_path": modal_content}
            else:
                content_data = modal_content

            audio_path = content_data.get("audio_path") or content_data.get("img_path")
            if not audio_path:
                raise ValueError(
                    f"No audio path provided in modal_content: {modal_content}"
                )

            # Transcribe
            segments = self.transcribe(audio_path)
            if not segments:
                raise RuntimeError(f"No speech detected in audio: {audio_path}")

            # Format transcription
            transcription = self._segments_to_text(segments)

            # Generate entity info
            filename = Path(audio_path).stem
            duration = segments[-1]["end"] if segments else 0
            entity_info = {
                "entity_name": entity_name
                if entity_name
                else f"audio_{filename}",
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
        """Process audio content: transcribe and insert into knowledge graph.

        Args:
            modal_content: Audio content dict with 'audio_path' key
            content_type: Type of modal content ("audio")
            file_path: Source file path for attribution
            entity_name: Optional entity name
            item_info: Item info for context
            batch_mode: Whether in batch processing mode
            doc_id: Document ID
            chunk_order_index: Chunk ordering index

        Returns:
            Tuple of (chunk_text, entity_info)
        """
        try:
            # Generate transcription and entity info
            transcription, entity_info = await self.generate_description_only(
                modal_content, content_type, item_info, entity_name
            )

            # Parse audio path for chunk formatting
            if isinstance(modal_content, str):
                try:
                    content_data = json.loads(modal_content)
                except json.JSONDecodeError:
                    content_data = {"audio_path": modal_content}
            else:
                content_data = modal_content

            audio_path = content_data.get("audio_path") or content_data.get(
                "img_path", ""
            )

            # Build audio chunk text
            modal_chunk = (
                f"[Audio Content]\n"
                f"Source: {audio_path}\n"
                f"Entity: {entity_info['entity_name']}\n"
                f"Transcription:\n{transcription}"
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
            logger.error(f"Error processing audio content: {e}")
            fallback_entity = {
                "entity_name": entity_name
                if entity_name
                else f"audio_{compute_mdhash_id(str(modal_content))}",
                "entity_type": "audio",
                "summary": f"Audio content: {str(modal_content)[:100]}",
            }
            return str(modal_content), fallback_entity
