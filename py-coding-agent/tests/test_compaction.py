"""Unit tests for compaction utilities."""

from __future__ import annotations

import unittest

from src.compaction import (
    CompactionSettings,
    compact_records,
    estimate_context_tokens,
    should_compact,
)
from src.session import SessionRecord

CONTEXT_WINDOW = 1_000
RESERVE_TOKENS = 100
KEEP_RECENT_TOKENS = 50


class CompactionTests(unittest.TestCase):
    """Tests compaction trigger and cut behavior."""

    def _make_records(self) -> list[SessionRecord]:
        return [
            SessionRecord(
                id=f"id-{index}",
                timestamp_ms=index,
                branch="main",
                mode="print",
                prompt=f"Prompt {index} " + ("x" * 100),
                response=f"Response {index} " + ("y" * 60),
            )
            for index in range(6)
        ]

    def test_should_compact_threshold(self) -> None:
        settings = CompactionSettings(
            enabled=True,
            reserve_tokens=RESERVE_TOKENS,
            keep_recent_tokens=KEEP_RECENT_TOKENS,
        )
        assert should_compact(
            context_tokens=CONTEXT_WINDOW,
            context_window_tokens=CONTEXT_WINDOW,
            settings=settings,
        )
        assert not should_compact(
            context_tokens=CONTEXT_WINDOW - RESERVE_TOKENS - 1,
            context_window_tokens=CONTEXT_WINDOW,
            settings=settings,
        )

    def test_compact_records_returns_result_when_over_threshold(self) -> None:
        records = self._make_records()
        result = compact_records(
            records=records,
            context_window_tokens=300,
            settings=CompactionSettings(
                enabled=True,
                reserve_tokens=50,
                keep_recent_tokens=KEEP_RECENT_TOKENS,
            ),
        )
        assert result is not None
        assert result.first_kept_id.startswith("id-")
        assert result.tokens_before > 0
        assert result.tokens_after > 0
        assert "## Goal" in result.summary

    def test_compact_records_returns_none_when_not_needed(self) -> None:
        records = self._make_records()
        context_tokens = estimate_context_tokens(records)
        result = compact_records(
            records=records,
            context_window_tokens=context_tokens + 1000,
            settings=CompactionSettings(
                enabled=True,
                reserve_tokens=RESERVE_TOKENS,
                keep_recent_tokens=KEEP_RECENT_TOKENS,
            ),
        )
        assert result is None


if __name__ == "__main__":
    unittest.main()
