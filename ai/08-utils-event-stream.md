# 08 — SSE / event-stream HTTP helper

## Goal

`src/llm_providers/utils/event_stream.py`: async generator consuming `httpx.Response` body, yielding decoded SSE messages. Every provider adapter uses this.

## Refs

- TS reference is per-provider (`pi-ai/providers/anthropic.ts:311`+ defines `iterateSseMessages`); we extract it into a shared utility because all three Python providers consume SSE the same way.
- `00-architecture.md` §2 (async-first)

## Module

```python
from __future__ import annotations
from dataclasses import dataclass
from typing import AsyncIterator

import httpx


@dataclass(slots=True, frozen=True)
class SSEMessage:
    event: str | None      # named event type; None if absent
    data: str              # joined data lines (newlines preserved between them)
    id: str | None         # last-event-id; None if absent
    raw: tuple[str, ...]   # raw lines (pre-decode), kept for diagnostic logging


async def iter_sse(response: httpx.Response) -> AsyncIterator[SSEMessage]:
    """Yield one SSEMessage per dispatched event from `response.aiter_lines()`.

    Honors the SSE spec:
      - blank line dispatches the current event
      - lines beginning with ':' are comments (ignored)
      - 'data:', 'event:', 'id:' fields are accumulated
      - data fields concatenate with '\\n' between them
      - leading single space after the colon is stripped

    Raises:
      httpx.TransportError on connection issues (caller wraps in TransportError).
      httpx.HTTPStatusError if response was a non-2xx (caller raises before iter).

    The caller is responsible for cancellation; this generator propagates
    asyncio.CancelledError without buffering.
    """
    event: str | None = None
    data_lines: list[str] = []
    last_id: str | None = None
    raw: list[str] = []

    async for line in response.aiter_lines():
        raw.append(line)
        # SSE spec: line endings are normalized by aiter_lines; blank line dispatches
        if line == "":
            if data_lines or event is not None:
                yield SSEMessage(
                    event=event,
                    data="\n".join(data_lines),
                    id=last_id,
                    raw=tuple(raw),
                )
            event = None
            data_lines = []
            raw = []
            continue
        if line.startswith(":"):
            continue  # comment
        field, _, value = line.partition(":")
        if value.startswith(" "):
            value = value[1:]
        if field == "data":
            data_lines.append(value)
        elif field == "event":
            event = value or None
        elif field == "id":
            last_id = value or None
        # 'retry:' and unknown fields are ignored

    # If the stream ends without a trailing blank line, dispatch any pending event
    if data_lines or event is not None:
        yield SSEMessage(
            event=event,
            data="\n".join(data_lines),
            id=last_id,
            raw=tuple(raw),
        )
```

## Acceptance

- [ ] `SSEMessage`, `iter_sse` exported.
- [ ] `tests/test_event_stream.py`:
  - basic `event: foo\ndata: bar\n\n` → one `SSEMessage(event="foo", data="bar")`
  - multi-line data `data: a\ndata: b\n\n` → `data == "a\nb"`
  - comment lines (`:`) ignored
  - lines without colons ignored (per spec field=line, value=""; we only act on `data`/`event`/`id`)
  - leading single space after colon stripped (`data: hi\n\n` → `data == "hi"`); two spaces preserves the second
  - stream ending without trailing blank dispatches pending event
  - empty stream yields nothing
  - `id: 123\n\n` → `SSEMessage.id == "123"`
- Tests use `httpx.MockTransport` to construct a streaming `Response`. `unittest.IsolatedAsyncioTestCase`.
- [ ] `basedpyright` clean. No `Any`.

## Notes

- Imports: `httpx` only. No `llm_providers` deps.
- `aiter_lines()` handles `\r\n` / `\n` / `\r`. Don't roll a byte-level parser unless a real provider breaks this.
- `raw` field included so providers can include raw lines in diagnostics when SSE `data` fails to parse (TS does this — `anthropic.ts:392`).
- Spec corners not implemented (no provider uses them): `retry:` field, BOM stripping at start of stream. Add only when needed.
