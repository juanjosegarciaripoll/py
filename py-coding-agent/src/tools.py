"""Compatibility wrapper for built-in tools now hosted in `py-agent-tools`."""

import sys
from pathlib import Path

try:
    from py_agent_tools import (
        BashResult,
        BuiltinToolExecutor,
        GrepMatch,
        ToolError,
        ToolPermissionError,
        ToolSandboxPolicy,
    )
except ModuleNotFoundError:
    tools_src = (
        Path(__file__).resolve().parents[2] / "py-agent-tools" / "src"
    )
    sys.path.insert(0, str(tools_src))
    from py_agent_tools import (
        BashResult,
        BuiltinToolExecutor,
        GrepMatch,
        ToolError,
        ToolPermissionError,
        ToolSandboxPolicy,
    )

__all__ = [
    "BashResult",
    "BuiltinToolExecutor",
    "GrepMatch",
    "ToolError",
    "ToolPermissionError",
    "ToolSandboxPolicy",
]
