# 01 — Unified types

## Goal

`src/llm_providers/types.py`: single canonical schema (messages, content parts, tool defs). Replaces both old `types.py` and `communication.py`. Both deleted in this task.

## Refs

- `00-architecture.md` §3, §8, §9, §10
- `pi-mono/packages/ai/src/types.ts:153-249` (TS shapes mirrored)

## Module

All `@dataclass(slots=True, frozen=True)` unless noted. Variants carry `type: Literal["..."]` with default so positional construction works.

```python
from __future__ import annotations
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Literal


Role = Literal["user", "assistant", "tool_result"]
# snake_case (vs TS "toolResult") — Python convention; aligns with class name


# ----- content parts -----

@dataclass(slots=True, frozen=True)
class TextPart:
    type: Literal["text"] = "text"
    text: str = ""
    cache: bool = False                  # prompt-caching marker (architecture §9)
    signature: str | None = None         # OpenAI Responses message metadata; opaque


@dataclass(slots=True, frozen=True)
class ReasoningPart:
    type: Literal["reasoning"] = "reasoning"
    text: str = ""
    signature: str | None = None         # mandatory for Anthropic round-trip
    redacted: bool = False               # Anthropic safety-redacted thinking
    provider_metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True, frozen=True)
class ImagePart:
    type: Literal["image"] = "image"
    data: str = ""                       # base64-encoded
    mime_type: str = "image/png"


@dataclass(slots=True, frozen=True)
class ToolCallPart:
    type: Literal["tool_call"] = "tool_call"
    id: str = ""                         # library-issued stable ID (architecture §8)
    name: str = ""
    arguments: dict[str, Any] = field(default_factory=dict)
    provider_id: str | None = None       # original provider ID, for wire round-trip


ContentPart = TextPart | ReasoningPart | ImagePart | ToolCallPart
UserContentPart = TextPart | ImagePart                       # user / tool-result content
AssistantContentPart = TextPart | ReasoningPart | ToolCallPart


# ----- messages -----

@dataclass(slots=True, frozen=True)
class UserMessage:
    role: Literal["user"] = "user"
    content: list[UserContentPart] = field(default_factory=list)
    timestamp_ms: int = 0                # 0 = unset; library fills in if 0


@dataclass(slots=True, frozen=True)
class AssistantMessage:
    role: Literal["assistant"] = "assistant"
    content: list[AssistantContentPart] = field(default_factory=list)
    api: str = ""                        # e.g. "anthropic-messages"
    provider: str = ""                   # e.g. "anthropic"
    model: str = ""
    response_id: str | None = None       # provider's request/message ID
    usage: "Usage | None" = None
    stop_reason: "StopReason" = "end_turn"
    error_message: str | None = None
    timestamp_ms: int = 0


@dataclass(slots=True, frozen=True)
class ToolResultMessage:
    role: Literal["tool_result"] = "tool_result"
    tool_call_id: str = ""               # library-issued ID (matches ToolCallPart.id)
    tool_name: str = ""
    content: list[TextPart | ImagePart] = field(default_factory=list)
    is_error: bool = False
    timestamp_ms: int = 0


Message = UserMessage | AssistantMessage | ToolResultMessage


# ----- tool definition -----

@dataclass(slots=True, frozen=True)
class ToolDefinition:
    name: str
    description: str
    input_schema: dict[str, Any]         # JSON Schema dict (architecture §3)
    cache: bool = False                  # cache_control marker (Anthropic)


# ----- context (input bundle) -----

@dataclass(slots=True, frozen=True)
class Context:
    system_prompt: str | None = None
    messages: list[Message] = field(default_factory=list)
    tools: list[ToolDefinition] = field(default_factory=list)
    system_prompt_cache: bool = False    # see architecture §9


# ----- usage / stop -----

StopReason = Literal[
    "end_turn", "max_tokens", "tool_use", "stop_sequence",
    "refusal", "error", "abort",
]


@dataclass(slots=True, frozen=True)
class Usage:
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0
    reasoning_tokens: int = 0            # 0 if unknown
    total_tokens: int = 0                # input + output (excludes reasoning if separately reported)
    cost_usd: Decimal = Decimal(0)       # populated by registry.compute_cost()
```

Convenience constructors (single-text-part case only):

```python
def user(text: str, *, cache: bool = False) -> UserMessage: ...
def assistant_text(text: str, **kwargs) -> AssistantMessage: ...
def tool_result(tool_call_id: str, tool_name: str, text: str,
                *, is_error: bool = False) -> ToolResultMessage: ...
```

## Acceptance

- [ ] `types.py` rewritten; `communication.py` deleted.
- [ ] All names importable from `llm_providers.types`: `Message`, `UserMessage`, `AssistantMessage`, `ToolResultMessage`, `TextPart`, `ReasoningPart`, `ImagePart`, `ToolCallPart`, `ToolDefinition`, `Context`, `Usage`, `StopReason`, `Role`, `ContentPart`, `UserContentPart`, `AssistantContentPart`, `user`, `assistant_text`, `tool_result`.
- [ ] `tests/test_types.py`:
  - positional construction per message variant
  - `match` exhaustively narrows `Message` (3 variants) and `ContentPart` (4 variants)
  - dataclasses are hashable + value-equal (`frozen=True`)
  - convenience ctors produce well-formed messages
- [ ] No imports from `pydantic`, `typing_extensions`, or any deleted module.
- [ ] No imports of `llm_providers.communication` / `api_registry` / `model_registry` (deleted in later tasks).
- [ ] `basedpyright` clean.

## Notes

- `frozen=True` → hashable. `content: list[...]` is mutable (Python lacks frozen list); known trade-off.
- `Any` only on `input_schema` and `arguments` (inherently dynamic). Don't broaden.
- No `__post_init__` validation. No `to_dict` / `from_dict`. Validation at wire boundary; serialization in consuming layers.
