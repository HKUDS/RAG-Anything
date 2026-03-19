"""Workspace-backed session manager for rag_agent."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any


@dataclass
class Session:
    """A single conversation session."""

    key: str
    messages: list[dict[str, Any]] = field(default_factory=list)
    created_at: datetime = field(default_factory=datetime.now)
    updated_at: datetime = field(default_factory=datetime.now)
    metadata: dict[str, Any] = field(default_factory=dict)

    def get_history(self, max_messages: int = 200) -> list[dict[str, Any]]:
        """Return a compact history list suitable for LLM input."""
        sliced = self.messages[-max_messages:] if max_messages > 0 else list(self.messages)

        # Align to user turn: avoid leading orphan tool/assistant messages.
        for i, msg in enumerate(sliced):
            if msg.get("role") == "user":
                sliced = sliced[i:]
                break

        out: list[dict[str, Any]] = []
        for msg in sliced:
            entry: dict[str, Any] = {
                "role": msg.get("role", "assistant"),
                "content": msg.get("content", ""),
            }
            for key in ("tool_calls", "tool_call_id", "name"):
                if key in msg:
                    entry[key] = msg[key]
            out.append(entry)
        return out

    def clear(self) -> None:
        """Reset session messages."""
        self.messages = []
        self.updated_at = datetime.now()


class SessionManager:
    """Workspace-backed JSONL session manager for MVP."""

    def __init__(self, workspace: str | Path) -> None:
        self.workspace = Path(workspace).expanduser().resolve()
        self.sessions_dir = self.workspace / "sessions"
        self.sessions_dir.mkdir(parents=True, exist_ok=True)
        self._cache: dict[str, Session] = {}

    def _get_session_path(self, key: str) -> Path:
        """Get the JSONL file path for one session."""
        safe_key = "".join(char if char.isalnum() or char in ("-", "_", ".") else "_" for char in key)
        return self.sessions_dir / f"{safe_key}.jsonl"

    def get_or_create(self, key: str) -> Session:
        """Get existing session or create a new one."""
        if key not in self._cache:
            self._cache[key] = self._load(key) or Session(key=key)
        return self._cache[key]

    def _load(self, key: str) -> Session | None:
        """Load one session from disk if it exists."""
        path = self._get_session_path(key)
        if not path.exists():
            return None

        try:
            messages: list[dict[str, Any]] = []
            metadata: dict[str, Any] = {}
            created_at: datetime | None = None
            updated_at: datetime | None = None

            with path.open("r", encoding="utf-8") as handle:
                for line in handle:
                    line = line.strip()
                    if not line:
                        continue
                    data = json.loads(line)
                    if data.get("_type") == "metadata":
                        metadata = data.get("metadata", {})
                        created_at = self._parse_datetime(data.get("created_at"))
                        updated_at = self._parse_datetime(data.get("updated_at"))
                        continue
                    messages.append(data)

            return Session(
                key=key,
                messages=messages,
                created_at=created_at or datetime.now(),
                updated_at=updated_at or datetime.now(),
                metadata=metadata,
            )
        except Exception:
            return None

    def save(self, session: Session) -> None:
        """Persist one session to workspace sessions directory."""
        path = self._get_session_path(session.key)
        with path.open("w", encoding="utf-8") as handle:
            metadata_line = {
                "_type": "metadata",
                "key": session.key,
                "created_at": session.created_at.isoformat(),
                "updated_at": session.updated_at.isoformat(),
                "metadata": session.metadata,
            }
            handle.write(json.dumps(metadata_line, ensure_ascii=False) + "\n")
            for message in session.messages:
                handle.write(json.dumps(message, ensure_ascii=False) + "\n")

        self._cache[session.key] = session

    def invalidate(self, key: str) -> None:
        """Remove one session from cache."""
        self._cache.pop(key, None)

    def list_keys(self) -> list[str]:
        """Return all known session keys from cache and disk."""
        keys = set(self._cache.keys())
        for path in self.sessions_dir.glob("*.jsonl"):
            try:
                with path.open("r", encoding="utf-8") as handle:
                    first_line = handle.readline().strip()
                if not first_line:
                    continue
                data = json.loads(first_line)
                key = data.get("key")
                if isinstance(key, str) and key:
                    keys.add(key)
            except Exception:
                continue
        return sorted(keys)

    @staticmethod
    def _parse_datetime(value: Any) -> datetime | None:
        """Parse ISO datetime safely."""
        if not isinstance(value, str) or not value:
            return None
        try:
            return datetime.fromisoformat(value)
        except ValueError:
            return None
