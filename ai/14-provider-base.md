# 14 — `Provider` abstract base + interface contract

## Goal

`src/llm_providers/provider.py`: `Provider` abstract base. Contract every concrete provider implements (`AnthropicProvider`, `OpenAIChatCompletionsProvider`, `OpenAIResponsesProvider`, `OpenAICompatibleProvider`).

Replaces the current `provider.py`.

## Refs

- `00-architecture.md` §2 (async-first), §4 (public API), §5 (event protocol), §7 (cancellation), §8 (tools)
- `pi-mono/packages/ai/src/types.ts:147-151` (`StreamFunction`) — TS form. We use a class instead of a free function so adapters can hold per-instance state (HTTP client, credentials).

## Module

```python
from __future__ import annotations
import asyncio
from abc import ABC, abstractmethod
from typing import AsyncIterator, ClassVar

import httpx

from llm_providers.events import Event
from llm_providers.models import ModelInfo
from llm_providers.types import Context


class Provider(ABC):
    """Base class for every provider adapter.

    Concrete subclasses implement `stream()`. `check_model_access()` is
    optional but recommended (used by config UIs to verify credentials).
    """

    name: ClassVar[str]
    """Stable identifier for this provider (e.g. "anthropic"). Used by env
    lookup and config files. Subclasses must override."""

    api: ClassVar[str]
    """The Api literal this provider serves (e.g. "anthropic-messages").
    Used by registry dispatch. Subclasses must override."""

    default_base_url: ClassVar[str]
    """Default base URL for outbound requests. Subclasses must override."""

    def __init__(
        self,
        *,
        api_key: str | None = None,
        base_url: str | None = None,
        client: httpx.AsyncClient | None = None,
        timeout: float = 600.0,
    ) -> None:
        self.api_key = api_key
        self.base_url = base_url or self.default_base_url
        self._owns_client = client is None
        self._client = client or httpx.AsyncClient(timeout=timeout)

    @abstractmethod
    def stream(
        self,
        model: ModelInfo,
        context: Context,
        *,
        abort: asyncio.Event | None = None,
        **options: object,
    ) -> AsyncIterator[Event]:
        """Yield events for the given (model, context).

        Async generator. Contract in architecture §5 — `MessageStart` first,
        content blocks correctly bracketed, `MessageEnd` then `Done` last.

        On asyncio.CancelledError, emit `MessageEnd(stop_reason="abort")`
        + `Done`, then re-raise. On `abort.is_set()`, same shutdown path;
        `AbortError` is not raised — stream simply ends with stop_reason
        "abort".

        On upstream errors, emit `Error(error=...)` then `MessageEnd
        (stop_reason="error")` then `Done` — do not raise from the
        generator. Pre-flight validation errors (bad arguments, missing
        credentials) MAY raise synchronously before the first event.
        """
        ...

    async def check_model_access(self, model: ModelInfo) -> bool:
        """Optional: probe whether this provider can reach the model.

        Default: True if `api_key` is set or `name` doesn't require credentials.
        Override for richer checks (e.g. hit the `/models` endpoint).
        """
        return bool(self.api_key)

    async def aclose(self) -> None:
        """Close the underlying HTTP client if we own it."""
        if self._owns_client:
            await self._client.aclose()

    async def __aenter__(self) -> "Provider":
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self.aclose()
```

## Subclass checklist

A concrete provider must:

1. Set `name`, `api`, `default_base_url` as class variables.
2. Implement `stream` as async generator obeying the §5 event contract.
3. Wrap upstream HTTP exceptions in `errors.LLMProviderError` subtypes (§6).
4. Translate stop reasons via the normalized enum (§5).
5. Issue stable library tool-call IDs and maintain `library_id → provider_id` per stream (§8).
6. Sanitize text via `utils.sanitize_surrogates` before sending.
7. Re-export the `cache: bool` flag on text/tool defs to the wire format (§9).

Checked by contract tests (tasks 30–31), not enforced here.

## Acceptance

- [ ] `Provider` exported.
- [ ] Old `provider.py` removed (overwrite is fine).
- [ ] `tests/test_provider_base.py`:
  - cannot instantiate `Provider` directly (`ABC` enforcement)
  - minimal subclass with `name`, `api`, `default_base_url` + stub `stream` instantiates
  - `check_model_access` default returns True iff `api_key` is set
  - `aclose()` closes an owned client; doesn't close an externally-supplied one
  - `async with provider:` calls `aclose` on exit
- [ ] `basedpyright` clean.

## Notes

- `**options` lets each provider accept its own optional knobs (`temperature`, `max_tokens`, …) without leaking them into the base signature. Concrete providers pull recognized keys + pass remaining ones through silently — same approach as TS's `ProviderStreamOptions`.
- No `complete` method on the base. `complete` is `assemble(stream(...))` and lives in task 27.
- `ClassVar[str]` with no default forces subclasses to set it; type checkers flag missing values.
- `httpx.AsyncClient` created in `__init__` if not provided. Provider left ungc-collected leaks a connection pool. Consumers `async with` the provider or call `aclose()` — covered in tests.
