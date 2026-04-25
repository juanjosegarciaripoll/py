"""Built-in tool execution with simple sandbox policies."""

from __future__ import annotations

import fnmatch
import os
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

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
    ShellEnvAssignment,
    ShellPipeline,
    ShellProgram,
    ShellRedirection,
    ShellSimpleCommand,
    ShellSubsetError,
)

type ToolName = Literal["read", "write", "edit", "bash", "find", "grep"]
type PermissionName = Literal["read", "write", "execute"]


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
        shell_registry: ShellCommandRegistry | None = None,
    ) -> None:
        self._cwd = cwd.resolve()
        self._policy = policy or ToolSandboxPolicy.from_cwd(self._cwd)
        self._shell_registry = shell_registry or _default_shell_registry()

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
            program = parse_shell_command(command)
        except (ShellParseError, ShellSubsetError) as exc:
            raise ToolError.invalid_bash_command(str(exc)) from exc
        cancellation = ShellCancellationToken.create()
        completed = self._execute_shell_program(program, cancellation=cancellation)
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

    def _resolve_user_path(self, path: str) -> Path:
        candidate = Path(path)
        if candidate.is_absolute():
            return candidate.resolve()
        return (self._cwd / candidate).resolve()

    def _execute_shell_program(
        self,
        program: ShellProgram,
        *,
        cancellation: ShellCancellationToken,
    ) -> ShellCommandResult:
        stdout_chunks: list[str] = []
        stderr_chunks: list[str] = []
        last_exit_code = 0
        pipelines = getattr(program, "pipelines", ())
        for pipeline_index, pipeline in enumerate(pipelines):
            result = self._execute_pipeline(
                pipeline,
                pipeline_index=pipeline_index,
                cancellation=cancellation,
            )
            if result.stdout:
                stdout_chunks.append(result.stdout)
            if result.stderr:
                stderr_chunks.append(result.stderr)
            last_exit_code = result.exit_code
            if last_exit_code != 0:
                break
        return ShellCommandResult(
            stdout="".join(stdout_chunks),
            stderr="".join(stderr_chunks),
            exit_code=last_exit_code,
        )

    def _execute_pipeline(
        self,
        pipeline: ShellPipeline,
        *,
        pipeline_index: int,
        cancellation: ShellCancellationToken,
    ) -> ShellCommandResult:
        pipeline_input = ""
        pipeline_stderr: list[str] = []
        last_result = ShellCommandResult()
        for command_index, command in enumerate(pipeline.commands):
            cancellation.ensure_active()
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
                pipeline_index=pipeline_index,
                command_index=command_index,
            )
            if result.stderr:
                pipeline_stderr.append(result.stderr)
            if result.exit_code != 0:
                last_result = result
                break
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
            )
        return ShellCommandResult(
            stdout=last_result.stdout,
            stderr=merged_stderr,
            exit_code=last_result.exit_code,
        )

    def _execute_simple_command(
        self,
        command: ShellSimpleCommand,
        *,
        stdin: str,
        cancellation: ShellCancellationToken,
        pipeline_index: int,
        command_index: int,
    ) -> ShellCommandResult:
        command_input, output_redirects = self._prepare_redirections(
            command.redirections,
            stdin=stdin,
        )
        result = self._run_command_handler(
            command,
            stdin=command_input,
            cancellation=cancellation,
        )
        visible_result = self._apply_output_redirections(
            output_redirects,
            stdout=result.stdout,
            stderr=result.stderr,
            exit_code=result.exit_code,
        )
        if visible_result.stdout:
            emit_shell_event(
                None,
                ShellExecutionEvent(
                    kind="stdout",
                    pipeline_index=pipeline_index,
                    command_index=command_index,
                    text=visible_result.stdout,
                ),
            )
        if visible_result.stderr:
            emit_shell_event(
                None,
                ShellExecutionEvent(
                    kind="stderr",
                    pipeline_index=pipeline_index,
                    command_index=command_index,
                    text=visible_result.stderr,
                ),
            )
        emit_shell_event(
            None,
            ShellExecutionEvent(
                kind="command_end",
                pipeline_index=pipeline_index,
                command_index=command_index,
                exit_code=visible_result.exit_code,
            ),
        )
        return visible_result

    def _prepare_redirections(
        self,
        redirections: tuple[ShellRedirection, ...],
        *,
        stdin: str,
    ) -> tuple[str, tuple[ShellRedirection, ...]]:
        command_input = stdin
        output_redirects: list[ShellRedirection] = []
        for redirection in redirections:
            target = self._resolve_user_path(redirection.target)
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
        stdout: str,
        stderr: str,
        exit_code: int,
    ) -> ShellCommandResult:
        redirected_stdout = stdout
        for redirection in redirections:
            target = self._resolve_user_path(redirection.target)
            target.parent.mkdir(parents=True, exist_ok=True)
            if redirection.operator == ">>":
                with target.open("a", encoding="utf-8") as handle:
                    handle.write(stdout)
            else:
                target.write_text(stdout, encoding="utf-8")
            redirected_stdout = ""
        return ShellCommandResult(
            stdout=redirected_stdout,
            stderr=stderr,
            exit_code=exit_code,
        )

    def _run_command_handler(
        self,
        command: ShellSimpleCommand,
        *,
        stdin: str,
        cancellation: ShellCancellationToken,
    ) -> ShellCommandResult:
        context = ShellCommandContext(cwd=self._cwd, stdin=stdin)
        try:
            handler = self._shell_registry.resolve(command.program)
        except ShellRegistryError:
            return self._run_external_command(command, context=context)
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
    ) -> ShellCommandResult:
        argv = [command.program, *command.arguments]
        env = _merge_command_environment(command.env_assignments)
        try:
            completed = subprocess.run(  # noqa: S603
                argv,
                capture_output=True,
                text=True,
                check=False,
                cwd=context.cwd,
                input=context.stdin,
                env=env,
            )
        except FileNotFoundError:
            message = f"Command not found: {command.program}\n"
            return ShellCommandResult(stdout="", stderr=message, exit_code=127)
        return ShellCommandResult(
            stdout=completed.stdout,
            stderr=completed.stderr,
            exit_code=completed.returncode,
        )

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


def _default_shell_registry() -> ShellCommandRegistry:
    registry = ShellCommandRegistry()
    registry.register("echo", _echo_command_handler)
    return registry


def _echo_command_handler(
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


def _is_within_root(path: Path, root: Path) -> bool:
    resolved_root = root.resolve()
    if path == resolved_root:
        return True
    return resolved_root in path.parents
