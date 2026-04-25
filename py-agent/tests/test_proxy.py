"""Unit tests for proxy stream reconstruction helpers."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.proxy import process_proxy_event, stream_proxy_from_events
from src.types import AssistantMessage, JsonObject, TextContent, ToolCallContent

EXPECTED_TOTAL_TOKENS = 3


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


if __name__ == "__main__":
    unittest.main()
