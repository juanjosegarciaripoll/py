"""Command and shortcut handling for the Textual TUI mode."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

type TuiAction = Literal[
    "submit_prompt",
    "clear_transcript",
    "quit",
    "show_message",
    "noop",
]

HELP_TEXT = """Available commands:
/help or /hotkeys  Show command and shortcut help
/clear             Clear transcript
/quit or /exit     Exit TUI
/prompt <text>     Submit prompt text

Shortcuts:
Ctrl+L clear transcript
Ctrl+Q quit
F1 show help"""


@dataclass(slots=True)
class TuiCommandResult:
    """Normalized command result consumed by the Textual UI."""

    action: TuiAction
    prompt: str = ""
    message: str = ""


class TuiController:
    """Parse user submissions and shortcut actions for TUI mode."""

    def __init__(self) -> None:
        self._slash_handlers = {
            "/help": self._handle_help,
            "/hotkeys": self._handle_help,
            "/clear": self._handle_clear,
            "/quit": self._handle_quit,
            "/exit": self._handle_quit,
            "/prompt": self._handle_prompt,
        }
        self._shortcut_handlers = {
            "ctrl+l": self._handle_clear,
            "ctrl+q": self._handle_quit,
            "f1": self._handle_help,
        }

    def handle_submission(self, text: str) -> TuiCommandResult:
        """Handle a submitted editor string."""
        content = text.strip()
        if not content:
            return TuiCommandResult(action="noop")
        if not content.startswith("/"):
            return TuiCommandResult(action="submit_prompt", prompt=content)
        command, _, arguments = content.partition(" ")
        handler = self._slash_handlers.get(command)
        if handler is None:
            return TuiCommandResult(
                action="show_message",
                message=f"Unknown command: {command}. Use /help.",
            )
        return handler(arguments.strip())

    def handle_shortcut(self, shortcut_id: str) -> TuiCommandResult:
        """Handle a keyboard shortcut identifier."""
        handler = self._shortcut_handlers.get(shortcut_id)
        if handler is None:
            return TuiCommandResult(action="noop")
        return handler("")

    def _handle_help(self, _arguments: str) -> TuiCommandResult:
        return TuiCommandResult(action="show_message", message=HELP_TEXT)

    def _handle_clear(self, _arguments: str) -> TuiCommandResult:
        return TuiCommandResult(
            action="clear_transcript",
            message="Transcript cleared.",
        )

    def _handle_quit(self, _arguments: str) -> TuiCommandResult:
        return TuiCommandResult(action="quit")

    def _handle_prompt(self, arguments: str) -> TuiCommandResult:
        if not arguments:
            return TuiCommandResult(
                action="show_message",
                message="Usage: /prompt <text>",
            )
        return TuiCommandResult(action="submit_prompt", prompt=arguments)
