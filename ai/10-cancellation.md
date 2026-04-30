# 10 — Cancellation helpers

## Goal

`src/llm_providers/cancellation.py`: small support layer letting a streaming provider honor an optional `abort: asyncio.Event` argument and translate it into clean shutdown.

Secondary mechanism. Primary is `asyncio.CancelledError`, which providers handle without help from this module.

## Refs

- `00-architecture.md` §7
- `pi-mono/packages/ai/src/types.ts:70` (`signal?: AbortSignal` — TS shape we mirror)

## Module

```python
from __future__ import annotations
import asyncio
from contextlib import asynccontextmanager
from typing import AsyncIterator

from llm_providers.errors import AbortError


@asynccontextmanager
async def watch_abort(
    abort: asyncio.Event | None,
    *,
    provider: str = "",
) -> AsyncIterator[None]:
    """Cancel the enclosing task when `abort` is set.

    Usage::

        async with watch_abort(abort, provider="anthropic"):
            async for event in provider_stream():
                yield event

    Implementation: starts a background task that waits on `abort.wait()`.
    When the event fires, the background task cancels the current task.
    On normal exit, the background task is cancelled and awaited.

    No-op if `abort` is None.
    """
    if abort is None:
        yield
        return

    current = asyncio.current_task()
    if current is None:
        # Should not happen inside a coroutine, but be defensive.
        yield
        return

    async def _watcher() -> None:
        try:
            await abort.wait()
        except asyncio.CancelledError:
            return
        # Cancel the current task; the provider's exception handler
        # distinguishes CancelledError-from-abort using `abort.is_set()`.
        current.cancel()

    watcher_task = asyncio.create_task(_watcher(), name=f"{provider}-abort-watcher")
    try:
        yield
    finally:
        watcher_task.cancel()
        try:
            await watcher_task
        except asyncio.CancelledError:
            pass


def is_aborted(abort: asyncio.Event | None) -> bool:
    """True if `abort` is non-None and set. Convenience for explicit polling."""
    return abort is not None and abort.is_set()


__all__ = ["watch_abort", "is_aborted", "AbortError"]
```

## Provider-side usage pattern

Each provider's streaming method follows this structure:

```python
async def stream(self, ..., *, abort: asyncio.Event | None = None) -> AsyncIterator[Event]:
    async with watch_abort(abort, provider="anthropic"):
        try:
            async for raw in self._http_stream(...):
                if is_aborted(abort):
                    break
                yield self._translate(raw)
        except asyncio.CancelledError:
            if abort is not None and abort.is_set():
                # cancellation was triggered by our abort event
                yield MessageEnd(stop_reason="abort", usage=...)
                yield Done()
                return
            # cancellation came from the caller's task being cancelled
            yield MessageEnd(stop_reason="abort", usage=...)
            yield Done()
            raise
```

Provider tasks (16–25) reference this pattern; do not duplicate the logic here.

## Acceptance

- [ ] Exports `watch_abort`, `is_aborted`. Re-exports `AbortError` from errors.
- [ ] `tests/test_cancellation.py`:
  - `watch_abort(None)` is a no-op (no background task spawned, body runs to completion)
  - `watch_abort(event)` with event never set runs body to completion + cleans up watcher
  - `watch_abort(event)`: setting the event during the body raises `asyncio.CancelledError` inside the body
  - `is_aborted(None)` is False
  - `is_aborted(asyncio.Event())` is False; after `.set()`, True
  - watcher task cleaned up on normal exit (no orphans in `asyncio.all_tasks()` at teardown)
- [ ] `basedpyright` clean.

## Notes

- `asyncio.current_task()` returns None outside a task. Guarded for sanity.
- Watcher task named for diagnostic visibility.
- `AbortError` re-export so callers can `from llm_providers.cancellation import AbortError, watch_abort`. Canonical home is still `errors.py`.
