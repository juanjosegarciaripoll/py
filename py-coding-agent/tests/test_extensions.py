"""Unit tests for event extension primitives."""

from __future__ import annotations

import unittest

from src.compaction import CompactionSettings
from src.extensions import (
    AppEvent,
    EventBus,
    SessionBeforeCompactContext,
    SessionBeforeCompactDecision,
)


class ExtensionTests(unittest.TestCase):
    """Tests event listener behavior and unsubscribe semantics."""

    def test_event_bus_emit_and_unsubscribe(self) -> None:
        bus = EventBus()
        calls: list[str] = []

        def first(event: AppEvent) -> None:
            calls.append(f"first:{event.mode}")

        def second(event: AppEvent) -> None:
            calls.append(f"second:{event.mode}")

        unsub_first = bus.subscribe(first)
        bus.subscribe(second)

        event = AppEvent(
            type="interaction_complete",
            mode="print",
            prompt="hello",
            response="Echo: hello",
            branch="main",
            session_file=None,
            timestamp_ms=1,
        )
        bus.emit(event)
        unsub_first()
        bus.emit(event)

        assert calls == [
            "first:print",
            "second:print",
            "second:print",
        ]

    def test_before_compact_hooks_support_override_and_cancel(self) -> None:
        bus = EventBus()
        calls: list[str] = []
        context = SessionBeforeCompactContext(
            branch="main",
            session_file="session.jsonl",
            context_window_tokens=1000,
            settings=CompactionSettings(),
            interactions_count=7,
            proposed_summary="generated",
            proposed_first_kept_id="abc123",
            proposed_tokens_before=900,
            proposed_tokens_after=400,
        )

        def override(
            _context: SessionBeforeCompactContext,
        ) -> SessionBeforeCompactDecision:
            calls.append("override")
            return SessionBeforeCompactDecision(summary="custom-summary")

        def cancel(
            _context: SessionBeforeCompactContext,
        ) -> SessionBeforeCompactDecision:
            calls.append("cancel")
            return SessionBeforeCompactDecision(cancel=True)

        bus.subscribe_session_before_compact(override)
        unsubscribe_cancel = bus.subscribe_session_before_compact(cancel)

        canceled = bus.run_session_before_compact(context)
        assert canceled is not None
        assert canceled.cancel is True
        assert calls == ["override", "cancel"]

        calls.clear()
        unsubscribe_cancel()
        overridden = bus.run_session_before_compact(context)
        assert overridden is not None
        assert overridden.cancel is False
        assert overridden.summary == "custom-summary"
        assert calls == ["override"]


if __name__ == "__main__":
    unittest.main()
