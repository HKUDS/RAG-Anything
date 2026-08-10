#!/usr/bin/env python3
"""Fail closed when a reviewed CI security exception is malformed or expired."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path


REQUIRED_FIELDS = {"id", "issue", "reason", "expires_on"}


def main() -> int:
    path = Path(__file__).resolve().parents[1] / ".github" / "security" / "ci-exceptions.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    exceptions = payload.get("exceptions")
    if not isinstance(exceptions, list):
        raise ValueError("security exception policy must contain an exceptions list")
    today = date.today()
    seen: set[str] = set()
    for entry in exceptions:
        if not isinstance(entry, dict) or not REQUIRED_FIELDS.issubset(entry):
            raise ValueError("each security exception requires id, issue, reason, and expires_on")
        exception_id = str(entry["id"])
        if exception_id in seen:
            raise ValueError(f"duplicate security exception id: {exception_id}")
        seen.add(exception_id)
        if date.fromisoformat(str(entry["expires_on"])) < today:
            raise ValueError(f"security exception expired: {exception_id}")
    print(f"security exception policy valid; active={len(exceptions)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
