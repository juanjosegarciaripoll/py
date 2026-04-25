"""TOML-backed configuration for py-coding-agent."""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, cast

type JsonObject = dict[str, object]
type ExecutionMode = Literal["interactive", "print", "json", "rpc", "tui"]
type CompactionThinkingLevel = Literal["low", "medium", "high"]


@dataclass(slots=True)
class AppConfig:
    """CLI defaults loaded from TOML."""

    mode: ExecutionMode = "interactive"
    branch: str = "main"
    session_file: str | None = None
    context_window_tokens: int = 272_000
    compaction_enabled: bool = True
    compaction_reserve_tokens: int = 16_384
    compaction_keep_recent_tokens: int = 20_000
    compaction_thinking_level: CompactionThinkingLevel = "medium"
    tool_allow_read: bool = True
    tool_allow_write: bool = True
    tool_allow_execute: bool = True
    tool_allowed_roots: tuple[str, ...] = ()
    skills_root: str = ".py/skills"


def load_config(path: Path | None) -> AppConfig:
    """Load application config from a TOML file path."""
    defaults = AppConfig()
    resolved_path = resolve_config_path(path)
    if resolved_path is None or not resolved_path.exists():
        return defaults
    with resolved_path.open("rb") as handle:
        parsed: object = tomllib.load(handle)
    data = _as_str_object_dict(parsed)
    if data is None:
        return defaults
    agent = _as_str_object_dict(data.get("agent"))
    if agent is None:
        return defaults
    mode = _as_mode(agent.get("mode"))
    branch = _as_str(agent.get("branch"), defaults.branch)
    session_file = _as_optional_str(agent.get("session_file"))
    context_window_tokens = _as_positive_int(
        agent.get("context_window_tokens"),
        defaults.context_window_tokens,
    )
    (
        compaction_enabled,
        compaction_reserve_tokens,
        compaction_keep_recent_tokens,
        compaction_thinking_level,
    ) = _parse_compaction(agent, defaults)
    (
        tool_allow_read,
        tool_allow_write,
        tool_allow_execute,
        tool_allowed_roots,
    ) = _parse_tools(agent, defaults)
    skills_root = _parse_skills(agent, defaults)
    return AppConfig(
        mode=mode,
        branch=branch,
        session_file=session_file,
        context_window_tokens=context_window_tokens,
        compaction_enabled=compaction_enabled,
        compaction_reserve_tokens=compaction_reserve_tokens,
        compaction_keep_recent_tokens=compaction_keep_recent_tokens,
        compaction_thinking_level=compaction_thinking_level,
        tool_allow_read=tool_allow_read,
        tool_allow_write=tool_allow_write,
        tool_allow_execute=tool_allow_execute,
        tool_allowed_roots=tool_allowed_roots,
        skills_root=skills_root,
    )


def _parse_compaction(
    agent: JsonObject,
    defaults: AppConfig,
) -> tuple[bool, int, int, CompactionThinkingLevel]:
    compaction = _as_str_object_dict(agent.get("compaction"))
    enabled = defaults.compaction_enabled
    reserve_tokens = defaults.compaction_reserve_tokens
    keep_recent_tokens = defaults.compaction_keep_recent_tokens
    thinking_level = defaults.compaction_thinking_level
    if compaction is not None:
        enabled = _as_bool(compaction.get("enabled"), default=enabled)
        reserve_tokens = _as_positive_int(
            compaction.get("reserve_tokens"),
            reserve_tokens,
        )
        keep_recent_tokens = _as_positive_int(
            compaction.get("keep_recent_tokens"),
            keep_recent_tokens,
        )
        thinking_level = _as_compaction_thinking_level(
            compaction.get("thinking_level"),
            default=thinking_level,
        )
    return (enabled, reserve_tokens, keep_recent_tokens, thinking_level)


def _parse_tools(
    agent: JsonObject,
    defaults: AppConfig,
) -> tuple[bool, bool, bool, tuple[str, ...]]:
    tools = _as_str_object_dict(agent.get("tools"))
    tool_allow_read = defaults.tool_allow_read
    tool_allow_write = defaults.tool_allow_write
    tool_allow_execute = defaults.tool_allow_execute
    tool_allowed_roots = defaults.tool_allowed_roots
    if tools is None:
        return (
            tool_allow_read,
            tool_allow_write,
            tool_allow_execute,
            tool_allowed_roots,
        )
    tool_allow_read = _as_bool(tools.get("allow_read"), default=tool_allow_read)
    tool_allow_write = _as_bool(tools.get("allow_write"), default=tool_allow_write)
    tool_allow_execute = _as_bool(
        tools.get("allow_execute"),
        default=tool_allow_execute,
    )
    parsed_roots = _as_tuple_of_str(tools.get("allowed_roots"))
    if parsed_roots is not None:
        tool_allowed_roots = parsed_roots
    return (
        tool_allow_read,
        tool_allow_write,
        tool_allow_execute,
        tool_allowed_roots,
    )


def _parse_skills(agent: JsonObject, defaults: AppConfig) -> str:
    skills = _as_str_object_dict(agent.get("skills"))
    if skills is None:
        return defaults.skills_root
    return _as_nonempty_str(skills.get("root"), defaults.skills_root)


def resolve_config_path(path: Path | None) -> Path | None:
    """Resolve explicit or default config path."""
    if path is not None:
        return path
    local_path = local_config_path()
    if local_path.exists():
        return local_path
    env_path = os.environ.get("PY_CODING_AGENT_CONFIG")
    if env_path:
        return Path(env_path)
    return default_config_path()


def local_config_path() -> Path:
    """Return local project config path (`.py/config.toml`)."""
    return Path.cwd() / ".py" / "config.toml"


def default_config_path() -> Path:
    """Return default user config path for py-coding-agent."""
    appdata = os.environ.get("APPDATA")
    if appdata:
        return Path(appdata) / "py-coding-agent" / "config.toml"
    xdg = os.environ.get("XDG_CONFIG_HOME")
    if xdg:
        return Path(xdg) / "py-coding-agent" / "config.toml"
    return Path.home() / ".config" / "py-coding-agent" / "config.toml"


def _as_mode(value: object) -> ExecutionMode:
    if value in {"interactive", "print", "json", "rpc", "tui"}:
        return cast("ExecutionMode", value)
    return "interactive"


def _as_str_object_dict(value: object) -> JsonObject | None:
    if not isinstance(value, dict):
        return None
    raw = cast("dict[object, object]", value)
    result: JsonObject = {}
    for key, item in raw.items():
        if not isinstance(key, str):
            return None
        result[key] = item
    return result


def _as_bool(value: object, *, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    return default


def _as_positive_int(value: object, default: int) -> int:
    if isinstance(value, int) and value > 0:
        return value
    return default


def _as_str(value: object, default: str) -> str:
    if isinstance(value, str):
        return value
    return default


def _as_nonempty_str(value: object, default: str) -> str:
    if isinstance(value, str) and value:
        return value
    return default


def _as_optional_str(value: object) -> str | None:
    if isinstance(value, str):
        return value
    return None


def _as_tuple_of_str(value: object) -> tuple[str, ...] | None:
    if value is None:
        return None
    if not isinstance(value, list):
        return None
    raw_values = cast("list[object]", value)
    result: list[str] = []
    for item in raw_values:
        if not isinstance(item, str):
            return None
        result.append(item)
    return tuple(result)


def _as_compaction_thinking_level(
    value: object,
    *,
    default: CompactionThinkingLevel,
) -> CompactionThinkingLevel:
    if value in {"low", "medium", "high"}:
        return cast("CompactionThinkingLevel", value)
    return default
