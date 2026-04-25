"""Session persistence for py-coding-agent."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING, cast
from uuid import uuid4

from .compaction import CompactionSettings, compact_records

type JsonObject = dict[str, object]

if TYPE_CHECKING:
    from pathlib import Path


def timestamp_ms() -> int:
    """Return current UTC timestamp in milliseconds."""
    return int(datetime.now(tz=UTC).timestamp() * 1000)


def _new_id() -> str:
    return uuid4().hex


@dataclass(slots=True)
class SessionRecord:
    """One persisted interaction in a session transcript."""

    id: str
    timestamp_ms: int
    branch: str
    mode: str
    prompt: str
    response: str
    record_type: str = "interaction"

    def to_json(self) -> JsonObject:
        """Return a JSON-serializable representation."""
        return {
            "type": self.record_type,
            "id": self.id,
            "timestamp_ms": self.timestamp_ms,
            "branch": self.branch,
            "mode": self.mode,
            "prompt": self.prompt,
            "response": self.response,
        }

    @classmethod
    def from_json(
        cls,
        payload: JsonObject,
        *,
        fallback_id: str,
    ) -> SessionRecord | None:
        """Build an interaction record from untyped JSON payload."""
        payload_type = payload.get("type", "interaction")
        if payload_type != "interaction":
            return None
        timestamp = payload.get("timestamp_ms")
        branch = payload.get("branch")
        mode = payload.get("mode")
        prompt = payload.get("prompt")
        response = payload.get("response")
        if not (
            isinstance(timestamp, int)
            and isinstance(branch, str)
            and isinstance(mode, str)
            and isinstance(prompt, str)
            and isinstance(response, str)
        ):
            return None
        record_id_value = payload.get("id")
        record_id = record_id_value if isinstance(record_id_value, str) else fallback_id
        return cls(
            id=record_id,
            timestamp_ms=timestamp,
            branch=branch,
            mode=mode,
            prompt=prompt,
            response=response,
        )


@dataclass(slots=True)
class CompactionRecord:
    """One persisted compaction boundary and summary."""

    id: str
    timestamp_ms: int
    branch: str
    summary: str
    first_kept_id: str
    tokens_before: int
    tokens_after: int
    record_type: str = "compaction"

    def to_json(self) -> JsonObject:
        """Return a JSON-serializable representation."""
        return {
            "type": self.record_type,
            "id": self.id,
            "timestamp_ms": self.timestamp_ms,
            "branch": self.branch,
            "summary": self.summary,
            "first_kept_id": self.first_kept_id,
            "tokens_before": self.tokens_before,
            "tokens_after": self.tokens_after,
        }

    @classmethod
    def from_json(
        cls,
        payload: JsonObject,
        *,
        fallback_id: str,
    ) -> CompactionRecord | None:
        """Build a compaction record from untyped JSON payload."""
        payload_type = payload.get("type")
        if payload_type != "compaction":
            return None
        timestamp = payload.get("timestamp_ms")
        branch = payload.get("branch")
        summary = payload.get("summary")
        first_kept_id = payload.get("first_kept_id")
        tokens_before = payload.get("tokens_before")
        tokens_after = payload.get("tokens_after")
        if not (
            isinstance(timestamp, int)
            and isinstance(branch, str)
            and isinstance(summary, str)
            and isinstance(first_kept_id, str)
            and isinstance(tokens_before, int)
            and isinstance(tokens_after, int)
        ):
            return None
        record_id_value = payload.get("id")
        record_id = record_id_value if isinstance(record_id_value, str) else fallback_id
        return cls(
            id=record_id,
            timestamp_ms=timestamp,
            branch=branch,
            summary=summary,
            first_kept_id=first_kept_id,
            tokens_before=tokens_before,
            tokens_after=tokens_after,
        )


type SessionEntry = SessionRecord | CompactionRecord


class SessionStore:
    """Append/load JSONL sessions with branch filtering and compaction support."""

    def __init__(self, *, path: Path, branch: str) -> None:
        self.path = path
        self.branch = branch

    def append_interaction(
        self,
        *,
        mode: str,
        prompt: str,
        response: str,
    ) -> SessionRecord:
        """Append one interaction to the JSONL transcript."""
        record = SessionRecord(
            id=_new_id(),
            timestamp_ms=timestamp_ms(),
            branch=self.branch,
            mode=mode,
            prompt=prompt,
            response=response,
        )
        self._append_json(record.to_json())
        return record

    def append_compaction(
        self,
        *,
        summary: str,
        first_kept_id: str,
        tokens_before: int,
        tokens_after: int,
    ) -> CompactionRecord:
        """Append one compaction summary boundary to the JSONL transcript."""
        record = CompactionRecord(
            id=_new_id(),
            timestamp_ms=timestamp_ms(),
            branch=self.branch,
            summary=summary,
            first_kept_id=first_kept_id,
            tokens_before=tokens_before,
            tokens_after=tokens_after,
        )
        self._append_json(record.to_json())
        return record

    def compact_if_needed(
        self,
        *,
        context_window_tokens: int,
        settings: CompactionSettings,
    ) -> CompactionRecord | None:
        """Run compaction when configured thresholds are crossed."""
        interactions = self.load()
        result = compact_records(
            records=interactions,
            context_window_tokens=context_window_tokens,
            settings=settings,
        )
        if result is None:
            return None
        return self.append_compaction(
            summary=result.summary,
            first_kept_id=result.first_kept_id,
            tokens_before=result.tokens_before,
            tokens_after=result.tokens_after,
        )

    def load(self, *, branch: str | None = None) -> list[SessionRecord]:
        """Load interaction records, applying latest compaction boundary if present."""
        selected_branch = self.branch if branch is None else branch
        entries = self.load_entries(branch=selected_branch)

        latest_compaction: CompactionRecord | None = None
        interactions: list[SessionRecord] = []
        for entry in entries:
            if isinstance(entry, SessionRecord):
                interactions.append(entry)
            else:
                latest_compaction = entry

        if latest_compaction is None:
            return interactions

        first_kept_id = latest_compaction.first_kept_id
        for index, record in enumerate(interactions):
            if record.id == first_kept_id:
                return interactions[index:]
        return interactions

    def load_entries(self, *, branch: str | None = None) -> list[SessionEntry]:
        """Load all entries (interactions and compactions) for a branch."""
        selected_branch = self.branch if branch is None else branch
        return [
            entry
            for entry in self._load_all_entries()
            if entry.branch == selected_branch
        ]

    def branches(self) -> set[str]:
        """Return all known branch names in this session file."""
        return {entry.branch for entry in self._load_all_entries()}

    def _append_json(self, payload: JsonObject) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload) + "\n")

    def _load_all_entries(self) -> list[SessionEntry]:
        if not self.path.exists():
            return []

        loaded: list[SessionEntry] = []
        with self.path.open("r", encoding="utf-8") as handle:
            for line_number, line in enumerate(handle, start=1):
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

                fallback_id = f"legacy-{line_number}"
                compaction = CompactionRecord.from_json(
                    payload,
                    fallback_id=fallback_id,
                )
                if compaction is not None:
                    loaded.append(compaction)
                    continue

                interaction = SessionRecord.from_json(payload, fallback_id=fallback_id)
                if interaction is not None:
                    loaded.append(interaction)

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
