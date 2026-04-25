"""Types for the py-agent runtime."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Literal, Protocol

type JsonPrimitive = str | int | float | bool | None
type JsonValue = JsonPrimitive | list["JsonValue"] | dict[str, "JsonValue"]
type JsonObject = dict[str, JsonValue]

type StopReason = Literal["stop", "length", "toolUse", "error", "aborted"]
type ThinkingLevel = Literal["off", "minimal", "low", "medium", "high", "xhigh"]
type ToolExecutionMode = Literal["sequential", "parallel"]
type QueueMode = Literal["one-at-a-time", "all"]


def _json_object() -> JsonObject:
    return {}


def _assistant_content_list() -> list[AssistantContent]:
    return []


def _text_image_content_list() -> list[TextContent | ImageContent]:
    return []


def _message_list() -> list[Message]:
    return []


def _agent_tool_list() -> list[AgentTool]:
    return []


def _agent_message_list() -> list[AgentMessage]:
    return []


def _tool_result_message_list() -> list[ToolResultMessage]:
    return []


def timestamp_ms() -> int:
    """Return current UTC timestamp in milliseconds."""
    return int(datetime.now(tz=UTC).timestamp() * 1000)


@dataclass(slots=True)
class TextContent:
    type: Literal["text"] = "text"
    text: str = ""
    text_signature: str | None = None


@dataclass(slots=True)
class ThinkingContent:
    type: Literal["thinking"] = "thinking"
    thinking: str = ""
    thinking_signature: str | None = None
    redacted: bool = False


@dataclass(slots=True)
class ImageContent:
    type: Literal["image"] = "image"
    data: str = ""
    mime_type: str = "image/png"


@dataclass(slots=True)
class ToolCallContent:
    type: Literal["toolCall"] = "toolCall"
    id: str = ""
    name: str = ""
    arguments: JsonObject = field(default_factory=_json_object)
    thought_signature: str | None = None
    partial_json: str | None = None


type UserContent = TextContent | ImageContent
type AssistantContent = TextContent | ThinkingContent | ToolCallContent


@dataclass(slots=True)
class UsageCost:
    input: float = 0.0
    output: float = 0.0
    cache_read: float = 0.0
    cache_write: float = 0.0
    total: float = 0.0


@dataclass(slots=True)
class Usage:
    input: int = 0
    output: int = 0
    cache_read: int = 0
    cache_write: int = 0
    total_tokens: int = 0
    cost: UsageCost = field(default_factory=UsageCost)


@dataclass(slots=True)
class UserMessage:
    role: Literal["user"] = "user"
    content: str | list[UserContent] = ""
    timestamp: int = field(default_factory=timestamp_ms)


@dataclass(slots=True)
class AssistantMessage:
    role: Literal["assistant"] = "assistant"
    content: list[AssistantContent] = field(default_factory=_assistant_content_list)
    api: str = "unknown"
    provider: str = "unknown"
    model: str = "unknown"
    response_id: str | None = None
    usage: Usage = field(default_factory=Usage)
    stop_reason: StopReason = "stop"
    error_message: str | None = None
    timestamp: int = field(default_factory=timestamp_ms)


@dataclass(slots=True)
class ToolResultMessage:
    role: Literal["toolResult"] = "toolResult"
    tool_call_id: str = ""
    tool_name: str = ""
    content: list[TextContent | ImageContent] = field(
        default_factory=_text_image_content_list
    )
    details: JsonObject | None = None
    is_error: bool = False
    timestamp: int = field(default_factory=timestamp_ms)


type Message = UserMessage | AssistantMessage | ToolResultMessage
type AgentMessage = Message
type AgentToolCall = ToolCallContent


@dataclass(slots=True)
class ToolDefinition:
    name: str
    description: str
    parameters: JsonObject


@dataclass(slots=True)
class Context:
    system_prompt: str | None = None
    messages: list[Message] = field(default_factory=_message_list)
    tools: list[ToolDefinition] | None = None


@dataclass(slots=True)
class AgentModel:
    id: str
    api: str
    provider: str
    name: str | None = None
    reasoning: bool = False


@dataclass(slots=True)
class AgentToolResult:
    content: list[TextContent | ImageContent]
    details: JsonValue = field(default_factory=_json_object)
    terminate: bool | None = None


class AgentTool(ABC):
    """Tool contract used by the runtime."""

    name: str
    label: str
    description: str
    parameters: JsonObject
    execution_mode: ToolExecutionMode | None = None

    def prepare_arguments(self, args: JsonObject) -> JsonObject:
        return args

    @abstractmethod
    async def execute(
        self,
        tool_call_id: str,
        params: JsonObject,
        signal: AbortSignal | None = None,
        on_update: Callable[[AgentToolResult], None] | None = None,
    ) -> AgentToolResult:
        raise NotImplementedError


@dataclass(slots=True)
class AgentContext:
    system_prompt: str
    messages: list[AgentMessage]
    tools: list[AgentTool] = field(default_factory=_agent_tool_list)


class AbortSignal(Protocol):
    @property
    def aborted(self) -> bool: ...


class AssistantEventStream(Protocol):
    """Streaming contract returned by provider stream functions."""

    def __aiter__(self) -> AsyncIterator[AssistantMessageEvent]: ...

    async def result(self) -> AssistantMessage: ...


@dataclass(slots=True)
class StartEvent:
    type: Literal["start"] = "start"
    partial: AssistantMessage = field(default_factory=AssistantMessage)


@dataclass(slots=True)
class TextStartEvent:
    type: Literal["text_start"] = "text_start"
    content_index: int = 0
    partial: AssistantMessage = field(default_factory=AssistantMessage)


@dataclass(slots=True)
class TextDeltaEvent:
    type: Literal["text_delta"] = "text_delta"
    content_index: int = 0
    delta: str = ""
    partial: AssistantMessage = field(default_factory=AssistantMessage)


@dataclass(slots=True)
class TextEndEvent:
    type: Literal["text_end"] = "text_end"
    content_index: int = 0
    content: str = ""
    partial: AssistantMessage = field(default_factory=AssistantMessage)


@dataclass(slots=True)
class ThinkingStartEvent:
    type: Literal["thinking_start"] = "thinking_start"
    content_index: int = 0
    partial: AssistantMessage = field(default_factory=AssistantMessage)


@dataclass(slots=True)
class ThinkingDeltaEvent:
    type: Literal["thinking_delta"] = "thinking_delta"
    content_index: int = 0
    delta: str = ""
    partial: AssistantMessage = field(default_factory=AssistantMessage)


@dataclass(slots=True)
class ThinkingEndEvent:
    type: Literal["thinking_end"] = "thinking_end"
    content_index: int = 0
    content: str = ""
    partial: AssistantMessage = field(default_factory=AssistantMessage)


@dataclass(slots=True)
class ToolCallStartEvent:
    type: Literal["toolcall_start"] = "toolcall_start"
    content_index: int = 0
    partial: AssistantMessage = field(default_factory=AssistantMessage)


@dataclass(slots=True)
class ToolCallDeltaEvent:
    type: Literal["toolcall_delta"] = "toolcall_delta"
    content_index: int = 0
    delta: str = ""
    partial: AssistantMessage = field(default_factory=AssistantMessage)


@dataclass(slots=True)
class ToolCallEndEvent:
    type: Literal["toolcall_end"] = "toolcall_end"
    content_index: int = 0
    tool_call: ToolCallContent = field(default_factory=ToolCallContent)
    partial: AssistantMessage = field(default_factory=AssistantMessage)


@dataclass(slots=True)
class DoneEvent:
    type: Literal["done"] = "done"
    reason: Literal["stop", "length", "toolUse"] = "stop"
    message: AssistantMessage = field(default_factory=AssistantMessage)


@dataclass(slots=True)
class ErrorEvent:
    type: Literal["error"] = "error"
    reason: Literal["aborted", "error"] = "error"
    error: AssistantMessage = field(default_factory=AssistantMessage)


type AssistantMessageEvent = (
    StartEvent
    | TextStartEvent
    | TextDeltaEvent
    | TextEndEvent
    | ThinkingStartEvent
    | ThinkingDeltaEvent
    | ThinkingEndEvent
    | ToolCallStartEvent
    | ToolCallDeltaEvent
    | ToolCallEndEvent
    | DoneEvent
    | ErrorEvent
)


@dataclass(slots=True)
class BeforeToolCallResult:
    block: bool = False
    reason: str | None = None


@dataclass(slots=True)
class AfterToolCallResult:
    content: list[TextContent | ImageContent] | None = None
    details: JsonValue | None = None
    is_error: bool | None = None
    terminate: bool | None = None


@dataclass(slots=True)
class BeforeToolCallContext:
    assistant_message: AssistantMessage
    tool_call: AgentToolCall
    args: JsonObject
    context: AgentContext


@dataclass(slots=True)
class AfterToolCallContext:
    assistant_message: AssistantMessage
    tool_call: AgentToolCall
    args: JsonObject
    result: AgentToolResult
    is_error: bool
    context: AgentContext


type ConvertToLlmFn = Callable[[list[AgentMessage]], Awaitable[list[Message]]]
type TransformContextFn = Callable[
    [list[AgentMessage], AbortSignal | None], Awaitable[list[AgentMessage]]
]
type ApiKeyFn = Callable[[str], Awaitable[str | None]]
type PendingMessagesFn = Callable[[], Awaitable[list[AgentMessage]]]
type BeforeToolCallFn = Callable[
    [BeforeToolCallContext, AbortSignal | None], Awaitable[BeforeToolCallResult | None]
]
type AfterToolCallFn = Callable[
    [AfterToolCallContext, AbortSignal | None], Awaitable[AfterToolCallResult | None]
]
type StreamFn = Callable[
    [AgentModel, Context, "AgentLoopConfig"], Awaitable[AssistantEventStream]
]
type AgentEventListener = Callable[["AgentEvent", AbortSignal], Awaitable[None]]


class AgentState(Protocol):
    system_prompt: str
    model: AgentModel
    thinking_level: ThinkingLevel
    is_streaming: bool
    streaming_message: AgentMessage | None
    pending_tool_calls: set[str]
    error_message: str | None

    @property
    def tools(self) -> list[AgentTool]: ...

    @tools.setter
    def tools(self, value: list[AgentTool]) -> None: ...

    @property
    def messages(self) -> list[AgentMessage]: ...

    @messages.setter
    def messages(self, value: list[AgentMessage]) -> None: ...


@dataclass(slots=True)
class AgentLoopConfig:
    model: AgentModel
    convert_to_llm: ConvertToLlmFn
    transform_context: TransformContextFn | None = None
    stream_fn: StreamFn | None = None
    get_api_key: ApiKeyFn | None = None
    get_steering_messages: PendingMessagesFn | None = None
    get_follow_up_messages: PendingMessagesFn | None = None
    tool_execution: ToolExecutionMode = "parallel"
    before_tool_call: BeforeToolCallFn | None = None
    after_tool_call: AfterToolCallFn | None = None
    api_key: str | None = None
    session_id: str | None = None
    reasoning: ThinkingLevel | None = None


@dataclass(slots=True)
class AgentEventAgentStart:
    type: Literal["agent_start"] = "agent_start"


@dataclass(slots=True)
class AgentEventAgentEnd:
    type: Literal["agent_end"] = "agent_end"
    messages: list[AgentMessage] = field(default_factory=_agent_message_list)


@dataclass(slots=True)
class AgentEventTurnStart:
    type: Literal["turn_start"] = "turn_start"


@dataclass(slots=True)
class AgentEventTurnEnd:
    type: Literal["turn_end"] = "turn_end"
    message: AgentMessage = field(default_factory=AssistantMessage)
    tool_results: list[ToolResultMessage] = field(
        default_factory=_tool_result_message_list
    )


@dataclass(slots=True)
class AgentEventMessageStart:
    type: Literal["message_start"] = "message_start"
    message: AgentMessage = field(default_factory=AssistantMessage)


@dataclass(slots=True)
class AgentEventMessageUpdate:
    type: Literal["message_update"] = "message_update"
    message: AgentMessage = field(default_factory=AssistantMessage)
    assistant_message_event: AssistantMessageEvent = field(default_factory=StartEvent)


@dataclass(slots=True)
class AgentEventMessageEnd:
    type: Literal["message_end"] = "message_end"
    message: AgentMessage = field(default_factory=AssistantMessage)


@dataclass(slots=True)
class AgentEventToolExecutionStart:
    type: Literal["tool_execution_start"] = "tool_execution_start"
    tool_call_id: str = ""
    tool_name: str = ""
    args: JsonObject = field(default_factory=_json_object)


@dataclass(slots=True)
class AgentEventToolExecutionUpdate:
    type: Literal["tool_execution_update"] = "tool_execution_update"
    tool_call_id: str = ""
    tool_name: str = ""
    args: JsonObject = field(default_factory=_json_object)
    partial_result: AgentToolResult = field(
        default_factory=lambda: AgentToolResult(content=[])
    )


@dataclass(slots=True)
class AgentEventToolExecutionEnd:
    type: Literal["tool_execution_end"] = "tool_execution_end"
    tool_call_id: str = ""
    tool_name: str = ""
    result: AgentToolResult = field(default_factory=lambda: AgentToolResult(content=[]))
    is_error: bool = False


type AgentEvent = (
    AgentEventAgentStart
    | AgentEventAgentEnd
    | AgentEventTurnStart
    | AgentEventTurnEnd
    | AgentEventMessageStart
    | AgentEventMessageUpdate
    | AgentEventMessageEnd
    | AgentEventToolExecutionStart
    | AgentEventToolExecutionUpdate
    | AgentEventToolExecutionEnd
)


async def default_convert_to_llm(messages: list[AgentMessage]) -> list[Message]:
    """Default conversion keeps only user/assistant/toolResult transcript messages."""
    return [
        message
        for message in messages
        if message.role in {"user", "assistant", "toolResult"}
    ]
