"""Built-in tool execution with simple sandbox policies."""

from __future__ import annotations

import fnmatch
import os
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

type ToolName = Literal["read", "write", "edit", "bash", "find", "grep"]


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
        return cls(message)


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

    def ensure_read_allowed(self, path: Path) -> None:
        """Ensure read access is allowed for path."""
        if not self.allow_read:
            raise ToolPermissionError.read_disabled()
        self._ensure_path_allowed(path)

    def ensure_write_allowed(self, path: Path) -> None:
        """Ensure write access is allowed for path."""
        if not self.allow_write:
            raise ToolPermissionError.write_disabled()
        self._ensure_path_allowed(path)

    def ensure_execute_allowed(self) -> None:
        """Ensure process execution is allowed."""
        if not self.allow_execute:
            raise ToolPermissionError.execute_disabled()

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
    ) -> None:
        self._cwd = cwd.resolve()
        self._policy = policy or ToolSandboxPolicy.from_cwd(self._cwd)

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
        """Execute a shell command in cwd."""
        self._policy.ensure_execute_allowed()
        shell_command = _build_shell_command(command)
        completed = subprocess.run(  # noqa: S603
            shell_command,
            capture_output=True,
            text=True,
            check=False,
            cwd=self._cwd,
        )
        return BashResult(
            stdout=completed.stdout,
            stderr=completed.stderr,
            exit_code=completed.returncode,
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


def _build_shell_command(command: str) -> list[str]:
    if os.name == "nt":
        return ["cmd.exe", "/c", command]
    return ["/bin/sh", "-lc", command]


def _is_within_root(path: Path, root: Path) -> bool:
    resolved_root = root.resolve()
    if path == resolved_root:
        return True
    return resolved_root in path.parents
