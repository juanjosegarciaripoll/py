"""Unit tests for high-level Agent behavior."""

from __future__ import annotations

import asyncio
import sys
import time
import unittest
from pathlib import Path
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Callable

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from py_agent.agent import Agent, AgentOptions
from py_agent.types import (
    AbortSignal,
    AgentEvent,
    AgentLoopConfig,
    AgentModel,
    AgentTool,
    AgentToolResult,
    AssistantMessage,
    AssistantMessageEvent,
    Context,
    DoneEvent,
    ImageContent,
    JsonObject,
    TextContent,
    ToolCallContent,
    ToolResultMessage,
    UserMessage,
)

EXPECTED_PROMPT_MESSAGES = 2
EXPECTED_CONTINUE_MESSAGES = 4
LISTENER_DELAY_SECONDS = 0.02


class FakeAssistantEventStream:
    """Simple assistant event stream test stub."""

    def __init__(self, result_message: AssistantMessage) -> None:
        self._result_message = result_message

    async def __aiter__(self) -> AsyncIterator[AssistantMessageEvent]:
        yield DoneEvent(reason="stop", message=self._result_message)

    async def result(self) -> AssistantMessage:
        return self._result_message


class EchoTool(AgentTool):
    """Simple tool stub for Agent integration tests."""

    def __init__(self, name: str = "echo") -> None:
        self.name = name
        self.label = name
        self.description = name
        self.parameters = {}

    async def execute(
        self,
        tool_call_id: str,
        params: JsonObject,
        signal: AbortSignal | None = None,
        on_update: Callable[[AgentToolResult], None] | None = None,
    ) -> AgentToolResult:
        del tool_call_id, params, signal
        if on_update is not None:
            on_update(AgentToolResult(content=[TextContent(text="working")]))
        return AgentToolResult(content=[TextContent(text="done")])


class AgentTests(unittest.IsolatedAsyncioTestCase):
    """Tests stateful Agent wrapper semantics."""

    async def test_prompt_updates_transcript_and_state(self) -> None:
        calls = 0

        async def stream_fn(
            model: AgentModel,
            context: Context,
            config: AgentLoopConfig,
        ) -> FakeAssistantEventStream:
            del model, context, config
            nonlocal calls
            calls += 1
            message = AssistantMessage(
                api="test-api",
                provider="test-provider",
                model="test-model",
                content=[TextContent(text=f"assistant-{calls}")],
            )
            return FakeAssistantEventStream(message)

        agent = Agent(
            AgentOptions(
                initial_model=AgentModel(id="m", api="a", provider="p"),
                stream_fn=stream_fn,
            )
        )
        await agent.prompt("hello")

        assert not agent.state.is_streaming
        assert len(agent.state.messages) == EXPECTED_PROMPT_MESSAGES
        assert agent.state.messages[0].role == "user"
        assert agent.state.messages[1].role == "assistant"

    async def test_continue_uses_queued_follow_up_after_assistant(self) -> None:
        seen_user_contents: list[str] = []

        async def stream_fn(
            model: AgentModel,
            context: Context,
            config: AgentLoopConfig,
        ) -> FakeAssistantEventStream:
            del model, config
            for message in context.messages:
                if isinstance(message, UserMessage):
                    if isinstance(message.content, str):
                        seen_user_contents.append(message.content)
                    elif message.content:
                        first_block = message.content[0]
                        if isinstance(first_block, TextContent):
                            seen_user_contents.append(first_block.text)
            return FakeAssistantEventStream(
                AssistantMessage(
                    api="test-api",
                    provider="test-provider",
                    model="test-model",
                    content=[TextContent(text="ok")],
                )
            )

        agent = Agent(
            AgentOptions(
                initial_model=AgentModel(id="m", api="a", provider="p"),
                stream_fn=stream_fn,
            )
        )
        await agent.prompt("first")
        agent.follow_up(UserMessage(content=[TextContent(text="follow")]))
        await agent.continue_()

        assert "first" in seen_user_contents
        assert "follow" in seen_user_contents
        # first run adds user+assistant, second run adds queued user+assistant
        assert len(agent.state.messages) == EXPECTED_CONTINUE_MESSAGES

    async def test_agent_end_listener_is_awaited_before_prompt_returns(self) -> None:
        async def stream_fn(
            model: AgentModel,
            context: Context,
            config: AgentLoopConfig,
        ) -> FakeAssistantEventStream:
            del model, context, config
            return FakeAssistantEventStream(
                AssistantMessage(
                    api="test-api",
                    provider="test-provider",
                    model="test-model",
                    content=[TextContent(text="ok")],
                )
            )

        agent = Agent(
            AgentOptions(
                initial_model=AgentModel(id="m", api="a", provider="p"),
                stream_fn=stream_fn,
            )
        )
        listener_done = False

        async def listener(event: AgentEvent, signal: AbortSignal) -> None:
            del signal
            nonlocal listener_done
            if event.type == "agent_end":
                await asyncio.sleep(LISTENER_DELAY_SECONDS)
                listener_done = True

        agent.subscribe(listener)
        start = time.perf_counter()
        await agent.prompt("hello")
        elapsed = time.perf_counter() - start

        assert listener_done
        assert elapsed >= LISTENER_DELAY_SECONDS

    async def test_abort_marks_signal(self) -> None:
        async def stream_fn(
            model: AgentModel,
            context: Context,
            config: AgentLoopConfig,
        ) -> FakeAssistantEventStream:
            del model, context, config
            await asyncio.sleep(0.03)
            return FakeAssistantEventStream(
                AssistantMessage(
                    api="test-api",
                    provider="test-provider",
                    model="test-model",
                    content=[TextContent(text="ok")],
                )
            )

        agent = Agent(
            AgentOptions(
                initial_model=AgentModel(id="m", api="a", provider="p"),
                stream_fn=stream_fn,
            )
        )

        task = asyncio.create_task(agent.prompt("hello"))
        await asyncio.sleep(0)
        signal = agent.signal
        assert signal is not None
        agent.abort()
        await task
        assert signal.aborted

    async def test_prompt_with_images_builds_user_message(self) -> None:
        captured_content_types: list[str] = []

        async def stream_fn(
            model: AgentModel,
            context: Context,
            config: AgentLoopConfig,
        ) -> FakeAssistantEventStream:
            del model, config
            last = context.messages[-1]
            if isinstance(last, UserMessage) and isinstance(last.content, list):
                captured_content_types.extend(block.type for block in last.content)
            return FakeAssistantEventStream(
                AssistantMessage(
                    api="test-api",
                    provider="test-provider",
                    model="test-model",
                    content=[TextContent(text="ok")],
                )
            )

        agent = Agent(
            AgentOptions(
                initial_model=AgentModel(id="m", api="a", provider="p"),
                stream_fn=stream_fn,
            )
        )
        await agent.prompt(
            "describe",
            images=[ImageContent(data="abc", mime_type="image/png")],
        )
        assert captured_content_types == ["text", "image"]

    async def test_agent_queue_management_reset_and_defaults(self) -> None:
        tool = EchoTool()
        initial_message = UserMessage(content="before")
        agent = Agent(
            AgentOptions(
                initial_system_prompt="sys",
                initial_tools=[tool],
                initial_messages=[initial_message],
            )
        )

        assert agent.state.model.id == "unknown"
        assert agent.state.model.api == "unknown"
        assert agent.state.model.provider == "unknown"
        assert agent.steering_mode == "one-at-a-time"
        assert agent.follow_up_mode == "one-at-a-time"
        assert agent.state.tools[0] is tool
        assert agent.state.messages[0] is initial_message
        assert agent.signal is None
        assert not agent.has_queued_messages()

        agent.steering_mode = "all"
        agent.follow_up_mode = "all"
        agent.steer(UserMessage(content="s1"))
        agent.follow_up(UserMessage(content="f1"))
        assert agent.has_queued_messages()

        agent.clear_steering_queue()
        assert agent.has_queued_messages()
        agent.clear_follow_up_queue()
        assert not agent.has_queued_messages()

        agent.steer(UserMessage(content="s2"))
        agent.follow_up(UserMessage(content="f2"))
        agent.reset()

        assert agent.state.messages == []
        assert agent.state.error_message is None
        assert agent.state.pending_tool_calls == set()
        assert agent.state.streaming_message is None
        assert not agent.has_queued_messages()

    async def test_prompt_passes_initial_context_and_reasoning(self) -> None:
        seen_session_ids: list[str | None] = []
        seen_reasoning: list[str | None] = []
        seen_system_prompts: list[str | None] = []
        seen_tools_lengths: list[int | None] = []
        seen_message_roles: list[list[str]] = []
        tool = EchoTool()

        async def stream_fn(
            model: AgentModel,
            context: Context,
            config: AgentLoopConfig,
        ) -> FakeAssistantEventStream:
            del model
            seen_session_ids.append(config.session_id)
            seen_reasoning.append(config.reasoning)
            seen_system_prompts.append(context.system_prompt)
            seen_tools_lengths.append(
                None if context.tools is None else len(context.tools)
            )
            seen_message_roles.append([message.role for message in context.messages])
            return FakeAssistantEventStream(
                AssistantMessage(content=[TextContent(text="ok")])
            )

        agent = Agent(
            AgentOptions(
                initial_system_prompt="sys",
                initial_model=AgentModel(id="m", api="a", provider="p"),
                initial_thinking_level="high",
                initial_tools=[tool],
                initial_messages=[UserMessage(content="history")],
                session_id="session-1",
                stream_fn=stream_fn,
            )
        )

        await agent.prompt(UserMessage(content="prompt"))

        assert seen_session_ids == ["session-1"]
        assert seen_reasoning == ["high"]
        assert seen_system_prompts == ["sys"]
        assert seen_tools_lengths == [None]
        assert seen_message_roles == [["user", "user"]]

    async def test_prompt_rejects_reentry_and_wait_for_idle_blocks_until_finish(
        self,
    ) -> None:
        entered = asyncio.Event()
        release = asyncio.Event()

        async def stream_fn(
            model: AgentModel,
            context: Context,
            config: AgentLoopConfig,
        ) -> FakeAssistantEventStream:
            del model, context, config
            entered.set()
            await release.wait()
            return FakeAssistantEventStream(
                AssistantMessage(content=[TextContent(text="ok")])
            )

        agent = Agent(
            AgentOptions(
                initial_model=AgentModel(id="m", api="a", provider="p"),
                stream_fn=stream_fn,
            )
        )

        first_prompt = asyncio.create_task(agent.prompt("hello"))
        await entered.wait()
        assert agent.signal is not None

        prompt_error_message: str | None = None
        try:
            await agent.prompt("again")
        except RuntimeError as error:
            prompt_error_message = str(error)
        else:
            self.fail("Expected prompt reentry to raise RuntimeError")

        continue_error_message: str | None = None
        try:
            await agent.continue_()
        except RuntimeError as error:
            continue_error_message = str(error)
        else:
            self.fail("Expected continue_ reentry to raise RuntimeError")

        assert prompt_error_message is not None
        assert "already processing a prompt" in prompt_error_message
        assert continue_error_message is not None
        assert "already processing" in continue_error_message
        idle_wait = asyncio.create_task(agent.wait_for_idle())
        await asyncio.sleep(0)
        assert not idle_wait.done()
        release.set()
        await first_prompt
        await idle_wait

    async def test_continue_run_alias_and_assistant_queue_paths(self) -> None:
        seen_inputs: list[str] = []

        async def stream_fn(
            model: AgentModel,
            context: Context,
            config: AgentLoopConfig,
        ) -> FakeAssistantEventStream:
            del model, config
            for message in context.messages:
                if isinstance(message, UserMessage):
                    if isinstance(message.content, str):
                        seen_inputs.append(message.content)
                    else:
                        first = message.content[0]
                        if isinstance(first, TextContent):
                            seen_inputs.append(first.text)
            return FakeAssistantEventStream(
                AssistantMessage(content=[TextContent(text="ok")])
            )

        agent = Agent(
            AgentOptions(
                initial_model=AgentModel(id="m", api="a", provider="p"),
                stream_fn=stream_fn,
                steering_mode="all",
                follow_up_mode="all",
            )
        )
        await agent.prompt("first")
        agent.steer(UserMessage(content="steer-1"))
        agent.steer(UserMessage(content="steer-2"))
        await agent.continue_run()
        agent.follow_up(UserMessage(content="follow-1"))
        agent.follow_up(UserMessage(content="follow-2"))
        await agent.continue_()

        assert "steer-1" in seen_inputs
        assert "steer-2" in seen_inputs
        assert "follow-1" in seen_inputs
        assert "follow-2" in seen_inputs

    async def test_continue_errors_when_not_resumable(self) -> None:
        agent = Agent(
            AgentOptions(initial_model=AgentModel(id="m", api="a", provider="p"))
        )
        empty_error_message: str | None = None
        try:
            await agent.continue_()
        except ValueError as error:
            empty_error_message = str(error)
        else:
            self.fail("Expected empty agent continuation to fail")

        assert empty_error_message is not None
        assert "No messages to continue from" in empty_error_message
        agent.state.messages = [AssistantMessage(content=[TextContent(text="done")])]
        assistant_error_message: str | None = None
        try:
            await agent.continue_()
        except ValueError as error:
            assistant_error_message = str(error)
        else:
            self.fail("Expected assistant-tail continuation to fail")

        assert assistant_error_message is not None
        assert "assistant" in assistant_error_message

    async def test_error_path_records_failure_and_clears_streaming_state(self) -> None:
        async def stream_fn(
            model: AgentModel,
            context: Context,
            config: AgentLoopConfig,
        ) -> FakeAssistantEventStream:
            del model, context, config
            msg = "boom"
            raise RuntimeError(msg)

        agent = Agent(
            AgentOptions(
                initial_model=AgentModel(id="m", api="api", provider="provider"),
                stream_fn=stream_fn,
            )
        )

        await agent.prompt("hello")

        assert not agent.state.is_streaming
        assert agent.state.streaming_message is None
        assert agent.state.pending_tool_calls == set()
        assert agent.state.error_message == "boom"
        last = agent.state.messages[-1]
        assert isinstance(last, AssistantMessage)
        assert last.stop_reason == "error"
        assert last.api == "api"
        assert last.provider == "provider"
        assert last.model == "m"

    async def test_abort_during_failure_marks_aborted_reason(self) -> None:
        release = asyncio.Event()

        async def stream_fn(
            model: AgentModel,
            context: Context,
            config: AgentLoopConfig,
        ) -> FakeAssistantEventStream:
            del model, context, config
            await release.wait()
            msg = "stopped"
            raise RuntimeError(msg)

        agent = Agent(
            AgentOptions(
                initial_model=AgentModel(id="m", api="api", provider="provider"),
                stream_fn=stream_fn,
            )
        )

        task = asyncio.create_task(agent.prompt("hello"))
        await asyncio.sleep(0)
        agent.abort()
        release.set()
        await task

        last = agent.state.messages[-1]
        assert isinstance(last, AssistantMessage)
        assert last.stop_reason == "aborted"

    async def test_subscribe_can_unsubscribe_and_sync_listener_runs(self) -> None:
        seen_event_types: list[str] = []

        async def stream_fn(
            model: AgentModel,
            context: Context,
            config: AgentLoopConfig,
        ) -> FakeAssistantEventStream:
            del model, context, config
            return FakeAssistantEventStream(
                AssistantMessage(content=[TextContent(text="ok")])
            )

        agent = Agent(
            AgentOptions(
                initial_model=AgentModel(id="m", api="a", provider="p"),
                stream_fn=stream_fn,
            )
        )

        def listener(event: AgentEvent, signal: AbortSignal) -> None:
            del signal
            seen_event_types.append(event.type)

        unsubscribe = agent.subscribe(listener)
        await agent.prompt("hello")
        unsubscribe()
        unsubscribe()
        await agent.prompt("again")

        assert seen_event_types.count("agent_start") == 1

    async def test_tool_flow_updates_pending_calls_and_appends_tool_result(
        self,
    ) -> None:
        first_assistant = AssistantMessage(
            content=[ToolCallContent(id="call-1", name="echo", arguments={})],
            stop_reason="toolUse",
        )
        second_assistant = AssistantMessage(content=[TextContent(text="done")])
        responses = [first_assistant, second_assistant]
        snapshots: list[tuple[str, set[str]]] = []

        class SequenceStream:
            def __init__(
                self,
                result_message: AssistantMessage,
                reason: Literal["stop", "toolUse"],
            ) -> None:
                self._result_message = result_message
                self._reason: Literal["stop", "toolUse"] = reason

            async def __aiter__(self) -> AsyncIterator[AssistantMessageEvent]:
                yield DoneEvent(reason=self._reason, message=self._result_message)

            async def result(self) -> AssistantMessage:
                return self._result_message

        async def stream_fn(
            model: AgentModel,
            context: Context,
            config: AgentLoopConfig,
        ) -> SequenceStream:
            del model, context, config
            message = responses.pop(0)
            reason: Literal["stop", "toolUse"] = (
                "toolUse" if message.stop_reason == "toolUse" else "stop"
            )
            return SequenceStream(message, reason)

        agent = Agent(
            AgentOptions(
                initial_model=AgentModel(id="m", api="a", provider="p"),
                initial_tools=[EchoTool()],
                stream_fn=stream_fn,
            )
        )

        def listener(event: AgentEvent, signal: AbortSignal) -> None:
            del signal
            if event.type in {"tool_execution_start", "tool_execution_end"}:
                snapshots.append((event.type, set(agent.state.pending_tool_calls)))

        agent.subscribe(listener)
        await agent.prompt("run")

        assert snapshots[0] == ("tool_execution_start", {"call-1"})
        assert snapshots[1] == ("tool_execution_end", set())
        assert agent.state.pending_tool_calls == set()
        assert any(
            isinstance(message, ToolResultMessage) for message in agent.state.messages
        )


if __name__ == "__main__":
    unittest.main()

