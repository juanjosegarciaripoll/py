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
from .config import (
    AppConfig,
    default_config_path,
    load_config,
    local_config_path,
    resolve_config_path,
)
from .extensions import AppEvent, EventBus, EventListener
from .session import CompactionRecord, SessionRecord, SessionStore
from .skills import (
    SkillDatabase,
    SkillError,
    SkillNotFoundError,
    SkillSummary,
    SkillValidationError,
)
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
    "SkillDatabase",
    "SkillError",
    "SkillNotFoundError",
    "SkillSummary",
    "SkillValidationError",
    "ToolError",
    "ToolPermissionError",
    "ToolSandboxPolicy",
    "TuiCommandResult",
    "TuiController",
    "build_parser",
    "default_config_path",
    "load_config",
    "local_config_path",
    "main",
    "parse_args",
    "resolve_config_path",
]
