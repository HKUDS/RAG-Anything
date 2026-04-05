from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Iterable, Mapping


class CSVReportWriter:
    def __init__(self, path: Path, header: Iterable[str]):
        self.path = Path(path)
        self.header = list(header)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if not self.path.exists():
            with open(self.path, "w", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(f, fieldnames=self.header)
                writer.writeheader()

    def append(self, row: Mapping[str, object]) -> None:
        with open(self.path, "a", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=self.header)
            writer.writerow(dict(row))


class JSONLReportWriter:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def append(self, record: Mapping[str, object]) -> None:
        with open(self.path, "a", encoding="utf-8") as f:
            f.write(json.dumps(dict(record), ensure_ascii=False) + "\n")
