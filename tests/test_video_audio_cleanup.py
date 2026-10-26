import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from raganything.modalprocessors_video import VideoModalProcessor


@pytest.mark.parametrize(
    "outcome", ["success", "no_audio", "write_error", "open_error"]
)
def test_extract_audio_closes_clip_and_cleans_failed_output(
    tmp_path, monkeypatch, outcome
):
    clip = MagicMock()
    clip.__enter__.return_value = clip
    clip.__exit__.side_effect = lambda *args: clip.close() and False
    if outcome == "no_audio":
        clip.audio = None
    else:

        def write_audiofile(path, **kwargs):
            Path(path).write_bytes(b"partial" if outcome == "write_error" else b"audio")
            if outcome == "write_error":
                raise OSError("audio encoder failed")

        clip.audio.write_audiofile.side_effect = write_audiofile
    factory = MagicMock(return_value=clip)
    if outcome == "open_error":
        factory.side_effect = OSError("video cannot be opened")
    monkeypatch.setitem(sys.modules, "moviepy", SimpleNamespace(VideoFileClip=factory))
    monkeypatch.setattr(
        "raganything.modalprocessors_video.tempfile.tempdir", str(tmp_path)
    )
    processor = object.__new__(VideoModalProcessor)

    result = processor._extract_audio_track("input.mp4")

    if outcome == "open_error":
        clip.close.assert_not_called()
    else:
        clip.close.assert_called_once()
    if outcome == "success":
        assert Path(result).read_bytes() == b"audio"
        Path(result).unlink()
    else:
        assert result is None
    assert list(tmp_path.iterdir()) == []
