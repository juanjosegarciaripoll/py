"""Unit tests for shell runtime event and cancellation primitives."""

from __future__ import annotations

import sys
import unittest
from dataclasses import dataclass, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from py_agent_tools import (
    ShellCancellationToken,
    ShellExecutionCancelledError,
    ShellExecutionEvent,
    emit_shell_event,
)


@dataclass(slots=True)
class _CollectingSink:
    events: list[ShellExecutionEvent] = field(default_factory=list)

    def on_event(self, event: ShellExecutionEvent) -> None:
        self.events.append(event)


class ShellRuntimeTests(unittest.TestCase):
    """Tests for cancellation and event emission primitives."""

    def test_cancellation_token_defaults_to_active(self) -> None:
        token = ShellCancellationToken.create()
        assert token.is_cancelled() is False
        token.ensure_active()

    def test_cancellation_token_raises_when_cancelled(self) -> None:
        token = ShellCancellationToken.create()
        token.cancel()
        failed = False
        try:
            token.ensure_active()
        except ShellExecutionCancelledError:
            failed = True
        assert failed is True

    def test_emit_shell_event_noop_without_sink(self) -> None:
        event = ShellExecutionEvent(
            kind="stdout",
            pipeline_index=0,
            command_index=0,
            text="hello",
        )
        emit_shell_event(None, event)

    def test_emit_shell_event_calls_sink(self) -> None:
        sink = _CollectingSink()
        event = ShellExecutionEvent(
            kind="command_start",
            pipeline_index=1,
            command_index=2,
            text="echo hi",
        )
        emit_shell_event(sink, event)
        assert sink.events == [event]


if __name__ == "__main__":
    unittest.main()

