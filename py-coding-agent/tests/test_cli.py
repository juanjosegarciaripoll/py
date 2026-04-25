"""Unit tests for py-coding-agent CLI execution modes."""

from __future__ import annotations

import io
import json
import shutil
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src import session
from src.cli import CodingAgentApp, RunConfig, build_parser, main, parse_args

ARGPARSE_ERROR_EXIT_CODE = 2
TMP_DIR = Path(__file__).resolve().parent / ".tmp"


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
            RunConfig(mode="print", prompt="hello", session_file=None, branch="main"),
            stdin=io.StringIO(),
            stdout=stdout,
        )
        assert exit_code == 0
        assert stdout.getvalue() == "Echo: hello\n"

    def test_run_json_mode(self) -> None:
        app = CodingAgentApp()
        stdout = io.StringIO()
        exit_code = app.run(
            RunConfig(mode="json", prompt="hello", session_file=None, branch="main"),
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
            RunConfig(mode="rpc", prompt="", session_file=None, branch="main"),
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
            RunConfig(mode="rpc", prompt="", session_file=None, branch="main"),
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


if __name__ == "__main__":
    unittest.main()
