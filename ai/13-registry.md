# 13 — API + model registry, dispatch logic

## Goal

`src/llm_providers/registry.py`: maps `model_id → ModelInfo → Provider`. Exposes top-level `stream` / `complete` dispatch + the overridable cost function.

Replaces current `api_registry.py` and `model_registry.py` — both deleted in this task.

## Refs

- `00-architecture.md` §4 (public API + resolution), §11 (models), §13 (layout)
- `pi-mono/packages/ai/src/api-registry.ts` (TS shape)

## Module

```python
from __future__ import annotations
import asyncio
from decimal import Decimal
from typing import AsyncIterator, Callable

from llm_providers.events import Event
from llm_providers.errors import LLMProviderError, BadRequestError
from llm_providers.models import ModelInfo, Api, CostFunction, compute_cost_default
from llm_providers.types import Context, Usage
from llm_providers.provider import Provider


# ---------------------------------------------------------------------------
# Model catalogue
# ---------------------------------------------------------------------------

_MODELS: dict[str, ModelInfo] = {}


def register_model(model: ModelInfo) -> None:
    _MODELS[model.id] = model


def register_models(models: list[ModelInfo]) -> None:
    for m in models:
        register_model(m)


def get_model(model_id: str) -> ModelInfo | None:
    return _MODELS.get(model_id)


def all_models() -> list[ModelInfo]:
    return list(_MODELS.values())


# ---------------------------------------------------------------------------
# Provider registry — keyed by Api literal
# ---------------------------------------------------------------------------

_PROVIDERS: dict[str, Provider] = {}


def register_provider(api: Api | str, provider: Provider) -> None:
    """Register a provider instance to handle requests for a given Api."""
    _PROVIDERS[str(api)] = provider


def get_provider(api: Api | str) -> Provider | None:
    return _PROVIDERS.get(str(api))


def all_providers() -> dict[str, Provider]:
    return dict(_PROVIDERS)


# ---------------------------------------------------------------------------
# Resolution: model_id → (ModelInfo, Provider)
# ---------------------------------------------------------------------------

_PREFIX_FALLBACK: tuple[tuple[str, Api], ...] = (
    ("claude-", "anthropic-messages"),
    ("gpt-", "openai-completions"),
    ("o1", "openai-responses"),
    ("o3", "openai-responses"),
    ("o4", "openai-responses"),
)


def resolve(model_id: str, *, api: Api | str | None = None) -> tuple[ModelInfo, Provider]:
    """Find the ModelInfo and Provider for `model_id`.

    Strategy:
      1. If `api` is explicitly passed, use it. Synthesize a minimal
         ModelInfo if `model_id` isn't in the catalogue.
      2. Look up `model_id` in the catalogue. If found, dispatch by its `api`.
      3. Prefix-fallback against the prefix table; synthesize ModelInfo.
      4. Raise BadRequestError.

    Raises BadRequestError if no provider is registered for the resolved api.
    """
    model = _MODELS.get(model_id)
    if api is not None:
        api_str = str(api)
        provider = _PROVIDERS.get(api_str)
        if not provider:
            raise BadRequestError(
                f"no provider registered for api {api_str!r}",
                provider=api_str,
            )
        if model is None:
            model = _synthesize_model(model_id, api_str)
        return model, provider

    if model is not None:
        provider = _PROVIDERS.get(model.api)
        if not provider:
            raise BadRequestError(
                f"no provider registered for api {model.api!r} (model {model_id!r})",
            )
        return model, provider

    for prefix, fallback_api in _PREFIX_FALLBACK:
        if model_id.startswith(prefix):
            provider = _PROVIDERS.get(fallback_api)
            if not provider:
                raise BadRequestError(
                    f"prefix-matched api {fallback_api!r} for model {model_id!r}, "
                    f"but no provider is registered for it",
                )
            return _synthesize_model(model_id, fallback_api), provider

    raise BadRequestError(
        f"unknown model {model_id!r} and no prefix matched. "
        f"Register the model via register_model() or pass api=... explicitly."
    )


def _synthesize_model(model_id: str, api: str) -> ModelInfo:
    """Build a minimal ModelInfo for a model not in the catalogue.

    Cost is zero, capabilities default. Used when a brand-new model hits.
    """
    return ModelInfo(
        id=model_id,
        api=api,  # type: ignore[arg-type]  -- caller-supplied
        name=model_id,
        provider=api.split("-", 1)[0] if "-" in api else api,
        base_url="",
        context_window=0,
        max_output=0,
    )


# ---------------------------------------------------------------------------
# Top-level dispatch
# ---------------------------------------------------------------------------

async def stream(
    model: str,
    context: Context,
    *,
    api: Api | str | None = None,
    abort: asyncio.Event | None = None,
    **options: object,
) -> AsyncIterator[Event]:
    """Top-level streaming entrypoint."""
    model_info, provider = resolve(model, api=api)
    async for event in provider.stream(model_info, context, abort=abort, **options):
        yield event


async def complete(
    model: str,
    context: Context,
    *,
    api: Api | str | None = None,
    abort: asyncio.Event | None = None,
    **options: object,
) -> "AssistantMessageResult":
    """Top-level non-streaming entrypoint. Drains the stream + returns
    accumulated final message + usage."""
    from llm_providers.assemble import assemble  # lazy import (task 27)
    return await assemble(stream(model, context, api=api, abort=abort, **options))


def sync_stream(*args: object, **kwargs: object):  # pragma: no cover -- thin wrapper
    """Sync wrapper. See architecture §2."""
    raise NotImplementedError("Implement in task 27 (top-level public API).")


def sync_complete(*args: object, **kwargs: object):  # pragma: no cover -- thin wrapper
    raise NotImplementedError("Implement in task 27 (top-level public API).")


# ---------------------------------------------------------------------------
# Cost function (overridable hook)
# ---------------------------------------------------------------------------

_cost_fn: CostFunction = compute_cost_default


def set_cost_function(fn: CostFunction) -> None:
    """Replace the global cost calculator. Not threadsafe; set at startup."""
    global _cost_fn
    _cost_fn = fn


def reset_cost_function() -> None:
    """Restore the default cost calculator."""
    global _cost_fn
    _cost_fn = compute_cost_default


def compute_cost(model: ModelInfo, usage: Usage) -> Decimal:
    """Compute USD cost for the given (model, usage) using the active hook."""
    return _cost_fn(model, usage)
```

> **Forward refs:**
> - `Provider` (task 14) is the abstract base.
> - `assemble` (task 27) drains an event stream into an `AssistantMessage`.
> - `AssistantMessageResult` is `AssistantMessage`; the docstring placeholder avoids an import cycle. Implementer can replace with direct import if no cycle arises.

## Acceptance

- [ ] Public functions exported. Old `api_registry.py` + `model_registry.py` deleted.
- [ ] Importable: `register_model, register_provider, get_model, get_provider, resolve, stream, complete, set_cost_function, compute_cost`.
- [ ] `tests/test_registry.py` (with stub `Provider` + `ModelInfo`):
  - register a model + look up by id
  - register a provider for an api + look up
  - `resolve("known-model")` returns `(model, provider)`
  - `resolve("claude-foo-9000")` (unknown) → synthesized + anthropic via prefix fallback
  - `resolve("gpt-foo-9000")` → openai-completions via prefix fallback
  - `resolve("o3-foo")` → openai-responses
  - `resolve("unknown-prefix-model")` raises `BadRequestError`
  - `resolve("foo", api="anthropic-messages")` returns anthropic + synthesized model
  - `resolve` raises if resolved api has no registered provider
  - `set_cost_function(custom)` swaps; `reset_cost_function()` restores
  - `compute_cost(...)` matches `compute_cost_default(...)` after reset
- [ ] `basedpyright` clean. Module-level globals fine; no `Any` in public signatures.

## Notes

- Module-level mutable state (`_MODELS`, `_PROVIDERS`, `_cost_fn`) intentional — same pattern as TS. Tests should `_MODELS.clear()` and `_PROVIDERS.clear()` in `setUp` to avoid cross-pollution. Provide an `_internal_reset_for_tests()` if the implementer prefers a public test API.
- `register_provider` takes a `Provider` *instance*, not a class. Construction (with credentials) happens in `providers/__init__.py`.
- Prefix-fallback table is small + explicit. No fuzzy matching.
- `stream` / `complete` are async. Sync wrappers (`sync_stream`, `sync_complete`) stubbed here; implemented in task 27 with `asyncio.run`.
