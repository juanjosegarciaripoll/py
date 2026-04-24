"""Anthropic provider implementation."""

import json
from collections.abc import AsyncIterator

import httpx

from ..communication import parse_streaming_json
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
    ToolCall,
    Usage,
)


class AnthropicProvider(Provider):
    """Anthropic LLM provider."""

    def __init__(self, api_key: str) -> None:
        self.api_key = api_key

    def convert_tool_message(self, message: Message) -> dict[str, object] | None:
        if not message.tool_call_id:
            return None
        return {
            "role": "user",
            "content": [
                {
                    "type": "tool_result",
                    "tool_use_id": message.tool_call_id,
                    "content": self.text_blocks(message),
                }
            ],
        }

    def convert_non_tool_message(
        self,
        message: Message,
    ) -> dict[str, object] | None:
        blocks: list[dict[str, object]] = [
            {"type": item["type"], "text": item["text"]}
            for item in self.text_blocks(message)
        ]
        if message.tool_calls:
            for tool_call in message.tool_calls:
                arguments_raw = tool_call.function.get("arguments", "{}")
                arguments_obj = parse_streaming_json(arguments_raw)
                blocks.append(
                    {
                        "type": "tool_use",
                        "id": tool_call.id,
                        "name": tool_call.function.get("name", ""),
                        "input": arguments_obj,
                    }
                )
        if not blocks:
            return None
        anthropic_content: object = (
            blocks[0]["text"]
            if len(blocks) == 1 and blocks[0]["type"] == "text"
            else blocks
        )
        return {"role": message.role.value, "content": anthropic_content}

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
            "messages": self.convert_messages(messages),
            "max_tokens": 4096,
            "stream": True,
        }
        if tools:
            payload["tools"] = self._convert_tools(tools)

        partial_tool_calls: dict[int, ToolCall] = {}
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
                for event in self._parse_event(line[6:], partial_tool_calls):
                    yield event

    def _parse_content_block_delta(
        self,
        payload_dict: JsonObject,
        partial_tool_calls: dict[int, ToolCall],
    ) -> list[AssistantMessageEvent]:
        events: list[AssistantMessageEvent] = []
        index_obj = payload_dict.get("index")
        index = index_obj if isinstance(index_obj, int) else None
        delta_obj = payload_dict.get("delta")
        if not isinstance(delta_obj, dict):
            return events
        delta_type_obj = delta_obj.get("type")
        text_obj = delta_obj.get("text")
        if delta_type_obj == "text_delta" and isinstance(text_obj, str):
            content: list[Content] = [TextContent(type="text", text=text_obj)]
            events.append(
                AssistantMessageEvent(
                    delta=Message(role=Role.ASSISTANT, content=content)
                )
            )
            return events
        partial_json_obj = delta_obj.get("partial_json")
        if (
            delta_type_obj == "input_json_delta"
            and isinstance(partial_json_obj, str)
            and index is not None
        ):
            partial = partial_tool_calls.get(
                index,
                ToolCall(id="", function={"name": "", "arguments": ""}),
            )
            partial.function["arguments"] = (
                partial.function.get("arguments", "") + partial_json_obj
            )
            partial_tool_calls[index] = partial
            events.append(
                AssistantMessageEvent(
                    delta=Message(
                        role=Role.ASSISTANT,
                        content=[],
                        tool_calls=[
                            ToolCall(
                                id=partial.id,
                                function={
                                    "name": partial.function.get("name", ""),
                                    "arguments": partial.function.get("arguments", ""),
                                },
                            )
                        ],
                    )
                )
            )
        return events

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

    def _parse_content_block_start(
        self,
        payload_dict: JsonObject,
        partial_tool_calls: dict[int, ToolCall],
    ) -> list[AssistantMessageEvent]:
        events: list[AssistantMessageEvent] = []
        index_obj = payload_dict.get("index")
        if not isinstance(index_obj, int):
            return events
        content_block_obj = payload_dict.get("content_block")
        if not isinstance(content_block_obj, dict):
            return events
        block_type_obj = content_block_obj.get("type")
        if block_type_obj != "tool_use":
            return events
        tool_use_id = content_block_obj.get("id")
        tool_name = content_block_obj.get("name")
        input_obj = content_block_obj.get("input")
        if (
            not isinstance(tool_use_id, str)
            or not isinstance(tool_name, str)
            or not isinstance(input_obj, dict)
        ):
            return events
        partial = ToolCall(
            id=tool_use_id,
            function={
                "name": tool_name,
                "arguments": (
                    json.dumps(input_obj, separators=(",", ":")) if input_obj else ""
                ),
            },
        )
        partial_tool_calls[index_obj] = partial
        events.append(
            AssistantMessageEvent(
                delta=Message(
                    role=Role.ASSISTANT,
                    content=[],
                    tool_calls=[
                        ToolCall(
                            id=partial.id,
                            function={
                                "name": partial.function.get("name", ""),
                                "arguments": partial.function.get("arguments", ""),
                            },
                        )
                    ],
                )
            )
        )
        return events

    def _parse_content_block_stop(
        self,
        payload_dict: JsonObject,
        partial_tool_calls: dict[int, ToolCall],
    ) -> list[AssistantMessageEvent]:
        index_obj = payload_dict.get("index")
        if not isinstance(index_obj, int):
            return []
        partial = partial_tool_calls.get(index_obj)
        if partial is None:
            return []
        parsed_arguments = parse_streaming_json(partial.function.get("arguments", ""))
        partial.function["arguments"] = json.dumps(
            parsed_arguments,
            separators=(",", ":"),
        )
        partial_tool_calls[index_obj] = partial
        return [
            AssistantMessageEvent(
                delta=Message(
                    role=Role.ASSISTANT,
                    content=[],
                    tool_calls=[
                        ToolCall(
                            id=partial.id,
                            function={
                                "name": partial.function.get("name", ""),
                                "arguments": partial.function.get("arguments", ""),
                            },
                        )
                    ],
                )
            )
        ]

    def _parse_message_delta_events(
        self,
        payload_dict: JsonObject,
    ) -> list[AssistantMessageEvent]:
        events: list[AssistantMessageEvent] = []
        message_delta_event = self._parse_message_delta(payload_dict)
        if message_delta_event is not None:
            events.append(message_delta_event)
        delta_obj = payload_dict.get("delta")
        if isinstance(delta_obj, dict):
            stop_reason_obj = delta_obj.get("stop_reason")
            if isinstance(stop_reason_obj, str):
                if stop_reason_obj == "tool_use":
                    stop_reason_obj = "toolUse"
                events.append(AssistantMessageEvent(finish_reason=stop_reason_obj))
        return events

    def _parse_event(  # noqa: PLR0911
        self,
        payload: str,
        partial_tool_calls: dict[int, ToolCall],
    ) -> list[AssistantMessageEvent]:
        payload_obj: JsonValue = json.loads(payload)
        if not isinstance(payload_obj, dict):
            return []
        payload_dict: JsonObject = payload_obj

        event_type_obj = payload_dict.get("type")
        if not isinstance(event_type_obj, str):
            return []
        if event_type_obj == "content_block_delta":
            return self._parse_content_block_delta(payload_dict, partial_tool_calls)
        if event_type_obj == "content_block_start":
            return self._parse_content_block_start(payload_dict, partial_tool_calls)
        if event_type_obj == "content_block_stop":
            return self._parse_content_block_stop(payload_dict, partial_tool_calls)
        if event_type_obj == "message_delta":
            return self._parse_message_delta_events(payload_dict)
        if event_type_obj == "message_stop":
            return [AssistantMessageEvent(finish_reason="stop")]
        return []

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
