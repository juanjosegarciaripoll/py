"""Unified communication schema and helpers for provider interoperability."""

from __future__ import annotations

import asyncio
import hashlib
import json
import re
from collections.abc import AsyncIterator  # noqa: TC003
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

type JsonPrimitive = str | int | float | bool | None
type JsonValue = JsonPrimitive | list["JsonValue"] | dict[str, "JsonValue"]
type JsonObject = dict[str, JsonValue]

type StopReason = Literal["stop", "length", "toolUse", "error", "aborted"]


def _timestamp_ms() -> int:
    return int(datetime.now(tz=UTC).timestamp() * 1000)


class TextContent(BaseModel):
    """Plain text content block."""

    model_config = ConfigDict(extra="forbid")

    type: Literal["text"] = "text"
    text: str
    text_signature: str | None = None


class ThinkingContent(BaseModel):
    """Reasoning/thinking content block."""

    model_config = ConfigDict(extra="forbid")

    type: Literal["thinking"] = "thinking"
    thinking: str
    thinking_signature: str | None = None
    redacted: bool = False


class ImageContent(BaseModel):
    """Image content block."""

    model_config = ConfigDict(extra="forbid")

    type: Literal["image"] = "image"
    data: str
    mime_type: str


class ToolCallContent(BaseModel):
    """Tool call content block."""

    model_config = ConfigDict(extra="forbid")

    type: Literal["toolCall"] = "toolCall"
    id: str
    name: str
    arguments: JsonObject = Field(default_factory=dict)
    thought_signature: str | None = None
    partial_json: str | None = None


type AssistantContent = TextContent | ThinkingContent | ToolCallContent
type UserContent = TextContent | ImageContent


def _assistant_content_list() -> list[TextContent | ThinkingContent | ToolCallContent]:
    return []


def _user_content_list() -> list[TextContent | ImageContent]:
    return []


class UsageCost(BaseModel):
    """Token cost accounting in USD."""

    model_config = ConfigDict(extra="forbid")

    input: float = 0.0
    output: float = 0.0
    cache_read: float = 0.0
    cache_write: float = 0.0
    total: float = 0.0


class Usage(BaseModel):
    """Token usage accounting."""

    model_config = ConfigDict(extra="forbid")

    input: int = 0
    output: int = 0
    cache_read: int = 0
    cache_write: int = 0
    total_tokens: int = 0
    cost: UsageCost = Field(default_factory=UsageCost)

    def with_cost(
        self,
        *,
        input_per_million: float,
        output_per_million: float,
        cache_read_per_million: float = 0.0,
        cache_write_per_million: float = 0.0,
    ) -> Usage:
        """Return a copy with derived cost fields."""
        cost = UsageCost(
            input=(input_per_million / 1_000_000) * self.input,
            output=(output_per_million / 1_000_000) * self.output,
            cache_read=(cache_read_per_million / 1_000_000) * self.cache_read,
            cache_write=(cache_write_per_million / 1_000_000) * self.cache_write,
        )
        cost.total = cost.input + cost.output + cost.cache_read + cost.cache_write
        return self.model_copy(update={"cost": cost})


class UserMessage(BaseModel):
    """User message."""

    model_config = ConfigDict(extra="forbid")

    role: Literal["user"] = "user"
    content: str | list[UserContent]
    timestamp: int = Field(default_factory=_timestamp_ms)


class AssistantMessage(BaseModel):
    """Assistant message."""

    model_config = ConfigDict(extra="forbid")

    role: Literal["assistant"] = "assistant"
    content: list[TextContent | ThinkingContent | ToolCallContent] = Field(
        default_factory=_assistant_content_list
    )
    api: str
    provider: str
    model: str
    response_id: str | None = None
    usage: Usage = Field(default_factory=Usage)
    stop_reason: StopReason = "stop"
    error_message: str | None = None
    timestamp: int = Field(default_factory=_timestamp_ms)


class ToolResultMessage(BaseModel):
    """Tool result message (supports text and images)."""

    model_config = ConfigDict(extra="forbid")

    role: Literal["toolResult"] = "toolResult"
    tool_call_id: str
    tool_name: str
    content: list[TextContent | ImageContent] = Field(default_factory=_user_content_list)
    details: JsonObject | None = None
    is_error: bool = False
    timestamp: int = Field(default_factory=_timestamp_ms)


type Message = UserMessage | AssistantMessage | ToolResultMessage


def _message_list() -> list[UserMessage | AssistantMessage | ToolResultMessage]:
    return []


class ToolDefinition(BaseModel):
    """Tool definition."""

    model_config = ConfigDict(extra="forbid")

    name: str
    description: str
    parameters: JsonObject


class Context(BaseModel):
    """Conversation context."""

    model_config = ConfigDict(extra="forbid")

    system_prompt: str | None = None
    messages: list[Message] = Field(default_factory=_message_list)
    tools: list[ToolDefinition] | None = None

    def to_dict(self) -> JsonObject:
        payload: JsonValue = json.loads(self.model_dump_json(exclude_none=True))
        if not isinstance(payload, dict):
            msg = "Serialized context must be a JSON object"
            raise TypeError(msg)
        return payload

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), sort_keys=True)

    @classmethod
    def from_dict(cls, payload: JsonObject) -> Context:
        return cls.model_validate(payload)

    @classmethod
    def from_json(cls, payload: str) -> Context:
        value: JsonValue = json.loads(payload)
        if not isinstance(value, dict):
            msg = "Serialized context must decode to a JSON object"
            raise TypeError(msg)
        return cls.from_dict(value)


class StartEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: Literal["start"] = "start"
    partial: AssistantMessage


class TextStartEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: Literal["text_start"] = "text_start"
    content_index: int
    partial: AssistantMessage


class TextDeltaEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: Literal["text_delta"] = "text_delta"
    content_index: int
    delta: str
    partial: AssistantMessage


class TextEndEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: Literal["text_end"] = "text_end"
    content_index: int
    content: str
    partial: AssistantMessage


class ThinkingStartEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: Literal["thinking_start"] = "thinking_start"
    content_index: int
    partial: AssistantMessage


class ThinkingDeltaEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: Literal["thinking_delta"] = "thinking_delta"
    content_index: int
    delta: str
    partial: AssistantMessage


class ThinkingEndEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: Literal["thinking_end"] = "thinking_end"
    content_index: int
    content: str
    partial: AssistantMessage


class ToolCallStartEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: Literal["toolcall_start"] = "toolcall_start"
    content_index: int
    partial: AssistantMessage


class ToolCallDeltaEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: Literal["toolcall_delta"] = "toolcall_delta"
    content_index: int
    delta: str
    partial: AssistantMessage


class ToolCallEndEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: Literal["toolcall_end"] = "toolcall_end"
    content_index: int
    tool_call: ToolCallContent
    partial: AssistantMessage


class DoneEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: Literal["done"] = "done"
    reason: Literal["stop", "length", "toolUse"]
    message: AssistantMessage


class ErrorEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: Literal["error"] = "error"
    reason: Literal["aborted", "error"]
    error: AssistantMessage


type AssistantEvent = (
    StartEvent
    | TextStartEvent
    | TextDeltaEvent
    | TextEndEvent
    | ThinkingStartEvent
    | ThinkingDeltaEvent
    | ThinkingEndEvent
    | ToolCallStartEvent
    | ToolCallDeltaEvent
    | ToolCallEndEvent
    | DoneEvent
    | ErrorEvent
)


class AssistantMessageEventStream:
    """Async stream helper that yields assistant events and resolves final output."""

    def __init__(self) -> None:
        self._queue: asyncio.Queue[AssistantEvent | None] = asyncio.Queue()
        self._final_result: asyncio.Future[AssistantMessage] = asyncio.Future()
        self._closed = False

    def push(self, event: AssistantEvent) -> None:
        if self._closed:
            return
        if isinstance(event, DoneEvent):
            self._final_result.set_result(event.message)
            self._closed = True
        if isinstance(event, ErrorEvent):
            self._final_result.set_result(event.error)
            self._closed = True
        self._queue.put_nowait(event)
        if self._closed:
            self._queue.put_nowait(None)

    def end(self, result: AssistantMessage | None = None) -> None:
        if self._closed:
            return
        if result is not None and not self._final_result.done():
            self._final_result.set_result(result)
        self._closed = True
        self._queue.put_nowait(None)

    async def result(self) -> AssistantMessage:
        return await self._final_result

    async def __aiter__(self) -> AsyncIterator[AssistantEvent]:
        while True:
            event = await self._queue.get()
            if event is None:
                break
            yield event


def create_assistant_message(
    *,
    api: str,
    provider: str,
    model: str,
    response_id: str | None = None,
) -> AssistantMessage:
    """Create an empty assistant message for stream initialization."""
    return AssistantMessage(
        api=api,
        provider=provider,
        model=model,
        response_id=response_id,
    )


_INVALID_SURROGATE_PATTERN = re.compile(
    r"[\ud800-\udbff](?![\udc00-\udfff])|(?<![\ud800-\udbff])[\udc00-\udfff]"
)


def sanitize_surrogates(text: str) -> str:
    """Remove unpaired unicode surrogates."""
    return _INVALID_SURROGATE_PATTERN.sub("", text)


_OVERFLOW_PATTERNS = (
    re.compile(r"prompt is too long", re.IGNORECASE),
    re.compile(r"request_too_large", re.IGNORECASE),
    re.compile(r"input is too long for requested model", re.IGNORECASE),
    re.compile(r"exceeds the context window", re.IGNORECASE),
    re.compile(r"input token count.*exceeds the maximum", re.IGNORECASE),
    re.compile(r"maximum prompt length is \d+", re.IGNORECASE),
    re.compile(r"reduce the length of the messages", re.IGNORECASE),
    re.compile(r"maximum context length is \d+ tokens", re.IGNORECASE),
    re.compile(r"context[_ ]length[_ ]exceeded", re.IGNORECASE),
    re.compile(r"too many tokens", re.IGNORECASE),
    re.compile(r"token limit exceeded", re.IGNORECASE),
)

_NON_OVERFLOW_PATTERNS = (
    re.compile(r"throttling", re.IGNORECASE),
    re.compile(r"service unavailable", re.IGNORECASE),
    re.compile(r"rate limit", re.IGNORECASE),
)


def is_context_overflow(
    message: AssistantMessage,
    *,
    context_window: int | None = None,
) -> bool:
    """Return whether an assistant message indicates a context overflow."""
    if message.stop_reason == "error" and message.error_message:
        error_message = message.error_message
        if any(pattern.search(error_message) for pattern in _NON_OVERFLOW_PATTERNS):
            return False
        if any(pattern.search(error_message) for pattern in _OVERFLOW_PATTERNS):
            return True
    if context_window and message.stop_reason == "stop":
        return (message.usage.input + message.usage.cache_read) > context_window
    return False


def normalize_tool_call_id(tool_call_id: str, *, max_length: int = 64) -> str:
    """Normalize tool call IDs to a conservative cross-provider shape."""
    normalized = re.sub(r"[^a-zA-Z0-9_-]", "_", tool_call_id).strip("_")
    if not normalized:
        normalized = "tool_call"
    if len(normalized) <= max_length:
        return normalized
    digest = hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:12]
    prefix_length = max_length - 13
    prefix = normalized[:prefix_length] if prefix_length > 0 else ""
    return f"{prefix}_{digest}" if prefix else digest


_CONTROL_CHAR_MAX = 0x1F


def _repair_json_string(value: str) -> str:  # noqa: C901
    repaired_chars: list[str] = []
    in_string = False
    i = 0
    while i < len(value):
        char = value[i]
        if not in_string:
            repaired_chars.append(char)
            if char == '"':
                in_string = True
            i += 1
            continue
        if char == '"':
            repaired_chars.append(char)
            in_string = False
            i += 1
            continue
        if char == "\\":
            next_char = value[i + 1] if i + 1 < len(value) else None
            if next_char is None:
                repaired_chars.append("\\\\")
                i += 1
                continue
            if next_char in {'"', "\\", "/", "b", "f", "n", "r", "t"}:
                repaired_chars.append("\\")
                repaired_chars.append(next_char)
                i += 2
                continue
            if next_char == "u" and i + 5 < len(value):
                digits = value[i + 2 : i + 6]
                if re.fullmatch(r"[0-9a-fA-F]{4}", digits):
                    repaired_chars.extend(["\\", "u", *digits])
                    i += 6
                    continue
            repaired_chars.append("\\\\")
            i += 1
            continue
        codepoint = ord(char)
        if 0x00 <= codepoint <= _CONTROL_CHAR_MAX:
            repaired_chars.append(f"\\u{codepoint:04x}")
        else:
            repaired_chars.append(char)
        i += 1
    return "".join(repaired_chars)


def _close_partial_json(value: str) -> str:
    stack: list[str] = []
    in_string = False
    escaped = False
    for char in value:
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char in "{[":
            stack.append("}" if char == "{" else "]")
        elif char in "}]" and stack and stack[-1] == char:
            stack.pop()
    if in_string:
        value += '"'
    return value + "".join(reversed(stack))


def parse_streaming_json(partial_json: str | None) -> JsonObject:
    """Parse potentially malformed/incomplete JSON into an object."""
    if partial_json is None or not partial_json.strip():
        return {}
    candidates = (
        partial_json,
        _repair_json_string(partial_json),
        _close_partial_json(partial_json),
        _close_partial_json(_repair_json_string(partial_json)),
    )
    for candidate in candidates:
        try:
            value: JsonValue = json.loads(candidate)
            if isinstance(value, dict):
                return value
        except json.JSONDecodeError:
            continue
    return {}


def transform_messages_for_handoff(  # noqa: C901
    messages: list[Message],
    *,
    target_provider: str,
    target_api: str,
    target_model: str,
) -> list[Message]:
    """Transform history for cross-provider replay compatibility."""
    transformed: list[Message] = []
    tool_call_id_map: dict[str, str] = {}
    pending_tool_calls: list[ToolCallContent] = []
    tool_results_for_pending: set[str] = set()

    def flush_pending() -> None:
        if not pending_tool_calls:
            return
        for pending in pending_tool_calls:
            if pending.id in tool_results_for_pending:
                continue
            transformed.append(
                ToolResultMessage(
                    tool_call_id=pending.id,
                    tool_name=pending.name,
                    content=[TextContent(text="No result provided")],
                    is_error=True,
                )
            )
        pending_tool_calls.clear()
        tool_results_for_pending.clear()

    for message in messages:
        if isinstance(message, UserMessage):
            flush_pending()
            transformed.append(message)
            continue
        if isinstance(message, ToolResultMessage):
            mapped_tool_id = tool_call_id_map.get(
                message.tool_call_id,
                message.tool_call_id,
            )
            tool_results_for_pending.add(mapped_tool_id)
            transformed.append(
                message.model_copy(update={"tool_call_id": mapped_tool_id})
            )
            continue
        if message.stop_reason in {"error", "aborted"}:
            continue

        flush_pending()
        same_model = (
            message.provider == target_provider
            and message.api == target_api
            and message.model == target_model
        )
        new_content: list[AssistantContent] = []
        for block in message.content:
            if isinstance(block, TextContent):
                new_content.append(block)
                continue
            if isinstance(block, ThinkingContent):
                if same_model:
                    new_content.append(block)
                    continue
                if not block.redacted and block.thinking.strip():
                    new_content.append(TextContent(text=block.thinking))
                continue
            normalized_id = block.id
            if not same_model:
                normalized_id = normalize_tool_call_id(block.id)
            tool_call_id_map[block.id] = normalized_id
            pending_tool_calls.append(block.model_copy(update={"id": normalized_id}))
            if same_model:
                new_content.append(block)
            else:
                new_content.append(
                    block.model_copy(
                        update={
                            "id": normalized_id,
                            "thought_signature": None,
                        }
                    )
                )
        transformed.append(message.model_copy(update={"content": new_content}))

    flush_pending()
    return transformed


def parse_assistant_event(payload: JsonObject) -> AssistantEvent:  # noqa: C901, PLR0911
    """Parse a serialized assistant event payload."""
    event_type = payload.get("type")
    if event_type == "start":
        return StartEvent.model_validate(payload)
    if event_type == "text_start":
        return TextStartEvent.model_validate(payload)
    if event_type == "text_delta":
        return TextDeltaEvent.model_validate(payload)
    if event_type == "text_end":
        return TextEndEvent.model_validate(payload)
    if event_type == "thinking_start":
        return ThinkingStartEvent.model_validate(payload)
    if event_type == "thinking_delta":
        return ThinkingDeltaEvent.model_validate(payload)
    if event_type == "thinking_end":
        return ThinkingEndEvent.model_validate(payload)
    if event_type == "toolcall_start":
        return ToolCallStartEvent.model_validate(payload)
    if event_type == "toolcall_delta":
        return ToolCallDeltaEvent.model_validate(payload)
    if event_type == "toolcall_end":
        return ToolCallEndEvent.model_validate(payload)
    if event_type == "done":
        return DoneEvent.model_validate(payload)
    if event_type == "error":
        return ErrorEvent.model_validate(payload)
    msg = f"Unknown assistant event type: {event_type!r}"
    raise ValueError(msg)


@dataclass(frozen=True)
class CommunicationTelemetry:
    """Telemetry payload for response usage tracking."""

    provider: str
    model: str
    response_id: str | None
    usage: Usage
