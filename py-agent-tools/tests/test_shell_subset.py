"""Unit tests for shell-subset AST definitions and validation."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from py_agent_tools import (
    ShellEnvAssignment,
    ShellLimits,
    ShellPipeline,
    ShellProgram,
    ShellRedirection,
    ShellSimpleCommand,
    ShellSubsetError,
    ShellSubsetFeatures,
    validate_shell_program,
)


class ShellSubsetTests(unittest.TestCase):
    """Tests for shell-subset AST invariants and shape validation."""

    def test_validate_shell_program_accepts_basic_program(self) -> None:
        program = ShellProgram(
            pipelines=(
                ShellPipeline(
                    commands=(
                        ShellSimpleCommand(
                            program="echo",
                            arguments=("hello",),
                            env_assignments=(
                                ShellEnvAssignment(name="FOO", value="bar"),
                            ),
                            redirections=(
                                ShellRedirection(operator=">", target="out.txt"),
                            ),
                        ),
                    ),
                ),
            ),
        )
        validate_shell_program(program)

    def test_env_assignment_rejects_invalid_name(self) -> None:
        failed = False
        try:
            ShellEnvAssignment(name="1NOPE", value="x")
        except ShellSubsetError:
            failed = True
        assert failed is True

    def test_validate_rejects_empty_program(self) -> None:
        failed = False
        try:
            validate_shell_program(ShellProgram(pipelines=()))
        except ShellSubsetError:
            failed = True
        assert failed is True

    def test_validate_rejects_pipeline_when_feature_disabled(self) -> None:
        program = ShellProgram(
            pipelines=(
                ShellPipeline(
                    commands=(
                        ShellSimpleCommand(program="echo"),
                        ShellSimpleCommand(program="cat"),
                    ),
                ),
            ),
        )
        failed = False
        try:
            validate_shell_program(
                program,
                features=ShellSubsetFeatures(allow_pipelines=False),
            )
        except ShellSubsetError:
            failed = True
        assert failed is True

    def test_validate_rejects_env_assignments_when_feature_disabled(self) -> None:
        program = ShellProgram(
            pipelines=(
                ShellPipeline(
                    commands=(
                        ShellSimpleCommand(
                            program="echo",
                            env_assignments=(
                                ShellEnvAssignment(name="FOO", value="bar"),
                            ),
                        ),
                    ),
                ),
            ),
        )
        failed = False
        try:
            validate_shell_program(
                program,
                features=ShellSubsetFeatures(allow_env_assignments=False),
            )
        except ShellSubsetError:
            failed = True
        assert failed is True

    def test_validate_rejects_redirections_when_feature_disabled(self) -> None:
        program = ShellProgram(
            pipelines=(
                ShellPipeline(
                    commands=(
                        ShellSimpleCommand(
                            program="echo",
                            redirections=(
                                ShellRedirection(operator=">", target="out.txt"),
                            ),
                        ),
                    ),
                ),
            ),
        )
        failed = False
        try:
            validate_shell_program(
                program,
                features=ShellSubsetFeatures(allow_redirections=False),
            )
        except ShellSubsetError:
            failed = True
        assert failed is True

    def test_validate_rejects_stderr_pipe_when_feature_disabled(self) -> None:
        program = ShellProgram(
            pipelines=(
                ShellPipeline(
                    commands=(ShellSimpleCommand(program="echo"),),
                    pipe_stderr=True,
                ),
            ),
        )
        failed = False
        try:
            validate_shell_program(
                program,
                features=ShellSubsetFeatures(allow_stderr_pipe=False),
            )
        except ShellSubsetError:
            failed = True
        assert failed is True

    def test_validate_enforces_limits(self) -> None:
        many_commands = tuple(
            ShellSimpleCommand(program=f"cmd{index}") for index in range(3)
        )
        program = ShellProgram(pipelines=(ShellPipeline(commands=many_commands),))
        failed = False
        try:
            validate_shell_program(
                program,
                limits=ShellLimits(max_commands_per_pipeline=2),
            )
        except ShellSubsetError:
            failed = True
        assert failed is True


if __name__ == "__main__":
    unittest.main()

