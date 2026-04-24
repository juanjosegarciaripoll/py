"""Unit tests for optional provider selection TUI."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.tui import select_provider


class SelectProviderTests(unittest.TestCase):
    """Tests for provider selection prompt logic."""

    def test_single_provider_returns_without_prompt(self) -> None:
        selected = select_provider(["openai"])
        assert selected == "openai"

    def test_invalid_then_valid_input(self) -> None:
        inputs = iter(["abc", "4", "2"])
        printed: list[str] = []

        def _input(_: str) -> str:
            return next(inputs)

        def _print(message: str) -> None:
            printed.append(message)

        selected = select_provider(
            ["openai", "anthropic", "openai-compatible"],
            input_fn=_input,
            output_fn=_print,
        )
        assert selected == "anthropic"
        assert any("Invalid choice" in message for message in printed)
        assert any("Choice out of range" in message for message in printed)

    def test_empty_provider_list_raises(self) -> None:
        try:
            select_provider([])
        except ValueError:
            pass
        else:
            msg = "Expected ValueError when provider list is empty"
            raise AssertionError(msg)


if __name__ == "__main__":
    unittest.main()
