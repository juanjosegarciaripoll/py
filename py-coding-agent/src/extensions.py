"""Extension hooks and event dispatch for py-coding-agent."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

type EventType = str


@dataclass(slots=True)
class AppEvent:
    """Event emitted by the coding-agent runtime."""

    type: EventType
    mode: str
    prompt: str
    response: str
    branch: str
    session_file: str | None
    timestamp_ms: int


type EventListener = Callable[[AppEvent], None]


class EventBus:
    """Simple in-process pub/sub bus for app events."""

    def __init__(self) -> None:
        self._listeners: list[EventListener] = []

    def subscribe(self, listener: EventListener) -> Callable[[], None]:
        """Register a listener and return an unsubscribe function."""
        self._listeners.append(listener)

        def unsubscribe() -> None:
            if listener in self._listeners:
                self._listeners.remove(listener)

        return unsubscribe

    def emit(self, event: AppEvent) -> None:
        """Emit an event to all listeners in registration order."""
        for listener in [*self._listeners]:
            listener(event)
