# 16 — Anthropic provider: request shaping, basic streaming, message round-trip

## Goal

`src/llm_providers/providers/anthropic.py` exporting `AnthropicProvider` (`Provider` subclass for `api="anthropic-messages"`). Minimum viable adapter: user/assistant text round-trip with streaming `Text*` events. Subsequent tasks (17–20) layer features on top.

## Refs

- `00-architecture.md` §2, §4, §5, §13
- `14-provider-base.md`
- `pi-mono/packages/ai/src/providers/anthropic.ts:398-658` (`streamAnthropic` lifecycle)
- `pi-mono/packages/ai/src/providers/anthropic.ts:944-1108` (`convertMessages`)
- Anthropic API: https://docs.anthropic.com/en/api/messages

## Wire format (subset for this task)

`POST {base_url}/v1/messages`:

```json
{
  "model": "claude-...",
  "max_tokens": 4096,
  "system": "<optional system prompt>",
  "messages": [
    {"role": "user", "content": [{"type": "text", "text": "..."}]},
    {"role": "assistant", "content": [{"type": "text", "text": "..."}]}
  ],
  "stream": true,
  "temperature": 0.0
}
```

Headers:

- `x-api-key: <key>`
- `anthropic-version: 2023-06-01`
- `Content-Type: application/json`
- `Accept: application/json`
- `User-Agent: llm-providers/<version>`

Response: SSE stream. Relevant events:

- `message_start` → `MessageStart`
- `content_block_start` (type=text) → `TextStart(part_id=index)`
- `content_block_delta` (type=text_delta) → `TextDelta`
- `content_block_stop` → `TextEnd`
- `message_delta` (with `stop_reason`, partial usage)
- `message_stop` → `MessageEnd` + `Done`

All other events (tool_use, thinking, ping, error, etc.) → no-op in this task.

## Module skeleton

```python
"""Anthropic Messages API provider."""
from __future__ import annotations
import asyncio
import json
import secrets
from typing import AsyncIterator, ClassVar

import httpx

from llm_providers.cancellation import is_aborted, watch_abort
from llm_providers.errors import APIError, BadRequestError, TransportError
from llm_providers.events import (
    Done,
    Event,
    MessageEnd,
    MessageStart,
    TextDelta,
    TextEnd,
    TextStart,
)
from llm_providers.models import ModelInfo
from llm_providers.provider import Provider
from llm_providers.types import (
    AssistantMessage,
    Context,
    Message,
    StopReason,
    TextPart,
    Usage,
    UserMessage,
    ImagePart,
    ToolResultMessage,
)
from llm_providers.utils.event_stream import iter_sse
from llm_providers.utils.headers import json_headers, merge_headers
from llm_providers.utils.sanitize_unicode import sanitize_surrogates


class AnthropicProvider(Provider):
    name: ClassVar[str] = "anthropic"
    api: ClassVar[str] = "anthropic-messages"
    default_base_url: ClassVar[str] = "https://api.anthropic.com"

    async def stream(
        self,
        model: ModelInfo,
        context: Context,
        *,
        abort: asyncio.Event | None = None,
        max_tokens: int | None = None,
        temperature: float | None = None,
        **options: object,
    ) -> AsyncIterator[Event]:
        async with watch_abort(abort, provider=self.name):
            request_body = self._build_request(model, context, max_tokens, temperature)
            headers = self._build_headers()
            url = f"{(model.base_url or self.base_url).rstrip('/')}/v1/messages"
            try:
                async with self._client.stream(
                    "POST", url, json=request_body, headers=headers
                ) as response:
                    if response.status_code >= 400:
                        # Full mapping: task 20
                        body = await response.aread()
                        raise APIError(
                            f"anthropic returned {response.status_code}",
                            provider=self.name,
                            status_code=response.status_code,
                            provider_error={"raw": body.decode("utf-8", "replace")},
                        )
                    async for event in self._iter_events(response, model):
                        if is_aborted(abort):
                            break
                        yield event
            except httpx.TransportError as exc:
                raise TransportError(
                    f"anthropic transport failure: {exc}",
                    provider=self.name,
                    cause=exc,
                )

    def _build_request(
        self,
        model: ModelInfo,
        context: Context,
        max_tokens: int | None,
        temperature: float | None,
    ) -> dict[str, object]:
        body: dict[str, object] = {
            "model": model.id,
            "max_tokens": max_tokens or model.max_output or 4096,
            "messages": _convert_messages(context.messages),
            "stream": True,
        }
        if context.system_prompt:
            body["system"] = sanitize_surrogates(context.system_prompt)
        if temperature is not None:
            body["temperature"] = temperature
        return body

    def _build_headers(self) -> dict[str, str]:
        if not self.api_key:
            raise BadRequestError("anthropic provider requires an api_key", provider=self.name)
        return json_headers(extra={
            "x-api-key": self.api_key,
            "anthropic-version": "2023-06-01",
        })

    async def _iter_events(
        self, response: httpx.Response, model: ModelInfo
    ) -> AsyncIterator[Event]:
        message_id = ""
        # part_index → part_id mapping for this stream
        parts: dict[int, str] = {}
        usage = Usage()
        stop_reason: StopReason = "end_turn"

        async for sse in iter_sse(response):
            if not sse.event or sse.event == "ping":
                continue
            try:
                payload = json.loads(sse.data)
            except json.JSONDecodeError as exc:
                raise APIError(
                    f"anthropic SSE parse failed: {exc}; data={sse.data!r}",
                    provider=self.name,
                )

            ev_type = payload.get("type")
            if ev_type == "message_start":
                message_id = payload["message"]["id"]
                yield MessageStart(
                    id=message_id, model=model.id, provider=self.name, api=self.api
                )
                # Initial usage (input_tokens / cache_*_tokens) appears here
                _accumulate_usage(usage, payload["message"].get("usage", {}))
            elif ev_type == "content_block_start":
                block = payload["content_block"]
                index = payload["index"]
                part_id = f"part_{index}"
                parts[index] = part_id
                if block["type"] == "text":
                    yield TextStart(part_id=part_id)
                # tool_use / thinking handled in tasks 17 / 18
            elif ev_type == "content_block_delta":
                delta = payload["delta"]
                index = payload["index"]
                part_id = parts.get(index, f"part_{index}")
                if delta["type"] == "text_delta":
                    yield TextDelta(part_id=part_id, text=delta["text"])
                # thinking_delta / input_json_delta handled in later tasks
            elif ev_type == "content_block_stop":
                index = payload["index"]
                part_id = parts.get(index, f"part_{index}")
                # Track type per-index in later tasks; emit TextEnd here.
                yield TextEnd(part_id=part_id, text="")
            elif ev_type == "message_delta":
                _accumulate_usage(usage, payload.get("usage", {}))
                if "stop_reason" in payload.get("delta", {}):
                    stop_reason = _map_stop_reason(payload["delta"]["stop_reason"])
            elif ev_type == "message_stop":
                pass
            elif ev_type == "error":
                # Defer rich mapping to task 20
                err_msg = payload.get("error", {}).get("message", "unknown error")
                raise APIError(err_msg, provider=self.name, provider_error=payload)

        usage = Usage(
            input_tokens=usage.input_tokens,
            output_tokens=usage.output_tokens,
            cache_read_tokens=usage.cache_read_tokens,
            cache_write_tokens=usage.cache_write_tokens,
            total_tokens=usage.input_tokens + usage.output_tokens,
        )
        yield MessageEnd(stop_reason=stop_reason, usage=usage, response_id=message_id)
        yield Done()


def _convert_messages(messages: list[Message]) -> list[dict[str, object]]:
    """Transform Message list to Anthropic wire format.

    For this task: only TextPart in user/assistant content; ImagePart in
    user. Tool calls / tool results raise NotImplementedError — tasks 17/18
    fill those in.
    """
    out: list[dict[str, object]] = []
    for m in messages:
        match m:
            case UserMessage(content=parts):
                content = []
                for p in parts:
                    if isinstance(p, TextPart):
                        content.append({"type": "text", "text": sanitize_surrogates(p.text)})
                    elif isinstance(p, ImagePart):
                        content.append({
                            "type": "image",
                            "source": {
                                "type": "base64",
                                "media_type": p.mime_type,
                                "data": p.data,
                            },
                        })
                out.append({"role": "user", "content": content})
            case AssistantMessage(content=parts):
                content = []
                for p in parts:
                    if isinstance(p, TextPart):
                        content.append({"type": "text", "text": sanitize_surrogates(p.text)})
                    # ReasoningPart / ToolCallPart in later tasks
                out.append({"role": "assistant", "content": content})
            case ToolResultMessage():
                raise NotImplementedError("tool results: task 17")
    return out


def _accumulate_usage(usage: Usage, raw: dict[str, object]) -> None:
    """In-place-ish update. `Usage` is frozen, so this stub is shape-only.

    Implementer: choose either (a) mutable accumulator dataclass + build the
    frozen Usage at the end, or (b) collect a dict and build the final Usage
    once. Recommend (a). Slots'd for cheap allocation.
    """
    raise NotImplementedError("implementer: choose one of the strategies above")


def _map_stop_reason(raw: str) -> StopReason:
    return {
        "end_turn": "end_turn",
        "max_tokens": "max_tokens",
        "stop_sequence": "stop_sequence",
        "tool_use": "tool_use",
        "refusal": "refusal",
    }.get(raw, "end_turn")
```

The skeleton above is illustrative. The implementer must:

- Choose a Usage accumulation strategy (mutable accumulator + frozen `Usage` constructor at the end is recommended).
- Track block type per-index (`{int: Literal["text", "thinking", "tool_use"]}`) so `content_block_stop` emits the right End event. For this task only the `text` branch is wired; the dict structure is established here so later tasks just add cases.
- Handle `model.headers` if `ModelInfo.compat["headers"]` is set (Anthropic-compatible endpoints).

## Acceptance

- [ ] `AnthropicProvider` exported from `providers/anthropic.py`.
- [ ] `tests/test_anthropic_basics.py` (mocked HTTP via `httpx.MockTransport`):
  - request body: `model`, `max_tokens`, `messages`, `stream=True`, `system` populated when `context.system_prompt` set
  - headers include `x-api-key`, `anthropic-version: 2023-06-01`
  - missing `api_key` → `BadRequestError` before any HTTP attempt
  - SSE `message_start` → `content_block_start(text)` → 2× `content_block_delta(text_delta)` → `content_block_stop` → `message_delta(stop_reason=end_turn, usage)` → `message_stop` produces: `MessageStart`, `TextStart`, 2× `TextDelta`, `TextEnd`, `MessageEnd(stop_reason="end_turn")`, `Done`
  - cumulative usage from `message_start.usage` + `message_delta.usage` correct on final `MessageEnd`
  - non-2xx response → `APIError` with `status_code`
  - `httpx.TransportError` → `TransportError`
  - cancellation: setting `abort` mid-stream → `MessageEnd(stop_reason="abort")` + `Done`
  - asyncio.CancelledError mid-stream → `MessageEnd(stop_reason="abort")` + `Done`, re-raises
  - text content `sanitize_surrogates`-cleaned before sending
- [ ] `basedpyright` clean.
- [ ] `providers/__init__.py` registers `AnthropicProvider()` (when `ANTHROPIC_API_KEY` set; else registration deferred to first use).

## Out of scope

- Tool calling (`tool_use` blocks) → task 17
- Reasoning / thinking blocks → task 18
- Prompt caching markers → task 19
- Rich error mapping → task 20
- OAuth → out of scope (architecture §1)

## Notes

- Anthropic `index` on content blocks is per-message, starts at 0. We use `f"part_{index}"` as `part_id`. Stable within a stream; not stable across streams.
- No Anthropic SDK. Direct `httpx`. Shared SSE infra (task 08).
- `_accumulate_usage` is a stub. Recommend a `_UsageAccumulator` dataclass with mutable `int` fields + `__slots__`.
