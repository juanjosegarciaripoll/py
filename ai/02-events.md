# 02 — Streaming events

## Goal

`src/llm_providers/events.py`: discriminated-union event dataclasses. Contract between providers and consumers.

## Refs

- `00-architecture.md` §5 (full protocol + rules)

## Module

All `@dataclass(slots=True, frozen=True)` with `type: Literal[...]`.

```python
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any, Literal

from llm_providers.types import StopReason, Usage
from llm_providers.errors import LLMProviderError


@dataclass(slots=True, frozen=True)
class MessageStart:
    type: Literal["message_start"] = "message_start"
    id: str = ""              # library-issued message ID
    model: str = ""
    provider: str = ""
    api: str = ""


@dataclass(slots=True, frozen=True)
class TextStart:
    type: Literal["text_start"] = "text_start"
    part_id: str = ""


@dataclass(slots=True, frozen=True)
class TextDelta:
    type: Literal["text_delta"] = "text_delta"
    part_id: str = ""
    text: str = ""


@dataclass(slots=True, frozen=True)
class TextEnd:
    type: Literal["text_end"] = "text_end"
    part_id: str = ""
    text: str = ""            # full accumulated text for this part


@dataclass(slots=True, frozen=True)
class ReasoningStart:
    type: Literal["reasoning_start"] = "reasoning_start"
    part_id: str = ""


@dataclass(slots=True, frozen=True)
class ReasoningDelta:
    type: Literal["reasoning_delta"] = "reasoning_delta"
    part_id: str = ""
    text: str = ""


@dataclass(slots=True, frozen=True)
class ReasoningEnd:
    type: Literal["reasoning_end"] = "reasoning_end"
    part_id: str = ""
    text: str = ""
    signature: str | None = None
    redacted: bool = False
    provider_metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True, frozen=True)
class ToolCallStart:
    type: Literal["tool_call_start"] = "tool_call_start"
    part_id: str = ""
    id: str = ""              # library-issued stable tool-call ID
    name: str = ""


@dataclass(slots=True, frozen=True)
class ToolCallDelta:
    type: Literal["tool_call_delta"] = "tool_call_delta"
    part_id: str = ""
    arguments_delta: str = "" # raw JSON fragment as delivered


@dataclass(slots=True, frozen=True)
class ToolCallEnd:
    type: Literal["tool_call_end"] = "tool_call_end"
    part_id: str = ""
    id: str = ""
    name: str = ""
    arguments: dict[str, Any] = field(default_factory=dict)  # parsed via tolerant JSON parser


@dataclass(slots=True, frozen=True)
class MessageEnd:
    type: Literal["message_end"] = "message_end"
    stop_reason: StopReason = "end_turn"
    usage: Usage = field(default_factory=Usage)
    response_id: str | None = None


@dataclass(slots=True, frozen=True)
class Error:
    type: Literal["error"] = "error"
    error: LLMProviderError | None = None


@dataclass(slots=True, frozen=True)
class Done:
    type: Literal["done"] = "done"


Event = (
    MessageStart
    | TextStart | TextDelta | TextEnd
    | ReasoningStart | ReasoningDelta | ReasoningEnd
    | ToolCallStart | ToolCallDelta | ToolCallEnd
    | MessageEnd
    | Error
    | Done
)
```

## Why no `partial: AssistantMessage` (TS deviation)

TS threads a running `AssistantMessage` through every event. We don't:

- Forces consumer dedup.
- Quadratic on long streams.
- Consumers needing the running message build it themselves (`assemble.py` task 27 has the pattern).

## Acceptance

- [ ] All variants exported. `Event` union exported.
- [ ] `tests/test_events.py`: per-variant construction; `match` exhaustively narrows all 13 variants; frozen + hashable; default values produce valid instances.
- [ ] No circular imports (`events.py` imports `types.py`, `errors.py`; nothing imports back).
- [ ] `basedpyright` clean.

## Notes

- No convenience ctors here. Provider adapters call dataclasses directly.
- No base class. Discriminator + `match` is enough.
- No `partial` field — see deviation note above.
