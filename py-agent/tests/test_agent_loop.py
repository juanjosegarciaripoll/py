"""Unit tests for low-level agent loop behavior."""

from __future__ import annotations

import asyncio
import sys
import unittest
from dataclasses import replace
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Callable, Sequence

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from py_agent.agent_loop import (
    agent_loop,
    agent_loop_continue,
    run_agent_loop,
    run_agent_loop_continue,
)
from py_agent.types import (
    AbortSignal,
    AfterToolCallContext,
    AfterToolCallResult,
    AgentContext,
    AgentEvent,
    AgentEventMessageEnd,
    AgentEventToolExecutionEnd,
    AgentEventToolExecutionUpdate,
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
    ErrorEvent,
    JsonObject,
    Message,
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
    ToolResultMessage,
    UserMessage,
)

EXPECTED_OVERRIDE_MESSAGE_COUNT = 2
EXPECTED_PARTIAL_UPDATE_COUNT = 9
EXPECTED_TOOL_RESULT_COUNT = 2
OVERRIDE_STREAM_MESSAGE = "override stream_fn should be used"
TOOL_FAILED_MESSAGE = "tool failed"


class FakeAssistantEventStream:
    """Simple assistant event stream test stub."""

    def __init__(
        self,
        *,
        events: Sequence[AssistantMessageEvent],
        result_message: AssistantMessage,
    ) -> None:
        self._events = list(events)
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
            on_update(
                AgentToolResult(content=[TextContent(text=f"{self.name}-progress")])
            )
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

    async def test_continue_rejects_invalid_contexts(self) -> None:
        config = AgentLoopConfig(
            model=AgentModel(id="m", api="a", provider="p"),
            convert_to_llm=_convert_to_llm,
        )
        empty = AgentContext(system_prompt="sys", messages=[], tools=[])
        empty_error_message: str | None = None
        try:
            await run_agent_loop_continue(empty, config, _noop_emit)
        except ValueError as error:
            empty_error_message = str(error)
        else:
            self.fail("Expected run_agent_loop_continue to reject empty context")
        assert empty_error_message is not None
        assert "no messages" in empty_error_message

        assistant_context = AgentContext(
            system_prompt="sys",
            messages=[AssistantMessage()],
            tools=[],
        )
        assistant_error_message: str | None = None
        try:
            agent_loop_continue(assistant_context, config)
        except ValueError as error:
            assistant_error_message = str(error)
        else:
            self.fail("Expected agent_loop_continue to reject assistant tail")
        assert assistant_error_message is not None
        assert "assistant" in assistant_error_message

    async def test_continue_stream_helper_returns_result(self) -> None:
        final = AssistantMessage(
            api="test-api",
            provider="test-provider",
            model="test-model",
            content=[TextContent(text="continued")],
        )

        async def stream_fn(
            model: AgentModel,
            context: Context,
            config: AgentLoopConfig,
        ) -> AssistantEventStream:
            del model, context, config
            return FakeAssistantEventStream(
                events=[DoneEvent(reason="stop", message=final)],
                result_message=final,
            )

        config = AgentLoopConfig(
            model=AgentModel(id="m", api="a", provider="p"),
            convert_to_llm=_convert_to_llm,
            stream_fn=stream_fn,
        )
        context = AgentContext(
            system_prompt="sys",
            messages=[UserMessage(content="previous")],
            tools=[],
        )

        stream = agent_loop_continue(context, config)
        seen = [event.type async for event in stream]
        result = await stream.result()

        assert seen[-1] == "agent_end"
        assert result[-1] is final

    async def test_transform_context_empty_conversion_and_stream_override(self) -> None:
        seen_message_counts: list[int] = []

        async def convert_to_llm(messages: list[AgentMessage]) -> list[Message]:
            seen_message_counts.append(len(messages))
            return []

        async def transform_context(
            messages: list[AgentMessage],
            signal: AbortSignal | None,
        ) -> list[AgentMessage]:
            del signal
            return [*messages, UserMessage(content="transformed")]

        async def config_stream_fn(
            model: AgentModel,
            context: Context,
            config: AgentLoopConfig,
        ) -> AssistantEventStream:
            del model, context, config
            raise AssertionError(OVERRIDE_STREAM_MESSAGE)

        async def override_stream_fn(
            model: AgentModel,
            context: Context,
            config: AgentLoopConfig,
        ) -> AssistantEventStream:
            del model, config
            assert len(context.messages) == EXPECTED_OVERRIDE_MESSAGE_COUNT
            final = AssistantMessage(content=[TextContent(text="override")])
            return FakeAssistantEventStream(
                events=[],
                result_message=final,
            )

        config = AgentLoopConfig(
            model=AgentModel(id="m", api="a", provider="p"),
            convert_to_llm=convert_to_llm,
            transform_context=transform_context,
            stream_fn=config_stream_fn,
        )

        events: list[AgentEvent] = []
        await run_agent_loop(
            [UserMessage(content="prompt")],
            AgentContext(system_prompt="sys", messages=[], tools=[]),
            config,
            _collect(events),
            stream_fn=override_stream_fn,
        )

        assert seen_message_counts == [2]
        assert any(isinstance(event, AgentEventMessageEnd) for event in events)

    async def test_stream_forwards_all_partial_event_kinds(self) -> None:
        partial = AssistantMessage(
            content=[
                TextContent(text=""),
                ThinkingContent(thinking=""),
                ToolCallContent(id="call", name="tool", partial_json=""),
            ]
        )
        final_tool_partial = AssistantMessage(
            content=[
                TextContent(text="hello"),
                ThinkingContent(thinking="think"),
                ToolCallContent(id="call", name="tool", arguments={"x": 1}),
            ]
        )
        final = AssistantMessage(
            content=[
                TextContent(text="hello"),
                ThinkingContent(thinking="think"),
            ]
        )
        final_tool_call = ToolCallContent(id="call", name="tool", arguments={"x": 1})
        events: tuple[AssistantMessageEvent, ...] = (
            StartEvent(partial=partial),
            TextStartEvent(content_index=0, partial=partial),
            TextDeltaEvent(content_index=0, delta="hello", partial=partial),
            TextEndEvent(content_index=0, content="hello", partial=partial),
            ThinkingStartEvent(content_index=1, partial=partial),
            ThinkingDeltaEvent(content_index=1, delta="think", partial=partial),
            ThinkingEndEvent(content_index=1, content="think", partial=partial),
            ToolCallStartEvent(content_index=2, partial=partial),
            ToolCallDeltaEvent(content_index=2, delta='{"x":1}', partial=partial),
            ToolCallEndEvent(
                content_index=2,
                tool_call=final_tool_call,
                partial=final_tool_partial,
            ),
            DoneEvent(reason="stop", message=final),
        )

        async def stream_fn(
            model: AgentModel,
            context: Context,
            config: AgentLoopConfig,
        ) -> AssistantEventStream:
            del model, context, config
            return FakeAssistantEventStream(events=events, result_message=final)

        emitted: list[AgentEvent] = []
        await run_agent_loop(
            [UserMessage(content="prompt")],
            AgentContext(system_prompt="sys", messages=[], tools=[]),
            AgentLoopConfig(
                model=AgentModel(id="m", api="a", provider="p"),
                convert_to_llm=_convert_to_llm,
                stream_fn=stream_fn,
            ),
            _collect(emitted),
        )

        update_count = len(
            [event for event in emitted if event.type == "message_update"]
        )
        assert update_count == EXPECTED_PARTIAL_UPDATE_COUNT

    async def test_error_response_ends_agent_early(self) -> None:
        error_message = AssistantMessage(
            stop_reason="error",
            error_message="boom",
            content=[TextContent(text="")],
        )

        async def stream_fn(
            model: AgentModel,
            context: Context,
            config: AgentLoopConfig,
        ) -> AssistantEventStream:
            del model, context, config
            return FakeAssistantEventStream(
                events=[ErrorEvent(reason="error", error=error_message)],
                result_message=error_message,
            )

        emitted: list[AgentEvent] = []
        result = await run_agent_loop(
            [UserMessage(content="prompt")],
            AgentContext(system_prompt="sys", messages=[], tools=[]),
            AgentLoopConfig(
                model=AgentModel(id="m", api="a", provider="p"),
                convert_to_llm=_convert_to_llm,
                stream_fn=stream_fn,
            ),
            _collect(emitted),
        )

        assert result[-1].role == "assistant"
        assert emitted[-1].type == "agent_end"

    async def test_sequential_tool_required_args_after_hook_and_termination(
        self,
    ) -> None:
        first = AssistantMessage(
            content=[
                ToolCallContent(id="missing", name="needs_arg", arguments={}),
                ToolCallContent(id="ok", name="ok", arguments={"value": "x"}),
            ],
            stop_reason="toolUse",
        )
        second = AssistantMessage(content=[TextContent(text="done")])
        responses = [first, second]

        class RequiredTool(RecordingTool):
            def __init__(self, *, name: str) -> None:
                super().__init__(name=name)
                self.parameters = {"required": ["value"]}

        class TerminatingTool(RecordingTool):
            async def execute(
                self,
                tool_call_id: str,
                params: JsonObject,
                signal: AbortSignal | None = None,
                on_update: Callable[[AgentToolResult], None] | None = None,
            ) -> AgentToolResult:
                del tool_call_id, params, signal, on_update
                return AgentToolResult(
                    content=[TextContent(text="original")],
                    details="scalar",
                    terminate=True,
                )

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

        async def after_tool_call(
            context: AfterToolCallContext,
            signal: AbortSignal | None,
        ) -> AfterToolCallResult | None:
            del context, signal
            return AfterToolCallResult(
                content=[TextContent(text="overridden")],
                details={"after": True},
                is_error=True,
            )

        emitted: list[AgentEvent] = []
        result = await run_agent_loop(
            [UserMessage(content="run")],
            AgentContext(
                system_prompt="sys",
                messages=[],
                tools=[
                    RequiredTool(name="needs_arg"),
                    TerminatingTool(name="ok"),
                ],
            ),
            AgentLoopConfig(
                model=AgentModel(id="m", api="a", provider="p"),
                convert_to_llm=_convert_to_llm,
                stream_fn=stream_fn,
                tool_execution="sequential",
                after_tool_call=after_tool_call,
            ),
            _collect(emitted),
        )

        tool_results = [
            event.message
            for event in emitted
            if isinstance(event, AgentEventMessageEnd)
            and isinstance(event.message, ToolResultMessage)
        ]
        updates = [
            event
            for event in emitted
            if isinstance(event, AgentEventToolExecutionUpdate)
        ]

        assert len(tool_results) == EXPECTED_TOOL_RESULT_COUNT
        assert tool_results[0].is_error
        assert tool_results[1].is_error
        assert tool_results[1].details == {"after": True}
        assert updates == []
        assert result[-1].role == "assistant"

    async def test_tool_execution_error_and_missing_tool_are_reported(self) -> None:
        assistant = AssistantMessage(
            content=[
                ToolCallContent(id="missing", name="missing", arguments={}),
                ToolCallContent(id="bad", name="bad", arguments={}),
            ],
            stop_reason="toolUse",
        )
        follow_up = AssistantMessage(content=[TextContent(text="done")])
        responses = [assistant, follow_up]

        class FailingTool(RecordingTool):
            async def execute(
                self,
                tool_call_id: str,
                params: JsonObject,
                signal: AbortSignal | None = None,
                on_update: Callable[[AgentToolResult], None] | None = None,
            ) -> AgentToolResult:
                del tool_call_id, params, signal, on_update
                raise RuntimeError(TOOL_FAILED_MESSAGE)

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

        emitted: list[AgentEvent] = []
        await run_agent_loop(
            [UserMessage(content="run")],
            AgentContext(
                system_prompt="sys",
                messages=[],
                tools=[FailingTool(name="bad")],
            ),
            AgentLoopConfig(
                model=AgentModel(id="m", api="a", provider="p"),
                convert_to_llm=_convert_to_llm,
                stream_fn=stream_fn,
            ),
            _collect(emitted),
        )

        tool_results = [
            event.message
            for event in emitted
            if isinstance(event, AgentEventMessageEnd)
            and isinstance(event.message, ToolResultMessage)
        ]
        assert [message.is_error for message in tool_results] == [True, True]


if __name__ == "__main__":
    unittest.main()

