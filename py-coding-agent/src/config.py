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
    mode = _as_mode(mode_value)
    branch = branch_value if isinstance(branch_value, str) else "main"
    session_file = session_value if isinstance(session_value, str) else None
    return AppConfig(mode=mode, branch=branch, session_file=session_file)


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
