import io
import json
from pathlib import Path

from raganything.parser.markdown_parser import MarkerParser


class _Response:
    def __init__(self, payload):
        self._stream = io.BytesIO(json.dumps(payload).encode("utf-8"))

    def read(self):
        return self._stream.read()

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False


def test_marker_remote_health_check(monkeypatch):
    monkeypatch.setenv("MARKER_SERVICE_URL", "http://marker:8765")
    monkeypatch.setattr(
        "urllib.request.urlopen", lambda request, timeout: _Response({"status": "ok"})
    )
    assert MarkerParser().check_installation() is True


def test_marker_remote_parse_uses_shared_paths(monkeypatch, tmp_path):
    source = tmp_path / "uploads" / "report.pdf"
    source.parent.mkdir()
    source.write_bytes(b"%PDF-1.4\n")
    output = tmp_path / "output"
    captured = {}

    def fake_urlopen(request, timeout):
        captured["url"] = request.full_url
        captured["payload"] = json.loads(request.data.decode("utf-8"))
        captured["timeout"] = timeout
        return _Response({"content_list": [{"type": "text", "text": "parsed", "page_idx": 0}]})

    monkeypatch.setenv("MARKER_SERVICE_URL", "http://marker:8765")
    monkeypatch.setenv("MARKER_SERVICE_TIMEOUT_SECONDS", "123")
    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)

    result = MarkerParser().parse_pdf(source, output_dir=str(output))

    assert result == [{"type": "text", "text": "parsed", "page_idx": 0}]
    assert captured["url"] == "http://marker:8765/v1/parse"
    assert captured["payload"]["input_path"] == str(source.resolve())
    assert captured["payload"]["output_dir"].startswith(str(output.resolve()))
    assert captured["timeout"] == 123.0


def test_marker_remote_uses_shared_output_when_none_is_supplied(monkeypatch, tmp_path):
    source = tmp_path / "report.pdf"
    source.write_bytes(b"%PDF-1.4\n")
    shared_output = tmp_path / "output"
    captured = {}

    def fake_urlopen(request, timeout):
        captured.update(json.loads(request.data.decode("utf-8")))
        return _Response({"content_list": [{"type": "text", "text": "parsed", "page_idx": 0}]})

    monkeypatch.setenv("MARKER_SERVICE_URL", "http://marker:8765")
    monkeypatch.setenv("MARKER_SHARED_OUTPUT_DIR", str(shared_output))
    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)

    MarkerParser().parse_pdf(source)

    assert captured["output_dir"].startswith(str(shared_output.resolve()))


def test_marker_remote_parse_rejects_malformed_result(monkeypatch, tmp_path):
    source = Path(tmp_path / "report.pdf")
    source.write_bytes(b"%PDF-1.4\n")
    monkeypatch.setenv("MARKER_SERVICE_URL", "http://marker:8765")
    monkeypatch.setattr("urllib.request.urlopen", lambda request, timeout: _Response({"unexpected": []}))

    try:
        MarkerParser().parse_pdf(source, output_dir=str(tmp_path / "output"))
    except RuntimeError as exc:
        assert "invalid parse result" in str(exc)
    else:
        raise AssertionError("expected invalid Marker worker result to raise")


def test_marker_worker_rejects_paths_outside_shared_volumes(monkeypatch, tmp_path):
    from raganything.parser import marker_worker

    input_root = tmp_path / "uploads"
    output_root = tmp_path / "output"
    input_root.mkdir()
    output_root.mkdir()
    source = input_root / "report.pdf"
    source.write_bytes(b"%PDF-1.4\n")
    monkeypatch.setattr(marker_worker, "INPUT_ROOTS", (input_root.resolve(),))
    monkeypatch.setattr(marker_worker, "OUTPUT_ROOT", output_root.resolve())

    assert marker_worker._resolve_input(str(source)) == source.resolve()
    assert marker_worker._resolve_output(str(output_root)) == output_root.resolve()

    try:
        marker_worker._resolve_input(str(tmp_path / "outside.pdf"))
    except marker_worker.MarkerWorkerError as exc:
        assert "outside the shared input" in str(exc)
    else:
        raise AssertionError("expected unshared input path to be rejected")

    try:
        marker_worker._resolve_output(str(tmp_path / "other-output"))
    except marker_worker.MarkerWorkerError as exc:
        assert "outside the shared output" in str(exc)
    else:
        raise AssertionError("expected unshared output path to be rejected")
