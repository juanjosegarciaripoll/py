"""Textual-backed TUI mode launcher for py-coding-agent."""

from __future__ import annotations

import importlib
import importlib.util
from collections.abc import Callable

from .tui_controller import TuiCommandResult, TuiController

type Responder = Callable[[str], str]
type PersistInteraction = Callable[[str, str], None]


def has_textual_dependency() -> bool:
    """Return whether the `textual` package is available."""
    return importlib.util.find_spec("textual") is not None


def launch_tui_mode(
    *,
    responder: Responder,
    persist_interaction: PersistInteraction,
) -> int:
    """Launch the Textual TUI and return an exit code."""
    app_class = _create_textual_app_class(
        responder=responder,
        persist_interaction=persist_interaction,
    )
    app = app_class()
    app.run()
    return 0


def _create_textual_app_class(  # noqa: C901
    *,
    responder: Responder,
    persist_interaction: PersistInteraction,
) -> type:
    textual_app = importlib.import_module("textual.app")
    textual_binding = importlib.import_module("textual.binding")
    textual_widgets = importlib.import_module("textual.widgets")

    app_base = textual_app.App
    binding = textual_binding.Binding
    header = textual_widgets.Header
    footer = textual_widgets.Footer
    input_widget = textual_widgets.Input
    rich_log = textual_widgets.RichLog

    class CodingAgentTextualApp(app_base):  # type: ignore[misc, valid-type]
        _controller: TuiController
        BINDINGS = (
            binding("ctrl+l", "clear_transcript", "Clear"),
            binding("ctrl+q", "quit_app", "Quit"),
            binding("f1", "show_help", "Help"),
        )

        CSS = """
        Screen {
          layout: vertical;
        }

        #transcript {
          height: 1fr;
          border: round $accent;
        }

        #editor {
          margin-top: 1;
        }
        """

        def compose(self) -> object:
            yield header(show_clock=True)
            yield rich_log(id="transcript", wrap=True, markup=False)
            yield input_widget(placeholder="Type a prompt or /help", id="editor")
            yield footer()

        def on_mount(self) -> None:
            self._controller = TuiController()
            self._append_line("TUI mode ready. Press F1 or run /help.")

        def action_show_help(self) -> None:
            self._apply_result(self._controller.handle_shortcut("f1"))

        def action_clear_transcript(self) -> None:
            self._apply_result(self._controller.handle_shortcut("ctrl+l"))

        def action_quit_app(self) -> None:
            self._apply_result(self._controller.handle_shortcut("ctrl+q"))

        def on_input_submitted(self, event: object) -> None:
            value = str(getattr(event, "value", ""))
            self._apply_result(self._controller.handle_submission(value))
            editor = getattr(event, "input", None)
            if editor is not None and hasattr(editor, "value"):
                editor.value = ""

        def _apply_result(self, result: TuiCommandResult) -> None:
            match result.action:
                case "noop":
                    return
                case "show_message":
                    self._append_line(result.message)
                case "clear_transcript":
                    transcript = self.query_one("#transcript")
                    transcript.clear()
                    if result.message:
                        self._append_line(result.message)
                case "quit":
                    self.exit()
                case "submit_prompt":
                    prompt = result.prompt
                    response = responder(prompt)
                    self._append_line(f"You: {prompt}")
                    self._append_line(f"Agent: {response}")
                    persist_interaction(prompt, response)

        def _append_line(self, line: str) -> None:
            transcript = self.query_one("#transcript")
            transcript.write(line)

    return CodingAgentTextualApp
