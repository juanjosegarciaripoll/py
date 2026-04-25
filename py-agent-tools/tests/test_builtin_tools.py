"""Unit tests for built-in tools and sandbox policy."""

from __future__ import annotations

import shutil
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from py_agent_tools import (
    BuiltinToolExecutor,
    ToolPermissionError,
    ToolPermissionPolicy,
    ToolSandboxPolicy,
)

TMP_DIR = Path(__file__).resolve().parent / ".tmp"
ALPHA_MATCH_COUNT = 2


class ToolTests(unittest.TestCase):
    """Tests for read/write/edit/bash/find/grep behavior."""

    def test_read_write_edit_roundtrip(self) -> None:
        test_dir = TMP_DIR / "tools-roundtrip"
        shutil.rmtree(test_dir, ignore_errors=True)
        test_dir.mkdir(parents=True, exist_ok=True)
        try:
            tools = BuiltinToolExecutor(cwd=test_dir)
            write_result = tools.write("a.txt", "hello world")
            assert write_result["bytes_written"] == len(b"hello world")
            assert tools.read("a.txt") == "hello world"
            edit_result = tools.edit("a.txt", "world", "tools")
            assert edit_result["replacements"] == 1
            assert tools.read("a.txt") == "hello tools"
        finally:
            shutil.rmtree(test_dir, ignore_errors=True)

    def test_find_and_grep(self) -> None:
        test_dir = TMP_DIR / "tools-search"
        shutil.rmtree(test_dir, ignore_errors=True)
        test_dir.mkdir(parents=True, exist_ok=True)
        try:
            tools = BuiltinToolExecutor(cwd=test_dir)
            tools.write("src/main.py", "print('alpha')\nprint('beta')\n")
            tools.write("src/notes.txt", "alpha\n")
            found = tools.find(pattern="*.py", base_path="src")
            assert len(found) == 1
            assert found[0].endswith("main.py")

            matches = tools.grep(pattern="alpha", base_path="src")
            assert len(matches) == ALPHA_MATCH_COUNT
            assert all("alpha" in match.line for match in matches)
        finally:
            shutil.rmtree(test_dir, ignore_errors=True)

    def test_bash_blocked_when_execute_denied(self) -> None:
        test_dir = TMP_DIR / "tools-bash-denied"
        shutil.rmtree(test_dir, ignore_errors=True)
        test_dir.mkdir(parents=True, exist_ok=True)
        try:
            policy = ToolSandboxPolicy(
                allowed_roots=(test_dir.resolve(),),
                allow_execute=False,
            )
            tools = BuiltinToolExecutor(cwd=test_dir, policy=policy)
            try:
                tools.bash("echo hello")
            except ToolPermissionError:
                pass
            else:
                message = "Expected ToolPermissionError for denied bash"
                raise AssertionError(message)
        finally:
            shutil.rmtree(test_dir, ignore_errors=True)

    def test_write_denied_outside_allowed_root(self) -> None:
        test_dir = TMP_DIR / "tools-restricted"
        outside_dir = TMP_DIR / "tools-outside"
        shutil.rmtree(test_dir, ignore_errors=True)
        shutil.rmtree(outside_dir, ignore_errors=True)
        test_dir.mkdir(parents=True, exist_ok=True)
        outside_dir.mkdir(parents=True, exist_ok=True)
        try:
            policy = ToolSandboxPolicy(
                allowed_roots=(test_dir.resolve(),),
                allow_read=True,
                allow_write=True,
                allow_execute=True,
            )
            tools = BuiltinToolExecutor(cwd=outside_dir, policy=policy)
            try:
                tools.write(str(outside_dir / "blocked.txt"), "blocked")
            except ToolPermissionError:
                pass
            else:
                message = "Expected ToolPermissionError for blocked write"
                raise AssertionError(message)
        finally:
            shutil.rmtree(test_dir, ignore_errors=True)
            shutil.rmtree(outside_dir, ignore_errors=True)

    def test_execute_dispatch_and_bash(self) -> None:
        test_dir = TMP_DIR / "tools-dispatch"
        shutil.rmtree(test_dir, ignore_errors=True)
        test_dir.mkdir(parents=True, exist_ok=True)
        try:
            tools = BuiltinToolExecutor(cwd=test_dir)
            write_result = tools.execute(
                "write",
                {"path": "dispatch.txt", "content": "alpha beta"},
            )
            assert isinstance(write_result, dict)
            read_result = tools.execute("read", {"path": "dispatch.txt"})
            assert read_result == "alpha beta"

            find_result = tools.execute(
                "find",
                {"pattern": "*.txt", "base_path": "."},
            )
            assert isinstance(find_result, list)

            grep_result = tools.execute(
                "grep",
                {"pattern": "alpha", "base_path": "."},
            )
            assert isinstance(grep_result, list)
            assert grep_result

            bash_result = tools.execute("bash", {"command": "echo hello"})
            assert hasattr(bash_result, "exit_code")
        finally:
            shutil.rmtree(test_dir, ignore_errors=True)

    def test_error_paths_for_missing_items(self) -> None:
        test_dir = TMP_DIR / "tools-errors"
        shutil.rmtree(test_dir, ignore_errors=True)
        test_dir.mkdir(parents=True, exist_ok=True)
        try:
            tools = BuiltinToolExecutor(cwd=test_dir)
            missing_read_failed = False
            try:
                tools.read("missing.txt")
            except Exception:  # noqa: BLE001
                missing_read_failed = True
            else:
                message = "Expected missing file error"
                raise AssertionError(message)
            assert missing_read_failed is True

            tools.write("edit.txt", "alpha")
            missing_old_text_failed = False
            try:
                tools.edit("edit.txt", "missing", "replace")
            except Exception:  # noqa: BLE001
                missing_old_text_failed = True
            else:
                message = "Expected old_text error"
                raise AssertionError(message)
            assert missing_old_text_failed is True

            missing_base_failed = False
            try:
                tools.find(pattern="*.txt", base_path="missing-folder")
            except Exception:  # noqa: BLE001
                missing_base_failed = True
            else:
                message = "Expected missing base path error"
                raise AssertionError(message)
            assert missing_base_failed is True
        finally:
            shutil.rmtree(test_dir, ignore_errors=True)

    def test_policy_read_and_write_disabled(self) -> None:
        test_dir = TMP_DIR / "tools-disabled"
        shutil.rmtree(test_dir, ignore_errors=True)
        test_dir.mkdir(parents=True, exist_ok=True)
        try:
            read_disabled = ToolSandboxPolicy(
                allowed_roots=(test_dir.resolve(),),
                allow_read=False,
                allow_write=True,
                allow_execute=True,
            )
            tools_read = BuiltinToolExecutor(cwd=test_dir, policy=read_disabled)
            read_denied = False
            try:
                tools_read.read("any.txt")
            except ToolPermissionError:
                read_denied = True
            else:
                message = "Expected read permission error"
                raise AssertionError(message)
            assert read_denied is True

            write_disabled = ToolSandboxPolicy(
                allowed_roots=(test_dir.resolve(),),
                allow_read=True,
                allow_write=False,
                allow_execute=True,
            )
            tools_write = BuiltinToolExecutor(cwd=test_dir, policy=write_disabled)
            write_denied = False
            try:
                tools_write.write("any.txt", "x")
            except ToolPermissionError:
                write_denied = True
            else:
                message = "Expected write permission error"
                raise AssertionError(message)
            assert write_denied is True
        finally:
            shutil.rmtree(test_dir, ignore_errors=True)

    def test_execute_validation_errors(self) -> None:
        tools = BuiltinToolExecutor(cwd=TMP_DIR)

        def assert_raises_tool_error(name: str, arguments: dict[str, object]) -> None:
            failed = False
            try:
                tools.execute(name, arguments)
            except Exception:  # noqa: BLE001
                failed = True
            else:
                message = "Expected tool execution to fail"
                raise AssertionError(message)
            assert failed is True

        assert_raises_tool_error("unknown", {})
        assert_raises_tool_error("read", {})
        assert_raises_tool_error("find", {"pattern": 5})

    def test_bash_rejects_unsupported_control_operator(self) -> None:
        test_dir = TMP_DIR / "tools-bash-unsupported"
        shutil.rmtree(test_dir, ignore_errors=True)
        test_dir.mkdir(parents=True, exist_ok=True)
        try:
            tools = BuiltinToolExecutor(cwd=test_dir)
            failed = False
            try:
                tools.bash("echo alpha && echo beta")
            except Exception:  # noqa: BLE001
                failed = True
            assert failed is True
        finally:
            shutil.rmtree(test_dir, ignore_errors=True)

    def test_bash_applies_write_permissions_for_redirection(self) -> None:
        test_dir = TMP_DIR / "tools-bash-redirection-policy"
        shutil.rmtree(test_dir, ignore_errors=True)
        test_dir.mkdir(parents=True, exist_ok=True)
        try:
            policy = ToolSandboxPolicy(
                allowed_roots=(test_dir.resolve(),),
                allow_read=True,
                allow_write=False,
                allow_execute=True,
            )
            tools = BuiltinToolExecutor(cwd=test_dir, policy=policy)
            failed = False
            try:
                tools.bash("echo hello > out.txt")
            except ToolPermissionError:
                failed = True
            assert failed is True
        finally:
            shutil.rmtree(test_dir, ignore_errors=True)

    def test_bash_supports_pipeline_and_separator(self) -> None:
        test_dir = TMP_DIR / "tools-bash-pipeline-separator"
        shutil.rmtree(test_dir, ignore_errors=True)
        test_dir.mkdir(parents=True, exist_ok=True)
        try:
            tools = BuiltinToolExecutor(cwd=test_dir)
            result = tools.bash("echo alpha ; echo beta")
            assert result.exit_code == 0
            assert "alpha" in result.stdout
            assert "beta" in result.stdout
        finally:
            shutil.rmtree(test_dir, ignore_errors=True)

    def test_permission_policy_allow_and_deny_helpers(self) -> None:
        allow_all = ToolPermissionPolicy.allow_all()
        assert allow_all.is_allowed("read") is True
        assert allow_all.is_allowed("write") is True
        assert allow_all.is_allowed("execute") is True

        deny_all = ToolPermissionPolicy.deny_all()
        assert deny_all.is_allowed("read") is False
        assert deny_all.is_allowed("write") is False
        assert deny_all.is_allowed("execute") is False

    def test_permission_policy_ensure_allowed_raises(self) -> None:
        policy = ToolPermissionPolicy(
            allow_read=False,
            allow_write=False,
            allow_execute=False,
        )
        for permission in ("read", "write", "execute"):
            failed = False
            try:
                policy.ensure_allowed(permission)
            except ToolPermissionError:
                failed = True
            else:
                message = "Expected denied permission to raise ToolPermissionError"
                raise AssertionError(message)
            assert failed is True

    def test_sandbox_policy_exposes_permission_object(self) -> None:
        sandbox = ToolSandboxPolicy(
            allowed_roots=(TMP_DIR.resolve(),),
            allow_read=True,
            allow_write=False,
            allow_execute=True,
        )
        permissions = sandbox.permissions
        assert permissions.is_allowed("read") is True
        assert permissions.is_allowed("write") is False
        assert permissions.is_allowed("execute") is True


if __name__ == "__main__":
    unittest.main()
