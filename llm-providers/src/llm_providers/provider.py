"""Base provider interface."""

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator

from .types import AssistantMessageEvent, Message, Role, TextContent, Tool


class Provider(ABC):
    """Abstract base class for LLM providers."""

    def convert_messages(self, messages: list[Message]) -> list[dict[str, object]]:
        """Convert all internal messages to provider payload messages."""
        converted_messages: list[dict[str, object]] = []
        for message in messages:
            converted = self.convert_message(message)
            if converted is not None:
                converted_messages.append(converted)
        return converted_messages

    def convert_message(self, message: Message) -> dict[str, object] | None:
        """Convert a single message. Override for custom dispatch behavior."""
        if message.role is Role.TOOL:
            return self.convert_tool_message(message)
        return self.convert_non_tool_message(message)

    @abstractmethod
    def convert_tool_message(self, message: Message) -> dict[str, object] | None:
        """Convert a tool-result message."""
        raise NotImplementedError

    @abstractmethod
    def convert_non_tool_message(
        self,
        message: Message,
    ) -> dict[str, object] | None:
        """Convert user/assistant messages."""
        raise NotImplementedError

    @staticmethod
    def text_values(message: Message) -> list[str]:
        """Extract text content values from a message."""
        return [
            content.text
            for content in message.content
            if isinstance(content, TextContent)
        ]

    @classmethod
    def text_blocks(cls, message: Message) -> list[dict[str, str]]:
        """Build ``type=text`` blocks from message text values."""
        return [{"type": "text", "text": text} for text in cls.text_values(message)]

    @abstractmethod
    def stream(
        self,
        model: str,
        system_prompt: str,
        messages: list[Message],
        tools: list[Tool],
    ) -> AsyncIterator[AssistantMessageEvent]:
        """Stream assistant messages."""
        raise NotImplementedError

    @abstractmethod
    def check_model_access(self, model: str) -> tuple[bool, str | None]:
        """Return whether a model is reachable for this provider."""
        raise NotImplementedError
