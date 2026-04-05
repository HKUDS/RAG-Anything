from __future__ import annotations

import sys
from pathlib import Path


def bootstrap_project_root() -> Path:
    current_dir = Path(__file__).resolve().parent
    project_root = current_dir.parent
    if str(project_root) not in sys.path:
        sys.path.insert(0, str(project_root))
    return project_root
