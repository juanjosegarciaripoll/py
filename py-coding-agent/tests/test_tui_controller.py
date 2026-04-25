"""Unit tests for TUI command and shortcut handling."""

from __future__ import annotations

import unittest

from src.tui_controller import TuiController


class TuiControllerTests(unittest.TestCase):
    """Tests for slash command parsing and shortcut dispatch."""

    def test_plain_text_submits_prompt(self) -> None:
        controller = TuiController()
        result = controller.handle_submission("hello")
        assert result.action == "submit_prompt"
        assert result.prompt == "hello"

    def test_help_command_shows_message(self) -> None:
        controller = TuiController()
        result = controller.handle_submission("/help")
        assert result.action == "show_message"
        assert "Available commands" in result.message

    def test_prompt_command_requires_arguments(self) -> None:
        controller = TuiController()
        result = controller.handle_submission("/prompt")
        assert result.action == "show_message"
        assert result.message == "Usage: /prompt <text>"

    def test_prompt_command_submits_arguments(self) -> None:
        controller = TuiController()
        result = controller.handle_submission("/prompt explain this")
        assert result.action == "submit_prompt"
        assert result.prompt == "explain this"

    def test_unknown_command_reports_error(self) -> None:
        controller = TuiController()
        result = controller.handle_submission("/missing")
        assert result.action == "show_message"
        assert "Unknown command: /missing" in result.message

    def test_shortcuts_map_to_expected_actions(self) -> None:
        controller = TuiController()
        assert controller.handle_shortcut("ctrl+l").action == "clear_transcript"
        assert controller.handle_shortcut("ctrl+q").action == "quit"
        assert controller.handle_shortcut("f1").action == "show_message"


if __name__ == "__main__":
    unittest.main()
