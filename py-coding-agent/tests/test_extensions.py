"""Unit tests for event extension primitives."""

from __future__ import annotations

import unittest

from src.extensions import AppEvent, EventBus


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


if __name__ == "__main__":
    unittest.main()
