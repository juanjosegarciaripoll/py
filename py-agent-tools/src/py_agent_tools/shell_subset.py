"""Typed shell-subset AST and structural validation helpers.

This module defines the safe shell grammar subset as data structures only.
Parsing and execution are intentionally separated and implemented in later steps.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

type RedirectOperator = Literal["<", ">", ">>"]
type PipelineCondition = Literal["always", "on_success", "on_failure"]
_ENV_NAME_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


class ShellSubsetError(ValueError):
    """Raised when shell-subset structures violate policy or shape rules."""

    @classmethod
    def invalid_env_name(cls, name: str) -> ShellSubsetError:
        """Create invalid-environment-name error."""
        message = f"Invalid environment variable name: {name}"
        return cls(message)

    @classmethod
    def empty_program(cls) -> ShellSubsetError:
        """Create empty-program error."""
        message = "Shell program must contain at least one pipeline."
        return cls(message)

    @classmethod
    def pipeline_count_exceeded(cls) -> ShellSubsetError:
        """Create pipeline-count-exceeded error."""
        message = "Shell program exceeds maximum pipeline count."
        return cls(message)

    @classmethod
    def empty_pipeline(cls) -> ShellSubsetError:
        """Create empty-pipeline error."""
        message = "Pipeline must contain at least one command."
        return cls(message)

    @classmethod
    def command_count_exceeded(cls) -> ShellSubsetError:
        """Create command-count-exceeded error."""
        message = "Pipeline exceeds maximum command count."
        return cls(message)

    @classmethod
    def pipelines_disabled(cls) -> ShellSubsetError:
        """Create pipelines-disabled error."""
        message = "Pipelines are disabled by shell-subset features."
        return cls(message)

    @classmethod
    def stderr_pipe_disabled(cls) -> ShellSubsetError:
        """Create stderr-pipe-disabled error."""
        message = "Stderr piping is disabled by shell-subset features."
        return cls(message)

    @classmethod
    def empty_command_program(cls) -> ShellSubsetError:
        """Create empty-command-program error."""
        message = "Command program cannot be empty."
        return cls(message)

    @classmethod
    def argument_count_exceeded(cls) -> ShellSubsetError:
        """Create argument-count-exceeded error."""
        message = "Command exceeds maximum argument count."
        return cls(message)

    @classmethod
    def env_assignments_disabled(cls) -> ShellSubsetError:
        """Create env-assignments-disabled error."""
        message = "Environment assignments are disabled by shell-subset features."
        return cls(message)

    @classmethod
    def redirection_count_exceeded(cls) -> ShellSubsetError:
        """Create redirection-count-exceeded error."""
        message = "Command exceeds maximum redirection count."
        return cls(message)

    @classmethod
    def redirections_disabled(cls) -> ShellSubsetError:
        """Create redirections-disabled error."""
        message = "Redirections are disabled by shell-subset features."
        return cls(message)

    @classmethod
    def invalid_pipeline_condition(cls, condition: str) -> ShellSubsetError:
        """Create invalid-pipeline-condition error."""
        message = f"Invalid pipeline condition: {condition}"
        return cls(message)


@dataclass(slots=True, frozen=True)
class ShellSubsetFeatures:
    """Feature switches defining the accepted shell-subset syntax."""

    allow_env_assignments: bool = True
    allow_pipelines: bool = True
    allow_redirections: bool = True
    allow_stderr_pipe: bool = False


@dataclass(slots=True, frozen=True)
class ShellLimits:
    """Structural limits used by subset validation."""

    max_pipelines: int = 8
    max_commands_per_pipeline: int = 8
    max_arguments_per_command: int = 64
    max_redirections_per_command: int = 8


@dataclass(slots=True, frozen=True)
class ShellEnvAssignment:
    """Environment variable assignment (`NAME=value`)."""

    name: str
    value: str

    def __post_init__(self) -> None:
        if not _ENV_NAME_PATTERN.fullmatch(self.name):
            raise ShellSubsetError.invalid_env_name(self.name)


@dataclass(slots=True, frozen=True)
class ShellRedirection:
    """Input/output redirection."""

    operator: RedirectOperator
    target: str


@dataclass(slots=True, frozen=True)
class ShellSimpleCommand:
    """A single command invocation with optional assignments/redirections."""

    program: str
    arguments: tuple[str, ...] = ()
    env_assignments: tuple[ShellEnvAssignment, ...] = ()
    redirections: tuple[ShellRedirection, ...] = ()


@dataclass(slots=True, frozen=True)
class ShellPipeline:
    """A sequence of commands connected by pipes."""

    commands: tuple[ShellSimpleCommand, ...]
    pipe_stderr: bool = False


@dataclass(slots=True, frozen=True)
class ShellProgram:
    """Root AST node for the supported subset."""

    steps: tuple[ShellPipelineStep, ...]


@dataclass(slots=True, frozen=True)
class ShellPipelineStep:
    """Pipeline plus condition controlling whether it should run."""

    pipeline: ShellPipeline
    condition: PipelineCondition = "always"


def validate_shell_program(
    program: ShellProgram,
    *,
    features: ShellSubsetFeatures | None = None,
    limits: ShellLimits | None = None,
) -> None:
    """Validate program shape against configured feature switches and limits."""
    active_features = features or ShellSubsetFeatures()
    active_limits = limits or ShellLimits()
    pipeline_count = len(program.steps)
    if pipeline_count == 0:
        raise ShellSubsetError.empty_program()
    if pipeline_count > active_limits.max_pipelines:
        raise ShellSubsetError.pipeline_count_exceeded()
    for step in program.steps:
        if step.condition not in {"always", "on_success", "on_failure"}:
            raise ShellSubsetError.invalid_pipeline_condition(step.condition)
        _validate_pipeline(
            step.pipeline,
            features=active_features,
            limits=active_limits,
        )


def _validate_pipeline(
    pipeline: ShellPipeline,
    *,
    features: ShellSubsetFeatures,
    limits: ShellLimits,
) -> None:
    command_count = len(pipeline.commands)
    if command_count == 0:
        raise ShellSubsetError.empty_pipeline()
    if command_count > limits.max_commands_per_pipeline:
        raise ShellSubsetError.command_count_exceeded()
    if command_count > 1 and not features.allow_pipelines:
        raise ShellSubsetError.pipelines_disabled()
    if pipeline.pipe_stderr and not features.allow_stderr_pipe:
        raise ShellSubsetError.stderr_pipe_disabled()
    for command in pipeline.commands:
        _validate_simple_command(
            command,
            features=features,
            limits=limits,
        )


def _validate_simple_command(
    command: ShellSimpleCommand,
    *,
    features: ShellSubsetFeatures,
    limits: ShellLimits,
) -> None:
    if not command.program:
        raise ShellSubsetError.empty_command_program()
    if len(command.arguments) > limits.max_arguments_per_command:
        raise ShellSubsetError.argument_count_exceeded()
    if command.env_assignments and not features.allow_env_assignments:
        raise ShellSubsetError.env_assignments_disabled()
    redirection_count = len(command.redirections)
    if redirection_count > limits.max_redirections_per_command:
        raise ShellSubsetError.redirection_count_exceeded()
    if redirection_count > 0 and not features.allow_redirections:
        raise ShellSubsetError.redirections_disabled()
