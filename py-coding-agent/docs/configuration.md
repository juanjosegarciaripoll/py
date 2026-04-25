# Configuration Schema

This document describes the TOML configuration schema currently used by `py-coding-agent`.

## Resolution Order

Configuration is loaded from:

1. `--config <path>` CLI argument (highest priority).
2. Local project config: `./.py/config.toml` (if present).
3. `PY_CODING_AGENT_CONFIG` environment variable.
4. Default user config path:
   - Windows: `%APPDATA%/py-coding-agent/config.toml`
   - Unix-like with XDG: `$XDG_CONFIG_HOME/py-coding-agent/config.toml`
   - Fallback: `~/.config/py-coding-agent/config.toml`

If no file exists, built-in defaults are used.

## Top-Level Structure

```toml
[agent]
mode = "interactive"
branch = "main"
session_file = "sessions/default.jsonl"
context_window_tokens = 272000

[agent.compaction]
enabled = true
reserve_tokens = 16384
keep_recent_tokens = 20000

[agent.tools]
allow_read = true
allow_write = true
allow_execute = true
allowed_roots = ["."]

[agent.skills]
root = ".py/skills"
```

## Schema Reference

### `[agent]`

- `mode` (`"interactive" | "print" | "json" | "rpc" | "tui"`, default: `"interactive"`)
- `branch` (`string`, default: `"main"`)
- `session_file` (`string`, optional, default: `null`)
- `context_window_tokens` (`int > 0`, default: `272000`)

### `[agent.compaction]`

- `enabled` (`bool`, default: `true`)
- `reserve_tokens` (`int > 0`, default: `16384`)
- `keep_recent_tokens` (`int > 0`, default: `20000`)

### `[agent.tools]`

- `allow_read` (`bool`, default: `true`)
- `allow_write` (`bool`, default: `true`)
- `allow_execute` (`bool`, default: `true`)
- `allowed_roots` (`array[string]`, default: empty)
  - When empty, tools default to current working directory confinement.
  - Relative paths are resolved from process working directory.

### `[agent.skills]`

- `root` (`string`, default: `".py/skills"`)
  - Root directory containing skill folders for incremental skill loading.

## Validation Behavior

- Unknown keys are ignored.
- Invalid values fall back to defaults.
- `allowed_roots` must be an array of strings; otherwise it is ignored.

## Minimal Example

```toml
[agent]
mode = "rpc"
branch = "main"

[agent.tools]
allow_execute = false
allowed_roots = ["py-coding-agent/src", "py-agent/src"]
```
