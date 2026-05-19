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

    def remove_where(self, **criteria: object) -> int:
        if not self.path.exists():
            return 0

        with open(self.path, "r", newline="", encoding="utf-8") as f:
            rows = list(csv.DictReader(f))

        def matches(row: Mapping[str, object]) -> bool:
            return all(str(row.get(key, "")) == str(value) for key, value in criteria.items())

        kept = [row for row in rows if not matches(row)]
        removed = len(rows) - len(kept)
        if removed == 0:
            return 0

        with open(self.path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=self.header)
            writer.writeheader()
            writer.writerows(kept)
        return removed


class JSONLReportWriter:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def append(self, record: Mapping[str, object]) -> None:
        with open(self.path, "a", encoding="utf-8") as f:
            f.write(json.dumps(dict(record), ensure_ascii=False) + "\n")
