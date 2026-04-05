from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Tuple


@dataclass
class ProcessedFileManifest:
    path: Path

    def load(self) -> Dict[str, Any]:
        if not self.path.exists():
            return {"files": {}}
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict) and isinstance(data.get("files"), dict):
                return data
        except Exception:
            pass
        return {"files": {}}

    def save(self, data: Dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    @staticmethod
    def fingerprint(file_path: Path) -> Dict[str, Any]:
        hasher = hashlib.md5()
        with open(file_path, "rb") as f:
            for chunk in iter(lambda: f.read(1024 * 1024), b""):
                hasher.update(chunk)
        stat = file_path.stat()
        return {
            "content_md5": hasher.hexdigest(),
            "size": stat.st_size,
            "mtime": int(stat.st_mtime),
        }

    def classify(self, file_path: Path) -> Tuple[str, Dict[str, Any]]:
        manifest = self.load()
        fingerprint = self.fingerprint(file_path)
        record = manifest.get("files", {}).get(file_path.name)
        if not record:
            return "new", fingerprint
        previous_md5 = record.get("content_md5")
        previous_status = record.get("status")
        if previous_md5 == fingerprint["content_md5"] and previous_status == "Success":
            return "skip_unchanged", fingerprint
        if previous_md5 and previous_md5 != fingerprint["content_md5"]:
            return "skip_changed", fingerprint
        return "retry", fingerprint
