# llm-providers

`llm-providers` is the Python package that encapsulates LLM API integrations for this workspace.
It provides a shared provider interface, common message/tool types, and concrete provider implementations.

## Goals

- Keep provider logic isolated from agent/runtime code.
- Offer a consistent streaming API across vendors.
- Maintain strict typing with minimal dependencies.

## Package Layout

- `llm_providers.types`: Provider stream-facing dataclasses and JSON typing aliases.
- `llm_providers.communication`: Unified communication schema (Pydantic models), event stream protocol, serialization, handoff/normalization utilities.
- `llm_providers.provider`: Single abstract `Provider` base class with message-conversion dispatch hooks.
- `llm_providers.api_registry`: Provider registry and API-key helper.
- `llm_providers.auth`: API key store + OAuth token models/store.
- `llm_providers.config`: Pydantic provider configuration models.
- `llm_providers.model_registry`, `llm_providers.generated_models`, `llm_providers.models`: Model metadata registry.
- `llm_providers.tui`: Interactive provider configuration helper.
- `llm_providers.providers.anthropic`: Anthropic streaming + message/tool conversion.
- `llm_providers.providers.openai`: OpenAI chat-completions streaming + message/tool conversion.
- `llm_providers.providers.openai_compatible`: OpenAI-compatible provider (inherits OpenAI behavior, custom base URL).

## Core Interfaces

### Provider API

All providers implement:

- `Provider.stream(model, system_prompt, messages, tools) -> AsyncIterator[AssistantMessageEvent]`
- `Provider.check_model_access(model) -> tuple[bool, str | None]`

Message conversion is standardized in the same base class:

- `Provider.convert_messages(messages) -> list[dict[str, object]]`
- `Provider.convert_message(message) -> dict[str, object] | None` (default role-dispatch)
- `Provider.convert_tool_message(...)` and `Provider.convert_non_tool_message(...)` (provider-specific hooks)

### Communication API

`llm_providers.communication` defines unified multi-provider message/event models:

- Messages: `UserMessage`, `AssistantMessage`, `ToolResultMessage`, `Context`
- Events: `start`, `text_*`, `thinking_*`, `toolcall_*`, `done`, `error`
- Helpers: streaming JSON repair/parsing, tool-call ID normalization, context overflow detection, cross-provider handoff transformation

## Basic Usage

```python
from llm_providers.providers.openai import OpenAIProvider
from llm_providers.types import Message, Role, TextContent

provider = OpenAIProvider(api_key="...")
messages = [
    Message(role=Role.USER, content=[TextContent(type="text", text="Hello")]),
]

async for event in provider.stream(
    model="gpt-4o-mini",
    system_prompt="You are helpful.",
    messages=messages,
    tools=[],
):
    if event.delta:
        print(event.delta.content)
```

## Validation

From the repository root:

```bash
uv run --no-cache ruff check llm-providers
uv run --no-cache basedpyright llm-providers
uv run --no-cache mypy llm-providers
uv run --no-cache python -m unittest discover -s llm-providers/tests -v
```

## Notes

- Current built-in providers are Anthropic, OpenAI, and OpenAI-compatible.
- `Provider` conversion hooks are intended to keep vendor-specific payload differences localized.
- Tests focus on public APIs and include provider streaming, conversion behavior, config/auth, registry, and communication helper coverage.
