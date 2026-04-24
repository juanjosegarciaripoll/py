"""OpenAI provider implementation."""

import json
import typing as t

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


class OpenAIProvider(Provider):
    """OpenAI LLM provider."""

    def __init__(self, api_key: str) -> None:
        self.api_key = api_key

    def _convert_messages(self, messages: list[Message]) -> list[dict[str, object]]:
        """Convert messages to OpenAI format."""
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
            openai_content: object = (
                text_parts[0]["text"] if len(text_parts) == 1 else text_parts
            )
            result.append({"role": msg.role.value, "content": openai_content})
        return result

    def _convert_tools(self, tools: list[Tool]) -> list[dict[str, object]]:
        """Convert tools to OpenAI format."""
        return [
            {
                "type": "function",
                "function": {
                    "name": tool.name,
                    "description": tool.description,
                    "parameters": tool.parameters,
                },
            }
            for tool in tools
        ]

    def stream(
        self,
        model: str,
        system_prompt: str,
        messages: list[Message],
        tools: list[Tool],
    ) -> t.AsyncIterator[AssistantMessageEvent]:
        """Stream assistant messages from OpenAI."""
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

        async with httpx.AsyncClient() as client, client.stream(
            "POST",
            "https://api.openai.com/v1/chat/completions",
            headers=headers,
            json=payload,
        ) as response:
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
            return self._parse_usage(payload_dict)
        first_choice = choices_obj[0]
        if not isinstance(first_choice, dict):
            return self._parse_usage(payload_dict)

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

        return self._parse_usage(payload_dict)

    def _parse_usage(self, payload_obj: JsonObject) -> AssistantMessageEvent | None:
        usage_obj = payload_obj.get("usage")
        if not isinstance(usage_obj, dict):
            return None
        prompt_tokens = usage_obj.get("prompt_tokens")
        completion_tokens = usage_obj.get("completion_tokens")
        total_tokens = usage_obj.get("total_tokens")
        if (
            isinstance(prompt_tokens, int)
            and isinstance(completion_tokens, int)
            and isinstance(total_tokens, int)
        ):
            return AssistantMessageEvent(
                usage=Usage(
                    input_tokens=prompt_tokens,
                    output_tokens=completion_tokens,
                    total_tokens=total_tokens,
                )
            )
        return None
