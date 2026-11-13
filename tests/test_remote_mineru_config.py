"""Tests for Remote MinerU and VLM HTTP backend configuration (#133).

Ensures that:
- MINERU_BACKEND, MINERU_VLM_URL, and MINERU_SOURCE environment variables populate RAGAnythingConfig
- Explicit RAGAnythingConfig parameters set mineru_backend, mineru_vlm_url, and mineru_source
- parse_document propagates config defaults to doc_parser.parse_pdf when kwargs are omitted
- Explicit kwargs passed to parse_document override config values
- _run_mineru_command correctly constructs -b, -u, and --source CLI flags for remote execution
"""

from unittest.mock import MagicMock, patch

import pytest

from raganything.config import RAGAnythingConfig
from raganything.parser import MineruParser
from raganything.processor import ProcessorMixin


class DummyProcessor(ProcessorMixin):
    def __init__(self, config=None):
        self.config = config or RAGAnythingConfig()
        self.doc_parser = MagicMock()
        self.logger = MagicMock()
        self.parse_cache = None


def test_mineru_remote_config_env_defaults(monkeypatch):
    """MINERU_* environment variables must populate RAGAnythingConfig defaults."""
    monkeypatch.setenv("MINERU_BACKEND", "vlm-http-client")
    monkeypatch.setenv("MINERU_VLM_URL", "http://remote-gpu:8000")
    monkeypatch.setenv("MINERU_SOURCE", "modelscope")

    config = RAGAnythingConfig()
    assert config.mineru_backend == "vlm-http-client"
    assert config.mineru_vlm_url == "http://remote-gpu:8000"
    assert config.mineru_source == "modelscope"


def test_mineru_remote_config_explicit_parameters():
    """Explicit parameters in RAGAnythingConfig must be stored."""
    config = RAGAnythingConfig(
        mineru_backend="vlm-http-client",
        mineru_vlm_url="http://remote-gpu:8000",
        mineru_source="huggingface",
    )
    assert config.mineru_backend == "vlm-http-client"
    assert config.mineru_vlm_url == "http://remote-gpu:8000"
    assert config.mineru_source == "huggingface"


@pytest.mark.asyncio
async def test_parse_document_propagates_remote_mineru_config(tmp_path):
    """parse_document must forward mineru_backend, mineru_vlm_url, mineru_source from config."""
    dummy_pdf = tmp_path / "test.pdf"
    dummy_pdf.write_bytes(b"%PDF-1.4 test")

    config = RAGAnythingConfig(
        working_dir=str(tmp_path),
        parser="mineru",
        mineru_backend="vlm-http-client",
        mineru_vlm_url="http://remote-gpu:8000",
        mineru_source="custom-source",
    )
    processor = DummyProcessor(config)
    processor.doc_parser.parse_pdf = MagicMock(
        return_value=[{"type": "text", "text": "sample"}]
    )

    content_list, _ = await processor.parse_document(str(dummy_pdf))
    assert len(content_list) == 1

    call_kwargs = processor.doc_parser.parse_pdf.call_args[1]
    assert call_kwargs["backend"] == "vlm-http-client"
    assert call_kwargs["vlm_url"] == "http://remote-gpu:8000"
    assert call_kwargs["source"] == "custom-source"


@pytest.mark.asyncio
async def test_parse_document_explicit_kwargs_override_config(tmp_path):
    """Explicit kwargs in parse_document must override RAGAnythingConfig defaults."""
    dummy_pdf = tmp_path / "test.pdf"
    dummy_pdf.write_bytes(b"%PDF-1.4 test")

    config = RAGAnythingConfig(
        working_dir=str(tmp_path),
        parser="mineru",
        mineru_backend="vlm-http-client",
        mineru_vlm_url="http://remote-gpu:8000",
    )
    processor = DummyProcessor(config)
    processor.doc_parser.parse_pdf = MagicMock(
        return_value=[{"type": "text", "text": "sample"}]
    )

    await processor.parse_document(
        str(dummy_pdf),
        backend="pipeline",
        vlm_url="http://local-override:9000",
    )

    call_kwargs = processor.doc_parser.parse_pdf.call_args[1]
    assert call_kwargs["backend"] == "pipeline"
    assert call_kwargs["vlm_url"] == "http://local-override:9000"


def test_run_mineru_command_flags_for_remote_vlm(tmp_path):
    """_run_mineru_command must append -b, -u, and --source to the command line."""
    fake_input = tmp_path / "doc.pdf"
    fake_output = tmp_path / "out"

    captured_cmds = []

    def fake_popen(cmd, **kwargs):
        captured_cmds.append(cmd)
        mock_proc = MagicMock()
        mock_proc.poll = MagicMock(return_value=0)
        mock_proc.wait = MagicMock(return_value=0)
        mock_proc.stdout = MagicMock()
        mock_proc.stdout.readline = MagicMock(return_value="")
        mock_proc.stderr = MagicMock()
        mock_proc.stderr.readline = MagicMock(return_value="")
        return mock_proc

    with patch("subprocess.Popen", side_effect=fake_popen):
        MineruParser._run_mineru_command(
            input_path=fake_input,
            output_dir=fake_output,
            method="auto",
            backend="vlm-http-client",
            vlm_url="http://remote-gpu:8000",
            source="huggingface",
        )

    assert len(captured_cmds) == 1
    cmd = captured_cmds[0]
    assert "-b" in cmd
    assert cmd[cmd.index("-b") + 1] == "vlm-http-client"
    assert "-u" in cmd
    assert cmd[cmd.index("-u") + 1] == "http://remote-gpu:8000"
    assert "--source" in cmd
    assert cmd[cmd.index("--source") + 1] == "huggingface"
