# 12 — TOML configuration

## Goal

`src/llm_providers/config.py`: TOML-backed configuration — load, save, in-memory mutation, default-path resolver respecting XDG / Windows conventions.

## Refs

- `00-architecture.md` §12 (TOML schema, resolution order)
- TS has no exact equivalent (reads from environment + per-app config); we ship one file because Python lacks the npm-style top-level config.

## Module

```python
from __future__ import annotations
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

if sys.version_info >= (3, 11):
    import tomllib
else:  # pragma: no cover  -- project requires 3.11+
    raise ImportError("llm-providers requires Python 3.11+")


@dataclass(slots=True)
class ProviderEntry:
    api_key: str | None = None
    base_url: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class ProvidersConfig:
    default_model: str | None = None
    providers: dict[str, ProviderEntry] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ProvidersConfig":
        providers_in = data.get("providers", {}) or {}
        providers: dict[str, ProviderEntry] = {}
        for name, entry in providers_in.items():
            if not isinstance(entry, dict):
                continue
            providers[name] = ProviderEntry(
                api_key=entry.get("api_key"),
                base_url=entry.get("base_url"),
                extra={
                    k: v for k, v in entry.items()
                    if k not in {"api_key", "base_url"}
                },
            )
        return cls(default_model=data.get("default_model"), providers=providers)

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {}
        if self.default_model is not None:
            out["default_model"] = self.default_model
        if self.providers:
            out["providers"] = {
                name: _provider_entry_to_dict(entry)
                for name, entry in self.providers.items()
            }
        return out


def _provider_entry_to_dict(entry: ProviderEntry) -> dict[str, Any]:
    out: dict[str, Any] = {}
    if entry.api_key is not None:
        out["api_key"] = entry.api_key
    if entry.base_url is not None:
        out["base_url"] = entry.base_url
    out.update(entry.extra)
    return out


def default_config_path() -> Path:
    """Resolve the per-user config file path.

    - $LLM_PROVIDERS_CONFIG (if set) → use as-is.
    - Linux/macOS: $XDG_CONFIG_HOME/llm-providers/config.toml
                   (fallback ~/.config/llm-providers/config.toml)
    - Windows:     %APPDATA%/llm-providers/config.toml
                   (fallback %USERPROFILE%/AppData/Roaming/llm-providers/config.toml)
    """
    override = os.environ.get("LLM_PROVIDERS_CONFIG")
    if override:
        return Path(override)
    if sys.platform.startswith("win"):
        appdata = os.environ.get("APPDATA")
        if appdata:
            return Path(appdata) / "llm-providers" / "config.toml"
        return Path.home() / "AppData" / "Roaming" / "llm-providers" / "config.toml"
    xdg = os.environ.get("XDG_CONFIG_HOME")
    base = Path(xdg) if xdg else Path.home() / ".config"
    return base / "llm-providers" / "config.toml"


def load_config(path: Path | None = None) -> ProvidersConfig:
    """Load and parse the TOML config. Returns an empty config if missing.

    Raises tomllib.TOMLDecodeError if the file is malformed.
    """
    target = path or default_config_path()
    if not target.exists():
        return ProvidersConfig()
    with target.open("rb") as fh:
        data = tomllib.load(fh)
    return ProvidersConfig.from_dict(data)


def save_config(config: ProvidersConfig, path: Path | None = None) -> None:
    """Write the config to disk in TOML format.

    Directory created if missing. Uses `_write_toml` (sufficient for our
    schema — no nested arrays of tables, no datetimes).
    """
    target = path or default_config_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    text = _write_toml(config.to_dict())
    target.write_text(text, encoding="utf-8")


def _write_toml(data: dict[str, Any]) -> str:
    """Minimal TOML writer for the ProvidersConfig schema.

    Supports:
      - top-level scalars (str, int, float, bool)
      - one level of nested tables (`[providers.<name>]`)
      - dict-valued scalars inside the nested table (extra)

    Doesn't support arrays of tables, datetimes, or top-level inline tables.
    Acceptable because the schema is fixed.
    """
    lines: list[str] = []
    for key, value in data.items():
        if isinstance(value, dict):
            continue
        lines.append(f"{key} = {_toml_value(value)}")
    providers = data.get("providers")
    if isinstance(providers, dict) and providers:
        if lines:
            lines.append("")
        for name, entry in providers.items():
            lines.append(f"[providers.{name}]")
            if isinstance(entry, dict):
                for k, v in entry.items():
                    lines.append(f"{k} = {_toml_value(v)}")
            lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def _toml_value(v: Any) -> str:
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (int, float)):
        return str(v)
    if isinstance(v, str):
        escaped = v.replace("\\", "\\\\").replace('"', '\\"')
        return f'"{escaped}"'
    raise ValueError(f"unsupported TOML value type: {type(v).__name__}")
```

## Resolution order for credentials (used by registry / providers, not here)

1. Explicit kwarg (`AnthropicProvider(api_key=...)`).
2. `ProvidersConfig.providers[<name>].api_key`.
3. `env.get_api_key(<name>)`.
4. Raise `AuthError("no API key for <name>")`.

This module just loads the config; resolution itself happens in the registry / provider classes.

## Acceptance

- [ ] Exports `ProviderEntry`, `ProvidersConfig`, `default_config_path`, `load_config`, `save_config`.
- [ ] `tests/test_config.py`:
  - `default_config_path()` honors `LLM_PROVIDERS_CONFIG` override
  - non-Windows uses `XDG_CONFIG_HOME` when set
  - non-Windows falls back to `~/.config` when unset
  - Windows uses `%APPDATA%`
  - `load_config(missing_path)` returns empty config
  - round-trip: save → load → equal config (use `tempfile.TemporaryDirectory`)
  - `from_dict`/`to_dict` round-trip with `default_model`, two providers, extra keys
  - malformed TOML raises `tomllib.TOMLDecodeError`
- [ ] `basedpyright` clean.
- [ ] No `tomli-w` dep unless approved.

## Notes

- Stdlib `tomllib` for read; minimal hand-rolled writer for our schema.
- `extra` is the escape hatch for provider-specific options. Providers ignore what they don't understand.
- OS-detection via `sys.platform.startswith("win")`, not `platform.system()` — avoids the import.
- No `merge_env(config)` here — env merging in registry (task 13) or provider constructors.
