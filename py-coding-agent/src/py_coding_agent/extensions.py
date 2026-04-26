"""Extension hooks and event dispatch for py-coding-agent."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .compaction import CompactionSettings

type EventType = str


@dataclass(slots=True)
class AppEvent:
    """Event emitted by the coding-agent runtime."""

    type: EventType
    timestamp_ms: int
    mode: str | None = None
    prompt: str | None = None
    response: str | None = None
    branch: str | None = None
    session_file: str | None = None
    summary: str | None = None
    first_kept_id: str | None = None
    tokens_before: int | None = None
    tokens_after: int | None = None


type EventListener = Callable[[AppEvent], None]
type SessionBeforeCompactHook = Callable[
    ["SessionBeforeCompactContext"],
    "SessionBeforeCompactDecision | None",
]


@dataclass(slots=True, frozen=True)
class SessionBeforeCompactContext:
    """Proposed compaction payload passed to extension hooks."""

    branch: str
    session_file: str | None
    context_window_tokens: int
    settings: CompactionSettings
    interactions_count: int
    proposed_summary: str
    proposed_first_kept_id: str
    proposed_tokens_before: int
    proposed_tokens_after: int


@dataclass(slots=True, frozen=True)
class SessionBeforeCompactDecision:
    """Optional hook decision to cancel or override compaction."""

    cancel: bool = False
    summary: str | None = None
    first_kept_id: str | None = None
    tokens_before: int | None = None
    tokens_after: int | None = None


class EventBus:
    """Simple in-process pub/sub bus for app events."""

    def __init__(self) -> None:
        self._listeners: list[EventListener] = []
        self._before_compact_hooks: list[SessionBeforeCompactHook] = []

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

    def subscribe_session_before_compact(
        self,
        hook: SessionBeforeCompactHook,
    ) -> Callable[[], None]:
        """Register a `session_before_compact` hook."""
        self._before_compact_hooks.append(hook)

        def unsubscribe() -> None:
            if hook in self._before_compact_hooks:
                self._before_compact_hooks.remove(hook)

        return unsubscribe

    def run_session_before_compact(
        self,
        context: SessionBeforeCompactContext,
    ) -> SessionBeforeCompactDecision | None:
        """Run compaction hooks and return latest override or cancellation."""
        last_override: SessionBeforeCompactDecision | None = None
        for hook in [*self._before_compact_hooks]:
            decision = hook(context)
            if decision is None:
                continue
            if decision.cancel:
                return decision
            last_override = decision
        return last_override
