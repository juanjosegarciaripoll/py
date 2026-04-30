# 23 — OpenAI tool calling (Completions + Responses)

## Goal

Add tool-calling support to **both** `OpenAIChatCompletionsProvider` and `OpenAIResponsesProvider`. The two APIs have very different shapes; work is duplicated but symmetric.

## Refs

- `00-architecture.md` §8
- `17-anthropic-tools.md` (parallel — same conceptual contract)
- `pi-mono/packages/ai/src/providers/openai-completions.ts` — search `tool_calls`, `convertMessages`
- `pi-mono/packages/ai/src/providers/openai-responses.ts` — search `function_call`, `function_call_output`

## Part A — Completions API

### Request additions

```json
{
  ...,
  "tools": [
    {
      "type": "function",
      "function": {
        "name": "read_file",
        "description": "Read a file from disk",
        "parameters": {"type": "object", "properties": {...}}
      }
    }
  ]
}
```

### Streaming additions

Tool calls in Completions stream via `delta.tool_calls` arrays:

```json
{"choices": [{"delta": {"tool_calls": [
  {"index": 0, "id": "call_abc", "type": "function",
   "function": {"name": "read_file", "arguments": ""}}
]}}]}
```

Subsequent chunks send only changing fields:

```json
{"choices": [{"delta": {"tool_calls": [
  {"index": 0, "function": {"arguments": "{\"path\":"}}
]}}]}
{"choices": [{"delta": {"tool_calls": [
  {"index": 0, "function": {"arguments": "\"/tmp\"}"}}
]}}]}
```

`index` correlates fragments. Final `finish_reason: "tool_calls"`.

### Adapter behavior

Track per-index state:

```python
@dataclass
class _ToolCallAccum:
    library_id: str        # call_<8 hex>
    provider_id: str       # OpenAI call_abc...
    name: str = ""
    args_buffer: str = ""
    started: bool = False
    closed: bool = False
```

On first arrival of an index: generate library id (`secrets.token_hex(4)`-derived), record `provider_id`, emit `ToolCallStart`. On every `arguments` fragment: emit `ToolCallDelta(arguments_delta=fragment)`, append to buffer. On `finish_reason: "tool_calls"`: close all open tool calls — parse with `parse_streaming_json`, emit `ToolCallEnd` per index in order.

### Tool-result message conversion

OpenAI Completions wire format:

```json
{"role": "tool", "tool_call_id": "call_abc...", "content": "..."}
```

`content` is a string in Chat Completions; image content in tool results is rejected. Architecture §8: split into a synthetic follow-up user message.

```python
case ToolResultMessage(tool_call_id=lib_id, content=parts, is_error=is_error):
    provider_id = _resolve_provider_id(messages, lib_id) or lib_id
    text_parts = [p.text for p in parts if isinstance(p, TextPart)]
    image_parts = [p for p in parts if isinstance(p, ImagePart)]
    text = "".join(text_parts) or ("" if not is_error else "Tool error.")
    if is_error:
        text = f"[error] {text}"
    out.append({
        "role": "tool",
        "tool_call_id": provider_id,
        "content": sanitize_surrogates(text),
    })
    if image_parts:
        # OpenAI Completions does not allow image content in tool messages.
        # Inject a synthetic user message with the images so they reach the model.
        blocks = [
            {"type": "text", "text": f"[images returned by tool {tool_name}]"},
            *[
                {"type": "image_url",
                 "image_url": {"url": f"data:{p.mime_type};base64,{p.data}"}}
                for p in image_parts
            ],
        ]
        out.append({"role": "user", "content": blocks})
```

### Assistant message round-trip with tool calls

```python
case AssistantMessage(content=parts):
    text_buf: list[str] = []
    tool_calls: list[dict] = []
    for p in parts:
        match p:
            case TextPart(text=t):
                text_buf.append(t)
            case ToolCallPart(id=lib, name=n, arguments=args, provider_id=pid):
                tool_calls.append({
                    "id": pid or lib,
                    "type": "function",
                    "function": {"name": n, "arguments": json.dumps(args)},
                })
    msg: dict[str, object] = {"role": "assistant"}
    if text_buf:
        msg["content"] = sanitize_surrogates("".join(text_buf))
    else:
        msg["content"] = None  # OpenAI permits null content when only tool calls
    if tool_calls:
        msg["tool_calls"] = tool_calls
    out.append(msg)
```

## Part B — Responses API

### Request additions

Responses API uses a flatter `tools` array:

```json
{
  ...,
  "tools": [
    {"type": "function", "name": "read_file", "description": "...",
     "parameters": {...}}
  ]
}
```

(No nested `function:` object — flat fields under `type: "function"`.)

### Streaming additions

Tool calls appear as separate `output_item`s:

- `response.output_item.added` with `item.type=function_call`, `item.id`, `item.call_id`, `item.name` → emit `ToolCallStart(part_id=item_id, id=<library_id>, name=item.name)` and remember `library_id ↔ item.call_id`.
- `response.function_call_arguments.delta` → emit `ToolCallDelta(arguments_delta=delta)`.
- `response.output_item.done` for the function_call item → parse buffer, emit `ToolCallEnd(arguments=parsed)`.

### Tool-result message conversion (Responses)

In Responses API, tool results are top-level input items with `type: "function_call_output"`:

```json
{"type": "function_call_output", "call_id": "call_abc...", "output": "..."}
```

`output` is a string. Same image-fallback strategy: text in `output`, images in a synthetic `user` follow-up.

```python
case ToolResultMessage(tool_call_id=lib_id, content=parts, is_error=is_error):
    provider_id = _resolve_provider_id(messages, lib_id) or lib_id
    # ... text/image split ...
    out.append({
        "type": "function_call_output",
        "call_id": provider_id,
        "output": text,
    })
    if image_parts:
        out.append({"role": "user", "content": [
            {"type": "input_text", "text": f"[images returned by tool]"},
            *[{"type": "input_image", "image_url": f"data:{p.mime_type};base64,{p.data}"}
              for p in image_parts],
        ]})
```

### Assistant tool-call round-trip (Responses)

Assistant tool calls are separate items:

```json
[
  {"type": "function_call", "call_id": "call_abc", "name": "read_file",
   "arguments": "{\"path\":\"/tmp\"}", "id": "fc_..."},
  {"type": "function_call_output", "call_id": "call_abc", "output": "..."}
]
```

A single Python `AssistantMessage` with both text and tool calls becomes multiple input items — one per text block, one per tool call. Conversion fans out:

```python
case AssistantMessage(content=parts):
    text_blocks = []
    for p in parts:
        match p:
            case TextPart(text=t):
                text_blocks.append({"type": "output_text", "text": sanitize_surrogates(t)})
            case ToolCallPart(id=lib, name=n, arguments=args, provider_id=pid):
                # Emit BEFORE collecting more text — tool calls are separate items
                if text_blocks:
                    out.append({"role": "assistant", "content": text_blocks})
                    text_blocks = []
                out.append({
                    "type": "function_call",
                    "call_id": pid or lib,
                    "name": n,
                    "arguments": json.dumps(args),
                })
    if text_blocks:
        out.append({"role": "assistant", "content": text_blocks})
```

## Acceptance

### Completions

- [ ] Request includes `tools` array when context has tools.
- [ ] Streaming `tool_calls` deltas across multiple chunks → one `ToolCallStart`, ordered `ToolCallDelta`s, one `ToolCallEnd` per index.
- [ ] `ToolCallEnd.arguments` parsed via `parse_streaming_json`.
- [ ] Library tool-call IDs match `^call_[0-9a-f]{8}$`.
- [ ] Assistant round-trip: `AssistantMessage` with tool calls → wire `tool_calls` array.
- [ ] Tool-result with text-only content → `tool` role message with the text.
- [ ] Tool-result with image content → `tool` text message PLUS synthetic `user` follow-up with `image_url` blocks.
- [ ] `is_error=True` prefixes text with `[error]`.

### Responses

- [ ] Request `tools` is the flat-shape array.
- [ ] Streaming `function_call` output_item produces correct events.
- [ ] Tool-result wire shape uses `function_call_output` items.
- [ ] Image-bearing tool results add synthetic user message.
- [ ] Assistant message with mixed text + tool calls fans out to multiple input items in order.

### Both

- [ ] `tests/test_openai_completions_tools.py` and `tests/test_openai_responses_tools.py` cover the items above.
- [ ] All task 21/22 tests still pass.
- [ ] `basedpyright` clean.

## Notes

- Synthetic follow-up user message is degraded — loses the structural link between tool call and its image output. Acceptable trade-off (OpenAI APIs reject inline images in tool messages).
- Library IDs `call_XXXXXXXX` deliberately look like OpenAI native ids. Within OpenAI, library and provider ids may coincide — fine. `provider_id` substitution is meaningful for cross-provider handoff (Anthropic `toolu_*` → OpenAI `call_*`).
- Don't unify the two adapters' tool conversion. They diverge enough that shared code becomes a tangle. Keep parallel + symmetric.
