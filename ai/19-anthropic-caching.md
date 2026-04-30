# 19 — Anthropic provider: prompt caching

## Goal

Extend `AnthropicProvider` to translate `cache: bool` (on `TextPart` and `ToolDefinition`) to Anthropic's `cache_control: {"type": "ephemeral"}` markers, and ship the `auto_cache()` helper.

## Refs

- `00-architecture.md` §9
- Anthropic prompt caching: https://docs.anthropic.com/en/docs/build-with-claude/prompt-caching
- `pi-mono/packages/ai/src/providers/anthropic.ts` — search `cache_control` (`getCacheControl`, `convertMessages`, `convertTools`)

## Wire format

Content block:

```json
{"type": "text", "text": "...", "cache_control": {"type": "ephemeral"}}
```

Tool definition:

```json
{
  "name": "...",
  "description": "...",
  "input_schema": {...},
  "cache_control": {"type": "ephemeral"}
}
```

System prompt as cached:

```json
{"system": [{"type": "text", "text": "...", "cache_control": {"type": "ephemeral"}}]}
```

## Updates to `_convert_messages` and `_convert_tools`

```python
def _convert_text_part(part: TextPart) -> dict[str, object]:
    block: dict[str, object] = {"type": "text", "text": sanitize_surrogates(part.text)}
    if part.cache:
        block["cache_control"] = {"type": "ephemeral"}
    return block


def _convert_tools(tools: list[ToolDefinition]) -> list[dict[str, object]]:
    out: list[dict[str, object]] = []
    for t in tools:
        block: dict[str, object] = {
            "name": t.name,
            "description": t.description,
            "input_schema": t.input_schema,
        }
        if t.cache:
            block["cache_control"] = {"type": "ephemeral"}
        out.append(block)
    return out
```

## System prompt caching

Plain string `context.system_prompt` → `system: <string>` (no caching). To cache:

`Context.system_prompt_cache: bool = False`. If True and `system_prompt` non-empty → array form on wire:

```json
{"system": [{"type": "text", "text": "...", "cache_control": {"type": "ephemeral"}}]}
```

`types.py` (task 01) already includes the field. Update `_build_request` to handle both forms.

## `auto_cache()` helper

`src/llm_providers/caching.py`:

```python
"""Prompt caching helpers."""
from __future__ import annotations
import dataclasses

from llm_providers.types import (
    AssistantMessage,
    Context,
    Message,
    TextPart,
    ToolDefinition,
    UserMessage,
)


def auto_cache(context: Context) -> Context:
    """Return a copy of `context` with cache_control markers added heuristically.

    Markers:
      - on the system prompt (Context.system_prompt_cache=True)
      - on every ToolDefinition (cache=True)
      - on the last text part of the last user/assistant message (cache=True)

    Anthropic supports up to 4 cache breakpoints per request. This helper
    uses at most 3 (system + tools + last message), leaving one slot free
    for callers who want to mark something specific.
    """
    new_tools = [dataclasses.replace(t, cache=True) for t in context.tools]
    new_messages = list(context.messages)
    for i in range(len(new_messages) - 1, -1, -1):
        m = new_messages[i]
        if isinstance(m, (UserMessage, AssistantMessage)) and m.content:
            new_content = list(m.content)
            for j in range(len(new_content) - 1, -1, -1):
                if isinstance(new_content[j], TextPart):
                    new_content[j] = dataclasses.replace(new_content[j], cache=True)
                    break
            new_messages[i] = dataclasses.replace(m, content=new_content)
            break
    return dataclasses.replace(
        context,
        messages=new_messages,
        tools=new_tools,
        system_prompt_cache=bool(context.system_prompt),
    )
```

## Usage report

Anthropic `message_start.usage` (and `message_delta.usage` updates) include `cache_creation_input_tokens` and `cache_read_input_tokens`. Task 16's `_accumulate_usage` is the place to propagate them into `Usage.cache_write_tokens` and `Usage.cache_read_tokens`. Verify in tests.

## Acceptance

- [ ] `cache=True` on a `TextPart` → `cache_control: {"type": "ephemeral"}` on wire.
- [ ] `cache=True` on a `ToolDefinition` → `cache_control` on wire.
- [ ] `Context.system_prompt_cache=True` → system prompt sent as array of one cached text block.
- [ ] `auto_cache(context)` marks tools, last user/assistant text part, and system prompt.
- [ ] SSE `message_start.usage.cache_creation_input_tokens` populates `Usage.cache_write_tokens` on `MessageEnd`.
- [ ] `cache_read_input_tokens` populates `Usage.cache_read_tokens`.
- [ ] `tests/test_anthropic_caching.py`:
  - cached text part round-trip on the wire
  - cached tool definition on the wire
  - cached system prompt on the wire (array form)
  - usage propagation: `Usage.cache_read_tokens == 1234` when SSE reports `cache_read_input_tokens: 1234`
  - `tests/test_caching.py`: `auto_cache(context)` shape preservation
- [ ] All prior Anthropic tests still pass.
- [ ] `basedpyright` clean.

## Notes

- Anthropic supports `cache_control.ttl: "1h"` for long-cache models. Default to standard ephemeral (5-minute) cache. Long-cache support → later via `model.compat["supports_long_cache_retention"]: bool` and a `cache_retention: Literal["short", "long"]` option. Out of scope here.
- `auto_cache` is conservative — no markers if any slot would be empty.
- OpenAI ignores `cache: bool` (auto-cache). OpenAI adapter (task 21+) drops the field; the field stays in `TextPart` because the schema is shared.
