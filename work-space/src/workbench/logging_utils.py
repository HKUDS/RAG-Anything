from __future__ import annotations

import atexit
import logging
import re
import sys
from datetime import datetime
from pathlib import Path


class _TeeStream:
    def __init__(self, original, mirror):
        self._original = original
        self._mirror = mirror

    def write(self, data):
        self._original.write(data)
        self._mirror.write(data)
        return len(data)

    def flush(self):
        self._original.flush()
        self._mirror.flush()

    def isatty(self):
        return getattr(self._original, "isatty", lambda: False)()

    @property
    def encoding(self):
        return getattr(self._original, "encoding", "utf-8")

    def fileno(self):
        return self._original.fileno()

    def __getattr__(self, item):
        return getattr(self._original, item)


_ORIGINAL_STDOUT = sys.stdout
_ORIGINAL_STDERR = sys.stderr
_TEE_FILE = None


def _close_tee_file():
    global _TEE_FILE
    if _TEE_FILE is not None and not _TEE_FILE.closed:
        _TEE_FILE.flush()
        _TEE_FILE.close()
    _TEE_FILE = None


def _sanitize_label(value: str | None) -> str:
    if not value:
        return "all"
    text = re.sub(r"[^A-Za-z0-9_.-]+", "_", str(value)).strip("._")
    return text or "all"


def configure_workbench_logging(command_name: str, run_label: str | None = None) -> Path:
    global _TEE_FILE

    logs_dir = Path("benchmark_outputs") / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    safe_label = _sanitize_label(run_label)
    log_path = logs_dir / f"{command_name}__{safe_label}__{timestamp}.log"

    _close_tee_file()
    _TEE_FILE = log_path.open("a", encoding="utf-8", buffering=1)
    sys.stdout = _TeeStream(_ORIGINAL_STDOUT, _TEE_FILE)
    sys.stderr = _TeeStream(_ORIGINAL_STDERR, _TEE_FILE)

    formatter = logging.Formatter("%(asctime)s | %(levelname)s | %(message)s")
    root = logging.getLogger()
    root.handlers.clear()
    root.setLevel(logging.INFO)

    console_handler = logging.StreamHandler(stream=sys.stderr)
    console_handler.setFormatter(formatter)

    root.addHandler(console_handler)
    root.propagate = False

    logging.getLogger(__name__).info("Logging to %s", log_path)
    return log_path


atexit.register(_close_tee_file)
