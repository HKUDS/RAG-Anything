## 1. Config Foundation

- [x] 1.1 Add `whisper_model_size` field to `RAGAnythingConfig` (default `"small"`, env var `WHISPER_MODEL_SIZE`)
- [x] 1.2 Add `__post_init__` enum validation for `whisper_model_size` — allow only `("tiny", "base", "small", "medium", "large")`, clamp to `"small"` with `UserWarning` on invalid
- [x] 1.3 Add `__post_init__` bounds validation for `video_max_duration` — clamp to [1, 86400] with `UserWarning` on out-of-range

## 2. Config-to-Processor Wiring

- [x] 2.1 Add `config` parameter to `VideoModalProcessor.__init__` — accept `RAGAnythingConfig` instance, extract `max_duration`, `max_transcript_tokens`, `whisper_model_size` as instance attributes with safe defaults when `config` is None
- [x] 2.2 Update `raganything/raganything.py` — pass `self.config` to `VideoModalProcessor(...)` constructor; pass `config.whisper_model_size` to `AudioTranscriber(model_size=...)`
- [x] 2.3 Update `AudioTranscriber.__init__` default from `model_size="tiny"` to `model_size="small"`

## 3. Duration Enforcement

- [x] 3.1 Add duration check in `generate_description_only()` — after `validate_video_file()` success, before frame extraction: if `metadata["duration"] > self._max_duration`, raise `ValueError` with duration and limit values
- [x] 3.2 Verify `multimodal_processor.py` exception handling — confirm the existing `except Exception` at the caller catches `ValueError` and creates a fallback entity without crashing the upload batch

## 4. Transcript Truncation Fix

- [x] 4.1 Implement `_truncate_transcript(text: str, max_tokens: int) -> str` helper — tiktoken `cl100k_base` token counting (fallback: `len(text) * 0.6`), reverse-scan for sentence boundary (`。！？\n`), append `[转录已截断]` marker
- [x] 4.2 Replace hardcoded `transcript[:4000]` in `generate_description_only()` with `self._truncate_transcript(transcript, self._max_transcript_tokens)`
- [x] 4.3 Verify `max_transcript_tokens` config value flows through to the truncation call site

## 5. Frame Extraction Optimization

- [x] 5.1 Implement `FrameExtractor._extract_fps_filter()` — single ffmpeg invocation using `fps=fps` filter, sequential file naming (`frame_%04d.png`), timestamp calculation via `index / sample_rate`
- [x] 5.2 Add duration-aware routing in `FrameExtractor.extract_frames()` — threshold = 180s OR `total_source_frames/output_frames < 100`: use fps filter; otherwise use existing serial seek
- [x] 5.3 Add fallback: if fps filter call fails, retry with serial seek and log `WARNING`
- [x] 5.4 Pass `video_max_frames` and `video_sample_rate` from config to `FrameExtractor` constructor in `raganything.py`

## 6. Integration Tests

- [x] 6.1 Test duration enforcement: video at 3599s (pass), 3600s (pass boundary), 3601s (reject with ValueError)
- [x] 6.2 Test Whisper model config: `WHISPER_MODEL_SIZE=base` loads `base` model; invalid value clamps to `small`
- [x] 6.3 Test transcript truncation: known-length transcript exceeding limit gets truncated at sentence boundary with marker
- [x] 6.4 Test frame extraction routing: short video uses fps filter path, long video uses serial seek path, fps failure falls back
- [x] 6.5 Test config wiring: verify `VideoModalProcessor` instance reads `max_duration`, `max_transcript_tokens` from passed config
- [x] 6.6 Verify existing `test_video_processor.py` tests still pass with updated defaults

## 7. Documentation

- [x] 7.1 Update `.env` comments — document `WHISPER_MODEL_SIZE` with allowed values and trade-off table
- [x] 7.2 Update `raganything/video_processor/__init__.py` docstring — mention new config dependency and duration enforcement behavior
