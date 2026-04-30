# 11 — Per-provider env-var resolution

## Goal

`src/llm_providers/env.py`: per-provider env-var precedence resolver. Replaces the current single-rule `<NAME>_API_KEY` logic.

## Refs

- `pi-mono/packages/ai/src/env-api-keys.ts` (port the relevant subset)
- `00-architecture.md` §12

## Module

```python
from __future__ import annotations
import os
from typing import Final


# Per-provider env-var precedence chains. First non-empty wins.
# Only providers in the rebuild scope are listed.
_API_KEY_ENV_VARS: Final[dict[str, tuple[str, ...]]] = {
    "anthropic": ("ANTHROPIC_API_KEY", "CLAUDE_API_KEY"),
    "openai": ("OPENAI_API_KEY",),
    "openai_compatible": ("OPENAI_COMPATIBLE_API_KEY", "OPENAI_API_KEY"),
}


# Per-provider base-URL env vars (optional override).
_BASE_URL_ENV_VARS: Final[dict[str, tuple[str, ...]]] = {
    "anthropic": ("ANTHROPIC_BASE_URL",),
    "openai": ("OPENAI_BASE_URL",),
    "openai_compatible": ("OPENAI_COMPATIBLE_BASE_URL",),
}


def find_api_key_env_vars(provider: str) -> tuple[str, ...]:
    """Return the env-var precedence chain for a provider, or () if unknown."""
    return _API_KEY_ENV_VARS.get(provider, ())


def get_api_key(provider: str) -> str | None:
    """Look up the API key for a provider in environment variables.

    Walks the precedence chain; returns the first non-empty value, or None
    if none are set (or the provider is unknown).
    """
    for var in find_api_key_env_vars(provider):
        value = os.environ.get(var)
        if value:
            return value
    return None


def get_base_url(provider: str) -> str | None:
    """Look up an optional base-URL override for a provider."""
    for var in _BASE_URL_ENV_VARS.get(provider, ()):
        value = os.environ.get(var)
        if value:
            return value
    return None


def find_present_env_keys(provider: str) -> tuple[str, ...]:
    """Return only the env vars from the chain that are currently set.

    Used by config UIs to show which credential is actually being used.
    """
    return tuple(
        var for var in find_api_key_env_vars(provider) if os.environ.get(var)
    )
```

## Acceptance

- [ ] All four functions + the two precedence-chain dicts exported.
- [ ] `tests/test_env.py` (use `unittest.mock.patch.dict(os.environ, ...)`):
  - `get_api_key("anthropic")` returns `ANTHROPIC_API_KEY` when set
  - falls back to `CLAUDE_API_KEY` when `ANTHROPIC_API_KEY` unset
  - returns None when neither is set
  - `get_api_key("openai_compatible")` falls back to `OPENAI_API_KEY`
  - `get_api_key("unknown_provider")` → None
  - `find_present_env_keys("anthropic")` lists set ones in precedence order
  - `get_base_url("openai_compatible")` returns `OPENAI_COMPATIBLE_BASE_URL` when set
  - empty-string env vars treated as unset
- [ ] `basedpyright` clean.

## Notes

- Sync. Reading `os.environ` doesn't need to be async.
- Don't implement Bedrock / Vertex / Copilot ambient-credential discovery (`<authenticated>` sentinel in pi-ai). Out of scope per architecture §1.
- Provider name keys (`"anthropic"`, `"openai"`, `"openai_compatible"`) are the same identifiers the registry (task 13) uses internally.
- New providers → extend the chains here, not in adapters.
