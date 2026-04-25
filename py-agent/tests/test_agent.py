"""Unit tests for high-level Agent behavior."""

from __future__ import annotations

import asyncio
import sys
import time
import unittest
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.agent import Agent, AgentOptions
from src.types import (
    AbortSignal,
    AgentEvent,
    AgentLoopConfig,
    AgentModel,
    AssistantMessage,
    AssistantMessageEvent,
    Context,
    DoneEvent,
    ImageContent,
    TextContent,
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


if __name__ == "__main__":
    unittest.main()
