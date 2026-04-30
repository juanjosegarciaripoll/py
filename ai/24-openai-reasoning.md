# 24 — OpenAI Responses: reasoning round-trip

## Goal

Add reasoning support to `OpenAIResponsesProvider`. Stream reasoning items as `Reasoning*` events, preserve the opaque reasoning-item id for round-trip, accept a `reasoning_effort` option mapped to OpenAI's `reasoning.effort` field.

The Completions adapter does **not** support reasoning round-trip in this rebuild — Completions reasoning content is not persistable and must be re-derived each turn. Leave Completions untouched here.

## Refs

- `00-architecture.md` §10
- `22-openai-responses-basics.md`
- `pi-mono/packages/ai/src/providers/openai-responses.ts` — search `reasoning`, `summary_text`, `encrypted_content`
- OpenAI reasoning: https://platform.openai.com/docs/guides/reasoning

## Wire format

### Request additions

```json
{
  ...,
  "reasoning": {
    "effort": "medium",
    "summary": "auto"
  },
  "include": ["reasoning.encrypted_content"]
}
```

- `effort` ∈ `{"minimal", "low", "medium", "high"}` (varies by model — `xhigh` not in OpenAI standard tier).
- `summary: "auto"` enables streamed reasoning summary text.
- `include: ["reasoning.encrypted_content"]` requests the opaque encrypted blob for round-trip.

### Streaming reasoning events

Reasoning items appear as their own `output_item`:

- `response.output_item.added` with `item.type=reasoning`, `item.id` → emit `ReasoningStart(part_id=item.id)`.
- `response.reasoning_summary_text.delta` (delta=`"..."`) → emit `ReasoningDelta(part_id=item.id, text=delta)`. Some models also emit `response.reasoning_summary_part.added` and `.done` to bracket parts of the summary; treat as soft markers (no events emitted, just ordering hints).
- `response.output_item.done` for the reasoning item → carries `item.encrypted_content` (round-trip blob) and `item.summary` (final summary text). Emit `ReasoningEnd(part_id=item.id, text=summary, signature=encrypted_content, redacted=False, provider_metadata={"item_id": item.id})`.

If the model omits the summary (e.g. effort=`minimal` with no summary), `text` is `""`, still emit `ReasoningStart` / `ReasoningEnd` with the encrypted blob in `signature`.

### Round-trip in `_convert_messages_responses`

```python
case AssistantMessage(content=parts):
    out_items = []
    text_blocks = []
    for p in parts:
        match p:
            case TextPart(text=t):
                text_blocks.append({"type": "output_text", "text": sanitize_surrogates(t)})
            case ReasoningPart(text=summary, signature=blob, provider_metadata=meta):
                if blob is None:
                    # Without the encrypted blob the item is not round-trip-able.
                    # Skip it; OpenAI requires the blob for context continuity.
                    continue
                if text_blocks:
                    out_items.append({"role": "assistant", "content": text_blocks})
                    text_blocks = []
                item = {
                    "type": "reasoning",
                    "id": meta.get("item_id", ""),
                    "encrypted_content": blob,
                    "summary": [
                        {"type": "summary_text", "text": summary}
                    ] if summary else [],
                }
                out_items.append(item)
            case ToolCallPart(...):
                # task 23 already handles fan-out; merge with same pattern
                ...
    if text_blocks:
        out_items.append({"role": "assistant", "content": text_blocks})
    out.extend(out_items)
```

The reasoning item must precede any text or tool_call items it contributed to. Since `AssistantMessage.content` is ordered, this happens naturally if streaming ingestion preserves order — verify in tests.

### `reasoning_effort` option

Accept `reasoning_effort: Literal["minimal", "low", "medium", "high"]` in `stream(...)`. When provided:

```python
body["reasoning"] = {"effort": reasoning_effort, "summary": "auto"}
body.setdefault("include", []).append("reasoning.encrypted_content")
```

If model is not a reasoning model (`_is_reasoning_model(model) == False`), warn-and-ignore (don't raise). Use `warnings`. Test for the warning.

## Acceptance

- [ ] `stream(..., reasoning_effort="medium")` adds `reasoning: {effort, summary}` to request body.
- [ ] Request `include` field contains `"reasoning.encrypted_content"` when `reasoning_effort` is set.
- [ ] `reasoning_effort` on a non-reasoning model emits a `UserWarning` and does not modify the request body.
- [ ] SSE `response.output_item.added(reasoning)` → `ReasoningStart(part_id=item.id)`.
- [ ] `response.reasoning_summary_text.delta` → `ReasoningDelta(part_id=item.id, text=delta)`.
- [ ] `response.output_item.done(reasoning)` → `ReasoningEnd(part_id=item.id, text=summary, signature=encrypted_content, provider_metadata={"item_id": item.id})`.
- [ ] Empty-summary reasoning item still produces well-formed `ReasoningStart` / `ReasoningEnd` with blob in `signature`.
- [ ] Round-trip: `AssistantMessage` containing `ReasoningPart(signature=blob)` → wire `reasoning` item with `encrypted_content=blob`.
- [ ] `ReasoningPart` with `signature=None` silently dropped on the wire (cannot round-trip).
- [ ] Reasoning item appears **before** corresponding `output_text` items in rebuilt input.
- [ ] `tests/test_openai_responses_reasoning.py` covers each above.
- [ ] All task 22/23 tests still pass.
- [ ] `basedpyright` clean.

## Notes

- Completions adapter doesn't support reasoning. If a caller hits a reasoning model via Completions, the API rejects it; the registry's prefix fallback (task 13) routes o-series to Responses, so this should not happen in normal use.
- `include: ["reasoning.encrypted_content"]` is critical — without it, SSE omits the blob and round-trip breaks. Tests must verify it's set.
- OpenAI's reasoning summary may arrive as multiple "summary parts" (`response.reasoning_summary_part.added` / `.done`). Treat each part's deltas as additive to the same `ReasoningPart` text — concatenate in order.
- Don't expose a `ThinkingLevel`-style abstraction. Caller passes `reasoning_effort` as the literal OpenAI effort string.
