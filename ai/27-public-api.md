# 27 — Public API: `__init__.py`, `assemble`, sync wrappers, provider self-registration

## Goal

Wire everything together. `import llm_providers` gives callers a working library: model registry populated, providers self-registered, top-level `stream` / `complete` (async) and `sync_stream` / `sync_complete` (sync) entrypoints exported.

Assumes tasks 01–26 complete.

## Refs

- `00-architecture.md` §2 (sync wrappers), §4 (public API)
- `13-registry.md`, `14-provider-base.md`

## Files

1. `src/llm_providers/assemble.py` — drains an event stream into an `AssistantMessage`.
2. `src/llm_providers/_sync.py` — sync wrappers around async functions.
3. `src/llm_providers/providers/__init__.py` — registers built-ins on import.
4. `src/llm_providers/__init__.py` — public re-exports.

## `assemble.py`

```python
"""Drain an event stream into a final AssistantMessage."""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any, AsyncIterator, Literal

from llm_providers.events import (
    Done,
    Error,
    Event,
    MessageEnd,
    MessageStart,
    ReasoningDelta,
    ReasoningEnd,
    ReasoningStart,
    TextDelta,
    TextEnd,
    TextStart,
    ToolCallDelta,
    ToolCallEnd,
    ToolCallStart,
)
from llm_providers.errors import LLMProviderError
from llm_providers.types import (
    AssistantContentPart,
    AssistantMessage,
    ReasoningPart,
    TextPart,
    ToolCallPart,
    Usage,
)


@dataclass(slots=True)
class _PartAccum:
    kind: Literal["text", "reasoning", "tool_call"]
    finalized: bool = False
    signature: str | None = None
    redacted: bool = False
    provider_metadata: dict[str, Any] = field(default_factory=dict)
    tool_id: str | None = None
    tool_name: str | None = None
    tool_arguments: dict[str, Any] | None = None


async def assemble(stream: AsyncIterator[Event]) -> AssistantMessage:
    """Consume an event stream, return the assembled AssistantMessage.

    Drains until `Done`. If an `Error` event is observed, the resulting
    message has `stop_reason="error"` and `error_message` populated; the
    error is NOT re-raised — callers wanting exceptions inspect
    `result.stop_reason`.
    """
    parts: dict[str, _PartAccum] = {}
    order: list[str] = []
    text_buffers: dict[str, list[str]] = {}
    reasoning_buffers: dict[str, list[str]] = {}
    tool_arg_buffers: dict[str, list[str]] = {}
    msg_id = ""
    model_id = ""
    provider = ""
    api = ""
    usage = Usage()
    stop_reason: Any = "end_turn"
    error_message: str | None = None
    response_id: str | None = None

    async for event in stream:
        match event:
            case MessageStart(id=id_, model=m, provider=p, api=a):
                msg_id = id_
                model_id = m
                provider = p
                api = a
            case TextStart(part_id=pid):
                if pid not in parts:
                    parts[pid] = _PartAccum(kind="text")
                    order.append(pid)
                    text_buffers[pid] = []
            case TextDelta(part_id=pid, text=t):
                text_buffers.setdefault(pid, []).append(t)
            case TextEnd(part_id=pid, text=full):
                if full:
                    text_buffers[pid] = [full]
                parts[pid].finalized = True
            case ReasoningStart(part_id=pid):
                if pid not in parts:
                    parts[pid] = _PartAccum(kind="reasoning")
                    order.append(pid)
                    reasoning_buffers[pid] = []
            case ReasoningDelta(part_id=pid, text=t):
                reasoning_buffers.setdefault(pid, []).append(t)
            case ReasoningEnd(part_id=pid, text=full, signature=sig, redacted=red, provider_metadata=meta):
                if full:
                    reasoning_buffers[pid] = [full]
                parts[pid].signature = sig
                parts[pid].redacted = red
                parts[pid].provider_metadata = dict(meta)
                parts[pid].finalized = True
            case ToolCallStart(part_id=pid, id=lib_id, name=name):
                if pid not in parts:
                    parts[pid] = _PartAccum(kind="tool_call", tool_id=lib_id, tool_name=name)
                    order.append(pid)
                    tool_arg_buffers[pid] = []
            case ToolCallDelta(part_id=pid, arguments_delta=d):
                tool_arg_buffers.setdefault(pid, []).append(d)
            case ToolCallEnd(part_id=pid, id=lib_id, name=name, arguments=args):
                parts[pid].tool_id = lib_id
                parts[pid].tool_name = name
                parts[pid].tool_arguments = args
                parts[pid].finalized = True
            case MessageEnd(stop_reason=sr, usage=u, response_id=rid):
                stop_reason = sr
                usage = u
                response_id = rid
            case Error(error=err):
                if isinstance(err, LLMProviderError):
                    error_message = err.message
            case Done():
                break

    content: list[AssistantContentPart] = []
    for pid in order:
        accum = parts[pid]
        if accum.kind == "text":
            content.append(TextPart(text="".join(text_buffers.get(pid, []))))
        elif accum.kind == "reasoning":
            content.append(ReasoningPart(
                text="".join(reasoning_buffers.get(pid, [])),
                signature=accum.signature,
                redacted=accum.redacted,
                provider_metadata=accum.provider_metadata,
            ))
        elif accum.kind == "tool_call":
            content.append(ToolCallPart(
                id=accum.tool_id or "",
                name=accum.tool_name or "",
                arguments=accum.tool_arguments or {},
            ))

    return AssistantMessage(
        content=content,
        api=api,
        provider=provider,
        model=model_id,
        response_id=response_id,
        usage=usage,
        stop_reason=stop_reason,
        error_message=error_message,
    )
```

## `_sync.py`

```python
"""Sync wrappers around async streaming/complete entrypoints."""
from __future__ import annotations
import asyncio
from collections.abc import Iterator
from typing import AsyncIterator

from llm_providers.events import Event
from llm_providers.types import AssistantMessage, Context


def sync_complete(coro_factory) -> AssistantMessage:
    """Run an async `complete()` call to completion in a sync context."""
    return asyncio.run(coro_factory)


def sync_stream(stream_factory: AsyncIterator[Event]) -> Iterator[Event]:
    """Iterate an async stream synchronously.

    Spins up a private loop, drives the async iterator with run_until_complete
    on each __anext__. Acceptable for CLI/REPL use; not for high-throughput.
    """
    loop = asyncio.new_event_loop()
    try:
        agen = stream_factory.__aiter__()
        while True:
            try:
                event = loop.run_until_complete(agen.__anext__())
            except StopAsyncIteration:
                return
            yield event
    finally:
        loop.run_until_complete(_cleanup_async_iter(stream_factory))
        loop.close()


async def _cleanup_async_iter(it) -> None:
    aclose = getattr(it, "aclose", None)
    if aclose is not None:
        try:
            await aclose()
        except Exception:
            pass
```

> **Caveat:** `sync_stream` creates a fresh event loop per call. Inside an existing async context, fails with `RuntimeError: asyncio.run() cannot be called from a running event loop`. Document; recommend the async API for any non-CLI use.

## `providers/__init__.py`

```python
"""Built-in provider registration. Importing this module registers
AnthropicProvider, OpenAIChatCompletionsProvider, OpenAIResponsesProvider,
and (if configured) OpenAICompatibleProvider into the global registry.
"""
from __future__ import annotations

from llm_providers import env, registry
from llm_providers.providers.anthropic import AnthropicProvider
from llm_providers.providers.openai import (
    OpenAIChatCompletionsProvider,
    OpenAICompatibleProvider,
    OpenAIResponsesProvider,
)
from llm_providers.generated_models import MODELS


def _register_models() -> None:
    for model in MODELS.values():
        registry.register_model(model)


def _register_anthropic() -> None:
    api_key = env.get_api_key("anthropic")
    base_url = env.get_base_url("anthropic")
    provider = AnthropicProvider(api_key=api_key, base_url=base_url)
    registry.register_provider("anthropic-messages", provider)


def _register_openai() -> None:
    api_key = env.get_api_key("openai")
    base_url = env.get_base_url("openai")
    completions = OpenAIChatCompletionsProvider(api_key=api_key, base_url=base_url)
    responses = OpenAIResponsesProvider(api_key=api_key, base_url=base_url)
    registry.register_provider("openai-completions", completions)
    registry.register_provider("openai-responses", responses)


def _register_openai_compatible() -> None:
    base_url = env.get_base_url("openai_compatible")
    if not base_url:
        return
    api_key = env.get_api_key("openai_compatible")
    provider = OpenAICompatibleProvider(api_key=api_key, base_url=base_url)
    registry.register_provider("openai-compatible", provider)


_register_models()
_register_anthropic()
_register_openai()
_register_openai_compatible()


__all__ = [
    "AnthropicProvider",
    "OpenAIChatCompletionsProvider",
    "OpenAICompatibleProvider",
    "OpenAIResponsesProvider",
]
```

> Registering at import-time means missing API keys silently produce providers that fail on first request with `BadRequestError("requires an api_key")`. Acceptable: callers can still override later by calling `register_provider(...)` themselves.

## `__init__.py`

```python
"""LLM provider library — unified interface to Anthropic and OpenAI."""
from __future__ import annotations

# Public types
from llm_providers.types import (
    AssistantContentPart,
    AssistantMessage,
    ContentPart,
    Context,
    ImagePart,
    Message,
    ReasoningPart,
    Role,
    StopReason,
    TextPart,
    ToolCallPart,
    ToolDefinition,
    ToolResultMessage,
    Usage,
    UserContentPart,
    UserMessage,
    assistant_text,
    tool_result,
    user,
)

# Events
from llm_providers.events import (
    Done,
    Error,
    Event,
    MessageEnd,
    MessageStart,
    ReasoningDelta,
    ReasoningEnd,
    ReasoningStart,
    TextDelta,
    TextEnd,
    TextStart,
    ToolCallDelta,
    ToolCallEnd,
    ToolCallStart,
)

# Errors
from llm_providers.errors import (
    AbortError,
    APIError,
    AuthError,
    BadRequestError,
    ContextOverflowError,
    LLMProviderError,
    RateLimitError,
    TransportError,
)

# Models / registry / dispatch
from llm_providers.models import ModelInfo, compute_cost_default
from llm_providers.registry import (
    all_models,
    all_providers,
    compute_cost,
    get_model,
    get_provider,
    register_model,
    register_provider,
    reset_cost_function,
    resolve,
    set_cost_function,
)

# Caching helper
from llm_providers.caching import auto_cache

# Top-level dispatch
from llm_providers.registry import stream, complete  # noqa: E402

# Sync wrappers
from llm_providers._sync import (  # noqa: E402
    sync_complete as _sync_complete_impl,
    sync_stream as _sync_stream_impl,
)

# Trigger built-in registration
import llm_providers.providers  # noqa: F401, E402


def sync_stream(model: str, context: Context, **kwargs):
    """Sync wrapper for stream(). See _sync_stream for caveats."""
    return _sync_stream_impl(stream(model, context, **kwargs))


def sync_complete(model: str, context: Context, **kwargs) -> AssistantMessage:
    """Sync wrapper for complete()."""
    return _sync_complete_impl(complete(model, context, **kwargs))


__all__ = [
    # types
    "AssistantContentPart", "AssistantMessage", "ContentPart", "Context",
    "ImagePart", "Message", "ReasoningPart", "Role", "StopReason", "TextPart",
    "ToolCallPart", "ToolDefinition", "ToolResultMessage", "Usage",
    "UserContentPart", "UserMessage", "assistant_text", "tool_result", "user",
    # events
    "Done", "Error", "Event", "MessageEnd", "MessageStart",
    "ReasoningDelta", "ReasoningEnd", "ReasoningStart",
    "TextDelta", "TextEnd", "TextStart",
    "ToolCallDelta", "ToolCallEnd", "ToolCallStart",
    # errors
    "AbortError", "APIError", "AuthError", "BadRequestError",
    "ContextOverflowError", "LLMProviderError", "RateLimitError", "TransportError",
    # models / registry
    "ModelInfo", "compute_cost_default", "all_models", "all_providers",
    "compute_cost", "get_model", "get_provider", "register_model",
    "register_provider", "reset_cost_function", "resolve", "set_cost_function",
    # caching
    "auto_cache",
    # entrypoints
    "stream", "complete", "sync_stream", "sync_complete",
]
```

## Acceptance

- [ ] `assemble.py` correctly assembles a stream of events into an `AssistantMessage`.
- [ ] `complete()` in `registry.py` (placeholder from task 13) is now wired through `assemble`.
- [ ] `sync_stream` and `sync_complete` work from a sync context.
- [ ] `import llm_providers` loads without raising even when no API keys are set.
- [ ] After import, `llm_providers.all_models()` returns the catalogue from `generated_models.MODELS`.
- [ ] After import, `llm_providers.get_provider("anthropic-messages")` returns an `AnthropicProvider` instance.
- [ ] `llm_providers.stream(model="claude-sonnet-4-5", context=Context(...))` resolves and dispatches.
- [ ] `tests/test_assemble.py`:
  - text-only stream → `AssistantMessage` with one `TextPart`
  - mixed text + tool calls → ordered `content` with both kinds
  - reasoning preserves signature
  - `Error` event populates `error_message` and `stop_reason="error"`
  - part order preserved (`text → reasoning → text` doesn't reorder)
- [ ] `tests/test_public_api.py`:
  - `import llm_providers` succeeds
  - `llm_providers.all_models()` non-empty
  - `llm_providers.stream(...)` is callable
  - `sync_stream(...)` yields events synchronously (stub provider)
  - `sync_complete(...)` returns an `AssistantMessage`
- [ ] `basedpyright` clean.

## Notes

- `complete()` in `registry.py` had a forward-reference stub from task 13. This task replaces the lazy `from llm_providers.assemble import assemble` import with a direct import.
- Module load order: `__init__.py` imports `llm_providers.providers` last so providers can `from llm_providers import xyz` if needed during their own import. Avoid circular imports by keeping providers' top-level imports limited to events/types/errors/utils.
- Sync wrappers create a new event loop. Inside an existing async context (Jupyter, FastAPI), use the async API — `sync_*` is for CLI-style entry only. Document in docstrings.
