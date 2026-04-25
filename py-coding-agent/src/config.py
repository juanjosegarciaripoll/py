"""TOML-backed configuration for py-coding-agent."""

from __future__ import annotations

import tomllib
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal, cast

type JsonObject = dict[str, object]
type ExecutionMode = Literal["interactive", "print", "json", "rpc"]

if TYPE_CHECKING:
    from pathlib import Path


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


def load_config(path: Path | None) -> AppConfig:
    """Load application config from a TOML file path."""
    if path is None:
        return AppConfig()
    if not path.exists():
        return AppConfig()
    with path.open("rb") as handle:
        parsed: object = tomllib.load(handle)
    data = _as_str_object_dict(parsed)
    if data is None:
        return AppConfig()
    agent = _as_str_object_dict(data.get("agent"))
    if agent is None:
        return AppConfig()
    mode_value = agent.get("mode")
    branch_value = agent.get("branch")
    session_value = agent.get("session_file")
    context_window_value = agent.get("context_window_tokens")
    compaction = _as_str_object_dict(agent.get("compaction"))
    mode = _as_mode(mode_value)
    branch = branch_value if isinstance(branch_value, str) else "main"
    session_file = session_value if isinstance(session_value, str) else None
    context_window_tokens = (
        context_window_value
        if isinstance(context_window_value, int) and context_window_value > 0
        else 272_000
    )
    enabled = True
    reserve_tokens = 16_384
    keep_recent_tokens = 20_000
    if compaction is not None:
        enabled_value = compaction.get("enabled")
        reserve_value = compaction.get("reserve_tokens")
        keep_recent_value = compaction.get("keep_recent_tokens")
        if isinstance(enabled_value, bool):
            enabled = enabled_value
        if isinstance(reserve_value, int) and reserve_value > 0:
            reserve_tokens = reserve_value
        if isinstance(keep_recent_value, int) and keep_recent_value > 0:
            keep_recent_tokens = keep_recent_value
    return AppConfig(
        mode=mode,
        branch=branch,
        session_file=session_file,
        context_window_tokens=context_window_tokens,
        compaction_enabled=enabled,
        compaction_reserve_tokens=reserve_tokens,
        compaction_keep_recent_tokens=keep_recent_tokens,
    )


def _as_mode(value: object) -> ExecutionMode:
    if value in {"interactive", "print", "json", "rpc"}:
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
