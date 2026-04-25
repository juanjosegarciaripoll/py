"""High-level stateful Agent wrapper."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable  # noqa: TC003
from dataclasses import dataclass, field

from .agent_loop import run_agent_loop, run_agent_loop_continue
from .types import (
    AfterToolCallFn,
    AgentContext,
    AgentEvent,
    AgentEventAgentEnd,
    AgentEventMessageEnd,
    AgentEventMessageStart,
    AgentEventMessageUpdate,
    AgentEventToolExecutionEnd,
    AgentEventToolExecutionStart,
    AgentEventTurnEnd,
    AgentLoopConfig,
    AgentMessage,
    AgentModel,
    AgentState,
    AgentTool,
    ApiKeyFn,
    AssistantMessage,
    BeforeToolCallFn,
    ConvertToLlmFn,
    ImageContent,
    QueueMode,
    StreamFn,
    TextContent,
    ThinkingLevel,
    ToolExecutionMode,
    TransformContextFn,
    UserMessage,
    default_convert_to_llm,
)


class _SimpleAbortSignal:
    def __init__(self) -> None:
        self._aborted = False

    @property
    def aborted(self) -> bool:
        return self._aborted

    def abort(self) -> None:
        self._aborted = True


class _SimpleAbortController:
    def __init__(self) -> None:
        self.signal = _SimpleAbortSignal()

    def abort(self) -> None:
        self.signal.abort()


def _agent_tools_list() -> list[AgentTool]:
    return []


def _agent_messages_list() -> list[AgentMessage]:
    return []


@dataclass(slots=True)
class AgentOptions:
    initial_system_prompt: str = ""
    initial_model: AgentModel | None = None
    initial_thinking_level: ThinkingLevel = "off"
    initial_tools: list[AgentTool] = field(default_factory=_agent_tools_list)
    initial_messages: list[AgentMessage] = field(default_factory=_agent_messages_list)
    convert_to_llm: ConvertToLlmFn = default_convert_to_llm
    transform_context: TransformContextFn | None = None
    stream_fn: StreamFn | None = None
    get_api_key: ApiKeyFn | None = None
    before_tool_call: BeforeToolCallFn | None = None
    after_tool_call: AfterToolCallFn | None = None
    steering_mode: QueueMode = "one-at-a-time"
    follow_up_mode: QueueMode = "one-at-a-time"
    session_id: str | None = None
    tool_execution: ToolExecutionMode = "parallel"


class _PendingMessageQueue:
    def __init__(self, mode: QueueMode) -> None:
        self._mode: QueueMode = mode
        self._messages: list[AgentMessage] = []

    @property
    def mode(self) -> QueueMode:
        return self._mode

    @mode.setter
    def mode(self, value: QueueMode) -> None:
        self._mode = value

    def enqueue(self, message: AgentMessage) -> None:
        self._messages.append(message)

    def has_items(self) -> bool:
        return bool(self._messages)

    def drain(self) -> list[AgentMessage]:
        if not self._messages:
            return []
        if self._mode == "all":
            drained = [*self._messages]
            self._messages.clear()
            return drained
        return [self._messages.pop(0)]

    def clear(self) -> None:
        self._messages.clear()


class _MutableAgentState:
    def __init__(
        self,
        *,
        system_prompt: str,
        model: AgentModel,
        thinking_level: ThinkingLevel,
        tools: list[AgentTool],
        messages: list[AgentMessage],
    ) -> None:
        self.system_prompt = system_prompt
        self.model = model
        self.thinking_level: ThinkingLevel = thinking_level
        self._tools = [*tools]
        self._messages = [*messages]
        self.is_streaming = False
        self.streaming_message: AgentMessage | None = None
        self.pending_tool_calls: set[str] = set()
        self.error_message: str | None = None

    @property
    def tools(self) -> list[AgentTool]:
        return self._tools

    @tools.setter
    def tools(self, value: list[AgentTool]) -> None:
        self._tools = [*value]

    @property
    def messages(self) -> list[AgentMessage]:
        return self._messages

    @messages.setter
    def messages(self, value: list[AgentMessage]) -> None:
        self._messages = [*value]


@dataclass(slots=True)
class _ActiveRun:
    completion: asyncio.Future[None]
    abort_controller: _SimpleAbortController


class Agent:
    """Stateful wrapper around low-level loop primitives."""

    def __init__(self, options: AgentOptions | None = None) -> None:
        opts = options or AgentOptions()
        model = opts.initial_model or AgentModel(
            id="unknown",
            api="unknown",
            provider="unknown",
            name="unknown",
        )
        self._state = _MutableAgentState(
            system_prompt=opts.initial_system_prompt,
            model=model,
            thinking_level=opts.initial_thinking_level,
            tools=opts.initial_tools,
            messages=opts.initial_messages,
        )
        self.convert_to_llm: ConvertToLlmFn = opts.convert_to_llm
        self.transform_context: TransformContextFn | None = opts.transform_context
        self.stream_fn: StreamFn | None = opts.stream_fn
        self.get_api_key: ApiKeyFn | None = opts.get_api_key
        self.before_tool_call: BeforeToolCallFn | None = opts.before_tool_call
        self.after_tool_call: AfterToolCallFn | None = opts.after_tool_call
        self.session_id: str | None = opts.session_id
        self.tool_execution: ToolExecutionMode = opts.tool_execution
        self._steering_queue = _PendingMessageQueue(opts.steering_mode)
        self._follow_up_queue = _PendingMessageQueue(opts.follow_up_mode)
        self._listeners: list[
            Callable[[AgentEvent, _SimpleAbortSignal], Awaitable[None] | None]
        ] = []
        self._active_run: _ActiveRun | None = None

    @property
    def state(self) -> AgentState:
        return self._state

    @property
    def steering_mode(self) -> QueueMode:
        return self._steering_queue.mode

    @steering_mode.setter
    def steering_mode(self, value: QueueMode) -> None:
        self._steering_queue.mode = value

    @property
    def follow_up_mode(self) -> QueueMode:
        return self._follow_up_queue.mode

    @follow_up_mode.setter
    def follow_up_mode(self, value: QueueMode) -> None:
        self._follow_up_queue.mode = value

    def subscribe(
        self,
        listener: Callable[[AgentEvent, _SimpleAbortSignal], Awaitable[None] | None],
    ) -> Callable[[], None]:
        self._listeners.append(listener)

        def unsubscribe() -> None:
            if listener in self._listeners:
                self._listeners.remove(listener)

        return unsubscribe

    def steer(self, message: AgentMessage) -> None:
        self._steering_queue.enqueue(message)

    def follow_up(self, message: AgentMessage) -> None:
        self._follow_up_queue.enqueue(message)

    def clear_steering_queue(self) -> None:
        self._steering_queue.clear()

    def clear_follow_up_queue(self) -> None:
        self._follow_up_queue.clear()

    def clear_all_queues(self) -> None:
        self.clear_steering_queue()
        self.clear_follow_up_queue()

    def has_queued_messages(self) -> bool:
        return self._steering_queue.has_items() or self._follow_up_queue.has_items()

    @property
    def signal(self) -> _SimpleAbortSignal | None:
        if self._active_run is None:
            return None
        return self._active_run.abort_controller.signal

    def abort(self) -> None:
        if self._active_run is not None:
            self._active_run.abort_controller.abort()

    async def wait_for_idle(self) -> None:
        if self._active_run is not None:
            await self._active_run.completion

    def reset(self) -> None:
        self._state.messages = []
        self._state.is_streaming = False
        self._state.streaming_message = None
        self._state.pending_tool_calls = set()
        self._state.error_message = None
        self.clear_all_queues()

    async def prompt(
        self,
        input_value: str | AgentMessage | list[AgentMessage],
        images: list[ImageContent] | None = None,
    ) -> None:
        if self._active_run is not None:
            msg = "Agent is already processing a prompt."
            raise RuntimeError(msg)
        messages = self._normalize_prompt_input(input_value, images)
        await self._run_prompt_messages(messages, skip_initial_steering_poll=False)

    async def continue_(self) -> None:
        if self._active_run is not None:
            msg = "Agent is already processing."
            raise RuntimeError(msg)
        if not self._state.messages:
            msg = "No messages to continue from"
            raise ValueError(msg)

        last = self._state.messages[-1]
        if last.role == "assistant":
            queued_steering = self._steering_queue.drain()
            if queued_steering:
                await self._run_prompt_messages(
                    queued_steering,
                    skip_initial_steering_poll=True,
                )
                return
            queued_follow_ups = self._follow_up_queue.drain()
            if queued_follow_ups:
                await self._run_prompt_messages(queued_follow_ups)
                return
            msg = "Cannot continue from message role: assistant"
            raise ValueError(msg)

        await self._run_continuation()

    async def continue_run(self) -> None:
        """Alias to keep a non-keyword method name."""
        await self.continue_()

    def _normalize_prompt_input(
        self,
        input_value: str | AgentMessage | list[AgentMessage],
        images: list[ImageContent] | None,
    ) -> list[AgentMessage]:
        if isinstance(input_value, list):
            return [*input_value]
        if isinstance(input_value, str):
            content: list[TextContent | ImageContent] = [TextContent(text=input_value)]
            if images:
                content.extend(images)
            return [UserMessage(content=content)]
        return [input_value]

    async def _run_prompt_messages(
        self,
        messages: list[AgentMessage],
        *,
        skip_initial_steering_poll: bool = False,
    ) -> None:
        async def executor(signal: _SimpleAbortSignal) -> None:
            await run_agent_loop(
                messages,
                self._create_context_snapshot(),
                self._create_loop_config(
                    skip_initial_steering_poll=skip_initial_steering_poll,
                ),
                self._process_event,
                signal=signal,
                stream_fn=self.stream_fn,
            )

        await self._run_with_lifecycle(executor)

    async def _run_continuation(self) -> None:
        async def executor(signal: _SimpleAbortSignal) -> None:
            await run_agent_loop_continue(
                self._create_context_snapshot(),
                self._create_loop_config(),
                self._process_event,
                signal=signal,
                stream_fn=self.stream_fn,
            )

        await self._run_with_lifecycle(executor)

    def _create_context_snapshot(self) -> AgentContext:
        return AgentContext(
            system_prompt=self._state.system_prompt,
            messages=[*self._state.messages],
            tools=[*self._state.tools],
        )

    def _create_loop_config(
        self, *, skip_initial_steering_poll: bool = False
    ) -> AgentLoopConfig:
        skip_first = skip_initial_steering_poll

        async def get_steering_messages() -> list[AgentMessage]:
            nonlocal skip_first
            if skip_first:
                skip_first = False
                return []
            return self._steering_queue.drain()

        async def get_follow_up_messages() -> list[AgentMessage]:
            return self._follow_up_queue.drain()

        return AgentLoopConfig(
            model=self._state.model,
            convert_to_llm=self.convert_to_llm,
            transform_context=self.transform_context,
            stream_fn=self.stream_fn,
            get_api_key=self.get_api_key,
            get_steering_messages=get_steering_messages,
            get_follow_up_messages=get_follow_up_messages,
            tool_execution=self.tool_execution,
            before_tool_call=self.before_tool_call,
            after_tool_call=self.after_tool_call,
            session_id=self.session_id,
            reasoning=(
                None
                if self._state.thinking_level == "off"
                else self._state.thinking_level
            ),
        )

    async def _run_with_lifecycle(
        self,
        executor: Callable[[_SimpleAbortSignal], Awaitable[None]],
    ) -> None:
        if self._active_run is not None:
            msg = "Agent is already processing."
            raise RuntimeError(msg)

        loop = asyncio.get_running_loop()
        completion: asyncio.Future[None] = loop.create_future()
        abort_controller = _SimpleAbortController()
        self._active_run = _ActiveRun(
            completion=completion,
            abort_controller=abort_controller,
        )
        self._state.is_streaming = True
        self._state.streaming_message = None
        self._state.error_message = None

        try:
            await executor(abort_controller.signal)
        except Exception as error:  # noqa: BLE001
            failure = AssistantMessage(
                content=[TextContent(text="")],
                api=self._state.model.api,
                provider=self._state.model.provider,
                model=self._state.model.id,
                stop_reason="aborted" if abort_controller.signal.aborted else "error",
                error_message=str(error),
            )
            self._state.messages.append(failure)
            self._state.error_message = failure.error_message
            await self._process_event(AgentEventAgentEnd(messages=[failure]))
        finally:
            self._state.is_streaming = False
            self._state.streaming_message = None
            self._state.pending_tool_calls = set()
            if not completion.done():
                completion.set_result(None)
            self._active_run = None

    async def _process_event(self, event: AgentEvent) -> None:
        if isinstance(event, AgentEventMessageStart | AgentEventMessageUpdate):
            self._state.streaming_message = event.message
        if isinstance(event, AgentEventMessageEnd):
            self._state.streaming_message = None
            self._state.messages.append(event.message)
        if isinstance(event, AgentEventToolExecutionStart):
            pending = set(self._state.pending_tool_calls)
            pending.add(event.tool_call_id)
            self._state.pending_tool_calls = pending
        if isinstance(event, AgentEventToolExecutionEnd):
            pending = set(self._state.pending_tool_calls)
            pending.discard(event.tool_call_id)
            self._state.pending_tool_calls = pending
        if (
            isinstance(event, AgentEventTurnEnd)
            and isinstance(event.message, AssistantMessage)
            and event.message.error_message
        ):
            self._state.error_message = event.message.error_message
        if isinstance(event, AgentEventAgentEnd):
            self._state.streaming_message = None

        signal = self.signal
        if signal is None:
            return
        for listener in [*self._listeners]:
            result = listener(event, signal)
            if asyncio.iscoroutine(result):
                await result
