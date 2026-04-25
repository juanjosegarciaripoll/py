"""Runtime event and cancellation primitives for shell-subset execution."""

from __future__ import annotations

from dataclasses import dataclass
from threading import Event
from typing import Literal, Protocol

type ShellExecutionEventKind = Literal[
    "command_start",
    "stdout",
    "stderr",
    "command_end",
    "cancelled",
    "error",
]


class ShellExecutionError(RuntimeError):
    """Base runtime error for shell-subset execution."""


class ShellExecutionCancelledError(ShellExecutionError):
    """Raised when shell execution is cancelled."""

    @classmethod
    def cancelled(cls) -> ShellExecutionCancelledError:
        """Create cancellation error."""
        message = "Shell execution cancelled."
        return cls(message)


@dataclass(slots=True, frozen=True)
class ShellExecutionEvent:
    """Structured shell execution event."""

    kind: ShellExecutionEventKind
    pipeline_index: int
    command_index: int
    text: str = ""
    exit_code: int | None = None


class ShellEventSink(Protocol):
    """Protocol for receiving shell execution events."""

    def on_event(self, event: ShellExecutionEvent) -> None:
        """Handle one emitted event."""


@dataclass(slots=True)
class ShellCancellationToken:
    """Cooperative cancellation token for shell execution stages."""

    _event: Event

    @classmethod
    def create(cls) -> ShellCancellationToken:
        """Create a fresh uncancelled token."""
        return cls(_event=Event())

    def cancel(self) -> None:
        """Mark execution as cancelled."""
        self._event.set()

    def is_cancelled(self) -> bool:
        """Whether cancellation has been requested."""
        return self._event.is_set()

    def ensure_active(self) -> None:
        """Raise if cancellation has already been requested."""
        if self.is_cancelled():
            raise ShellExecutionCancelledError.cancelled()


def emit_shell_event(
    sink: ShellEventSink | None,
    event: ShellExecutionEvent,
) -> None:
    """Emit event to sink when provided."""
    if sink is None:
        return
    sink.on_event(event)

