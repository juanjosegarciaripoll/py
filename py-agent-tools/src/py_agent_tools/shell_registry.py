"""Extensible command-handler registry for shell-subset execution."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from pathlib import Path

    from .shell_runtime import ShellCancellationToken, ShellEventSink


class ShellRegistryError(LookupError):
    """Base error for shell command registry operations."""

    @classmethod
    def already_registered(cls, name: str) -> ShellRegistryError:
        """Create already-registered error."""
        message = f"Shell command already registered: {name}"
        return cls(message)

    @classmethod
    def not_registered(cls, name: str) -> ShellRegistryError:
        """Create not-registered error."""
        message = f"Shell command is not registered: {name}"
        return cls(message)


@dataclass(slots=True, frozen=True)
class ShellCommandContext:
    """Execution context passed to one command handler."""

    cwd: Path
    stdin: str = ""


@dataclass(slots=True, frozen=True)
class ShellCommandResult:
    """Result payload returned by one command handler."""

    stdout: str = ""
    stderr: str = ""
    exit_code: int = 0
    next_cwd: Path | None = None


class ShellCommandHandler(Protocol):
    """Protocol implemented by shell command handlers."""

    def __call__(
        self,
        *,
        context: ShellCommandContext,
        arguments: tuple[str, ...],
        cancellation: ShellCancellationToken,
        event_sink: ShellEventSink | None,
    ) -> ShellCommandResult:
        """Execute one command and return structured result."""
        ...


def _handler_map() -> dict[str, ShellCommandHandler]:
    """Create a typed handler map for dataclass defaults."""
    return {}


@dataclass(slots=True)
class ShellCommandRegistry:
    """Name-to-handler registry for shell command execution."""

    _handlers: dict[str, ShellCommandHandler] = field(default_factory=_handler_map)

    def register(
        self,
        name: str,
        handler: ShellCommandHandler,
        *,
        replace: bool = False,
    ) -> None:
        """Register one command handler."""
        if not replace and name in self._handlers:
            raise ShellRegistryError.already_registered(name)
        self._handlers[name] = handler

    def resolve(self, name: str) -> ShellCommandHandler:
        """Resolve handler for command name."""
        if name not in self._handlers:
            raise ShellRegistryError.not_registered(name)
        return self._handlers[name]

    def list_commands(self) -> tuple[str, ...]:
        """List registered command names in sorted order."""
        return tuple(sorted(self._handlers))
