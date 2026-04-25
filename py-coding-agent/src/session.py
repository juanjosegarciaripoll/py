"""Session persistence for py-coding-agent."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING, cast

if TYPE_CHECKING:
    from pathlib import Path

type JsonObject = dict[str, object]


def timestamp_ms() -> int:
    """Return current UTC timestamp in milliseconds."""
    return int(datetime.now(tz=UTC).timestamp() * 1000)


@dataclass(slots=True)
class SessionRecord:
    """One persisted interaction in a session transcript."""

    timestamp_ms: int
    branch: str
    mode: str
    prompt: str
    response: str

    def to_json(self) -> JsonObject:
        """Return a JSON-serializable representation."""
        return {
            "timestamp_ms": self.timestamp_ms,
            "branch": self.branch,
            "mode": self.mode,
            "prompt": self.prompt,
            "response": self.response,
        }

    @classmethod
    def from_json(cls, payload: JsonObject) -> SessionRecord | None:
        """Build a record from untyped JSON payload."""
        timestamp = payload.get("timestamp_ms")
        branch = payload.get("branch")
        mode = payload.get("mode")
        prompt = payload.get("prompt")
        response = payload.get("response")
        if not isinstance(timestamp, int):
            return None
        if not isinstance(branch, str):
            return None
        if not isinstance(mode, str):
            return None
        if not isinstance(prompt, str):
            return None
        if not isinstance(response, str):
            return None
        return cls(
            timestamp_ms=timestamp,
            branch=branch,
            mode=mode,
            prompt=prompt,
            response=response,
        )


class SessionStore:
    """Append/load JSONL sessions with branch filtering."""

    def __init__(self, *, path: Path, branch: str) -> None:
        self.path = path
        self.branch = branch

    def append_interaction(self, *, mode: str, prompt: str, response: str) -> None:
        """Append one interaction to the JSONL transcript."""
        record = SessionRecord(
            timestamp_ms=timestamp_ms(),
            branch=self.branch,
            mode=mode,
            prompt=prompt,
            response=response,
        )
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record.to_json()) + "\n")

    def load(self, *, branch: str | None = None) -> list[SessionRecord]:
        """Load session records, optionally filtered by branch."""
        all_records = self._load_all_records()
        selected_branch = self.branch if branch is None else branch
        return [
            record for record in all_records if record.branch == selected_branch
        ]

    def branches(self) -> set[str]:
        """Return all known branch names in this session file."""
        return {record.branch for record in self._load_all_records()}

    def _load_all_records(self) -> list[SessionRecord]:
        if not self.path.exists():
            return []
        loaded: list[SessionRecord] = []
        with self.path.open("r", encoding="utf-8") as handle:
            for line in handle:
                text = line.strip()
                if not text:
                    continue
                try:
                    raw_payload: object = json.loads(text)
                except json.JSONDecodeError:
                    continue
                payload = self._as_json_object(raw_payload)
                if payload is None:
                    continue
                record = SessionRecord.from_json(payload)
                if record is None:
                    continue
                loaded.append(record)
        return loaded

    def _as_json_object(self, value: object) -> JsonObject | None:
        if not isinstance(value, dict):
            return None
        raw = cast("dict[object, object]", value)
        result: JsonObject = {}
        for key, item in raw.items():
            if not isinstance(key, str):
                return None
            result[key] = item
        return result
