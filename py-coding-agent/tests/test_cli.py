"""Unit tests for py-coding-agent CLI execution modes."""

from __future__ import annotations

import io
import json
import shutil
import sys
import unittest
from pathlib import Path
from typing import TYPE_CHECKING, cast

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src import session
from src.cli import CodingAgentApp, RunConfig, build_parser, main, parse_args
from src.extensions import SessionBeforeCompactDecision

if TYPE_CHECKING:
    from src.extensions import AppEvent, SessionBeforeCompactContext

ARGPARSE_ERROR_EXIT_CODE = 2
TMP_DIR = Path(__file__).resolve().parent / ".tmp"
DEFAULT_CONTEXT_WINDOW_TOKENS = 272_000
DEFAULT_RESERVE_TOKENS = 16_384
DEFAULT_KEEP_RECENT_TOKENS = 20_000
COMPACTION_OVERRIDE_TOKENS_AFTER = 77


class CliTests(unittest.TestCase):
    """Tests for argument parsing and mode execution."""

    def test_build_parser_has_expected_defaults(self) -> None:
        parser = build_parser()
        namespace = parser.parse_args([])
        assert namespace.mode == "interactive"
        assert namespace.prompt == ""
        assert namespace.session_file is None
        assert namespace.branch == "main"

    def test_parse_args_print_mode(self) -> None:
        config = parse_args(["--mode", "print", "hello"])
        assert config.mode == "print"
        assert config.prompt == "hello"
        assert config.session_file is None
        assert config.branch == "main"
        assert config.config_file is None
        assert config.context_window_tokens == DEFAULT_CONTEXT_WINDOW_TOKENS
        assert config.compaction_enabled is True
        assert config.compaction_reserve_tokens == DEFAULT_RESERVE_TOKENS
        assert config.compaction_keep_recent_tokens == DEFAULT_KEEP_RECENT_TOKENS

    def test_parse_args_with_session_options(self) -> None:
        config = parse_args(
            [
                "--mode",
                "json",
                "--session-file",
                "tmp/session.jsonl",
                "--branch",
                "feature-x",
                "hello",
            ]
        )
        assert config.mode == "json"
        assert config.prompt == "hello"
        assert config.session_file == "tmp/session.jsonl"
        assert config.branch == "feature-x"
        assert config.config_file is None

    def test_parse_args_tui_mode(self) -> None:
        config = parse_args(["--mode", "tui"])
        assert config.mode == "tui"

    def test_parse_args_uses_config_defaults_and_cli_overrides(self) -> None:
        test_dir = TMP_DIR / "cli-config"
        shutil.rmtree(test_dir, ignore_errors=True)
        test_dir.mkdir(parents=True, exist_ok=True)
        config_path = test_dir / "agent.toml"
        config_path.write_text(
            "[agent]\nmode='json'\nbranch='feature-a'\nsession_file='saved.jsonl'\n",
            encoding="utf-8",
        )
        try:
            loaded = parse_args(["--config", str(config_path), "prompt-a"])
            assert loaded.mode == "json"
            assert loaded.branch == "feature-a"
            assert loaded.session_file == "saved.jsonl"
            assert loaded.config_file == str(config_path)

            overridden = parse_args(
                [
                    "--config",
                    str(config_path),
                    "--mode",
                    "print",
                    "--branch",
                    "hotfix",
                    "--session-file",
                    "override.jsonl",
                    "prompt-b",
                ]
            )
            assert overridden.mode == "print"
            assert overridden.branch == "hotfix"
            assert overridden.session_file == "override.jsonl"
        finally:
            shutil.rmtree(test_dir, ignore_errors=True)

    def test_parse_args_loads_tool_policy_defaults(self) -> None:
        test_dir = TMP_DIR / "cli-tools-config"
        shutil.rmtree(test_dir, ignore_errors=True)
        test_dir.mkdir(parents=True, exist_ok=True)
        config_path = test_dir / "agent.toml"
        config_path.write_text(
            "[agent]\n"
            "[agent.tools]\n"
            "allow_read=false\n"
            "allow_write=true\n"
            "allow_execute=false\n"
            "allowed_roots=['py-coding-agent/src']\n",
            encoding="utf-8",
        )
        try:
            config = parse_args(["--config", str(config_path), "--mode", "rpc"])
            assert config.tool_allow_read is False
            assert config.tool_allow_write is True
            assert config.tool_allow_execute is False
            assert config.tool_allowed_roots == ("py-coding-agent/src",)
        finally:
            shutil.rmtree(test_dir, ignore_errors=True)

    def test_parse_args_rejects_invalid_mode(self) -> None:
        error: BaseException | None = None
        try:
            parse_args(["--mode", "invalid"])
        except BaseException as caught:  # noqa: BLE001
            error = caught
        assert isinstance(error, SystemExit)
        assert error.code == ARGPARSE_ERROR_EXIT_CODE

    def test_run_print_mode(self) -> None:
        app = CodingAgentApp()
        stdout = io.StringIO()
        exit_code = app.run(
            RunConfig(
                mode="print",
                prompt="hello",
                session_file=None,
                branch="main",
                config_file=None,
                context_window_tokens=272000,
                compaction_enabled=True,
                compaction_reserve_tokens=16384,
                compaction_keep_recent_tokens=20000,
            ),
            stdin=io.StringIO(),
            stdout=stdout,
        )
        assert exit_code == 0
        assert stdout.getvalue() == "Echo: hello\n"

    def test_run_json_mode(self) -> None:
        app = CodingAgentApp()
        stdout = io.StringIO()
        exit_code = app.run(
            RunConfig(
                mode="json",
                prompt="hello",
                session_file=None,
                branch="main",
                config_file=None,
                context_window_tokens=272000,
                compaction_enabled=True,
                compaction_reserve_tokens=16384,
                compaction_keep_recent_tokens=20000,
            ),
            stdin=io.StringIO(),
            stdout=stdout,
        )
        assert exit_code == 0
        payload = json.loads(stdout.getvalue().strip())
        assert payload["mode"] == "json"
        assert payload["prompt"] == "hello"
        assert payload["response"] == "Echo: hello"

    def test_run_interactive_mode(self) -> None:
        app = CodingAgentApp()
        stdin = io.StringIO("test\nexit\n")
        stdout = io.StringIO()
        exit_code = app.run(
            RunConfig(
                mode="interactive",
                prompt="",
                session_file=None,
                branch="main",
                config_file=None,
                context_window_tokens=272000,
                compaction_enabled=True,
                compaction_reserve_tokens=16384,
                compaction_keep_recent_tokens=20000,
            ),
            stdin=stdin,
            stdout=stdout,
        )
        assert exit_code == 0
        text = stdout.getvalue()
        assert "Interactive mode. Type 'exit' to quit." in text
        assert "Echo: test" in text

    def test_run_interactive_mode_eof(self) -> None:
        app = CodingAgentApp()
        stdout = io.StringIO()
        exit_code = app.run(
            RunConfig(
                mode="interactive",
                prompt="",
                session_file=None,
                branch="main",
                config_file=None,
                context_window_tokens=272000,
                compaction_enabled=True,
                compaction_reserve_tokens=16384,
                compaction_keep_recent_tokens=20000,
            ),
            stdin=io.StringIO(""),
            stdout=stdout,
        )
        assert exit_code == 0
        assert stdout.getvalue().startswith("Interactive mode")

    def test_run_rpc_mode(self) -> None:
        app = CodingAgentApp()
        request = {
            "id": "req-1",
            "method": "prompt",
            "params": {"prompt": "hello"},
        }
        stdin = io.StringIO(json.dumps(request) + "\n" + '{"method":"shutdown"}\n')
        stdout = io.StringIO()
        exit_code = app.run(
            RunConfig(
                mode="rpc",
                prompt="",
                session_file=None,
                branch="main",
                config_file=None,
                context_window_tokens=272000,
                compaction_enabled=True,
                compaction_reserve_tokens=16384,
                compaction_keep_recent_tokens=20000,
            ),
            stdin=stdin,
            stdout=stdout,
        )
        lines = [line for line in stdout.getvalue().splitlines() if line]
        assert exit_code == 0
        response = json.loads(lines[0])
        assert response["id"] == "req-1"
        assert response["result"]["response"] == "Echo: hello"
        assert lines[1] == '{"ok":true}'

    def test_run_rpc_mode_error_paths(self) -> None:
        app = CodingAgentApp()
        stdin = io.StringIO(
            "\n"
            "not-json\n"
            '["array"]\n'
            '{"method":"unknown"}\n'
            '{"method":"prompt","params":[]}\n'
            '{"method":"prompt","params":{"prompt":1}}\n'
            '{"method":"shutdown"}\n'
        )
        stdout = io.StringIO()
        exit_code = app.run(
            RunConfig(
                mode="rpc",
                prompt="",
                session_file=None,
                branch="main",
                config_file=None,
                context_window_tokens=272000,
                compaction_enabled=True,
                compaction_reserve_tokens=16384,
                compaction_keep_recent_tokens=20000,
            ),
            stdin=stdin,
            stdout=stdout,
        )
        assert exit_code == 0
        lines = [line for line in stdout.getvalue().splitlines() if line]
        assert lines[0] == '{"error":"invalid_json"}'
        assert lines[1] == '{"error":"invalid_request"}'
        assert lines[2] == '{"error":"method_not_found"}'
        assert lines[3] == '{"error":"invalid_params"}'
        assert lines[4] == '{"error":"invalid_params"}'
        assert lines[5] == '{"ok":true}'

    def test_run_rpc_mode_tool_success(self) -> None:
        app = CodingAgentApp()
        request: dict[str, object] = {
            "id": "tool-1",
            "method": "tool",
            "params": {
                "name": "find",
                "arguments": {"pattern": "*.py", "base_path": "py-coding-agent/src"},
            },
        }
        stdin = io.StringIO(json.dumps(request) + "\n" + '{"method":"shutdown"}\n')
        stdout = io.StringIO()
        exit_code = app.run(
            RunConfig(
                mode="rpc",
                prompt="",
                session_file=None,
                branch="main",
                config_file=None,
                context_window_tokens=272000,
                compaction_enabled=True,
                compaction_reserve_tokens=16384,
                compaction_keep_recent_tokens=20000,
            ),
            stdin=stdin,
            stdout=stdout,
        )
        lines = [line for line in stdout.getvalue().splitlines() if line]
        assert exit_code == 0
        response = cast("dict[str, object]", json.loads(lines[0]))
        assert response["id"] == "tool-1"
        result = cast("list[object]", response["result"])
        assert isinstance(result, list)
        assert any(
            isinstance(item, str) and item.endswith("cli.py")
            for item in result
        )

    def test_run_rpc_mode_tool_error(self) -> None:
        app = CodingAgentApp()
        request: dict[str, object] = {
            "id": "tool-2",
            "method": "tool",
            "params": {"name": "unknown", "arguments": {}},
        }
        stdin = io.StringIO(json.dumps(request) + "\n" + '{"method":"shutdown"}\n')
        stdout = io.StringIO()
        exit_code = app.run(
            RunConfig(
                mode="rpc",
                prompt="",
                session_file=None,
                branch="main",
                config_file=None,
                context_window_tokens=272000,
                compaction_enabled=True,
                compaction_reserve_tokens=16384,
                compaction_keep_recent_tokens=20000,
            ),
            stdin=stdin,
            stdout=stdout,
        )
        lines = [line for line in stdout.getvalue().splitlines() if line]
        assert exit_code == 0
        response = json.loads(lines[0])
        assert response["id"] == "tool-2"
        assert response["error"]["code"] == "tool_error"

    def test_run_rpc_mode_honors_execute_policy(self) -> None:
        app = CodingAgentApp()
        request: dict[str, object] = {
            "id": "tool-3",
            "method": "tool",
            "params": {
                "name": "bash",
                "arguments": {"command": "echo hello"},
            },
        }
        stdin = io.StringIO(json.dumps(request) + "\n" + '{"method":"shutdown"}\n')
        stdout = io.StringIO()
        exit_code = app.run(
            RunConfig(
                mode="rpc",
                prompt="",
                session_file=None,
                branch="main",
                config_file=None,
                context_window_tokens=272000,
                compaction_enabled=True,
                compaction_reserve_tokens=16384,
                compaction_keep_recent_tokens=20000,
                tool_allow_execute=False,
            ),
            stdin=stdin,
            stdout=stdout,
        )
        lines = [line for line in stdout.getvalue().splitlines() if line]
        assert exit_code == 0
        response = cast("dict[str, object]", json.loads(lines[0]))
        error = cast("dict[str, object]", response["error"])
        assert error["code"] == "tool_error"
        assert "disabled by policy" in str(error["message"])

    def test_run_tui_mode_calls_launcher(self) -> None:
        class StubTuiApp(CodingAgentApp):
            def __init__(self) -> None:
                super().__init__()
                self.called = False

            def _launch_tui_mode(
                self,
                *,
                store: object,
                persistence: object,
                stdout: object,
            ) -> int:
                del store, persistence, stdout
                self.called = True
                return 0

        app = StubTuiApp()
        exit_code = app.run(
            RunConfig(
                mode="tui",
                prompt="",
                session_file=None,
                branch="main",
                config_file=None,
                context_window_tokens=272000,
                compaction_enabled=True,
                compaction_reserve_tokens=16384,
                compaction_keep_recent_tokens=20000,
            ),
            stdin=io.StringIO(),
            stdout=io.StringIO(),
        )
        assert exit_code == 0
        assert app.called is True

    def test_print_mode_persists_session_record(self) -> None:
        app = CodingAgentApp()
        test_dir = TMP_DIR / "cli-session"
        shutil.rmtree(test_dir, ignore_errors=True)
        test_dir.mkdir(parents=True, exist_ok=True)
        try:
            session_path = test_dir / "session.jsonl"
            now_ms = 1_710_000_000_000
            original_timestamp = session.timestamp_ms
            try:
                session.timestamp_ms = lambda: now_ms
                stdout = io.StringIO()
                exit_code = app.run(
                    RunConfig(
                        mode="print",
                        prompt="hello",
                        session_file=str(session_path),
                        branch="feature-x",
                        config_file=None,
                        context_window_tokens=272000,
                        compaction_enabled=True,
                        compaction_reserve_tokens=16384,
                        compaction_keep_recent_tokens=20000,
                    ),
                    stdin=io.StringIO(),
                    stdout=stdout,
                )
            finally:
                session.timestamp_ms = original_timestamp
            assert exit_code == 0
            lines = session_path.read_text(encoding="utf-8").splitlines()
            assert len(lines) == 1
            payload = json.loads(lines[0])
            assert payload["timestamp_ms"] == now_ms
            assert payload["branch"] == "feature-x"
            assert payload["mode"] == "print"
            assert payload["prompt"] == "hello"
            assert payload["response"] == "Echo: hello"
        finally:
            shutil.rmtree(test_dir, ignore_errors=True)

    def test_main_uses_parsed_args(self) -> None:
        original_stdin = sys.stdin
        original_stdout = sys.stdout
        try:
            sys.stdin = io.StringIO()
            sys.stdout = io.StringIO()
            exit_code = main(["--mode", "print", "from-main"])
            output = sys.stdout.getvalue()
        finally:
            sys.stdin = original_stdin
            sys.stdout = original_stdout
        assert exit_code == 0
        assert output == "Echo: from-main\n"

    def test_subscribe_emits_interaction_event(self) -> None:
        app = CodingAgentApp()
        seen: list[AppEvent] = []

        def listener(event: AppEvent) -> None:
            seen.append(event)

        unsubscribe = app.subscribe(listener)
        app.run(
            RunConfig(
                mode="print",
                prompt="hello",
                session_file=None,
                branch="branch-a",
                config_file=None,
                context_window_tokens=272000,
                compaction_enabled=True,
                compaction_reserve_tokens=16384,
                compaction_keep_recent_tokens=20000,
            ),
            stdin=io.StringIO(),
            stdout=io.StringIO(),
        )
        unsubscribe()

        assert len(seen) == 1
        assert seen[0].type == "interaction_complete"
        assert seen[0].mode == "print"
        assert seen[0].prompt == "hello"
        assert seen[0].branch == "branch-a"

    def test_session_compaction_event_is_emitted(self) -> None:
        app = CodingAgentApp()
        seen: list[AppEvent] = []

        def listener(event: AppEvent) -> None:
            seen.append(event)

        app.subscribe(listener)

        test_dir = TMP_DIR / "cli-compaction-event"
        shutil.rmtree(test_dir, ignore_errors=True)
        test_dir.mkdir(parents=True, exist_ok=True)
        session_path = test_dir / "session.jsonl"
        try:
            for index in range(4):
                app.run(
                    RunConfig(
                        mode="print",
                        prompt=f"prompt-{index} " + ("x" * 120),
                        session_file=str(session_path),
                        branch="main",
                        config_file=None,
                        context_window_tokens=200,
                        compaction_enabled=True,
                        compaction_reserve_tokens=40,
                        compaction_keep_recent_tokens=40,
                    ),
                    stdin=io.StringIO(),
                    stdout=io.StringIO(),
                )
        finally:
            shutil.rmtree(test_dir, ignore_errors=True)

        compacted = [event for event in seen if event.type == "session_compacted"]
        assert compacted
        assert compacted[-1].tokens_before is not None
        assert compacted[-1].tokens_after is not None

    def test_session_before_compact_hook_can_cancel_compaction(self) -> None:
        app = CodingAgentApp()
        test_dir = TMP_DIR / "cli-compaction-cancel"
        shutil.rmtree(test_dir, ignore_errors=True)
        test_dir.mkdir(parents=True, exist_ok=True)
        session_path = test_dir / "session.jsonl"
        try:
            seen: list[AppEvent] = []

            def listener(event: AppEvent) -> None:
                seen.append(event)

            def cancel_hook(
                _context: SessionBeforeCompactContext,
            ) -> SessionBeforeCompactDecision:
                return SessionBeforeCompactDecision(cancel=True)

            app.subscribe(listener)
            app.subscribe_session_before_compact(cancel_hook)
            for index in range(4):
                app.run(
                    RunConfig(
                        mode="print",
                        prompt=f"compact-{index} " + ("x" * 120),
                        session_file=str(session_path),
                        branch="main",
                        config_file=None,
                        context_window_tokens=200,
                        compaction_enabled=True,
                        compaction_reserve_tokens=40,
                        compaction_keep_recent_tokens=40,
                    ),
                    stdin=io.StringIO(),
                    stdout=io.StringIO(),
                )
            entries = session_path.read_text(encoding="utf-8").splitlines()
            payloads = [cast("dict[str, object]", json.loads(line)) for line in entries]
            assert all(payload.get("type") == "interaction" for payload in payloads)
            assert all(event.type != "session_compacted" for event in seen)
        finally:
            shutil.rmtree(test_dir, ignore_errors=True)

    def test_session_before_compact_hook_can_override_summary(self) -> None:
        app = CodingAgentApp()
        test_dir = TMP_DIR / "cli-compaction-override"
        shutil.rmtree(test_dir, ignore_errors=True)
        test_dir.mkdir(parents=True, exist_ok=True)
        session_path = test_dir / "session.jsonl"
        try:
            def override_hook(
                context: SessionBeforeCompactContext,
            ) -> SessionBeforeCompactDecision:
                return SessionBeforeCompactDecision(
                    summary="Manual checkpoint",
                    first_kept_id=context.proposed_first_kept_id,
                    tokens_after=COMPACTION_OVERRIDE_TOKENS_AFTER,
                )

            app.subscribe_session_before_compact(override_hook)
            for index in range(4):
                app.run(
                    RunConfig(
                        mode="print",
                        prompt=f"compact-{index} " + ("x" * 120),
                        session_file=str(session_path),
                        branch="main",
                        config_file=None,
                        context_window_tokens=200,
                        compaction_enabled=True,
                        compaction_reserve_tokens=40,
                        compaction_keep_recent_tokens=40,
                    ),
                    stdin=io.StringIO(),
                    stdout=io.StringIO(),
                )
            entries = session_path.read_text(encoding="utf-8").splitlines()
            payloads = [cast("dict[str, object]", json.loads(line)) for line in entries]
            compactions = [
                payload
                for payload in payloads
                if payload.get("type") == "compaction"
            ]
            assert compactions
            latest = compactions[-1]
            assert latest["summary"] == "Manual checkpoint"
            assert latest["tokens_after"] == COMPACTION_OVERRIDE_TOKENS_AFTER
        finally:
            shutil.rmtree(test_dir, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
