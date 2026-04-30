# 09 — Header helpers

## Goal

`src/llm_providers/utils/headers.py`: shared User-Agent, JSON content-type, header merge.

## Refs

- `pi-mono/packages/ai/src/utils/headers.ts` (TS reference; minimal, but the surface is broader in practice)

## Module

```python
from __future__ import annotations
from importlib.metadata import version, PackageNotFoundError


def package_version() -> str:
    """Return the installed llm-providers version, or 'unknown' if not installed."""
    try:
        return version("llm-providers")
    except PackageNotFoundError:
        return "unknown"


def user_agent(extra: str | None = None) -> str:
    """Standard User-Agent. Format: 'llm-providers/{version}' with optional suffix."""
    base = f"llm-providers/{package_version()}"
    if extra:
        return f"{base} {extra}"
    return base


def json_headers(
    *,
    api_key: str | None = None,
    auth_scheme: str = "Bearer",
    extra: dict[str, str] | None = None,
) -> dict[str, str]:
    """Build a Content-Type=application/json header dict.

    If `api_key` is provided, sets Authorization with the given scheme. If
    `extra` is provided, its keys override the defaults — providers can swap
    auth schemes (Anthropic uses `x-api-key`, OpenAI uses `Authorization: Bearer`).
    """
    headers: dict[str, str] = {
        "Content-Type": "application/json",
        "Accept": "application/json",
        "User-Agent": user_agent(),
    }
    if api_key:
        headers["Authorization"] = f"{auth_scheme} {api_key}"
    if extra:
        headers.update(extra)
    return headers


def merge_headers(*sources: dict[str, str] | None) -> dict[str, str]:
    """Merge header dicts left-to-right; later wins. None entries skipped."""
    out: dict[str, str] = {}
    for src in sources:
        if src:
            out.update(src)
    return out
```

## Acceptance

- [ ] All four functions exported.
- [ ] `tests/test_headers.py`:
  - `package_version()` returns a string (don't assert specific value)
  - `user_agent()` starts with `"llm-providers/"`
  - `user_agent("foo/1.0")` ends with `" foo/1.0"`
  - `json_headers()` always contains `Content-Type` + `User-Agent`
  - `json_headers(api_key="x")` adds `Authorization: Bearer x`
  - `json_headers(api_key="x", auth_scheme="Token")` produces `Authorization: Token x`
  - `json_headers(extra={"Authorization": "custom"})` overrides to `"custom"`
  - `merge_headers({"a":"1"}, None, {"a":"2","b":"3"}) == {"a":"2","b":"3"}`
- [ ] `basedpyright` clean.

## Notes

- No `llm_providers` deps.
- Anthropic: `x-api-key: <key>` + `anthropic-version: 2023-06-01`. Build via `json_headers(extra={"x-api-key": key, "anthropic-version": "2023-06-01"})` — no `scheme="anthropic"` special case here. Adapters compose what they need.
- OpenAI: `Authorization: Bearer <key>` is the default — `json_headers(api_key=key)` is enough.
- OpenAI-compatible: same as OpenAI, but some endpoints accept no auth. Adapter handles the optional case.
