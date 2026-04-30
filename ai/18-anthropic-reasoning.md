# 18 — Anthropic provider: extended thinking with signature round-trip

## Goal

Extend `AnthropicProvider` to support extended thinking. Stream `thinking` blocks as `Reasoning*` events, preserve `signature` on round-trip, handle `redacted_thinking`.

## Refs

- `00-architecture.md` §5 (`Reasoning*` events), §10 (round-trip)
- Anthropic extended thinking: https://docs.anthropic.com/en/docs/build-with-claude/extended-thinking
- `pi-mono/packages/ai/src/providers/anthropic.ts` — search `thinking`, `redacted_thinking`

## Wire format additions

Request (when reasoning enabled):

```json
{
  ...,
  "thinking": {"type": "enabled", "budget_tokens": 16000},
  "max_tokens": 32000
}
```

`max_tokens` must exceed `budget_tokens`.

SSE:

- `content_block_start` with `content_block.type == "thinking"`:
  - `{"type": "thinking", "thinking": ""}`
  - emit `ReasoningStart(part_id)`
- `content_block_start` with `content_block.type == "redacted_thinking"`:
  - `{"type": "redacted_thinking", "data": "<encrypted>"}`
  - emit `ReasoningStart(part_id)` immediately followed by `ReasoningEnd(part_id, text="", signature=None, redacted=True, provider_metadata={"data": "<encrypted>"})` (atomic)
- `content_block_delta` with `delta.type == "thinking_delta"`:
  - emit `ReasoningDelta(part_id, text=delta.thinking)`
- `content_block_delta` with `delta.type == "signature_delta"`:
  - accumulate the signature; do not emit an event
- `content_block_stop` for a thinking block:
  - emit `ReasoningEnd(part_id, text=accumulated, signature=accumulated_signature, redacted=False)`

## API option

Accept `reasoning_budget: int | None = None` in `stream(...)`. When provided and > 0:

```python
body["thinking"] = {"type": "enabled", "budget_tokens": reasoning_budget}
```

Bump `max_tokens` to at least `reasoning_budget + 1024` if caller's `max_tokens` is too small (or raise `BadRequestError` if explicitly provided and incompatible — match TS `adjustMaxTokensForThinking` in `simple-options.ts`).

Deliberate simplification of TS's `SimpleStreamOptions.reasoning: ThinkingLevel` — TS maps `"low" | "medium" | "high" | "xhigh"` to budgets via `mapThinkingLevelToEffort`. We expose the raw budget; level mapping is a UX concern that belongs in the agent layer or a future `simple_stream` wrapper.

## Round-trip via `_convert_messages`

```python
case AssistantMessage(content=parts):
    content = []
    for p in parts:
        match p:
            case TextPart(text=t):
                content.append({"type": "text", "text": sanitize_surrogates(t)})
            case ToolCallPart(...):
                ...  # task 17
            case ReasoningPart(text=text, signature=sig, redacted=False):
                # Anthropic requires both thinking + signature, OR omit the
                # block entirely. Skip if signature is missing (caller
                # constructed by hand without going through stream).
                if sig is None:
                    continue
                content.append({"type": "thinking", "thinking": text, "signature": sig})
            case ReasoningPart(redacted=True, provider_metadata=meta):
                data = meta.get("data")
                if not data:
                    continue
                content.append({"type": "redacted_thinking", "data": data})
    out.append({"role": "assistant", "content": content})
```

Critical: when an assistant message contains a `tool_use` block, *thinking blocks before it must be retained on the wire*. Anthropic's tool-use chain breaks if you strip them. Round-trip preservation of `signature` is mandatory.

## Acceptance

- [ ] `stream(..., reasoning_budget=N)` adds `thinking` block to request body and bumps `max_tokens` accordingly.
- [ ] SSE `content_block_start(thinking)` → `thinking_delta`(s) → `signature_delta` → `content_block_stop` emits `ReasoningStart`, `ReasoningDelta`(s), `ReasoningEnd(signature=accumulated)`.
- [ ] `content_block_start(redacted_thinking)` produces `ReasoningStart` + `ReasoningEnd(redacted=True, text="", signature=None, provider_metadata={"data": encrypted})`.
- [ ] `_convert_messages` round-trips `ReasoningPart(text, signature)` → `{"type": "thinking", ...}`.
- [ ] `_convert_messages` round-trips `ReasoningPart(redacted=True, provider_metadata={"data": ...})` → `{"type": "redacted_thinking", "data": ...}`.
- [ ] `ReasoningPart` without a signature silently dropped on outbound (assistant) messages — don't raise.
- [ ] `tests/test_anthropic_reasoning.py`:
  - request body includes `thinking` block when `reasoning_budget=8000`
  - request `max_tokens` auto-bumped when too small
  - thinking-block streaming produces correct `Reasoning*` events with accumulated signature
  - redacted_thinking → `redacted=True` ReasoningEnd
  - assistant message round-trip preserves signature on the wire
  - assistant message round-trip preserves redacted_thinking via `provider_metadata`
- [ ] All prior Anthropic tests still pass.
- [ ] `basedpyright` clean.

## Notes

- Anthropic requires thinking blocks be sent back **verbatim** with `signature` if extended thinking is enabled and you want tool-use chain validity. Stripping signatures = broken tool calling.
- Don't expose `ThinkingLevel`. Mapping is policy that depends on the model.
- `signature_delta` arrives in pieces; concatenate. Signature is opaque — don't validate or interpret.
- `thinking_delta` for an unrecorded block (out-of-order events shouldn't happen, but defensively): drop. One-line comment explaining why.
