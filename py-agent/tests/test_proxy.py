"""Unit tests for proxy stream reconstruction helpers."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from py_agent.proxy import (
    ProxyMessageEventStream,
    ProxyStreamOptions,
    parse_streaming_json,
    process_proxy_event,
    stream_proxy_from_events,
)
from py_agent.types import (
    AssistantMessage,
    ErrorEvent,
    JsonObject,
    TextContent,
    ThinkingContent,
    ToolCallContent,
)

EXPECTED_TOTAL_TOKENS = 3
EXPECTED_USAGE_OUTPUT = 2
EXPECTED_USAGE_CACHE_READ = 3
EXPECTED_USAGE_TOTAL = 6


async def _done_events() -> AsyncIterator[JsonObject]:
    start: JsonObject = {"type": "start"}
    text_start: JsonObject = {"type": "text_start", "contentIndex": 0}
    text_delta: JsonObject = {"type": "text_delta", "contentIndex": 0, "delta": "hi"}
    done: JsonObject = {
        "type": "done",
        "reason": "stop",
        "usage": {"input": 1, "output": 2, "totalTokens": 3},
    }
    for event in (start, text_start, text_delta, done):
        yield event


async def _error_events() -> AsyncIterator[JsonObject]:
    start: JsonObject = {"type": "start"}
    error: JsonObject = {"type": "error", "reason": "error", "errorMessage": "boom"}
    for event in (start, error):
        yield event


async def _partial_events() -> AsyncIterator[JsonObject]:
    yield {"type": "text_start", "contentIndex": 0}
    yield {"type": "text_delta", "contentIndex": 0, "delta": "partial"}


class ProxyTests(unittest.IsolatedAsyncioTestCase):
    """Tests proxy event decoding and stream result behavior."""

    async def test_process_proxy_tool_call_partial_json(self) -> None:
        partial = AssistantMessage(api="api", provider="provider", model="model")

        start_event: JsonObject = {
            "type": "toolcall_start",
            "contentIndex": 0,
            "id": "call_1",
            "toolName": "search",
        }
        start = process_proxy_event(start_event, partial)
        assert start is not None
        first_content = partial.content[0]
        assert isinstance(first_content, ToolCallContent)

        delta_one: JsonObject = {
            "type": "toolcall_delta",
            "contentIndex": 0,
            "delta": '{"q":"',
        }
        delta_two: JsonObject = {
            "type": "toolcall_delta",
            "contentIndex": 0,
            "delta": 'hello"}',
        }
        process_proxy_event(delta_one, partial)
        process_proxy_event(delta_two, partial)

        block = partial.content[0]
        assert isinstance(block, ToolCallContent)
        assert block.arguments == {"q": "hello"}

        end_event: JsonObject = {"type": "toolcall_end", "contentIndex": 0}
        end = process_proxy_event(end_event, partial)
        assert end is not None
        assert block.partial_json is None

    async def test_stream_proxy_from_events_done(self) -> None:
        stream = stream_proxy_from_events("api", "provider", "model", _done_events())
        seen = [event.type async for event in stream]
        result = await stream.result()

        assert seen[-1] == "done"
        assert result.stop_reason == "stop"
        assert result.usage.total_tokens == EXPECTED_TOTAL_TOKENS
        first_block = result.content[0]
        assert isinstance(first_block, TextContent)
        assert first_block.text == "hi"

    async def test_stream_proxy_from_events_error(self) -> None:
        stream = stream_proxy_from_events("api", "provider", "model", _error_events())
        _seen = [event.type async for event in stream]
        result = await stream.result()

        assert result.stop_reason == "error"
        assert result.error_message == "boom"

    async def test_parse_streaming_json_handles_partial_empty_and_invalid_values(
        self,
    ) -> None:
        assert parse_streaming_json(None) == {}
        assert parse_streaming_json("   ") == {}
        assert parse_streaming_json('{"outer":{"x":1') == {"outer": {"x": 1}}
        assert parse_streaming_json("[1,2,3]") == {}
        assert parse_streaming_json("{invalid") == {}

    async def test_process_proxy_event_supports_text_thinking_done_and_error_variants(
        self,
    ) -> None:
        partial = AssistantMessage(api="api", provider="provider", model="model")

        start = process_proxy_event({"type": "start"}, partial)
        assert start is not None

        text_start = process_proxy_event(
            {"type": "text_start", "contentIndex": "0"},
            partial,
        )
        assert text_start is not None
        text_delta = process_proxy_event(
            {"type": "text_delta", "contentIndex": 0, "delta": 123},
            partial,
        )
        assert text_delta is not None
        text_end = process_proxy_event({"type": "text_end", "contentIndex": 0}, partial)
        assert text_end is not None

        thinking_start = process_proxy_event(
            {"type": "thinking_start", "contentIndex": 1},
            partial,
        )
        assert thinking_start is not None
        thinking_delta = process_proxy_event(
            {"type": "thinking_delta", "contentIndex": 1, "delta": "step"},
            partial,
        )
        assert thinking_delta is not None
        thinking_end = process_proxy_event(
            {"type": "thinking_end", "contentIndex": 1},
            partial,
        )
        assert thinking_end is not None

        done = process_proxy_event(
            {
                "type": "done",
                "reason": "toolUse",
                "usage": {
                    "input": "1",
                    "output": 2,
                    "cacheRead": "3",
                    "cacheWrite": "oops",
                    "totalTokens": "6",
                },
            },
            partial,
        )
        assert done is not None
        assert partial.stop_reason == "toolUse"
        assert partial.usage.input == 1
        assert partial.usage.output == EXPECTED_USAGE_OUTPUT
        assert partial.usage.cache_read == EXPECTED_USAGE_CACHE_READ
        assert partial.usage.cache_write == 0
        assert partial.usage.total_tokens == EXPECTED_USAGE_TOTAL

        error_partial = AssistantMessage(api="api", provider="provider", model="model")
        error = process_proxy_event(
            {"type": "error", "reason": "aborted", "errorMessage": 99},
            error_partial,
        )
        assert isinstance(error, ErrorEvent)
        assert error_partial.stop_reason == "aborted"
        assert error_partial.error_message == "99"

        assert process_proxy_event({"type": "unknown"}, partial) is None

    async def test_process_proxy_event_rejects_wrong_text_content(self) -> None:
        text_partial = AssistantMessage(content=[ThinkingContent(thinking="x")])
        text_delta_error: str | None = None
        try:
            process_proxy_event({"type": "text_delta", "contentIndex": 0}, text_partial)
        except ValueError as error:
            text_delta_error = str(error)
        else:
            self.fail("Expected text_delta to reject non-text content")

        text_end_error: str | None = None
        try:
            process_proxy_event({"type": "text_end", "contentIndex": 0}, text_partial)
        except ValueError as error:
            text_end_error = str(error)
        else:
            self.fail("Expected text_end to reject non-text content")

        assert text_delta_error is not None
        assert "non-text" in text_delta_error
        assert text_end_error is not None
        assert "non-text" in text_end_error

    async def test_process_proxy_event_rejects_wrong_thinking_content(self) -> None:
        thinking_partial = AssistantMessage(content=[TextContent(text="x")])
        thinking_delta_error: str | None = None
        try:
            process_proxy_event(
                {"type": "thinking_delta", "contentIndex": 0},
                thinking_partial,
            )
        except ValueError as error:
            thinking_delta_error = str(error)
        else:
            self.fail("Expected thinking_delta to reject text content")

        thinking_end_error: str | None = None
        try:
            process_proxy_event(
                {"type": "thinking_end", "contentIndex": 0},
                thinking_partial,
            )
        except ValueError as error:
            thinking_end_error = str(error)
        else:
            self.fail("Expected thinking_end to reject text content")

        assert thinking_delta_error is not None
        assert "non-thinking" in thinking_delta_error
        assert thinking_end_error is not None
        assert "non-thinking" in thinking_end_error

    async def test_process_proxy_event_rejects_wrong_tool_content(self) -> None:
        tool_partial = AssistantMessage(content=[TextContent(text="x")])
        tool_delta_error: str | None = None
        try:
            process_proxy_event(
                {"type": "toolcall_delta", "contentIndex": 0},
                tool_partial,
            )
        except ValueError as error:
            tool_delta_error = str(error)
        else:
            self.fail("Expected toolcall_delta to reject non-tool content")

        assert tool_delta_error is not None
        assert "non-toolCall" in tool_delta_error
        assert process_proxy_event(
            {"type": "toolcall_end", "contentIndex": 0},
            tool_partial,
        ) is None

    async def test_proxy_message_stream_handles_done_error_and_end(self) -> None:
        done_stream = ProxyMessageEventStream()
        message = AssistantMessage(content=[TextContent(text="done")])
        done_stream.push(ErrorEvent(reason="error", error=message))
        done_stream.push(ErrorEvent(reason="error", error=message))
        events = [event.type async for event in done_stream]
        result = await done_stream.result()

        assert events == ["error"]
        assert result is message

        partial_stream = ProxyMessageEventStream()
        partial_result = AssistantMessage(content=[TextContent(text="partial")])
        partial_stream.end(partial_result)
        partial_stream.end(partial_result)
        no_events = [event async for event in partial_stream]
        partial_done = await partial_stream.result()

        assert no_events == []
        assert partial_done is partial_result

    async def test_stream_proxy_from_events_returns_partial_when_source_ends(
        self,
    ) -> None:
        stream = stream_proxy_from_events("api", "provider", "model", _partial_events())
        seen = [event.type async for event in stream]
        result = await stream.result()

        assert seen == ["text_start", "text_delta"]
        first = result.content[0]
        assert isinstance(first, TextContent)
        assert first.text == "partial"

    async def test_proxy_stream_options_dataclass(self) -> None:
        options = ProxyStreamOptions(
            auth_token="example-auth-token",  # noqa: S106
            proxy_url="https://proxy",
        )
        assert options.auth_token == "example-auth-token"  # noqa: S105
        assert options.proxy_url == "https://proxy"


if __name__ == "__main__":
    unittest.main()

