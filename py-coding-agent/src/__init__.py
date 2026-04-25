"""Public API for the py-coding-agent package."""

from .cli import (
    CodingAgentApp,
    ExecutionMode,
    RunConfig,
    build_parser,
    main,
    parse_args,
)
from .compaction import CompactionSettings
from .config import AppConfig, load_config
from .extensions import AppEvent, EventBus, EventListener
from .session import CompactionRecord, SessionRecord, SessionStore
from .tools import (
    BashResult,
    BuiltinToolExecutor,
    GrepMatch,
    ToolError,
    ToolPermissionError,
    ToolSandboxPolicy,
)
from .tui_controller import TuiCommandResult, TuiController

__all__ = [
    "AppConfig",
    "AppEvent",
    "BashResult",
    "BuiltinToolExecutor",
    "CodingAgentApp",
    "CompactionRecord",
    "CompactionSettings",
    "EventBus",
    "EventListener",
    "ExecutionMode",
    "GrepMatch",
    "RunConfig",
    "SessionRecord",
    "SessionStore",
    "ToolError",
    "ToolPermissionError",
    "ToolSandboxPolicy",
    "TuiCommandResult",
    "TuiController",
    "build_parser",
    "load_config",
    "main",
    "parse_args",
]
