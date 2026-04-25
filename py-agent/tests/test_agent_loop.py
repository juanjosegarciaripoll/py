"""Unit tests for low-level agent loop behavior."""

from __future__ import annotations

import asyncio
import sys
import unittest
from dataclasses import replace
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Callable

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.agent_loop import agent_loop, run_agent_loop
from src.types import (
    AbortSignal,
    AgentContext,
    AgentEvent,
    AgentEventMessageEnd,
    AgentEventToolExecutionEnd,
    AgentLoopConfig,
    AgentMessage,
    AgentModel,
    AgentTool,
    AgentToolResult,
    AssistantEventStream,
    AssistantMessage,
    AssistantMessageEvent,
    BeforeToolCallContext,
    BeforeToolCallResult,
    Context,
    DoneEvent,
    JsonObject,
    Message,
    StartEvent,
    TextContent,
    TextDeltaEvent,
    ToolCallContent,
    ToolResultMessage,
    UserMessage,
)


class FakeAssistantEventStream:
    """Simple assistant event stream test stub."""

    def __init__(
        self,
        *,
        events: list[AssistantMessageEvent],
        result_message: AssistantMessage,
    ) -> None:
        self._events = events
        self._result_message = result_message

    def __aiter__(self) -> AsyncIterator[AssistantMessageEvent]:
        async def iterate() -> AsyncIterator[AssistantMessageEvent]:
            for event in self._events:
                yield event

        return iterate()

    async def result(self) -> AssistantMessage:
        return self._result_message


class RecordingTool(AgentTool):
    """Tool stub that can delay and record execution order."""

    def __init__(self, *, name: str, delay: float = 0.0) -> None:
        self.name = name
        self.label = name
        self.description = name
        self.parameters = {}
        self.execution_mode = None
        self._delay = delay

    async def execute(
        self,
        tool_call_id: str,
        params: JsonObject,
        signal: AbortSignal | None = None,
        on_update: Callable[[AgentToolResult], None] | None = None,
    ) -> AgentToolResult:
        del tool_call_id, params, signal
        if self._delay > 0:
            await asyncio.sleep(self._delay)
        if on_update is not None:
            on_update(AgentToolResult(content=[TextContent(text=f"{self.name}-progress")]))
        return AgentToolResult(
            content=[TextContent(text=f"{self.name}-done")],
            details={},
        )


async def _convert_to_llm(messages: list[AgentMessage]) -> list[Message]:
    return [*messages]


def _collect(events: list[AgentEvent]) -> Callable[[AgentEvent], None]:
    def emit(event: AgentEvent) -> None:
        events.append(event)

    return emit


def _noop_emit(event: AgentEvent) -> None:
    del event


class AgentLoopTests(unittest.IsolatedAsyncioTestCase):
    """Tests low-level loop lifecycle and tool semantics."""

    async def test_prompt_event_sequence_without_tools(self) -> None:
        assistant = AssistantMessage(
            api="test-api",
            provider="test-provider",
            model="test-model",
            content=[TextContent(text="hello")],
            stop_reason="stop",
        )

        async def stream_fn(
            model: AgentModel,
            context: Context,
            config: AgentLoopConfig,
        ) -> AssistantEventStream:
            del model, context, config
            return FakeAssistantEventStream(
                events=[DoneEvent(reason="stop", message=assistant)],
                result_message=assistant,
            )

        config = AgentLoopConfig(
            model=AgentModel(id="m", api="a", provider="p"),
            convert_to_llm=_convert_to_llm,
            stream_fn=stream_fn,
        )
        context = AgentContext(system_prompt="sys", messages=[], tools=[])
        prompt = UserMessage(content="hi")

        stream = agent_loop([prompt], context, config)
        event_types = [event.type async for event in stream]
        expected = [
            "agent_start",
            "turn_start",
            "message_start",
            "message_end",
            "message_start",
            "message_end",
            "turn_end",
            "agent_end",
        ]
        assert event_types == expected

    async def test_stream_emits_message_update_for_partial_events(self) -> None:
        partial = AssistantMessage(
            api="test-api",
            provider="test-provider",
            model="test-model",
            content=[TextContent(text="")],
        )
        finished = replace(
            partial,
            content=[TextContent(text="hello")],
            stop_reason="stop",
        )

        async def stream_fn(
            model: AgentModel,
            context: Context,
            config: AgentLoopConfig,
        ) -> AssistantEventStream:
            del model, context, config
            return FakeAssistantEventStream(
                events=[
                    StartEvent(partial=partial),
                    TextDeltaEvent(content_index=0, delta="hello", partial=finished),
                    DoneEvent(reason="stop", message=finished),
                ],
                result_message=finished,
            )

        config = AgentLoopConfig(
            model=AgentModel(id="m", api="a", provider="p"),
            convert_to_llm=_convert_to_llm,
            stream_fn=stream_fn,
        )
        context = AgentContext(system_prompt="sys", messages=[], tools=[])
        events: list[AgentEvent] = []

        await run_agent_loop(
            [UserMessage(content="hi")],
            context,
            config,
            _collect(events),
        )
        update_events = [event for event in events if event.type == "message_update"]
        assert len(update_events) == 1

    async def test_parallel_tool_execution_end_order_differs_from_tool_result_order(
        self,
    ) -> None:
        first_assistant = AssistantMessage(
            api="test-api",
            provider="test-provider",
            model="test-model",
            content=[
                ToolCallContent(id="slow", name="slow", arguments={}),
                ToolCallContent(id="fast", name="fast", arguments={}),
            ],
            stop_reason="toolUse",
        )
        second_assistant = AssistantMessage(
            api="test-api",
            provider="test-provider",
            model="test-model",
            content=[TextContent(text="done")],
            stop_reason="stop",
        )
        responses = [first_assistant, second_assistant]

        async def stream_fn(
            model: AgentModel,
            context: Context,
            config: AgentLoopConfig,
        ) -> AssistantEventStream:
            del model, context, config
            message = responses.pop(0)
            done_event = (
                DoneEvent(reason="toolUse", message=message)
                if message.stop_reason == "toolUse"
                else DoneEvent(reason="stop", message=message)
            )
            return FakeAssistantEventStream(
                events=[done_event],
                result_message=message,
            )

        tools: list[AgentTool] = [
            RecordingTool(name="slow", delay=0.03),
            RecordingTool(name="fast", delay=0.0),
        ]
        config = AgentLoopConfig(
            model=AgentModel(id="m", api="a", provider="p"),
            convert_to_llm=_convert_to_llm,
            stream_fn=stream_fn,
            tool_execution="parallel",
        )
        events: list[AgentEvent] = []
        context = AgentContext(system_prompt="sys", messages=[], tools=tools)

        await run_agent_loop(
            [UserMessage(content="run")],
            context,
            config,
            _collect(events),
        )

        tool_end_ids = [
            event.tool_call_id
            for event in events
            if isinstance(event, AgentEventToolExecutionEnd)
        ]
        assert tool_end_ids == ["fast", "slow"]

        tool_message_ids = [
            event.message.tool_call_id
            for event in events
            if isinstance(event, AgentEventMessageEnd)
            and isinstance(event.message, ToolResultMessage)
        ]
        assert tool_message_ids == ["slow", "fast"]

    async def test_before_hook_can_block_tool_execution(self) -> None:
        assistant = AssistantMessage(
            api="test-api",
            provider="test-provider",
            model="test-model",
            content=[ToolCallContent(id="blocked", name="blocked", arguments={})],
            stop_reason="toolUse",
        )
        follow_up = AssistantMessage(
            api="test-api",
            provider="test-provider",
            model="test-model",
            content=[TextContent(text="after")],
            stop_reason="stop",
        )
        responses = [assistant, follow_up]

        async def stream_fn(
            model: AgentModel,
            context: Context,
            config: AgentLoopConfig,
        ) -> AssistantEventStream:
            del model, context, config
            message = responses.pop(0)
            done_event = (
                DoneEvent(reason="toolUse", message=message)
                if message.stop_reason == "toolUse"
                else DoneEvent(reason="stop", message=message)
            )
            return FakeAssistantEventStream(
                events=[done_event],
                result_message=message,
            )

        async def before_tool_call(
            context: BeforeToolCallContext,
            signal: AbortSignal | None,
        ) -> BeforeToolCallResult | None:
            del signal
            if context.tool_call.name == "blocked":
                return BeforeToolCallResult(block=True, reason="blocked by policy")
            return None

        config = AgentLoopConfig(
            model=AgentModel(id="m", api="a", provider="p"),
            convert_to_llm=_convert_to_llm,
            stream_fn=stream_fn,
            before_tool_call=before_tool_call,
        )
        events: list[AgentEvent] = []
        context = AgentContext(
            system_prompt="sys",
            messages=[],
            tools=[RecordingTool(name="blocked")],
        )

        await run_agent_loop(
            [UserMessage(content="run")],
            context,
            config,
            _collect(events),
        )

        tool_result_messages = [
            event.message
            for event in events
            if isinstance(event, AgentEventMessageEnd)
            and isinstance(event.message, ToolResultMessage)
        ]
        assert len(tool_result_messages) == 1
        assert tool_result_messages[0].is_error

    async def test_resolves_dynamic_api_key_before_stream_call(self) -> None:
        seen_api_keys: list[str | None] = []

        async def stream_fn(
            model: AgentModel,
            context: Context,
            config: AgentLoopConfig,
        ) -> AssistantEventStream:
            del model, context
            seen_api_keys.append(config.api_key)
            message = AssistantMessage(
                api="test-api",
                provider="test-provider",
                model="test-model",
                content=[TextContent(text="hello")],
            )
            return FakeAssistantEventStream(
                events=[DoneEvent(reason="stop", message=message)],
                result_message=message,
            )

        async def get_api_key(provider: str) -> str | None:
            del provider
            return "dynamic-token"

        config = AgentLoopConfig(
            model=AgentModel(id="m", api="a", provider="p"),
            convert_to_llm=_convert_to_llm,
            stream_fn=stream_fn,
            api_key="static-token",
            get_api_key=get_api_key,
        )
        context = AgentContext(system_prompt="sys", messages=[], tools=[])

        await run_agent_loop(
            [UserMessage(content="hello")],
            context,
            config,
            _noop_emit,
        )
        assert seen_api_keys == ["dynamic-token"]


if __name__ == "__main__":
    unittest.main()
