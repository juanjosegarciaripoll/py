# 17 — Anthropic provider: tool calling

## Goal

Extend `AnthropicProvider` (task 16) to support tools: send tool defs, stream `tool_use` content blocks with partial-JSON arguments, normalize tool-call IDs, round-trip `ToolResultMessage` (text + image content) on subsequent requests.

## Refs

- `00-architecture.md` §8
- `16-anthropic-basics.md`
- `pi-mono/packages/ai/src/providers/anthropic.ts:940-1108` (`normalizeToolCallId`, `convertMessages` tool branches)
- `pi-mono/packages/ai/src/providers/anthropic.ts:1112-1135` (`convertTools`)

## Wire format additions

Request:

```json
{
  ...,
  "tools": [
    {
      "name": "read_file",
      "description": "Read a file from disk",
      "input_schema": {"type": "object", "properties": {...}}
    }
  ]
}
```

Tool-result message (sent as a `user` role with `tool_result` content blocks):

```json
{
  "role": "user",
  "content": [
    {
      "type": "tool_result",
      "tool_use_id": "toolu_01ABC...",
      "is_error": false,
      "content": [
        {"type": "text", "text": "..."},
        {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": "..."}}
      ]
    }
  ]
}
```

SSE additions:

- `content_block_start` with `content_block.type == "tool_use"`:
  - payload: `{"id": "toolu_01ABC...", "name": "read_file", "input": {}}`
  - emit `ToolCallStart(part_id, id=<library_id>, name)` and remember `<library_id> ↔ toolu_01ABC...` for this stream
- `content_block_delta` with `delta.type == "input_json_delta"`:
  - payload: `{"partial_json": "..."}`
  - emit `ToolCallDelta(part_id, arguments_delta=partial_json)`, accumulate buffer
- `content_block_stop` for a tool-use block:
  - parse buffer with `parse_streaming_json`
  - emit `ToolCallEnd(part_id, id=<library_id>, name, arguments=<parsed dict>)`

## ID normalization

Library IDs format: `call_<8 hex chars>` (deliberately matches OpenAI's wire format so cross-provider handoff is easier). Generate with `secrets.token_hex(4)`.

Per-stream map `{library_id: provider_id}`. Required when sending the next request: assistant tool-call message contains library IDs and `_convert_messages` translates them back. Persist on the `AssistantMessage`: store as `ToolCallPart.provider_id`.

## Updates to `_convert_messages`

```python
case AssistantMessage(content=parts):
    content = []
    for p in parts:
        match p:
            case TextPart(text=t):
                content.append({"type": "text", "text": sanitize_surrogates(t)})
            case ToolCallPart(id=library_id, name=name, arguments=args, provider_id=pid):
                content.append({
                    "type": "tool_use",
                    "id": pid or library_id,  # prefer original Anthropic id
                    "name": name,
                    "input": args,
                })
            case ReasoningPart():
                # task 18
                ...
    out.append({"role": "assistant", "content": content})

case ToolResultMessage(tool_call_id=lib_id, content=parts, is_error=is_error):
    # Look up the provider_id from the assistant message that produced this call
    provider_id = _resolve_provider_id(messages, lib_id) or lib_id
    blocks = []
    for part in parts:
        if isinstance(part, TextPart):
            blocks.append({"type": "text", "text": sanitize_surrogates(part.text)})
        elif isinstance(part, ImagePart):
            blocks.append({
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": part.mime_type,
                    "data": part.data,
                },
            })
    out.append({
        "role": "user",
        "content": [{
            "type": "tool_result",
            "tool_use_id": provider_id,
            "is_error": is_error,
            "content": blocks,
        }],
    })
```

`_resolve_provider_id` walks back through `messages` for an `AssistantMessage` containing a `ToolCallPart` with `id == lib_id`; returns its `provider_id`. If not found, fall back to the library id.

## Tool definitions

```python
def _convert_tools(tools: list[ToolDefinition]) -> list[dict[str, object]]:
    return [
        {
            "name": t.name,
            "description": t.description,
            "input_schema": t.input_schema,
        }
        for t in tools
    ]
```

If `tools` is non-empty, set `request_body["tools"] = _convert_tools(context.tools)`. Otherwise omit.

## Acceptance

- [ ] `_convert_messages` handles `ToolCallPart` and `ToolResultMessage` with text + image content.
- [ ] `_convert_tools` produces correct Anthropic shape.
- [ ] Streaming `tool_use` blocks emit ordered `ToolCallStart` / `ToolCallDelta` / `ToolCallEnd`.
- [ ] `ToolCallEnd.arguments` parsed via `utils.json_parse.parse_streaming_json`.
- [ ] Library IDs match `^call_[0-9a-f]{8}$`.
- [ ] `ToolCallPart.provider_id` stores Anthropic `toolu_*` from `content_block_start`.
- [ ] On follow-up request, `ToolResultMessage(tool_call_id=<lib_id>)` → wire `tool_use_id=<provider_id>`.
- [ ] Missing prior `AssistantMessage` → library id used as `tool_use_id` (best effort).
- [ ] `tests/test_anthropic_tools.py`:
  - request `tools` array present when context has tools, omitted otherwise
  - SSE `content_block_start(tool_use, id=toolu_X, name=foo)` + `input_json_delta(partial_json='{"a":')` + `input_json_delta(partial_json='1}')` + `content_block_stop` → `ToolCallStart`, two `ToolCallDelta`, one `ToolCallEnd(arguments={"a": 1})`
  - emitted `ToolCallStart.id` matches `^call_[0-9a-f]{8}$`
  - assembled `AssistantMessage` contains `ToolCallPart` with `provider_id="toolu_X"`
  - sending `ToolResultMessage(tool_call_id=<lib_id>)` → wire `tool_use_id="toolu_X"`
  - mixed-content tool result (text + image) produces both block types on the wire
  - `is_error=True` propagated to wire
- [ ] All task 16 tests still pass.
- [ ] `basedpyright` clean.

## Notes

- Don't use Anthropic's `tool_choice`. Default tool-selection. Caller can add later via `**options`.
- Anthropic's `eager_input_streaming` and `fine-grained-tool-streaming-2025-05-14` betas: enabled by default (modern Anthropic default). Legacy via `model.compat["supports_eager_tool_input_streaming"]: bool`.
- TS provider's "stealth mode" mapping tool names to Claude Code casing (`anthropic.ts:69-105`) — **don't port**. Pi-specific OAuth-flow compatibility hack.
- `parse_streaming_json` (task 05) is the right tool for the argument buffer. Don't roll a parser here.
