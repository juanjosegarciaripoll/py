"""Built-in tool execution with simple sandbox policies."""

from __future__ import annotations

import fnmatch
import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from time import monotonic
from typing import Literal

from .shell_args import ShellArgParser, ShellArgsError
from .shell_parser import ShellParseError, parse_shell_command
from .shell_registry import (
    ShellCommandContext,
    ShellCommandRegistry,
    ShellCommandResult,
    ShellRegistryError,
)
from .shell_runtime import (
    ShellCancellationToken,
    ShellExecutionEvent,
    emit_shell_event,
)
from .shell_subset import (
    PipelineCondition,
    ShellEnvAssignment,
    ShellPipeline,
    ShellProgram,
    ShellRedirection,
    ShellSimpleCommand,
    ShellSubsetError,
)

type ToolName = Literal["read", "write", "edit", "bash", "find", "grep"]
type PermissionName = Literal["read", "write", "execute"]
MIN_COPY_MOVE_ARGS = 2
SHELL_TIMEOUT_EXIT_CODE = 124
SHELL_LIMIT_EXIT_CODE = 125


class ToolError(Exception):
    """Base error for tool execution failures."""

    @classmethod
    def file_missing(cls, path: Path) -> ToolError:
        """Create file-not-found error."""
        message = f"File does not exist: {path}"
        return cls(message)

    @classmethod
    def base_path_missing(cls, path: Path) -> ToolError:
        """Create base-path-not-found error."""
        message = f"Base path does not exist: {path}"
        return cls(message)

    @classmethod
    def old_text_not_found(cls) -> ToolError:
        """Create edit mismatch error."""
        message = "`old_text` was not found in file."
        return cls(message)

    @classmethod
    def missing_or_invalid_argument(cls, key: str) -> ToolError:
        """Create required argument error."""
        message = f"Missing or invalid required argument: {key}"
        return cls(message)

    @classmethod
    def invalid_string_argument(cls, key: str) -> ToolError:
        """Create invalid string argument error."""
        message = f"Invalid string argument: {key}"
        return cls(message)

    @classmethod
    def unknown_tool(cls, name: str) -> ToolError:
        """Create unknown-tool error."""
        message = f"Unknown tool: {name}"
        return UnknownToolError(message)

    @classmethod
    def invalid_bash_command(cls, details: str) -> ToolError:
        """Create invalid-bash-command error."""
        message = f"Invalid bash command: {details}"
        return cls(message)

    @classmethod
    def invalid_shell_arguments(cls, details: str) -> ToolError:
        """Create invalid-shell-arguments error."""
        message = f"Invalid shell arguments: {details}"
        return cls(message)


class UnknownToolError(ToolError):
    """Raised when a tool name is not handled by built-in tools."""


class ToolPermissionError(ToolError):
    """Raised when sandbox policy blocks a tool call."""

    @classmethod
    def read_disabled(cls) -> ToolPermissionError:
        """Create read-disabled error."""
        message = "Read operations are disabled by policy."
        return cls(message)

    @classmethod
    def write_disabled(cls) -> ToolPermissionError:
        """Create write-disabled error."""
        message = "Write operations are disabled by policy."
        return cls(message)

    @classmethod
    def execute_disabled(cls) -> ToolPermissionError:
        """Create execute-disabled error."""
        message = "Command execution is disabled by policy."
        return cls(message)

    @classmethod
    def path_not_allowed(cls, path: Path) -> ToolPermissionError:
        """Create path-denied error."""
        message = f"Path not allowed by policy: {path}"
        return cls(message)


@dataclass(slots=True, frozen=True)
class ToolPermissionPolicy:
    """Read/write/execute permission policy for tool operations."""

    allow_read: bool = True
    allow_write: bool = True
    allow_execute: bool = True

    @classmethod
    def allow_all(cls) -> ToolPermissionPolicy:
        """Create policy allowing all operations."""
        return cls()

    @classmethod
    def deny_all(cls) -> ToolPermissionPolicy:
        """Create policy denying all operations."""
        return cls(allow_read=False, allow_write=False, allow_execute=False)

    def is_allowed(self, permission: PermissionName) -> bool:
        """Return whether a permission is enabled."""
        match permission:
            case "read":
                return self.allow_read
            case "write":
                return self.allow_write
            case "execute":
                return self.allow_execute

    def ensure_allowed(self, permission: PermissionName) -> None:
        """Raise if requested permission is denied."""
        if self.is_allowed(permission):
            return
        match permission:
            case "read":
                raise ToolPermissionError.read_disabled()
            case "write":
                raise ToolPermissionError.write_disabled()
            case "execute":
                raise ToolPermissionError.execute_disabled()


@dataclass(slots=True, frozen=True)
class BashResult:
    """Result from the `bash` tool."""

    stdout: str
    stderr: str
    exit_code: int


@dataclass(slots=True, frozen=True)
class BashExecutionLimits:
    """Runtime safety limits for shell-subset command execution."""

    max_execution_seconds: float = 10.0
    max_output_bytes: int = 262_144
    max_pipelines: int = 8
    max_commands: int = 32


@dataclass(slots=True, frozen=True)
class ToolSandboxPolicy:
    """Permission policy for built-in tools."""

    allowed_roots: tuple[Path, ...]
    allow_read: bool = True
    allow_write: bool = True
    allow_execute: bool = True

    @classmethod
    def from_cwd(cls, cwd: Path) -> ToolSandboxPolicy:
        """Create policy allowing only paths under `cwd`."""
        return cls(allowed_roots=(cwd.resolve(),))

    @property
    def permissions(self) -> ToolPermissionPolicy:
        """Expose read/write/execute policy as a first-class object."""
        return ToolPermissionPolicy(
            allow_read=self.allow_read,
            allow_write=self.allow_write,
            allow_execute=self.allow_execute,
        )

    def ensure_read_allowed(self, path: Path) -> None:
        """Ensure read access is allowed for path."""
        self.permissions.ensure_allowed("read")
        self._ensure_path_allowed(path)

    def ensure_write_allowed(self, path: Path) -> None:
        """Ensure write access is allowed for path."""
        self.permissions.ensure_allowed("write")
        self._ensure_path_allowed(path)

    def ensure_execute_allowed(self) -> None:
        """Ensure process execution is allowed."""
        self.permissions.ensure_allowed("execute")

    def _ensure_path_allowed(self, path: Path) -> None:
        resolved = path.resolve()
        for root in self.allowed_roots:
            if _is_within_root(resolved, root):
                return
        raise ToolPermissionError.path_not_allowed(resolved)


@dataclass(slots=True)
class GrepMatch:
    """Single grep match in a text file."""

    path: str
    line_number: int
    line: str


class BuiltinToolExecutor:
    """Executor for built-in coding-agent tools."""

    def __init__(
        self,
        *,
        cwd: Path,
        policy: ToolSandboxPolicy | None = None,
        bash_limits: BashExecutionLimits | None = None,
        shell_registry: ShellCommandRegistry | None = None,
    ) -> None:
        self._cwd = cwd.resolve()
        self._policy = policy or ToolSandboxPolicy.from_cwd(self._cwd)
        self._bash_limits = bash_limits or BashExecutionLimits()
        self._shell_registry = shell_registry or self._build_default_shell_registry()

    def execute(self, tool_name: str, arguments: dict[str, object]) -> object:
        """Execute a tool by name."""
        name = _normalize_tool_name(tool_name)
        match name:
            case "read":
                return self.read(_required_str(arguments, "path"))
            case "write":
                return self.write(
                    _required_str(arguments, "path"),
                    _required_str(arguments, "content"),
                )
            case "edit":
                return self.edit(
                    _required_str(arguments, "path"),
                    _required_str(arguments, "old_text"),
                    _required_str(arguments, "new_text"),
                )
            case "bash":
                return self.bash(_required_str(arguments, "command"))
            case "find":
                pattern = _optional_str(arguments, "pattern", "*")
                base_path = _optional_str(arguments, "base_path", ".")
                return self.find(pattern=pattern, base_path=base_path)
            case "grep":
                pattern = _required_str(arguments, "pattern")
                base_path = _optional_str(arguments, "base_path", ".")
                return self.grep(pattern=pattern, base_path=base_path)

    def read(self, path: str) -> str:
        """Read UTF-8 text from a file."""
        target = self._resolve_user_path(path)
        self._policy.ensure_read_allowed(target)
        if not target.is_file():
            raise ToolError.file_missing(target)
        return target.read_text(encoding="utf-8")

    def write(self, path: str, content: str) -> dict[str, object]:
        """Write UTF-8 text to a file."""
        target = self._resolve_user_path(path)
        self._policy.ensure_write_allowed(target)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        encoded = content.encode("utf-8")
        return {
            "path": str(target),
            "bytes_written": len(encoded),
        }

    def edit(self, path: str, old_text: str, new_text: str) -> dict[str, object]:
        """Replace exact text in a UTF-8 file."""
        target = self._resolve_user_path(path)
        self._policy.ensure_read_allowed(target)
        self._policy.ensure_write_allowed(target)
        original = self.read(path)
        if old_text not in original:
            raise ToolError.old_text_not_found()
        updated = original.replace(old_text, new_text, 1)
        target.write_text(updated, encoding="utf-8")
        return {"path": str(target), "replacements": 1}

    def bash(self, command: str) -> BashResult:
        """Execute shell-subset command in cwd without invoking full shell parsing."""
        self._policy.ensure_execute_allowed()
        try:
            program = parse_shell_command(command, glob_cwd=self._cwd)
        except (ShellParseError, ShellSubsetError) as exc:
            raise ToolError.invalid_bash_command(str(exc)) from exc
        cancellation = ShellCancellationToken.create()
        completed = self._execute_shell_program(
            program,
            cancellation=cancellation,
            limits=self._bash_limits,
        )
        return BashResult(
            stdout=completed.stdout,
            stderr=completed.stderr,
            exit_code=completed.exit_code,
        )

    def find(self, *, pattern: str, base_path: str = ".") -> list[str]:
        """Find files matching glob `pattern` under base path."""
        base = self._resolve_user_path(base_path)
        self._policy.ensure_read_allowed(base)
        if not base.exists():
            raise ToolError.base_path_missing(base)
        matches: list[str] = []
        for candidate in base.rglob("*"):
            if not candidate.is_file():
                continue
            if fnmatch.fnmatch(candidate.name, pattern):
                matches.append(str(candidate))
        return sorted(matches)

    def grep(self, *, pattern: str, base_path: str = ".") -> list[GrepMatch]:
        """Search for text in files under base path."""
        base = self._resolve_user_path(base_path)
        self._policy.ensure_read_allowed(base)
        if not base.exists():
            raise ToolError.base_path_missing(base)
        results: list[GrepMatch] = []
        for candidate in base.rglob("*"):
            if not candidate.is_file():
                continue
            if not self._is_text_file(candidate):
                continue
            try:
                text = candidate.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                continue
            for index, line in enumerate(text.splitlines(), start=1):
                if pattern in line:
                    results.append(
                        GrepMatch(
                            path=str(candidate),
                            line_number=index,
                            line=line,
                        )
                    )
        return results

    def _resolve_user_path(self, path: str, *, cwd: Path | None = None) -> Path:
        base_cwd = self._cwd if cwd is None else cwd
        candidate = Path(path)
        if candidate.is_absolute():
            return candidate.resolve()
        return (base_cwd / candidate).resolve()

    def _execute_shell_program(
        self,
        program: ShellProgram,
        *,
        cancellation: ShellCancellationToken,
        limits: BashExecutionLimits,
    ) -> ShellCommandResult:
        stdout_chunks: list[str] = []
        stderr_chunks: list[str] = []
        last_exit_code = 0
        runtime_cwd = self._cwd
        budget = _ShellExecutionBudget(limits=limits, started_at=monotonic())
        try:
            for pipeline_index, step in enumerate(program.steps):
                if not _should_run_pipeline(step.condition, last_exit_code):
                    continue
                budget.ensure_time_remaining()
                budget.note_pipeline()
                result = self._execute_pipeline(
                    step.pipeline,
                    pipeline_index=pipeline_index,
                    cancellation=cancellation,
                    cwd=runtime_cwd,
                    budget=budget,
                )
                if result.stdout:
                    stdout_chunks.append(result.stdout)
                if result.stderr:
                    stderr_chunks.append(result.stderr)
                last_exit_code = result.exit_code
                if result.next_cwd is not None:
                    runtime_cwd = result.next_cwd
        except _ShellExecutionLimitError as exc:
            stderr_chunks.append(f"{exc.message}\n")
            return ShellCommandResult(
                stdout="".join(stdout_chunks),
                stderr="".join(stderr_chunks),
                exit_code=exc.exit_code,
                next_cwd=runtime_cwd,
            )
        return ShellCommandResult(
            stdout="".join(stdout_chunks),
            stderr="".join(stderr_chunks),
            exit_code=last_exit_code,
            next_cwd=runtime_cwd,
        )

    def _execute_pipeline(
        self,
        pipeline: ShellPipeline,
        *,
        pipeline_index: int,
        cancellation: ShellCancellationToken,
        cwd: Path,
        budget: _ShellExecutionBudget,
    ) -> ShellCommandResult:
        pipeline_input = ""
        pipeline_stderr: list[str] = []
        last_result = ShellCommandResult()
        runtime_cwd = cwd
        for command_index, command in enumerate(pipeline.commands):
            cancellation.ensure_active()
            budget.ensure_time_remaining()
            budget.note_command()
            command_text = _render_command_text(command)
            emit_shell_event(
                None,
                ShellExecutionEvent(
                    kind="command_start",
                    pipeline_index=pipeline_index,
                    command_index=command_index,
                    text=command_text,
                ),
            )
            result = self._execute_simple_command(
                command,
                stdin=pipeline_input,
                cancellation=cancellation,
                metadata=_CommandExecutionMeta(
                    pipeline_index=pipeline_index,
                    command_index=command_index,
                    cwd=runtime_cwd,
                ),
                budget=budget,
            )
            budget.note_output(result.stdout)
            budget.note_output(result.stderr)
            if result.stderr:
                pipeline_stderr.append(result.stderr)
            if result.exit_code != 0:
                last_result = result
                break
            if result.next_cwd is not None:
                runtime_cwd = result.next_cwd
            if command_index < len(pipeline.commands) - 1:
                if pipeline.pipe_stderr:
                    pipeline_input = result.stdout + result.stderr
                else:
                    pipeline_input = result.stdout
            last_result = result
        merged_stderr = "".join(pipeline_stderr)
        if last_result.exit_code != 0:
            return ShellCommandResult(
                stdout="",
                stderr=merged_stderr,
                exit_code=last_result.exit_code,
                next_cwd=runtime_cwd,
            )
        return ShellCommandResult(
            stdout=last_result.stdout,
            stderr=merged_stderr,
            exit_code=last_result.exit_code,
            next_cwd=runtime_cwd,
        )

    def _execute_simple_command(
        self,
        command: ShellSimpleCommand,
        *,
        stdin: str,
        cancellation: ShellCancellationToken,
        metadata: _CommandExecutionMeta,
        budget: _ShellExecutionBudget,
    ) -> ShellCommandResult:
        command_input, output_redirects = self._prepare_redirections(
            command.redirections,
            stdin=stdin,
            cwd=metadata.cwd,
        )
        result = self._run_command_handler(
            command,
            stdin=command_input,
            cancellation=cancellation,
            cwd=metadata.cwd,
            budget=budget,
        )
        visible_result = self._apply_output_redirections(
            output_redirects,
            result=result,
            cwd=metadata.cwd,
        )
        if visible_result.stdout:
            emit_shell_event(
                None,
                ShellExecutionEvent(
                    kind="stdout",
                    pipeline_index=metadata.pipeline_index,
                    command_index=metadata.command_index,
                    text=visible_result.stdout,
                ),
            )
        if visible_result.stderr:
            emit_shell_event(
                None,
                ShellExecutionEvent(
                    kind="stderr",
                    pipeline_index=metadata.pipeline_index,
                    command_index=metadata.command_index,
                    text=visible_result.stderr,
                ),
            )
        emit_shell_event(
            None,
            ShellExecutionEvent(
                kind="command_end",
                pipeline_index=metadata.pipeline_index,
                command_index=metadata.command_index,
                exit_code=visible_result.exit_code,
            ),
        )
        return visible_result

    def _prepare_redirections(
        self,
        redirections: tuple[ShellRedirection, ...],
        *,
        stdin: str,
        cwd: Path,
    ) -> tuple[str, tuple[ShellRedirection, ...]]:
        command_input = stdin
        output_redirects: list[ShellRedirection] = []
        for redirection in redirections:
            target = self._resolve_user_path(redirection.target, cwd=cwd)
            match redirection.operator:
                case "<":
                    self._policy.ensure_read_allowed(target)
                    if not target.is_file():
                        raise ToolError.file_missing(target)
                    command_input = target.read_text(encoding="utf-8")
                case ">" | ">>":
                    self._policy.ensure_write_allowed(target)
                    output_redirects.append(redirection)
        return (command_input, tuple(output_redirects))

    def _apply_output_redirections(
        self,
        redirections: tuple[ShellRedirection, ...],
        *,
        result: ShellCommandResult,
        cwd: Path,
    ) -> ShellCommandResult:
        redirected_stdout = result.stdout
        for redirection in redirections:
            target = self._resolve_user_path(redirection.target, cwd=cwd)
            target.parent.mkdir(parents=True, exist_ok=True)
            if redirection.operator == ">>":
                with target.open("a", encoding="utf-8") as handle:
                    handle.write(result.stdout)
            else:
                target.write_text(result.stdout, encoding="utf-8")
            redirected_stdout = ""
        return ShellCommandResult(
            stdout=redirected_stdout,
            stderr=result.stderr,
            exit_code=result.exit_code,
            next_cwd=result.next_cwd,
        )

    def _run_command_handler(
        self,
        command: ShellSimpleCommand,
        *,
        stdin: str,
        cancellation: ShellCancellationToken,
        cwd: Path,
        budget: _ShellExecutionBudget,
    ) -> ShellCommandResult:
        context = ShellCommandContext(cwd=cwd, stdin=stdin)
        try:
            handler = self._shell_registry.resolve(command.program)
        except ShellRegistryError:
            return self._run_external_command(
                command,
                context=context,
                budget=budget,
            )
        return handler(
            context=context,
            arguments=command.arguments,
            cancellation=cancellation,
            event_sink=None,
        )

    def _run_external_command(
        self,
        command: ShellSimpleCommand,
        *,
        context: ShellCommandContext,
        budget: _ShellExecutionBudget,
    ) -> ShellCommandResult:
        argv = [command.program, *command.arguments]
        env = _merge_command_environment(command.env_assignments)
        timeout_seconds = budget.remaining_seconds()
        if timeout_seconds <= 0:
            raise _ShellExecutionLimitError.timeout_exceeded()
        try:
            completed = subprocess.run(  # noqa: S603
                argv,
                capture_output=True,
                text=True,
                check=False,
                cwd=context.cwd,
                input=context.stdin,
                env=env,
                timeout=timeout_seconds,
            )
        except FileNotFoundError:
            message = f"Command not found: {command.program}\n"
            return ShellCommandResult(stdout="", stderr=message, exit_code=127)
        except subprocess.TimeoutExpired as exc:
            raise _ShellExecutionLimitError.timeout_exceeded() from exc
        return ShellCommandResult(
            stdout=completed.stdout,
            stderr=completed.stderr,
            exit_code=completed.returncode,
        )

    def _build_default_shell_registry(self) -> ShellCommandRegistry:
        registry = ShellCommandRegistry()
        registry.register("echo", self._cmd_echo)
        registry.register("pwd", self._cmd_pwd)
        registry.register("cd", self._cmd_cd)
        registry.register("ls", self._cmd_ls)
        registry.register("dir", self._cmd_ls)
        registry.register("cat", self._cmd_cat)
        registry.register("head", self._cmd_head)
        registry.register("tail", self._cmd_tail)
        registry.register("mkdir", self._cmd_mkdir)
        registry.register("cp", self._cmd_cp)
        registry.register("mv", self._cmd_mv)
        registry.register("grep", self._cmd_grep)
        return registry

    def _cmd_echo(
        self,
        *,
        context: ShellCommandContext,
        arguments: tuple[str, ...],
        cancellation: ShellCancellationToken,
        event_sink: object | None,
    ) -> ShellCommandResult:
        _ = context
        _ = event_sink
        cancellation.ensure_active()
        output = f"{' '.join(arguments)}\n" if arguments else "\n"
        return ShellCommandResult(stdout=output, stderr="", exit_code=0)

    def _cmd_pwd(
        self,
        *,
        context: ShellCommandContext,
        arguments: tuple[str, ...],
        cancellation: ShellCancellationToken,
        event_sink: object | None,
    ) -> ShellCommandResult:
        _ = event_sink
        cancellation.ensure_active()
        if arguments:
            return _command_usage_error("pwd does not accept positional arguments.")
        return ShellCommandResult(stdout=f"{context.cwd}\n")

    def _cmd_cd(
        self,
        *,
        context: ShellCommandContext,
        arguments: tuple[str, ...],
        cancellation: ShellCancellationToken,
        event_sink: object | None,
    ) -> ShellCommandResult:
        _ = event_sink
        cancellation.ensure_active()
        if len(arguments) > 1:
            return _command_usage_error("cd accepts at most one path.")
        target = (
            context.cwd
            if not arguments
            else self._resolve_user_path(arguments[0], cwd=context.cwd)
        )
        self._policy.ensure_read_allowed(target)
        if not target.is_dir():
            return _command_usage_error(f"cd target is not a directory: {target}")
        return ShellCommandResult(next_cwd=target.resolve())

    def _cmd_ls(
        self,
        *,
        context: ShellCommandContext,
        arguments: tuple[str, ...],
        cancellation: ShellCancellationToken,
        event_sink: object | None,
    ) -> ShellCommandResult:
        _ = event_sink
        cancellation.ensure_active()
        try:
            parsed = ShellArgParser(
                allowed_flags=frozenset({"-a", "--all"})
            ).parse(arguments)
        except ShellArgsError as exc:
            raise ToolError.invalid_shell_arguments(str(exc)) from exc
        include_hidden = parsed.has_flag("-a") or parsed.has_flag("--all")
        targets = parsed.positionals or (".",)
        lines: list[str] = []
        for raw_target in targets:
            target = self._resolve_user_path(raw_target, cwd=context.cwd)
            self._policy.ensure_read_allowed(target)
            if not target.exists():
                return _command_usage_error(f"Path does not exist: {target}")
            if target.is_file():
                lines.append(target.name)
                continue
            entries = sorted(target.iterdir(), key=lambda item: item.name.lower())
            for entry in entries:
                if not include_hidden and entry.name.startswith("."):
                    continue
                label = f"{entry.name}/" if entry.is_dir() else entry.name
                lines.append(label)
        output = "\n".join(lines)
        if output:
            output += "\n"
        return ShellCommandResult(stdout=output)

    def _cmd_cat(
        self,
        *,
        context: ShellCommandContext,
        arguments: tuple[str, ...],
        cancellation: ShellCancellationToken,
        event_sink: object | None,
    ) -> ShellCommandResult:
        _ = event_sink
        cancellation.ensure_active()
        if not arguments:
            return ShellCommandResult(stdout=context.stdin)
        chunks: list[str] = []
        for raw_path in arguments:
            target = self._resolve_user_path(raw_path, cwd=context.cwd)
            self._policy.ensure_read_allowed(target)
            if not target.is_file():
                return _command_usage_error(f"cat target is not a file: {target}")
            chunks.append(target.read_text(encoding="utf-8"))
        return ShellCommandResult(stdout="".join(chunks))

    def _cmd_head(
        self,
        *,
        context: ShellCommandContext,
        arguments: tuple[str, ...],
        cancellation: ShellCancellationToken,
        event_sink: object | None,
    ) -> ShellCommandResult:
        _ = event_sink
        cancellation.ensure_active()
        parsed = _parse_line_count_args(arguments)
        text = self._load_text_for_stream_command(
            context=context,
            files=parsed.positionals,
        )
        lines = text.splitlines()
        output = "\n".join(lines[: parsed.count])
        if output:
            output += "\n"
        return ShellCommandResult(stdout=output)

    def _cmd_tail(
        self,
        *,
        context: ShellCommandContext,
        arguments: tuple[str, ...],
        cancellation: ShellCancellationToken,
        event_sink: object | None,
    ) -> ShellCommandResult:
        _ = event_sink
        cancellation.ensure_active()
        parsed = _parse_line_count_args(arguments)
        text = self._load_text_for_stream_command(
            context=context,
            files=parsed.positionals,
        )
        lines = text.splitlines()
        output = "\n".join(lines[-parsed.count :])
        if output:
            output += "\n"
        return ShellCommandResult(stdout=output)

    def _cmd_mkdir(
        self,
        *,
        context: ShellCommandContext,
        arguments: tuple[str, ...],
        cancellation: ShellCancellationToken,
        event_sink: object | None,
    ) -> ShellCommandResult:
        _ = event_sink
        cancellation.ensure_active()
        try:
            parsed = ShellArgParser(allowed_flags=frozenset({"-p"})).parse(arguments)
        except ShellArgsError as exc:
            raise ToolError.invalid_shell_arguments(str(exc)) from exc
        if not parsed.positionals:
            return _command_usage_error("mkdir requires at least one path.")
        allow_parents = parsed.has_flag("-p")
        for raw_path in parsed.positionals:
            target = self._resolve_user_path(raw_path, cwd=context.cwd)
            self._policy.ensure_write_allowed(target)
            target.mkdir(parents=allow_parents, exist_ok=allow_parents)
        return ShellCommandResult()

    def _cmd_cp(
        self,
        *,
        context: ShellCommandContext,
        arguments: tuple[str, ...],
        cancellation: ShellCancellationToken,
        event_sink: object | None,
    ) -> ShellCommandResult:
        _ = event_sink
        cancellation.ensure_active()
        if len(arguments) < MIN_COPY_MOVE_ARGS:
            return _command_usage_error("cp requires source and destination.")
        source_values = arguments[:-1]
        destination = self._resolve_user_path(arguments[-1], cwd=context.cwd)
        sources = tuple(
            self._resolve_user_path(value, cwd=context.cwd)
            for value in source_values
        )
        for source in sources:
            self._policy.ensure_read_allowed(source)
            if not source.exists():
                return _command_usage_error(f"cp source does not exist: {source}")
        if len(sources) > 1:
            self._policy.ensure_write_allowed(destination)
            if not destination.is_dir():
                message = "cp destination must be a directory for multiple sources."
                return _command_usage_error(message)
            for source in sources:
                target = destination / source.name
                self._policy.ensure_write_allowed(target)
                _copy_path(source, target)
            return ShellCommandResult()
        source = next(iter(sources))
        self._policy.ensure_write_allowed(destination)
        _copy_path(source, destination)
        return ShellCommandResult()

    def _cmd_mv(
        self,
        *,
        context: ShellCommandContext,
        arguments: tuple[str, ...],
        cancellation: ShellCancellationToken,
        event_sink: object | None,
    ) -> ShellCommandResult:
        _ = event_sink
        cancellation.ensure_active()
        if len(arguments) < MIN_COPY_MOVE_ARGS:
            return _command_usage_error("mv requires source and destination.")
        source_values = arguments[:-1]
        destination = self._resolve_user_path(arguments[-1], cwd=context.cwd)
        sources = tuple(
            self._resolve_user_path(value, cwd=context.cwd)
            for value in source_values
        )
        for source in sources:
            self._policy.ensure_read_allowed(source)
            if not source.exists():
                return _command_usage_error(f"mv source does not exist: {source}")
        if len(sources) > 1:
            self._policy.ensure_write_allowed(destination)
            if not destination.is_dir():
                message = "mv destination must be a directory for multiple sources."
                return _command_usage_error(message)
            for source in sources:
                target = destination / source.name
                self._policy.ensure_write_allowed(target)
                shutil.move(str(source), str(target))
            return ShellCommandResult()
        source = next(iter(sources))
        self._policy.ensure_write_allowed(destination)
        shutil.move(str(source), str(destination))
        return ShellCommandResult()

    def _cmd_grep(
        self,
        *,
        context: ShellCommandContext,
        arguments: tuple[str, ...],
        cancellation: ShellCancellationToken,
        event_sink: object | None,
    ) -> ShellCommandResult:
        _ = event_sink
        cancellation.ensure_active()
        if not arguments:
            return _command_usage_error("grep requires a search pattern.")
        pattern = arguments[0]
        files = arguments[1:]
        if not files:
            output = "\n".join(
                line for line in context.stdin.splitlines() if pattern in line
            )
            if output:
                output += "\n"
            return ShellCommandResult(stdout=output)
        matches: list[str] = []
        for raw_path in files:
            target = self._resolve_user_path(raw_path, cwd=context.cwd)
            self._policy.ensure_read_allowed(target)
            if not target.is_file():
                return _command_usage_error(f"grep target is not a file: {target}")
            text = target.read_text(encoding="utf-8")
            for index, line in enumerate(text.splitlines(), start=1):
                if pattern in line:
                    matches.append(f"{target}:{index}:{line}")
        output = "\n".join(matches)
        if output:
            output += "\n"
        return ShellCommandResult(stdout=output)

    def _load_text_for_stream_command(
        self,
        *,
        context: ShellCommandContext,
        files: tuple[str, ...],
    ) -> str:
        if not files:
            return context.stdin
        chunks: list[str] = []
        for raw_path in files:
            target = self._resolve_user_path(raw_path, cwd=context.cwd)
            self._policy.ensure_read_allowed(target)
            if not target.is_file():
                message = f"Expected file path, got: {target}"
                raise ToolError.invalid_shell_arguments(message)
            chunks.append(target.read_text(encoding="utf-8"))
        return "".join(chunks)

    @staticmethod
    def _is_text_file(path: Path) -> bool:
        binary_extensions = {
            ".png",
            ".jpg",
            ".jpeg",
            ".gif",
            ".webp",
            ".bmp",
            ".pdf",
        }
        return path.suffix.lower() not in binary_extensions


def _required_str(values: dict[str, object], key: str) -> str:
    value = values.get(key)
    if isinstance(value, str):
        return value
    raise ToolError.missing_or_invalid_argument(key)


def _optional_str(values: dict[str, object], key: str, default: str) -> str:
    value = values.get(key)
    if value is None:
        return default
    if isinstance(value, str):
        return value
    raise ToolError.invalid_string_argument(key)


def _normalize_tool_name(value: str) -> ToolName:
    match value:
        case "read" | "write" | "edit" | "bash" | "find" | "grep":
            return value
        case _:
            raise ToolError.unknown_tool(value)


def _merge_command_environment(
    assignments: tuple[ShellEnvAssignment, ...],
) -> dict[str, str]:
    env = dict(os.environ)
    for assignment in assignments:
        env[assignment.name] = assignment.value
    return env


def _render_command_text(command: ShellSimpleCommand) -> str:
    parts: list[str] = [command.program, *command.arguments]
    return " ".join(parts)


def _should_run_pipeline(condition: PipelineCondition, last_exit_code: int) -> bool:
    match condition:
        case "always":
            return True
        case "on_success":
            return last_exit_code == 0
        case "on_failure":
            return last_exit_code != 0


def _command_usage_error(message: str) -> ShellCommandResult:
    return ShellCommandResult(stdout="", stderr=f"{message}\n", exit_code=2)


@dataclass(slots=True, frozen=True)
class _LineCountArgs:
    count: int
    positionals: tuple[str, ...]


@dataclass(slots=True, frozen=True)
class _CommandExecutionMeta:
    pipeline_index: int
    command_index: int
    cwd: Path


@dataclass(slots=True)
class _ShellExecutionBudget:
    limits: BashExecutionLimits
    started_at: float
    pipeline_count: int = 0
    command_count: int = 0
    output_bytes: int = 0

    def elapsed_seconds(self) -> float:
        return monotonic() - self.started_at

    def remaining_seconds(self) -> float:
        return self.limits.max_execution_seconds - self.elapsed_seconds()

    def ensure_time_remaining(self) -> None:
        if self.remaining_seconds() <= 0:
            raise _ShellExecutionLimitError.timeout_exceeded()

    def note_pipeline(self) -> None:
        self.pipeline_count += 1
        if self.pipeline_count > self.limits.max_pipelines:
            raise _ShellExecutionLimitError.pipeline_limit_exceeded(
                self.limits.max_pipelines
            )

    def note_command(self) -> None:
        self.command_count += 1
        if self.command_count > self.limits.max_commands:
            raise _ShellExecutionLimitError.command_limit_exceeded(
                self.limits.max_commands
            )

    def note_output(self, text: str) -> None:
        if not text:
            return
        self.output_bytes += len(text.encode("utf-8"))
        if self.output_bytes > self.limits.max_output_bytes:
            raise _ShellExecutionLimitError.output_limit_exceeded(
                self.limits.max_output_bytes
            )


@dataclass(slots=True, frozen=True)
class _ShellExecutionLimitError(Exception):
    message: str
    exit_code: int

    @classmethod
    def timeout_exceeded(cls) -> _ShellExecutionLimitError:
        return cls(
            message="Shell execution timed out before completion.",
            exit_code=SHELL_TIMEOUT_EXIT_CODE,
        )

    @classmethod
    def output_limit_exceeded(cls, max_output_bytes: int) -> _ShellExecutionLimitError:
        message = f"Shell output exceeded limit ({max_output_bytes} bytes)."
        return cls(message=message, exit_code=SHELL_LIMIT_EXIT_CODE)

    @classmethod
    def pipeline_limit_exceeded(cls, max_pipelines: int) -> _ShellExecutionLimitError:
        message = f"Shell pipeline limit exceeded ({max_pipelines})."
        return cls(message=message, exit_code=SHELL_LIMIT_EXIT_CODE)

    @classmethod
    def command_limit_exceeded(cls, max_commands: int) -> _ShellExecutionLimitError:
        message = f"Shell command limit exceeded ({max_commands})."
        return cls(message=message, exit_code=SHELL_LIMIT_EXIT_CODE)


def _parse_line_count_args(arguments: tuple[str, ...]) -> _LineCountArgs:
    try:
        parsed = ShellArgParser(
            value_options=frozenset({"-n", "--lines"}),
        ).parse(arguments)
    except ShellArgsError as exc:
        raise ToolError.invalid_shell_arguments(str(exc)) from exc
    raw_count = parsed.get_value("-n", parsed.get_value("--lines", "10"))
    assert raw_count is not None
    try:
        count = int(raw_count)
    except ValueError as exc:
        message = f"Invalid integer for line count: {raw_count}"
        raise ToolError.invalid_shell_arguments(message) from exc
    if count < 0:
        message = "Line count cannot be negative."
        raise ToolError.invalid_shell_arguments(message)
    return _LineCountArgs(count=count, positionals=parsed.positionals)


def _copy_path(source: Path, destination: Path) -> None:
    if source.is_dir():
        shutil.copytree(source, destination, dirs_exist_ok=True)
        return
    if destination.is_dir():
        target = destination / source.name
        shutil.copy2(source, target)
        return
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)


def _is_within_root(path: Path, root: Path) -> bool:
    resolved_root = root.resolve()
    if path == resolved_root:
        return True
    return resolved_root in path.parents
