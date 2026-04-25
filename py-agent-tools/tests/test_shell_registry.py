"""Unit tests for shell command registry primitives."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from py_agent_tools import (
    ShellCancellationToken,
    ShellCommandContext,
    ShellCommandRegistry,
    ShellCommandResult,
    ShellRegistryError,
)


def _echo_handler(
    *,
    context: ShellCommandContext,
    arguments: tuple[str, ...],
    cancellation: ShellCancellationToken,
    event_sink: object,
) -> ShellCommandResult:
    _ = context
    _ = event_sink
    cancellation.ensure_active()
    return ShellCommandResult(stdout=" ".join(arguments))


class ShellRegistryTests(unittest.TestCase):
    """Tests for registry registration and lookup behavior."""

    def test_register_and_resolve_handler(self) -> None:
        registry = ShellCommandRegistry()
        registry.register("echo", _echo_handler)
        handler = registry.resolve("echo")
        result = handler(
            context=ShellCommandContext(cwd=Path.cwd()),
            arguments=("hello", "world"),
            cancellation=ShellCancellationToken.create(),
            event_sink=None,
        )
        assert result.stdout == "hello world"

    def test_register_duplicate_requires_replace(self) -> None:
        registry = ShellCommandRegistry()
        registry.register("echo", _echo_handler)
        failed = False
        try:
            registry.register("echo", _echo_handler)
        except ShellRegistryError:
            failed = True
        assert failed is True

    def test_resolve_unknown_raises(self) -> None:
        registry = ShellCommandRegistry()
        failed = False
        try:
            registry.resolve("missing")
        except ShellRegistryError:
            failed = True
        assert failed is True

    def test_list_commands_sorted(self) -> None:
        registry = ShellCommandRegistry()
        registry.register("zeta", _echo_handler)
        registry.register("alpha", _echo_handler)
        assert registry.list_commands() == ("alpha", "zeta")


if __name__ == "__main__":
    unittest.main()

