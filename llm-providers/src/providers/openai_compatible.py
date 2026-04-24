"""OpenAI-compatible provider implementation."""

import json
import typing as t

import httpx

from ..types import (
    AssistantMessageEvent,
    Content,
    JsonObject,
    JsonValue,
    Message,
    Role,
    TextContent,
    Tool,
)
from .openai import OpenAIProvider


class OpenAICompatibleProvider(OpenAIProvider):
    """OpenAI-compatible LLM provider."""

    def __init__(self, api_key: str, base_url: str) -> None:
        super().__init__(api_key)
        self.base_url = base_url.rstrip("/")

    def stream(
        self,
        model: str,
        system_prompt: str,
        messages: list[Message],
        tools: list[Tool],
    ) -> t.AsyncIterator[AssistantMessageEvent]:
        """Stream assistant messages from an OpenAI-compatible API."""
        return self._stream_impl(model, system_prompt, messages, tools)

    async def _stream_impl(
        self,
        model: str,
        system_prompt: str,
        messages: list[Message],
        tools: list[Tool],
    ) -> t.AsyncIterator[AssistantMessageEvent]:
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "content-type": "application/json",
        }
        payload: dict[str, object] = {
            "model": model,
            "messages": [
                {"role": "system", "content": system_prompt},
                *self._convert_messages(messages),
            ],
            "max_tokens": 4096,
            "stream": True,
        }
        if tools:
            payload["tools"] = self._convert_tools(tools)

        async with (
            httpx.AsyncClient() as client,
            client.stream(
                "POST",
                f"{self.base_url}/chat/completions",
                headers=headers,
                json=payload,
            ) as response,
        ):
            response.raise_for_status()
            async for line in response.aiter_lines():
                if not line.startswith("data: ") or line == "data: [DONE]":
                    continue
                event = self._parse_event(line[6:])
                if event is None:
                    continue
                yield event

    def _parse_event(self, payload: str) -> AssistantMessageEvent | None:
        payload_obj: JsonValue = json.loads(payload)
        if not isinstance(payload_obj, dict):
            return None
        payload_dict: JsonObject = payload_obj

        choices_obj = payload_dict.get("choices")
        if not isinstance(choices_obj, list) or not choices_obj:
            return None
        first_choice = choices_obj[0]
        if not isinstance(first_choice, dict):
            return None

        delta_obj = first_choice.get("delta")
        if isinstance(delta_obj, dict):
            content_obj = delta_obj.get("content")
            if isinstance(content_obj, str) and content_obj:
                content: list[Content] = [TextContent(type="text", text=content_obj)]
                return AssistantMessageEvent(
                    delta=Message(role=Role.ASSISTANT, content=content)
                )

        finish_reason_obj = first_choice.get("finish_reason")
        if isinstance(finish_reason_obj, str) and finish_reason_obj:
            return AssistantMessageEvent(finish_reason=finish_reason_obj)

        return None
