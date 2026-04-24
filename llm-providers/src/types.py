"""Type definitions for LLM providers."""

from dataclasses import dataclass
from enum import StrEnum
from typing import Literal

type JsonPrimitive = str | int | float | bool | None
type JsonValue = JsonPrimitive | list["JsonValue"] | dict[str, "JsonValue"]
type JsonObject = dict[str, JsonValue]


class Role(StrEnum):
    USER = "user"
    ASSISTANT = "assistant"
    TOOL = "tool"


@dataclass
class TextContent:
    type: Literal["text"]
    text: str


@dataclass
class ImageContent:
    type: Literal["image"]
    image_url: dict[str, str]


Content = TextContent | ImageContent


@dataclass
class ToolCall:
    id: str
    function: dict[str, str]


@dataclass
class Message:
    role: Role
    content: list[Content]
    tool_calls: list[ToolCall] | None = None
    tool_call_id: str | None = None


@dataclass
class Tool:
    name: str
    description: str
    parameters: dict[str, object]


@dataclass
class Usage:
    input_tokens: int
    output_tokens: int
    total_tokens: int


@dataclass
class AssistantMessageEvent:
    delta: Message | None = None
    usage: Usage | None = None
    finish_reason: str | None = None


AssistantMessage = Message  # alias
