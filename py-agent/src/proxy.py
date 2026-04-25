"""Proxy-stream helpers for server-routed model streaming."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Coroutine  # noqa: TC003
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

from .types import (
    AssistantMessage,
    AssistantMessageEvent,
    DoneEvent,
    ErrorEvent,
    StartEvent,
    TextContent,
    TextDeltaEvent,
    TextEndEvent,
    TextStartEvent,
    ThinkingContent,
    ThinkingDeltaEvent,
    ThinkingEndEvent,
    ThinkingStartEvent,
    ToolCallContent,
    ToolCallDeltaEvent,
    ToolCallEndEvent,
    ToolCallStartEvent,
    Usage,
)

type JsonPrimitive = str | int | float | bool | None
type JsonValue = JsonPrimitive | list["JsonValue"] | dict[str, "JsonValue"]
type JsonObject = dict[str, JsonValue]


class ProxyMessageEventStream:
    """Simple assistant-event stream from proxy payload events."""

    def __init__(self) -> None:
        self._queue: asyncio.Queue[AssistantMessageEvent | None] = asyncio.Queue()
        self._result: asyncio.Future[AssistantMessage] = asyncio.Future()
        self._closed = False
        self._background_tasks: set[asyncio.Task[None]] = set()

    def create_background_task(
        self,
        task_coro: Coroutine[object, object, None],
    ) -> None:
        task: asyncio.Task[None] = asyncio.create_task(task_coro)
        self._background_tasks.add(task)
        task.add_done_callback(self._background_tasks.discard)

    def push(self, event: AssistantMessageEvent) -> None:
        if self._closed:
            return
        self._queue.put_nowait(event)
        if isinstance(event, DoneEvent):
            self._result.set_result(event.message)
            self._closed = True
            self._queue.put_nowait(None)
        if isinstance(event, ErrorEvent):
            self._result.set_result(event.error)
            self._closed = True
            self._queue.put_nowait(None)

    def end(self, result: AssistantMessage | None = None) -> None:
        if self._closed:
            return
        if result is not None and not self._result.done():
            self._result.set_result(result)
        self._closed = True
        self._queue.put_nowait(None)

    async def result(self) -> AssistantMessage:
        return await self._result

    async def __aiter__(self) -> AsyncIterator[AssistantMessageEvent]:
        while True:
            event = await self._queue.get()
            if event is None:
                break
            yield event


@dataclass(slots=True)
class ProxyStreamOptions:
    auth_token: str
    proxy_url: str


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
    """Best-effort parser for partial tool-call JSON."""
    if partial_json is None or not partial_json.strip():
        return {}
    candidates = (partial_json, _close_partial_json(partial_json))
    for candidate in candidates:
        try:
            value: JsonValue = json.loads(candidate)
            if isinstance(value, dict):
                return value
        except json.JSONDecodeError:
            continue
    return {}


def _int_field(payload: JsonObject, key: str, default: int = 0) -> int:
    value = payload.get(key)
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        try:
            return int(value)
        except ValueError:
            return default
    return default


def _str_field(payload: JsonObject, key: str, default: str = "") -> str:
    value = payload.get(key)
    if isinstance(value, str):
        return value
    if value is None:
        return default
    return str(value)


def _int_value(value: JsonValue, default: int = 0) -> int:
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        try:
            return int(value)
        except ValueError:
            return default
    return default


def process_proxy_event(  # noqa: C901, PLR0911, PLR0912, PLR0915
    proxy_event: JsonObject,
    partial: AssistantMessage,
) -> AssistantMessageEvent | None:
    """Process a proxy payload event and mutate partial assistant message."""
    event_type = _str_field(proxy_event, "type")
    match event_type:
        case "start":
            return StartEvent(partial=partial)
        case "text_start":
            content_index = _int_field(proxy_event, "contentIndex")
            while len(partial.content) <= content_index:
                partial.content.append(TextContent())
            partial.content[content_index] = TextContent()
            return TextStartEvent(content_index=content_index, partial=partial)
        case "text_delta":
            content_index = _int_field(proxy_event, "contentIndex")
            delta = _str_field(proxy_event, "delta")
            block = partial.content[content_index]
            if isinstance(block, TextContent):
                block.text += delta
                return TextDeltaEvent(
                    content_index=content_index,
                    delta=delta,
                    partial=partial,
                )
            msg = "Received text_delta for non-text content"
            raise ValueError(msg)
        case "text_end":
            content_index = _int_field(proxy_event, "contentIndex")
            block = partial.content[content_index]
            if isinstance(block, TextContent):
                return TextEndEvent(
                    content_index=content_index,
                    content=block.text,
                    partial=partial,
                )
            msg = "Received text_end for non-text content"
            raise ValueError(msg)
        case "thinking_start":
            content_index = _int_field(proxy_event, "contentIndex")
            while len(partial.content) <= content_index:
                partial.content.append(TextContent())
            partial.content[content_index] = ThinkingContent()
            return ThinkingStartEvent(content_index=content_index, partial=partial)
        case "thinking_delta":
            content_index = _int_field(proxy_event, "contentIndex")
            delta = _str_field(proxy_event, "delta")
            block = partial.content[content_index]
            if isinstance(block, ThinkingContent):
                block.thinking += delta
                return ThinkingDeltaEvent(
                    content_index=content_index,
                    delta=delta,
                    partial=partial,
                )
            msg = "Received thinking_delta for non-thinking content"
            raise ValueError(msg)
        case "thinking_end":
            content_index = _int_field(proxy_event, "contentIndex")
            block = partial.content[content_index]
            if isinstance(block, ThinkingContent):
                return ThinkingEndEvent(
                    content_index=content_index,
                    content=block.thinking,
                    partial=partial,
                )
            msg = "Received thinking_end for non-thinking content"
            raise ValueError(msg)
        case "toolcall_start":
            content_index = _int_field(proxy_event, "contentIndex")
            while len(partial.content) <= content_index:
                partial.content.append(TextContent())
            partial.content[content_index] = ToolCallContent(
                id=_str_field(proxy_event, "id"),
                name=_str_field(proxy_event, "toolName"),
                arguments={},
                partial_json="",
            )
            return ToolCallStartEvent(content_index=content_index, partial=partial)
        case "toolcall_delta":
            content_index = _int_field(proxy_event, "contentIndex")
            delta = _str_field(proxy_event, "delta")
            block = partial.content[content_index]
            if isinstance(block, ToolCallContent):
                partial_json = (block.partial_json or "") + delta
                block.partial_json = partial_json
                block.arguments = parse_streaming_json(partial_json)
                return ToolCallDeltaEvent(
                    content_index=content_index,
                    delta=delta,
                    partial=partial,
                )
            msg = "Received toolcall_delta for non-toolCall content"
            raise ValueError(msg)
        case "toolcall_end":
            content_index = _int_field(proxy_event, "contentIndex")
            block = partial.content[content_index]
            if isinstance(block, ToolCallContent):
                block.partial_json = None
                return ToolCallEndEvent(
                    content_index=content_index,
                    tool_call=block,
                    partial=partial,
                )
            return None
        case "done":
            reason = _str_field(proxy_event, "reason", "stop")
            usage = proxy_event.get("usage")
            if isinstance(usage, dict):
                partial.usage = Usage(
                    input=_int_value(usage.get("input", 0)),
                    output=_int_value(usage.get("output", 0)),
                    cache_read=_int_value(usage.get("cacheRead", 0)),
                    cache_write=_int_value(usage.get("cacheWrite", 0)),
                    total_tokens=_int_value(usage.get("totalTokens", 0)),
                )
            done_reason: Literal["stop", "toolUse"] = (
                "toolUse" if reason == "toolUse" else "stop"
            )
            partial.stop_reason = done_reason
            return DoneEvent(reason=done_reason, message=partial)
        case "error":
            reason = _str_field(proxy_event, "reason", "error")
            error_reason: Literal["aborted", "error"] = (
                "aborted" if reason == "aborted" else "error"
            )
            partial.stop_reason = error_reason
            error_message = proxy_event.get("errorMessage")
            partial.error_message = (
                str(error_message) if error_message is not None else None
            )
            return ErrorEvent(reason=error_reason, error=partial)
        case _:
            return None


def stream_proxy_from_events(
    model_api: str,
    model_provider: str,
    model_id: str,
    events: AsyncIterator[JsonObject],
) -> ProxyMessageEventStream:
    """Reconstruct assistant events from proxy payload events."""
    stream = ProxyMessageEventStream()

    async def runner() -> None:
        partial = AssistantMessage(
            api=model_api,
            provider=model_provider,
            model=model_id,
        )
        async for proxy_event in events:
            event = process_proxy_event(proxy_event, partial)
            if event is not None:
                stream.push(event)
        stream.end(partial)

    stream.create_background_task(runner())
    return stream
