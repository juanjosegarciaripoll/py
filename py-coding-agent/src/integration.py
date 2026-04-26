"""Integration bridge between py-coding-agent, py-agent, and llm-providers."""

from __future__ import annotations

import importlib
import importlib.util
import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal, Protocol, cast, runtime_checkable

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

type RuntimeBackend = Literal["echo", "agent"]
type RuntimeProvider = Literal["echo", "openai", "anthropic", "openai_compatible"]


class _AgentModelLike(Protocol):
    id: str


class _AgentContextLike(Protocol):
    system_prompt: str
    messages: list[object]
    tools: list[object]


@runtime_checkable
class _ProviderLike(Protocol):
    def stream(
        self,
        model: str,
        system_prompt: str,
        messages: list[object],
        tools: list[object],
    ) -> AsyncIterator[object]: ...


@runtime_checkable
class _AssistantMessageLike(Protocol):
    stop_reason: str


class AgentRuntimeError(RuntimeError):
    """Raised when integrated runtime initialization or execution fails."""


@dataclass(slots=True, frozen=True)
class RuntimeModelConfig:
    """Runtime provider/model configuration for integrated execution."""

    backend: RuntimeBackend = "echo"
    provider: RuntimeProvider = "echo"
    model: str = "echo-1"
    api_key_env: str | None = None
    base_url: str | None = None


class _SingleResultStream:
    def __init__(self, event: object, message: object) -> None:
        self._event = event
        self._message = message

    async def __aiter__(self):  # type: ignore[no-untyped-def]
        yield self._event

    async def result(self) -> object:
        return self._message


class _EchoProvider:
    """Local provider used for offline integration and deterministic behavior."""

    async def stream(
        self,
        model: str,
        system_prompt: str,
        messages: list[object],
        tools: list[object],
    ) -> AsyncIterator[dict[str, str]]:
        _ = model
        _ = system_prompt
        _ = tools
        prompt = _last_user_text(messages)
        text = f"Echo: {prompt}" if prompt else "Echo: (empty prompt)"
        yield {"type": "text", "text": text}
        yield {"type": "finish", "reason": "stop"}


@dataclass(slots=True)
class _AssistantBuildState:
    text_parts: list[str]
    tool_calls: dict[str, tuple[str, str]]
    stop_reason: str = "stop"
    usage_input: int = 0
    usage_output: int = 0


class AgenticResponder:
    """Thin facade that executes prompts through py-agent + llm-providers."""

    def __init__(self, model_config: RuntimeModelConfig) -> None:
        self._config = model_config
        self._py_agent = _load_workspace_package(
            package_name="_py_workspace_agent",
            package_root=Path(__file__).resolve().parents[2] / "py-agent" / "src",
        )
        self._llm_providers = _load_workspace_package(
            package_name="_py_workspace_llm_providers",
            package_root=Path(__file__).resolve().parents[2] / "llm-providers" / "src",
        )
        self._llm_types = importlib.import_module("_py_workspace_llm_providers.types")
        self._py_agent_types = importlib.import_module("_py_workspace_agent.types")
        self._provider: _ProviderLike = self._build_provider()

    async def respond(self, prompt: str, *, system_prompt: str) -> str:
        """Run one prompt through py-agent and return final assistant text."""
        model = self._py_agent.AgentModel(
            id=self._config.model,
            api="llm-providers",
            provider=self._config.provider,
            name=self._config.model,
        )
        options = self._py_agent.AgentOptions(
            initial_model=model,
            initial_system_prompt=system_prompt,
            stream_fn=self._stream_fn,
        )
        agent = self._py_agent.Agent(options)
        await agent.prompt(prompt)
        for message in reversed(agent.state.messages):
            if isinstance(message, self._py_agent_types.AssistantMessage):
                return _extract_assistant_text(message.content)
        return ""

    @property
    def llm_types(self) -> Any:
        """Expose loaded llm-providers module for integration customization."""
        return self._llm_types

    def set_provider(self, provider: _ProviderLike) -> None:
        """Override provider implementation."""
        self._provider = provider

    async def _stream_fn(
        self,
        model: _AgentModelLike,
        context: _AgentContextLike,
        config: object,
    ) -> _SingleResultStream:
        del config
        try:
            llm_messages = self._convert_messages(context.messages)
            llm_tools: list[object] = []
            events = self._provider.stream(
                model=model.id,
                system_prompt=str(context.system_prompt or ""),
                messages=llm_messages,
                tools=llm_tools,
            )
            assistant = await self._materialize_assistant(
                model=model,
                provider_events=events,
            )
            if not context.tools:
                assistant = _normalize_assistant_without_tools(
                    assistant,
                    types_module=self._py_agent_types,
                )
            done_event = self._py_agent_types.DoneEvent(
                reason=_to_done_reason(assistant.stop_reason),
                message=assistant,
            )
            return _SingleResultStream(done_event, assistant)
        except Exception as exc:  # noqa: BLE001
            failure = self._py_agent_types.AssistantMessage(
                content=[self._py_agent_types.TextContent(text="")],
                api="llm-providers",
                provider=self._config.provider,
                model=self._config.model,
                stop_reason="error",
                error_message=str(exc),
            )
            error_event = self._py_agent_types.ErrorEvent(reason="error", error=failure)
            return _SingleResultStream(error_event, failure)

    def _build_provider(self) -> _ProviderLike:
        if self._config.provider == "echo":
            return _EchoProvider()
        key_name = self._config.api_key_env
        api_key = "" if key_name is None else os.environ.get(key_name, "")
        if not api_key:
            msg = "Missing provider API key environment variable value."
            raise AgentRuntimeError(msg)
        providers_module = importlib.import_module(
            "_py_workspace_llm_providers.providers"
        )
        match self._config.provider:
            case "openai":
                return _require_provider(
                    providers_module.OpenAIProvider(api_key=api_key)
                )
            case "anthropic":
                return _require_provider(
                    providers_module.AnthropicProvider(api_key=api_key)
                )
            case "openai_compatible":
                if not self._config.base_url:
                    msg = "openai_compatible provider requires base_url."
                    raise AgentRuntimeError(msg)
                return _require_provider(
                    providers_module.OpenAICompatibleProvider(
                        api_key=api_key,
                        base_url=self._config.base_url,
                    )
                )

    def _convert_messages(self, messages: list[object]) -> list[object]:
        role = self._llm_types.Role
        llm_messages: list[object] = []
        for message in messages:
            message_role = getattr(message, "role", "")
            if message_role == "user":
                llm_messages.append(
                    self._llm_types.Message(
                        role=role.USER,
                        content=[
                            self._llm_types.TextContent(
                                type="text",
                                text=_message_text(message),
                            )
                        ],
                    )
                )
                continue
            if message_role == "assistant":
                tool_calls = _assistant_tool_calls(self._llm_types, message)
                llm_messages.append(
                    self._llm_types.Message(
                        role=role.ASSISTANT,
                        content=[
                            self._llm_types.TextContent(
                                type="text",
                                text=_message_text(message),
                            )
                        ],
                        tool_calls=tool_calls or None,
                    )
                )
                continue
            if message_role == "toolResult":
                llm_messages.append(
                    self._llm_types.Message(
                        role=role.TOOL,
                        content=[
                            self._llm_types.TextContent(
                                type="text",
                                text=_message_text(message),
                            )
                        ],
                        tool_call_id=getattr(message, "tool_call_id", None),
                    )
                )
        return llm_messages

    async def _materialize_assistant(
        self,
        *,
        model: _AgentModelLike,
        provider_events: AsyncIterator[object],
    ) -> _AssistantMessageLike:
        state = _AssistantBuildState(text_parts=[], tool_calls={})
        async for event in provider_events:
            event_dict = _as_str_object_mapping(event)
            if event_dict is not None:
                _consume_dict_event(event_dict, state=state)
                continue
            _consume_provider_event(event, state=state)
        content: list[object] = []
        if state.text_parts:
            content.append(
                self._py_agent_types.TextContent(text="".join(state.text_parts))
            )
        for tool_id, (name, raw_arguments) in state.tool_calls.items():
            content.append(
                self._py_agent_types.ToolCallContent(
                    id=tool_id,
                    name=name,
                    arguments=_parse_json_object(raw_arguments),
                )
            )
        usage = self._py_agent_types.Usage(
            input=state.usage_input,
            output=state.usage_output,
            total_tokens=state.usage_input + state.usage_output,
        )
        message = self._py_agent_types.AssistantMessage(
            content=content,
            api="llm-providers",
            provider=self._config.provider,
            model=str(model.id),
            usage=usage,
            stop_reason=_to_agent_stop_reason(state.stop_reason),
        )
        return _require_assistant_message(message)


def _load_workspace_package(package_name: str, package_root: Path) -> Any:
    module = sys.modules.get(package_name)
    if module is not None:
        return module
    init_path = package_root / "__init__.py"
    if not init_path.is_file():
        msg = f"Workspace package not found: {package_root}"
        raise AgentRuntimeError(msg)
    spec = importlib.util.spec_from_file_location(
        package_name,
        init_path,
        submodule_search_locations=[str(package_root)],
    )
    if spec is None or spec.loader is None:
        msg = f"Unable to load workspace package: {package_root}"
        raise AgentRuntimeError(msg)
    loaded = importlib.util.module_from_spec(spec)
    sys.modules[package_name] = loaded
    spec.loader.exec_module(loaded)
    return loaded


def _parse_json_object(raw: str) -> dict[str, object]:
    try:
        decoded: object = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    mapping = _as_object_dict(decoded)
    if mapping is not None:
        return {key: value for key, value in mapping.items() if isinstance(key, str)}
    return {}


def _extract_assistant_text(content: list[object]) -> str:
    chunks: list[str] = []
    for item in content:
        text = getattr(item, "text", None)
        if isinstance(text, str):
            chunks.append(text)
    return "".join(chunks)


def _message_text(message: object) -> str:
    content: object = getattr(message, "content", "")
    if isinstance(content, str):
        return content
    content_list = _as_object_list(content)
    if content_list is not None:
        parts: list[str] = []
        for item_obj in content_list:
            text = getattr(item_obj, "text", None)
            if isinstance(text, str):
                parts.append(text)
        return "".join(parts)
    return ""


def _assistant_tool_calls(llm_module: Any, message: object) -> list[object]:
    calls: list[object] = []
    raw_content: object = getattr(message, "content", [])
    content_list = _as_object_list(raw_content)
    if content_list is None:
        return calls
    for item_obj in content_list:
        item_type = getattr(item_obj, "type", "")
        if item_type != "toolCall":
            continue
        calls.append(
            llm_module.ToolCall(
                id=str(getattr(item_obj, "id", "")),
                function={
                    "name": str(getattr(item_obj, "name", "")),
                    "arguments": json.dumps(getattr(item_obj, "arguments", {})),
                },
            )
        )
    return calls


def _last_user_text(messages: list[object]) -> str:
    for message in reversed(messages):
        role = getattr(message, "role", "")
        if str(role).lower() in {"role.user", "user"}:
            content: object = getattr(message, "content", [])
            content_list = _as_object_list(content)
            if content_list is not None:
                parts: list[str] = []
                for item_obj in content_list:
                    text = getattr(item_obj, "text", None)
                    if isinstance(text, str):
                        parts.append(text)
                return "".join(parts).strip()
    return ""


def _to_agent_stop_reason(reason: str) -> str:
    if reason == "toolUse":
        return "toolUse"
    if reason in {"stop", "length", "error", "aborted"}:
        return reason
    return "stop"


def _to_done_reason(stop_reason: str) -> str:
    if stop_reason in {"stop", "length", "toolUse"}:
        return stop_reason
    return "stop"


def _normalize_assistant_without_tools(
    assistant: _AssistantMessageLike,
    *,
    types_module: Any,
) -> _AssistantMessageLike:
    """Prevent retry loops for tool calls when no tools are configured."""
    content_items = _as_object_list(getattr(assistant, "content", [])) or []
    normalized_content = [
        item for item in content_items if getattr(item, "type", "") != "toolCall"
    ]
    stop_reason_obj = getattr(assistant, "stop_reason", "stop")
    stop_reason = str(stop_reason_obj)
    normalized_stop_reason = "stop" if stop_reason == "toolUse" else stop_reason
    if (
        normalized_stop_reason == stop_reason
        and len(normalized_content) == len(content_items)
    ):
        return assistant
    rebuilt = types_module.AssistantMessage(
        content=normalized_content,
        api=str(getattr(assistant, "api", "llm-providers")),
        provider=str(getattr(assistant, "provider", "unknown")),
        model=str(getattr(assistant, "model", "unknown")),
        response_id=getattr(assistant, "response_id", None),
        usage=getattr(assistant, "usage", None),
        stop_reason=_to_agent_stop_reason(normalized_stop_reason),
        error_message=getattr(assistant, "error_message", None),
        timestamp=int(getattr(assistant, "timestamp", 0) or 0),
    )
    return _require_assistant_message(rebuilt)


def _consume_dict_event(
    event: dict[str, object],
    *,
    state: _AssistantBuildState,
) -> None:
    event_type = event.get("type")
    if event_type == "text":
        text_value = event.get("text")
        if isinstance(text_value, str):
            state.text_parts.append(text_value)
        return
    if event_type == "finish":
        reason = event.get("reason")
        if isinstance(reason, str):
            state.stop_reason = reason


def _consume_provider_event(event: object, *, state: _AssistantBuildState) -> None:
    _consume_finish_reason(event, state=state)
    _consume_usage(event, state=state)
    delta = getattr(event, "delta", None)
    if delta is None:
        return
    delta_content = _as_object_list(getattr(delta, "content", []))
    if delta_content is not None:
        _consume_delta_content(delta_content, state=state)
    delta_tool_calls = _as_object_list(getattr(delta, "tool_calls", []))
    if delta_tool_calls is None:
        return
    _consume_delta_tool_calls(delta_tool_calls, state=state)


def _consume_finish_reason(event: object, *, state: _AssistantBuildState) -> None:
    finish_reason = getattr(event, "finish_reason", None)
    if isinstance(finish_reason, str):
        state.stop_reason = finish_reason


def _consume_usage(event: object, *, state: _AssistantBuildState) -> None:
    usage = getattr(event, "usage", None)
    if usage is None:
        return
    input_tokens = getattr(usage, "input_tokens", None)
    output_tokens = getattr(usage, "output_tokens", None)
    if isinstance(input_tokens, int):
        state.usage_input = input_tokens
    if isinstance(output_tokens, int):
        state.usage_output = output_tokens


def _consume_delta_content(
    delta_content: list[object],
    *,
    state: _AssistantBuildState,
) -> None:
    for block in delta_content:
        text_value = getattr(block, "text", None)
        if isinstance(text_value, str):
            state.text_parts.append(text_value)


def _consume_delta_tool_calls(
    tool_calls: list[object],
    *,
    state: _AssistantBuildState,
) -> None:
    for tool_call_obj in tool_calls:
        tool_id = getattr(tool_call_obj, "id", "")
        if not tool_id:
            continue
        function_obj: object = getattr(tool_call_obj, "function", {})
        name = ""
        arguments = "{}"
        function_map = _as_object_dict(function_obj)
        if function_map is not None:
            name_obj = function_map.get("name", "")
            arguments_obj = function_map.get("arguments", "{}")
            if isinstance(name_obj, str):
                name = name_obj
            if isinstance(arguments_obj, str):
                arguments = arguments_obj
        state.tool_calls[tool_id] = (name, arguments)


def _require_provider(candidate: object) -> _ProviderLike:
    if isinstance(candidate, _ProviderLike):
        return candidate
    msg = "Provider does not implement required stream interface."
    raise AgentRuntimeError(msg)


def _require_assistant_message(candidate: object) -> _AssistantMessageLike:
    if isinstance(candidate, _AssistantMessageLike):
        return candidate
    msg = "Assistant message object does not expose stop_reason."
    raise AgentRuntimeError(msg)


def _as_str_object_mapping(value: object) -> dict[str, object] | None:
    if not isinstance(value, dict):
        return None
    result: dict[str, object] = {}
    for key, item in cast("dict[object, object]", value).items():
        if not isinstance(key, str):
            return None
        result[key] = item
    return result


def _as_object_list(value: object) -> list[object] | None:
    if not isinstance(value, list):
        return None
    return list(cast("list[object]", value))


def _as_object_dict(value: object) -> dict[object, object] | None:
    if not isinstance(value, dict):
        return None
    return dict(cast("dict[object, object]", value))
