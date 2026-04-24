"""Unit tests for provider streaming behavior."""

import asyncio
import json
import sys
import typing as t
import unittest
from pathlib import Path
from types import TracebackType
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.providers.anthropic import AnthropicProvider
from src.providers.openai import OpenAIProvider
from src.providers.openai_compatible import OpenAICompatibleProvider
from src.types import AssistantMessageEvent, Message, Role, TextContent

OPENAI_EXPECTED_EVENT_COUNT = 3
OPENAI_EXPECTED_TOTAL_TOKENS = 3
OPENAI_EXPECTED_REQUEST_MESSAGES = 2
OPENAI_COMPAT_EXPECTED_EVENT_COUNT = 2
ANTHROPIC_EXPECTED_EVENT_COUNT = 3
ANTHROPIC_EXPECTED_TOTAL_TOKENS = 9


class RequestCall(t.TypedDict):
    """Recorded outbound request details for assertions."""

    method: str
    url: str
    headers: dict[str, str]
    json: dict[str, object]


class FakeResponse:
    """Async context manager that yields predefined SSE lines."""

    def __init__(self, lines: list[str]) -> None:
        self._lines = lines

    async def __aenter__(self) -> t.Self:
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

    async def aiter_lines(self) -> t.AsyncIterator[str]:
        for line in self._lines:
            yield line


class FakeAsyncClient:
    """Async client that records request payloads and returns fake responses."""

    def __init__(self, lines: list[str], calls: list[RequestCall]) -> None:
        self._lines = lines
        self._calls = calls

    async def __aenter__(self) -> t.Self:
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


def _is_object_list(value: object) -> t.TypeGuard[list[object]]:
    """Narrow an arbitrary value to a list of objects."""
    return isinstance(value, list)


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
        )

        with patch(
            "src.providers.openai.httpx.AsyncClient",
            return_value=FakeAsyncClient(lines, calls),
        ):
            events = asyncio.run(
                _collect_events(provider, [messages[0], tool_message])
            )

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
            "src.providers.openai_compatible.httpx.AsyncClient",
            return_value=FakeAsyncClient(lines, calls),
        ):
            events = asyncio.run(_collect_events(provider, messages))

        assert provider.base_url == "http://localhost:11434"
        assert len(events) == OPENAI_COMPAT_EXPECTED_EVENT_COUNT
        assert events[0].delta is not None
        assert events[1].finish_reason == "length"
        assert len(calls) == 1
        assert calls[0]["url"] == "http://localhost:11434/chat/completions"


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


if __name__ == "__main__":
    unittest.main()
