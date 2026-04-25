"""Unit tests for provider streaming behavior."""

import asyncio
import json
import sys
import unittest
from collections.abc import AsyncIterator
from pathlib import Path
from types import TracebackType
from typing import Self, TypedDict, TypeGuard
from unittest.mock import patch

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.providers.anthropic import AnthropicProvider
from src.providers.openai import OpenAIProvider
from src.providers.openai_compatible import OpenAICompatibleProvider
from src.types import AssistantMessageEvent, Message, Role, TextContent, ToolCall

OPENAI_EXPECTED_EVENT_COUNT = 3
OPENAI_EXPECTED_TOTAL_TOKENS = 3
OPENAI_EXPECTED_REQUEST_MESSAGES = 3
OPENAI_COMPAT_EXPECTED_EVENT_COUNT = 2
ANTHROPIC_EXPECTED_EVENT_COUNT = 3
ANTHROPIC_EXPECTED_TOTAL_TOKENS = 9
EXPECTED_TOOL_DELTA_EVENT_MINIMUM = 2
EXPECTED_ANTHROPIC_CONVERTED_MESSAGES = 2
ACCESS_CHECK_OK = True
ACCESS_CHECK_FAILURE_MESSAGE = "network error"


class RequestCall(TypedDict):
    """Recorded outbound request details for assertions."""

    method: str
    url: str
    headers: dict[str, str]
    json: dict[str, object]


class FakeResponse:
    """Async context manager that yields predefined SSE lines."""

    def __init__(self, lines: list[str]) -> None:
        self._lines = lines

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        del exc_type, exc, tb

    def raise_for_status(self) -> None:
        return None

    async def aiter_lines(self) -> AsyncIterator[str]:
        for line in self._lines:
            yield line


class FakeAsyncClient:
    """Async client that records request payloads and returns fake responses."""

    def __init__(self, lines: list[str], calls: list[RequestCall]) -> None:
        self._lines = lines
        self._calls = calls

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        del exc_type, exc, tb

    def stream(
        self,
        method: str,
        url: str,
        *,
        headers: dict[str, str],
        json: dict[str, object],
    ) -> FakeResponse:
        self._calls.append(
            RequestCall(method=method, url=url, headers=headers, json=json)
        )
        return FakeResponse(self._lines)


class FakeSyncResponse:
    """Sync HTTP response stub used by accessibility checks."""

    def __init__(self, *, should_raise: bool = False) -> None:
        self._should_raise = should_raise

    def raise_for_status(self) -> None:
        if self._should_raise:
            msg = ACCESS_CHECK_FAILURE_MESSAGE
            raise httpx.HTTPError(msg)


class FakeSyncClient:
    """Sync HTTP client stub for model accessibility checks."""

    def __init__(
        self,
        calls: list[RequestCall],
        *,
        should_raise: bool = False,
    ) -> None:
        self._calls = calls
        self._should_raise = should_raise

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        del exc_type, exc, tb

    def get(self, url: str, *, headers: dict[str, str]) -> FakeSyncResponse:
        self._calls.append(RequestCall(method="GET", url=url, headers=headers, json={}))
        return FakeSyncResponse(should_raise=self._should_raise)

    def post(
        self,
        url: str,
        *,
        headers: dict[str, str],
        json: dict[str, object],
    ) -> FakeSyncResponse:
        self._calls.append(
            RequestCall(method="POST", url=url, headers=headers, json=json)
        )
        return FakeSyncResponse(should_raise=self._should_raise)


async def _collect_events(
    provider: OpenAIProvider | OpenAICompatibleProvider | AnthropicProvider,
    messages: list[Message],
) -> list[AssistantMessageEvent]:
    return [
        event
        async for event in provider.stream(
            model="test-model",
            system_prompt="You are helpful.",
            messages=messages,
            tools=[],
        )
    ]


def _is_object_list(value: object) -> TypeGuard[list[object]]:
    """Narrow an arbitrary value to a list of objects."""
    return isinstance(value, list)


def _has_tool_call_delta(event: AssistantMessageEvent) -> bool:
    """Return True when an event carries tool call delta data."""
    if event.delta is None:
        return False
    return event.delta.tool_calls is not None


class OpenAIProviderStreamingTests(unittest.TestCase):
    """Tests OpenAI stream parsing via the public stream API."""

    def test_stream_emits_delta_finish_and_usage(self) -> None:
        calls: list[RequestCall] = []
        lines = [
            "data: "
            + json.dumps(
                {"choices": [{"delta": {"content": "Hi"}, "finish_reason": None}]}
            ),
            "data: "
            + json.dumps({"choices": [{"delta": {}, "finish_reason": "stop"}]}),
            "data: "
            + json.dumps(
                {
                    "usage": {
                        "prompt_tokens": 1,
                        "completion_tokens": 2,
                        "total_tokens": 3,
                    }
                }
            ),
            "data: [DONE]",
        ]
        provider = OpenAIProvider(api_key="test-key")
        messages = [
            Message(
                role=Role.USER,
                content=[TextContent(type="text", text="Q")],
            )
        ]
        tool_message = Message(
            role=Role.TOOL,
            content=[TextContent(type="text", text="tool result")],
            tool_call_id="call_123",
        )

        with patch(
            "src.providers.openai.httpx.AsyncClient",
            return_value=FakeAsyncClient(lines, calls),
        ):
            events = asyncio.run(_collect_events(provider, [messages[0], tool_message]))

        assert len(events) == OPENAI_EXPECTED_EVENT_COUNT
        assert events[0].delta is not None
        assert events[0].delta.content[0] == TextContent(type="text", text="Hi")
        assert events[1].finish_reason == "stop"
        assert events[2].usage is not None
        assert events[2].usage.total_tokens == OPENAI_EXPECTED_TOTAL_TOKENS
        assert len(calls) == 1
        call = calls[0]
        assert call["method"] == "POST"
        assert call["url"] == "https://api.openai.com/v1/chat/completions"
        payload = call["json"]
        assert isinstance(payload, dict)
        payload_messages_obj = payload.get("messages")
        assert _is_object_list(payload_messages_obj)
        payload_messages = payload_messages_obj
        assert len(payload_messages) == OPENAI_EXPECTED_REQUEST_MESSAGES
        second_message = payload_messages[1]
        assert isinstance(second_message, dict)
        assert second_message == {"role": "user", "content": "Q"}
        third_message = payload_messages[2]
        assert isinstance(third_message, dict)
        assert third_message["role"] == "tool"
        assert third_message["tool_call_id"] == "call_123"


class OpenAICompatibleStreamingTests(unittest.TestCase):
    """Tests OpenAI-compatible stream URL and event parsing."""

    def test_stream_uses_custom_base_url(self) -> None:
        calls: list[RequestCall] = []
        lines = [
            "data: "
            + json.dumps(
                {"choices": [{"delta": {"content": "Hi"}, "finish_reason": None}]}
            ),
            "data: "
            + json.dumps({"choices": [{"delta": {}, "finish_reason": "length"}]}),
            "data: [DONE]",
        ]
        provider = OpenAICompatibleProvider(
            api_key="test-key",
            base_url="http://localhost:11434/",
        )
        messages = [
            Message(
                role=Role.USER,
                content=[TextContent(type="text", text="Q")],
            )
        ]

        with patch(
            "src.providers.openai.httpx.AsyncClient",
            return_value=FakeAsyncClient(lines, calls),
        ):
            events = asyncio.run(_collect_events(provider, messages))

        assert provider.base_url == "http://localhost:11434"
        assert len(events) == OPENAI_COMPAT_EXPECTED_EVENT_COUNT
        assert events[0].delta is not None
        assert events[1].finish_reason == "length"
        assert len(calls) == 1
        assert calls[0]["url"] == "http://localhost:11434/chat/completions"

    def test_check_model_access_uses_custom_base_url(self) -> None:
        calls: list[RequestCall] = []
        provider = OpenAICompatibleProvider(
            api_key="test-key",
            base_url="http://localhost:11434/",
        )
        with patch(
            "src.providers.openai.httpx.Client",
            return_value=FakeSyncClient(calls),
        ):
            ok, detail = provider.check_model_access("llama3")

        assert ok is ACCESS_CHECK_OK
        assert detail is None
        assert len(calls) == 1
        assert calls[0]["url"] == "http://localhost:11434/models/llama3"


class AnthropicStreamingTests(unittest.TestCase):
    """Tests Anthropic stream parsing via the public stream API."""

    def test_stream_emits_delta_usage_and_stop(self) -> None:
        calls: list[RequestCall] = []
        lines = [
            "data: "
            + json.dumps(
                {
                    "type": "content_block_delta",
                    "delta": {"type": "text_delta", "text": "Hello"},
                }
            ),
            "data: "
            + json.dumps(
                {
                    "type": "message_delta",
                    "usage": {"input_tokens": 4, "output_tokens": 5},
                }
            ),
            "data: " + json.dumps({"type": "message_stop"}),
        ]
        provider = AnthropicProvider(api_key="test-key")
        messages = [
            Message(
                role=Role.USER,
                content=[TextContent(type="text", text="Q")],
            )
        ]

        with patch(
            "src.providers.anthropic.httpx.AsyncClient",
            return_value=FakeAsyncClient(lines, calls),
        ):
            events = asyncio.run(_collect_events(provider, messages))

        assert len(events) == ANTHROPIC_EXPECTED_EVENT_COUNT
        assert events[0].delta is not None
        assert events[0].delta.content[0] == TextContent(type="text", text="Hello")
        assert events[1].usage is not None
        assert events[1].usage.total_tokens == ANTHROPIC_EXPECTED_TOTAL_TOKENS
        assert events[2].finish_reason == "stop"
        assert len(calls) == 1
        assert calls[0]["url"] == "https://api.anthropic.com/v1/messages"

    def test_check_model_access_success(self) -> None:
        calls: list[RequestCall] = []
        provider = AnthropicProvider(api_key="test-key")
        with patch(
            "src.providers.anthropic.httpx.Client",
            return_value=FakeSyncClient(calls),
        ):
            ok, detail = provider.check_model_access("claude-3-5-haiku-20241022")

        assert ok is ACCESS_CHECK_OK
        assert detail is None
        assert len(calls) == 1
        assert calls[0]["url"] == "https://api.anthropic.com/v1/messages"

    def test_stream_emits_tool_call_delta_and_tool_use_finish_reason(self) -> None:
        calls: list[RequestCall] = []
        lines = [
            "data: "
            + json.dumps(
                {
                    "type": "content_block_start",
                    "index": 0,
                    "content_block": {
                        "type": "tool_use",
                        "id": "toolu_01",
                        "name": "weather",
                        "input": {},
                    },
                }
            ),
            "data: "
            + json.dumps(
                {
                    "type": "content_block_delta",
                    "index": 0,
                    "delta": {"type": "input_json_delta", "partial_json": '{"city":"'},
                }
            ),
            "data: "
            + json.dumps(
                {
                    "type": "content_block_delta",
                    "index": 0,
                    "delta": {"type": "input_json_delta", "partial_json": 'Madrid"}'},
                }
            ),
            "data: " + json.dumps({"type": "content_block_stop", "index": 0}),
            "data: "
            + json.dumps(
                {
                    "type": "message_delta",
                    "delta": {"stop_reason": "tool_use"},
                    "usage": {"input_tokens": 1, "output_tokens": 1},
                }
            ),
        ]
        provider = AnthropicProvider(api_key="test-key")
        messages = [
            Message(
                role=Role.USER,
                content=[TextContent(type="text", text="Q")],
            )
        ]

        with patch(
            "src.providers.anthropic.httpx.AsyncClient",
            return_value=FakeAsyncClient(lines, calls),
        ):
            events = asyncio.run(_collect_events(provider, messages))

        tool_events = [event for event in events if _has_tool_call_delta(event)]
        assert len(tool_events) >= EXPECTED_TOOL_DELTA_EVENT_MINIMUM
        final_delta = tool_events[-1].delta
        assert final_delta is not None
        assert final_delta.tool_calls is not None
        final_tool_call = final_delta.tool_calls[0]
        assert final_tool_call.id == "toolu_01"
        assert final_tool_call.function["name"] == "weather"
        assert final_tool_call.function["arguments"] == '{"city":"Madrid"}'
        finish_events = [event for event in events if event.finish_reason is not None]
        assert finish_events[-1].finish_reason == "toolUse"

    def test_convert_messages_and_access_failure(self) -> None:
        provider = AnthropicProvider(api_key="test-key")
        assistant = Message(
            role=Role.ASSISTANT,
            content=[TextContent(type="text", text="hello")],
            tool_calls=[
                ToolCall(
                    id="call_1",
                    function={"name": "search", "arguments": '{"q":"x"}'},
                )
            ],
        )
        tool_message = Message(
            role=Role.TOOL,
            content=[TextContent(type="text", text="tool result")],
            tool_call_id="call_1",
        )
        converted = provider.convert_messages([assistant, tool_message])

        assert len(converted) == EXPECTED_ANTHROPIC_CONVERTED_MESSAGES
        first_content = converted[0]["content"]
        assert isinstance(first_content, list)
        assert first_content[1]["type"] == "tool_use"
        second_content = converted[1]["content"]
        assert isinstance(second_content, list)
        assert second_content[0]["type"] == "tool_result"

        with patch(
            "src.providers.anthropic.httpx.Client",
            return_value=FakeSyncClient([], should_raise=True),
        ):
            ok, detail = provider.check_model_access("claude-3-5-haiku-20241022")

        assert ok is False
        assert isinstance(detail, str)


class OpenAIAccessibilityTests(unittest.TestCase):
    """Tests OpenAI model accessibility checks."""

    def test_check_model_access_success(self) -> None:
        calls: list[RequestCall] = []
        provider = OpenAIProvider(api_key="test-key")
        with patch(
            "src.providers.openai.httpx.Client",
            return_value=FakeSyncClient(calls),
        ):
            ok, detail = provider.check_model_access("gpt-4o-mini")

        assert ok is ACCESS_CHECK_OK
        assert detail is None
        assert len(calls) == 1
        assert calls[0]["url"] == "https://api.openai.com/v1/models/gpt-4o-mini"

    def test_check_model_access_failure(self) -> None:
        provider = OpenAIProvider(api_key="test-key")
        with patch(
            "src.providers.openai.httpx.Client",
            return_value=FakeSyncClient([], should_raise=True),
        ):
            ok, detail = provider.check_model_access("gpt-4o-mini")

        assert ok is False
        assert isinstance(detail, str)
        assert ACCESS_CHECK_FAILURE_MESSAGE in detail


class OpenAIToolCallParsingTests(unittest.TestCase):
    """Tests OpenAI tool call delta parsing and finish reason normalization."""

    def test_stream_parses_tool_call_deltas(self) -> None:
        calls: list[RequestCall] = []
        lines = [
            "data: "
            + json.dumps(
                {
                    "choices": [
                        {
                            "delta": {
                                "tool_calls": [
                                    {
                                        "index": 0,
                                        "id": "call_abc",
                                        "function": {
                                            "name": "search",
                                            "arguments": '{"q":"',
                                        },
                                    }
                                ]
                            },
                            "finish_reason": None,
                        }
                    ]
                }
            ),
            "data: "
            + json.dumps(
                {
                    "choices": [
                        {
                            "delta": {
                                "tool_calls": [
                                    {
                                        "index": 0,
                                        "function": {"arguments": 'test"}'},
                                    }
                                ]
                            },
                            "finish_reason": "tool_calls",
                        }
                    ]
                }
            ),
        ]
        provider = OpenAIProvider(api_key="test-key")
        messages = [
            Message(
                role=Role.USER,
                content=[TextContent(type="text", text="Q")],
            )
        ]

        with patch(
            "src.providers.openai.httpx.AsyncClient",
            return_value=FakeAsyncClient(lines, calls),
        ):
            events = asyncio.run(_collect_events(provider, messages))

        delta_events = [event for event in events if _has_tool_call_delta(event)]
        assert len(delta_events) == EXPECTED_TOOL_DELTA_EVENT_MINIMUM
        last_delta = delta_events[-1].delta
        assert last_delta is not None
        assert last_delta.tool_calls is not None
        last_tool_call = last_delta.tool_calls[0]
        assert last_tool_call.id == "call_abc"
        assert last_tool_call.function["name"] == "search"
        assert last_tool_call.function["arguments"] == '{"q":"test"}'
        finish_events = [event for event in events if event.finish_reason]
        assert len(finish_events) == 1
        assert finish_events[0].finish_reason == "toolUse"


if __name__ == "__main__":
    unittest.main()
