"""Tests for unified communication helpers."""

import asyncio
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.communication import (
    AssistantMessage,
    AssistantMessageEventStream,
    Context,
    DoneEvent,
    ErrorEvent,
    Message,
    TextContent,
    ThinkingContent,
    ToolCallContent,
    ToolResultMessage,
    Usage,
    UserMessage,
    is_context_overflow,
    normalize_tool_call_id,
    parse_streaming_json,
    sanitize_surrogates,
    transform_messages_for_handoff,
)


class CommunicationSerializationTests(unittest.TestCase):
    """Tests context serialization and replay compatibility."""

    def test_context_roundtrip_json(self) -> None:
        context = Context(
            system_prompt="Be concise",
            messages=[
                UserMessage(content="Hello"),
                AssistantMessage(
                    api="openai-completions",
                    provider="openai",
                    model="gpt-4o-mini",
                    content=[
                        TextContent(text="Hi"),
                        ThinkingContent(thinking="internal"),
                        ToolCallContent(
                            id="call_1",
                            name="weather",
                            arguments={"city": "Madrid"},
                        ),
                    ],
                ),
                ToolResultMessage(
                    tool_call_id="call_1",
                    tool_name="weather",
                    content=[TextContent(text="sunny")],
                ),
            ],
        )
        payload = context.to_json()
        replayed = Context.from_json(payload)

        assert replayed.system_prompt == "Be concise"
        expected_message_count = 3
        assert len(replayed.messages) == expected_message_count
        assert isinstance(replayed.messages[1], AssistantMessage)


class CommunicationRobustnessTests(unittest.TestCase):
    """Tests JSON parsing, unicode sanitization and ID normalization."""

    def test_parse_streaming_json_repairs_and_closes_partial(self) -> None:
        parsed = parse_streaming_json('{"a":"x\\q","b":"line\nend"')
        assert parsed["a"] == "x\\q"
        assert parsed["b"] == "line\nend"

    def test_sanitize_surrogates_removes_unpaired(self) -> None:
        broken = f"a{chr(0xD83D)}b"
        assert sanitize_surrogates(broken) == "ab"

    def test_normalize_tool_call_id(self) -> None:
        normalized = normalize_tool_call_id("call|with spaces|and/slashes")
        assert "|" not in normalized
        assert " " not in normalized
        assert "/" not in normalized


class CommunicationHandoffTests(unittest.TestCase):
    """Tests cross-provider message transformations."""

    def test_transform_messages_converts_thinking_and_inserts_missing_tool_results(
        self,
    ) -> None:
        messages: list[Message] = [
            UserMessage(content="Hi"),
            AssistantMessage(
                api="openai-completions",
                provider="openai",
                model="gpt-4o-mini",
                content=[
                    ThinkingContent(thinking="reasoned"),
                    ToolCallContent(
                        id="tool|id|1",
                        name="search",
                        arguments={"q": "x"},
                        thought_signature="secret",
                    ),
                ],
                stop_reason="toolUse",
            ),
            UserMessage(content="Continue"),
        ]
        transformed = transform_messages_for_handoff(
            messages,
            target_provider="anthropic",
            target_api="anthropic-messages",
            target_model="claude-3-5-haiku-20241022",
        )

        assert isinstance(transformed[1], AssistantMessage)
        assistant = transformed[1]
        assert isinstance(assistant.content[0], TextContent)
        assert isinstance(transformed[2], ToolResultMessage)
        tool_result = transformed[2]
        assert tool_result.is_error is True
        assert tool_result.tool_call_id == normalize_tool_call_id("tool|id|1")


class CommunicationOverflowTests(unittest.TestCase):
    """Tests overflow detection behavior."""

    def test_detects_error_overflow(self) -> None:
        message = AssistantMessage(
            api="openai-completions",
            provider="openai",
            model="gpt-4o-mini",
            stop_reason="error",
            error_message="Your input exceeds the context window of this model",
        )
        assert is_context_overflow(message) is True

    def test_detects_silent_overflow(self) -> None:
        message = AssistantMessage(
            api="zai",
            provider="zai",
            model="glm",
            usage=Usage(input=5000, cache_read=100, total_tokens=5100),
        )
        assert is_context_overflow(message, context_window=4096) is True


class CommunicationEventStreamTests(unittest.TestCase):
    """Tests event stream finalization behavior."""

    def test_done_event_resolves_result(self) -> None:
        async def runner() -> AssistantMessage:
            stream = AssistantMessageEventStream()
            msg = AssistantMessage(
                api="openai-completions",
                provider="openai",
                model="gpt-4o-mini",
                content=[TextContent(text="Hello")],
            )
            stream.push(DoneEvent(reason="stop", message=msg))
            events = [event async for event in stream]
            assert len(events) == 1
            return await stream.result()

        result = asyncio.run(runner())
        first_content = result.content[0]
        assert isinstance(first_content, TextContent)
        assert first_content.text == "Hello"

    def test_error_event_resolves_result(self) -> None:
        async def runner() -> AssistantMessage:
            stream = AssistantMessageEventStream()
            msg = AssistantMessage(
                api="openai-completions",
                provider="openai",
                model="gpt-4o-mini",
                stop_reason="error",
                error_message="boom",
            )
            stream.push(ErrorEvent(reason="error", error=msg))
            _events = [event async for event in stream]
            return await stream.result()

        result = asyncio.run(runner())
        assert result.error_message == "boom"


if __name__ == "__main__":
    unittest.main()
