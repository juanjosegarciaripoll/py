# 21 — OpenAI Completions provider: request, streaming, basic messages

## Goal

`src/llm_providers/providers/openai.py` containing `OpenAIChatCompletionsProvider`. This task: Chat Completions (`/v1/chat/completions`), text-only round-trip + streaming. Tools → task 23, Responses API → task 22, reasoning → task 24, errors → task 25.

## Naming

The module hosts both Completions and Responses adapters. **Two classes in one file**: `OpenAIChatCompletionsProvider` (`api="openai-completions"`) and `OpenAIResponsesProvider` (`api="openai-responses"`). Both subclass `Provider`. Both registered separately. The OpenAI-compatible adapter (task 26) subclasses `OpenAIChatCompletionsProvider`.

This task creates `OpenAIChatCompletionsProvider`. Task 22 creates `OpenAIResponsesProvider`.

## Refs

- `00-architecture.md` §2, §4, §5, §6, §13
- `14-provider-base.md`
- `pi-mono/packages/ai/src/providers/openai-completions.ts:110-398` (`streamOpenAICompletions`)
- `pi-mono/packages/ai/src/providers/openai-completions.ts:465-573` (`buildParams`)
- `pi-mono/packages/ai/src/providers/openai-completions.ts:695-938` (`convertMessages` — for shape; port basic text branches only)
- OpenAI Chat Completions: https://platform.openai.com/docs/api-reference/chat

## Wire format

`POST {base_url}/chat/completions`:

```json
{
  "model": "gpt-4o",
  "messages": [
    {"role": "system", "content": "..."},
    {"role": "user", "content": "..."},
    {"role": "assistant", "content": "..."}
  ],
  "stream": true,
  "stream_options": {"include_usage": true},
  "max_completion_tokens": 4096,
  "temperature": 0.0
}
```

Headers: `Authorization: Bearer <key>` + standard JSON headers.

Response: SSE stream of `data: {chunk}\n\n`. Last data line: `data: [DONE]`. Each chunk:

```json
{
  "id": "chatcmpl-...",
  "choices": [
    {"index": 0, "delta": {"content": "...", "role": "assistant"}, "finish_reason": null}
  ],
  "usage": null
}
```

`finish_reason`: `"stop" | "length" | "tool_calls" | "content_filter" | "function_call"`.

## Implementation skeleton

```python
"""OpenAI Chat Completions API provider."""
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
    ImagePart,
    ToolResultMessage,
    Usage,
    UserMessage,
)
from llm_providers.utils.event_stream import iter_sse
from llm_providers.utils.headers import json_headers
from llm_providers.utils.sanitize_unicode import sanitize_surrogates


class OpenAIChatCompletionsProvider(Provider):
    name: ClassVar[str] = "openai"
    api: ClassVar[str] = "openai-completions"
    default_base_url: ClassVar[str] = "https://api.openai.com/v1"

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
            url = f"{(model.base_url or self.base_url).rstrip('/')}/chat/completions"
            try:
                async with self._client.stream(
                    "POST", url, json=request_body, headers=headers
                ) as response:
                    if response.status_code >= 400:
                        body = await response.aread()
                        # Replace with full mapping in task 25
                        raise APIError(
                            f"openai returned {response.status_code}",
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
                    f"openai transport failure: {exc}",
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
            "messages": _convert_messages(context.system_prompt, context.messages),
            "stream": True,
            "stream_options": {"include_usage": True},
        }
        if max_tokens is not None or model.max_output:
            field = _max_tokens_field(model)
            body[field] = max_tokens or model.max_output
        if temperature is not None:
            body["temperature"] = temperature
        return body

    def _build_headers(self) -> dict[str, str]:
        if not self.api_key:
            raise BadRequestError(
                "openai provider requires an api_key", provider=self.name
            )
        return json_headers(api_key=self.api_key)

    async def _iter_events(
        self, response: httpx.Response, model: ModelInfo
    ) -> AsyncIterator[Event]:
        message_id = ""
        text_open = False
        text_part_id = "part_text_0"
        accumulated_text: list[str] = []
        usage = Usage()
        stop_reason: StopReason = "end_turn"
        emitted_start = False

        async for sse in iter_sse(response):
            if sse.data == "[DONE]":
                break
            try:
                chunk = json.loads(sse.data)
            except json.JSONDecodeError as exc:
                raise APIError(
                    f"openai SSE parse failed: {exc}; data={sse.data!r}",
                    provider=self.name,
                )

            if not emitted_start:
                message_id = chunk.get("id", "")
                yield MessageStart(
                    id=message_id,
                    model=model.id,
                    provider=self.name,
                    api=self.api,
                )
                emitted_start = True

            choices = chunk.get("choices", [])
            if choices:
                choice = choices[0]
                delta = choice.get("delta", {}) or {}
                content = delta.get("content")
                if content:
                    if not text_open:
                        yield TextStart(part_id=text_part_id)
                        text_open = True
                    yield TextDelta(part_id=text_part_id, text=content)
                    accumulated_text.append(content)
                finish_reason = choice.get("finish_reason")
                if finish_reason:
                    stop_reason = _map_finish_reason(finish_reason)

            chunk_usage = chunk.get("usage")
            if chunk_usage:
                usage = _parse_usage(chunk_usage)

        if text_open:
            yield TextEnd(part_id=text_part_id, text="".join(accumulated_text))
        yield MessageEnd(stop_reason=stop_reason, usage=usage, response_id=message_id)
        yield Done()
```

## Helpers

```python
def _max_tokens_field(model: ModelInfo) -> str:
    """Reasoning models (o-series) require max_completion_tokens; legacy uses max_tokens."""
    field = model.compat.get("max_tokens_field") if model.compat else None
    if field in {"max_tokens", "max_completion_tokens"}:
        return field  # type: ignore[return-value]
    if model.id.startswith(("o1", "o3", "o4")):
        return "max_completion_tokens"
    return "max_tokens"


def _map_finish_reason(reason: str) -> StopReason:
    return {
        "stop": "end_turn",
        "length": "max_tokens",
        "tool_calls": "tool_use",
        "function_call": "tool_use",
        "content_filter": "refusal",
    }.get(reason, "end_turn")


def _parse_usage(raw: dict[str, object]) -> Usage:
    pt = int(raw.get("prompt_tokens") or 0)
    ct = int(raw.get("completion_tokens") or 0)
    cached = 0
    details = raw.get("prompt_tokens_details")
    if isinstance(details, dict):
        cached = int(details.get("cached_tokens") or 0)
    reasoning = 0
    out_details = raw.get("completion_tokens_details")
    if isinstance(out_details, dict):
        reasoning = int(out_details.get("reasoning_tokens") or 0)
    return Usage(
        input_tokens=pt - cached,
        output_tokens=ct,
        cache_read_tokens=cached,
        reasoning_tokens=reasoning,
        total_tokens=pt + ct,
    )


def _convert_messages(
    system_prompt: str | None, messages: list[Message]
) -> list[dict[str, object]]:
    """Convert Message list to OpenAI Chat Completions format.

    For this task: text-only user/assistant + image content in user.
    Tool calling and reasoning round-trip handled in tasks 23/24.
    """
    out: list[dict[str, object]] = []
    if system_prompt:
        out.append({"role": "system", "content": sanitize_surrogates(system_prompt)})

    for m in messages:
        match m:
            case UserMessage(content=parts):
                content = _convert_user_content(parts)
                out.append({"role": "user", "content": content})
            case AssistantMessage(content=parts):
                texts = [p.text for p in parts if isinstance(p, TextPart)]
                out.append({
                    "role": "assistant",
                    "content": sanitize_surrogates("".join(texts)),
                })
            case ToolResultMessage():
                raise NotImplementedError("tool results: task 23")
    return out


def _convert_user_content(
    parts: list[TextPart | ImagePart],
) -> str | list[dict[str, object]]:
    """If only text, return a string; else array form with image_url blocks."""
    if all(isinstance(p, TextPart) for p in parts):
        return sanitize_surrogates("".join(p.text for p in parts if isinstance(p, TextPart)))
    blocks: list[dict[str, object]] = []
    for p in parts:
        if isinstance(p, TextPart):
            blocks.append({"type": "text", "text": sanitize_surrogates(p.text)})
        elif isinstance(p, ImagePart):
            blocks.append({
                "type": "image_url",
                "image_url": {
                    "url": f"data:{p.mime_type};base64,{p.data}",
                },
            })
    return blocks
```

## Acceptance

- [ ] `OpenAIChatCompletionsProvider` exported from `providers/openai.py`.
- [ ] `tests/test_openai_completions_basics.py` (`httpx.MockTransport`):
  - request body shape with `model`, `messages`, `stream=True`, `stream_options.include_usage=True`
  - system prompt becomes the first message with `role: "system"`
  - user content all-text → string form; with image → array form with `image_url` block
  - headers include `Authorization: Bearer <key>`
  - missing api key → `BadRequestError`
  - SSE response with one chunk emitting `"Hi"` then a final chunk with `finish_reason: "stop"` and `usage` → `MessageStart`, `TextStart`, `TextDelta("Hi")`, `TextEnd`, `MessageEnd(stop_reason="end_turn", usage=...)`, `Done`
  - `[DONE]` SSE marker terminates the stream
  - `_map_finish_reason` translates each known value
  - `_parse_usage` parses cached/reasoning token detail subfields
  - `_max_tokens_field` returns `max_completion_tokens` for `o3-mini` and `max_tokens` for `gpt-4o`
  - cancellation: `abort.set()` mid-stream → `MessageEnd(stop_reason="abort")` + `Done`
  - asyncio.CancelledError propagates after emitting abort tail
  - text content sanitized for unpaired surrogates
- [ ] `basedpyright` clean.

## Out of scope

- Tool calling → task 23
- Responses API entirely → task 22
- Reasoning round-trip / `reasoning_effort` parameter → task 24
- Error mapping → task 25
- OpenAI-compatible adapter → task 26
- `cache_control` for Anthropic-compat servers — not implemented (architecture §1)

## Notes

- `stream_options.include_usage: True` essential — without it, OpenAI doesn't send a usage block in streaming responses.
- `[DONE]` marker is literal `data: [DONE]\n\n` — `iter_sse` delivers as `SSEMessage(data="[DONE]")`. Compare on `sse.data == "[DONE]"`.
- `_parse_usage` deducts cached tokens from input total to avoid double-counting (matches pi-ai's `parseChunkUsage`).
- Two adapters (Completions / Responses) keeping separate matches TS and lets each evolve independently.
