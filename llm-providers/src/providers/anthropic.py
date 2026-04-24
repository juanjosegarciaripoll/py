"""Anthropic provider implementation."""

import json
from collections.abc import AsyncIterator

import httpx

from ..provider import Provider
from ..types import (
    AssistantMessageEvent,
    Content,
    JsonObject,
    JsonValue,
    Message,
    Role,
    TextContent,
    Tool,
    Usage,
)


class AnthropicProvider(Provider):
    """Anthropic LLM provider."""

    def __init__(self, api_key: str) -> None:
        self.api_key = api_key

    def _convert_messages(self, messages: list[Message]) -> list[dict[str, object]]:
        """Convert messages to Anthropic format."""
        result: list[dict[str, object]] = []
        for msg in messages:
            if msg.role is Role.TOOL:
                # TODO: handle tool results.
                continue
            text_parts = [
                {"type": "text", "text": content.text}
                for content in msg.content
                if isinstance(content, TextContent)
            ]
            if not text_parts:
                continue
            anthropic_content: object = (
                text_parts[0]["text"] if len(text_parts) == 1 else text_parts
            )
            result.append({"role": msg.role.value, "content": anthropic_content})
        return result

    def _convert_tools(self, tools: list[Tool]) -> list[dict[str, object]]:
        """Convert tools to Anthropic format."""
        return [
            {
                "name": tool.name,
                "description": tool.description,
                "input_schema": tool.parameters,
            }
            for tool in tools
        ]

    def stream(
        self,
        model: str,
        system_prompt: str,
        messages: list[Message],
        tools: list[Tool],
    ) -> AsyncIterator[AssistantMessageEvent]:
        """Stream assistant messages from Anthropic."""
        return self._stream_impl(model, system_prompt, messages, tools)

    async def _stream_impl(
        self,
        model: str,
        system_prompt: str,
        messages: list[Message],
        tools: list[Tool],
    ) -> AsyncIterator[AssistantMessageEvent]:
        headers = {
            "x-api-key": self.api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        }
        payload: dict[str, object] = {
            "model": model,
            "system": system_prompt,
            "messages": self._convert_messages(messages),
            "max_tokens": 4096,
            "stream": True,
        }
        if tools:
            payload["tools"] = self._convert_tools(tools)

        async with (
            httpx.AsyncClient() as client,
            client.stream(
                "POST",
                "https://api.anthropic.com/v1/messages",
                headers=headers,
                json=payload,
            ) as response,
        ):
            response.raise_for_status()
            async for line in response.aiter_lines():
                if not line.startswith("data: "):
                    continue
                event = self._parse_event(line[6:])
                if event is None:
                    continue
                yield event

    def _parse_content_block_delta(
        self, payload_dict: JsonObject
    ) -> AssistantMessageEvent | None:
        delta_obj = payload_dict.get("delta")
        if not isinstance(delta_obj, dict):
            return None
        delta_type_obj = delta_obj.get("type")
        text_obj = delta_obj.get("text")
        if delta_type_obj != "text_delta" or not isinstance(text_obj, str):
            return None
        content: list[Content] = [TextContent(type="text", text=text_obj)]
        return AssistantMessageEvent(
            delta=Message(role=Role.ASSISTANT, content=content)
        )

    def _parse_message_delta(
        self, payload_dict: JsonObject
    ) -> AssistantMessageEvent | None:
        usage_obj = payload_dict.get("usage")
        if not isinstance(usage_obj, dict):
            return None
        input_tokens = usage_obj.get("input_tokens")
        output_tokens = usage_obj.get("output_tokens")
        if not isinstance(input_tokens, int) or not isinstance(output_tokens, int):
            return None
        return AssistantMessageEvent(
            usage=Usage(
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                total_tokens=input_tokens + output_tokens,
            )
        )

    def _parse_event(self, payload: str) -> AssistantMessageEvent | None:
        payload_obj: JsonValue = json.loads(payload)
        if not isinstance(payload_obj, dict):
            return None
        payload_dict: JsonObject = payload_obj

        event_type_obj = payload_dict.get("type")
        if not isinstance(event_type_obj, str):
            return None
        if event_type_obj == "content_block_delta":
            return self._parse_content_block_delta(payload_dict)
        if event_type_obj == "message_delta":
            return self._parse_message_delta(payload_dict)
        if event_type_obj == "message_stop":
            return AssistantMessageEvent(finish_reason="stop")
        return None

    def check_model_access(self, model: str) -> tuple[bool, str | None]:
        """Check model availability with a minimal non-stream request."""
        headers = {
            "x-api-key": self.api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        }
        payload: dict[str, object] = {
            "model": model,
            "max_tokens": 1,
            "messages": [{"role": "user", "content": "ping"}],
            "stream": False,
        }
        try:
            with httpx.Client() as client:
                response = client.post(
                    "https://api.anthropic.com/v1/messages",
                    headers=headers,
                    json=payload,
                )
                response.raise_for_status()
        except httpx.HTTPError as exc:
            return False, str(exc)
        return True, None
