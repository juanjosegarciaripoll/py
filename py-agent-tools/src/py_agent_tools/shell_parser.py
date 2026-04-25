"""Composable parser stages for the safe shell subset."""

from __future__ import annotations

import shlex
from dataclasses import dataclass, field
from typing import Literal

from .shell_subset import (
    PipelineCondition,
    ShellEnvAssignment,
    ShellLimits,
    ShellPipeline,
    ShellPipelineStep,
    ShellProgram,
    ShellRedirection,
    ShellSimpleCommand,
    ShellSubsetError,
    ShellSubsetFeatures,
    validate_shell_program,
)

_REDIRECT_OPERATORS = {"<", ">", ">>"}
_PIPE_OPERATORS = {"|", "|&"}
_PIPELINE_SEPARATORS = {";"}
_CONDITIONAL_OPERATORS = {"&&", "||"}
_UNSUPPORTED_CONTROL_OPERATORS = {"&"}
_PIPELINE_CONNECTORS = _PIPELINE_SEPARATORS | _CONDITIONAL_OPERATORS
_DELIMITERS = _REDIRECT_OPERATORS | _PIPE_OPERATORS | _PIPELINE_CONNECTORS
type RedirectOperator = Literal["<", ">", ">>"]


class ShellParseError(ShellSubsetError):
    """Raised when tokenization or parsing fails for the shell subset."""

    @classmethod
    def empty_input(cls) -> ShellParseError:
        """Create empty-input error."""
        message = "Shell command is empty."
        return cls(message)

    @classmethod
    def tokenization_failed(cls, details: str) -> ShellParseError:
        """Create tokenization-failed error."""
        message = f"Shell tokenization failed: {details}"
        return cls(message)

    @classmethod
    def trailing_operator(cls, operator: str) -> ShellParseError:
        """Create trailing-operator error."""
        message = f"Operator requires a following command: {operator}"
        return cls(message)

    @classmethod
    def expected_command(cls) -> ShellParseError:
        """Create expected-command error."""
        message = "Expected command after operator."
        return cls(message)

    @classmethod
    def missing_redirection_target(cls, operator: str) -> ShellParseError:
        """Create missing-redirection-target error."""
        message = f"Redirection missing target: {operator}"
        return cls(message)

    @classmethod
    def invalid_redirection_target(cls, target: str) -> ShellParseError:
        """Create invalid-redirection-target error."""
        message = f"Invalid redirection target: {target}"
        return cls(message)

    @classmethod
    def unsupported_operator(cls, operator: str) -> ShellParseError:
        """Create unsupported-operator error."""
        message = f"Unsupported control operator: {operator}"
        return cls(message)

    @classmethod
    def trailing_separator(cls, separator: str) -> ShellParseError:
        """Create trailing-separator error."""
        message = f"Separator cannot terminate command: {separator}"
        return cls(message)


@dataclass(slots=True, frozen=True)
class ShlexTokenizer:
    """Tokenize shell input with strict `shlex` settings."""

    punctuation_chars: str = "|&;<>"
    posix: bool = True

    def tokenize(self, command: str) -> tuple[str, ...]:
        """Tokenize shell text using shlex."""
        if not command.strip():
            raise ShellParseError.empty_input()
        lexer = shlex.shlex(
            command,
            posix=self.posix,
            punctuation_chars=self.punctuation_chars,
        )
        lexer.whitespace_split = True
        lexer.commenters = ""
        try:
            tokens = tuple(token for token in lexer if token)
        except ValueError as exc:
            raise ShellParseError.tokenization_failed(str(exc)) from exc
        if not tokens:
            raise ShellParseError.empty_input()
        return tokens


@dataclass(slots=True)
class _TokenCursor:
    """Mutable token cursor used by parser internals."""

    tokens: tuple[str, ...]
    index: int = 0

    @property
    def done(self) -> bool:
        """Whether all tokens have been consumed."""
        return self.index >= len(self.tokens)

    def peek(self) -> str:
        """Peek current token."""
        return self.tokens[self.index]

    def pop(self) -> str:
        """Consume and return current token."""
        token = self.tokens[self.index]
        self.index += 1
        return token


@dataclass(slots=True, frozen=True)
class ShellSubsetParser:
    """Parse token streams into shell-subset AST structures."""

    tokenizer: ShlexTokenizer = field(default_factory=ShlexTokenizer)
    features: ShellSubsetFeatures = field(default_factory=ShellSubsetFeatures)
    limits: ShellLimits = field(default_factory=ShellLimits)

    def parse(self, command: str) -> ShellProgram:
        """Tokenize and parse one shell command string."""
        tokens = self.tokenizer.tokenize(command)
        return self.parse_tokens(tokens)

    def parse_tokens(self, tokens: tuple[str, ...]) -> ShellProgram:
        """Parse a token stream into a validated shell program."""
        if not tokens:
            raise ShellParseError.empty_input()
        cursor = _TokenCursor(tokens=tokens)
        steps: list[ShellPipelineStep] = []
        next_condition: PipelineCondition = "always"
        while not cursor.done:
            steps.append(
                ShellPipelineStep(
                    pipeline=_parse_pipeline(cursor),
                    condition=next_condition,
                )
            )
            if cursor.done:
                break
            connector = cursor.pop()
            next_condition = _parse_connector_condition(connector)
            if cursor.done:
                raise ShellParseError.trailing_separator(connector)
        program = ShellProgram(steps=tuple(steps))
        validate_shell_program(
            program,
            features=self.features,
            limits=self.limits,
        )
        return program


def parse_shell_command(
    command: str,
    *,
    parser: ShellSubsetParser | None = None,
) -> ShellProgram:
    """Convenience function for parsing shell text into AST."""
    active_parser = parser or ShellSubsetParser()
    return active_parser.parse(command)


def _parse_pipeline(cursor: _TokenCursor) -> ShellPipeline:
    commands: list[ShellSimpleCommand] = [_parse_simple_command(cursor)]
    pipe_stderr = False
    while not cursor.done and cursor.peek() in _PIPE_OPERATORS:
        operator = cursor.pop()
        if operator == "|&":
            pipe_stderr = True
        if cursor.done:
            raise ShellParseError.trailing_operator(operator)
        commands.append(_parse_simple_command(cursor))
    return ShellPipeline(commands=tuple(commands), pipe_stderr=pipe_stderr)


def _parse_simple_command(cursor: _TokenCursor) -> ShellSimpleCommand:
    program: str | None = None
    arguments: list[str] = []
    env_assignments: list[ShellEnvAssignment] = []
    redirections: list[ShellRedirection] = []
    while not cursor.done:
        token = cursor.peek()
        if token in _UNSUPPORTED_CONTROL_OPERATORS:
            raise ShellParseError.unsupported_operator(token)
        if token in _PIPE_OPERATORS or token in _PIPELINE_CONNECTORS:
            break
        if token in _REDIRECT_OPERATORS:
            redirections.append(_parse_redirection(cursor))
            continue
        cursor.pop()
        if program is None:
            env_assignment = _parse_env_assignment(token)
            if env_assignment is not None:
                env_assignments.append(env_assignment)
                continue
            program = token
            continue
        arguments.append(token)
    if program is None:
        raise ShellParseError.expected_command()
    return ShellSimpleCommand(
        program=program,
        arguments=tuple(arguments),
        env_assignments=tuple(env_assignments),
        redirections=tuple(redirections),
    )


def _parse_redirection(cursor: _TokenCursor) -> ShellRedirection:
    operator = _to_redirect_operator(cursor.pop())
    if cursor.done:
        raise ShellParseError.missing_redirection_target(operator)
    target = cursor.pop()
    if target in _DELIMITERS or target in _UNSUPPORTED_CONTROL_OPERATORS:
        raise ShellParseError.invalid_redirection_target(target)
    return ShellRedirection(operator=operator, target=target)


def _parse_connector_condition(token: str) -> PipelineCondition:
    match token:
        case ";":
            return "always"
        case "&&":
            return "on_success"
        case "||":
            return "on_failure"
        case "&":
            raise ShellParseError.unsupported_operator(token)
        case _:
            raise ShellParseError.trailing_separator(token)


def _to_redirect_operator(value: str) -> RedirectOperator:
    match value:
        case "<" | ">" | ">>":
            return value
        case _:
            raise ShellParseError.unsupported_operator(value)


def _parse_env_assignment(token: str) -> ShellEnvAssignment | None:
    if "=" not in token:
        return None
    name, value = token.split("=", 1)
    if not name:
        return None
    try:
        return ShellEnvAssignment(name=name, value=value)
    except ShellSubsetError:
        return None
