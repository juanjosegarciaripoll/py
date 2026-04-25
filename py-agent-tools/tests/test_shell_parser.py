"""Unit tests for shell tokenizer and parser stages."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from py_agent_tools import (
    ShellParseError,
    ShellSubsetError,
    ShellSubsetFeatures,
    ShellSubsetParser,
    ShlexTokenizer,
    parse_shell_command,
)

TWO_ITEMS = 2


class ShellParserTests(unittest.TestCase):
    """Tests for shlex tokenization and subset parsing behavior."""

    def test_shlex_tokenizer_handles_quotes(self) -> None:
        tokenizer = ShlexTokenizer()
        tokens = tokenizer.tokenize('echo "hello world"')
        assert tokens == ("echo", "hello world")

    def test_parse_simple_command(self) -> None:
        program = parse_shell_command("echo hello")
        pipeline = program.pipelines[0]
        command = pipeline.commands[0]
        assert command.program == "echo"
        assert command.arguments == ("hello",)

    def test_parse_pipeline(self) -> None:
        program = parse_shell_command("echo hi | cat")
        pipeline = program.pipelines[0]
        assert len(pipeline.commands) == TWO_ITEMS
        assert pipeline.commands[0].program == "echo"
        assert pipeline.commands[1].program == "cat"
        assert pipeline.pipe_stderr is False

    def test_parse_stderr_pipeline(self) -> None:
        parser = ShellSubsetParser(
            features=ShellSubsetFeatures(allow_stderr_pipe=True),
        )
        program = parser.parse("build |& tee build.log")
        pipeline = program.pipelines[0]
        assert pipeline.pipe_stderr is True

    def test_parse_env_assignments_and_redirections(self) -> None:
        program = parse_shell_command("FOO=bar echo hi > out.txt")
        command = program.pipelines[0].commands[0]
        assert command.env_assignments[0].name == "FOO"
        assert command.env_assignments[0].value == "bar"
        assert command.arguments == ("hi",)
        assert command.redirections[0].operator == ">"
        assert command.redirections[0].target == "out.txt"

    def test_parse_multiple_pipelines_with_separator(self) -> None:
        program = parse_shell_command("echo a ; echo b")
        assert len(program.pipelines) == TWO_ITEMS
        assert program.pipelines[0].commands[0].arguments == ("a",)
        assert program.pipelines[1].commands[0].arguments == ("b",)

    def test_parse_rejects_unsupported_operator(self) -> None:
        failed = False
        try:
            parse_shell_command("echo a && echo b")
        except ShellParseError:
            failed = True
        assert failed is True

    def test_parse_rejects_trailing_pipe(self) -> None:
        failed = False
        try:
            parse_shell_command("echo hi |")
        except ShellParseError:
            failed = True
        assert failed is True

    def test_parse_rejects_missing_redirection_target(self) -> None:
        failed = False
        try:
            parse_shell_command("echo hi >")
        except ShellParseError:
            failed = True
        assert failed is True

    def test_parse_rejects_empty_input(self) -> None:
        failed = False
        try:
            parse_shell_command("   ")
        except ShellParseError:
            failed = True
        assert failed is True

    def test_parser_features_enforced_by_validation(self) -> None:
        parser = ShellSubsetParser(
            features=ShellSubsetFeatures(allow_pipelines=False),
        )
        failed = False
        try:
            parser.parse("echo a | cat")
        except ShellSubsetError:
            failed = True
        assert failed is True


if __name__ == "__main__":
    unittest.main()
