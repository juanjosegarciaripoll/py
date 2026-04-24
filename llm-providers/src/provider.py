"""Base provider interface."""

import typing as t
from abc import ABC, abstractmethod

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
    ) -> t.AsyncIterator[AssistantMessageEvent]:
        """Stream assistant messages."""
        raise NotImplementedError
