# 22 — OpenAI Responses provider: request, streaming, basic messages

## Goal

Add `OpenAIResponsesProvider` to `src/llm_providers/providers/openai.py`. Handles the Responses API (`/v1/responses`) — required for o-series reasoning models. Text-only round-trip + streaming. Tools → task 23, reasoning round-trip → task 24, errors → task 25.

## Refs

- `00-architecture.md` §2, §4, §5, §13
- `14-provider-base.md`
- `21-openai-completions-basics.md`
- `pi-mono/packages/ai/src/providers/openai-responses.ts`
- `pi-mono/packages/ai/src/providers/openai-responses-shared.ts`
- OpenAI Responses: https://platform.openai.com/docs/api-reference/responses

## Wire format

`POST {base_url}/responses`:

```json
{
  "model": "o3",
  "input": [
    {"role": "system", "content": [{"type": "input_text", "text": "..."}]},
    {"role": "user", "content": [{"type": "input_text", "text": "..."}]},
    {"role": "assistant", "content": [{"type": "output_text", "text": "..."}]}
  ],
  "stream": true,
  "max_output_tokens": 4096,
  "reasoning": {"effort": "medium"}
}
```

Differences from Completions:

- `input` (not `messages`).
- Each message's `content` is always an array (no string shortcut).
- Content block types: `input_text`, `input_image`, `output_text`, `tool_call`, `tool_result`, `reasoning` (task 24).
- `developer` role replaces `system` for newer models — detect from model id or `compat`.
- `temperature` not allowed for o-series reasoning models.

Response: stream of typed events. Relevant for this task:

- `response.created` — emit `MessageStart`.
- `response.output_item.added` (`item.type=message`) — assistant message starts; track `item.id`.
- `response.content_part.added` (`part.type=output_text`) — emit `TextStart(part_id=item_id + ":" + content_index)`.
- `response.output_text.delta` (`delta="..."`) — emit `TextDelta`.
- `response.content_part.done` (`part.type=output_text`) — emit `TextEnd`.
- `response.output_item.done` — finalize the item.
- `response.completed` — payload includes final `usage`; emit `MessageEnd` + `Done`.
- `response.failed` / `response.incomplete` → emit error tail (task 25).

Reasoning items, tool_use, etc. → defer; pass through silently.

## Implementation skeleton

```python
class OpenAIResponsesProvider(Provider):
    name: ClassVar[str] = "openai"
    api: ClassVar[str] = "openai-responses"
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
            url = f"{(model.base_url or self.base_url).rstrip('/')}/responses"
            try:
                async with self._client.stream(
                    "POST", url, json=request_body, headers=headers
                ) as response:
                    if response.status_code >= 400:
                        body = await response.aread()
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
                raise TransportError(...)

    def _build_request(
        self,
        model: ModelInfo,
        context: Context,
        max_tokens: int | None,
        temperature: float | None,
    ) -> dict[str, object]:
        body: dict[str, object] = {
            "model": model.id,
            "input": _convert_messages_responses(context.system_prompt, context.messages, model),
            "stream": True,
        }
        if max_tokens is not None or model.max_output:
            body["max_output_tokens"] = max_tokens or model.max_output
        if temperature is not None and not _is_reasoning_model(model):
            body["temperature"] = temperature
        return body

    async def _iter_events(self, response, model):
        message_id = ""
        # part_id mapping by (item_id, content_index)
        text_parts: dict[str, str] = {}
        usage = Usage()
        stop_reason: StopReason = "end_turn"
        emitted_start = False

        async for sse in iter_sse(response):
            if not sse.event:
                continue
            try:
                payload = json.loads(sse.data) if sse.data else {}
            except json.JSONDecodeError:
                continue

            ev = sse.event
            if ev == "response.created":
                message_id = payload.get("response", {}).get("id", "")
                yield MessageStart(id=message_id, model=model.id, provider=self.name, api=self.api)
                emitted_start = True
            elif ev == "response.content_part.added":
                part = payload.get("part", {})
                if part.get("type") == "output_text":
                    item_id = payload.get("item_id", "")
                    idx = payload.get("content_index", 0)
                    pid = f"{item_id}:{idx}"
                    text_parts[pid] = pid
                    yield TextStart(part_id=pid)
            elif ev == "response.output_text.delta":
                item_id = payload.get("item_id", "")
                idx = payload.get("content_index", 0)
                pid = f"{item_id}:{idx}"
                yield TextDelta(part_id=pid, text=payload.get("delta", ""))
            elif ev == "response.content_part.done":
                part = payload.get("part", {})
                if part.get("type") == "output_text":
                    item_id = payload.get("item_id", "")
                    idx = payload.get("content_index", 0)
                    pid = f"{item_id}:{idx}"
                    yield TextEnd(part_id=pid, text=part.get("text", ""))
            elif ev == "response.completed":
                resp = payload.get("response", {})
                usage = _parse_responses_usage(resp.get("usage", {}))
                stop_reason = _map_responses_status(resp.get("status"))
            elif ev in {"response.failed", "response.incomplete"}:
                # full mapping in task 25 — placeholder
                resp = payload.get("response", {})
                err = resp.get("error", {}) or resp.get("incomplete_details", {})
                yield Error(error=APIError(
                    err.get("message", "openai responses failed"),
                    provider=self.name,
                    provider_error=payload,
                ))
                yield MessageEnd(stop_reason="error", usage=usage, response_id=message_id)
                yield Done()
                return
            # other events (reasoning, tool_call_*, etc.) — tasks 23/24

        yield MessageEnd(stop_reason=stop_reason, usage=usage, response_id=message_id)
        yield Done()
```

## Helpers

```python
_REASONING_MODEL_PREFIXES = ("o1", "o3", "o4")

def _is_reasoning_model(model: ModelInfo) -> bool:
    return model.id.startswith(_REASONING_MODEL_PREFIXES)


def _system_role_for(model: ModelInfo) -> str:
    """Newer models accept 'developer'; legacy accepts 'system'."""
    if model.compat.get("supports_developer_role"):
        return "developer"
    if _is_reasoning_model(model):
        return "developer"
    return "system"


def _convert_messages_responses(
    system_prompt: str | None,
    messages: list[Message],
    model: ModelInfo,
) -> list[dict[str, object]]:
    out: list[dict[str, object]] = []
    if system_prompt:
        out.append({
            "role": _system_role_for(model),
            "content": [{"type": "input_text", "text": sanitize_surrogates(system_prompt)}],
        })
    for m in messages:
        match m:
            case UserMessage(content=parts):
                blocks = []
                for p in parts:
                    if isinstance(p, TextPart):
                        blocks.append({"type": "input_text", "text": sanitize_surrogates(p.text)})
                    elif isinstance(p, ImagePart):
                        blocks.append({
                            "type": "input_image",
                            "image_url": f"data:{p.mime_type};base64,{p.data}",
                        })
                out.append({"role": "user", "content": blocks})
            case AssistantMessage(content=parts):
                blocks = []
                for p in parts:
                    if isinstance(p, TextPart):
                        blocks.append({"type": "output_text", "text": sanitize_surrogates(p.text)})
                    # reasoning + tool_call → tasks 23/24
                out.append({"role": "assistant", "content": blocks})
            case ToolResultMessage():
                raise NotImplementedError("tool results: task 23")
    return out


def _parse_responses_usage(raw: dict[str, object]) -> Usage:
    pt = int(raw.get("input_tokens") or 0)
    ct = int(raw.get("output_tokens") or 0)
    cached = 0
    details = raw.get("input_tokens_details")
    if isinstance(details, dict):
        cached = int(details.get("cached_tokens") or 0)
    reasoning = 0
    out_details = raw.get("output_tokens_details")
    if isinstance(out_details, dict):
        reasoning = int(out_details.get("reasoning_tokens") or 0)
    return Usage(
        input_tokens=pt - cached,
        output_tokens=ct,
        cache_read_tokens=cached,
        reasoning_tokens=reasoning,
        total_tokens=pt + ct,
    )


def _map_responses_status(status: str | None) -> StopReason:
    return {
        "completed": "end_turn",
        "incomplete": "max_tokens",
        "failed": "error",
        "cancelled": "abort",
    }.get(status or "", "end_turn")
```

## Acceptance

- [ ] `OpenAIResponsesProvider` added to `providers/openai.py`.
- [ ] Request body shape matches wire format above (input array, all-array content blocks, max_output_tokens).
- [ ] System prompt uses `developer` role for o-series, `system` for others.
- [ ] `temperature` omitted for reasoning models.
- [ ] SSE `response.created` → `MessageStart`.
- [ ] `response.content_part.added(output_text)` → `TextStart` with `part_id = item_id + ":" + content_index`.
- [ ] `response.output_text.delta` → `TextDelta`.
- [ ] `response.content_part.done` → `TextEnd`.
- [ ] `response.completed` → `MessageEnd(stop_reason, usage)` + `Done`.
- [ ] `response.failed` / `response.incomplete` → `Error` + `MessageEnd("error")` + `Done`.
- [ ] `tests/test_openai_responses_basics.py` covers each above with mocked HTTP.
- [ ] `basedpyright` clean.

## Out of scope

- Reasoning round-trip / `reasoning.effort` → task 24
- Tool calling → task 23
- Error mapping → task 25
- OpenAI-compatible adapter → task 26 (Completions only; Responses isn't widely supported by third parties)

## Notes

- Responses API is event-typed (`event: response.created`, etc.) rather than data-only chunks. SSE parsing via `iter_sse` already handles named events.
- `part_id` for text blocks: `f"{item_id}:{content_index}"` to disambiguate multiple text parts within the same response item.
- TS reference handles many more event types (annotations, web_search, tool_call_*, reasoning_*, etc.). Ignore everything not listed; later tasks add wiring.
- Don't share a base class with Completions beyond `Provider`. Different URL, different request shape, different streaming protocol — abstraction would be premature.
