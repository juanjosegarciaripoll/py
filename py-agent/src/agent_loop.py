"""Low-level agent loop implementation."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Awaitable, Callable, Coroutine, Mapping
from dataclasses import dataclass

from .types import (
    AbortSignal,
    AfterToolCallContext,
    AgentContext,
    AgentEvent,
    AgentEventAgentEnd,
    AgentEventAgentStart,
    AgentEventMessageEnd,
    AgentEventMessageStart,
    AgentEventMessageUpdate,
    AgentEventToolExecutionEnd,
    AgentEventToolExecutionStart,
    AgentEventToolExecutionUpdate,
    AgentEventTurnEnd,
    AgentEventTurnStart,
    AgentLoopConfig,
    AgentMessage,
    AgentTool,
    AgentToolCall,
    AgentToolResult,
    AssistantMessage,
    BeforeToolCallContext,
    Context,
    JsonValue,
    PendingMessagesFn,
    StreamFn,
    TextContent,
    ToolCallContent,
    ToolResultMessage,
    default_convert_to_llm,
)

type AgentEventSink = Callable[[AgentEvent], Awaitable[None] | None]


class AgentEventStream:
    """Async stream helper for low-level event APIs."""

    def __init__(self) -> None:
        self._queue: asyncio.Queue[AgentEvent | None] = asyncio.Queue()
        self._result_future: asyncio.Future[list[AgentMessage]] = asyncio.Future()
        self._closed = False
        self._background_tasks: set[asyncio.Task[None]] = set()

    def create_background_task(
        self,
        task_coro: Coroutine[object, object, None],
    ) -> None:
        task: asyncio.Task[None] = asyncio.create_task(task_coro)
        self._background_tasks.add(task)
        task.add_done_callback(self._background_tasks.discard)

    def push(self, event: AgentEvent) -> None:
        if self._closed:
            return
        self._queue.put_nowait(event)
        if isinstance(event, AgentEventAgentEnd):
            self._result_future.set_result(event.messages)
            self._closed = True
            self._queue.put_nowait(None)

    def end(self, result: list[AgentMessage] | None = None) -> None:
        if self._closed:
            return
        if result is not None and not self._result_future.done():
            self._result_future.set_result(result)
        self._closed = True
        self._queue.put_nowait(None)

    async def result(self) -> list[AgentMessage]:
        return await self._result_future

    async def __aiter__(self) -> AsyncIterator[AgentEvent]:
        while True:
            event = await self._queue.get()
            if event is None:
                break
            yield event


def agent_loop(
    prompts: list[AgentMessage],
    context: AgentContext,
    config: AgentLoopConfig,
    *,
    signal: AbortSignal | None = None,
    stream_fn: StreamFn | None = None,
) -> AgentEventStream:
    """Start a new loop from prompt messages."""
    stream = AgentEventStream()

    async def runner() -> None:
        messages = await run_agent_loop(
            prompts,
            context,
            config,
            stream.push,
            signal=signal,
            stream_fn=stream_fn,
        )
        stream.end(messages)

    stream.create_background_task(runner())
    return stream


def agent_loop_continue(
    context: AgentContext,
    config: AgentLoopConfig,
    *,
    signal: AbortSignal | None = None,
    stream_fn: StreamFn | None = None,
) -> AgentEventStream:
    """Continue loop from existing context."""
    if not context.messages:
        msg = "Cannot continue: no messages in context"
        raise ValueError(msg)
    if context.messages[-1].role == "assistant":
        msg = "Cannot continue from message role: assistant"
        raise ValueError(msg)

    stream = AgentEventStream()

    async def runner() -> None:
        messages = await run_agent_loop_continue(
            context,
            config,
            stream.push,
            signal=signal,
            stream_fn=stream_fn,
        )
        stream.end(messages)

    stream.create_background_task(runner())
    return stream


async def run_agent_loop(  # noqa: PLR0913
    prompts: list[AgentMessage],
    context: AgentContext,
    config: AgentLoopConfig,
    emit: AgentEventSink,
    *,
    signal: AbortSignal | None = None,
    stream_fn: StreamFn | None = None,
) -> list[AgentMessage]:
    """Run one full agent cycle from prompt messages."""
    new_messages: list[AgentMessage] = [*prompts]
    current_context = AgentContext(
        system_prompt=context.system_prompt,
        messages=[*context.messages, *prompts],
        tools=[*context.tools],
    )

    await _emit(emit, AgentEventAgentStart())
    await _emit(emit, AgentEventTurnStart())
    for prompt in prompts:
        await _emit(emit, AgentEventMessageStart(message=prompt))
        await _emit(emit, AgentEventMessageEnd(message=prompt))

    await _run_loop(
        current_context,
        new_messages,
        config,
        emit,
        signal=signal,
        stream_fn=stream_fn,
    )
    return new_messages


async def run_agent_loop_continue(
    context: AgentContext,
    config: AgentLoopConfig,
    emit: AgentEventSink,
    *,
    signal: AbortSignal | None = None,
    stream_fn: StreamFn | None = None,
) -> list[AgentMessage]:
    """Run loop continuation from existing context."""
    if not context.messages:
        msg = "Cannot continue: no messages in context"
        raise ValueError(msg)
    if context.messages[-1].role == "assistant":
        msg = "Cannot continue from message role: assistant"
        raise ValueError(msg)

    new_messages: list[AgentMessage] = []
    current_context = AgentContext(
        system_prompt=context.system_prompt,
        messages=[*context.messages],
        tools=[*context.tools],
    )
    await _emit(emit, AgentEventAgentStart())
    await _emit(emit, AgentEventTurnStart())
    await _run_loop(
        current_context,
        new_messages,
        config,
        emit,
        signal=signal,
        stream_fn=stream_fn,
    )
    return new_messages


async def _run_loop(  # noqa: PLR0913
    current_context: AgentContext,
    new_messages: list[AgentMessage],
    config: AgentLoopConfig,
    emit: AgentEventSink,
    *,
    signal: AbortSignal | None = None,
    stream_fn: StreamFn | None = None,
) -> None:
    first_turn = True
    pending_messages = await _get_messages(config.get_steering_messages)

    while True:
        has_more_tool_calls = True

        while has_more_tool_calls or pending_messages:
            if first_turn:
                first_turn = False
            else:
                await _emit(emit, AgentEventTurnStart())

            if pending_messages:
                for message in pending_messages:
                    await _emit(emit, AgentEventMessageStart(message=message))
                    await _emit(emit, AgentEventMessageEnd(message=message))
                    current_context.messages.append(message)
                    new_messages.append(message)
                pending_messages = []

            assistant_message = await _stream_assistant_response(
                current_context,
                config,
                emit,
                signal=signal,
                stream_fn=stream_fn,
            )
            new_messages.append(assistant_message)

            if assistant_message.stop_reason in {"error", "aborted"}:
                await _emit(
                    emit,
                    AgentEventTurnEnd(message=assistant_message, tool_results=[]),
                )
                await _emit(emit, AgentEventAgentEnd(messages=new_messages))
                return

            tool_calls = [
                content
                for content in assistant_message.content
                if isinstance(content, ToolCallContent)
            ]
            tool_results: list[ToolResultMessage] = []
            has_more_tool_calls = False
            if tool_calls:
                executed_batch = await _execute_tool_calls(
                    current_context,
                    assistant_message,
                    tool_calls,
                    config,
                    emit,
                    signal=signal,
                )
                tool_results.extend(executed_batch.messages)
                has_more_tool_calls = not executed_batch.terminate
                for result in tool_results:
                    current_context.messages.append(result)
                    new_messages.append(result)

            await _emit(
                emit,
                AgentEventTurnEnd(message=assistant_message, tool_results=tool_results),
            )
            pending_messages = await _get_messages(config.get_steering_messages)

        follow_ups = await _get_messages(config.get_follow_up_messages)
        if follow_ups:
            pending_messages = follow_ups
            continue
        break

    await _emit(emit, AgentEventAgentEnd(messages=new_messages))


async def _stream_assistant_response(  # noqa: C901
    context: AgentContext,
    config: AgentLoopConfig,
    emit: AgentEventSink,
    *,
    signal: AbortSignal | None = None,
    stream_fn: StreamFn | None = None,
) -> AssistantMessage:
    messages = [*context.messages]
    if config.transform_context is not None:
        messages = await config.transform_context(messages, signal)

    llm_messages = await config.convert_to_llm(messages)
    if not llm_messages:
        llm_messages = await default_convert_to_llm(messages)

    llm_context = Context(
        system_prompt=context.system_prompt,
        messages=llm_messages,
        tools=None,
    )

    call_stream_fn = stream_fn if stream_fn is not None else config.stream_fn
    if call_stream_fn is None:
        msg = "No stream function configured"
        raise ValueError(msg)
    response = await call_stream_fn(config.model, llm_context, config)

    partial_message: AssistantMessage | None = None
    added_partial = False
    async for event in response:
        match event.type:
            case "start":
                partial_message = event.partial
                context.messages.append(partial_message)
                added_partial = True
                await _emit(
                    emit,
                    AgentEventMessageStart(
                        message=_clone_assistant(partial_message),
                    ),
                )
            case (
                "text_start"
                | "text_delta"
                | "text_end"
                | "thinking_start"
                | "thinking_delta"
                | "thinking_end"
                | "toolcall_start"
                | "toolcall_delta"
                | "toolcall_end"
            ):
                if partial_message is None:
                    continue
                partial_message = event.partial
                context.messages[-1] = partial_message
                await _emit(
                    emit,
                    AgentEventMessageUpdate(
                        message=_clone_assistant(partial_message),
                        assistant_message_event=event,
                    ),
                )
            case "done" | "error":
                final_message = await response.result()
                if added_partial:
                    context.messages[-1] = final_message
                else:
                    context.messages.append(final_message)
                    await _emit(
                        emit,
                        AgentEventMessageStart(
                            message=_clone_assistant(final_message),
                        ),
                    )
                await _emit(emit, AgentEventMessageEnd(message=final_message))
                return final_message

    final_message = await response.result()
    if added_partial:
        context.messages[-1] = final_message
    else:
        context.messages.append(final_message)
        await _emit(
            emit,
            AgentEventMessageStart(message=_clone_assistant(final_message)),
        )
    await _emit(emit, AgentEventMessageEnd(message=final_message))
    return final_message


@dataclass(slots=True)
class _PreparedToolCall:
    tool_call: AgentToolCall
    tool: AgentTool
    args: dict[str, JsonValue]


@dataclass(slots=True)
class _ImmediateToolCallOutcome:
    result: AgentToolResult
    is_error: bool


@dataclass(slots=True)
class _FinalizedToolCallOutcome:
    tool_call: AgentToolCall
    result: AgentToolResult
    is_error: bool


@dataclass(slots=True)
class _ExecutedToolCallBatch:
    messages: list[ToolResultMessage]
    terminate: bool


def _should_terminate_batch(finalized: list[_FinalizedToolCallOutcome]) -> bool:
    return bool(finalized) and all(item.result.terminate is True for item in finalized)


async def _execute_tool_calls(  # noqa: PLR0913
    context: AgentContext,
    assistant_message: AssistantMessage,
    tool_calls: list[AgentToolCall],
    config: AgentLoopConfig,
    emit: AgentEventSink,
    *,
    signal: AbortSignal | None = None,
) -> _ExecutedToolCallBatch:
    has_sequential_tool = False
    for tool_call in tool_calls:
        tool = _find_tool(context.tools, tool_call.name)
        if tool is not None and tool.execution_mode == "sequential":
            has_sequential_tool = True
            break
    if config.tool_execution == "sequential" or has_sequential_tool:
        return await _execute_tool_calls_sequential(
            context, assistant_message, tool_calls, config, emit, signal=signal
        )
    return await _execute_tool_calls_parallel(
        context, assistant_message, tool_calls, config, emit, signal=signal
    )


async def _execute_tool_calls_sequential(  # noqa: PLR0913
    context: AgentContext,
    assistant_message: AssistantMessage,
    tool_calls: list[AgentToolCall],
    config: AgentLoopConfig,
    emit: AgentEventSink,
    *,
    signal: AbortSignal | None = None,
) -> _ExecutedToolCallBatch:
    finalized_calls: list[_FinalizedToolCallOutcome] = []
    messages: list[ToolResultMessage] = []
    for tool_call in tool_calls:
        await _emit(
            emit,
            AgentEventToolExecutionStart(
                tool_call_id=tool_call.id,
                tool_name=tool_call.name,
                args=tool_call.arguments,
            ),
        )
        prepared = await _prepare_tool_call(
            context, assistant_message, tool_call, config, signal=signal
        )
        if isinstance(prepared, _ImmediateToolCallOutcome):
            finalized = _FinalizedToolCallOutcome(
                tool_call=tool_call,
                result=prepared.result,
                is_error=prepared.is_error,
            )
        else:
            executed = await _execute_prepared_tool_call(prepared, emit, signal=signal)
            finalized = await _finalize_tool_call(
                context, assistant_message, prepared, executed, config, signal=signal
            )
        await _emit_tool_execution_end(finalized, emit)
        tool_result = _create_tool_result_message(finalized)
        await _emit_tool_result_message(tool_result, emit)
        finalized_calls.append(finalized)
        messages.append(tool_result)
    return _ExecutedToolCallBatch(
        messages=messages, terminate=_should_terminate_batch(finalized_calls)
    )


async def _execute_tool_calls_parallel(  # noqa: PLR0913
    context: AgentContext,
    assistant_message: AssistantMessage,
    tool_calls: list[AgentToolCall],
    config: AgentLoopConfig,
    emit: AgentEventSink,
    *,
    signal: AbortSignal | None = None,
) -> _ExecutedToolCallBatch:
    finalized_by_order: list[_FinalizedToolCallOutcome | None] = [
        None
    ] * len(tool_calls)
    tasks: list[asyncio.Task[tuple[int, _FinalizedToolCallOutcome]]] = []

    for index, tool_call in enumerate(tool_calls):
        await _emit(
            emit,
            AgentEventToolExecutionStart(
                tool_call_id=tool_call.id,
                tool_name=tool_call.name,
                args=tool_call.arguments,
            ),
        )
        prepared = await _prepare_tool_call(
            context, assistant_message, tool_call, config, signal=signal
        )
        if isinstance(prepared, _ImmediateToolCallOutcome):
            finalized_outcome = _FinalizedToolCallOutcome(
                tool_call=tool_call,
                result=prepared.result,
                is_error=prepared.is_error,
            )
            await _emit_tool_execution_end(finalized_outcome, emit)
            finalized_by_order[index] = finalized_outcome
            continue

        async def run_prepared(
            task_index: int, task_prepared: _PreparedToolCall
        ) -> tuple[int, _FinalizedToolCallOutcome]:
            executed = await _execute_prepared_tool_call(
                task_prepared,
                emit,
                signal=signal,
            )
            finalized_outcome = await _finalize_tool_call(
                context,
                assistant_message,
                task_prepared,
                executed,
                config,
                signal=signal,
            )
            await _emit_tool_execution_end(finalized_outcome, emit)
            return task_index, finalized_outcome

        tasks.append(asyncio.create_task(run_prepared(index, prepared)))

    for task in asyncio.as_completed(tasks):
        task_index, finalized_outcome = await task
        finalized_by_order[task_index] = finalized_outcome

    finalized_calls: list[_FinalizedToolCallOutcome] = [
        item for item in finalized_by_order if item is not None
    ]
    messages: list[ToolResultMessage] = []
    for item in finalized_calls:
        tool_result = _create_tool_result_message(item)
        await _emit_tool_result_message(tool_result, emit)
        messages.append(tool_result)
    return _ExecutedToolCallBatch(
        messages=messages, terminate=_should_terminate_batch(finalized_calls)
    )


def _find_tool(tools: list[AgentTool], name: str) -> AgentTool | None:
    for tool in tools:
        if tool.name == name:
            return tool
    return None


def _validate_tool_arguments(
    parameters: Mapping[str, JsonValue],
    args: Mapping[str, JsonValue],
) -> None:
    required = parameters.get("required")
    if isinstance(required, list):
        for value in required:
            if isinstance(value, str) and value not in args:
                msg = f"Missing required argument: {value}"
                raise ValueError(msg)


async def _prepare_tool_call(
    context: AgentContext,
    assistant_message: AssistantMessage,
    tool_call: AgentToolCall,
    config: AgentLoopConfig,
    *,
    signal: AbortSignal | None = None,
) -> _PreparedToolCall | _ImmediateToolCallOutcome:
    tool = _find_tool(context.tools, tool_call.name)
    if tool is None:
        return _ImmediateToolCallOutcome(
            result=_error_tool_result(f"Tool {tool_call.name} not found"),
            is_error=True,
        )

    try:
        prepared_raw = tool.prepare_arguments(tool_call.arguments)
        _validate_tool_arguments(tool.parameters, prepared_raw)
        if config.before_tool_call is not None:
            before_result = await config.before_tool_call(
                BeforeToolCallContext(
                    assistant_message=assistant_message,
                    tool_call=tool_call,
                    args=prepared_raw,
                    context=context,
                ),
                signal,
            )
            if before_result is not None and before_result.block:
                return _ImmediateToolCallOutcome(
                    result=_error_tool_result(
                        before_result.reason or "Tool execution was blocked"
                    ),
                    is_error=True,
                )
        return _PreparedToolCall(
            tool_call=tool_call,
            tool=tool,
            args=prepared_raw,
        )
    except Exception as error:  # noqa: BLE001
        return _ImmediateToolCallOutcome(
            result=_error_tool_result(str(error)),
            is_error=True,
        )


async def _execute_prepared_tool_call(
    prepared: _PreparedToolCall,
    emit: AgentEventSink,
    *,
    signal: AbortSignal | None = None,
) -> _ImmediateToolCallOutcome:
    try:
        updates: list[asyncio.Task[None]] = []

        def on_update(partial: AgentToolResult) -> None:
            updates.append(
                asyncio.create_task(
                    _emit(
                        emit,
                        AgentEventToolExecutionUpdate(
                            tool_call_id=prepared.tool_call.id,
                            tool_name=prepared.tool_call.name,
                            args=prepared.tool_call.arguments,
                            partial_result=partial,
                        ),
                    )
                )
            )

        result = await prepared.tool.execute(
            prepared.tool_call.id,
            prepared.args,
            signal=signal,
            on_update=on_update,
        )
        if updates:
            await asyncio.gather(*updates)
        return _ImmediateToolCallOutcome(result=result, is_error=False)
    except Exception as error:  # noqa: BLE001
        return _ImmediateToolCallOutcome(
            result=_error_tool_result(str(error)),
            is_error=True,
        )


async def _finalize_tool_call(  # noqa: PLR0913
    context: AgentContext,
    assistant_message: AssistantMessage,
    prepared: _PreparedToolCall,
    executed: _ImmediateToolCallOutcome,
    config: AgentLoopConfig,
    *,
    signal: AbortSignal | None = None,
) -> _FinalizedToolCallOutcome:
    result = executed.result
    is_error = executed.is_error
    if config.after_tool_call is not None:
        try:
            after_result = await config.after_tool_call(
                AfterToolCallContext(
                    assistant_message=assistant_message,
                    tool_call=prepared.tool_call,
                    args=prepared.args,
                    result=result,
                    is_error=is_error,
                    context=context,
                ),
                signal,
            )
            if after_result is not None:
                if after_result.content is not None:
                    result.content = after_result.content
                if after_result.details is not None:
                    result.details = after_result.details
                if after_result.terminate is not None:
                    result.terminate = after_result.terminate
                if after_result.is_error is not None:
                    is_error = after_result.is_error
        except Exception as error:  # noqa: BLE001
            result = _error_tool_result(str(error))
            is_error = True
    return _FinalizedToolCallOutcome(
        tool_call=prepared.tool_call,
        result=result,
        is_error=is_error,
    )


def _error_tool_result(message: str) -> AgentToolResult:
    return AgentToolResult(content=[TextContent(text=message)], details={})


def _create_tool_result_message(
    finalized: _FinalizedToolCallOutcome,
) -> ToolResultMessage:
    details_obj: dict[str, JsonValue] | None
    if isinstance(finalized.result.details, dict):
        details_obj = finalized.result.details
    else:
        details_obj = {"value": str(finalized.result.details)}
    return ToolResultMessage(
        tool_call_id=finalized.tool_call.id,
        tool_name=finalized.tool_call.name,
        content=finalized.result.content,
        details=details_obj,
        is_error=finalized.is_error,
    )


async def _emit_tool_result_message(
    tool_result_message: ToolResultMessage,
    emit: AgentEventSink,
) -> None:
    await _emit(emit, AgentEventMessageStart(message=tool_result_message))
    await _emit(emit, AgentEventMessageEnd(message=tool_result_message))


async def _emit_tool_execution_end(
    finalized: _FinalizedToolCallOutcome,
    emit: AgentEventSink,
) -> None:
    await _emit(
        emit,
        AgentEventToolExecutionEnd(
            tool_call_id=finalized.tool_call.id,
            tool_name=finalized.tool_call.name,
            result=finalized.result,
            is_error=finalized.is_error,
        ),
    )


async def _get_messages(fn: PendingMessagesFn | None) -> list[AgentMessage]:
    if fn is None:
        return []
    result = await fn()
    return [*result]


def _clone_assistant(message: AssistantMessage) -> AssistantMessage:
    return AssistantMessage(
        content=[*message.content],
        api=message.api,
        provider=message.provider,
        model=message.model,
        response_id=message.response_id,
        usage=message.usage,
        stop_reason=message.stop_reason,
        error_message=message.error_message,
        timestamp=message.timestamp,
    )


async def _emit(emit: AgentEventSink, event: AgentEvent) -> None:
    value = emit(event)
    if asyncio.iscoroutine(value):
        await value
