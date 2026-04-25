"""Unit tests for JSONL session persistence."""

from __future__ import annotations

import json
import shutil
import unittest
from pathlib import Path

from src import session
from src.compaction import CompactionSettings
from src.session import CompactionRecord, SessionRecord, SessionStore

TMP_DIR = Path(__file__).resolve().parent / ".tmp"
TOTAL_INTERACTIONS = 10


class SessionTests(unittest.TestCase):
    """Tests for SessionStore append/load behavior."""

    def test_session_record_to_from_json(self) -> None:
        record = SessionRecord(
            id="id-1",
            timestamp_ms=1,
            branch="main",
            mode="print",
            prompt="hello",
            response="Echo: hello",
        )
        payload = record.to_json()
        parsed = SessionRecord.from_json(payload, fallback_id="fallback")
        assert parsed == record

    def test_session_record_from_json_invalid_payload(self) -> None:
        assert (
            SessionRecord.from_json({"timestamp_ms": "bad"}, fallback_id="x")
            is None
        )
        assert (
            SessionRecord.from_json({"timestamp_ms": 1, "branch": 1}, fallback_id="x")
            is None
        )

    def test_compaction_record_to_from_json(self) -> None:
        record = CompactionRecord(
            id="cmp-1",
            timestamp_ms=2,
            branch="main",
            summary="summary",
            first_kept_id="id-9",
            tokens_before=100,
            tokens_after=40,
        )
        payload = record.to_json()
        parsed = CompactionRecord.from_json(payload, fallback_id="fallback")
        assert parsed == record

    def test_append_and_load_with_branch_filter(self) -> None:
        test_dir = TMP_DIR / "session-branch"
        shutil.rmtree(test_dir, ignore_errors=True)
        test_dir.mkdir(parents=True, exist_ok=True)
        try:
            path = test_dir / "logs" / "session.jsonl"
            now_values = iter([10, 20, 30])
            original_timestamp = session.timestamp_ms
            try:
                session.timestamp_ms = lambda: next(now_values)
                main_store = SessionStore(path=path, branch="main")
                feature_store = SessionStore(path=path, branch="feature")
                main_store.append_interaction(
                    mode="print",
                    prompt="main-1",
                    response="Echo: main-1",
                )
                feature_store.append_interaction(
                    mode="json",
                    prompt="feature-1",
                    response="Echo: feature-1",
                )
                main_store.append_interaction(
                    mode="rpc",
                    prompt="main-2",
                    response="Echo: main-2",
                )
            finally:
                session.timestamp_ms = original_timestamp

            loaded_main = main_store.load()
            loaded_feature = main_store.load(branch="feature")
            assert [item.prompt for item in loaded_main] == ["main-1", "main-2"]
            assert [item.prompt for item in loaded_feature] == ["feature-1"]

            branches = main_store.branches()
            assert branches == {"main", "feature"}
        finally:
            shutil.rmtree(test_dir, ignore_errors=True)

    def test_load_ignores_invalid_lines_and_missing_file(self) -> None:
        test_dir = TMP_DIR / "session-invalid"
        shutil.rmtree(test_dir, ignore_errors=True)
        test_dir.mkdir(parents=True, exist_ok=True)
        try:
            path = test_dir / "session.jsonl"
            store = SessionStore(path=path, branch="main")
            assert store.load() == []

            payload = {
                "timestamp_ms": 1,
                "branch": "main",
                "mode": "print",
                "prompt": "hello",
                "response": "Echo: hello",
            }
            content = "\n".join(
                [
                    "",
                    "not json",
                    json.dumps(["array"]),
                    json.dumps({"timestamp_ms": "bad"}),
                    json.dumps(payload),
                    "",
                ]
            )
            path.write_text(content, encoding="utf-8")
            loaded = store.load()
            assert len(loaded) == 1
            assert loaded[0].prompt == "hello"
        finally:
            shutil.rmtree(test_dir, ignore_errors=True)

    def test_compact_if_needed_appends_compaction_and_applies_boundary(self) -> None:
        test_dir = TMP_DIR / "session-compaction"
        shutil.rmtree(test_dir, ignore_errors=True)
        test_dir.mkdir(parents=True, exist_ok=True)
        try:
            path = test_dir / "session.jsonl"
            store = SessionStore(path=path, branch="main")
            for number in range(TOTAL_INTERACTIONS):
                prompt = f"task-{number} " + ("x" * 120)
                store.append_interaction(mode="print", prompt=prompt, response="ok")

            compaction = store.compact_if_needed(
                context_window_tokens=200,
                settings=CompactionSettings(
                    enabled=True,
                    reserve_tokens=40,
                    keep_recent_tokens=40,
                ),
            )
            assert compaction is not None

            entries = store.load_entries()
            assert any(isinstance(entry, CompactionRecord) for entry in entries)

            loaded = store.load()
            assert len(loaded) < TOTAL_INTERACTIONS
            assert loaded[0].id == compaction.first_kept_id
        finally:
            shutil.rmtree(test_dir, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
