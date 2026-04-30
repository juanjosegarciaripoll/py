# 03 — Errors

## Goal

`src/llm_providers/errors.py`: unified exception hierarchy.

## Refs

- `00-architecture.md` §6

## Module

```python
from __future__ import annotations
from typing import Any


class LLMProviderError(Exception):
    """Base for all errors raised by llm-providers."""

    def __init__(
        self,
        message: str,
        *,
        provider: str = "",
        provider_error: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.provider = provider
        self.provider_error = provider_error or {}

    @property
    def message(self) -> str:
        return self.args[0] if self.args else ""


class AuthError(LLMProviderError):
    """401 / 403."""


class RateLimitError(LLMProviderError):
    """429. Includes retry-after when the server provides one."""

    def __init__(
        self,
        message: str,
        *,
        provider: str = "",
        provider_error: dict[str, Any] | None = None,
        retry_after: float | None = None,
    ) -> None:
        super().__init__(message, provider=provider, provider_error=provider_error)
        self.retry_after = retry_after


class ContextOverflowError(LLMProviderError):
    """Request exceeded the model's context window. Detected via utils.overflow.
    Caught by py-agent's compaction logic."""


class BadRequestError(LLMProviderError):
    """400-class error not covered by a more specific subtype."""


class APIError(LLMProviderError):
    """5xx and other unexpected upstream failures."""

    def __init__(
        self,
        message: str,
        *,
        provider: str = "",
        provider_error: dict[str, Any] | None = None,
        status_code: int = 0,
    ) -> None:
        super().__init__(message, provider=provider, provider_error=provider_error)
        self.status_code = status_code


class TransportError(LLMProviderError):
    """Network / DNS / TLS / read-timeout. Wraps the underlying httpx exception."""

    def __init__(
        self,
        message: str,
        *,
        provider: str = "",
        cause: Exception | None = None,
    ) -> None:
        super().__init__(message, provider=provider)
        self.__cause__ = cause


class AbortError(LLMProviderError):
    """Raised on the explicit abort-event code path so callers can distinguish
    abort reasons. Normal asyncio cancellation re-raises CancelledError unchanged."""
```

## Mapping (informational; concrete in provider tasks)

| HTTP / signal | Subtype |
|---|---|
| 401, 403 | `AuthError` |
| 429 | `RateLimitError` (read `retry-after` header) |
| 400 with overflow message pattern | `ContextOverflowError` (via `utils.overflow`) |
| 400 (other) | `BadRequestError` |
| 5xx | `APIError(status_code=...)` |
| `httpx.TransportError` / `httpx.TimeoutException` | `TransportError` |
| `asyncio.CancelledError` | re-raise unchanged (architecture §7) |
| explicit abort event | `AbortError` |

## Acceptance

- [ ] All classes exported.
- [ ] `tests/test_errors.py`:
  - per-subtype construction
  - `provider`, `provider_error`, `message` populated correctly
  - `RateLimitError(retry_after=12.5)` round-trips
  - `APIError(status_code=503)` round-trips
  - `try / except LLMProviderError` catches every subtype
- [ ] `basedpyright` clean.

## Notes

- Don't subclass `httpx.HTTPError` or import httpx here. Providers wrap httpx exceptions in `TransportError(cause=...)`.
- No `from_response()` classmethod. Per-provider dispatch needs provider-specific knowledge.
- Messages user-facing + short. Full payload lives in `provider_error`.
