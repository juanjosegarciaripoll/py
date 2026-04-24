"""Base provider interface."""

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator

from .types import AssistantMessageEvent, Message, Tool


class Provider(ABC):
    """Abstract base class for LLM providers."""

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
