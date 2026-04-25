"""Tests for unified communication helpers."""

from __future__ import annotations

import asyncio
import sys
import unittest
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.types import JsonObject

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.communication import (
    AssistantMessage,
    AssistantMessageEventStream,
    Context,
    DoneEvent,
    ErrorEvent,
    Message,
    StartEvent,
    TextContent,
    TextDeltaEvent,
    ThinkingContent,
    ToolCallContent,
    ToolResultMessage,
    Usage,
    UserMessage,
    create_assistant_message,
    is_context_overflow,
    normalize_tool_call_id,
    parse_assistant_event,
    parse_streaming_json,
    sanitize_surrogates,
    transform_messages_for_handoff,
)

EXPECTED_ROUNDTRIP_MESSAGE_COUNT = 3
EXPECTED_HASHED_ID_LENGTH = 16
EXPECTED_COST_INPUT = 2.0
EXPECTED_COST_OUTPUT = 2.0
EXPECTED_COST_CACHE_READ = 0.25
EXPECTED_COST_TOTAL = 4.25
EXPECTED_SAME_MODEL_TRANSFORMED_COUNT = 2


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
        assert len(replayed.messages) == EXPECTED_ROUNDTRIP_MESSAGE_COUNT
        assert isinstance(replayed.messages[1], AssistantMessage)

    def test_context_from_json_rejects_non_object_payload(self) -> None:
        try:
            Context.from_json("[]")
        except TypeError:
            pass
        else:
            msg = "Expected TypeError when Context JSON is not an object"
            raise AssertionError(msg)


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

    def test_normalize_tool_call_id_empty_and_truncated(self) -> None:
        assert normalize_tool_call_id("!!!") == "tool_call"
        long_id = normalize_tool_call_id(
            "x" * 100,
            max_length=EXPECTED_HASHED_ID_LENGTH,
        )
        assert len(long_id) == EXPECTED_HASHED_ID_LENGTH

    def test_parse_streaming_json_handles_empty_and_invalid_inputs(self) -> None:
        assert parse_streaming_json(None) == {}
        assert parse_streaming_json("   ") == {}
        assert parse_streaming_json('{"a":"\\') == {"a": "\\"}


class CommunicationParsingTests(unittest.TestCase):
    """Tests assistant event parsing and cost helpers."""

    def test_usage_with_cost_computes_totals(self) -> None:
        usage = Usage(input=2_000_000, output=1_000_000, cache_read=500_000)
        costed = usage.with_cost(
            input_per_million=1.0,
            output_per_million=2.0,
            cache_read_per_million=0.5,
        )
        assert costed.cost.input == EXPECTED_COST_INPUT
        assert costed.cost.output == EXPECTED_COST_OUTPUT
        assert costed.cost.cache_read == EXPECTED_COST_CACHE_READ
        assert costed.cost.total == EXPECTED_COST_TOTAL

    def test_parse_assistant_event_variants_and_unknown_type(self) -> None:
        partial = create_assistant_message(
            api="openai-completions",
            provider="openai",
            model="gpt-4o-mini",
        )
        start_payload: JsonObject = {
            "type": "start",
            "partial": partial.model_dump(mode="json"),
        }
        parsed_start = parse_assistant_event(start_payload)
        assert isinstance(parsed_start, StartEvent)

        delta_payload: JsonObject = {
            "type": "text_delta",
            "content_index": 0,
            "delta": "hi",
            "partial": partial.model_dump(mode="json"),
        }
        parsed_delta = parse_assistant_event(delta_payload)
        assert isinstance(parsed_delta, TextDeltaEvent)

        try:
            parse_assistant_event({"type": "mystery"})
        except ValueError:
            pass
        else:
            msg = "Expected ValueError for unknown assistant event type"
            raise AssertionError(msg)


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

    def test_transform_messages_same_model_preserves_reasoning_and_tool_results(
        self,
    ) -> None:
        messages: list[Message] = [
            AssistantMessage(
                api="openai-completions",
                provider="openai",
                model="gpt-4o-mini",
                content=[
                    ThinkingContent(thinking="kept"),
                    ToolCallContent(id="call_1", name="search", arguments={"q": "x"}),
                ],
                stop_reason="toolUse",
            ),
            ToolResultMessage(
                tool_call_id="call_1",
                tool_name="search",
                content=[TextContent(text="ok")],
            ),
            AssistantMessage(
                api="openai-completions",
                provider="openai",
                model="gpt-4o-mini",
                content=[ThinkingContent(thinking="hidden", redacted=True)],
                stop_reason="aborted",
            ),
        ]
        transformed = transform_messages_for_handoff(
            messages,
            target_provider="openai",
            target_api="openai-completions",
            target_model="gpt-4o-mini",
        )

        assistant = transformed[0]
        assert isinstance(assistant, AssistantMessage)
        assert isinstance(assistant.content[0], ThinkingContent)
        tool_result = transformed[1]
        assert isinstance(tool_result, ToolResultMessage)
        assert tool_result.tool_call_id == "call_1"
        assert len(transformed) == EXPECTED_SAME_MODEL_TRANSFORMED_COUNT


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

    def test_non_overflow_errors_and_default_stop_are_not_flagged(self) -> None:
        throttled = AssistantMessage(
            api="openai-completions",
            provider="openai",
            model="gpt-4o-mini",
            stop_reason="error",
            error_message="rate limit exceeded",
        )
        normal = AssistantMessage(
            api="openai-completions",
            provider="openai",
            model="gpt-4o-mini",
            stop_reason="stop",
            usage=Usage(input=10, cache_read=5),
        )
        assert is_context_overflow(throttled) is False
        assert is_context_overflow(normal, context_window=100) is False


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

    def test_end_resolves_result_and_subsequent_close_is_ignored(self) -> None:
        async def runner() -> tuple[list[str], AssistantMessage]:
            stream = AssistantMessageEventStream()
            message = create_assistant_message(
                api="openai-completions",
                provider="openai",
                model="gpt-4o-mini",
                response_id="resp_1",
            )
            stream.end(message)
            stream.push(DoneEvent(reason="stop", message=message))
            events: list[str] = [event.type async for event in stream]
            return events, await stream.result()

        events, result = asyncio.run(runner())
        assert events == []
        assert result.response_id == "resp_1"


if __name__ == "__main__":
    unittest.main()
