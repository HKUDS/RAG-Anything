from __future__ import annotations

import importlib.util
from pathlib import Path


def _load_example_module():
    module_path = (
        Path(__file__).resolve().parents[1] / "examples" / "raganything_example.py"
    )
    spec = importlib.util.spec_from_file_location("raganything_example", module_path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_configure_logging_creates_log_dir(monkeypatch, tmp_path):
    module = _load_example_module()
    log_dir = tmp_path / "nested" / "logs"

    monkeypatch.setenv("LOG_DIR", str(log_dir))
    module.configure_logging()

    assert log_dir.is_dir()
    assert (log_dir / "raganything_example.log").parent == log_dir
